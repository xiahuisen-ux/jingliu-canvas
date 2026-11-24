"""Shot reference resolution and serial h3.c Metal video execution."""
import copy
from pathlib import Path
import time
import uuid
import h3_native
import h3_prompt_skill
import character_states
import video_timing
import video_modes
import project_audio
import video_choices
import secrets
import tail_repair
import opening_frames

AUTHOR_FIELDS = ('description','camera','dialogue','motion_prompt','character_actions','duration','canvas_request','canvas_mentions')


def authored_input(shot):
    return {k:copy.deepcopy(shot.get(k)) for k in AUTHOR_FIELDS}


def predecessor(st, p, shot):
    ordered=st.ordered_shots(p)
    index=next((i for i,s in enumerate(ordered) if s is shot or s.get('id')==shot.get('id')),0)
    return ordered[index-1] if index and video_modes.uses_previous(shot) else None


def references(st,p,shot,materialize=False):
    video_modes.validate_fields(shot)
    if materialize:tail_repair.validate(st,p,shot)
    selected=video_modes.mode(shot)
    shot['reference_warnings']=[];shot['reference_blockers']=[]
    if selected=='text':return [],False
    if selected=='first_frame':return frame_anchors(st,p,shot,materialize)
    items,pending=image_references(st,p,shot,materialize)
    performance=project_audio.performance_reference(p,shot)
    if performance:
        if not st.project_path(p['id'],performance['path']).is_file():performance['missing']=True
        items.append(performance)
    for ref in shot.get('omni_media',[]):
        if performance and ref['path']==performance['path']:continue
        path=st.project_path(p['id'],ref['path'])
        from canvas_videos import reference_label
        item={'path':ref['path'],'kind':ref['kind'],'source':'media','label':reference_label(p,ref['path'])}
        if not path.is_file():item['missing']=True
        items.append(item)
    if not performance:
        present=character_states.present_ids(shot)
        seen={r['path'] for r in items}
        for character in p.get('analysis',{}).get('characters',[]):
            audio=character.get('voice_audio')
            if character['id'] in present and character.get('voice_mode')=='audio' and audio and audio not in seen:
                items.append({'path':audio,'kind':'audio','source':'character_voice','audio_role':'timbre','character_name':character.get('character_name') or character['name'],'label':(character.get('character_name') or character['name'])+' · 音色','missing':not st.project_path(p['id'],audio).is_file()});seen.add(audio)
    excluded=set(shot.get('canvas_excluded_audio',[]))
    return [r for r in items if not (r.get('kind')=='audio' and r['path'] in excluded)],pending


def frame_anchors(st,p,shot,materialize):
    items=[];pending=False;pid=p['id']
    source=shot.get('first_frame_source','image')
    if source=='qwen':
        try:
            spec=opening_frames.inputs(st,p,shot,st.video_settings())
            result=opening_frames.current(st,p,spec)
            if materialize:
                result=opening_frames.prepare(st,p,shot,st.video_settings())
                st.prepare_model_mode('video')
            if result:items.append({'path':result['image'],'source':'first_frame','kind':'anchor','label':'Qwen 起始构图高清首帧'})
            else:pending=True
        except (ValueError,OSError) as error:
            if materialize:raise
            shot['reference_blockers'].append(str(error))
    elif source=='previous_tail':
        previous=predecessor(st,p,shot)
        if previous is None:
            shot['reference_blockers'].append('第一段没有上一段尾帧，请上传或选择首帧图片')
        else:
            video=previous.get('video')
            valid=video and not previous.get('video_stale') and st.project_path(pid,video).is_file()
            tail=previous.get('actual_tail_frame') if previous.get('tail_source_video')==video else None
            if materialize:
                if not valid:raise ValueError('请先生成上一段有效视频，再用其尾帧作为本段首帧')
                if not tail or not st.project_path(pid,tail).is_file():
                    tail=st.extract_video_tail(pid,video,previous['id'])
                    previous.update(actual_tail_frame=tail,tail_source_video=video);st.save_project(p)
            if valid and tail and st.project_path(pid,tail).is_file():
                tail=tail_repair.resolve(st,p,shot,previous,tail,materialize)
                items.append({'path':tail,'source':'first_frame','kind':'anchor','label':'首帧 · 上一段接续图'})
            else:pending=True
    elif shot.get('first_frame_image'):
        items.append({'path':shot['first_frame_image'],'source':'first_frame','kind':'anchor','label':'指定首帧'})
    else:shot['reference_blockers'].append('首帧生视频需要上传或选择一张首帧图片')
    if shot.get('last_frame_image'):
        items.append({'path':shot['last_frame_image'],'source':'last_frame','kind':'anchor','label':'指定尾帧'})
    for item in items:
        path=st.project_path(pid,item['path'])
        if path.suffix.lower() not in video_modes.IMAGE_EXTENSIONS or not path.is_file():item['missing']=True
    return items,pending


