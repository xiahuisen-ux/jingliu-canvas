"""Explicit single-view prompts and reviewed multi-angle reference selection."""
import re
from pathlib import Path
from media_prompts import NO_VISIBLE_TEXT

PROMPT_REVISION = 12
CHARACTER_SHEET_LAYOUT = 'four-view-headless-front'
VIEWS = ('front', 'three-quarter', 'side', 'back')
LABELS = dict(zip(VIEWS, ('正面', '45° 斜侧面', '侧面', '背面')))
LABELS['character-sheet']='原有三栏设定图'
LABELS['character-sheet-4view']='人物四视图'


def character_sheet_prompt(item):
    layout=('单张高清横向角色设定图，严格单行四个纵向区域，宽度比例2:1:1:1：'
            '左侧脸部高清特写占40%，正视、侧视、背视各占20%。四栏顶底对齐，不分上下排，不在任何栏内添加小图。'
            '第一栏仅一张放大的正面脸部特写，从头发顶部到下巴、完整五官清晰，脸占满主体区域；不要半身或全身照，不加下方照片或嵌入小图。'
            '第二栏正视服装和体型，从颈部以下至完整双脚；不画头、脸或头发，原头部区域留纯灰背景。'
            '这是无头部的服装展示，无伤口、切口、血迹或断头情节。双肩、胸口、双膝与脚尖正对镜头。'
            '第三栏严格90度侧面全身，头与身体都向左，保留正常侧面头部，从头顶到双脚完整可见。'
            '第四栏背面全身，保留后脑到双脚，头部不回转，不露正脸或侧脸。'
            '四栏均为同一个角色；服装、配饰、发型和体型一致，纯灰摄影棚背景，柔和均匀光照，全部双脚留在画内。'
            'No text, arrows, labels, frames or watermark. Exactly FOUR tall panels in ONE horizontal row, width ratio 2:1:1:1 (40%,20%,20%,20%). '
            'LEFT 40%: one uninterrupted high-resolution FACE CLOSE-UP, hairline to chin, no torso, no extra photo beneath it. '
            'SECOND 20%: HEAD-OMITTED FRONT BODY, below the neck through both feet, no head, face or hair, plain grey space above the neck. '
            'Non-graphic clothing reference, no injury, blood, wound or cut surface. '
            'THIRD 20%: STRICT LEFT PROFILE FULL BODY including normal profile head and both feet. '
            'RIGHT 20%: REAR FULL BODY including back of head and both feet, no visible face. '
            'No stacked images, inset pictures, extra panels, fifth view or duplicate portrait.')
    return (layout+'\nCharacter appearance and wardrobe only: '+visual_description('characters',item)+
            '\n以上角色文字只取外貌、服装与配饰。忽略其中的场景、湖泊、栏杆、鸟、夕阳、人物动作和原照构图；所有栏均使用纯灰背景。'
            '布局优先：仅一排四栏2:1:1:1，左栏只有一张脸部大特写，正视栏没有头部，侧视和背视保留正常头部。'
            'The sheet layout overrides any conflicting scene, pose or composition in the description or input photo. '
            'ONE row, no subdivision of the close-up panel. Omit the head ONLY in the second front-body panel.')


SHEET_USAGE=('This is a three-panel reference sheet of ONE character, not three people. '
             'Use ONLY the LEFT facial close-up for facial identity and facial features. '
             'Use the CENTER head-omitted front body only for clothing and body proportions, '
             'and the RIGHT rear full-body view only for the rear outfit and hairstyle. '
             'Generate one anatomically complete person with a normal head and face. '
             'Never reproduce the head omission, panels, grey reference-sheet layout or multiple copies in the video.')


FOUR_VIEW_USAGE=('This is a four-panel reference sheet of ONE character, not four people. '
                 'From left to right: facial close-up, front full body, side full body, rear full body. '
                 'Use ONLY the LEFT facial close-up for facial identity. Use the three body views ONLY for clothing, proportions and hairstyle, never for facial features. '
                 'Generate one anatomically complete person with a normal head and face. '
                 'Never reproduce the panels, grey reference-sheet layout or multiple copies in the video.')


HEADLESS_FOUR_VIEW_USAGE=('This is a four-panel reference sheet of ONE character, with panel widths 2:1:1:1. '
                        'Use ONLY the wide LEFT facial close-up for facial identity and facial features. Never infer the face from any body view. '
                        'The SECOND head-omitted front body supplies only clothing and body proportions; '
                        'the THIRD complete side view and FOURTH complete rear view supply profile, hairstyle and outfit details. '
                        'The blank area above the front body is a reference-layout convention, not an injury. '
                        'Generate one anatomically complete person with a normal head and face. '
                        'Never reproduce the head omission, panels, grey reference-sheet layout or multiple copies in the video.')


