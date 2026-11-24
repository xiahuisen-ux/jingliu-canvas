"""Per-shot H3 input modes and media limits; never loads model weights."""
import json
import math
from pathlib import Path
import subprocess

MODES = {'text': '文生视频', 'first_frame': '首帧生视频', 'omni_reference': '全能参考'}
FIELDS = ('generation_mode', 'first_frame_source', 'first_frame_image', 'last_frame_image', 'omni_media')
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv'}
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aif', '.aiff'}


def mode(shot):
    value = shot.get('generation_mode', 'omni_reference')
    if not isinstance(value,str) or value not in MODES:
        raise ValueError('生成模式须为文生视频、首帧生视频或全能参考')
    return value


def validate_fields(shot):
    mode(shot)
    if not isinstance(shot.get('tail_repair_mode',''),str) or shot.get('tail_repair_mode', '') not in ('', 'raw', 'review', 'auto', 'qwen_review', 'qwen_auto'):
        raise ValueError('尾帧处理方式无效')
    if not isinstance(shot.get('tail_reference_image', ''), str):
        raise ValueError('尾帧颜色参考路径格式错误')
    if not isinstance(shot.get('first_frame_source','image'),str) or shot.get('first_frame_source', 'image') not in {'image', 'previous_tail', 'qwen'}:
        raise ValueError('首帧来源不正确')
    for key in ('first_frame_image', 'last_frame_image', 'opening_reference_image'):
        if not isinstance(shot.get(key, ''), str):
            raise ValueError('首尾帧图片路径格式错误')
    media = shot.get('omni_media', [])
    if not isinstance(media, list) or len(media) > 6:
        raise ValueError('视频与音频参考列表格式错误，最多六项')
    for item in media:
        if not isinstance(item, dict) or not isinstance(item.get('kind'),str) or item.get('kind') not in {'video', 'silent_video', 'audio'} or not isinstance(item.get('path'), str) or not item['path']:
            raise ValueError('视频与音频参考须包含有效类型和路径')


def configuration(shot):
    selected=mode(shot)
    if selected=='text':return (selected,)
    if selected=='first_frame':
        source=shot.get('first_frame_source','image')
        return (selected,source,shot.get('first_frame_image','') if source=='image' else '',shot.get('last_frame_image',''))
    return (selected,shot.get('omni_media',[]),shot.get('opening_reference_image','') if not uses_previous(shot) else '')


def uses_previous(shot):
    selected = mode(shot)
    if selected == 'text':
        return False
    if selected == 'first_frame':
        return shot.get('first_frame_source', 'image') == 'previous_tail'
    return shot.get('inherit_previous', True)


def probe(path, kind, ffprobe):
    """Read actual streams/duration, including for files supplied through save API."""
    path = Path(path)
    extensions = AUDIO_EXTENSIONS if kind == 'audio' else VIDEO_EXTENSIONS
    if path.suffix.lower() not in extensions or not path.is_file():
        raise ValueError('参考媒体缺失或格式不支持：' + path.name)
    try:
        result = subprocess.run([str(ffprobe), '-v', 'error', '-show_entries',
                                 'format=duration:stream=codec_type,duration', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        wanted = 'audio' if kind == 'audio' else 'video'
        if result.returncode or not any(s.get('codec_type') == wanted for s in streams):
            raise ValueError('缺少有效的' + ('音频' if wanted == 'audio' else '视频') + '流')
        duration = float(data.get('format', {}).get('duration', 0))
        if not math.isfinite(duration) or not 2 <= duration <= 15.001:
            raise ValueError('每段参考视频或音频须为 2–15 秒，请先裁剪')
        has_audio = any(s.get('codec_type') == 'audio' for s in streams)
        if kind == 'video' and not has_audio:
            raise ValueError('该视频没有音轨，请选择“仅参考画面”')
        return {'duration': duration, 'has_audio': has_audio}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError) as error:
        raise ValueError('无法读取参考媒体：' + path.name) from error


def validate_references(refs, pending=0):
    images = sum(r.get('kind', 'image') == 'image' for r in refs) + pending
    videos = [r for r in refs if r.get('kind') in {'video', 'silent_video'}]
    audios = [r for r in refs if r.get('kind') in {'video', 'audio'}]
    if images > 9 or len(videos) > 3 or len(audios) > 3 or len(refs) + pending > 12:
        raise ValueError('全能参考最多 9 张图片、3 段视频、3 路音频，总计 12 项；视频自带声音占一路音频')
    if audios and not (images or videos):
        raise ValueError('音频参考须搭配至少一张图片或一段视频')
    for items, label in ((videos, '视频'), (audios, '音频（含视频声音）')):
        if sum(r.get('duration', 0) for r in items) > 15.001:
            raise ValueError(label + '参考总时长不能超过 15 秒，请先裁剪')


def numbered(refs):
    counts = {'Picture': 0, 'Video': 0, 'Audio': 0}
    for ref in refs:
        kind = ref.get('kind', 'image')
        label = 'Picture' if kind == 'image' else 'Audio' if kind == 'audio' else 'Video'
        counts[label] += 1
        tags = f'<{label} {counts[label]}>'
        if kind == 'video':
            counts['Audio'] += 1
            tags += f' with soundtrack <Audio {counts["Audio"]}>'
        yield ref, tags
