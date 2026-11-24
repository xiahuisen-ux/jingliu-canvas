"""Convert an imported audio node to an independent, silent-picture MP4 with sound."""
import uuid
import canvas_videos as cv


def validate(st,p,payload):
    node_id=payload.get('node_id')
    if not isinstance(node_id,str) or not node_id.startswith('audio:'):raise ValueError('请选择音频节点')
    item,file=cv.source(st,p,node_id,payload.get('audio'))
    info=cv.upload_info(file,'audio',st.h3_native.FFPROBE)
    return item,file,info


def run(st,jid,pid,payload):
    p=st.load_project(pid);item,file,info=validate(st,p,payload)
    suffix=uuid.uuid4().hex[:12];output=st.project_path(pid,'clips/audio-black-'+suffix+'.mp4');output.parent.mkdir(parents=True,exist_ok=True)
    st.update_job(jid,message='正在把音频封装成黑屏 MP4，保留完整声音…',progress=10)
    # A bounded color source plus the original audio stream. AAC maximizes MP4 playback compatibility.
    st.run_ffmpeg([st.get_ffmpeg(),'-y','-f','lavfi','-i','color=c=black:s=512x288:r=24','-i',str(file),'-map','0:v:0','-map','1:a:0',
                   '-t',str(info['duration']),'-c:v','libx264','-preset','veryfast','-tune','stillimage','-crf','28','-pix_fmt','yuv420p',
                   '-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',str(output)])
    st.check_cancel();checked=cv.upload_info(output,'video',st.h3_native.FFPROBE)
    if not checked['has_audio']:raise ValueError('输出缺少音轨，未添加节点；原音频保留')
    if abs(checked['duration']-info['duration'])>.2:raise ValueError('输出时长与原音频不符，未添加节点；原音频保留')
    origin={'node_id':payload['node_id'],'path':payload['audio'],'operation':'audio_to_video','created_at':st.now(),
            'source_size':file.stat().st_size,'source_mtime_ns':file.stat().st_mtime_ns}
    created=cv.blank(st,item.get('title','音频')+' · 黑屏视频',max(5,min(15,round(info['duration']))))
    created.update(video=str(output.relative_to(st.project_dir(pid).resolve())),status='video_ready',
                   canvas_origin=origin,canvas_reference_kind='video',video_result={'duration':checked['duration'],'has_audio':True,'audio_black_video':True})
    node_id='clip:'+created['id']
    with st.PROJECT_LOCK:
        fresh=st.load_project(pid);fresh.setdefault('canvas_videos',[]).append(created);cv.place(fresh,node_id,payload['node_id']);st.save_project(fresh)
    st.update_job(jid,result_node_id=node_id)
    return {'node_id':node_id,'origin':origin}
