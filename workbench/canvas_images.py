"""Image-first canvas operations; outputs are independent, reviewable candidates."""
import copy
import math
import subprocess
import time
import uuid
from pathlib import Path
from PIL import Image, ImageOps
import character_image_edit
import asset_views
import tail_redraw
import video_enhance
import h3_native
import task_diagnostics
import canvas_image_references as image_refs

FIELDS = ('name', 'canvas_identity', 'canvas_status', 'canvas_prompt', 'spatial_anchor', 'character_name', 'appearance_name', 'voice_prompt', 'voice_mode', 'voice_audio')

def base(item):
    return {key:copy.deepcopy(item.get(key)) for key in FIELDS}

def candidate(st,p,eid,path):
    st.entity_from_project(p,eid)
    a=st.asset_record(copy.deepcopy(p),eid)
    version=next((v for v in a['versions'] if path in v.get('images',[]) and v.get('status')=='done'),None)
    if not version:raise ValueError('请先选择本节点已经完成的图片')
    source=st.project_path(p['id'],path)
    if not source.is_file():raise ValueError('参考图片已不存在，请重新选择')
    with Image.open(source) as im:
        if im.width*im.height>40_000_000:raise ValueError('图片超过4000万像素')
        im.verify()
    return version

def validate_parent(st,p,target,eid,path):
    kind,_=st.entity_from_project(p,target)
    parent_kind,parent=st.entity_from_project(p,eid)
    if kind!=parent_kind:raise ValueError('请连接相同类型的参考图：人物连接人物，场景连接场景')
    seen={target}
    while parent:
        if parent['id'] in seen:raise ValueError('参考连线不能形成循环')
        seen.add(parent['id'])
        next_id=(parent.get('canvas_parent') or {}).get('entity_id')
        parent=st.entity_from_project(p,next_id)[1] if next_id else None
    candidate(st,p,eid,path)

