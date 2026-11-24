"""Conservative, versioned tail conditioning. Never rewrites a source video."""
import hashlib
import json
import subprocess
import time
import uuid
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageOps
import video_enhance
import video_modes
import task_diagnostics
import h3_native
import tail_redraw
import character_image_edit

REVISION = 1
MODES = {'raw', 'review', 'auto', 'qwen_review', 'qwen_auto'}
AUTO_MODES = {'auto', 'qwen_auto'}
QWEN_MODES = {'qwen_review', 'qwen_auto'}
FIELDS = ('tail_repair_mode', 'tail_reference_image')


class ReviewRequired(ValueError):
    def __init__(self, shot):
        self.shot_id = shot['id']
        super().__init__(f"第 {shot.get('shot')} 段尾帧已修复，请在 04 视频任务预览并采用后继续生成；已完成视频保留")


def config(p, shot):
    defaults = p.get('tail_repair_defaults', {})
    if not isinstance(defaults, dict):raise ValueError('尾帧接续设置格式错误')
    mode = shot.get('tail_repair_mode') or defaults.get('mode', 'raw')
    reference = shot.get('tail_reference_image') or defaults.get('reference', '')
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('尾帧处理方式无效')
    if not isinstance(reference, str):
        raise ValueError('固定颜色参考图片格式无效')
    return {'mode': mode, 'reference': reference}


def image_path(st, pid, relative):
    path = st.project_path(pid, relative)
    if path.suffix.lower() not in video_modes.IMAGE_EXTENSIONS or not path.is_file():
        raise ValueError('请先选择有效的固定颜色参考图片')
    with Image.open(path) as im:
        if im.width * im.height > 24_000_000:
            raise ValueError('参考图片超过 2400 万像素，请缩小后上传')
        im.verify()
    return path


def validate(st, p, shot):
    c = config(p, shot)
    if video_modes.uses_previous(shot) and c['mode'] != 'raw':
        if c['mode'] in QWEN_MODES:
            character_image_edit.require_ready(st.director.CFG)
            tail_redraw.character_refs(st, p, shot)
            if c['reference']:image_path(st, p['id'], c['reference'])
            return c
        if not c['reference']:
            raise ValueError('尾帧轻修复需要固定颜色参考，请先在 04 视频任务选择并保存')
        image_path(st, p['id'], c['reference'])
        if not video_enhance.status()['ready']:
            raise ValueError('Real-ESRGAN 未就绪，不能修复尾帧')
    return c


@lru_cache(maxsize=128)
def _digest(path, size, mtime):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_digest(path):
    stat = path.stat()
    return _digest(str(path), stat.st_size, stat.st_mtime_ns)


def signature(st, p, shot, previous, tail):
    c = config(p, shot)
    src = st.project_path(p['id'], previous['video']).stat()
    data = {
        'revision': REVISION, 'video': previous['video'], 'video_stat': [src.st_size, src.st_mtime_ns],
        'tail': tail, 'tail_hash': image_digest(st.project_path(p['id'], tail)),
        'reference': c['reference'], 'reference_hash': image_digest(image_path(st, p['id'], c['reference'])) if c['reference'] else '',
    }
    if c['mode'] in QWEN_MODES:
        refs = tail_redraw.character_refs(st, p, shot)
        data.update(algorithm='qwen_image_edit_2511', redraw_revision=tail_redraw.REVISION,
                    characters=[{**r, 'hash': image_digest(st.project_path(p['id'], r['path']))} for r in refs])
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def current(st, p, shot, previous, tail):
    result = shot.get('tail_repair_result')
    if not result or not previous or not tail or previous.get('video_stale'):
        return None
    try:
        if result.get('signature') != signature(st, p, shot, previous, tail):
            return None
        for key in ('original', 'corrected', 'repaired'):
            if not st.project_path(p['id'], result[key]).is_file():
                return None
        if image_digest(st.project_path(p['id'], result['repaired'])) != result.get('output_hash'):
            return None
        return result
    except (OSError, ValueError, KeyError):
        return None


def predecessor(st, p, shot):
    ordered = st.ordered_shots(p)
    index = next((i for i, s in enumerate(ordered) if s['id'] == shot['id']), 0)
    return ordered[index-1] if index and video_modes.uses_previous(shot) else None


