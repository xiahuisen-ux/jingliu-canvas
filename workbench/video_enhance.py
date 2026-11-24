"""Bounded-disk Real-ESRGAN postprocessing. Originals are never overwritten."""
import json
import os
from pathlib import Path
from portable_paths import BACKENDS
import subprocess
import tempfile
import time
import uuid
import h3_native
import task_diagnostics

ROOT=BACKENDS/'Real-ESRGAN部署'
BINARY=ROOT/'realesrgan-ncnn-vulkan-v0.2.0-macos/realesrgan-ncnn-vulkan'
MODELS=ROOT/'models'


def status():
    return {'ready':BINARY.is_file() and os.access(BINARY,os.X_OK) and all((MODELS/('realesrgan-x4plus.'+ext)).is_file() for ext in ('bin','param')),'directory':str(ROOT)}


def enhance(st, source, target, scale, progress):
    from PIL import Image
    import imageio_ffmpeg
    if scale not in (2,4):raise ValueError('增强倍率只能为 2 或 4')
    if not status()['ready']:raise ValueError('Real-ESRGAN 尚未安装完整')
    if Path(source).resolve()==Path(target).resolve():raise ValueError('增强不能覆盖原视频')
    probe=json.loads(subprocess.check_output([str(h3_native.FFPROBE),'-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_frames:format=duration','-of','json',str(source)],text=True))
    info=probe['streams'][0];width=info['width'];height=info['height']
    if width*scale>4096 or height*scale>4096 or width*height*scale**2>4096*2160:raise ValueError('增强输出超过 4K 像素预算，请降低倍率')
    numerator,denominator=map(int,info['avg_frame_rate'].split('/'));fps=numerator/denominator
    total=int(info.get('nb_frames','0')) if str(info.get('nb_frames','')).isdigit() else round(float(probe['format']['duration'])*fps)
    target=Path(target);target.parent.mkdir(exist_ok=True,parents=True)
    temp_root=target.parent.parent/'temp'/'upscale';temp_root.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();done=0;reader=None;encoder=None
    log_path=target.with_suffix('.log')
    with tempfile.TemporaryDirectory(prefix='upscale-',dir=temp_root) as temporary, open(log_path,'wb') as log:
        temp=Path(temporary);inputs=temp/'in';outputs=temp/'out';inputs.mkdir();outputs.mkdir()
        try:
            reader=imageio_ffmpeg.read_frames(str(source),pix_fmt='rgb24');next(reader)
            encoder=subprocess.Popen([st.get_ffmpeg(),'-y','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{width*scale}x{height*scale}','-framerate',info['avg_frame_rate'],'-i','pipe:0','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(temp/'silent.mp4')],stdin=subprocess.PIPE,stdout=log,stderr=log,start_new_session=True)
            finished=False
            while not finished:
                count=0
                for i in range(8):
                    st.check_cancel()
                    try:frame=next(reader)
                    except StopIteration:finished=True;break
                    Image.frombytes('RGB',(width,height),frame).save(inputs/f'{i:03}.png');count+=1
                if not count:break
                command=[str(BINARY),'-i',str(inputs),'-o',str(outputs),'-m',str(MODELS),'-n','realesrgan-x4plus','-s','4','-t','128','-j','1:1:1','-f','png']
                process=subprocess.Popen(command,cwd=BINARY.parent,stdout=log,stderr=log,start_new_session=True)
                try:
                    while process.poll() is None:
                        st.check_cancel();current=len(list(outputs.glob('*.png')))
                        progress(min(total,done+current),total,time.monotonic()-started);time.sleep(.3)
                    if process.returncode:raise RuntimeError('Real-ESRGAN 失败，请查看 '+str(log_path))
                finally:task_diagnostics.cleanup(lambda:h3_native.stop_process(process))
                for i in range(count):
                    st.check_cancel();path=outputs/f'{i:03}.png'
                    with Image.open(path) as img:
                        frame=img.convert('RGB')
                        if frame.size!=(width*scale,height*scale):frame=frame.resize((width*scale,height*scale),Image.Resampling.LANCZOS)
                        encoder.stdin.write(frame.tobytes())
                    (inputs/f'{i:03}.png').unlink();path.unlink();done+=1
                progress(done,total,time.monotonic()-started)
            encoder.stdin.close()
            while encoder.poll() is None:st.check_cancel();time.sleep(.2)
            if encoder.returncode or not done:raise RuntimeError('增强视频编码失败')
            st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(temp/'silent.mp4'),'-i',str(source),'-map','0:v:0','-map','1:a?','-c:v','copy','-c:a','aac','-t',str(probe['format']['duration']),'-movflags','+faststart',str(target)])
            result={'video':str(target),'scale':scale,'frames':done,'seconds':round(time.monotonic()-started,2),'width':width*scale,'height':height*scale,'model':'realesrgan-x4plus'}
            return result
        finally:
            if reader:task_diagnostics.cleanup(reader.close)
            if encoder:
                task_diagnostics.cleanup(lambda:h3_native.stop_process(encoder))
                if encoder.stdin and not encoder.stdin.closed:task_diagnostics.cleanup(encoder.stdin.close)


def run(st,jid,pid,payload):
    p=st.load_project(pid);is_final=payload.get('shot_id')=='__final__'
    shot=None if is_final else st.find_shot(p,payload['shot_id'])
    source=p.get('final_video') if is_final else shot.get('video')
    if not source:raise ValueError('请先生成视频')
    if shot and shot.get('video_stale'):raise ValueError('视频已失效，请重新生成后再增强')
    # All heavyweight generation models must be released first.
    st.prepare_model_mode('vision')
    st.unload_ollama(st.VISION_MODEL)
    scale=payload.get('scale',st.video_settings().get('video_upscale',2)) or 2
    output=st.project_dir(pid)/'enhanced'/f"{'final' if is_final else shot['id']}_{uuid.uuid4().hex[:8]}_{scale}x.mp4"
    def report(done,total,elapsed):
        eta=round(elapsed/max(done,1)*(total-done)) if done else None
        st.update_job(jid,message=f'视频增强 {done}/{total} 帧 · '+(f'预计剩余 {eta} 秒' if eta is not None else '正在估算'),progress=min(98,5+int(90*done/max(total,1))))
    result=enhance(st,st.project_path(pid,source),output,scale,report)
    result.update(video=str(output.relative_to(st.project_dir(pid))),source_video=source,created_at=st.now())
    if is_final:p.setdefault('enhanced_versions',[]).append(result)
    else:shot.setdefault('enhanced_versions',[]).append(result)
    st.save_project(p);return result
