"""Character states and stable, editable voice descriptions."""
DEFAULT_VOICE=('Natural mid-register speaking voice, clear articulation, gently textured timbre, '
               'moderate pace, standard Mandarin pronunciation and restrained delivery. '
               'Keep the same pitch range, resonance, accent and vocal texture across shots.')


def present_ids(shot):
    return (set(shot.get('element_ids',[])) if shot.get('use_element_references',True) else set()) | {r['node_id'][6:] for r in shot.get('canvas_image_links',[]) if r['node_id'].startswith('asset:')}

def voices(p,shot):
    present=present_ids(shot)
    lines=[]
    for character in p.get('analysis',{}).get('characters',[]):
        if character['id'] in present and character.get('voice_mode','text')!='audio':
            lines.append(str(character.get('name',character['id']))+': '+(character.get('voice_prompt') or DEFAULT_VOICE))
    if not lines:return ''
    return ('Voice identity instructions (not visible text): '+'; '.join(lines)+
            ' Apply only when the script calls for that character to speak. '
            'Do not add speech or singing to silent roles. These are voice descriptions, not cloned audio.')


def state_version(p,eid,vid):
    version=next((v for v in p.get('assets',{}).get(eid,{}).get('versions',[]) if v.get('id')==vid),None)
    if not version or not version.get('state_name') or version.get('status')!='done' or not version.get('images'):
        raise ValueError('角色状态图不存在或尚未生成完成，请重新选择')
    return version


def reference_project(p,shot):
    import copy
    selected=shot.get('character_states',{})
    if not isinstance(selected,dict):raise ValueError('角色状态选择格式错误')
    if not selected:return p
    result=copy.deepcopy(p)
    chars={c['id'] for c in p.get('analysis',{}).get('characters',[])}
    for eid,vid in selected.items():
        if eid not in shot.get('element_ids',[]):continue
        if eid not in chars:raise ValueError('只有人物可以选择角色状态')
        if not vid:continue
        v=state_version(p,eid,vid);path=v['images'][0]
        result['assets'][eid]['primary_image']=path
        result['assets'][eid]['selected_images']=[path]
    return result


def state_instructions(p,shot):
    lines=[]
    for character in p.get('analysis',{}).get('characters',[]):
        eid=character['id'];vid=shot.get('character_states',{}).get(eid)
        if eid in shot.get('element_ids',[]) and vid:
            version=state_version(p,eid,vid)
            lines.append(character.get('name',eid)+': '+version.get('state_prompt',version['state_name']))
    return ('Selected character states override conflicting base costume or age descriptions; preserve identity: '+'; '.join(lines)) if lines else ''


def generate_voice(st,jid,pid,payload):
    p=st.load_project(pid);kind,item=st.entity_from_project(p,payload['entity_id'])
    if kind!='characters':raise ValueError('只能为人物生成音色设定')
    st.update_job(jid,message='生成角色音色描述',progress=30)
    import json
    data=st.ollama_json('为虚构影视角色设计稳定可复用的英文音色提示词，描述音高、共鸣、质感、语速、口音。'
        '不克隆或声称识别真人声音，不虚构参考音频。只返回voice_prompt字符串。角色：'+json.dumps(item,ensure_ascii=False),
        {'type':'object','required':['voice_prompt'],'properties':{'voice_prompt':{'type':'string'}}})
    voice=data.get('voice_prompt','').strip()
    if not voice:raise ValueError('音色描述为空')
    item['voice_prompt']=voice[:4000]
    for shot in p.get('shots',[]):
        if item['id'] in shot.get('element_ids',[]):
            if shot.get('video'):shot.update(video_stale=True,stale_reason='角色音色设定已修改')
            st.video_workflow.invalidate(st,p,shot,'上游角色音色设定已修改')
    st.save_project(p)
