"""Pinned video references and independent canvas results; never rewrite source media."""
import copy
import json
import math
from pathlib import Path
import re
import subprocess
import uuid

import canvas_workspace
import video_choices
import video_enhance
import video_modes
import video_timing
import video_workflow


def node(p, node_id):
    prefix, _, identity = str(node_id).partition(':')
    rows = p.get('shots', []) if prefix == 'video' else p.get('canvas_videos', []) if prefix == 'clip' else p.get('canvas_audios', []) if prefix == 'audio' else []
    for item in rows:
        if item['id'] == identity:
            return item
    raise ValueError('视频节点已不存在，请同步画布')


def paths(item):
    return list(dict.fromkeys([v['video'] for v in video_choices.versions(item)] +
                             [v['video'] for v in item.get('enhanced_versions', []) if v.get('video')] + item.get('audio_history',[]) +
                             ([item['audio']] if item.get('audio') else [])))


def source(st, p, node_id, path):
    item = node(p, node_id)
    if not isinstance(path, str) or path not in paths(item):
        raise ValueError('请选择该视频节点中已保存的版本')
    file = st.project_path(p['id'], path)
    extensions=video_modes.AUDIO_EXTENSIONS if str(node_id).startswith('audio:') else video_modes.VIDEO_EXTENSIONS
    if not file.is_file() or file.suffix.lower() not in extensions:
        raise ValueError('视频文件缺失或格式不支持')
    return item, file


def reference_kind(p,node_id):
    if node_id.startswith('audio:'):return 'audio'
    return 'video' if node(p,node_id).get('canvas_reference_kind')=='video' else 'silent_video'


def upload_info(file, kind, ffprobe):
    """Canvas imports can be long; H3 duration limits apply only to references."""
    response=subprocess.run([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(file)],capture_output=True,text=True,timeout=30)
    try:data=json.loads(response.stdout)
    except ValueError:raise ValueError('无法读取导入素材')
    wanted='audio' if kind=='audio' else 'video'
    stream=next((x for x in data.get('streams',[]) if x.get('codec_type')==wanted),None)
    if response.returncode or not stream:raise ValueError('文件没有有效的'+('音频' if wanted=='audio' else '视频'))
    duration=float(stream.get('duration') or data.get('format',{}).get('duration',0))
    if not math.isfinite(duration) or duration<=0:raise ValueError('无法确认素材时长')
    return {'duration':duration,'has_audio':any(x.get('codec_type')=='audio' for x in data['streams'])}


def reference_label(p,path):
    for collection in ('canvas_audios','canvas_videos','shots'):
        for item in p.get(collection,[]):
            if path in paths(item):return item.get('title') or Path(path).name
    return next((u.get('name') for u in p.get('uploads',[]) if u.get('path')==path and u.get('name')),Path(path).name)


def blank(st, title='新的视频镜头', duration=None):
    return dict(id='canvas_'+uuid.uuid4().hex[:12], shot=1, title=title[:100], description='', camera='', dialogue='',
                motion_prompt='', duration=video_timing.validate_duration(duration or st.load_settings()['video_duration']),
                exact_duration=True, canvas_standalone=True, status='planned', generation_mode='text',
                auto_elements=False, element_ids=[], inherit_previous=False, inherit_previous_manual=True,
                use_element_references=True, reference_angle_mode='main', manual_reference_images=[])


def place(p, output_id, source_id):
    layout = p.setdefault('canvas_workspace', {})
    positions = layout.setdefault('positions', {})
    base = positions.get(source_id, {'x':1080, 'y':150})
    x, y = base['x']+480, base['y']
    while any(abs(v['x']-x)<380 and abs(v['y']-y)<300 for v in positions.values()):
        y += 360
    positions[output_id] = {'x':x, 'y':y}
    layout['version'] = 1


