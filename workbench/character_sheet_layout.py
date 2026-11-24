"""Deterministic four-panel layout; model composition is never trusted for panel widths."""
from pathlib import Path
import math
import re
import asset_views
import single_image_edit

KEYS=('face','front','side','back')
HEAD_KEYS=('front','side','back')

def head_identity(item,back=False):
    """Only visible head traits; clothing/actions otherwise pull the camera back."""
    text=asset_views.visual_description('characters',item)
    parts=re.split(r'[\n，,。；;]+',text)
    head=r'脸|面容|五官|下颌|眉|眼|鼻|唇|嘴|发|胡|须|耳|肤|头|墨镜|眼镜|帽|角|龙|仓鼠|金丝熊|毛色|动画|卡通|写实|亚洲|亚裔|非裔|混血|青年|岁|face|eye|hair|head|skin|beard|glasses|hat|cartoon|dragon|hamster'
    body=r'衬衫|西装|裤|鞋|袜|领带|工牌|公文包|咖啡|美式|手机|麦克风|吉他|贝斯|萨克斯|鼓|步履|抖肩|打响指|垫步|身高|身形|肩线|身材|体格|肌肉|shirt|suit|trousers|shoes|armor|full.body|standing'
    chosen=[s.strip() for s in parts if re.search(head,s,re.I) and not re.search(body,s,re.I)]
    if back:
        chosen=[s for s in chosen if not re.search(r'脸|五官|下颌|眉|眼|鼻|唇|嘴|表情|face|eye|nose|mouth|lip|gaze',s,re.I)]
    return '；'.join(chosen) or '保持参考中的同一个角色及原画风'

def head_prompt(item,key):
    view={'front':'正面高清完整头部，0度，双眼对称',
          'side':'严格左侧高清完整头部，90度，鼻尖朝左，只见侧面轮廓',
          'back':'严格背面高清完整头部，180度，只见后脑、头发与后颈，脸部不可见'}[key]
    return (view+'。紧贴头部的特写构图，裁至下巴下缘，只露极少颈部；完整头顶与下巴之间占画面高度85%至90%。'
            '头部居中，左右只留少量背景，肩膀、胸口、手臂及随身道具全部在画外。'
            'TIGHT HEAD CLOSE-UP, '+{'front':'camera azimuth 0 degrees','side':'camera azimuth 90 degrees','back':'camera azimuth 180 degrees'}[key]+'. '
            'The complete head fills 85 to 90 percent of the canvas height, crown to chin, with minimal margins. '
            'Frame ends immediately below the chin. Shoulders, chest, hands and props are outside the frame. '
            '头部身份特征：'+head_identity(item,back=key=='back')+'。'
            '保持原画风，纯灰背景，柔光，清晰细节。一个头部，一个机位。'
            +('只看后脑和发型，脸朝向背景，完全不回头。' if key=='back' else ''))

def panel_prompt(item,key,headless_front=False):
    if key=='face':return head_prompt(item,'front')
    import asset_views
    identity=asset_views.visual_description('characters',item)
    if key=='back':
        identity='；'.join(s for s in re.split(r'[\n，,。；;]+',identity) if not re.search(r'脸|五官|眉|眼|鼻|唇|嘴|回看|扶墨镜|face|eye|gaze',s,re.I))
    view={
        'face':'高清正脸大特写：相机正对脸部，双眼对称，完整头顶、两侧脸颊和下巴都在画面内。只有一个大头部，头部占画面约80%。ONE straight-on facial close-up, camera azimuth 0 degrees, complete head centered with a small margin, eyes looking directly at the camera.',
        'front':'正面全身：双肩、胸口、膝盖、脚尖正对相机，双臂自然下垂，双手双脚完整。ONE straight FRONT full-body standing view with normal complete head, camera azimuth 0 degrees. The complete standing body occupies 85 percent of image height.',
        'side':'严格左侧全身：头和身体一起朝左，双肩投影重合，鼻尖朝左，头顶到双脚完整。ONE strict LEFT PROFILE full-body standing view at exactly 90 degrees. Only the profile silhouette is visible. Include entire head, hands, tail if present and both feet with margins.',
        'back':'严格背面全身：完全背对相机，后脑、后颈、衣服背面和脚跟朝向镜头。ONE straight REAR full-body standing view at exactly 180 degrees. The character faces the background wall, back of head toward camera. Include hands, tail if present and both feet with margins.',
    }[key]
    if key=='front' and headless_front:
        view='正面服装与体型：保持参考中的颈部以下身体至完整双脚，上方保留灰色空白。ONE straight front clothing/body view from below the neck to both feet, with plain grey space above the neck.'
    # Z-Image uses zeroed negative conditioning. Describe the desired image positively;
    # repeatedly naming collages/contact sheets in its positive prompt can suggest them.
    return ('角色外貌与服饰：'+identity+'\n'+view+
            '\n一张连续画面，只有一个角色，只有这个机位。保持参考角色的画风、发型、体型、服装、颜色和配饰。'
            '纯灰无缝摄影棚背景，均匀柔光，清晰细节。Single continuous studio image of exactly ONE character from ONE camera position. '
            'Preserve the described rendering style and wardrobe. Plain neutral grey background, crisp details, even light. '
            'Keep the requested camera view and framing.')


