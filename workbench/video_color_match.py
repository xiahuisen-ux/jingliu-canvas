"""Local, temporally stable RGB histogram matching. No model or network calls."""
import bisect
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from PIL import Image, ImageChops
import video_choices

SAMPLE_COUNT = 12
SAMPLE_WIDTH, SAMPLE_HEIGHT = 192, 108
DEFAULTS = {'strength': 0.65, 'brightness': 0, 'contrast': 1, 'saturation': 1}
LIMITS = {'strength': (0, 1), 'brightness': (-0.2, 0.2),
          'contrast': (0.5, 1.5), 'saturation': (0, 2)}


def validate(st, p, payload):
    reference = payload.get('reference')
    if not isinstance(reference, dict):
        raise ValueError('请选择一个参考视频版本')
    ref = video_choices.assembly_clips(st, p, {'clips': [reference]})[0]
    if not payload.get('targets'):
        raise ValueError('请至少勾选一个其他段落进行色彩对齐')
    targets = video_choices.assembly_clips(st, p, {'clips': payload.get('targets')})
    if any(c['shot_id'] == ref['shot_id'] for c in targets):
        raise ValueError('参考段落保持原样，请只勾选其他需要对齐的段落')
    settings = payload.get('settings', {})
    if not isinstance(settings, dict) or set(settings) - set(DEFAULTS):
        raise ValueError('色彩调整参数格式错误')
    values = dict(DEFAULTS)
    for key, value in settings.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError('色彩调整参数必须是有效数字')
        low, high = LIMITS[key]
        if not low <= value <= high:
            raise ValueError(f'色彩调整参数 {key} 超出允许范围')
        values[key] = float(value)
    select = payload.get('select_results', True)
    if not isinstance(select, bool):
        raise ValueError('选用校色版参数格式错误')
    return ref, targets, values, select


def run_ffmpeg(st, command, folder):
    """Relative LUT names avoid filter-parser escaping of user folder names."""
    st.check_cancel()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, cwd=folder, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            while process.poll() is None:
                st.check_cancel(); time.sleep(0.1)
            if process.returncode:
                errors.seek(0, 2); errors.seek(max(0, errors.tell() - 3000))
                raise RuntimeError('FFmpeg 色彩处理失败：' + errors.read().decode('utf-8', 'replace'))
            st.check_cancel()
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()


def sample_histogram(st, pid, clip, folder, name):
    duration = clip['duration']
    path = Path(folder) / (name + '.rgb')
    # A fixed-size sample across the whole clip; no full-resolution frame arrays.
    run_ffmpeg(st, [st.get_ffmpeg(), '-v', 'error', '-y', '-i',
        str(st.project_path(pid, clip['video'])), '-map', '0:v:0', '-an',
        '-vf', f'fps={SAMPLE_COUNT/duration:.9f}:start_time=0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}',
        '-frames:v', str(SAMPLE_COUNT), '-pix_fmt', 'rgb24', '-f', 'rawvideo', str(path)], folder)
    data = path.read_bytes()
    frame_size = SAMPLE_WIDTH * SAMPLE_HEIGHT * 3
    if not data or len(data) % frame_size or len(data) > frame_size * SAMPLE_COUNT:
        raise ValueError('视频抽帧失败，未保存校色版本')
    count = len(data) // frame_size
    with Image.frombytes('RGB', (SAMPLE_WIDTH, SAMPLE_HEIGHT * count), data) as pixels:
        red, green, blue = pixels.split()
        maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
        mask = ImageChops.multiply(maximum.point(lambda x: 255 if x > 4 else 0),
                                   minimum.point(lambda x: 255 if x < 251 else 0))
        histogram = pixels.histogram(mask=mask)
    if sum(histogram[:256]) < 64:
        raise ValueError('画面几乎全黑或全白，无法可靠匹配；请选择有正常画面的版本')
    return [histogram[i:i+256] for i in (0, 256, 512)], count


def histogram_lut(source, reference, strength):
    """Midpoint CDF inversion, small uniform prior, smooth monotonic 1D curves."""
    def cdf(values):
        total = sum(values)
        if total <= 0: raise ValueError('颜色统计为空')
        prior = total * 0.002 / 256
        weights = [v + prior for v in values]
        cumulative, result = 0, []
        denominator = sum(weights)
        for weight in weights:
            result.append((cumulative + weight / 2) / denominator)
            cumulative += weight
        return result
    channels = []
    for src, ref in zip(source, reference):
        a, b = cdf(src), cdf(ref)
        mapped = []
        for quantile in a:
            index = bisect.bisect_left(b, quantile)
            if index == 0: value = 0
            elif index == 256: value = 255
            else: value = index - 1 + (quantile - b[index-1]) / (b[index] - b[index-1])
            mapped.append(value)
        smooth = [sum(mapped[max(0, i-2):min(256, i+3)]) /
                  len(mapped[max(0, i-2):min(256, i+3)]) for i in range(256)]
        curve = [(1-strength)*i + strength*smooth[i] for i in range(256)]
        curve[0], curve[-1] = 0, 255
        channels.append(curve)
    return list(zip(*channels))