def invalidate(p, item, st):
    if not item.get('canvas_standalone'):
        canvas_workspace.invalidate(st, p, item)
    else:
        video_choices.archive(item)
        for key in video_choices.RESULT_FIELDS:
            item.pop(key, None)
        item['status'] = 'planned'


def refs(st, p, item):
    view = copy.deepcopy(p)
    shot = copy.deepcopy(item)
    if item.get('canvas_standalone'):
        view.pop('audio_timeline', None)
        view.pop('script', None)
        view['shots'] = [shot]
    return video_workflow.references(st, view, shot)[0]


def mention_text(item, references):
    """Resolve visible @tokens only against the actual, ordered model inputs."""
    text = item.get('canvas_request') or ''
    bindings = item.get('canvas_mentions') or []
    if not isinstance(text, str) or len(text)>16000 or not isinstance(bindings, list) or len(bindings)>30:
        raise ValueError('视频要求或素材引用格式不正确')
    tags = {}
    model_refs = [r for r in references if r.get('kind') != 'anchor']
    for ref, tag in video_modes.numbered(model_refs):
        for path in (ref['path'], ref.get('preview_path')):
            if path:tags[path] = tag
    for ref in references:
        if ref.get('kind') == 'anchor':
            tags[ref['path']] = 'the supplied '+('first' if ref['source']=='first_frame' else 'last')+' frame'
    replacements = {}
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding)-{'token','path'}:
            raise ValueError('素材引用格式不正确')
        token, path = binding.get('token'), binding.get('path')
        if not isinstance(token, str) or not token.startswith('@') or len(token)<2 or len(token)>200 or not isinstance(path, str):
            raise ValueError('素材引用格式不正确')
        if token not in text:continue
        if token in replacements and replacements[token][0] != path:
            raise ValueError('同名素材引用不明确，请重新选择 @素材')
        if path not in tags:
            raise ValueError('引用素材已断开或换版，请重新选择 '+token)
        replacements[token] = (path, tags[path])
    if replacements:
        pattern = '|'.join(re.escape(t) for t in sorted(replacements, key=len, reverse=True))
        text = re.sub(pattern, lambda m:replacements[m[0]][1], text)
    if '@' in text:
        raise ValueError('有未绑定的 @素材，请从引用列表选择后再生成')
    return text.strip()


def derive(st,p,data):
    """Create a connected draft. Merely choosing a node type never runs inference."""
    import canvas_images
    kind=data.get('kind');source_id=data.get('source_id');path=data.get('path')
    if kind not in {'image','video','audio','character'}:raise ValueError('请选择图片、视频、音频或角色')
    if not isinstance(source_id,str):raise ValueError('请选择来源节点')
    if source_id.startswith('asset:'):
        _,original=st.entity_from_project(p,source_id[6:]);canvas_images.candidate(st,p,original['id'],path)
        is_image=True;title=original.get('name','图片')
    else:
        if not source_id.startswith(('video:','clip:')):raise ValueError('请从图片或视频接口创建')
        original,file=source(st,p,source_id,path);is_image=False;title=original.get('title','视频')
    suffix=uuid.uuid4().hex[:12]
    origin={'node_id':source_id,'path':path,'operation':'reference','created_at':st.now()}
    if kind=='video':
        item=blank(st,title+' · 新视频')
        item['generation_mode']='omni_reference'
        if is_image:
            # Pin the exact preview without changing the shared source-node selection.
            item['manual_reference_images']=[path]
            item['canvas_image_links']=[{'node_id':source_id,'path':path}]
        else:
            ref_kind=reference_kind(p,source_id);video_modes.probe(file,ref_kind,st.h3_native.FFPROBE)
            item.update(omni_media=[{'kind':ref_kind,'path':path}],canvas_video_links=[{'node_id':source_id,'path':path,'kind':ref_kind}])
        p.setdefault('canvas_videos',[]).append(item);result_id='clip:'+item['id']
    elif kind=='audio':
        item={'id':'audio_'+suffix,'title':title+' · 音频','canvas_origin':origin,'audio':'','duration':0}
        p.setdefault('canvas_audios',[]).append(item);result_id='audio:'+item['id']
    else:
        reference=path
        if not is_image:
            # Image editing takes the pinned first frame, not the entire video.
            output=st.project_path(p['id'],'frames/reference-'+suffix+'.png');output.parent.mkdir(parents=True,exist_ok=True)
            st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(file),'-map','0:v:0','-frames:v','1','-an',str(output)])
            from PIL import Image
            with Image.open(output) as im:im.verify()
            reference=str(output.relative_to(st.project_dir(p['id']).resolve()));origin['frame']='first'
        group='characters' if kind=='character' else 'key_objects'
        item={'id':group+'_'+suffix,'name':title+(' · 新角色' if kind=='character' else ' · 新图片'),'custom':True,'canvas_image':True,
              'canvas_prompt':'','canvas_identity':'','canvas_status':'初始','role':'','canvas_origin':origin,
              'canvas_reference':{'node_id':source_id,'path':path,'image':reference}}
        if kind=='character':item.update(appearance='',wardrobe='')
        else:item.update(description='',spatial_anchor='')
        p.setdefault('analysis',{}).setdefault(group,[]).append(item);st.asset_record(p,item['id']);result_id='asset:'+item['id']
    place(p,result_id,source_id)
    return result_id