def edit(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);op=data.get('operation')
        if op=='create_image':
            kind=data.get('kind')
            if kind not in ('characters','locations','key_objects'):raise ValueError('图片类型不正确')
            item={'id':kind+'_'+uuid.uuid4().hex[:10],'name':str(data.get('name') or ('新人物' if kind=='characters' else '新场景'))[:100],
                  'custom':True,'canvas_image':True,'canvas_prompt':'','canvas_status':'初始','canvas_identity':'','role':''}
            if kind=='characters':item.update(appearance='',wardrobe='')
            else:item.update(description='',spatial_anchor='')
            p.setdefault('analysis',{}).setdefault(kind,[]).append(item)
        elif op=='create_variant':
            kind,original=st.entity_from_project(p,data.get('entity_id'));path=data.get('image')
            candidate(st,p,original['id'],path)
            item={'id':kind+'_'+uuid.uuid4().hex[:10],'name':original['name']+' · 新状态','custom':True,'canvas_image':True,
                  'canvas_derived':True,'canvas_parent':{'entity_id':original['id'],'image':path},
                  'canvas_prompt':'','canvas_status':'新状态','role':original.get('role',''),'canvas_identity':original.get('canvas_identity') or (original.get('role','') if len(original.get('role',''))<=40 else ''),
                  'identity_group':original.get('identity_group') or original['id']}
            if kind=='characters':
                label=str(data.get('appearance_name') or '新状态').strip()[:100]
                prompt=str(data.get('prompt') or '').strip()[:16000]
                item.update(appearance=original.get('appearance',''),wardrobe=original.get('wardrobe',''),voice_prompt=original.get('voice_prompt',''),voice_mode=original.get('voice_mode','text'),voice_audio=original.get('voice_audio',''),character_name=original.get('character_name') or original['name'],appearance_name=label,canvas_status=label,canvas_prompt=prompt,name=(original.get('character_name') or original['name'])+' · '+label)
                if original.get('character_library'):item['character_library']={'role_id':original['character_library']['role_id']}
            else:item.update(description=original.get('description',''),spatial_anchor=original.get('spatial_anchor',''))
            p.setdefault('analysis',{}).setdefault(kind,[]).append(item)
        else:
            kind,item=st.entity_from_project(p,data.get('entity_id'));before=copy.deepcopy(item)
            if op=='save_image':
                supplied=data.get('base')
                if not isinstance(supplied,dict) or not set(('name','canvas_identity','canvas_status','canvas_prompt','spatial_anchor')).issubset(supplied) or any(item.get(k)!=v for k,v in supplied.items()):raise ValueError('图片信息已在其他页面修改，请同步后核对；当前输入保留')
                changes=data.get('changes',{})
                if not isinstance(changes,dict) or set(changes)-set(FIELDS):raise ValueError('图片信息字段不正确')
                for key,value in changes.items():
                    if key not in supplied:raise ValueError('人物信息字段已更新，请同步后重试')
                    if key in {'character_name','appearance_name','voice_prompt','voice_mode','voice_audio'} and kind!='characters':raise ValueError('只有人物可以设置角色与音色')
                    if not isinstance(value,str) or len(value)>(16000 if key=='canvas_prompt' else 4000 if key=='voice_prompt' else 1000):raise ValueError('图片信息过长或格式不正确')
                    item[key]=value.strip()
                if not item.get('name'):raise ValueError('请填写名称')
                if kind=='characters':
                    if (item.get('voice_mode') or 'text') not in {'text','audio'}:raise ValueError('请选择文字或音频音色')
                    if item.get('voice_audio'):
                        import character_library
                        character_library.voice_path(st,p,item['voice_audio'])
                    if item.get('voice_mode')=='audio' and not item.get('voice_audio'):raise ValueError('请先上传参考音频')
                if item.get('canvas_image') and 'canvas_identity' in changes:item['role']=item['canvas_identity']
                if item.get('canvas_image') and 'canvas_prompt' in changes:
                    if kind=='characters':item.update(appearance=item['canvas_prompt'],wardrobe='')
                    else:item['description']=item['canvas_prompt']
            elif op in {'add_reference','remove_reference'}:
                rows=image_refs.links(st,p,item)
                eid=data.get('source_id');path=data.get('image')
                if op=='add_reference':
                    image_refs.validate_link(st,p,item,eid,path)
                    source_kind,source_item=st.entity_from_project(p,eid)
                    rows=[r for r in rows if r['entity_id']!=eid]+[{'entity_id':eid,'path':path,'kind':source_kind,'label':source_item['name']}]
                else:
                    rows=[r for r in rows if not (r['entity_id']==eid and r['path']==path)]
                item['canvas_redraw_links']=rows
            elif op=='connect_image':
                if not item.get('canvas_derived'):raise ValueError('请先从原图创建其他状态图')
                validate_parent(st,p,item['id'],data.get('source_id'),data.get('image'))
                item['canvas_parent']={'entity_id':data['source_id'],'image':data['image']}
            elif op=='disconnect_image':
                if not item.get('canvas_derived'):raise ValueError('本节点没有状态参考输入')
                item['canvas_parent']=None
            else:raise ValueError('未知图片操作')
            if before!=item:
                for shot in [*p.get('shots',[]),*p.get('canvas_videos',[])]:
                    if item['id'] in shot.get('element_ids',[]) or any(x['node_id']=='asset:'+item['id'] for x in shot.get('canvas_image_links',[])):
                        if shot.get('video'):shot.update(video_stale=True,stale_reason='图片节点信息已修改')
                        if not shot.get('canvas_standalone'):st.video_workflow.invalidate(st,p,shot,'图片节点信息已修改')
        st.asset_record(p,item['id'])
        st.save_project(p)
        return {'project':st.project_view(p),'node_id':'asset:'+item['id']}

def input_paths(st,p,item,payload=None):
    return image_refs.inputs(st,p,item,base_input_paths(st,p,item,payload))

def base_input_paths(st,p,item,payload=None):
    # An explicit preview pins the image seen alongside the submitted text.
    if payload and 'reference_image' in payload:
        path=payload['reference_image']
        if not isinstance(path,str) or not path:raise ValueError('请先选择当前要编辑的图片')
        candidate(st,p,item['id'],path)
        return [path]
    reference=item.get('canvas_reference')
    if reference:
        if reference['node_id'].startswith('asset:'):candidate(st,p,reference['node_id'][6:],reference['path'])
        else:
            import canvas_videos
            canvas_videos.source(st,p,reference['node_id'],reference['path'])
        image=st.project_path(p['id'],reference['image'])
        if not image.is_file():raise ValueError('参考图片已不存在，请重新创建节点')
        with Image.open(image) as im:im.verify()
        return [reference['image']]
    parent=item.get('canvas_parent')
    if item.get('canvas_derived'):
        if not parent:raise ValueError('请先把原图连到此状态图的左侧接口')
        validate_parent(st,p,item['id'],parent.get('entity_id'),parent.get('image'))
        return [parent['image']]
    a=st.asset_record(p,item['id'])
    if image_refs.links(st,p,item) or item.get('canvas_origin',{}).get('operation')=='extract_frame':
        current=next((v['images'][0] for v in reversed(a['versions']) if v.get('status')=='done' and v.get('images')),None)
        if current:
            candidate(st,p,item['id'],current);return [current]
    return st.generation_sources(p,item['id']) if a.get('reference_mode')=='image' else []