def validate_inputs(st,p,shot,refs,pending=False):
    tail_repair.validate(st,p,shot)
    if shot.get('reference_blockers'):raise ValueError('；'.join(shot['reference_blockers']))
    if any(r.get('missing') for r in refs):raise ValueError('参考图片或媒体缺失，请重新选择；未启动模型')
    selected=video_modes.mode(shot)
    if selected=='first_frame':
        if shot.get('first_frame_source')=='qwen':opening_frames.validate(st,p,shot,st.video_settings())
        if not pending and not any(r['source']=='first_frame' for r in refs):raise ValueError('请先选择首帧图片')
    elif selected=='omni_reference':
        for item in refs:
            if item.get('kind') in {'video','silent_video','audio'}:
                item.update(video_modes.probe(st.project_path(p['id'],item['path']),item['kind'],h3_native.FFPROBE))
                if item.get('audio_role')=='performance' and abs(item['duration']-video_timing.shot_duration(shot))>.05:
                    raise ValueError('本段录音时长与视频不一致，请重新剪分音频；未启动模型')
        video_modes.validate_references(refs,int(pending))
        if 'generation_mode' in shot and not refs and not pending:raise ValueError('全能参考需要至少一张图片或一段视频；仅文字请选文生视频')
    validate('h3c',sum(r.get('kind','image')=='image' for r in refs)+int(pending and selected=='omni_reference'))


def image_references(st,p,shot,materialize=False):
    items=[];pending=False;pid=p['id']
    shot['reference_warnings']=[]
    shot['reference_blockers']=[]
    previous=predecessor(st,p,shot)
    if previous:
        video=previous.get('video')
        tail=previous.get('actual_tail_frame') if previous.get('tail_source_video')==video else None
        valid=video and not previous.get('video_stale') and st.project_path(pid,video).is_file()
        if materialize:
            if not valid:raise ValueError('请先生成上一段有效视频，再生成本段；换场可关闭尾帧继承')
            if not tail or not st.project_path(pid,tail).is_file():
                tail=st.extract_video_tail(pid,video,previous['id'])
                previous.update(actual_tail_frame=tail,tail_source_video=video)
                st.save_project(p)
        if valid and tail and st.project_path(pid,tail).is_file():
            original_tail=tail
            tail=tail_repair.resolve(st,p,shot,previous,tail,materialize)
            items.append({'path':tail,'original_path':original_tail,'tail_repaired':tail!=original_tail,'source':'previous_tail','label':f"上一段 {previous['shot']} 实际尾帧"})
        else:pending=True
    if not previous and shot.get('opening_reference_image'):
        items.append({'path':shot['opening_reference_image'],'source':'opening_frame','label':'新镜头高清开场参考'})
    if shot.get('use_element_references',True):
        st.associate_shot_references(character_states.reference_project(p,shot),shot)
        if materialize and shot.get('reference_blockers'):raise ValueError('；'.join(shot['reference_blockers']))
        for binding in shot.get('reference_bindings',[]):
            import asset_views
            name=st.entity_from_project(p,binding['entity_id'])[1].get('name',binding['entity_id'])
            asset=p.get('assets',{}).get(binding['entity_id'],{})
            version=next((v for v in asset.get('versions',[]) if binding['image'] in v.get('images',[])),{})
            conditioned=version.get('conditioning_image')
            input_path=conditioned or binding['image']
            if conditioned and not st.project_path(pid,conditioned).is_file():raise ValueError('四视图的面部隔离参考缺失，请重新保存裁切布局')
            items.append({'path':input_path,'preview_path':binding['image'],'face_only_conditioning':bool(conditioned),'source':'element','entity_id':binding['entity_id'],'label':name+' · '+asset_views.LABELS.get(binding.get('view'), '参考图'),
                          'character_sheet':bool(binding.get('character_sheet_layout')) or binding.get('view') in {'character-sheet','character-sheet-4view'},'character_sheet_layout':binding.get('character_sheet_layout') or ('four-view' if binding.get('view')=='character-sheet-4view' else 'face-front-body-back'),'reference_role':'appearance','entity_kind':binding.get('entity_kind')})
    manual=shot.get('manual_reference_images',[])
    if not isinstance(manual,list) or any(not isinstance(x,str) for x in manual):raise ValueError('参考图列表格式错误')
    excluded=shot.get('excluded_reference_images',[])
    if not isinstance(excluded,list) or any(not isinstance(path,str) for path in excluded):raise ValueError('排除参考图列表格式错误')
    items.extend({'path':path,'source':'manual','label':next((st.entity_from_project(p,link['node_id'][6:])[1]['name'] for link in shot.get('canvas_image_links',[]) if link['path']==path),'补充参考图')} for path in manual if path not in excluded)
    unique=[];seen=set()
    for item in items:
        path=st.project_path(pid,item['path'])
        if path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'} or not path.is_file():
            if materialize:raise ValueError('参考图缺失或格式不支持：'+item['path'])
            item={**item,'missing':True}
        if item['path'] not in seen:unique.append(item);seen.add(item['path'])
    return unique,pending