def remove_reference(st,p,item,data):
    """Disconnect only this target's reference, keeping source files and timeline audio."""
    current=refs(st,p,item)
    match=next((r for r in current if r.get('source')==data.get('source') and r['path']==data.get('path')),None)
    if not match:raise ValueError('该参考素材已变更，请同步后重试')
    paths={match['path'],match.get('preview_path',match['path'])}
    source=match['source'];eid=match.get('entity_id')
    if eid:
        item['element_ids']=[x for x in item.get('element_ids',[]) if x!=eid]
        item['auto_elements']=False
        paths.update(x['path'] for x in item.get('canvas_image_links',[]) if x['node_id']=='asset:'+eid)
    item['canvas_image_links']=[x for x in item.get('canvas_image_links',[]) if x['path'] not in paths and x['node_id']!='asset:'+str(eid)]
    item['manual_reference_images']=[x for x in item.get('manual_reference_images',[]) if x not in paths]
    item['canvas_video_links']=[x for x in item.get('canvas_video_links',[]) if x['path'] not in paths]
    item['omni_media']=[x for x in item.get('omni_media',[]) if x['path'] not in paths]
    if match.get('kind')=='audio':item['canvas_excluded_audio']=sorted(set(item.get('canvas_excluded_audio',[]))|paths)
    if source=='previous_tail' or (source=='first_frame' and item.get('first_frame_source')=='previous_tail'):
        item.update(inherit_previous=False,inherit_previous_manual=True)
    if source=='opening_frame':item.pop('opening_reference_image',None)
    if source=='first_frame':
        item.pop('first_frame_image',None);item['first_frame_source']='image'
        if not item.get('last_frame_image'):item['generation_mode']='omni_reference'
    if source=='last_frame':item.pop('last_frame_image',None)
    origin=item.get('canvas_origin',{})
    if origin.get('operation')=='reference' and (origin.get('path') in paths or origin.get('node_id')=='asset:'+str(eid)):
        origin['detached']=True
    remaining=refs(st,p,item)
    available={r.get('preview_path',r['path']) for r in remaining}|{r['path'] for r in remaining}
    removed=[b for b in item.get('canvas_mentions',[]) if b.get('path') not in available]
    text=item.get('canvas_request','')
    for binding in sorted(removed,key=lambda b:len(b.get('token','')),reverse=True):
        if binding.get('token'):text=text.replace(binding['token'],binding['token'].lstrip('@'))
    item['canvas_request']=text
    item['canvas_mentions']=[b for b in item.get('canvas_mentions',[]) if b.get('path') in available]
    if not remaining and not video_modes.uses_previous(item) and item.get('generation_mode')!='first_frame':item['generation_mode']='text'


