"""One owned h3.c process, with framed requests and native (single-entry) caches.

No model loading at import/status. Different projects get separate lifetimes;
only one process may live at a time. Stop/error/model-switch releases all RAM.
"""
import hashlib
import json
import os
from pathlib import Path
from portable_paths import BACKENDS
import select
import subprocess
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime

import task_diagnostics

WORKER = BACKENDS / 'H3C-Metal部署/source/h3-worker'
_guard = threading.RLock()
_serial = threading.Lock()
_worker = None
PREFIX = b'@h3-worker@'


class Worker:
    def __init__(self, key, command, cwd, env):
        self.key = key
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        start_new_session=True, bufsize=0)
        os.set_blocking(self.process.stdout.fileno(), False)
        self.buffer = b''
        self.ready = False
        self.features = []
        self.busy = False
        self.cache = {}
        self.inputs = {}
        self.requests = 0
        self.performance = None

    def receive(self):
        chunks = []
        # Bound draining so cancellation and memory checks cannot be starved.
        for _ in range(16):
            try:
                chunk = os.read(self.process.stdout.fileno(), 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        raw = b''.join(chunks)
        self.buffer += raw
        if len(self.buffer) > 2 * 1024 * 1024:
            raise RuntimeError('H3 常驻进程输出过长且未分行')
        lines = self.buffer.split(b'\n')
        self.buffer = lines.pop()
        events = []
        for line in lines:
            if PREFIX in line:
                _, _, data = line.partition(PREFIX)
                try:
                    event = json.loads(data)
                    if not isinstance(event, dict):raise ValueError('not object')
                except (ValueError, UnicodeError) as error:
                    raise RuntimeError('H3 常驻进程协议响应损坏') from error
                events.append(event)
        return raw, events

    def send(self, request):
        data = (json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n').encode()
        if len(data) > 1024 * 1024:
            raise ValueError('H3 请求超过 1 MiB')
        # FileIO.write may be short for large prompts; never split logical requests.
        view = memoryview(data)
        while view:
            n = self.process.stdin.write(view)
            if not n:raise RuntimeError('H3 常驻进程输入已关闭')
            view = view[n:]


def state():
    with _guard:
        worker = _worker
        if worker is None or worker.process.poll() is not None:
            return {'running': False, 'busy': False, 'pid': None, 'cache': {}}
        return {'running': True, 'busy': worker.busy, 'pid': worker.process.pid,
                'cache': dict(worker.cache), 'completed_requests': worker.requests}


def stop():
    global _worker
    import h3_native as native
    with _guard:
        worker = _worker
        if worker is None:return
        # Keep ownership if stopping fails, so a second worker cannot be launched.
        native.stop_process(worker.process)
        for stream in (worker.process.stdin, worker.process.stdout):
            if stream:stream.close()
        _worker = None


def fingerprints(paths, check_cancel):
    result = {}
    for item in paths:
        if item is None:continue
        path = Path(item).resolve()
        before = path.stat()
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                check_cancel();digest.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise RuntimeError('参考素材在准备过程中发生变化，请重试')
        result[str(path)] = digest.hexdigest()
    return result


def generate(*, prompt, references, width, height, duration, steps, seed, output,
             log_path, ffmpeg, check_cancel, on_progress, streaming, swap_limit_gib,
             stall_minutes, first_frame, last_frame, media_references,
             refine_source=None, refine_denoise=.05, layers=50, reuse=1, reference_video_max_pixels=0):
    global _worker
    import h3_native as native
    if not _serial.acquire(blocking=False):
        raise RuntimeError('H3 常驻进程已有生成任务')
    worker = None
    started = time.monotonic()
    output, log_path = Path(output).resolve(), Path(log_path).resolve()
    diagnostic_path = log_path.with_suffix('.diagnostics.json')
    performance = dict(layers=layers,reuse=reuse,reference_video_max_pixels=reference_video_max_pixels)
    diagnostic = {**performance,'started_at': datetime.now().isoformat(timespec='seconds'),
                  'status': 'starting', 'resident': True, 'ssd_streaming': streaming,
                  'width': width, 'height': height, 'duration': duration, 'steps': steps,
                  'reference_count': len(references) + len(media_references),
                  'first_frame': str(first_frame) if first_frame else None,
                  'last_frame': str(last_frame) if last_frame else None,
                  'generation_mode': 'omni_reference' if references or media_references else
                                     'first_frame' if first_frame or last_frame else 'text',
                  'log_path': str(log_path), 'stage': 'prepare', 'cache_hits': [],
                  'refine_source': str(refine_source) if refine_source else None,
                  'refine_denoise': refine_denoise if refine_source else None,
                  'swap_limit_mb': swap_limit_gib * 1024,
                  'swap_warning_mb': min(4096, swap_limit_gib * 512),
                  'swap_scope': 'whole_system', 'stall_timeout_seconds': stall_minutes * 60}
    samples = deque(maxlen=40)
    peak_kib = 0
    try:
        check_cancel()
        if output.exists():raise ValueError('H3 输出路径已存在，拒绝覆盖已有文件')
        if not WORKER.is_file() or not os.access(WORKER, os.X_OK):
            raise RuntimeError('H3 常驻程序未就绪，请构建 h3-worker')
        output.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        inputs = fingerprints([*references, first_frame, last_frame, refine_source,
                               *[r['path'] for r in media_references]], check_cancel)
        project_root = output.parent.parent
        temp = project_root / 'temp/h3'
        temp.mkdir(parents=True, exist_ok=True)
        signature = WORKER.stat()
        key = (str(project_root), str(native.MODELS), str(ffmpeg),
               signature.st_mtime_ns, signature.st_size)
        baseline = native.swap_mb()
        diagnostic.update(swap_start_mb=baseline, swap_peak_mb=baseline)
        task_diagnostics.write(diagnostic_path, diagnostic)
        with _guard:
            if _worker and (_worker.key != key or _worker.process.poll() is not None):stop()
            reused = _worker is not None
            if _worker is None:
                env = {**os.environ, 'H3_FFMPEG': str(ffmpeg), 'H3_FFPROBE': str(native.FFPROBE),
                       'TMPDIR': str(temp)}
                _worker = Worker(key, [str(WORKER), str(native.MODELS)], native.BINARY.parent, env)
            worker = _worker
            worker.busy = True
        request_id = uuid.uuid4().hex
        request = {**performance,'command': 'generate', 'id': request_id, 'prompt': prompt,
                   'width': width, 'height': height, 'seconds': duration, 'steps': steps,
                   'seed': seed, 'ssd_streaming': streaming, 'output': str(output),
                   'refine_source': str(Path(refine_source).resolve()) if refine_source else None,
                   'refine_denoise': refine_denoise if refine_source else None,
                   'first_frame': str(Path(first_frame).resolve()) if first_frame else None,
                   'last_frame': str(Path(last_frame).resolve()) if last_frame else None,
                   'references': [{'kind': 'image', 'path': str(Path(p).resolve())} for p in references] +
                                 [{'kind': r['kind'], 'path': str(Path(r['path']).resolve())} for r in media_references],
                   # Hashes also catch same-path rewrites with preserved size/mtime.
                   'clear_cache': (worker.performance is not None and worker.performance != performance) or
                       any(p in worker.inputs and worker.inputs[p] != digest for p, digest in inputs.items())}
        diagnostic.update(pid=worker.process.pid, request_id=request_id, process_reused=reused,
                          cache_invalidated=request['clear_cache'], status='running')
        last_progress = started
        last_check = last_diagnostic = 0
        sent = False
        complete = None
        log_tail = ''
        with log_path.open('wb') as log:
            while complete is None:
                check_cancel()
                raw, events = worker.receive()
                if raw:
                    log.write(raw);log.flush()
                    last_progress = time.monotonic()
                    lines = raw.decode(errors='replace').replace('\r', '\n').splitlines()
                    plain = [line for line in lines if line.strip() and '@h3-worker@' not in line]
                    if plain:diagnostic['stage'] = plain[-1][-250:]
                    cache_text = log_tail + raw.decode(errors='replace')
                    for label in ('conditioning', 'prepared DiT', 'video VAE'):
                        if label + ' cache hit' in cache_text and label not in diagnostic['cache_hits']:
                            diagnostic['cache_hits'].append(label)
                    log_tail = cache_text[-80:]
                for event in events:
                    if event.get('event') == 'ready':
                        if event.get('protocol') != 1 or event.get('validate_only'):
                            raise RuntimeError('H3 常驻协议版本不兼容')
                        worker.ready = True
                        worker.features = event.get('features',[])
                        continue
                    if event.get('id') != request_id:
                        raise RuntimeError('H3 常驻响应与当前镜头不匹配')
                    if event.get('event') == 'error':raise RuntimeError('h3.c：' + event.get('message', '生成失败'))
                    if event.get('event') == 'progress':
                        diagnostic['stage'] = f"{event['phase']} {event['completed']}/{event['total']}"
                    elif event.get('event') == 'done':complete = event
                if worker.ready and not sent:
                    if performance != dict(layers=50,reuse=1,reference_video_max_pixels=0) and 'performance_controls_v1' not in worker.features:
                        raise RuntimeError('H3 程序尚未部署 D 档接口，未发送生成请求；请完成部署后重试')
                    if refine_source and 'face_refine' not in worker.features:
                        raise RuntimeError('H3 常驻程序尚未更新面部精修接口')
                    check_cancel();worker.send(request);sent = True
                now = time.monotonic()
                if now - last_check >= 3:
                    last_check = now
                    rss = native.subprocess.run(['/bin/ps', '-p', str(worker.process.pid), '-o', 'rss='],
                                                capture_output=True, text=True).stdout.strip()
                    if rss.isdigit():peak_kib = max(peak_kib, int(rss))
                    current = native.swap_mb()
                    delta = current - baseline
                    diagnostic.update(swap_last_mb=current, swap_delta_mb=round(delta, 2),
                                      swap_peak_mb=max(current, diagnostic['swap_peak_mb']))
                    samples.append({'elapsed': round(now-started, 2), 'swap_mb': current,
                                    'rss_kib': int(rss) if rss.isdigit() else None})
                    if delta > diagnostic['swap_limit_mb']:
                        diagnostic['swap_protection_triggered'] = True
                        raise RuntimeError(f'交换内存保护触发：新增 {delta/1024:.1f} GiB，超过 {swap_limit_gib} GiB；已请求释放 H3 缓存')
                    diagnostic['swap_warning_active'] = delta >= diagnostic['swap_warning_mb']
                idle = now-last_progress
                diagnostic.update(no_progress_seconds=round(idle, 1), elapsed=round(now-started, 2))
                message = native.progress_message(diagnostic['stage'], idle, stall_minutes*60)
                if diagnostic.get('swap_warning_active'):message += ' · 内存提醒：交换量增加'
                on_progress(message)
                if now-last_diagnostic >= 15:
                    last_diagnostic = now
                    diagnostic.update(peak_rss_gib=round(peak_kib/1024**2, 2), samples=list(samples))
                    task_diagnostics.write(diagnostic_path, diagnostic)
                if complete is not None:break
                if worker.process.poll() is not None:
                    raise RuntimeError(f'H3 常驻进程提前退出（{worker.process.returncode}），请查看本段日志')
                select.select([worker.process.stdout], [], [], .25)
        check_cancel()
        if complete.get('output') != str(output) or not output.is_file() or not output.stat().st_size:
            raise RuntimeError('H3 返回的输出路径不匹配或视频文件为空')
        with _guard:
            worker.cache = complete.get('cache', {})
            worker.inputs = inputs
            worker.performance = performance
            worker.requests += 1
            worker.busy = False
        diagnostic.update(status='done', cache=worker.cache, worker_retained=True)
        return {**performance,'backend': 'h3c', 'resident': True, 'worker_pid': worker.process.pid,
                'process_reused': reused, 'cache_hits': diagnostic['cache_hits'], 'cache': worker.cache,
                'seconds': round(time.monotonic()-started, 2), 'peak_rss_gib': round(peak_kib/1024**2, 2),
                'variant': 'Ref2VA' if references or media_references else 'FL2VA',
                'generation_mode': diagnostic['generation_mode'], 'ssd_streaming': streaming}
    except BaseException as error:
        diagnostic.update(status='error', error_type=type(error).__name__, error=str(error),
                          traceback=traceback.format_exc(), worker_retained=False)
        if worker:task_diagnostics.cleanup(stop)
        diagnostic.update(traceback=traceback.format_exc(),
                          worker_retained=bool(worker and worker.process.poll() is None))
        raise
    finally:
        try:
            try:diagnostic['swap_end_mb'] = native.swap_mb()
            except Exception as error:diagnostic['swap_end_error'] = str(error)
            diagnostic.update(ended_at=datetime.now().isoformat(timespec='seconds'),
                              elapsed=round(time.monotonic()-started, 2), peak_rss_gib=round(peak_kib/1024**2, 2),
                              samples=list(samples), exit_code=worker.process.poll() if worker else None)
            task_diagnostics.write(diagnostic_path, diagnostic)
        finally:_serial.release()