def validate(backend, count):
    if backend!='h3c':raise ValueError('ComfyUI 视频后端已移除，仅支持 h3.c Metal')
    if count>9:raise ValueError('h3.c 最多输入 9 张参考图，包含上一段尾帧')
    state=h3_native.status()
    if not state['ready']:raise ValueError('h3.c 部署未就绪：'+'；'.join(state['missing']))


def invalidate(st,p,shot,reason):
    ordered=st.ordered_shots(p);index=next((i for i,x in enumerate(ordered) if x.get('id')==shot.get('id')),0)
    for following in ordered[index+1:]:
        if not video_modes.uses_previous(following):break
        if following.get('video'):following.update(video_stale=True,stale_reason=reason)
    if p.get('final_video'):
        p.setdefault('invalidated_final_videos',[]).append({'video':p.pop('final_video'),'created_at':st.now(),'reason':reason})
    p.pop('final_review',None)


def render(st,jid,p,shot,settings,label,progress,commit=True,resolved=None):
    pid=p['id'];backend=settings.get('video_backend','h3c')
    input_snapshot=authored_input(shot)
    input_previous=predecessor(st,p,shot)
    previous_video=input_previous.get('video') if input_previous else None
    refs,pending=references(st,p,shot,True) if resolved is None else (resolved,False)
    validate(backend,0)
    validate_inputs(st,p,shot,refs,pending)
    project_audio.validate_timeline(p)
    audio_options=project_audio.mux_options(st,p,shot)
    selected=video_modes.mode(shot)
    anchors={r['source']:r['path'] for r in refs if r.get('kind')=='anchor'}
    model_refs=[r for r in refs if r.get('kind')!='anchor']
    if not (shot.get('description') or shot.get('motion_prompt') or shot.get('canvas_request')):raise ValueError('请先填写镜头文字内容')
    prompt=st.shot_prompt(p,shot,'Scene: '+shot.get('description','')+'\nMotion: '+shot.get('motion_prompt','')+'\nDialogue: '+shot.get('dialogue',''))
    for ref,tag in video_modes.numbered(model_refs):
        instruction='Use this continuity frame for opening pose, relative positions and framing. Preserve the corrected exposure and color without progressive darkening. Use the original character appearance references for identity, facial details and clothing; do not inherit blur or malformed details from the preceding frame.' if ref['source']=='previous_tail' else ('Use this only as an auxiliary appearance reference for the corresponding character, object or environment. The text specifies composition, positions, actions and camera movement; do not copy the reference image pose, framing or camera angle and do not treat it as the first frame. Ignore all writing, labels and graphic overlays in this reference.' if ref['source']=='element' else 'Use this image to preserve the corresponding subject appearance. Ignore all writing, labels and graphic overlays in this reference.')
        if ref['source']=='opening_frame':instruction='Use this image for the new shot opening composition, pose and scene lighting. Use original character references for facial identity and clothing. This is an auxiliary composition reference, not a forced first frame.'
        if ref.get('kind') in {'video','silent_video','audio'}:instruction='Use this reference for the motion, visual style or sound requested in the shot; do not invent additional subjects or dialogue.'
        if ref.get('audio_role')=='performance':instruction=h3_prompt_skill.performance_schedule(ref,tag,{})
        prompt+=f"\n{tag} ({ref['label']}): {instruction}"
        if ref.get('character_sheet'):
            import asset_views
            prompt+=' '+asset_views.sheet_usage(ref.get('character_sheet_layout'))
    out=st.project_dir(pid)/('videos' if commit else 'comparisons');out.mkdir(exist_ok=True)
    target=out/f"{shot['id']}_{backend}_{uuid.uuid4().hex[:8]}.mp4"
    raw=target.with_name(target.stem+'_source.mp4')
    steps=settings.get('h3c_steps',8)
    duration=video_timing.shot_duration(shot,settings.get('video_duration',10))
    prompt+=f'\nOutput one continuous {duration}-second shot. Fit all actions into {duration} seconds.'
    if shot.get('h3_prompt_skill_revision'):
        # Resolve labels only after reference selection and predecessor-tail extraction.
        prompt=h3_prompt_skill.render(shot.get('motion_prompt',''),model_refs,duration,st.director.NO_VISIBLE_TEXT,editor_notes=h3_prompt_skill.editor_notes(shot))
        # A bound performance already supplies voice, words and timing. Global
        # voice notes may contain the whole character arc, outside this segment.
        voice='' if any(r.get('audio_role')=='performance' for r in model_refs) else character_states.voices(p,shot)
        if voice:
            marker='\n\noverall_soundscape:'
            prompt=prompt.replace(marker,'\n'+voice+marker,1)
    if shot.get('audio_segment') and shot['audio_segment'].get('mode')!='generated' and selected!='omni_reference':
        prompt+='\nNo audio reference is supplied in this mode. Vocal timing is guided only by the written directions; the prepared master is added after generation.'
    state_text=character_states.state_instructions(p,shot)
    if state_text:
        marker='\n\noverall_soundscape:'
        prompt=prompt.replace(marker,'\n'+state_text+marker,1) if marker in prompt else prompt+'\n'+state_text
    if anchors:
        note=' Begin from the supplied first-frame image; preserve its opening composition and subjects, then follow the action timeline.'
        if 'last_frame' in anchors:note+=' End at the supplied last-frame image.'
        marker='\n\noverall_soundscape:'
        prompt=prompt.replace(marker,note+marker,1) if marker in prompt else prompt+note
    for ref,tag in video_modes.numbered(model_refs):
        if ref.get('audio_role')=='timbre':prompt+=f"\n{tag} is the voice timbre reference for {ref.get('character_name') or ref['label']}. Preserve this speaker's vocal tone when the script requires speech; follow the script's words and timing, do not copy the sample's words or add speech to silent roles."
    if shot.get('canvas_request'):
        from canvas_videos import mention_text
        request=mention_text(shot,refs)
        prompt+='\n\nAdditional user generation/editing requirements (these override conflicting earlier visual directions; reference tags identify the actual supplied media):\n'+request
    seed=secrets.randbelow(2147483647)
    started=time.monotonic();metrics={}
    prompt_file=target.with_suffix('.prompt.txt')
    prompt_file.write_text(prompt,encoding='utf-8')
    st.update_job(jid,message=f'{label} · {video_modes.MODES[selected]} · {len(refs)} 项输入',progress=progress)
    metrics=h3_native.generate(prompt=prompt,references=[st.project_path(pid,r['path']) for r in model_refs if r.get('kind','image')=='image'],
        media_references=[{**r,'path':st.project_path(pid,r['path'])} for r in model_refs if r.get('kind','image')!='image'],
        first_frame=st.project_path(pid,anchors['first_frame']) if 'first_frame' in anchors else None,
        last_frame=st.project_path(pid,anchors['last_frame']) if 'last_frame' in anchors else None,
        width=settings['video_width'],height=settings['video_height'],duration=duration,steps=steps,
        layers=settings.get('h3c_layers',50),reuse=settings.get('h3c_reuse',1),
        reference_video_max_pixels=settings.get('h3c_reference_video_max_pixels',0),
        swap_limit_gib=settings.get('h3c_swap_limit_gib',8),
        streaming=settings.get('h3c_ssd_streaming',False),resident=settings.get('h3c_resident',True),stall_minutes=settings.get('h3c_stall_minutes',10),
        seed=seed,output=raw,log_path=out/(target.stem+'.log'),ffmpeg=st.get_ffmpeg(),
        check_cancel=st.check_cancel,on_progress=lambda message:st.update_job(jid,message=f'{label} · {message}'))
    st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(raw),*audio_options,'-t',str(duration),'-r','24',
                  '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
                  '-c:a','aac','-b:a','192k','-movflags','+faststart',str(target)])
    result={**metrics,'created_at':st.now(),'seed':seed,'backend':backend,'video':str(target.relative_to(st.project_dir(pid))),
            'source_video':str(raw.relative_to(st.project_dir(pid))), 'prompt_path':str(prompt_file.relative_to(st.project_dir(pid))), 'seconds':round(time.monotonic()-started,2),
            'settings':{'width':settings['video_width'],'height':settings['video_height'],'steps':steps,'duration':duration,
                        'layers':settings.get('h3c_layers',50),'reuse':settings.get('h3c_reuse',1),
                        'reference_video_max_pixels':settings.get('h3c_reference_video_max_pixels',0),
                        'output_encoding':{'codec':'libx264','preset':'fast','crf':18,'audio':'aac','audio_bitrate':'192k'}},
            'references':refs,'generation_mode':selected if refs or selected=='text' else 'text','status':'done',
            'input_snapshot':input_snapshot}
    if commit:
        caller_shot=shot
        tail=st.extract_video_tail(pid,result['video'],shot['id'])
        with st.PROJECT_LOCK:
            # Inference used a fixed prompt. Publish onto the latest document,
            # never write its old in-memory script over a concurrent API edit.
            p=st.load_project(pid);shot=st.find_shot(p,shot['id'])
            previous=predecessor(st,p,shot)
            take=dict(video=result['video'],source_video=result['source_video'],video_result=result,
                      video_mode='first_frame' if anchors else 'reference_video' if refs else 'text_elements',
                      actual_tail_frame=tail,tail_source_video=result['video'],
                      continuity_source_video=previous_video)
            continuity_changed=bool(input_previous and (not previous or previous.get('video')!=previous_video or previous.get('video_stale')))
            if authored_input(shot)!=input_snapshot or continuity_changed:
                result.update(superseded=True,note='生成期间已改稿：本版本使用提交时的旧稿')
                shot.setdefault('media_history',[]).append(take)
                st.save_project(p)
                if jid in st.JOBS:
                    st.update_job(jid,superseded_shot_ids=[*st.JOBS[jid].get('superseded_shot_ids',[]),shot['id']])
            else:
                video_choices.archive(shot)
                invalidate(st,p,shot,'上一段视频已更新，需要按新尾帧重新生成')
                shot.update(**take,status='video_ready',video_stale=False)
                shot.pop('review',None);shot.pop('stale_reason',None);shot.pop('face_refine_report',None);st.save_project(p)
                if shot.get('audio_segment',{}).get('mode')=='generated':
                    remaining=[s for s in p['shots'] if s.get('audio_segment',{}).get('mode')=='generated' and (not s.get('video') or s.get('video_stale'))]
                    if not remaining:
                        project_audio.prepare_master(st,p);st.save_project(p)
            published_shot=copy.deepcopy(shot)
            caller_shot.clear();caller_shot.update(published_shot)
    return result
