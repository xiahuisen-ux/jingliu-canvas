"""Recoverable deletion of generated asset images, without losing old video provenance."""
import copy
import json
import os
import shutil
import uuid


def delete(st,pid,eid,path,*,role='result'):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p=st.load_project(pid);st.entity_from_project(p,eid);a=st.asset_record(p,eid)
        if role not in {'input','result'}:raise ValueError('图片区域不正确')
        if role=='input':
            if not isinstance(path,str) or path not in a['source_images']:raise ValueError('只能删除本元素参考图框中的图片')
            source=st.project_path(pid,path)
            record={'id':uuid.uuid4().hex[:12],'path':path,'role':'input','deleted_at':st.now(),'position':a['source_images'].index(path)}
            folder=st.project_path(pid,'回收站/images/'+record['id']);folder.mkdir(parents=True)
            if source.is_file():
                target=folder/source.name
                try:os.link(source,target)
                except OSError:shutil.copy2(source,target)
                record['recovery_file']=str(target.relative_to(st.project_dir(pid).resolve()))
            (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            a['source_images']=[x for x in a['source_images'] if x!=path]
            if a.get('source_image')==path:a['source_image']=''
            a.setdefault('deleted_images',[]).append(record);st.save_project(p)
            return st.project_view(p)
        versions=[v for v in a['versions'] if path in v.get('images',[])]
        if not isinstance(path,str) or not versions:
            raise ValueError('只能删除该元素已有的生成图片')
        source=st.project_path(pid,path)
        affected=[]
        for shot in st.ordered_shots(p):
            refs,_=st.video_workflow.references(st,p,shot)
            if any(r['path']==path for r in refs):affected.append(shot)
        record={'id':uuid.uuid4().hex[:12],'path':path,'role':'result','deleted_at':st.now(),
                'versions':[{'version':copy.deepcopy(v),'position':v['images'].index(path)} for v in versions]}
        folder=st.project_path(pid,'回收站/images/'+record['id']);folder.mkdir(parents=True)
        # Keep original bytes for provenance in completed videos and historical versions.
        # A recovery link also survives an external removal of the original path.
        if source.is_file():
            target=folder/source.name
            try:os.link(source,target)
            except OSError:shutil.copy2(source,target)
            record['recovery_file']=str(target.relative_to(st.project_dir(pid).resolve()))
        (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        for v in versions:
            if path in a['source_images'] and v.get('reference_layout'):
                a.setdefault('source_layouts',{})[path]=v['reference_layout']
            v['images']=[x for x in v['images'] if x!=path];v['views_verified']=False
        for key in ('images','selected_images'):
            a[key]=[x for x in a.get(key,[]) if x!=path]
        for key in ('primary_image',):
            if a.get(key)==path:a[key]=''
        empty_states={v['id'] for v in versions if v.get('state_name') and not v['images']}
        for shot in st.ordered_shots(p):
            for key in ('reference_images','manual_reference_images','excluded_reference_images'):
                if key in shot:shot[key]=[x for x in shot[key] if x!=path]
            for key in ('reference_image','first_frame_image','last_frame_image','tail_reference_image','opening_reference_image'):
                if shot.get(key)==path:shot[key]=''
            if shot.get('character_states',{}).get(eid) in empty_states:
                shot['character_states'].pop(eid)
        if p.get('tail_repair_defaults',{}).get('reference')==path:p['tail_repair_defaults']['reference']=''
        for shot in affected:
            if shot.get('video'):shot.update(video_stale=True,stale_reason='所用参考图片已删除')
            st.video_workflow.invalidate(st,p,shot,'上游参考图片已删除')
        a.setdefault('deleted_images',[]).append(record)
        st.save_project(p)
        return st.project_view(p)


def restore(st,pid,eid,record_id):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p=st.load_project(pid);st.entity_from_project(p,eid);a=st.asset_record(p,eid)
        record=next((r for r in a.get('deleted_images',[]) if r['id']==record_id),None)
        if record is None:raise ValueError('未找到已删除的图片')
        path=record['path'];target=st.project_path(pid,path)
        if record.get('role')=='input':
            if path in a['source_images']:raise ValueError('这张图片已经恢复')
        elif any(path in v.get('images',[]) for v in a['versions']):raise ValueError('这张图片已经恢复')
        if not target.is_file():
            recovery=record.get('recovery_file')
            if not recovery or not st.project_path(pid,recovery).is_file():raise ValueError('图片文件与恢复副本均不存在')
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(st.project_path(pid,recovery),target)
        if record.get('role')=='input':
            a['source_images'].insert(min(record.get('position',len(a['source_images'])),len(a['source_images'])),path)
            a['deleted_images'].remove(record);st.save_project(p);return st.project_view(p)
        for saved in record['versions']:
            old=saved['version'];v=next((v for v in a['versions'] if v['id']==old['id']),None)
            if v is None:
                v={**old,'images':[]};a['versions'].append(v)
            if path not in v['images']:v['images'].insert(min(saved['position'],len(v['images'])),path)
            v['views_verified']=False
        # Restoration does not silently re-select an image or change a shot's references.
        if a['versions'] and path in a['versions'][-1]['images']:a['images']=list(a['versions'][-1]['images'])
        a['deleted_images'].remove(record)
        st.save_project(p)
        return st.project_view(p)
