"""Resolve shot -> source scenes -> element IDs without re-running a model."""
import hashlib
import json
import copy


# The editor owns these fields. Provenance, audio bindings and generated results
# belong to the saved project and must not be replaced by an older browser tab.
EDIT_FIELDS=frozenset((
    'title','shot','duration','description','camera','motion_prompt','dialogue',
    'start_prompt','end_prompt','element_ids','character_actions','auto_elements',
    'added_element_ids','excluded_element_ids','inherit_previous','inherit_previous_manual',
    'transition','use_element_references','manual_reference_images','reference_angle_mode',
    'excluded_reference_images','character_states','generation_mode','first_frame_source',
    'first_frame_image','last_frame_image','omni_media','auto_reference','reference_image',
    'tail_repair_mode','tail_reference_image','opening_reference_image',
))


def merge_edits(p, incoming):
    if not isinstance(incoming,list) or any(not isinstance(s,dict) or not isinstance(s.get('id'),str) for s in incoming):
        raise ValueError('镜头列表格式错误')
    ids=[s['id'] for s in incoming]
    if len(ids)!=len(set(ids)):raise ValueError('镜头编号重复')
    saved={s['id']:s for s in p.get('shots',[])}
    if not saved:return copy.deepcopy(incoming)  # Legacy initial import.
    stale='页面中的镜头来自旧版剧本，请刷新页面后重试；已保存的内容与素材保留'
    if set(ids)!=set(saved):raise ValueError(stale)
    result=[]
    for draft in incoming:
        old=saved[draft['id']]
        if 'source_script_key' in draft and draft['source_script_key']!=old.get('source_script_key'):
            raise ValueError(stale)
        # Do not re-stamp provenance to the current script here: actual script
        # changes must still be caught by source_scenes and render preflight.
        shot=copy.deepcopy(old)
        shot.update({k:copy.deepcopy(v) for k,v in draft.items() if k in EDIT_FIELDS})
        result.append(shot)
    return result


def script_key(script):
    return hashlib.sha256(json.dumps(script,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def source_scenes(p,shot):
    script=p.get('script',{});scenes=script.get('scenes',[])
    current=script_key(script)
    source=shot.get('source_scene_indices')
    if source is not None:
        if shot.get('source_script_key')!=current:return [],'剧本已变更，镜头来源场次需重新确认'
        if not isinstance(source,list) or any(type(n) is not int or not 1<=n<=len(scenes) for n in source):
            return [],'镜头来源场次无效，需重新拆分或确认'
        return sorted(set(source)),''
    # Safely migrate the old one-scene-per-authored-shot path, not arbitrary shots.
    index=shot.get('shot',0)
    if (type(index) is int and 1<=index<=len(scenes) and len(p.get('shots',[]))==len(scenes)):
        scene=scenes[index-1]
        if scene.get('video_prompt') and scene['video_prompt']==shot.get('motion_prompt') and scene.get('action','')==shot.get('description',''):
            shot.update(source_scene_indices=[index],source_script_key=current)
            return [index],''
    return [],''


def resolve(p,shot):
    entities=[e for kind in ('characters','key_objects','locations') for e in p.get('analysis',{}).get(kind,[])]
    known={e['id'] for e in entities}
    sources,warning=source_scenes(p,shot)
    snapshot=p.get('elements_script_snapshot')
    if sources and snapshot and snapshot!=json.dumps(p.get('script',{}),ensure_ascii=False,sort_keys=True):
        sources=[];warning='元素出场表对应旧剧本，请重新提取元素'
    suggested=[]
    if not warning:
        text=' '.join(str(shot.get(k,'')) for k in ('description','title','motion_prompt'))
        for entity in entities:
            appearances=entity.get('source_scenes')
            if sources and appearances is not None:
                if set(sources)&set(appearances):suggested.append(entity['id'])
            elif len(entity.get('name',''))>=2 and entity['name'] in text:
                suggested.append(entity['id'])
        if not sources:
            suggested.extend(shot.get('element_ids',[]))
            for actor in shot.get('character_actions',[]):suggested.extend([actor.get('character_id'),*actor.get('element_ids',[])])
    suggested=list(dict.fromkeys(e for e in suggested if e in known))
    shot['suggested_element_ids']=suggested
    shot['element_association_warning']=warning
    if shot.get('auto_elements',True):
        excluded=set(shot.get('excluded_element_ids',[]))
        shot['element_ids']=list(dict.fromkeys(e for e in [*suggested,*shot.get('added_element_ids',[])] if e in known and e not in excluded))
    else:
        shot['element_ids']=list(dict.fromkeys(e for e in shot.get('element_ids',[]) if e in known))
    return shot['element_ids']