def validate(st,p,action,payload):
    _,item=st.entity_from_project(p,payload.get('entity_id'))
    if action=='canvas_upscale':
        candidate(st,p,item['id'],payload.get('image'))
        scale=payload.get('scale',2)
        if type(scale) is not int or scale not in (2,4):raise ValueError('超分倍率只能是2倍或4倍')
        with Image.open(st.project_path(p['id'],payload['image'])) as im:
            if max(im.size)*scale>8192 or im.width*im.height*16>64_000_000:raise ValueError('超分尺寸超出预算，请使用更小的图片或2倍倍率')
        if not video_enhance.status()['ready']:raise ValueError('本机Real-ESRGAN超分组件未就绪')
    else:
        prompt=item.get('canvas_prompt')
        if not prompt or not prompt.strip():raise ValueError('请填写描述提示词或图片下方的画面要求')
        refs=input_paths(st,p,item,payload)
        if refs:character_image_edit.require_ready(st.director.CFG)
        elif st.director.CFG.get('image_backend')=='z_image':st.single_image_edit.require_ready(st.director.CFG)

def graph(cfg,names,text,width,height,seed):
    g=character_image_edit.graph(cfg,names[0],text,width,height,seed)
    g['6']['inputs']['prompt']=text
    g['7']['inputs']['prompt']='collage, panels, contact sheet, text, watermark, duplicate subjects'
    for i,name in enumerate(names[1:],2):
        if i>3:raise ValueError('图片编辑最多使用3张输入图片')
        key=str(11+i);g[key]={'class_type':'LoadImage','inputs':{'image':name}}
        for encoder in ('6','7'):g[encoder]['inputs']['image'+str(i)]=[key,0]
    g['11']['inputs']['filename_prefix']='story_pipeline/canvas_image'
    return g

def publish(st,pid,eid,version):
    # Merge with the latest project; never replace selected originals or other edits.
    with st.PROJECT_LOCK:
        fresh=st.load_project(pid);a=st.asset_record(fresh,eid)
        a['versions'].append(version);a['images']=version['images'];a['updated_at']=st.now()
        st.save_project(fresh)

def generate(st,jid,pid,payload):
    p=st.load_project(pid);validate(st,p,'canvas_image',payload)
    kind,item=st.entity_from_project(p,payload['entity_id']);refs=input_paths(st,p,item,payload)
    settings=st.load_settings();width=settings['image_width'];height=settings['image_height']
    vid='canvas-'+uuid.uuid4().hex[:12];folder=st.project_path(pid,'assets/'+item['id']+'/'+vid);folder.mkdir(parents=True)
    target=folder/'image.png';text=item['canvas_prompt']
    prefix='Create ONE coherent image. No panels, grids, contact sheets, captions or watermarks. '
    if refs:
        prefix+=('Preserve the same facial identity from the reference. Apply the requested occupation, clothing, pose and state changes. If the reference is a character sheet, use it to depict ONE person in ONE frame. ' if kind=='characters' else 'Preserve the recognizable location and fixed spatial structure from the reference; apply the requested weather, time, lighting and atmosphere changes. ' if kind=='locations' else 'Use the reference image to preserve the relevant subjects and visual details; apply the requested image changes. ')
    model_refs,reference_prompt=image_refs.prepare(st,p,item,refs,folder)
    prompt=prefix+'\n'+reference_prompt+'\n'+text
    if item.get('canvas_identity'):prompt+='\n'+('Occupation / identity: ' if kind=='characters' else 'Environment type: ')+item['canvas_identity']
    if item.get('canvas_status') not in (None,'','初始','新状态'):prompt+='\nRequested state: '+item['canvas_status']
    st.update_job(jid,message='正在生成单张图片',progress=10)
    if refs:
        result=tail_redraw.execute(st,p,{},target,folder,[st.project_path(pid,x) for x in model_refs],prompt,width,height,graph,'canvas',
                                  'Qwen 正在绘制新的图片状态','画布图片编辑')
    else:
        st.prepare_model_mode('image')
        try:
            seed=int(uuid.uuid4().hex[:8],16)
            workflow=st.reference_graph(pid,'',prompt,width,height,seed,settings['image_steps'])
            h=st.director.queue_and_wait(st.director.CFG['qwen_image_url'],workflow,'画布单张图片')
            im=st.director.first_output(h,'images');root=st.comfy_project_paths(pid)['output'].resolve();source=(root/im.get('subfolder','')/im['filename']).resolve()
            if not source.is_relative_to(root):raise ValueError('生成结果超出工程路径')
            with Image.open(source) as image:image.convert('RGB').save(target)
            result={'backend':st.director.CFG.get('image_backend'),'seed':seed,'steps':settings['image_steps'],'width':width,'height':height}
        finally:
            owned={prompt_id for url,prompt_id in st.JOBS[jid].get('comfy_prompts',[]) if url==st.director.CFG['qwen_image_url']}
            task_diagnostics.cleanup(lambda:st.stop_comfy('qwen_image',allowed_prompt_ids=owned))
    st.check_cancel()
    version={'id':vid,'status':'done','created_at':st.now(),'mode':'image' if refs else 'text','origin':'canvas_single',
             'images':[str(target.relative_to(st.project_dir(pid).resolve()))],'reference_images':refs,'model_reference_images':model_refs,'entity':copy.deepcopy(item),
             'generation_settings':result,'prompt':prompt,'canvas_parent':copy.deepcopy(item.get('canvas_parent'))}
    publish(st,pid,item['id'],version)

