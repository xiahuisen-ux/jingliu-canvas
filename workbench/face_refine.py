"""H3 FaceRefine tracking/compositing plus native Metal video-seed refinement."""
import copy
from functools import lru_cache
import json
import os
from pathlib import Path
from portable_paths import BACKENDS
import secrets
import subprocess
import time
import uuid

import asset_views
import single_image_edit
import character_states
import h3_native
import task_diagnostics
import video_workflow

DEPLOY=BACKENDS/'H3FaceRefine-Metal'
PYTHON=DEPLOY/'venv/bin/python'
SCRIPT=DEPLOY/'face_runtime.py'

@lru_cache(maxsize=4)
def native_ready(path,mtime,size):
    """Lazy protocol probe; --validate cannot load model weights."""
    try:
        result=subprocess.run([path,'--validate'],input='',capture_output=True,text=True,check=True,timeout=10)
        prefix=h3_native.h3_resident.PREFIX.decode('ascii')
        events=[json.loads(line[len(prefix):]) for line in result.stdout.splitlines() if line.startswith(prefix)]
        return any(e.get('event')=='ready' and e.get('protocol')==1 and e.get('validate_only') is True
                   and 'face_refine' in (e.get('features') or []) for e in events)
    except (OSError,TypeError,ValueError,subprocess.SubprocessError):return False

def status():
    missing=[str(p) for p in (PYTHON,SCRIPT,DEPLOY/'models/face_yolov8n.pt',DEPLOY/'upstream/nodes.py') if not p.is_file()]
    worker=h3_native.h3_resident.WORKER
    if not worker.is_file() or not native_ready(str(worker),worker.stat().st_mtime_ns,worker.stat().st_size):
        missing.append('H3 常驻程序尚未更新面部精修接口')
    return {'ready':not missing,'missing':missing,'engine':'h3.c Metal + H3 FaceRefine',
            'upstream':'https://github.com/Carasibana/ComfyUI-H3-FaceRefine',
            'adaptation':'native video seed; original crop/stitch nodes; mouth protection'}

