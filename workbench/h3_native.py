"""Native H3 process boundary; no model is loaded at import or status time."""
import os
import json
from pathlib import Path
from portable_paths import BACKENDS
import re
import signal
import shutil
import subprocess
import threading
import time
import traceback
from datetime import datetime
from collections import deque
import task_diagnostics
import video_modes
import h3_resident
import h3_performance

DEPLOY = BACKENDS / "H3C-Metal部署"
BINARY = DEPLOY / "source/h3"
MODELS = DEPLOY / "models/MiniMax-H3"
FFPROBE = Path(os.environ.get("JINGLIU_FFPROBE") or shutil.which("ffprobe") or DEPLOY / "tools/node_modules/@ffprobe-installer/darwin-arm64/ffprobe")
_processes = set()
_lock = threading.Lock()


def running_pids():
    with _lock:
        pids = [p.pid for p in _processes if p.poll() is None]
    resident = h3_resident.state()
    return pids + ([resident['pid']] if resident['running'] else [])


def progress_message(stage, idle_seconds, stall_seconds):
    if idle_seconds >= stall_seconds:
        raise RuntimeError(f'H3 连续 {stall_seconds // 60} 分钟没有新进度，已停止并释放模型；最后阶段：{stage}。请降低尺寸或缩短镜头后重试，已完成作品保留。')
    if idle_seconds >= 120:
        return stage + f' · 已 {int(idle_seconds)} 秒无新进度（{stall_seconds // 60} 分钟保护）'
    return stage


def status():
    missing = []
    for label, path in (("h3.c 程序", BINARY), ("H3 常驻程序", h3_resident.WORKER), ("FFprobe", FFPROBE)):
        if not path.is_file() or not os.access(path, os.X_OK):
            missing.append(label)
    variants = {}
    for name in ("FL2VA", "Ref2VA"):
        root = MODELS / name
        variants[name] = all((root / part).exists() for part in (
            "transformer/model.safetensors.index.json",
            "text_encoder/model.safetensors.index.json", "tokenizer/tokenizer.json",
            "video_vae/source/model.safetensors", "audio_vae/model.safetensors"))
        if variants[name]:
            try:
                for part in ('transformer','text_encoder'):
                    index=json.loads((root/part/'model.safetensors.index.json').read_text())
                    shards=set(index['weight_map'].values())
                    if not shards or not all((root/part/shard).is_file() for shard in shards):variants[name]=False
            except (OSError,ValueError,KeyError,TypeError):variants[name]=False
        if not variants[name]:missing.append(name+' 模型文件')
    return {"ready":not missing and all(variants.values()), "missing":missing,
            "variants":variants, "binary":str(BINARY), "model_dir":str(MODELS),
            "resident":h3_resident.state(), "worker_binary":str(h3_resident.WORKER)}


def stop_process(process):
    if process.poll() is not None:return
    def send(sig):
        try:os.killpg(process.pid,sig)
        except (ProcessLookupError,PermissionError):
            if process.poll() is not None:return
            # Only target the owned child; never signal an unrelated process.
            process.send_signal(sig)
    send(signal.SIGTERM)
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)
        process.wait(timeout=5)


def stop_all():
    h3_resident.stop()
    with _lock:processes=list(_processes)
    for process in processes:task_diagnostics.cleanup(lambda:stop_process(process))


def swap_mb():
    result=subprocess.run(["/usr/sbin/sysctl","-n","vm.swapusage"],capture_output=True,text=True)
    match=re.search(r"used\s*=\s*([\d.]+)M",result.stdout)
    if result.returncode or not match:raise RuntimeError('无法读取系统交换内存，未能验证 SSD 保护阈值')
    return float(match[1])


