"""Versioned Qwen opening compositions, separate from character asset generation."""
import copy
import hashlib
import json
import math
import re
import uuid
from PIL import Image
import asset_views
import character_states
import character_image_edit
import shot_elements
import tail_redraw

REVISION = 1


def targets(p):
    shots = p.get('shots', [])
    current = shot_elements.script_key(p.get('script', {}))
    if shots and all(not s.get('source_script_key') or s['source_script_key'] == current for s in shots):
        return sorted(shots, key=lambda s: s.get('shot', 0))
    # Reference creation is available immediately after the script, before 04.
    return [dict(id=f'scene-{i}', shot=i, title=scene.get('title', f'第{i}段'),
                 description=scene.get('action') or '起始构图与状态：'+scene.get('opening', ''),
                 source_scene_indices=[i], source_script_key=current, auto_elements=True,
                 element_ids=[], reference_angle_mode='main')
            for i, scene in enumerate(p.get('script', {}).get('scenes', []), 1)]


def find(p, sid):
    shot = next((s for s in targets(p) if s['id'] == sid), None)
    if shot is None:raise ValueError('段落已变化，请刷新后重新选择')
    return shot


def opening(p, shot):
    text = shot.get('description', '')
    match = re.search(r'(?:起始构图与状态|起始构图状态|起始构图|开场状态)\s*[:：]\s*(.*?)(?=\n\s*(?:本段时间|\d+\s*[–—-]|结束接续|【)|\Z)', text, re.S)
    if match and match.group(1).strip():return match.group(1).strip()
    indices, warning = shot_elements.source_scenes(p, shot)
    if not warning and len(indices) == 1:
        scene = p['script']['scenes'][indices[0]-1]
        # A later editor change must not silently reuse an older scene opening.
        if text == scene.get('action') and scene.get('opening'):return scene['opening'].strip()
    raise ValueError('请在本段剧情开头填写“起始构图与状态：…”并保存，不能用整段动作代替首帧')


def dimensions(settings):
    w, h = settings['video_width'], settings['video_height']
    edge = max(1280, min(2048, max(settings['image_width'], settings['image_height'])))
    scale = min(edge/max(w, h), math.sqrt(2_097_152/(w*h)))
    return max(16, round(w*scale/16)*16), max(16, round(h*scale/16)*16)


def references(st, p, shot):
    if not shot.get('use_element_references', True):raise ValueError('Qwen 首帧需要启用元素参考，并在 03 勾选人物／场景成品图')
    draft = copy.deepcopy(shot);shot_elements.resolve(p, draft)
    if draft.get('element_association_warning'):raise ValueError(draft['element_association_warning'])
    scoped = character_states.reference_project(p, draft)
    bindings = asset_views.reference_bindings(scoped, draft)
    if draft.get('reference_blockers'):raise ValueError('；'.join(draft['reference_blockers']))
    refs = []
    for eid in draft.get('element_ids', []):
        options = [b for b in bindings if b['entity_id'] == eid]
        kind, entity = st.entity_from_project(p, eid)
        if not options:raise ValueError(entity.get('name', eid)+'：请在 03 选用成品参考图，且不要在本段排除全部图片')
        binding = next((b for b in options if b.get('character_sheet_layout')), options[0])
        version = next((v for v in scoped.get('assets', {}).get(eid, {}).get('versions', []) if binding['image'] in v.get('images', [])), {})
        if version.get('layout_review', {}).get('status') in {'needs_review', 'needs_revision'}:
            raise ValueError(entity.get('name', eid)+'：请先确认人物参考布局')
        path = version.get('conditioning_image') or binding['image']
        source = st.project_path(p['id'], path)
        if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'} or not source.is_file():raise ValueError('首帧参考图片缺失：'+path)
        with Image.open(source) as im:
            if im.width*im.height > 24_000_000:raise ValueError('首帧参考图超过 2400 万像素')
            im.verify()
        description = '\n'.join(str(entity.get(k, '')) for k in ('appearance', 'wardrobe') if entity.get(k)) if kind == 'characters' else entity.get('description', '')
        state_id = draft.get('character_states', {}).get(eid)
        if state_id:
            description = entity.get('appearance', '')+'\nSelected costume/state overrides base clothing: '+character_states.state_version(p, eid, state_id).get('state_prompt', '')
        refs.append(dict(entity_id=eid, label=entity.get('name', eid), kind=kind,
                         path=path, preview_path=binding['image'], layout=binding.get('character_sheet_layout'),
                         description=description, spatial_anchor=entity.get('spatial_anchor', '')))
    if not 2 <= len(refs) <= 3:
        raise ValueError('Qwen 首帧多图重绘需要 2–3 个已选元素（例如两位人物＋一个场景）；请在 04 调整本段元素选择，不会暗中丢弃多余元素')
    return refs


def prompt(state, refs):
    lines = ['Create ONE high-resolution cinematic opening frame from the independently supplied references.',
             'The following opening composition and initial state have highest priority. Depict ONLY this instant before the action begins; do not advance the story, use later poses or copy the framing of a character sheet.',
             'OPENING COMPOSITION AND STATE:\n'+state]
    for i, ref in enumerate(refs, 1):
        role = 'character identity, face, physique and clothing ONLY' if ref['kind'] == 'characters' else 'environment geometry, materials and lighting' if ref['kind'] == 'locations' else 'the specified prop appearance'
        lines.append(f"Picture {i}: {ref['label']}; use for {role}. {ref['description']}")
        if ref['layout']:
            lines.append(f'Picture {i} shows ONE character in multiple views. Use only the large facial close-up for facial identity; other panels provide clothing and body. Render a normal complete head; never reproduce panels or omitted heads.')
        if ref['spatial_anchor']:lines.append('Fixed environment reference: '+ref['spatial_anchor'])
    lines.append('Arrange subjects, camera angle, screen positions, pose, gaze, facial expression and hand contacts exactly as described in the OPENING state. Preserve each subject identity and original art style. Clear natural faces without beauty filters. Output one coherent scene, no reference grids, collage, duplicate people, extra limbs, text, subtitles, logos or watermarks.')
    return '\n'.join(lines)


