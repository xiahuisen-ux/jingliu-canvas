"""Cross-project library for finished images, scenes, video and audio."""
import copy
import json
from pathlib import Path
from portable_paths import DATA
import shutil
import uuid
import canvas_images
import canvas_videos
import character_library

LIBRARY=DATA/'资产库'

def read(identity):
    character_library.identity(identity);file=LIBRARY/identity/'asset.json'
    if not file.is_file():raise ValueError('资产不存在，请刷新资产库')
    return json.loads(file.read_text())

def media_file(identity,name):
    record=read(identity)
    if name!=record['file']:raise ValueError('资产文件不存在')
    file=(LIBRARY/identity/name).resolve()
    if not file.is_relative_to(LIBRARY.resolve()) or not file.is_file():raise ValueError('资产文件已缺失')
    return file

def catalog():
    records=[read(p.parent.name) for p in LIBRARY.glob('*/asset.json')]
    return sorted(records,key=lambda x:x['updated_at'],reverse=True)

def save(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);node_id=data.get('node_id');path=data.get('path')
        if not isinstance(node_id,str):raise ValueError('请选择节点')
        if node_id.startswith('asset:'):
            kind,item=st.entity_from_project(p,node_id[6:])
            if kind=='characters':raise ValueError('角色请存入角色资产库')
            canvas_images.candidate(st,p,item['id'],path);file=st.project_path(pid,path)
            category='locations' if kind=='locations' else 'images'
            profile={k:copy.deepcopy(item.get(k,'')) for k in ('name','canvas_identity','canvas_status','canvas_prompt','spatial_anchor','description')}
        else:
            item,file=canvas_videos.source(st,p,node_id,path);category='audio' if node_id.startswith('audio:') else 'videos'
            profile={'title':item.get('title','素材'),'saved_request':item.get('canvas_request',''),'canvas_reference_kind':item.get('canvas_reference_kind','silent_video')}
        identity=item.get('asset_library_id') or uuid.uuid4().hex[:12];character_library.identity(identity)
        folder=LIBRARY/identity;folder.mkdir(parents=True,exist_ok=True);name=uuid.uuid4().hex[:12]+file.suffix.lower();shutil.copy2(file,folder/name)
        previous=read(identity) if (folder/'asset.json').is_file() else None
        record={'id':identity,'category':category,'name':item.get('name') or item.get('title') or '素材','file':name,'profile':profile,'updated_at':st.now(),'source_project':pid,'source_node':node_id}
        if previous:record['history']=[*previous.get('history',[]),{k:v for k,v in previous.items() if k!='history'}]
        temporary=folder/(uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2));temporary.replace(folder/'asset.json');item['asset_library_id']=identity;st.save_project(p)
        return {'project':st.project_view(p),'asset':record}

def import_asset(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);record=read(data.get('asset_id'));file=media_file(record['id'],record['file']);category=record['category'];suffix=uuid.uuid4().hex[:12]
        folder=st.project_path(pid,'library-imports/'+suffix);folder.mkdir(parents=True);target=folder/file.name;shutil.copy2(file,target);path=str(target.relative_to(st.project_dir(pid).resolve()))
        if category in {'images','locations'}:
            kind='locations' if category=='locations' else 'key_objects';item=copy.deepcopy(record['profile']);item.update(id=kind+'_'+suffix,name=record['name'],custom=True,canvas_image=True,asset_library_id=record['id'])
            p.setdefault('analysis',{}).setdefault(kind,[]).append(item);asset=st.asset_record(p,item['id']);asset['versions'].append({'id':suffix,'status':'done','mode':'import','images':[path],'created_at':st.now(),'origin':'asset_library'});asset['images']=[path];node_id='asset:'+item['id']
        elif category=='videos':
            item=canvas_videos.blank(st,record['name']);info=canvas_videos.upload_info(target,'video',st.h3_native.FFPROBE);item.update(video=path,status='video_ready',video_result={'duration':info['duration'],'imported':True},asset_library_id=record['id'],library_source_request=record['profile'].get('saved_request',''),canvas_reference_kind=record['profile'].get('canvas_reference_kind','silent_video'));p.setdefault('canvas_videos',[]).append(item);node_id='clip:'+item['id']
        elif category=='audio':
            info=canvas_videos.upload_info(target,'audio',st.h3_native.FFPROBE);item={'id':'audio_'+suffix,'title':record['name'],'audio':path,'duration':info['duration'],'asset_library_id':record['id']};p.setdefault('canvas_audios',[]).append(item);node_id='audio:'+item['id']
        else:raise ValueError('资产类型无效')
        st.save_project(p);return {'project':st.project_view(p),'node_id':node_id}
