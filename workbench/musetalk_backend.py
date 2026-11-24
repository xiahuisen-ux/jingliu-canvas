"""Isolated MuseTalk 1.5 runtime, no imports of torch in the workbench server."""
import json
import os
from pathlib import Path
from portable_paths import BACKENDS
import signal
import subprocess
import time
import re
import threading

DEPLOYMENT=BACKENDS/'MuseTalk-Metal部署'
_processes=set()
_guard=threading.Lock()


def status():
    runtime=DEPLOYMENT/'runtime.json'
    if not runtime.is_file():
        return {'ready':False,'message':'MuseTalk 1.5 独立 Metal 环境正在准备，完成后刷新素材。','model':'MuseTalk 1.5'}
    try:
        cfg=json.loads(runtime.read_text())
        missing=[k for k in ('python','runner','checkpoint','unet_config','source','vae','whisper','face_parse','resnet','ffmpeg') if not Path(cfg.get(k,'/missing')).exists()]
        for item in cfg.get('weight_files',[]):
            f=Path(item['path'])
            if not f.is_file() or f.stat().st_size!=item['size']:missing.append(f.name)
        ready=not missing and cfg.get('environment_checked') and cfg.get('weights_verified')
        return {'ready':bool(ready),'message':'MuseTalk 1.5 · 本机 MPS / Metal 已就绪' if ready else 'MuseTalk 1.5 环境待验证'+('，缺少：'+','.join(missing) if missing else ''),
                'model':'MuseTalk 1.5','device':cfg.get('device'),'validated':bool(cfg.get('validated',False))}
    except (OSError,ValueError,TypeError):return {'ready':False,'message':'MuseTalk 1.5 运行配置无效','model':'MuseTalk 1.5'}


def generate(st,jid,pid,video,audio,folder,values):
    state=status()
    if not state['ready']:raise ValueError(state['message'])
    cfg=json.loads((DEPLOYMENT/'runtime.json').read_text());output=folder/'generated.mp4'
    info=__import__('video_lipsync').media_info(st,st.load_project(pid),{'video':values['path']})
    if info['variable_fps'] or abs(info['fps']-round(info['fps']))>.01:
        normalized=folder/'normalized.mp4'
        st.run_ffmpeg([st.get_ffmpeg(),'-y','-i',str(video),'-an','-vf',f"fps={round(info['fps'])}",'-c:v','libx264','-crf','16',str(normalized)])
        video=normalized
    request={'video':str(video),'audio':str(audio),'output':str(output),'temp':str(folder/'model-temp'),
             'batch_size':values['batch_size'],'extra_margin':values['extra_margin'],'region':values.get('region'),'runtime':cfg}
    request_path=folder/'request.json';request_path.write_text(json.dumps(request,ensure_ascii=False))
    log=st.project_path(pid,'logs/musetalk-'+jid+'.log');log.parent.mkdir(exist_ok=True)
    env=os.environ.copy()
    for key in ('PYTHONPATH','PYTHONHOME','PYTHONUSERBASE'):env.pop(key,None)
    env.update(PYTHONNOUSERSITE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTORCH_ENABLE_MPS_FALLBACK='1',MUSETALK_DEVICE='mps',MUSETALK_MASK_EVERY='1',MUSETALK_TAESD='',MUSETALK_STOCHASTIC='',MUSETALK_BLEND_CV2='',HF_HOME=str(DEPLOYMENT/'cache/huggingface'))
    env['PATH']=str(Path(st.get_ffmpeg()).parent)+os.pathsep+env.get('PATH','')
    st.update_job(jid,message='MuseTalk 1.5 正在加载与重做嘴型；详细进度见工程日志',progress=20)
    settings=st.load_settings();swap_start=st.h3_native.swap_mb();checked=time.monotonic();size=0;changed=time.monotonic()
    with log.open('wb') as stream:
        process=subprocess.Popen([cfg['python'],'-s','-u',cfg['runner'],str(request_path)],cwd=cfg['source'],env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        with _guard:_processes.add(process)
        try:
            while process.poll() is None:
                st.check_cancel();time.sleep(.3)
                if time.monotonic()-checked>=3:
                    checked=time.monotonic();delta=max(0,st.h3_native.swap_mb()-swap_start)
                    if delta>settings['h3c_swap_limit_gib']*1024:raise RuntimeError('MuseTalk 交换新增超过工作台保护阈值，已停止并保留原片')
                    current_size=log.stat().st_size
                    if current_size!=size:
                        size=current_size;changed=checked
                        with log.open('rb') as read:read.seek(max(0,size-4096));tail=read.read().decode('utf-8',errors='replace')
                        matches=list(re.finditer(r'PROGRESS (\d+) ([^\r\n]+)',tail))
                        if matches:
                            m=matches[-1];st.update_job(jid,progress=20+int(int(m[1])*.7),message=m[2])
                    if checked-changed>settings['h3c_stall_minutes']*60:raise RuntimeError('MuseTalk 长时间无进度，已停止；请查看工程日志')
            if process.returncode:raise RuntimeError('MuseTalk 1.5 处理失败，请查看 '+str(log.relative_to(st.project_dir(pid))))
            st.check_cancel()
            if not output.is_file() or not output.stat().st_size:raise RuntimeError('MuseTalk 1.5 未输出有效视频')
        finally:
            stop_process(process)
            with _guard:_processes.discard(process)
    return output


def stop_process(process):
    if process.poll() is not None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()


def stop_all():
    with _guard:processes=list(_processes)
    for process in processes:stop_process(process)
