"""Canvas layout and targeted shot edits; reuse existing generation/media rules."""
import copy
import math
import uuid
import shot_elements
import video_timing
import video_modes
import video_workflow
import video_choices
import project_audio

FIELDS = ('title', 'description', 'camera', 'dialogue', 'motion_prompt', 'duration', 'canvas_request', 'canvas_mentions')

def shot_base(shot):
    return {key:copy.deepcopy(shot.get(key)) for key in FIELDS}

def number(value, low, high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('画布坐标或缩放超出范围')
    return value

def known_nodes(p):
    return {'asset:'+e['id'] for kind in ('characters','locations','key_objects') for e in p.get('analysis',{}).get(kind,[])} | {'video:'+s['id'] for s in p.get('shots',[])} | {'clip:'+s['id'] for s in p.get('canvas_videos',[])} | {'audio:'+s['id'] for s in p.get('canvas_audios',[])}

def save_layout(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p=st.load_project(pid)
        layout=copy.deepcopy(p.get('canvas_workspace',{}))
        positions=data.get('positions',{})
        if not isinstance(positions,dict) or len(positions)>1000:raise ValueError('画布节点格式错误')
        valid=known_nodes(p)
        for key,pos in positions.items():
            if key not in valid or not isinstance(pos,dict):raise ValueError('画布节点已变化，请刷新')
            layout.setdefault('positions',{})[key]={'x':number(pos.get('x'),-100000,100000),'y':number(pos.get('y'),-100000,100000)}
        if 'viewport' in data:
            v=data['viewport']
            if not isinstance(v,dict):raise ValueError('画布视口格式错误')
            layout['viewport']={'x':number(v.get('x'),-200000,200000),'y':number(v.get('y'),-200000,200000),'zoom':number(v.get('zoom'),.15,2)}
        layout['version']=1
        p['canvas_workspace']=layout
        st.save_project(p)
        return layout

def invalidate(st,p,shot):
    video_workflow.invalidate(st,p,shot,'画布中的提示词或连线已修改')
    video_choices.archive(shot)
    for key in ('video','source_video','review','continuity_source_shot','continuity_source_video'):
        shot.pop(key,None)
    shot['status']='planned'

def edit(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p=st.load_project(pid)
        operation=data.get('operation')
        if operation=='create_video':
            if p.get('audio_timeline'):raise ValueError('本工程已绑定整片音轨，请在剧本工作区调整分段后再新增视频')
            shot={'id':'canvas_'+uuid.uuid4().hex[:12], 'shot':max([int(s.get('shot',0)) for s in p.get('shots',[])]+[0])+1,
                  'title':str(data.get('title') or '新的视频镜头')[:100], 'description':'','motion_prompt':'','camera':'','dialogue':'',
                  'duration':video_timing.validate_duration(data.get('duration',st.load_settings()['video_duration'])),
                  'exact_duration':True,'status':'planned','generation_mode':'omni_reference','canvas_created':True,
                  'auto_elements':False,'element_ids':[],'inherit_previous':False,'inherit_previous_manual':True,
                  'transition':'cut','use_element_references':True,'reference_angle_mode':'main','manual_reference_images':[]}
            p.setdefault('shots',[]).append(shot)
            video_timing.update_timelines(p)
        else:
            shot=st.find_shot(p,data.get('shot_id'))
            before=copy.deepcopy(shot)
            if operation=='save_video':
                if data.get('base')!=shot_base(shot):raise ValueError('该镜头已在其他页面修改，请刷新后核对；当前输入仍保留')
                changes=data.get('changes',{})
                if not isinstance(changes,dict) or set(changes)-set(FIELDS):raise ValueError('视频字段不正确')
                for key,value in changes.items():
                    if key=='duration':shot[key]=video_timing.validate_duration(value)
                    elif not isinstance(value,str) or len(value)>60000:raise ValueError('提示词格式或长度不正确')
                    else:shot[key]=value
                project_audio.validate_timeline(p)
                video_timing.update_timelines(p,{before['id']:before})
                # Preserve the existing H3 contract for authored/imported shots.
                if shot.get('h3_prompt_skill_revision'):
                    st.h3_prompt_skill.validate_shots({'shots':[shot]})
            elif operation in ('connect','disconnect'):
                eid=data.get('entity_id')
                st.entity_from_project(p,eid)
                shot_elements.resolve(p,shot)
                ids=list(shot.get('element_ids',[]))
                if operation=='connect':
                    if eid not in ids:ids.append(eid)
                    shot.update(generation_mode='omni_reference',use_element_references=True)
                else:ids=[item for item in ids if item!=eid]
                shot.update(element_ids=ids,auto_elements=False)
                # Existing character states, manual images, audio and tail choices remain intact.
                video_workflow.references(st,p,shot)
            else:raise ValueError('未知画布操作')
            if any(before.get(key)!=shot.get(key) for key in (*FIELDS,'element_ids','generation_mode','use_element_references')):
                invalidate(st,p,shot)
        st.save_project(p)
        return {'project':st.project_view(p),'node_id':'video:'+shot['id']}