def generate(*, prompt, references, width, height, duration, steps, seed,
             output, log_path, ffmpeg, check_cancel, on_progress, streaming=False, swap_limit_gib=8,
             stall_minutes=10, first_frame=None, last_frame=None, media_references=None, resident=True,
             refine_source=None, refine_denoise=.05, layers=50, reuse=1, reference_video_max_pixels=0):
    performance=h3_performance.validate(layers,reuse,reference_video_max_pixels,steps)
    if type(resident) is not bool:raise ValueError('H3 常驻缓存须为开关')
    if refine_source:
        if not resident or not Path(refine_source).is_file():raise ValueError('面部精修需要常驻协议和有效的裁剪视频')
        if type(refine_denoise) not in (float,int) or not .01<=refine_denoise<=.15:raise ValueError('精修重绘幅度须为0.01–0.15')
    if type(streaming) is not bool or type(stall_minutes) is not int or not 5<=stall_minutes<=60:
        raise ValueError('逐层加载须为开关，无进度停止时间须为 5–60 分钟整数')
    if type(swap_limit_gib) is not int or not 2<=swap_limit_gib<=30:
        raise ValueError('交换内存新增停止阈值须为 2–30 GiB 的整数')
    swap_limit_mb=swap_limit_gib*1024
    swap_warning_mb=min(4096,swap_limit_mb/2)
    state=status()
    if not state["ready"]:raise ValueError("h3.c 部署不完整："+str(state))
    if len(references)>9:raise ValueError("h3.c 每段最多 9 张参考图（包括上一段尾帧）")
    if width%32 or height%32 or width*height>768*1344:raise ValueError("h3.c 尺寸须为 32 的倍数，且不超过 1344×768 的像素数")
    if not 0<duration<=15 or not 4<=steps<=50:raise ValueError("h3.c 时长或步数超出范围")
    for ref in references:
        if not Path(ref).is_file():raise ValueError("参考图不存在："+str(ref))
    media_references=[dict(r) for r in (media_references or [])]
    if (references or media_references) and (first_frame or last_frame):
        raise ValueError('首尾帧模式不能同时传入全能参考素材')
    for frame in (first_frame,last_frame):
        if frame and (Path(frame).suffix.lower() not in video_modes.IMAGE_EXTENSIONS or not Path(frame).is_file()):
            raise ValueError('首尾帧图片不存在或格式错误：'+str(frame))
    for ref in media_references:
        if ref.get('kind') not in {'video','silent_video','audio'}:raise ValueError('参考媒体类型不支持')
        ref.update(video_modes.probe(ref['path'],ref['kind'],FFPROBE))
    video_modes.validate_references([{'kind':'image'} for _ in references]+media_references)
    if resident:
        return h3_resident.generate(prompt=prompt,references=references,width=width,height=height,
            duration=duration,steps=steps,seed=seed,output=output,log_path=log_path,ffmpeg=ffmpeg,
            check_cancel=check_cancel,on_progress=on_progress,streaming=streaming,
            swap_limit_gib=swap_limit_gib,stall_minutes=stall_minutes,first_frame=first_frame,
            last_frame=last_frame,media_references=media_references,
            refine_source=refine_source,refine_denoise=refine_denoise,**performance)
    h3_resident.stop()
    selected='first_frame' if first_frame or last_frame else 'omni_reference' if references or media_references else 'text'
    command=[str(BINARY),"--profile","-d",str(MODELS),"-p",prompt,
             "--width",str(width),"--height",str(height),"--seconds",str(duration),
             "--steps",str(steps),"--seed",str(seed),"--layers",str(layers),"--reuse",str(reuse),
             "--ref-video-max-pixels",str(reference_video_max_pixels),"-o",str(output)]
    for ref in references:command.extend(["--ref-image",str(ref)])
    for ref in media_references:
        command.extend([{'video':'--ref-video','silent_video':'--ref-silent-video','audio':'--ref-audio'}[ref['kind']],str(ref['path'])])
    if first_frame:command.extend(['--first-frame',str(first_frame)])
    if last_frame:command.extend(['--last-frame',str(last_frame)])
    if streaming:command.append("--ssd-streaming")
    env={**os.environ,"H3_FFMPEG":str(ffmpeg),"H3_FFPROBE":str(FFPROBE)}
    temp_root=Path(output).parent.parent/'temp'/'h3';temp_root.mkdir(parents=True,exist_ok=True)
    env['TMPDIR']=str(temp_root.resolve())
    Path(log_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();last_check=0;offset=0;peak_kib=0;process=None;baseline=None
    last_progress=started;last_diagnostic=started;stall_seconds=stall_minutes*60
    samples=deque(maxlen=40)
    diagnostic={**performance,'started_at':datetime.now().isoformat(timespec='seconds'),'status':'starting',
                'width':width,'height':height,'duration':duration,'steps':steps,
                'generation_mode':selected,'reference_count':len(references)+len(media_references),
                'first_frame':str(first_frame) if first_frame else None,'last_frame':str(last_frame) if last_frame else None,
                'swap_limit_mb':swap_limit_mb,'swap_warning_mb':swap_warning_mb,'swap_scope':'whole_system',
                'stage':'prepare','log_path':str(log_path),'ssd_streaming':streaming,
                'stall_timeout_seconds':stall_seconds}
    diagnostic_path=Path(log_path).with_suffix('.diagnostics.json')
    try:
        baseline=swap_mb();diagnostic.update(swap_start_mb=baseline,swap_peak_mb=baseline)
        task_diagnostics.write(diagnostic_path,diagnostic)
        try:
            check_cancel()
            with open(log_path,"wb") as log:
                process=subprocess.Popen(command,cwd=BINARY.parent,env=env,stdout=log,
                                         stderr=subprocess.STDOUT,start_new_session=True)
            with _lock:_processes.add(process)
            diagnostic.update(pid=process.pid,status='running')
            while process.poll() is None:
                check_cancel()
                if time.monotonic()-last_check>=3:
                    last_check=time.monotonic()
                    rss=subprocess.run(["/bin/ps","-p",str(process.pid),"-o","rss="],capture_output=True,text=True).stdout.strip()
                    if rss.isdigit():peak_kib=max(peak_kib,int(rss))
                    current=swap_mb();delta=current-baseline
                    diagnostic.update(swap_last_mb=current,swap_delta_mb=round(delta,2),swap_peak_mb=max(current,diagnostic['swap_peak_mb']))
                    samples.append({'elapsed':round(time.monotonic()-started,2),'swap_mb':current,'rss_kib':int(rss) if rss.isdigit() else None})
                    with open(log_path,"rb") as stream:
                        stream.seek(offset);chunk=stream.read(65536);offset=stream.tell()
                    lines=chunk.decode(errors="replace").replace("\r","\n").splitlines()
                    if lines:
                        diagnostic['stage']=lines[-1][-250:]
                        last_progress=time.monotonic()
                    idle_seconds=time.monotonic()-last_progress
                    diagnostic.update(no_progress_seconds=round(idle_seconds,1),elapsed=round(time.monotonic()-started,1))
                    if delta>swap_limit_mb:
                        diagnostic['swap_protection_triggered']=True
                        raise RuntimeError(f'交换内存保护触发：启动 {baseline:.0f} MB → 当前 {current:.0f} MB，新增 {delta:.0f} MB，超过 {swap_limit_mb} MB 阈值；已请求停止，现有结果保留。')
                    warning=f' · 内存提醒：交换新增 {delta/1024:.1f} GiB（{swap_limit_gib} GiB 才停止）' if delta>=swap_warning_mb else ''
                    diagnostic['swap_warning_active']=bool(warning)
                    message=progress_message(diagnostic['stage'],idle_seconds,stall_seconds)
                    on_progress(message+warning)
                    if time.monotonic()-last_diagnostic>=15:
                        diagnostic.update(peak_rss_gib=round(peak_kib/1024**2,2),samples=list(samples))
                        task_diagnostics.write(diagnostic_path,diagnostic)
                        last_diagnostic=time.monotonic()
                time.sleep(.25)
            check_cancel()
            if process.returncode or not Path(output).is_file():
                with open(log_path,"rb") as stream:
                    stream.seek(max(0,Path(log_path).stat().st_size-2000));detail=stream.read().decode(errors="replace")
                raise RuntimeError('h3.c 生成失败（退出码 '+str(process.returncode)+'）：'+detail)
        finally:
            if process:
                task_diagnostics.cleanup(lambda:stop_process(process))
                with _lock:
                    if process.poll() is not None:_processes.discard(process)
        diagnostic['status']='done'
        return {**performance,"backend":"h3c","seconds":round(time.monotonic()-started,2),
                "peak_rss_gib":round(peak_kib/1024**2,2),"variant":"Ref2VA" if references or media_references else "FL2VA",
                "generation_mode":selected,
                "ssd_streaming":streaming}
    except Exception as error:
        diagnostic.update(status='error',error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
        raise
    finally:
        try:diagnostic['swap_end_mb']=swap_mb()
        except Exception as error:diagnostic['swap_end_error']=str(error)
        diagnostic.update(ended_at=datetime.now().isoformat(timespec='seconds'),elapsed=round(time.monotonic()-started,2),
                          peak_rss_gib=round(peak_kib/1024**2,2),samples=list(samples),
                          exit_code=process.returncode if process else None)
        task_diagnostics.write(diagnostic_path,diagnostic)
