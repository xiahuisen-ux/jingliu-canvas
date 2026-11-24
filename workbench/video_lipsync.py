"""Lip review, audio alignment and isolated MuseTalk 1.5 postprocessing."""
import copy
import json
import math
from pathlib import Path
import tempfile
import uuid
import subprocess
from fractions import Fraction

import video_choices


def catalog(p):
    videos=[]; audios=[]
    deleted={r.get('result',{}).get('video') for s in p.get('shots',[]) for r in s.get('deleted_videos',[])}
    for s in p.get('shots',[]):
        for v in video_choices.versions(s):
            videos.append({'path':v['video'],'label':f"第{s.get('shot')}段 · {s.get('title','')} · 版本{v['number']}",
                           'shot_id':s['id'],'version_id':v['id']})
        a=s.get('audio_segment') or {}
        if a.get('path'):audios.append({'path':a['path'],'label':f"第{s.get('shot')}段录音"})
    if p.get('final_video'):videos.append({'path':p['final_video'],'label':'当前合成视频'})
    for a in p.get('uploads',[]):
        if a.get('kind') in {'video','silent_video'}:videos.append({'path':a['path'],'label':'上传 · '+a.get('name','视频')})
        if a.get('kind')=='audio':audios.append({'path':a['path'],'label':'上传 · '+a.get('name','录音')})
    a=p.get('audio_timeline') or {}
    if a.get('path'):audios.append({'path':a['path'],'label':'整片主音轨'})
    for r in p.get('lipsync_results',[]):
        if r['video'] in deleted:continue
        videos.append({'path':r['video'],'label':('MuseTalk 1.5' if r['mode']=='musetalk' else '音轨同步')+' · '+r['created_at'],'shot_id':r.get('shot_id')})
    def unique(rows):
        return list({r['path']:r for r in reversed(rows)}.values())[::-1]
    return {'videos':unique(videos),'audios':unique(audios)}


def number(value,low,high,label):
    if isinstance(value,bool):raise ValueError(label+'格式错误')
    try:value=float(value)
    except (TypeError,ValueError):raise ValueError(label+'格式错误')
    if not math.isfinite(value) or not low<=value<=high:raise ValueError(label+'超出允许范围')
    return value


def region_value(value):
    if value is None:return None
    if not isinstance(value,list) or len(value)!=4:raise ValueError('人物区域格式错误')
    x,y,w,h=[number(v,0,1,'人物区域') for v in value]
    if w<.03 or h<.03 or x+w>1.00001 or y+h>1.00001:raise ValueError('请圈选画面内完整、足够大的单个人脸区域')
    return [x,y,w,h]


def media_info(st,p,payload):
    source=payload.get('video')
    if source not in {v['path'] for v in catalog(p)['videos']}:raise ValueError('请选择本工程的视频')
    info=video_choices.media_info(st,p['id'],source)
    r=subprocess.run([str(st.h3_native.FFPROBE),'-v','error','-select_streams','v:0','-show_entries',
                      'stream=avg_frame_rate,r_frame_rate','-of','json',str(st.project_path(p['id'],source))],capture_output=True,text=True,timeout=30,check=True)
    stream=json.loads(r.stdout)['streams'][0]
    try:fps=float(Fraction(stream['avg_frame_rate']));nominal=float(Fraction(stream['r_frame_rate']))
    except (ValueError,ZeroDivisionError,KeyError):fps=24;nominal=24
    return {**info,'fps':fps if fps>0 else 24,'variable_fps':abs(fps-nominal)>.01}


def validate(st,p,payload):
    rows=catalog(p);source=payload.get('video');audio=payload.get('audio') or source
    selected=next((v for v in rows['videos'] if v['path']==source),None)
    if not selected:raise ValueError('请选择本工程已登记的视频版本')
    if audio!=source and audio not in {a['path'] for a in rows['audios']}:raise ValueError('请选择本工程已登记的录音')
    for path in (source,audio):
        if not st.project_path(p['id'],path).is_file():raise ValueError('素材文件缺失，请重新选择或上传')
    info=video_choices.media_info(st,p['id'],source)
    if audio==source and not info['has_audio']:raise ValueError('本视频没有原声，请选择或上传配音')
    mode=payload.get('mode','audio_sync')
    if mode not in {'audio_sync','musetalk'}:raise ValueError('处理模式不支持')
    offset=number(payload.get('offset_ms',0),-5000,5000,'声音偏移')
    batch=number(payload.get('batch_size',4),1,8,'处理批量')
    if not batch.is_integer():raise ValueError('处理批量必须为整数')
    margin=number(payload.get('extra_margin',10),0,40,'下巴额外边距')
    if mode=='musetalk':
        import musetalk_backend
        state=musetalk_backend.status()
        if not state['ready']:raise ValueError(state['message'])
    if mode=='musetalk' and info['duration']>300:raise ValueError('请先将视频拆成不超过5分钟的片段再对口型')
    return {**selected,'audio':audio,'mode':mode,'offset_ms':offset,'batch_size':int(batch),'extra_margin':int(margin),'region':region_value(payload.get('region')),**info}