def view(st, p, shot):
    c = config(p, shot)
    prev = predecessor(st, p, shot)
    tail = prev.get('actual_tail_frame') if prev and prev.get('tail_source_video') == prev.get('video') else None
    result = current(st, p, shot, prev, tail) if c['mode'] != 'raw' else None
    refs = []; error = ''
    if prev and c['mode'] in QWEN_MODES:
        try:refs = tail_redraw.character_refs(st, p, shot)
        except (ValueError, OSError) as e:error = str(e)
    return {**c, 'active': bool(prev) and c['mode'] != 'raw', 'result': result,
            'character_references': refs, 'reference_error': error,
            'approved': bool(result and (c['mode'] in AUTO_MODES or shot.get('tail_repair_approved') == result['signature'])),
            'previous_ready': bool(prev and prev.get('video') and not prev.get('video_stale'))}


def color_correct(source, reference, target):
    """Fixed bounded RGB gains, not per-frame histogram matching or repainting."""
    with Image.open(source) as f:
        im = ImageOps.exif_transpose(f).convert('RGB')
    with Image.open(reference) as f:
        ref = ImageOps.exif_transpose(f).convert('RGB')
    def means(img):
        img = img.copy(); img.thumbnail((256, 256))
        # Exclude near-black/white pixels from the robust global estimate.
        pixels = [rgb for rgb in getattr(img, 'get_flattened_data', img.getdata)() if 18 < sum(rgb)/3 < 237]
        return [sum(rgb[c] for rgb in pixels)/len(pixels) for c in range(3)] if pixels else None
    a, b = means(im), means(ref)
    gains = [max(.88, min(1.12, (b[c]/max(a[c], 1))**.5)) for c in range(3)] if a and b else [1.0]*3
    lut = [round(min(255, max(0, x*g))) for g in gains for x in range(256)]
    im.point(lut).save(target)
    return {'rgb_gains': gains, 'gain_limit': [.88, 1.12], 'strength': .5,
            'note': '固定参考、保守校色；非语义匹配，不恢复欠曝丢失细节'}


def upscale(st, source, target, log):
    """One image, bounded tile memory, cancellable; releases subprocess before H3."""
    with Image.open(source) as im:
        size = im.size
    if size[0]*size[1] > 2_100_000:
        raise ValueError('尾帧超过 210 万像素，请检查生成尺寸；未启动增强模型')
    raw = target.with_name('upscale-4x.png')
    cmd = [str(video_enhance.BINARY), '-i', str(source), '-o', str(raw),
           '-m', str(video_enhance.MODELS), '-n', 'realesrgan-x4plus', '-s', '4', '-t', '128', '-j', '1:1:1', '-f', 'png']
    started = time.monotonic()
    try:
        with open(log, 'wb') as stream:
            process = subprocess.Popen(cmd, cwd=video_enhance.BINARY.parent, stdout=stream, stderr=stream, start_new_session=True)
            try:
                while process.poll() is None:
                    st.check_cancel()
                    if time.monotonic()-started > 180:
                        raise RuntimeError('尾帧修复超过 3 分钟，已停止；原尾帧保留')
                    time.sleep(.2)
                st.check_cancel()
                if process.returncode:
                    raise RuntimeError('Real-ESRGAN 尾帧修复失败，请查看 '+str(log))
            finally:
                task_diagnostics.cleanup(lambda: h3_native.stop_process(process))
        with Image.open(raw) as im:
            if im.size != (size[0]*4, size[1]*4):
                raise RuntimeError('尾帧增强输出尺寸异常')
            im.convert('RGB').resize((size[0]*2, size[1]*2), Image.Resampling.LANCZOS).save(target)
    finally:
        raw.unlink(missing_ok=True)
    return round(time.monotonic()-started, 3)