def sheet_usage(layout=None):
    if layout==CHARACTER_SHEET_LAYOUT:return HEADLESS_FOUR_VIEW_USAGE
    return FOUR_VIEW_USAGE if layout=='four-view' else SHEET_USAGE


def sheet_layout(asset,path):
    stem=Path(path).stem
    version=next((v for v in asset.get('versions',[]) if path in v.get('images',[])),{})
    if version.get('reference_layout'):return version['reference_layout']
    if stem not in {'character-sheet','character-sheet-4view'}:return None
    return version.get('reference_layout') or ('four-view' if stem=='character-sheet-4view' else 'face-front-body-back')


def visual_description(kind, item):
    keys = ('appearance', 'wardrobe') if kind == 'characters' else ('description',)
    return '. '.join(str(item.get(k, '')).strip() for k in keys if item.get(k)) or str(item.get('name', ''))


def prompt(kind, item, view, style):
    if kind == 'characters':
        return character_prompt(item, view)
    angles = {
        'front': 'FRONT VIEW. Camera directly in front of the subject, azimuth 0 degrees.',
        'three-quarter': 'ONE oblique view at an azimuth of 45 degrees. Camera halfway between the front and the left side. The subject is angled away from the camera, NOT facing straight ahead.',
        'side': 'STRICT LEFT SIDE PROFILE. Camera at an azimuth of 90 degrees. Only one side of the subject is visible.',
        'back': 'STRICT REAR VIEW. Camera directly behind the subject, azimuth 180 degrees. Show only the back, never the front.',
    }
    if kind == 'locations':
        # Film style and spatial_anchor can contain cast names and blocking.
        # The visible scene description is the only source of scene contents.
        composition = ('One continuous environment image from one camera position. '
                       'Unoccupied environment plate by default. Include people, animals or fictional characters '
                       'only if explicitly requested in Visible appearance below. Preserve the described architecture and layout.')
        if view=='front':angles[view]='THREE-QUARTER ESTABLISHING VIEW, camera at a 45 degree oblique angle, showing depth and two sides of the environment.'
        composition+=' Keep the landmarks specified in the scene description recognizable and unobstructed. Do not add unspecified landmarks or labels.'
        style='Follow the lighting, medium and visual treatment explicitly specified in the scene description; otherwise use a natural cinematic environment photograph'
    else:
        composition = 'One photograph of exactly ONE subject, centered, fully visible, with empty margins. Plain neutral grey background, soft even lighting.'
    if kind == 'characters':
        composition += ' Exactly one person. Head, torso and feet face the same direction. Neutral relaxed pose.'
        if view == 'back':composition += ' Back of head and back of clothing visible. Face, eyes, nose and mouth are completely hidden. Do not look over the shoulder.'
        if view == 'side':composition += ' One eye visible in profile; nose silhouette points toward the left edge of the image.'
        if view == 'three-quarter':composition += ' Near cheek clearly visible, far cheek foreshortened; nose points diagonally left, shoulders visibly angled.'
    return (f'{angles[view]} {composition} Visible appearance: {visual_description(kind,item)}. '
            f'Visual style: {style}. Single image, single viewpoint. '
            'No duplicate subjects, no triptych, no collage, no panels, no contact sheet, no diagram. '
            +NO_VISIBLE_TEXT+' '+angles[view])


def character_prompt(item, view):
    """Isolate casting photos from the film's location, lighting and aspect ratio."""
    directions = {
        'front': '正面全身照。人物的胸口、双肩、膝盖、脚尖朝向镜头，左右肩对称。FRONT VIEW, camera azimuth 0 degrees.',
        'three-quarter': '左前方45度全身照。整个人的头、胸口、髋部、双脚一起向画面左侧转45度。近侧肩较大，远侧肩后退，鼻尖指向左前方，目光跟随身体方向。THREE-QUARTER VIEW, 45 degrees between front and left profile.',
        'side': '严格左侧全身侧影。头、胸口、髋部、双脚全部朝画面左边。双肩在投影中重合，身体只显示窄窄的侧面，鼻尖轮廓朝向画面左边。STRICT LEFT PROFILE, 90 degrees, head and entire body in profile.',
        'back': '背影全身照。人物完全背对相机，面向背景墙，头部不回转。画面只展示后脑勺的头发、后颈、衣服背部、裤子后侧和鞋跟。REAR VIEW, 180 degrees. The face is completely hidden; the back of the head and back of the coat face the camera.',
    }
    appearance=str(item.get('appearance','')).strip()
    if view == 'back':
        # Eyes, expressions and facial details encourage a frontal portrait even in a rear-view request.
        appearance='，'.join(part for part in re.split(r'[，,。;；]',appearance)
                             if not re.search(r'眼|眉|鼻|嘴|唇|五官|表情|眼神|妆|皮肤|face|eye|brow|nose|mouth|lip|gaze|expression|makeup|skin',part,re.I))
    wardrobe=str(item.get('wardrobe','')).strip()
    return (directions[view]+'\n'
            '单人全身服装参考照片，exactly ONE subject。人物从头顶到完整双脚都在画面内，上下留空，站立占画面高度约80%。'
            '双臂自然垂下，双手在身体两侧，头和身体方向一致。固定平视相机，50mm标准镜头，统一距离。'
            '纯浅灰色无缝摄影棚背景与地面，均匀柔和白光，写实照片，方形画布边到边填满。'
            '外形：'+appearance+'。服装与配饰：'+wardrobe+'。\n'
            '只有一张照片、一个人、一个角度。没有场景、海岸或地平线，没有白边黑边，没有拼图、文字、标注、水印。'
            'Unlabelled full-body studio photograph, seamless plain grey background, no borders or text.\n'+directions[view])


