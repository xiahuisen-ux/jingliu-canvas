"""Qwen multi-image tail editing. Input 1 owns composition; 2/3 own identity."""
import copy
import json
import math
import time
import uuid
from pathlib import Path
from PIL import Image, ImageOps
import character_image_edit
import character_states
import asset_views
import shot_elements
import task_diagnostics
import h3_native

REVISION = 1
MAX_SECONDS = 3600


def character_refs(st, p, shot):
    if not shot.get('use_element_references', True):
        raise ValueError('Qwen 尾帧重绘需要启用人物元素参考，并在 03 选用角色图')
    draft = copy.deepcopy(shot)
    shot_elements.resolve(p, draft)
    if draft.get('element_association_warning') and draft.get('auto_elements', True):
        raise ValueError(draft['element_association_warning'])
    chars = {e['id']: e for e in p.get('analysis', {}).get('characters', [])}
    draft['element_ids'] = [eid for eid in draft.get('element_ids', []) if eid in chars]
    if not 1 <= len(draft['element_ids']) <= 2:
        raise ValueError('Qwen 尾帧重绘支持尾帧＋1–2 位角色图，请在本段选择一至两位人物')
    scoped = character_states.reference_project(p, draft)
    bindings = asset_views.reference_bindings(scoped, draft)
    if draft.get('reference_blockers'):
        raise ValueError('；'.join(draft['reference_blockers']))
    refs = []
    for eid in draft['element_ids']:
        candidates = [b for b in bindings if b['entity_id'] == eid]
        if not candidates:
            raise ValueError(chars[eid].get('name', eid)+'：请在 03 选用有效角色图，且不要在本段排除全部角色图')
        # One selected picture per character, preferring an explicitly selected sheet.
        binding = next((b for b in candidates if b['view'] in {'character-sheet', 'character-sheet-4view'}), candidates[0])
        asset = scoped.get('assets', {}).get(eid, {})
        version = next((v for v in asset.get('versions', []) if binding['image'] in v.get('images', [])), {})
        if version.get('layout_review', {}).get('status') in {'needs_review', 'needs_revision'}:
            raise ValueError(chars[eid].get('name', eid)+'：角色图需要先预览并确认采用')
        path = version.get('conditioning_image') or binding['image']
        source = st.project_path(p['id'], path)
        if not source.is_file():
            raise ValueError(chars[eid].get('name', eid)+'：角色参考或面部隔离图缺失，请重新选图')
        with Image.open(source) as im:
            if im.width*im.height > 24_000_000:raise ValueError('角色参考超过 2400 万像素')
            im.verify()
        refs.append({'entity_id': eid, 'label': chars[eid].get('name', eid), 'path': path,
                     'preview_path': binding['image'], 'layout': binding.get('character_sheet_layout'),
                     'face_only_conditioning': bool(version.get('conditioning_image'))})
    return refs


def prompt(refs):
    lines = [
        'Edit Picture 1 into a clearer single cinematic frame. Picture 1 is the PRIMARY frame and the highest priority for composition.',
        'Preserve its exact camera angle, framing, background geometry, subject count, screen positions, body proportions, poses, gaze directions, facial expressions, mouth opening, hand contacts and occlusions. Do not advance the action or introduce a new shot.',
        'Use Pictures 2 and 3, when present, ONLY as identity and clothing detail references for matching characters already visible in Picture 1. Never add a character absent from Picture 1. Do not copy reference poses, backgrounds, lighting or layout.',
        'Restore restrained natural facial, hair, fabric and skin/surface detail. Preserve the exposure and color palette of Picture 1; no darkening, dramatic relighting, beauty filter, excessive sharpening or redesign.',
    ]
    for i, ref in enumerate(refs, 2):
        lines.append(f"Picture {i}: identity reference for {ref['label']}.")
        if ref.get('layout') or 'character-sheet' in Path(ref['preview_path']).stem:
            lines.append(f'Picture {i} is a character sheet, not multiple people: use ONLY the large facial close-up for facial identity; body panels provide clothing and physique. Ignore blank/omitted heads and all panel borders. Render normal complete heads in the output.')
    lines.append('Output ONE coherent frame. No grids, panels, collage, new objects, extra limbs, text, subtitles or watermarks.')
    return '\n'.join(lines)


