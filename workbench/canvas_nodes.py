"""Reversible canvas operations. Existing timeline shots and source files remain intact."""
import copy
import uuid
import canvas_workspace
import canvas_videos

def edit(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);op=data.get('operation');node_id=data.get('node_id')
        layout=p.setdefault('canvas_workspace',{});hidden=layout.setdefault('hidden_nodes',[])
        if op=='restore':
            if not hidden:raise ValueError('没有可恢复的节点')
            node_id=hidden.pop();st.save_project(p);return {'project':st.project_view(p),'node_id':node_id}
        if node_id not in canvas_workspace.known_nodes(p):raise ValueError('节点不存在，请同步')
        if op=='delete':
            if node_id not in hidden:hidden.append(node_id)
            st.save_project(p);return {'project':st.project_view(p),'node_id':node_id}
        if op!='copy':raise ValueError('未知节点操作')
        new_id=uuid.uuid4().hex[:12]
        if node_id.startswith('asset:'):
            kind,original=st.entity_from_project(p,node_id[6:]);item=copy.deepcopy(original);old_id=item['id'];item['id']=kind+'_'+new_id;item['name']=item['name']+' · 副本'
            item.pop('asset_library_id',None);item.pop('character_library',None)
            p.setdefault('analysis',{}).setdefault(kind,[]).append(item)
            p.setdefault('assets',{})[item['id']]=copy.deepcopy(st.asset_record(p,old_id));result='asset:'+item['id']
        else:
            original=canvas_videos.node(p,node_id);item=copy.deepcopy(original);item['id']=('audio_' if node_id.startswith('audio:') else 'canvas_')+new_id;item['title']=item.get('title','素材')+' · 副本';item.pop('asset_library_id',None)
            if node_id.startswith('audio:'):p.setdefault('canvas_audios',[]).append(item);result='audio:'+item['id']
            else:
                item.update(canvas_standalone=True,shot=1,inherit_previous=False,inherit_previous_manual=True)
                for key in ('audio_segment','audio_reference_timing','previous_tail_pending','video_references','video_versions'):item.pop(key,None)
                p.setdefault('canvas_videos',[]).append(item);result='clip:'+item['id']
        canvas_videos.place(p,result,node_id);st.save_project(p);return {'project':st.project_view(p),'node_id':result}