def render_upscale(st,source,target,scale):
    """NCNN x4 inference, then resample for an exact 2x result. No source overwrite."""
    st.prepare_model_mode('vision');st.unload_ollama(st.VISION_MODEL)
    raw=target.with_name('model-4x.png');log=target.with_suffix('.log')
    with Image.open(source) as image:
        im=ImageOps.exif_transpose(image).convert('RGB');size=im.size;normalized=target.with_name('input.png');im.save(normalized)
    started=time.monotonic();initial=h3_native.swap_mb();limit=st.load_settings()['h3c_swap_limit_gib']*1024
    with log.open('wb') as output:
        proc=subprocess.Popen([str(video_enhance.BINARY),'-i',str(normalized),'-o',str(raw),'-m',str(video_enhance.MODELS),'-n','realesrgan-x4plus','-s','4','-t','128','-j','1:1:1','-f','png'],cwd=video_enhance.BINARY.parent,stdout=output,stderr=output,start_new_session=True)
        try:
            while proc.poll() is None:
                st.check_cancel()
                if time.monotonic()-started>1200:raise RuntimeError('图片超分超过20分钟，已停止')
                if h3_native.swap_mb()-initial>limit:raise RuntimeError('图片超分交换内存超过设置阈值，已停止')
                time.sleep(.3)
            if proc.returncode:raise RuntimeError('图片超分失败，请查看 '+str(log))
        finally:task_diagnostics.cleanup(lambda:h3_native.stop_process(proc))
    st.check_cancel()
    with Image.open(raw) as im:
        if im.size!=(size[0]*4,size[1]*4):raise ValueError('超分模型输出尺寸异常')
        im.convert('RGB').resize((size[0]*scale,size[1]*scale),Image.Resampling.LANCZOS).save(target)
    raw.unlink();normalized.unlink()
    return {'model':'realesrgan-x4plus','scale':scale,'width':size[0]*scale,'height':size[1]*scale}

def upscale(st,jid,pid,payload):
    p=st.load_project(pid);validate(st,p,'canvas_upscale',payload);eid=payload['entity_id'];source=payload['image'];scale=payload.get('scale',2)
    original=candidate(st,p,eid,source);vid='upscale-'+uuid.uuid4().hex[:12]
    folder=st.project_path(pid,'assets/'+eid+'/'+vid);folder.mkdir(parents=True);target=folder/'image.png'
    st.update_job(jid,message=f'Real-ESRGAN 正在进行{scale}倍超分',progress=15)
    result=render_upscale(st,st.project_path(pid,source),target,scale)
    st.check_cancel()
    version={'id':vid,'status':'done','mode':'upscale','created_at':st.now(),'images':[str(target.relative_to(st.project_dir(pid).resolve()))],
             'source_image':source,'generation_settings':result,'origin':'canvas_upscale'}
    for key in ('reference_layout','panel_edges','layout_review','face_references','face_reference_sheet','state_name','state_prompt'):
        if key in original:version[key]=copy.deepcopy(original[key])
    publish(st,pid,eid,version)