def complete_views(version):
    by_name={Path(path).stem:path for path in version.get('images', [])}
    return [by_name[v] for v in VIEWS] if version.get('status') == 'done' and all(v in by_name for v in VIEWS) else []


def available_views(version, primary):
    """Use only existing angle entries from the chosen primary's version."""
    by_name={Path(path).stem:path for path in (version or {}).get('images', [])}
    paths=[by_name[v] for v in VIEWS if v in by_name]
    return paths if primary in paths else [primary]


def needs_multiview(shot):
    mode=shot.get('reference_angle_mode', 'auto')
    if mode not in {'auto', 'multi', 'main'}:raise ValueError('参考角度模式错误')
    if mode!='auto':return mode=='multi'
    text=' '.join(str(shot.get(k,'')) for k in ('camera','motion_prompt','description')).lower()
    text=re.sub(r'(?:不|无|避免|禁止)(?:进行)?(?:环绕|绕拍|旋转|转头|转身)', '', text)
    text=re.sub(r'\b(?:no|without)\s+(?:camera\s+)?(?:rotation|orbit(?:ing)?)\b','',text)
    return bool(re.search(r'环绕|绕拍|绕行|旋转|转头|转身|摇镜|弧形运镜|侧面.*正面|正面.*侧面|\b(?:orbit\w*|rotat\w*|arc(?:ing)?|turn(?:s|ing)?\s+(?:his|her|their|the)\s+(?:head|body))\b',text))


def reference_bindings(p, shot):
    multi=needs_multiview(shot);bindings=[];warnings=[];blockers=[]
    excluded=shot.get('excluded_reference_images',[])
    if not isinstance(excluded,list) or any(not isinstance(path,str) for path in excluded):
        raise ValueError('排除参考图列表格式错误')
    excluded=set(excluded)
    entities={e['id']:e for k in ('characters','key_objects','locations') for e in p.get('analysis',{}).get(k,[])}
    characters={e['id'] for e in p.get('analysis',{}).get('characters',[])}
    for eid in shot.get('element_ids',[]):
        all_views=multi or (eid in characters and shot.get('reference_angle_mode','auto')!='main')
        a=p.get('assets',{}).get(eid,{})
        selected=list(dict.fromkeys(a.get('selected_images',[])))
        primary=a.get('primary_image') if a.get('primary_image') in selected else next(iter(selected),None)
        if not selected:
            warnings.append(f"{entities.get(eid,{}).get('name',eid)}：尚未选用参考图")
            blockers.append(warnings[-1])
            continue
        version=next((v for v in a.get('versions',[]) if primary in v.get('images',[])),None)
        complete=bool(complete_views(version)) if version else False
        sheet=bool(sheet_layout(a,primary))
        paths=list(dict.fromkeys(selected+(available_views(version,primary) if all_views and not sheet else [])))
        if shot.get('reference_angle_mode')=='main':paths=[primary]
        paths=[path for path in paths if path not in excluded]
        if not paths:continue
        if all_views and not sheet:
            if complete and not version.get('views_verified'):
                warnings.append(f"{entities.get(eid,{}).get('name',eid)}：请先确认本组正面、45°、侧面、背面均正确")
                blockers.append(warnings[-1])
            if not complete:warnings.append(f"{entities.get(eid,{}).get('name',eid)}：缺少多视角，将使用现有 {len(paths)} 张参考图生成（不阻止生成）")
        kind=next((k for k in ('characters','key_objects','locations') if any(e['id']==eid for e in p.get('analysis',{}).get(k,[]))),None)
        bindings.extend({'entity_id':eid,'image':path,'view':Path(path).stem,'reference_role':'appearance','entity_kind':kind,'character_sheet_layout':sheet_layout(a,path)} for path in paths)
    shot['rotation_detected']=multi
    require_four=multi or (shot.get('reference_angle_mode','auto')!='main' and any(e in characters for e in shot.get('element_ids',[])))
    shot['reference_warnings']=warnings if require_four and shot.get('use_element_references',True) else []
    shot['reference_blockers']=blockers if require_four and shot.get('use_element_references',True) else []
    return bindings