def supervise(st,jid,phase,request,directory,settings):
    path=directory/(phase+'-request.json');path.write_text(json.dumps(request,ensure_ascii=False,indent=2))
    log=directory/(phase+'.log');baseline=h3_native.swap_mb();started=last_progress=time.monotonic();offset=0
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','PYTHONUSERBASE')}
    env.update(MPLCONFIGDIR=str(DEPLOY/'cache/matplotlib'),YOLO_CONFIG_DIR=str(DEPLOY/'cache/yolo'))
    with log.open('wb') as stream:
        process=subprocess.Popen([str(PYTHON),'-E','-s','-u',str(SCRIPT),phase,str(path)],env=env,
                                 stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    with h3_native._lock:h3_native._processes.add(process)
    try:
        while process.poll() is None:
            st.check_cancel()
            with log.open('rb') as stream:stream.seek(offset);chunk=stream.read(65536);offset=stream.tell()
            if chunk:
                last_progress=time.monotonic()
                for line in chunk.decode(errors='replace').splitlines():
                    if line.startswith('@face-refine@'):
                        try:st.update_job(jid,message='H3 面部精修 · '+json.loads(line[13:])['stage'])
                        except (ValueError,KeyError):pass
            delta=h3_native.swap_mb()-baseline
            if delta>settings.get('h3c_swap_limit_gib',8)*1024:
                raise RuntimeError('面部精修交换内存保护触发；原片已保留')
            h3_native.progress_message('面部精修 '+phase,time.monotonic()-last_progress,settings.get('h3c_stall_minutes',10)*60)
            time.sleep(.5)
        st.check_cancel()
        if process.returncode:raise RuntimeError('面部精修'+phase+'失败，请查看 '+str(log))
    finally:
        task_diagnostics.cleanup(lambda:h3_native.stop_process(process))
        with h3_native._lock:h3_native._processes.discard(process)
    return round(time.monotonic()-started,2)

def characters(st,p,shot,directory):
    """Use head views belonging to the selected character/state version only.

    Legacy sheets provide a front crop as a compatibility input; side/rear heads
    are not invented, and newly generated separate refs never inflate base inputs.
    """
    from PIL import Image,ImageOps
    result=[]
    for item in p.get('analysis',{}).get('characters',[]):
        if item['id'] not in shot.get('element_ids',[]):continue
        asset=p.get('assets',{}).get(item['id'],{})
        chosen=asset.get('selected_images',[])
        state=shot.get('character_states',{}).get(item['id'])
        versions=[v for v in asset.get('versions',[]) if v.get('status')=='done' and
                  ((state and (v.get('id')==state or v.get('state_name')==state)) or
                   (not state and any(path in chosen for path in v.get('images',[]))))]
        refs={};version=character_states.state_version(p,item['id'],state) if state else versions[-1] if versions else None
        if version:
            refs={key:str(st.project_path(p['id'],path)) for key,path in version.get('face_references',{}).items()
                  if key in {'front','side','back'} and st.project_path(p['id'],path).is_file()}
            # The user-facing artifact is one triptych. Split only inside this
            # refinement job, so the tracker never sees three heads as one face.
            sheet=version.get('face_reference_sheet')
            if sheet and st.project_path(p['id'],sheet).is_file():
                with Image.open(st.project_path(p['id'],sheet)) as source:
                    image=ImageOps.exif_transpose(source).convert('RGB');width,height=image.size
                    if width!=height*3:raise ValueError('面部三联图应为正面／侧面／背面三等宽方形栏')
                    refs={}
                    for i,key in enumerate(('front','side','back')):
                        path=directory/(item['id']+'-'+key+'-reference.png')
                        image.crop((i*height,0,(i+1)*height,height)).save(path);refs[key]=str(path)
        if not refs.get('front'):
            source=next(iter(version.get('images',[]) if version else chosen),None)
            if not source:continue
            path=st.project_path(p['id'],source)
            if not path.is_file():continue
            with Image.open(path) as original:
                image=ImageOps.exif_transpose(original).convert('RGB')
                spec=single_image_edit.source_spec(asset,source,path)
                if spec['layout']:
                    box=single_image_edit.view_crop(spec['layout'],'face',spec['edges'])
                    width,height=image.size;image=image.crop((round(box[0]*width),round(box[1]*height),round(box[2]*width),round(box[3]*height)))
                front=directory/(item['id']+'-front-reference.png');image.save(front)
                refs['front']=str(front)
        result.append({'id':item['id'],'name':item.get('name',item['id']),
                       'appearance':asset_views.visual_description('characters',item)+((' Selected state: '+version.get('state_prompt',version.get('state_name',''))) if version and version.get('state_name') else ''),
                       'references':refs,'legacy_front_only':len(refs)==1})
    return result

def publish_report(st,jid,pid,shot_id,source,record):
    with st.PROJECT_LOCK:
        p=st.load_project(pid);shot=st.find_shot(p,shot_id)
        if shot.get('video')==source:shot['face_refine_report']=copy.deepcopy(record);st.save_project(p)
    if record.get('status')=='skipped':
        job=st.JOBS.get(jid,{})
        st.update_job(jid,face_refine_skipped=[*job.get('face_refine_skipped',[]),shot_id],
                      message='面部精修跳过：'+('；'.join(record.get('warnings',[])) or '没有人物参考')+'，原片保留')

def run(st,jid,pid,payload,settings=None):
    settings=settings or st.video_settings();p=st.load_project(pid);shot=st.find_shot(p,payload['shot_id'])
    source=payload.get('source_video') or shot.get('video')
    if not source or not st.project_path(pid,source).is_file():raise ValueError('请先生成本段视频')
    if not status()['ready']:raise RuntimeError('H3 FaceRefine 未就绪：'+str(status()['missing']))
    snapshot=video_workflow.authored_input(shot)
    directory=st.project_path(pid,'videos/face-refined/'+uuid.uuid4().hex[:12]);directory.mkdir(parents=True)
    profiles=characters(st,p,shot,directory)
    if not profiles:
        st.update_job(jid,message='面部精修跳过：本段没有可用的人物头部参考，原片保留')
        record={'status':'skipped','reason':'no_character_reference','source_video':source,'warnings':['本段没有可用的人物头部参考']}
        task_diagnostics.write(directory/'result.json',record);publish_report(st,jid,pid,shot['id'],source,record);return record
    ffmpeg=st.get_ffmpeg();source_path=st.project_path(pid,source)
    # Release the base DiT/decoder before the detector runtime or another canvas
    # is started. All phases run inside the workbench's existing MODEL_LOCK.
    h3_native.stop_all()
    request={'source':str(source_path),'directory':str(directory),'characters':profiles,
             'size':settings.get('h3c_face_size',512),'ffmpeg':ffmpeg}
    started=time.monotonic();stage='prepare';record={'source_video':source,'status':'running'}
    record_path=directory/'result.json'
    try:
        supervise(st,jid,'prepare',request,directory,settings)
        prepared=json.loads((directory/'prepared.json').read_text());tracks=prepared['tracks']
        if not tracks:
            record.update(status='skipped',warnings=prepared['warnings']);publish_report(st,jid,pid,shot['id'],source,record);return record
        audio=directory/'original-reference.wav'
        probe=subprocess.run([str(h3_native.FFPROBE),'-v','error','-select_streams','a','-show_entries','stream=index',
                              '-of','json',str(source_path)],capture_output=True,text=True,check=True)
        has_audio=bool(json.loads(probe.stdout)['streams'])
        if has_audio:st.run_ffmpeg([ffmpeg,'-n','-i',str(source_path),'-vn','-ar','32000','-ac','2',str(audio)])
        stage='refine'
        for index,track in enumerate(tracks):
            st.check_cancel();h3_native.stop_all()
            views=[k for k in ('front','side','back') if k in track['references']]
            images=[track['references'][k] for k in views]
            prompt=('subject_definitions:\n<Subject 1> is '+track['appearance']+'. '+
                    ' '.join(f'<Picture {i+1}> shows the same subject head from '+views[i]+'.' for i in range(len(images)))+
                    '\n\nsummary:\n[reference generation] Refine only the existing head crop. Preserve the exact head trajectory, pose, expression, identity and lighting. Improve clear facial detail without changing the shot.'+
                    '\n\ndetailed_description:\n[Shot 1] Follow the original cropped video timing and view. Keep face proportions and mouth positions stable. Do not add subjects, hair, teeth or text.'+
                    '\n\noverall_soundscape:\n'+('Follow the supplied <Audio 1> performance.' if has_audio else 'No dialogue.')+
                    '\n\nnon_diegetic_music:\nN/A')
            target=directory/f'face-{index}-refined.mp4'
            (directory/f'face-{index}.prompt.txt').write_text(prompt)
            metrics=h3_native.generate(prompt=prompt,references=images,width=track['width'],height=track['height'],
                duration=min(15,track['frames']/24),steps=settings.get('h3c_face_steps',6),seed=secrets.randbelow(2147483647),
                output=target,log_path=directory/f'face-{index}.log',ffmpeg=ffmpeg,check_cancel=st.check_cancel,
                on_progress=lambda message:st.update_job(jid,message=f'H3 面部精修 {index+1}/{len(tracks)} · {track["name"]} · '+message),
                streaming=settings.get('h3c_ssd_streaming',False),swap_limit_gib=settings.get('h3c_swap_limit_gib',8),
                stall_minutes=settings.get('h3c_stall_minutes',10),resident=True,
                media_references=[{'kind':'audio','path':audio}] if has_audio else [],
                refine_source=track['crop'],refine_denoise=settings.get('h3c_face_denoise',.05))
            track.update(refined=str(target),metrics=metrics)
        h3_native.stop_all();stage='stitch'
        target=directory/'face-refined.mp4'
        supervise(st,jid,'stitch',{'source':str(source_path),'tracks':tracks,'output':str(target),'ffmpeg':ffmpeg,
                                  'preserve_mouth':settings.get('h3c_face_preserve_mouth',True)},directory,settings)
        st.check_cancel()
        relative=str(target.relative_to(st.project_dir(pid).resolve()))
        record.update(status='done',video=relative,created_at=st.now(),faces=[t['entity_id'] for t in tracks],
                      warnings=prepared['warnings'],seconds=round(time.monotonic()-started,2),settings={**shot.get('video_result',{}).get('settings',{}),**{k:v for k,v in settings.items() if 'face' in k}},
                      backend='h3c',face_refine={'source_video':source,'upstream':'H3 FaceRefine','metal_adapter':True,
                                               'preserve_mouth':settings.get('h3c_face_preserve_mouth',True)},
                      references=profiles)
        tail=st.extract_video_tail(pid,relative,shot['id'])
        with st.PROJECT_LOCK:
            latest=st.load_project(pid);current=st.find_shot(latest,shot['id'])
            take={'video':relative,'source_video':source,'video_result':record,'actual_tail_frame':tail,'tail_source_video':relative}
            if current.get('video')!=source or video_workflow.authored_input(current)!=snapshot:
                record.update(superseded=True,note='精修期间已改稿或换版，精修结果保留为历史版本')
                current.setdefault('media_history',[]).append(take)
                st.update_job(jid,superseded_shot_ids=[*st.JOBS.get(jid,{}).get('superseded_shot_ids',[]),shot['id']])
            else:
                st.video_choices.archive(current);video_workflow.invalidate(st,latest,current,'上一段面部精修已更新，需要按新尾帧生成')
                current.update(**take,status='video_ready',video_stale=bool(shot.get('video_stale')))
                current.pop('face_refine_report',None);current.pop('review',None)
                if not current.get('video_stale'):current.pop('stale_reason',None)
            st.save_project(latest)
        return record
    except BaseException as error:
        record.update(status='error',stage=stage,error=str(error));task_diagnostics.cleanup(h3_native.stop_all)
        if isinstance(error,Exception) and not isinstance(error,st.Cancelled):
            raise RuntimeError('面部精修失败，原片已保留：'+str(error)) from error
        raise
    finally:task_diagnostics.write(record_path,record)

def after(st,jid,pid,shot_id,result,settings):
    if settings.get('h3c_face_refine') and not (result or {}).get('superseded'):
        return run(st,jid,pid,{'shot_id':shot_id,'source_video':result['video']},settings)