def graph(cfg, names, text, width, height, seed):
    if not 2 <= len(names) <= 3:raise ValueError('Qwen 首帧需要 2–3 张输入图片')
    g = tail_redraw.graph(cfg, names, text, width, height, seed)
    g['7']['inputs']['prompt'] = 'collage, panels, text, watermark, duplicate people, extra limbs, blurred face, missing head'
    g['11']['inputs']['filename_prefix'] = 'story_pipeline/opening_frame'
    return g


def inputs(st, p, shot, settings):
    state = opening(p, shot);refs = references(st, p, shot)
    w, h = dimensions(settings)
    text = prompt(state, refs)
    data = dict(revision=REVISION, model=character_image_edit.DEFAULTS, prompt=text, width=w, height=h,
                refs=[{**r, 'sha256':hashlib.sha256(st.project_path(p['id'], r['path']).read_bytes()).hexdigest()} for r in refs])
    signature = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return dict(signature=signature, opening=state, references=refs, prompt=text, width=w, height=h)


def current(st, p, spec):
    for result in reversed(p.get('opening_frames', [])):
        if result.get('signature') == spec['signature'] and not result.get('superseded'):
            path = st.project_path(p['id'], result['image'])
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == result.get('output_sha256'):
                return result
    return None


def generate(st, p, shot, spec, folder):
    return tail_redraw.execute(st, p, shot, folder/'opening.png', folder,
        [st.project_path(p['id'], r['path']) for r in spec['references']], spec['prompt'],
        spec['width'], spec['height'], graph, 'opening',
        f'第 {shot.get("shot")} 段：Qwen 多图首帧 · {spec["width"]}×{spec["height"]} · 8 步', 'Qwen 首帧多图重绘')


def prepare(st, p, shot, settings, force=False):
    spec = inputs(st, p, shot, settings)
    old = current(st, p, spec)
    if old and not force:return old
    character_image_edit.require_ready(st.director.CFG)
    folder = st.project_path(p['id'], 'frames/opening/'+uuid.uuid4().hex[:12]);folder.mkdir(parents=True)
    (folder/'inputs.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    metrics = generate(st, p, shot, spec, folder);st.check_cancel()
    target = folder/'opening.png'
    with Image.open(target) as im:
        if im.size != (spec['width'], spec['height']):raise ValueError('Qwen 首帧输出尺寸异常；已有图片保留')
    result = {**metrics, **{k:spec[k] for k in ('signature', 'opening', 'references', 'width', 'height')},
              'image':str(target.relative_to(st.project_dir(p['id']).resolve())), 'created_at':st.now(),
              'shot_id':shot['id'], 'source_scene_indices':shot.get('source_scene_indices', []),
              'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    with st.PROJECT_LOCK:
        fresh = st.load_project(p['id'])
        try:changed = inputs(st, fresh, find(fresh, shot['id']), settings)['signature'] != spec['signature']
        except ValueError:changed = True
        if changed:result.update(superseded=True, note='生成期间构图或参考已变化，本图保留为旧输入版本')
        fresh.setdefault('opening_frames', []).append(result);st.save_project(fresh)
        p['opening_frames'] = copy.deepcopy(fresh['opening_frames'])
    (folder/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if result.get('superseded'):raise ValueError(result['note']+'；请按新稿重新生成，未启动 H3')
    return result


def validate(st, p, shot, settings):
    inputs(st, p, shot, settings);character_image_edit.require_ready(st.director.CFG)


def selected(p, payload):
    ids = payload.get('shot_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(s, str) for s in ids) or len(ids) != len(set(ids)):
        raise ValueError('请勾选需要生成首帧的段落，段落编号不能重复')
    known = {s['id'] for s in targets(p)}
    if not set(ids) <= known:raise ValueError('段落已变化，请刷新后重新选择')
    return [s for s in targets(p) if s['id'] in ids]


def run(st, jid, pid, payload):
    settings = st.video_settings()
    for i, initial in enumerate(selected(st.load_project(pid), payload)):
        st.check_cancel();p = st.load_project(pid);shot = find(p, initial['id'])
        st.update_job(jid, message=f'准备第 {shot.get("shot")} 段首帧', progress=5+int(i*90/len(payload['shot_ids'])))
        prepare(st, p, shot, settings, force=bool(payload.get('force')))
        st.update_job(jid, completed_shot_ids=[*st.JOBS[jid].get('completed_shot_ids', []), shot['id']])


def view(st, p):
    rows = []
    for shot in targets(p):
        row = {k:shot.get(k) for k in ('id', 'shot', 'title')}
        try:
            row['opening'] = opening(p, shot)
            spec = inputs(st, p, shot, st.load_settings())
            row.update(opening=spec['opening'], references=spec['references'], width=spec['width'], height=spec['height'],
                       result=current(st, p, spec), ready=True)
        except (ValueError, OSError) as error:row.update(ready=False, error=str(error))
        row['versions'] = [r for r in p.get('opening_frames', []) if r.get('shot_id') == shot['id'] or
                           r.get('source_scene_indices') and r['source_scene_indices'] == shot.get('source_scene_indices')]
        rows.append(row)
    return rows