def audio_filter(offset_ms,duration):
    trim=max(0,-offset_ms/1000)
    delay=max(0,round(offset_ms))
    return f'atrim=start={trim},asetpts=PTS-STARTPTS,aresample=48000,adelay={delay}:all=1,apad,atrim=duration={duration}'


def save_review(st,pid,data):
    with st.PROJECT_LOCK:
        st.ensure_project_editable(pid);p=st.load_project(pid)
        source=data.get('video')
        if source not in {v['path'] for v in catalog(p)['videos']}:raise ValueError('校对视频已变化，请重新选择')
        offset=number(data.get('offset_ms',0),-5000,5000,'声音偏移')
        markers=data.get('markers',[])
        if not isinstance(markers,list) or len(markers)>300:raise ValueError('校对标记格式错误或超过300条')
        duration=video_choices.media_info(st,pid,source)['duration']
        clean=[]
        for m in markers:
            if not isinstance(m,dict):raise ValueError('校对标记格式错误')
            clean.append({'time':number(m.get('time'),0,duration,'标记时间'),'note':str(m.get('note',''))[:2000]})
        p.setdefault('lipsync_reviews',{})[source]={'offset_ms':offset,'markers':clean,'region':region_value(data.get('region')),'updated_at':st.now()}
        st.save_project(p);return st.project_view(p)


def run(st,jid,pid,payload):
    p=st.load_project(pid);v=validate(st,p,payload);root=st.project_dir(pid)
    (root/'temp').mkdir(exist_ok=True);out=root/'videos/lipsync';out.mkdir(parents=True,exist_ok=True)
    target=out/('lip-'+uuid.uuid4().hex[:12]+'.mp4');published=False
    try:
        with tempfile.TemporaryDirectory(prefix='lipsync-',dir=root/'temp') as folder:
            folder=Path(folder);audio=folder/'aligned.wav'
            st.update_job(jid,message='按校对偏移整理配音',progress=8)
            st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(st.project_path(pid,v['audio'])),
                           '-vn','-af',audio_filter(v['offset_ms'],v['duration']),'-ar','48000','-ac','2','-c:a','pcm_s16le',str(audio)])
            source=st.project_path(pid,v['path'])
            metrics={}
            if v['mode']=='musetalk':
                import musetalk_backend
                st.h3_native.stop_all();st.unload_other_ollama();st.stop_comfy('qwen_image')
                source=musetalk_backend.generate(st,jid,pid,source,audio,folder,v)
                if source.with_suffix('.metrics.json').is_file():metrics=json.loads(source.with_suffix('.metrics.json').read_text())
            st.update_job(jid,message='导出校对视频，保留原片',progress=92)
            st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(source),'-i',str(audio),'-map','0:v:0','-map','1:a:0',
                           '-c:v','copy','-c:a','aac','-b:a','192k','-t',str(v['duration']),'-movflags','+faststart',str(target)])
        st.check_cancel();info=video_choices.media_info(st,pid,str(target.relative_to(root)))
        if abs(info['duration']-v['duration'])>.1:raise ValueError('输出视频时长异常，未发布；请检查模型输出')
        record={'id':uuid.uuid4().hex[:12],'video':str(target.relative_to(root)),'source_video':v['path'],
                'audio':v['audio'],'mode':v['mode'],'offset_ms':v['offset_ms'],'batch_size':v['batch_size'],
                'extra_margin':v['extra_margin'],'region':v.get('region'),'metrics':metrics,'created_at':st.now(),'shot_id':v.get('shot_id'),'duration':info['duration']}
        with st.PROJECT_LOCK:
            st.check_cancel();fresh=st.load_project(pid)
            # Publish an additional take, never change the source video or tail chain.
            fresh.setdefault('lipsync_results',[]).append(copy.deepcopy(record))
            if record['shot_id']:
                shot=st.find_shot(fresh,record['shot_id'])
                if not any(h.get('video')==shot.get('video') for h in shot.get('media_history',[])):video_choices.archive(shot)
                shot.setdefault('media_history',[]).append({'video':record['video'],'source_video':v['path'],'video_result':{'created_at':record['created_at'],'settings':{'duration':info['duration']},'lip_sync':record}})
            st.save_project(fresh);published=True
        st.update_job(jid,result=record,progress=99)
    finally:
        if not published:target.unlink(missing_ok=True)
