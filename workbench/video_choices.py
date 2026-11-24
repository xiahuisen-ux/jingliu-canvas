"""Generation subsets and recoverable per-shot takes; no model calls."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import uuid

RESULT_FIELDS = ('video', 'source_video', 'review', 'video_result', 'video_mode',
                 'actual_tail_frame', 'tail_source_video', 'continuity_source_video')


def version_id(path):
    return hashlib.sha256(path.encode('utf-8')).hexdigest()[:16]


def archive(shot):
    if shot.get('video'):
        shot.setdefault('media_history', []).append({k: copy.deepcopy(shot[k]) for k in RESULT_FIELDS if k in shot})


def versions(shot):
    """Read legacy history without migrating files or duplicating repeated paths."""
    deleted = {r.get('result', {}).get('video') for r in shot.get('deleted_videos', [])}
    items = {}
    for entry in [*shot.get('media_history', []), shot]:
        path = entry.get('video')
        if not path or path in deleted:
            continue
        record = items.setdefault(path, {})
        record.update({k: copy.deepcopy(entry[k]) for k in RESULT_FIELDS if k in entry})
    result = []
    for number, (path, entry) in enumerate(items.items(), 1):
        metrics = entry.get('video_result') or {}
        result.append({**entry, 'id': version_id(path), 'number': number,
                       'created_at': metrics.get('created_at', ''),
                       'duration': metrics.get('settings', {}).get('duration'),
                       'seed': metrics.get('seed'), 'current': path == shot.get('video')})
    return result


def selection(p, shot):
    choices = p.get('assembly_choices', {})
    if shot['id'] in choices:
        return choices[shot['id']]
    return version_id(shot['video']) if shot.get('video') else None


def generation_shots(st, p, payload):
    shots = st.ordered_shots(p)
    if 'shot_ids' not in payload:
        return shots
    ids = payload['shot_ids']
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids):
        raise ValueError('请至少勾选一段需要生成的视频')
    if len(set(ids)) != len(ids) or set(ids) - {s.get('id') for s in shots}:
        raise ValueError('所选视频段落已变化，请刷新后重新选择')
    wanted = set(ids)
    return [s for s in shots if s.get('id') in wanted]


def validate_predecessors(st, p, targets, batch=False):
    import video_workflow
    import video_modes
    ordered = st.ordered_shots(p)
    available = {s['id'] for s in ordered if s.get('video') and not s.get('video_stale')
                 and st.project_path(p['id'], s['video']).is_file()}
    selected = {s['id'] for s in targets}
    for index, shot in enumerate(ordered):
        if shot['id'] not in selected:
            continue
        previous = video_workflow.predecessor(st, p, shot)
        if previous is not None and previous['id'] not in available:
            raise ValueError(f"第 {shot.get('shot')} 段需要上一段有效尾帧；请同时勾选第 {previous.get('shot')} 段，或在本段设置中关闭尾帧继承")
        if batch:
            # Regenerating an upstream shot invalidates intervening dependent
            # tails even if those unselected clips currently exist.
            for following in ordered[index+1:]:
                if not video_modes.uses_previous(following):
                    break
                available.discard(following['id'])
            available.add(shot['id'])


def save_choice(st, pid, sid, data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p = st.load_project(pid); shot = st.find_shot(p, sid)
        if 'version_id' not in data:
            raise ValueError('请选择视频版本或取消参与合成')
        selected = data['version_id']
        if selected is not None:
            chosen = next((v for v in versions(shot) if v['id'] == selected), None)
            if not chosen or not st.project_path(pid, chosen['video']).is_file():
                raise ValueError('所选版本不存在或文件缺失，请刷新')
        p.setdefault('assembly_choices', {})[sid] = selected
        st.save_project(p)
        return st.project_view(p)


def assembly_clips(st, p, payload):
    clips = payload.get('clips')
    if not isinstance(clips, list) or not clips:
        raise ValueError('请至少选择一段视频参与合成')
    selected = {}
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get('shot_id'), str):
            raise ValueError('合成选择格式错误')
        sid = clip['shot_id']; shot = st.find_shot(p, sid)
        if sid in selected:
            raise ValueError('同一段只能选择一个合成版本')
        chosen = next((v for v in versions(shot) if v['id'] == clip.get('version_id')), None)
        if not chosen or not st.project_path(p['id'], chosen['video']).is_file():
            raise ValueError(f"第 {shot.get('shot')} 段所选版本不存在或文件缺失")
        selected[sid] = {'shot_id': sid, 'shot': shot.get('shot'),
                         'version_id': chosen['id'], 'video': chosen['video']}
    return [selected[s['id']] for s in st.ordered_shots(p) if s['id'] in selected]


def media_info(st, pid, path):
    file = st.project_path(pid, path)
    response = subprocess.run([str(st.h3_native.FFPROBE), '-v', 'error', '-show_streams',
                               '-show_format', '-of', 'json', str(file)], capture_output=True, text=True, timeout=30)
    if response.returncode:
        raise ValueError('视频无法读取：' + file.name)
    data = json.loads(response.stdout)
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('所选文件没有视频画面：' + file.name)
    duration = float(video.get('duration') or data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('无法确认视频时长：' + file.name)
    return {'duration': duration, 'width': int(video['width']), 'height': int(video['height']),
            'has_audio': any(s.get('codec_type') == 'audio' for s in data['streams'])}


def assemble(st, jid, pid, payload):
    """Compose exactly the chosen takes, with their own sound and actual lengths."""
    p = st.load_project(pid)
    clips = assembly_clips(st, p, payload)
    for clip in clips:
        st.check_cancel(); clip.update(media_info(st, pid, clip['video']))
    width = clips[0]['width'] // 2 * 2; height = clips[0]['height'] // 2 * 2
    root = st.project_dir(pid); (root/'temp').mkdir(exist_ok=True); (root/'final').mkdir(exist_ok=True)
    target = root/'final'/('final_cut_' + uuid.uuid4().hex[:8] + '.mp4')
    published = False
    try:
        with tempfile.TemporaryDirectory(prefix='assemble-', dir=root/'temp') as folder:
            normalized = []
            for index, clip in enumerate(clips):
                st.update_job(jid, message=f'整理所选视频 {index+1}/{len(clips)} · 第 {clip["shot"]} 段', progress=5+int(75*index/len(clips)))
                output = Path(folder)/f'{index:04d}.mov'
                command = [st.get_ffmpeg(), '-y', '-i', str(st.project_path(pid, clip['video']))]
                if not clip['has_audio']:
                    command += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
                command += ['-map', '0:v:0', '-map', '0:a:0' if clip['has_audio'] else '1:a:0',
                            '-vf', f'setpts=PTS-STARTPTS,fps=24:start_time=0,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1',
                            '-af', 'asetpts=PTS-STARTPTS,aresample=48000,apad', '-t', str(clip['duration']), '-r', '24',
                            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                            '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', str(output)]
                st.run_ffmpeg(command); normalized.append(output)
            concat = Path(folder)/'concat.txt'
            concat.write_text(''.join("file '" + str(f).replace("'", "'\\''") + "'\n" for f in normalized), encoding='utf-8')
            st.update_job(jid, message='正在合成所选视频', progress=85)
            st.run_ffmpeg([st.get_ffmpeg(), '-y', '-f', 'concat', '-safe', '0', '-i', str(concat),
                           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(target)])
        st.check_cancel()
        if p.get('final_video'):
            p.setdefault('invalidated_final_videos', []).append({'video': p['final_video'], 'review': p.get('final_review'),
                'sources': p.get('final_sources'), 'created_at': st.now(), 'reason': '另存新的所选版本合片'})
        p.update(final_video=str(target.relative_to(root)), final_sources=clips, stage='video')
        p.pop('final_review', None)
        st.save_project(p); published = True
    finally:
        if not published:
            target.unlink(missing_ok=True)