def edit(st, pid, data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid)
        p = st.load_project(pid)
        op = data.get('operation')
        if op == 'derive':
            node_id=derive(st,p,data)
        elif op == 'attach_audio':
            node_id=data.get('node_id')
            if not str(node_id).startswith('audio:'):raise ValueError('请选择音频节点')
            item=node(p,node_id);path=data.get('path')
            upload=next((u for u in p.get('uploads',[]) if u.get('path')==path and u.get('kind')=='audio'),None)
            if not upload:raise ValueError('请先上传本工程的音频')
            info=upload_info(st.project_path(pid,path),'audio',st.h3_native.FFPROBE)
            if item.get('audio'):item.setdefault('audio_history',[]).append(item['audio'])
            item.update(audio=path,duration=info['duration'],title=upload.get('name') or item['title'])
        elif op == 'create':
            item = blank(st, str(data.get('title') or '新的视频镜头'))
            p.setdefault('canvas_videos', []).append(item)
            node_id = 'clip:'+item['id']
        elif op == 'import':
            path = data.get('path')
            upload = next((u for u in p.get('uploads', []) if u.get('path')==path and u.get('kind') in {'video','silent_video','audio'}), None)
            if not upload:raise ValueError('请先上传本工程的视频素材')
            info = upload_info(st.project_path(pid,path),upload['kind'],st.h3_native.FFPROBE)
            if upload['kind']=='audio':
                item={'id':'audio_'+uuid.uuid4().hex[:12],'title':upload.get('name') or Path(path).name,'audio':path,'duration':info['duration']}
                p.setdefault('canvas_audios',[]).append(item);node_id='audio:'+item['id']
            else:
                item = blank(st, upload.get('name') or Path(path).name)
                item.update(video=path, status='video_ready', video_result={'duration':info['duration'], 'imported':True})
                p.setdefault('canvas_videos', []).append(item)
                node_id = 'clip:'+item['id']
            if data.get('beside'):place(p, node_id, data['beside'])
        else:
            node_id = data.get('node_id')
            if not isinstance(node_id,str) or not node_id.startswith(('video:','clip:')):raise ValueError('请选择目标视频节点')
            item = node(p, node_id)
            before = copy.deepcopy(item)
            if op == 'save':
                if data.get('base') != canvas_workspace.shot_base(item):
                    raise ValueError('该视频已在其他页面修改，请同步后核对；输入保留')
                changes = data.get('changes', {})
                if not isinstance(changes, dict) or set(changes)-set(canvas_workspace.FIELDS):raise ValueError('视频字段不正确')
                for key, value in changes.items():
                    if key=='duration':value=video_timing.validate_duration(value)
                    elif key=='canvas_mentions':
                        if not isinstance(value,list):raise ValueError('素材引用格式不正确')
                    elif not isinstance(value,str) or len(value)>60000:raise ValueError('提示词格式或长度不正确')
                    item[key]=copy.deepcopy(value)
                # Validate bindings before invalidating any old results.
                mention_text(item, refs(st,p,item))
                if not item.get('canvas_standalone'):
                    st.project_audio.validate_timeline(p)
                    video_timing.update_timelines(p, {item['id']:before})
                    if item.get('h3_prompt_skill_revision'):st.h3_prompt_skill.validate_shots({'shots':[item]})
            elif op=='remove_reference':
                remove_reference(st,p,item,data)
            elif op in {'connect_image','disconnect_image'}:
                eid=data.get('entity_id');st.entity_from_project(p,eid)
                ids=list(item.get('element_ids', []))
                if op=='connect_image':
                    if eid not in ids:ids.append(eid)
                    item.update(generation_mode='omni_reference',use_element_references=True)
                else:
                    ids=[x for x in ids if x!=eid]
                    removed={x['path'] for x in item.get('canvas_image_links',[]) if x['node_id']=='asset:'+eid}
                    item['canvas_image_links']=[x for x in item.get('canvas_image_links',[]) if x['node_id']!='asset:'+eid]
                    item['manual_reference_images']=[x for x in item.get('manual_reference_images',[]) if x not in removed]
                item.update(element_ids=ids,auto_elements=False)
            elif op in {'connect_video','disconnect_video'}:
                source_id=data.get('source_id');path=data.get('path')
                if op=='connect_video':
                    source(st,p,source_id,path)
                    if source_id==node_id:raise ValueError('不能将视频连接到自身')
                    seen=set()
                    def reaches(current):
                        if current==node_id:return True
                        if current in seen:return False
                        seen.add(current)
                        return any(reaches(x['node_id']) for x in node(p,current).get('canvas_video_links',[]))
                    if reaches(source_id):raise ValueError('视频参考连线不能形成循环')
                    kind=reference_kind(p,source_id)
                    video_modes.probe(st.project_path(pid,path),kind,st.h3_native.FFPROBE)
                    links=[x for x in item.get('canvas_video_links',[]) if x['node_id']!=source_id]
                    old_paths={x['path'] for x in item.get('canvas_video_links',[]) if x['node_id']==source_id}
                    links.append({'node_id':source_id,'path':path,'kind':kind})
                    item['omni_media']=[x for x in item.get('omni_media',[]) if x['path'] not in old_paths|{path}]+[{'kind':kind,'path':path}]
                    item.update(canvas_video_links=links,generation_mode='omni_reference')
                    item['canvas_excluded_audio']=[x for x in item.get('canvas_excluded_audio',[]) if x!=path]
                else:
                    removed={x['path'] for x in item.get('canvas_video_links',[]) if x['node_id']==source_id and (path is None or path==x['path'])}
                    item['canvas_video_links']=[x for x in item.get('canvas_video_links',[]) if x['path'] not in removed]
                    item['omni_media']=[x for x in item.get('omni_media',[]) if x['path'] not in removed]
                video_modes.validate_fields(item)
            else:raise ValueError('未知视频画布操作')
            if op!='remove_reference' and item.get('canvas_standalone') and not item.get('element_ids') and not item.get('omni_media') and not item.get('manual_reference_images'):
                item['generation_mode']='text'
            if before!=item:invalidate(p,item,st)
        st.save_project(p)
        return {'project':st.project_view(p),'node_id':node_id}