def graph(cfg, names, text, width, height, seed):
    if not 2 <= len(names) <= 3:raise ValueError('尾帧重绘需要 2–3 张实际输入图片')
    g = character_image_edit.graph(cfg, names[0], '', width, height, seed)
    g['6']['inputs']['prompt'] = text
    g['7']['inputs']['prompt'] = 'collage, panels, cropped face, changed pose, changed camera, extra people, text, watermark'
    for i, name in enumerate(names[1:], 2):
        node = str(11+i)
        g[node] = {'class_type': 'LoadImage', 'inputs': {'image': name}}
        for key in ('6', '7'):g[key]['inputs'][f'image{i}'] = [node, 0]
    g['11']['inputs']['filename_prefix'] = 'story_pipeline/tail_redraw'
    return g


def dimensions(source):
    with Image.open(source) as im:w, h = ImageOps.exif_transpose(im).size
    scale = min(1280/max(w, h), math.sqrt(1_048_576/(w*h)))
    return max(16, round(w*scale/16)*16), max(16, round(h*scale/16)*16)


def generate(st, p, shot, source, target, folder, refs):
    width, height = dimensions(source)
    result = execute(st, p, shot, target, folder,
                     [source, *[st.project_path(p['id'], r['path']) for r in refs]],
                     prompt(refs), width, height, graph, 'tail_edit',
                     f'第 {shot.get("shot")} 段接续：Qwen 多图重绘（尾帧＋{len(refs)} 张角色图，8 步）',
                     'Qwen 尾帧多图重绘')
    return {**result, 'character_references': refs,
            'priority': 'tail_composition_then_character_identity'}


def execute(st, p, shot, target, folder, input_paths, text, width, height,
            build_graph, prefix, message, label):
    """Shared serial Qwen execution; the caller owns reference roles and publication."""
    character_image_edit.require_ready(st.director.CFG)
    names = []; paths = st.comfy_project_paths(p['id'])
    for i, path in enumerate(input_paths, 1):
        name = f'{prefix}_{folder.name}_{i}.png'
        with Image.open(path) as im:ImageOps.exif_transpose(im).convert('RGB').save(paths['input']/name)
        names.append(name)
    seed = int(uuid.uuid4().hex[:8], 16)
    workflow = build_graph(st.director.CFG, names, text, width, height, seed)
    (folder/'prompt.txt').write_text(text, encoding='utf-8')
    (folder/'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding='utf-8')
    started = time.monotonic(); owned = []
    ctx = st.director.TASK_CONTEXT
    old_check = getattr(ctx, 'check', None); old_prompt = getattr(ctx, 'prompt', None)
    initial_swap = h3_native.swap_mb(); peak_swap = initial_swap; last_check = [0]
    limit = st.video_settings().get('h3c_swap_limit_gib', 8)*1024
    def check():
        nonlocal peak_swap
        st.check_cancel()
        if time.monotonic()-started > MAX_SECONDS:raise RuntimeError(label+'超过 60 分钟，已停止；已有素材保留')
        if time.monotonic()-last_check[0] >= 3:
            last_check[0] = time.monotonic(); peak_swap = max(peak_swap, h3_native.swap_mb())
            if peak_swap-initial_swap > limit:raise RuntimeError(label+'交换内存新增超过设置阈值，已停止；已有素材保留')
    def remember(url, pid):
        owned.append(pid)
        if old_prompt:old_prompt(url, pid)
    # A fresh image service avoids keeping the previous Z-Image model resident.
    st.ensure_comfy_idle(); st.stop_comfy('qwen_image')
    ctx.check = check; ctx.prompt = remember
    try:
        st.prepare_model_mode('image')
        jid = getattr(st.TASK_LOCAL, 'jid', None)
        if jid:
            st.update_job(jid, message=message,
                          image_backend='qwen_image_edit_2511', image_model=character_image_edit.MODEL)
        history = st.director.queue_and_wait(st.director.CFG['qwen_image_url'], workflow, label)
        check()
        image = st.director.first_output(history, 'images')
        output = (paths['output']/image.get('subfolder', '')/image['filename']).resolve()
        if not output.is_relative_to(paths['output'].resolve()):raise ValueError('Qwen 输出路径超出本工程')
        with Image.open(output) as im:
            if im.size != (width, height):raise ValueError(label+'输出尺寸异常')
            im.convert('RGB').save(target)
    finally:
        ctx.check = old_check; ctx.prompt = old_prompt
        task_diagnostics.cleanup(lambda: st.stop_comfy('qwen_image', allowed_prompt_ids=owned))
    return {'model': character_image_edit.MODEL, 'backend': 'qwen_image_edit_2511',
            'steps': 8, 'seed': seed, 'width': width, 'height': height,
            'seconds': round(time.monotonic()-started, 3),
            'swap_start_mb': initial_swap, 'swap_peak_mb': peak_swap}