def prepare(st, p, shot, previous, tail, force=False):
    validate(st, p, shot)
    result = current(st, p, shot, previous, tail)
    if result and not force:
        return result
    pid = p['id']; c = config(p, shot)
    folder = st.project_dir(pid)/'frames'/'tail-repair'/uuid.uuid4().hex[:12]
    folder.mkdir(parents=True)
    is_qwen = c['mode'] in QWEN_MODES
    corrected, repaired = folder/'color-corrected.png', folder/('qwen-repaired.png' if is_qwen else 'repaired-2x.png')
    generated = folder/'qwen-generated.png'
    try:
        sig = signature(st, p, shot, previous, tail)
        st.check_cancel()
        if c['reference']:
            color = color_correct(st.project_path(pid, tail), image_path(st, pid, c['reference']), corrected)
        else:
            with Image.open(st.project_path(pid, tail)) as im:im.convert('RGB').save(corrected)
            color = {'note': '未指定固定基准，保留原尾帧颜色'}
        details = {}
        if is_qwen:
            refs = tail_redraw.character_refs(st, p, shot)
            details = tail_redraw.generate(st, p, shot, corrected, generated, folder, refs)
            if c['reference']:
                details['post_color'] = color_correct(generated, image_path(st, pid, c['reference']), repaired)
            else:
                with Image.open(generated) as im:im.convert('RGB').save(repaired)
            details['generated'] = str(generated.relative_to(st.project_dir(pid)))
            seconds = details['seconds']
        else:seconds = upscale(st, corrected, repaired, folder/'repair.log')
        st.check_cancel()
        if sig != signature(st, p, shot, previous, tail):
            raise ValueError('尾帧或参考图在修复期间变化，请重新修复')
        result = {'signature': sig, 'revision': REVISION, 'original': tail,
                  'corrected': str(corrected.relative_to(st.project_dir(pid))),
                  'repaired': str(repaired.relative_to(st.project_dir(pid))),
                  'reference': c['reference'], 'source_video': previous['video'],
                  'output_hash': image_digest(repaired), 'color': color,
                  'model': 'realesrgan-x4plus', 'scale': 2, 'seconds': seconds, 'created_at': st.now()}
        if is_qwen:
            result.pop('scale', None)
            result.update(details)
        (folder/'source.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if shot.get('tail_repair_result'):
            shot.setdefault('tail_repair_history', []).append(shot['tail_repair_result'])
        shot['tail_repair_result'] = result
        shot.pop('tail_repair_approved', None)
        st.save_project(p)
        return result
    except Exception:
        # Only unpublished outputs from this invocation are removed. Keep failure log.
        corrected.unlink(missing_ok=True); repaired.unlink(missing_ok=True); generated.unlink(missing_ok=True)
        raise


def resolve(st, p, shot, previous, tail, materialize=False):
    c = validate(st, p, shot) if materialize else config(p, shot)
    if c['mode'] == 'raw':
        return tail
    result = prepare(st, p, shot, previous, tail) if materialize else current(st, p, shot, previous, tail)
    if not result:
        return tail
    approved = c['mode'] in AUTO_MODES or shot.get('tail_repair_approved') == result['signature']
    if materialize and not approved:
        raise ReviewRequired(shot)
    return result['repaired'] if approved else tail


def run(st, jid, pid, payload):
    p = st.load_project(pid); shot = st.find_shot(p, payload.get('shot_id'))
    c = validate(st, p, shot); prev = predecessor(st, p, shot)
    if c['mode'] == 'raw' or not prev or not prev.get('video') or prev.get('video_stale'):
        raise ValueError('请选择尾帧修复或重绘，并先完成上一段有效视频')
    # Vision mode releases image services; explicitly unload the last allowed model too.
    st.prepare_model_mode('vision'); st.unload_other_ollama()
    tail = prev.get('actual_tail_frame') if prev.get('tail_source_video') == prev['video'] else None
    if not tail or not st.project_path(pid, tail).is_file():
        tail = st.extract_video_tail(pid, prev['video'], prev['id'])
        prev.update(actual_tail_frame=tail, tail_source_video=prev['video']); st.save_project(p)
    st.update_job(jid, message='Qwen 尾帧多图重绘' if c['mode'] in QWEN_MODES else '尾帧轻度校色与 Real-ESRGAN 修复', progress=15)
    return prepare(st, p, shot, prev, tail, force=bool(payload.get("force")))


def approve(st, pid, payload):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p = st.load_project(pid); shot = st.find_shot(p, payload.get('shot_id'))
        state = view(st, p, shot); result = state['result']
        if not state['active'] or not result or payload.get('signature') != result['signature']:
            raise ValueError('预览已过期，请重新修复并检查尾帧')
        shot['tail_repair_approved'] = result['signature']; st.save_project(p)
        return st.project_view(p)


def save_defaults(st, pid, payload):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid); p = st.load_project(pid)
        value = {'mode': payload.get('mode'), 'reference': payload.get('reference', '')}
        probe = {**p, 'tail_repair_defaults': value}
        c = config(probe, {})
        if c['mode'] in QWEN_MODES:
            character_image_edit.require_ready(st.director.CFG)
            if c['reference']:image_path(st, pid, c['reference'])
        elif c['mode'] != 'raw':
            image_path(st, pid, c['reference'])
        p['tail_repair_defaults'] = value
        # These are future-generation settings; preserve all completed takes and audio.
        st.save_project(p)
        return st.project_view(p)