def validate(st, p, action, payload):
    node_id=payload.get('node_id')
    if action=='canvas_video_generate':
        item=node(p,node_id)
        if not item.get('canvas_standalone'):raise ValueError('请使用原分段视频生成入口')
        request=mention_text(item,refs(st,p,item))
        if not (request or item.get('description') or item.get('motion_prompt')):raise ValueError('请填写视频生成要求')
        work=copy.deepcopy(p);work.pop('audio_timeline',None);work.pop('script',None);shot=copy.deepcopy(item);work['shots']=[shot]
        r,pending=video_workflow.references(st,work,shot)
        video_workflow.validate_inputs(st,work,shot,r,pending)
        return
    item,file=source(st,p,node_id,payload.get('video'))
    info=video_choices.media_info(st,p['id'],payload['video'])
    if action=='canvas_video_upscale':
        scale=payload.get('scale')
        if type(scale)!=int or scale not in (2,4):raise ValueError('请选择2倍或4倍')
        if max(info['width'],info['height'])*scale>4096 or info['width']*info['height']*scale*scale>4096*2160:
            raise ValueError('增强输出超过4K像素预算，请降低倍率')
        if not video_enhance.status()['ready']:raise ValueError('Real-ESRGAN尚未就绪')
    elif action=='canvas_trim_video':
        start,end=payload.get('start'),payload.get('end')
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in (start,end)) or not 0<=start<end<=info['duration']+.02:
            raise ValueError('请选择原视频范围内的有效起止时间')
        if end-start<.1:raise ValueError('截取片段至少需要0.1秒')
    elif action=='canvas_extract_frame':
        if payload.get('frame') not in {'first','last','current'}:raise ValueError('请选择首帧、尾帧或当前帧')
        if payload['frame']=='current':
            value=payload.get('time')
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=info['duration']+.1:
                raise ValueError('当前播放时间无效，请重新定位视频')
    else:raise ValueError('未知视频任务')
    return info