def write_cube(path, lut):
    path.write_text('TITLE "Studio RGB histogram match"\nLUT_1D_SIZE 256\n'
                    'DOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n' +
                    ''.join(' '.join(f'{x/255:.9f}' for x in row) + '\n' for row in lut), encoding='ascii')


def run(st, jid, pid, payload):
    p = st.load_project(pid)
    reference, targets, settings, select_results = validate(st, p, payload)
    for clip in [reference, *targets]:
        st.check_cancel()
        clip.update(video_choices.media_info(st, pid, clip['video']))
    root = st.project_dir(pid)
    (root / 'temp').mkdir(exist_ok=True)
    (root / 'videos' / 'color-matched').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='color-match-', dir=root / 'temp') as work:
        st.update_job(jid, message=f'读取参考色彩 · 第 {reference["shot"]} 段', progress=5)
        ref_hist, ref_samples = sample_histogram(st, pid, reference, work, 'reference')
        completed = []
        for index, clip in enumerate(targets):
            st.check_cancel()
            st.update_job(jid, message=f'对齐色彩 {index+1}/{len(targets)} · 第 {clip["shot"]} 段',
                          progress=10+int(85*index/len(targets)))
            histogram, samples = sample_histogram(st, pid, clip, work, 'target')
            lut = histogram_lut(histogram, ref_hist, settings['strength'])
            cube = Path(work) / 'match.cube'; write_cube(cube, lut)
            token = uuid.uuid4().hex[:12]
            dest = root / 'videos' / 'color-matched' / f'color-{token}.mp4'
            sidecar = dest.with_suffix('.json')
            published = False
            try:
                vf = 'lut1d=file=match.cube:interp=linear'
                if any(settings[k] != DEFAULTS[k] for k in ('brightness', 'contrast', 'saturation')):
                    vf += f",eq=brightness={settings['brightness']}:contrast={settings['contrast']}:saturation={settings['saturation']}"
                run_ffmpeg(st, [st.get_ffmpeg(), '-v', 'error', '-y', '-i',
                    str(st.project_path(pid, clip['video'])), '-map', '0:v:0', '-map', '0:a?',
                    '-vf', vf, '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '2',
                    '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-c:a', 'copy',
                    '-movflags', '+faststart', str(dest)], work)
                output_path = str(dest.relative_to(root))
                info = video_choices.media_info(st, pid, output_path)
                if abs(info['duration']-clip['duration']) > 0.05 or info['has_audio'] != clip['has_audio']:
                    raise ValueError('校色后时长或声音校验未通过，原视频已保留')
                st.check_cancel()
                details = {'algorithm': 'rgb_histogram_lut_v1', 'reference': reference,
                           'source': clip, 'settings': settings, 'samples': samples,
                           'reference_samples': ref_samples, 'created_at': st.now()}
                sidecar.write_text(json.dumps({**details, 'lut_rgb_0_255': lut}, ensure_ascii=False, indent=2))
                # A derived take, not a regenerated shot: keep the original tail
                # and downstream continuity untouched. Publish each completed take.
                with st.PROJECT_LOCK:
                    latest = st.load_project(pid)
                    shot = st.find_shot(latest, clip['shot_id'])
                    source = next(v for v in video_choices.versions(shot) if v['id'] == clip['version_id'])
                    video_choices.archive(shot)
                    shot.setdefault('media_history', []).append({
                        'video': output_path, 'source_video': clip['video'],
                        'video_result': {'created_at': details['created_at'],
                            'settings': {'duration': info['duration']}, 'color_match': details,
                            'generation_mode': (source.get('video_result') or {}).get('generation_mode')}})
                    if select_results:
                        latest.setdefault('assembly_choices', {})[shot['id']] = video_choices.version_id(output_path)
                    st.save_project(latest)
                    published = True
                completed.append(clip['shot_id'])
                st.update_job(jid, completed_shot_ids=list(completed), progress=10+int(85*(index+1)/len(targets)))
            finally:
                if not published:
                    dest.unlink(missing_ok=True); sidecar.unlink(missing_ok=True)
