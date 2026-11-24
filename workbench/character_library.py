"""Local reusable character appearances. Media are copied; original projects stay independent."""
import copy
import json
from pathlib import Path
from portable_paths import DATA
import re
import shutil
import uuid
import canvas_images
import canvas_videos
import video_modes

LIBRARY = DATA / '角色库'
PROFILE_FIELDS = ('name','character_name','appearance_name','canvas_identity','canvas_status','canvas_prompt','voice_prompt','voice_mode')

def identity(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{12}',value):raise ValueError('角色库编号无效')
    return value

def media_file(role_id,name):
    identity(role_id)
    if not isinstance(name,str) or not re.fullmatch(r'[a-f0-9]{12}\.(png|jpg|jpeg|webp|wav|mp3|m4a|flac|ogg|aif|aiff)',name):raise ValueError('角色库文件无效')
    p=(LIBRARY/role_id/name).resolve()
    if not p.is_relative_to(LIBRARY.resolve()) or not p.is_file():raise ValueError('角色库素材不存在')
    return p

def read(role_id):
    p=LIBRARY/identity(role_id)/'role.json'
    if not p.is_file():raise ValueError('角色库记录不存在，请刷新列表')
    return json.loads(p.read_text())

def catalog():
    rows=[]
    for file in LIBRARY.glob('*/role.json'):
        record=read(file.parent.name)
        rows.append({k:record[k] for k in ('id','name','updated_at','appearances')})
    return sorted(rows,key=lambda r:r['updated_at'],reverse=True)

def voice_path(st,p,path):
    if not path:return None
    if not isinstance(path,str) or not any(u.get('path')==path and u.get('kind')=='audio' for u in p.get('uploads',[])):
        raise ValueError('请上传或选择本工程的音频作为参考音色')
    file=st.project_path(p['id'],path)
    video_modes.probe(file,'audio',st.h3_native.FFPROBE)
    return file

def save(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid)
        kind,item=st.entity_from_project(p,data.get('entity_id'))
        if kind!='characters':raise ValueError('只有人物可以存入角色库')
        image=data.get('image');canvas_images.candidate(st,p,item['id'],image)
        voice=voice_path(st,p,item.get('voice_audio')) if item.get('voice_audio') else None
        binding=item.get('character_library') or {}
        role_id=identity(data.get('role_id') or binding.get('role_id')) if data.get('role_id') or binding.get('role_id') else uuid.uuid4().hex[:12]
        existing=(LIBRARY/role_id/'role.json').is_file()
        record=read(role_id) if existing else {'id':role_id,'name':item.get('character_name') or item['name'],'appearances':[]}
        aid=binding.get('appearance_id') if binding.get('role_id')==role_id else None
        previous=next((a for a in record['appearances'] if a['id']==aid),None)
        aid=aid or uuid.uuid4().hex[:12]
        appearance={'id':aid,'name':item.get('appearance_name') or '基础形象','profile':{k:copy.deepcopy(item.get(k,'')) for k in PROFILE_FIELDS},'saved_at':st.now(),
                    'source_project':pid,'source_entity':item['id']}
        folder=LIBRARY/role_id;folder.mkdir(parents=True,exist_ok=True)
        def copy_media(file):
            name=uuid.uuid4().hex[:12]+file.suffix.lower();shutil.copy2(file,folder/name);return name
        appearance['profile']['voice_mode']=item.get('voice_mode') or 'text'
        appearance['image']=copy_media(st.project_path(pid,image))
        if voice:appearance['voice_audio']=copy_media(voice)
        if previous:
            appearance['history']=[*previous.get('history',[]),{k:v for k,v in previous.items() if k!='history'}]
        record['appearances']=[a for a in record['appearances'] if a['id']!=aid]+[appearance];record['updated_at']=st.now()
        temp=folder/('role-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(record,ensure_ascii=False,indent=2));temp.replace(folder/'role.json')
        item['character_library']={'role_id':role_id,'appearance_id':aid};st.save_project(p)
        return {'project':st.project_view(p),'role':record}

def import_appearance(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);record=read(data.get('role_id'))
        appearance=next((a for a in record['appearances'] if a['id']==data.get('appearance_id')),None)
        if not appearance:raise ValueError('请选择角色形象')
        image=media_file(record['id'],appearance['image'])
        voice=media_file(record['id'],appearance['voice_audio']) if appearance.get('voice_audio') else None
        item={k:copy.deepcopy(appearance['profile'].get(k,'')) for k in PROFILE_FIELDS}
        item['voice_mode']=item.get('voice_mode') or 'text'
        eid='characters_'+uuid.uuid4().hex[:12];item.update(id=eid,name=item.get('name') or record['name'],character_name=record['name'],appearance_name=appearance['name'],
            custom=True,canvas_image=True,appearance=item.get('canvas_prompt',''),wardrobe='',role=item.get('canvas_identity',''),identity_group='library:'+record['id'],
            character_library={'role_id':record['id'],'appearance_id':appearance['id']})
        folder=st.project_path(pid,'assets/'+eid+'/library');folder.mkdir(parents=True)
        target=folder/('image'+image.suffix);shutil.copy2(image,target);path=str(target.relative_to(st.project_dir(pid).resolve()))
        if voice:
            audio=folder/('voice'+voice.suffix);shutil.copy2(voice,audio);item['voice_audio']=str(audio.relative_to(st.project_dir(pid).resolve()))
            p.setdefault('uploads',[]).append({'id':uuid.uuid4().hex[:8],'kind':'audio','name':record['name']+'参考音色'+voice.suffix,'path':item['voice_audio'],'created_at':st.now()})
        p.setdefault('analysis',{}).setdefault('characters',[]).append(item)
        asset=st.asset_record(p,eid);asset['versions'].append({'id':uuid.uuid4().hex[:12],'status':'done','mode':'import','images':[path],'created_at':st.now(),'origin':'character_library'});asset['images']=[path]
        result_id='asset:'+eid
        if data.get('beside') in __import__('canvas_workspace').known_nodes(p):canvas_videos.place(p,result_id,data['beside'])
        st.save_project(p);return {'project':st.project_view(p),'node_id':result_id}