def run(st,jid,pid,action,payload):
    p=st.load_project(pid);info=validate(st,p,action,payload)
    node_id=payload['node_id'];item=node(p,node_id)
    if action=='canvas_video_generate':
        work=copy.deepcopy(p);work.pop('audio_timeline',None);work.pop('script',None)
        shot=copy.deepcopy(item);work['shots']=[shot]
        shot['description']=shot.get('description') or shot.get('canvas_request','')
        st.prepare_model_mode('video')
        try:result=video_workflow.render(st,jid,work,shot,st.video_settings(),'画布视频',10,commit=False)
        finally:
            import sys
            if sys.exc_info()[0] is not None or not st.video_settings().get('h3c_resident',True):st.h3_native.stop_all()
        st.check_cancel()
        with st.PROJECT_LOCK:
            fresh=st.load_project(pid);target=node(fresh,node_id)
            take={'video':result['video'],'source_video':result['source_video'],'video_result':result}
            if canvas_workspace.shot_base(target)!=canvas_workspace.shot_base(item):
                target.setdefault('media_history',[]).append(take)
            else:
                video_choices.archive(target);target.update(**take,status='video_ready',video_stale=False)
            st.save_project(fresh)
        st.update_job(jid,result_node_id=node_id)
        return result
    path=payload['video'];file=st.project_path(pid,path)
    origin={'node_id':node_id,'path':path,'operation':'upscale' if action=='canvas_video_upscale' else 'trim' if action=='canvas_trim_video' else 'extract_frame',
            'created_at':st.now(),'source_size':file.stat().st_size,'source_mtime_ns':file.stat().st_mtime_ns}
    suffix=uuid.uuid4().hex[:12]
    if action=='canvas_trim_video':
        start,end=payload['start'],min(payload['end'],info['duration']);duration=end-start
        output=st.project_path(pid,'clips/canvas-'+suffix+'.mp4');output.parent.mkdir(parents=True,exist_ok=True)
        st.update_job(jid,message='正在截取视频片段',progress=10)
        st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(file),'-ss',str(start),'-t',str(duration),'-map','0:v:0','-map','0:a?','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(output)])
        checked=video_choices.media_info(st,pid,str(output.relative_to(st.project_dir(pid).resolve())))
        if checked['duration']<=0:raise ValueError('截取结果为空，原片已保留')
        origin.update(start=start,end=end,duration=checked['duration'])
        created=blank(st,item.get('title','视频')+f' · {start:g}–{end:g}s',max(5,min(15,round(duration))))
        for key in ('description','camera','dialogue','motion_prompt','character_actions','canvas_request','canvas_mentions','element_ids','use_element_references','reference_angle_mode','manual_reference_images','canvas_image_links','canvas_video_links','omni_media','canvas_excluded_audio','character_states'):
            if key in item:created[key]=copy.deepcopy(item[key])
        created['generation_mode']='omni_reference'
        actual=refs(st,p,created)
        if not actual:created['generation_mode']='text'
        allowed={r['path'] for r in actual}|{r.get('preview_path') for r in actual}
        bindings=created.get('canvas_mentions',[])
        for binding in sorted(bindings,key=lambda b:len(b.get('token','')),reverse=True):
            if binding.get('path') not in allowed and binding.get('token'):created['canvas_request']=created.get('canvas_request','').replace(binding['token'],binding['token'].lstrip('@'))
        created['canvas_mentions']=[b for b in bindings if b.get('path') in allowed]
        created.update(video=str(output.relative_to(st.project_dir(pid).resolve())),video_result={'duration':checked['duration'],'trimmed':True},status='video_ready',canvas_origin=origin)
        result_id='clip:'+created['id']
    elif action=='canvas_video_upscale':
        st.prepare_model_mode('vision');st.unload_ollama(st.VISION_MODEL)
        output=st.project_path(pid,'enhanced/canvas-'+suffix+'.mp4')
        swap=st.h3_native.swap_mb();settings=st.load_settings()
        def report(done,total,elapsed):
            st.check_cancel()
            if st.h3_native.swap_mb()-swap>settings['h3c_swap_limit_gib']*1024:raise RuntimeError('视频增强交换新增超过保护阈值')
            st.update_job(jid,message=f'视频超分 {done}/{total} 帧',progress=min(98,5+int(90*done/max(total,1))))
        result=video_enhance.enhance(st,file,output,payload['scale'],report)
        origin['scale']=payload['scale']
        created=blank(st,item.get('title','视频')+f" · {payload['scale']}×",item.get('duration'))
        result.update(video=str(output.relative_to(st.project_dir(pid).resolve())),source_video=path)
        created.update(video=result['video'],video_result=result,status='video_ready',canvas_origin=origin)
        result_id='clip:'+created['id']
    else:
        frame=payload['frame'];origin['frame']=frame
        output=st.project_path(pid,'frames/canvas-'+suffix+'.png');output.parent.mkdir(parents=True,exist_ok=True)
        command=[st.get_ffmpeg(),'-y']
        # Decode a bounded tail and overwrite a temporary PNG through the final decoded frame.
        if frame=='last' or (frame=='current' and payload['time']>=info['duration']):
            command+=['-sseof',str(-min(2,info['duration'])),'-i',str(file),'-map','0:v:0','-an','-update','1']
            origin['time']=info['duration'];origin['time_is_end_boundary']=True
        else:
            at=payload.get('time',0) if frame=='current' else 0
            command+=['-i',str(file),'-ss',str(at),'-map','0:v:0','-frames:v','1','-an']
            origin['time']=at
        st.run_ffmpeg(command+[str(output)])
        from PIL import Image
        with Image.open(output) as im:im.verify()
        label={'first':'首帧','last':'尾帧','current':'当前帧'}[frame]
        created={'id':'frame_'+suffix,'name':item.get('title','视频')+' · '+label,'description':'','custom':True,
                 'canvas_image':True,'canvas_identity':'视频抽帧','canvas_status':label,'canvas_prompt':'','canvas_origin':origin}
        import canvas_image_references
        created['canvas_redraw_links']=canvas_image_references.from_video(st,p,node_id)
        created['canvas_prompt']='保持抽帧画面的构图、机位、姿态和人物数量，结合关联人物图修复身份与服装细节，结合场景图修复环境细节，重绘为一张清晰连贯的画面。'
        result_id='asset:'+created['id']
    if action in {'canvas_video_upscale','canvas_trim_video'} and item.get('canvas_reference_kind')=='video':created['canvas_reference_kind']='video'
    st.check_cancel()
    if not output.is_file() or not output.stat().st_size:raise ValueError('任务未产生有效输出')
    with st.PROJECT_LOCK:
        fresh=st.load_project(pid)
        if action in {'canvas_video_upscale','canvas_trim_video'}:fresh.setdefault('canvas_videos',[]).append(created)
        else:
            fresh.setdefault('analysis',{}).setdefault('key_objects',[]).append(created)
            asset=st.asset_record(fresh,created['id'])
            relative=str(output.relative_to(st.project_dir(pid).resolve()))
            asset['versions'].append({'id':suffix,'status':'done','mode':'import','images':[relative],'created_at':st.now(),'canvas_origin':origin})
            asset['images']=[relative]
        place(fresh,result_id,node_id);st.save_project(fresh)
    st.update_job(jid,result_node_id=result_id)
    return {'node_id':result_id,'origin':origin}