def validated_crop(value):
    if not isinstance(value,(list,tuple)) or len(value)!=4:raise ValueError('裁切范围应为左、上、右、下四个比例')
    try:x,y,r,b=map(float,value)
    except (ValueError,TypeError):raise ValueError('裁切范围必须是数字') from None
    if not all(math.isfinite(v) for v in (x,y,r,b)) or not 0<=x<r<=1 or not 0<=y<b<=1:raise ValueError('裁切范围须在0到1之间且有有效宽高')
    return [x,y,r,b]


def compose_heads(sources,out,*,crops=None,height=1024):
    """Publish exactly one front/profile/rear triptych, with recorded crop regions."""
    from PIL import Image,ImageOps
    canvas=Image.new('RGB',(height*3,height),(166,166,166));crops=crops or {}
    if set(sources)!=set(HEAD_KEYS):raise ValueError('头部三联图需要正面、侧面和背面来源')
    for i,key in enumerate(HEAD_KEYS):
        with Image.open(sources[key]) as source:
            im=ImageOps.exif_transpose(source).convert('RGB');w,h=im.size
            crop=validated_crop(crops.get(key,[0,0,1,1]))
            im=im.crop(tuple(round(v*(w if j%2==0 else h)) for j,v in enumerate(crop)))
            if not im.width or not im.height:raise ValueError('头部裁切范围过小')
            im=ImageOps.contain(im,(height-16,height-16),Image.Resampling.LANCZOS)
            canvas.paste(im,(i*height+(height-im.width)//2,(height-im.height)//2))
    target=Path(out)/'face-reference-3view.png';target.parent.mkdir(parents=True,exist_ok=True);canvas.save(target)
    return target


def compose(sources,out,*,crops=None,front_neck=.28,side_neck=.30,height=1024):
    from PIL import Image,ImageOps,ImageDraw
    if not all(math.isfinite(float(v)) and .05<=float(v)<=.75 for v in (front_neck,side_neck)):raise ValueError('颈部位置须在5%到75%之间')
    crops=crops or {};images={}
    if set(crops)-set(KEYS):raise ValueError('裁切包含未知视角')
    for key in KEYS:
        with Image.open(sources[key]) as original:
            im=ImageOps.exif_transpose(original).convert('RGB')
            box=validated_crop(crops.get(key,[0,0,1,1]));w,h=im.size
            images[key]=im.crop((round(box[0]*w),round(box[1]*h),round(box[2]*w),round(box[3]*h)))
            if not images[key].width or not images[key].height:raise ValueError('裁切范围过小')
    # Each view is contained, never center-cropped to fill a narrow strip.
    unit=height//2;sheet=Image.new('RGB',(5*unit,height),(166,166,166));safe=sheet.copy()
    for index,key in enumerate(KEYS):
        source=images[key];w,h=source.size
        if key=='front':
            cut=round(h*float(front_neck))
            # Omit everything above the chosen neck line, without inventing anatomy.
            source=source.copy()
            ImageDraw.Draw(source).rectangle((0,0,w,cut),fill=(166,166,166))
        box=(2*unit,height) if key=='face' else (unit,height)
        fitted=ImageOps.contain(source,(box[0]-16,box[1]-16),Image.Resampling.LANCZOS)
        left=0 if index==0 else (index+1)*unit
        x=left+(box[0]-fitted.width)//2;y=(height-fitted.height)//2
        sheet.paste(fitted,(x,y));safe.paste(fitted,(x,y))
        if key in {'side','back'}:
            # Video-only copy contains no second head; preview/download keeps the full side/back.
            ImageDraw.Draw(safe).rectangle((x,y,x+fitted.width,y+math.ceil(fitted.height*float(side_neck))),fill=(166,166,166))
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    sheet.save(out/'character-sheet-4view.png');safe.save(out/'video-reference.png')
    return {'height':height,'front_neck':float(front_neck),'side_neck':float(side_neck),'crops':crops,
            'panel_widths':[2*unit,unit,unit,unit],'sources':{k:str(v) for k,v in sources.items()}}


def generate(st,jid,p,item,version,out,reference,steps,size,state_prompt=''):
    sources={};pid=p['id'];height=min(1024,size);height=max(512,height//64*64)
    source_asset=st.asset_record(p,item['id'])
    refs=reference if isinstance(reference,list) else [reference] if reference else []
    specs={ref:single_image_edit.source_spec(source_asset,ref,st.project_path(pid,ref)) for ref in refs}
    ref_layout={ref:spec['layout'] for ref,spec in specs.items()} if isinstance(reference,list) else specs[reference]['layout'] if reference else None
    ref_edges={ref:spec['edges'] for ref,spec in specs.items()} if isinstance(reference,list) else specs[reference]['edges'] if reference else None
    headless=bool(specs) and all(spec['layout']=='four-view-headless-front' for spec in specs.values())
    view_denoise={key:single_image_edit.MATCHED_VIEW_DENOISE if specs and all(spec['layout'] and not (key=='side' and spec['layout']=='face-front-body-back') for spec in specs.values()) else single_image_edit.CHARACTER_DENOISE for key in KEYS}
    face_crop=source_asset.get('source_face_crop') if reference else None
    for i,key in enumerate(KEYS):
        st.check_cancel()
        prompt=panel_prompt(item,key,headless_front=headless)
        if state_prompt:prompt+=' 本造型变化：'+(head_identity({'appearance':state_prompt}) if key=='face' else state_prompt)
        version['prompts'][key]=prompt
        width=height if key=='face' else height//2
        label={'face':'完整脸部特写','front':'正面服装','side':'侧面','back':'背面'}[key]
        version['view_progress']={'completed':i,'total':6,'current':key,'label':label}
        st.save_project(p)
        model=st.JOBS.get(jid,{}).get('image_model','')
        st.update_job(jid,message=f'{model} · 正在生成 {item["name"]}：{label}（第{i+1}/6次，已完成{i}次）',progress=10+i*13)
        # A previously generated sheet is never fed whole into a single-view redraw.
        graph=st.reference_graph(pid,reference,prompt,width,height,version['seed']+i,steps,character_sheet=True,
                                 character_view=key,reference_layout=ref_layout,reference_crop=face_crop if key=='face' else None,
                                 reference_edges=ref_edges,character_denoise=view_denoise[key])
        result=st.director.queue_and_wait(st.director.CFG['qwen_image_url'],graph,'人物 '+key)
        im=st.director.first_output(result,'images');src=st.comfy_project_paths(pid)['output']/im.get('subfolder','')/im['filename']
        target=out/(key+'-source.png');st.shutil.copy2(src,target);sources[key]=target
        version['view_sources']={k:str(path.relative_to(st.project_dir(pid).resolve())) for k,path in sources.items()}
        version['view_progress']['completed']=i+1
        st.save_project(p)
    layout=compose(sources,out,height=height,front_neck=.08 if headless else .28)
    layout['sources']={k:str(path.relative_to(st.project_dir(pid).resolve())) for k,path in sources.items()}
    version['layout_editor']=layout
    version['conditioning_image']=str((out/'video-reference.png').relative_to(st.project_dir(pid).resolve()))
    version['layout_review']={'status':'needs_review','summary':'四栏已固定拼版；请核对完整脸部和颈部裁切线，必要时展开「调整四视图裁切」。'}
    version['generation_settings'].update(width=height//2*5,height=height,separate_view_generation=True,shared_seed=False,view_seeds={key:version['seed']+i for i,key in enumerate(KEYS)})
    # The existing model-generated front close-up is shared with the new head
    # references. Side/rear close-ups get their own image-model passes, seeded
    # from the corresponding freshly generated full-body view.
    heads={'front':sources['face']}
    for index,key in enumerate(('side','back'),4):
        st.check_cancel();prompt=head_prompt(item,key)
        if state_prompt:prompt+=' 头部状态变化：'+head_identity({'appearance':state_prompt},back=key=='back')
        version['prompts']['head_'+key]=prompt
        version['view_progress']={'completed':index,'total':6,'current':'head_'+key,'label':'独立头部'+key}
        st.save_project(p);st.update_job(jid,message=f'{model} · {item["name"]} · 头部{key}（第{index+1}/6次）',progress=10+index*13)
        ref=str(sources[key].relative_to(st.project_dir(pid).resolve()))
        graph=st.reference_graph(pid,ref,prompt,height,height,version['seed']+index,steps,
                                 character_sheet=True,reference_crop=[.15,0,.85,.27],
                                 character_denoise=single_image_edit.MATCHED_VIEW_DENOISE)
        generated=st.director.queue_and_wait(st.director.CFG['qwen_image_url'],graph,'头部 '+key)
        im=st.director.first_output(generated,'images');src=st.comfy_project_paths(pid)['output']/im.get('subfolder','')/im['filename']
        target=out/('head-'+key+'-source.png');st.shutil.copy2(src,target);heads[key]=target
        version['view_progress']['completed']=index+1;st.save_project(p)
    sheet=compose_heads(heads,out,height=height)
    version['face_reference_sheet']=str(sheet.relative_to(st.project_dir(pid).resolve()))
    version['face_reference_layout']='front-side-back'
    version['face_reference_sources']={k:str(v.relative_to(st.project_dir(pid).resolve())) for k,v in heads.items()}
    version['generation_settings'].update(face_reference_generation=True,face_reference_output_count=1,
        face_reference_seeds={'front':version['seed'],'side':version['seed']+4,'back':version['seed']+5})
    if reference:version['generation_settings'].update(source_layout=ref_layout,source_panel_edges=ref_edges,source_face_crop=face_crop,view_denoise=view_denoise,effective_denoise=max(view_denoise.values()))
    return out/'character-sheet-4view.png'


def revise(st,pid,eid,data):
    import copy,uuid
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);kind,item=st.entity_from_project(p,eid)
        if kind!='characters':raise ValueError('仅人物四视图支持裁切调整')
        asset=st.asset_record(p,eid);old=next((v for v in asset['versions'] if v['id']==data.get('version_id')),None)
        if not old or not old.get('images') or not old.get('layout_editor'):raise ValueError('此旧图没有独立视图来源，请重新生成四视图')
        layout=copy.deepcopy(old['layout_editor']);layout['front_neck']=float(data.get('front_neck',layout['front_neck']));layout['side_neck']=float(data.get('side_neck',layout['side_neck']))
        if 'crops' in data:
            if not isinstance(data['crops'],dict) or set(data['crops'])-set(KEYS):raise ValueError('裁切视角不正确')
            layout.setdefault('crops',{}).update({key:validated_crop(value) for key,value in data['crops'].items()})
        if 'face_crop' in data:layout.setdefault('crops',{})['face']=validated_crop(data['face_crop'])
        sources={key:st.project_path(pid,path) for key,path in layout['sources'].items()}
        if set(sources)!=set(KEYS) or any(not path.is_file() for path in sources.values()):raise ValueError('视图原片缺失，不能裁切')
        version=copy.deepcopy(old);version_id=st.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
        out=st.project_path(pid,f'assets/{eid}/{version_id}')
        composed=compose(sources,out,crops=layout.get('crops'),front_neck=layout['front_neck'],side_neck=layout['side_neck'],height=layout['height'])
        composed['sources']=layout['sources'];path=str((out/'character-sheet-4view.png').relative_to(st.project_dir(pid).resolve()))
        version.update(id=version_id,created_at=st.now(),images=[path],layout_editor=composed,layout_only=True,source_version=old['id'],reference_layout='four-view-headless-front',conditioning_image=str((out/'video-reference.png').relative_to(st.project_dir(pid).resolve())),layout_review={'status':'needs_review','summary':'已按裁切线保存新版本，请预览后选用。'})
        heads=old.get('face_reference_sources') or old.get('face_references')
        if heads and set(heads)==set(HEAD_KEYS):
            heads=dict(heads,front=layout['sources']['face'])
            head_crops=dict(old.get('face_reference_crops',{}),front=composed['crops'].get('face',[0,0,1,1]))
            sheet=compose_heads({k:st.project_path(pid,v) for k,v in heads.items()},out,crops=head_crops,height=layout['height'])
            version.update(face_reference_sheet=str(sheet.relative_to(st.project_dir(pid).resolve())),face_reference_layout='front-side-back',face_reference_sources=heads,face_reference_crops=head_crops)
            version.pop('face_references',None)
        asset['versions'].append(version);asset['images']=[path];asset['updated_at']=st.now();st.save_project(p)
        return p


def reuse_source(st,pid,eid,data):
    """Explicit user action: copy existing artwork into results without any model."""
    import uuid
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid);kind,item=st.entity_from_project(p,eid)
        asset=st.asset_record(p,eid);ref=data.get('path')
        if kind!='characters' or ref not in asset['source_images']:raise ValueError('请选择本人物参考图框中的图片')
        source=st.project_path(pid,ref)
        if not source.is_file():raise ValueError('参考原图不存在')
        spec=single_image_edit.source_spec(asset,ref,source)
        version_id=st.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
        target=st.project_path(pid,f'assets/{eid}/{version_id}/reference-original{source.suffix}')
        target.parent.mkdir(parents=True,exist_ok=True);st.shutil.copy2(source,target)
        path=str(target.relative_to(st.project_dir(pid).resolve()))
        version={'id':version_id,'created_at':st.now(),'images':[path],'status':'done','mode':'import',
                 'origin':'reference_copy','reference':ref,'view_count':1,'name':'参考原图 · 未重绘'}
        if spec['layout']:
            version.update(reference_layout=spec['layout'],source_panel_edges=spec['edges'])
        asset['versions'].append(version);asset['images']=[path];asset['updated_at']=st.now()
        st.save_project(p);return p
