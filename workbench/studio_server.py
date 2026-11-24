#!/usr/bin/env python3
from __future__ import annotations

import base64
import cgi
import json
import mimetypes
import math
import os
import re
import shutil
import signal
import socket
import http.client
import subprocess
import sys
import threading
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
from contextlib import nullcontext
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "studio"
from portable_paths import DATA
PROJECTS = DATA / "工程"
PROJECTS.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
import director
import h3_native
import h3_prompt_skill
import h3_translation
import creative_chat
import canvas_assistant
import canvas_audio_video
import shot_chat
import script_workspace
import character_states
import task_diagnostics
import asset_views
import single_image_edit
import local_http
import character_image_edit
import character_sheet_layout
import face_refine
import asset_images
import video_enhance
import video_workflow
import video_modes
import video_timing
import project_audio
import power_guard
import video_choices
import video_color_match
import video_lipsync
import musetalk_backend
import tail_repair
import opening_frames
import text_models
import element_analysis
import shot_elements
import project_storage
import project_merge
import canvas_images
import canvas_workspace
import canvas_videos
import character_library
import asset_library
import canvas_nodes

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
MODEL_LOCK = threading.Lock()
PROJECT_LOCK = threading.RLock()
COMFY_PROCESSES = {}
COMFY_PROJECTS = {}
STOPPING = threading.Event()
STOP_STATE = {"status":"idle","message":""}
ACTIVE_CONNECTIONS = set()
CONNECTION_LOCK = threading.Lock()
TASK_LOCAL = threading.local()
VISION_MODEL = "qwen3-vl:8b"
SETTINGS_FILE = DATA / "studio_settings.json"
DEFAULT_SETTINGS = {
    "reference_size": 768,
    "image_width": 384,
    "image_height": 672,
    "image_steps": 8 if director.CFG.get("image_backend")=="z_image" else 4,
    "video_width": 352,
    "video_height": 608,
    "video_fps": 24,
    "video_duration": 10,
    "video_backend": "h3c",
    "h3c_steps": 8,
    "h3c_layers": 50,
    "h3c_reuse": 1,
    "h3c_reference_video_max_pixels": 0,
    "h3c_swap_limit_gib": 8,
    "h3c_ssd_streaming": False,
    "h3c_resident": True,
    "h3c_face_refine": False,
    "h3c_face_preserve_mouth": True,
    "h3c_face_size": 512,
    "h3c_face_steps": 6,
    "h3c_face_denoise": .05,
    "h3c_stall_minutes": 10,
    "video_upscale": 0,
    "qwen_keep_alive": "60s",
}


def now(): return datetime.now().isoformat(timespec="seconds")
def project_dir(pid):
    if not isinstance(pid,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",pid):
        raise ValueError("项目编号不正确")
    target=PROJECTS/pid
    if target.is_symlink():raise ValueError("不允许符号链接项目")
    return target
def project_file(pid): return project_dir(pid) / "project.json"


def create_project(data):
    pid=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    with PROJECT_LOCK:
        project_dir(pid).mkdir()
        p={'id':pid,'title':data.get('title') or '未命名项目','brief':data.get('brief',''),
           'stage':'brief','created_at':now(),'uploads':[],'assets':{},'shots':[]}
        project_storage.initialize(project_dir(pid),p['title'])
        save_project(p)
    return project_view(p)


def comfy_project_paths(pid):
    paths={key:project_path(pid,'temp/comfy/'+key) for key in ('input','output','temp')}
    for path in paths.values():path.mkdir(parents=True,exist_ok=True)
    return paths


def bounded(value, low, high, multiple=1):
    value=max(low,min(high,int(value)))
    return max(low,(value//multiple)*multiple)


def normalize_settings(data):
    import h3_performance
    merged={**DEFAULT_SETTINGS,**(data or {})}
    h3_performance.validate(merged['h3c_layers'],merged['h3c_reuse'],merged['h3c_reference_video_max_pixels'],
                            bounded(merged['h3c_steps'],4,50))
    if merged['video_backend'] not in {'comfyui','h3c'}:raise ValueError('仅支持 h3.c Metal 视频后端')
    if type(merged['video_upscale']) is not int or merged['video_upscale'] not in {0,2,4}:raise ValueError('视频增强只能选择关闭、2倍或4倍')
    if type(merged['h3c_ssd_streaming']) is not bool:raise ValueError('H3 逐层加载须为开关')
    if type(merged['h3c_resident']) is not bool:raise ValueError('H3 常驻缓存须为开关')
    if any(type(merged[k]) is not bool for k in ('h3c_face_refine','h3c_face_preserve_mouth')):raise ValueError('面部精修须为开关')
    if type(merged['h3c_face_denoise']) not in (int,float) or not .01<=merged['h3c_face_denoise']<=.15:raise ValueError('面部重绘幅度须为0.01–0.15')
    return {
        "reference_size":bounded(merged["reference_size"],512,1024,64),
        "image_width":bounded(merged["image_width"],384,1536,16),
        "image_height":bounded(merged["image_height"],384,1536,16),
        "image_steps":bounded(merged["image_steps"],4,12),
        "video_width":bounded(merged["video_width"],256,1344,32),
        "video_height":bounded(merged["video_height"],256,1344,32),
        "video_fps":24,
        "video_duration":video_timing.validate_duration(merged['video_duration']),
        "video_backend":"h3c",
        "h3c_steps":bounded(merged['h3c_steps'],4,50),
        "h3c_layers":merged['h3c_layers'],
        "h3c_reuse":merged['h3c_reuse'],
        "h3c_reference_video_max_pixels":merged['h3c_reference_video_max_pixels'],
        "h3c_swap_limit_gib":bounded(merged['h3c_swap_limit_gib'],2,30),
        "h3c_ssd_streaming":merged['h3c_ssd_streaming'],
        "h3c_resident":merged['h3c_resident'],
        "h3c_face_refine":merged['h3c_face_refine'],
        "h3c_face_preserve_mouth":merged['h3c_face_preserve_mouth'],
        "h3c_face_size":bounded(merged['h3c_face_size'],512,768,32),
        "h3c_face_steps":bounded(merged['h3c_face_steps'],4,20),
        "h3c_face_denoise":float(merged['h3c_face_denoise']),
        "h3c_stall_minutes":bounded(merged['h3c_stall_minutes'],5,60),
        "video_upscale":merged['video_upscale'],
        "qwen_keep_alive":"60s",
    }


def load_settings():
    try:return normalize_settings(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:return DEFAULT_SETTINGS.copy()


def save_settings(data):
    if data.get("video_backend","h3c")!="h3c":raise ValueError("ComfyUI 视频后端已移除，仅支持 h3.c Metal")
    settings=normalize_settings({**load_settings(),**data})
    SETTINGS_FILE.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding="utf-8")
    if not settings['h3c_resident'] and MODEL_LOCK.acquire(blocking=False):
        try:h3_native.stop_all()
        finally:MODEL_LOCK.release()
    return settings


def video_settings():
    return getattr(TASK_LOCAL,'video_settings',None) or load_settings()


def load_project(pid):
    p=json.loads(project_file(pid).read_text(encoding="utf-8"))
    if getattr(TASK_LOCAL,'video_edit_snapshot',False):return project_merge.Snapshot(p)
    return p


def save_project(project):
    project["updated_at"] = now()
    with PROJECT_LOCK:
        target=project_file(project["id"])
        saved=project_merge.save_data(project,json.loads(target.read_text(encoding='utf-8'))) if isinstance(project,project_merge.Snapshot) and target.exists() else project
        # This catalog is derived from current text/reference files on each read.
        saved={k:v for k,v in saved.items() if k!='opening_frame_catalog'}
        temporary=target.with_name(".project-"+uuid.uuid4().hex+".json")
        temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)


class Cancelled(RuntimeError):pass


def check_cancel():
    jid=getattr(TASK_LOCAL,"jid",None)
    if STOPPING.is_set() or (jid and JOBS.get(jid,{}).get("cancel_requested")):
        raise Cancelled("任务已停止，已完成的文件保留")


def ollama_events(payload,timeout=300):
    check_cancel()
    endpoint=urlparse(director.CFG["ollama_url"])
    cls=http.client.HTTPSConnection if endpoint.scheme=="https" else http.client.HTTPConnection
    conn=cls(endpoint.hostname,endpoint.port,timeout=5)
    try:
        conn.connect();conn.sock.settimeout(timeout)
        with CONNECTION_LOCK:ACTIVE_CONNECTIONS.add(conn)
        check_cancel()
        conn.request("POST",endpoint.path.rstrip("/")+"/api/chat",json.dumps({**payload,"stream":True}),{"Content-Type":"application/json"})
        response=conn.getresponse()
        if response.status!=200:raise RuntimeError(response.read().decode()[:500])
        for line in response:
            check_cancel()
            if not line.strip():continue
            event=json.loads(line)
            if event.get("error"):raise RuntimeError(event["error"])
            yield event
            if event.get("done"):return
        check_cancel();raise RuntimeError("模型连接提前结束")
    finally:
        with CONNECTION_LOCK:ACTIVE_CONNECTIONS.discard(conn)
        conn.close()


def request_stop():
    with LOCK:
        if STOPPING.is_set():return dict(STOP_STATE)
        STOPPING.set();STOP_STATE.update(status="stopping",message="正在停止任务并释放模型…")
        for job in JOBS.values():
            if job.get("status") in {"queued","running"}:
                job["cancel_requested"]=True
                if job["status"]=="queued":job.update(status="cancelled",message="已取消排队",progress=100)
    with CONNECTION_LOCK:
        for conn in list(ACTIVE_CONNECTIONS):
            try:conn.sock.shutdown(socket.SHUT_RDWR)
            except (OSError,AttributeError):pass
    threading.Thread(target=finish_stop,daemon=True).start()
    return dict(STOP_STATE)


def finish_stop():
    errors=[]
    def stop_owned(key):
        url=director.CFG[key+"_url"]
        with LOCK:
            owned={pid for j in JOBS.values() if j.get("cancel_requested") for base,pid in j.get("comfy_prompts",[]) if base==url}
        for pid in owned:
            for route,body in (("/queue",{"delete":[pid]}),("/interrupt",{"prompt_id":pid})):
                try:json_request(url+route,body,timeout=5)
                except Exception:pass
        stop_comfy(key,allowed_prompt_ids=owned)
    try:
        musetalk_backend.stop_all()
        h3_native.stop_all()
        # Keep prompt ownership records until the cancelled worker exits.
        for key in ("qwen_image",):
            try:stop_owned(key)
            except Exception:pass
        with MODEL_LOCK:
            try:unload_other_ollama()
            except Exception as e:errors.append(str(e))
            # A service might have been starting as the stop request arrived.
            for key in ("qwen_image",):
                try:stop_owned(key)
                except Exception as e:
                    if str(e) not in errors:errors.append(str(e))
        STOP_STATE.update(status="error" if errors else "done",message="；".join(errors) if errors else "已停止任务并释放模型，已完成图片保留")
    finally:STOPPING.clear()


def delete_project(pid):
    # Recoverable deletion: move the entire project, never remove model files.
    with PROJECT_LOCK:
        source=project_dir(pid)
        if not (source/"project.json").is_file():raise FileNotFoundError("项目不存在")
        if any(j.get("project_id")==pid and j.get("status") in {"queued","running"} for j in JOBS.values()):
            raise ValueError("项目还有正在执行或排队的任务，请完成后再删除")
        target=project_storage.recycle_project(source)
        return {"deleted":True,"recoverable":True,"recovery_path":str(target)}


def json_request(url, payload=None, timeout=120):
    if url==director.CFG["ollama_url"]+"/api/chat" and payload:
        content="";last={};stamp=0
        for last in ollama_events(payload,timeout):
            content+=last.get("message",{}).get("content","")
            jid=getattr(TASK_LOCAL,'jid',None)
            if jid and JOBS.get(jid,{}).get('action')=='analyze' and time.monotonic()-stamp>=1:
                update_job(jid,message=f"本地模型正在提取跨场重复元素 · 已接收 {len(content)} 字（等待完整清单）")
                stamp=time.monotonic()
        check_cancel()
        return {**last,"message":{"role":"assistant","content":content}}
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with local_http.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_json(prompt, schema, model=None, images=None, timeout=1200, system=None):
    config=getattr(TASK_LOCAL,'text_config',None) or text_models.load()
    if not model and not images and config['provider']!='local':
        return text_models.request(config,([{'role':'system','content':system}] if system else [])+[{'role':'user','content':prompt}],schema,sys.modules[__name__])
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = [base64.b64encode(Path(p).read_bytes()).decode() for p in images]
    selected=model or director.CFG["ollama_model"]
    context=16384 if images or selected==VISION_MODEL else config.get('local_num_ctx',32768)
    result = json_request(director.CFG["ollama_url"] + "/api/chat", {
        "model": selected, "stream": False, "format": schema, "think":False,
        "keep_alive":"5m" if selected==VISION_MODEL else 0,
        "options": {"temperature": .2, "num_ctx": context, "num_predict":8192}, "messages": ([{"role":"system","content":system}] if system else [])+[msg]
    }, timeout=timeout)
    if result.get('done_reason')=='length' or result.get('prompt_eval_count',0)+result.get('eval_count',0)>=context:
        raise ValueError('本地模型输出达到上下文或输出上限，清单可能被截断；请精简输入、提高上下文或分批提取。原内容未覆盖')
    try:value=json.loads(result["message"]["content"])
    except json.JSONDecodeError:
        raise ValueError('本地模型未返回完整有效的JSON，提取失败，原内容未覆盖；请精简输入或提高上下文后重试') from None
    text_models.validate_result(value,schema)
    return value


def model_key(name):
    return name if ':' in name.rsplit('/',1)[-1] else name+':latest'


def ollama_resident_models():
    try:result=json_request(director.CFG['ollama_url']+'/api/ps',timeout=5)
    except urllib.error.URLError as error:
        if isinstance(error.reason,ConnectionRefusedError):return []
        raise RuntimeError('无法确认 Ollama 已加载模型，暂不加载另一个模型') from error
    models=result.get('models')
    if not isinstance(models,list) or any(not isinstance(m,dict) or not (m.get('model') or m.get('name')) for m in models):
        raise RuntimeError('Ollama 返回无效模型列表，暂不加载另一个模型')
    return models


def unload_ollama(model):
    if not any(model_key(m.get('model') or m['name'])==model_key(model) for m in ollama_resident_models()):return
    json_request(director.CFG['ollama_url']+'/api/generate',{'model':model,'keep_alive':0},timeout=45)
    deadline=time.monotonic()+15
    while any(model_key(m.get('model') or m['name'])==model_key(model) for m in ollama_resident_models()):
        if time.monotonic()>=deadline:raise RuntimeError(f'{model} 卸载后仍驻留，暂不加载另一个模型')
        time.sleep(.25)


def unload_other_ollama(keep=()):
    allowed={model_key(name) for name in keep}
    for model in ollama_resident_models():
        name=model.get('model') or model['name']
        if model_key(name) not in allowed:unload_ollama(name)
    remaining=[m.get('model') or m['name'] for m in ollama_resident_models()
               if model_key(m.get('model') or m['name']) not in allowed]
    if remaining:raise RuntimeError('其他模型仍驻留，暂不启动：'+', '.join(remaining))


def ensure_comfy_idle():
    for name,key in (("生图服务","qwen_image_url"),):
        try:q=json_request(director.CFG[key]+"/queue",timeout=5)
        except urllib.error.URLError:continue
        if q.get("queue_running") or q.get("queue_pending"):
            raise ValueError(f"{name} 还有直接提交的任务，请等它完成后再切换模型。")


def stop_comfy(key,allowed_prompt_ids=()):
    """Only stop the listener whose working directory matches this configured service."""
    if key!="qwen_image":raise ValueError("ComfyUI 仅用于生图，视频请使用 h3.c Metal")
    url=director.CFG[key+"_url"]
    if urlparse(url).hostname not in {"127.0.0.1","localhost"}:
        raise ValueError("按需进程管理仅支持本机 ComfyUI")
    try:queue=json_request(url+"/queue",timeout=5)
    except urllib.error.URLError:queue={}
    active=queue.get("queue_running",[])+queue.get("queue_pending",[])
    if any(item[1] not in allowed_prompt_ids for item in active):
        raise ValueError(f"{key} 仍有生成任务，未停止该服务")
    port=urlparse(url).port
    result=subprocess.run(["/usr/sbin/lsof","-t",f"-iTCP:{port}","-sTCP:LISTEN"],capture_output=True,text=True)
    for value in set(result.stdout.split()):
        pid=int(value)
        cwd=subprocess.run(["/usr/sbin/lsof","-a","-p",value,"-d","cwd","-Fn"],capture_output=True,text=True).stdout
        expected=Path(director.CFG[key+"_root"]).resolve()
        if not any(line.startswith("n") and Path(line[1:]).resolve()==expected for line in cwd.splitlines()):
            raise ValueError(f"端口 {port} 不属于配置的模型目录，未停止该进程")
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:continue
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            managed=COMFY_PROCESSES.get(key)
            if managed and managed.pid==pid and managed.poll() is not None:break
            try:os.kill(pid,0)
            except ProcessLookupError:break
            time.sleep(.2)
        else:raise ValueError(f"端口 {port} 的模型服务未退出，暂不加载另一个模型")


def ensure_comfy_started(key):
    if key!="qwen_image":raise ValueError("ComfyUI 视频后端已移除")
    check_cancel()
    url=director.CFG[key+"_url"]
    pid=getattr(TASK_LOCAL,'project_id',None)
    if not pid:raise ValueError('生图服务必须在具体项目内启动')
    paths=comfy_project_paths(pid)
    if service_status(url+"/system_stats"):
        managed=COMFY_PROCESSES.get(key)
        if COMFY_PROJECTS.get(key)==pid and managed and managed.poll() is None:return
        stop_comfy(key)
    root=Path(director.CFG[key+"_root"])
    python=Path(director.CFG.get(key+"_python",str(root/"venv/bin/python")))
    if not python.is_file():raise RuntimeError(f"{key} Python 环境不存在：{python}")
    command=[str(python),"-E","-s","main.py","--listen","127.0.0.1","--port",str(urlparse(url).port)]
    for kind,path in paths.items():command.extend(['--'+kind+'-directory',str(path)])
    env=os.environ.copy()
    # Keep inherited IDE/user Python paths out of the model service and its children.
    for name in ("PYTHONPATH","PYTHONHOME","PYTHONUSERBASE"):env.pop(name,None)
    env["PYTHONNOUSERSITE"]="1"
    env["VIRTUAL_ENV"]=str(python.parent.parent)
    env["PATH"]=str(python.parent)+os.pathsep+env.get("PATH","")
    env['TMPDIR']=str(paths['temp'])
    log_path=project_path(pid,'logs/'+key+'-service.log');log_path.parent.mkdir(parents=True,exist_ok=True)
    with log_path.open("ab") as log:
        process=subprocess.Popen(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    COMFY_PROCESSES[key]=process
    COMFY_PROJECTS[key]=pid
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        if STOPPING.is_set():
            process.terminate();raise Cancelled("启动已取消")
        if process.poll() is not None:raise RuntimeError(f"{key} 启动失败，请查看服务日志")
        if service_status(url+"/system_stats"):return
        time.sleep(.5)
    process.terminate()
    raise RuntimeError(f"{key} 启动超时，请查看服务日志")


def prepare_model_mode(mode):
    if mode=='text' and (getattr(TASK_LOCAL,'text_config',None) or text_models.load())['provider']!='local':return
    if mode in {'text','image','vision'}:h3_native.stop_all()
    ensure_comfy_idle()
    if mode=="text":
        unload_other_ollama((director.CFG['ollama_model'],))
        stop_comfy("qwen_image")
    elif mode=="image":
        unload_other_ollama()
        ensure_comfy_started("qwen_image")
    elif mode=="video":
        unload_other_ollama();stop_comfy("qwen_image")
        if not h3_native.status()['ready']:raise ValueError('h3.c 原生模型或程序未就绪')
    elif mode=="vision":
        unload_other_ollama((VISION_MODEL,));stop_comfy("qwen_image")


def chat_payload(messages):
    if not isinstance(messages,list) or any(not isinstance(m,dict) for m in messages):raise ValueError("对话格式不正确")
    clean=[]
    for item in messages[-10:]:
        role=item.get("role")
        content=str(item.get("content", ""))[:4000]
        if role in {"user","assistant"} and content.strip():clean.append({"role":role,"content":content})
    if not clean or clean[-1]["role"]!="user":raise ValueError("请输入问题")
    # Keep recent context bounded, rather than repeatedly evaluating a long transcript.
    total=0;recent=[]
    for item in reversed(clean):
        remaining=6000-total
        if remaining<=0:break
        item={**item,"content":item["content"][-remaining:]}
        recent.append(item);total+=len(item["content"])
    return {
        "model":director.CFG["ollama_model"],"stream":False,"think":False,
        "keep_alive":load_settings()["qwen_keep_alive"],
        "options":{"temperature":.3,"num_ctx":8192,"num_predict":1024},
        "messages":[{"role":"system","content":"你是本机通用中文助手。直接、简洁、准确回答问题，除非用户要求详细解释。你没有联网搜索、网页读取或图片搜索工具，不能声称已经搜索、核实或找到网页、图片。不确定的信息明确说不确定，不编造来源。用户要求搜索或最新资料时，说明当前为离线模式。不要输出思考过程或反复自我纠正。"},*reversed(recent)]
    }


def qwen_chat(messages):
    config=text_models.load()
    if config['provider']!='local':
        clean=chat_payload(messages)['messages'][1:]
        return {'role':'assistant','content':text_models.request(config,clean,None,sys.modules[__name__])}
    result=json_request(director.CFG["ollama_url"]+"/api/chat",chat_payload(messages),timeout=300)
    return {"role":"assistant","content":result["message"]["content"]}


def start_job(pid, action, payload):
    if action=="benchmark_video":raise ValueError("双后端对照已移除，视频仅使用 h3.c Metal")
    if action in {"frames","all_frames"}:raise ValueError("首尾帧功能已移除，请直接编辑文字任务并生成视频")
    with PROJECT_LOCK, LOCK:
        if STOPPING.is_set():raise ValueError("正在停止模型，请稍后重试")
        p=load_project(pid)
        payload={**payload,'_text_config':text_models.load()}
        remote_shot=action in {'shot_chat','script_discuss','script_propose'} and payload['_text_config']['provider']=='deepseek'
        if remote_shot:
            active=[j for j in JOBS.values() if j.get('project_id')==pid and j.get('status') in {'queued','running'}]
            if any(j.get('action') not in {'video','all_videos','render_sequence','repair_tail','face_refine'} for j in active):
                raise ValueError('请等待本工程的上一次改稿或其他编辑任务完成；视频生成期间可以使用 DeepSeek')
        else:ensure_project_editable(pid)
        if action=='storyboard':payload={**payload,'_settings':load_settings()}
        if action=='opening_frames':
            payload={**payload,'_settings':load_settings()}
            for shot in opening_frames.selected(p,payload):opening_frames.validate(sys.modules[__name__],p,shot,payload['_settings'])
        if action in {'creative_chat','creative_draft'}:payload=creative_chat.prepare(sys.modules[__name__],p,{**payload,'action':action})
        if action=='canvas_assistant':payload=canvas_assistant.prepare(sys.modules[__name__],p,payload)
        if action=='shot_chat':payload=shot_chat.prepare(sys.modules[__name__],p,payload)
        if action in {'script_discuss','script_propose'}:payload=script_workspace.prepare(sys.modules[__name__],p,{**payload,'action':action})
        if action=='translate_h3':payload=h3_translation.prepare(sys.modules[__name__],p,payload)
        if action in {'video','all_videos','render_sequence'}:
            payload={**payload,'_settings':load_settings()}
            if payload['_settings'].get('h3c_face_refine') and not face_refine.status()['ready']:raise ValueError('H3 FaceRefine 尚未就绪，请检查依赖或关闭自动精修')
            targets=[find_shot(p,payload.get('shot_id'))] if action=='video' else video_choices.generation_shots(sys.modules[__name__],p,payload)
            if 'shot_ids' in payload:video_choices.validate_predecessors(sys.modules[__name__],p,targets,batch=action!='video')
            for shot in targets:
                video_timing.shot_duration(shot, payload['_settings']['video_duration'])
                if action=='render_sequence' and 'shot_ids' not in payload and shot.get('video') and not shot.get('video_stale'):continue
                refs,pending=video_workflow.references(sys.modules[__name__],p,shot)
                video_workflow.validate_inputs(sys.modules[__name__],p,shot,refs,pending)
                canvas_videos.mention_text(shot,refs)
        if action=='face_refine':
            shot=find_shot(p,payload.get('shot_id'))
            if not shot.get('video'):raise ValueError('请先生成本段视频')
            if not face_refine.status()['ready']:raise ValueError('H3 FaceRefine 尚未安装完整')
            payload={**payload,'_settings':load_settings()}
        if action=='assemble' and 'clips' in payload:video_choices.assembly_clips(sys.modules[__name__],p,payload)
        if action=='color_match':video_color_match.validate(sys.modules[__name__],p,payload)
        if action=='lip_sync':video_lipsync.validate(sys.modules[__name__],p,payload)
        if action=='repair_tail':
            shot=find_shot(p,payload.get('shot_id'));tail_repair.validate(sys.modules[__name__],p,shot)
            prev=tail_repair.predecessor(sys.modules[__name__],p,shot)
            if not prev or not prev.get('video') or prev.get('video_stale'):raise ValueError('请先完成上一段有效视频')
        if action=="all_assets":
            payload=dict(payload);payload["asset_plan"]=normalize_asset_plan(p,payload.get("asset_plan"))
            if not any(payload["asset_plan"].values()):raise ValueError("请至少选择一个需要生成的元素")
            validate_asset_generation(p,action,payload)
            for eid,count in payload["asset_plan"].items():asset_record(p,eid)["reference_views"]=count
            save_project(p)
        elif action=='asset':validate_asset_generation(p,action,payload)
        if action=='canvas_audio_video':canvas_audio_video.validate(sys.modules[__name__],p,payload)
        if action in {'canvas_image','canvas_upscale'}:canvas_images.validate(sys.modules[__name__],p,action,payload)
        if action in {'canvas_video_generate','canvas_video_upscale','canvas_extract_frame','canvas_trim_video'}:
            payload={**payload,'_settings':load_settings()}
            canvas_videos.validate(sys.modules[__name__],p,action,payload)
        jid = uuid.uuid4().hex[:12]
        JOBS[jid] = {"id": jid, "project_id": pid, "action": action, "status": "queued", "progress": 0, "message": "等待执行", "created_at": now()}
        if action=='canvas_assistant':
            try:canvas_assistant.register(sys.modules[__name__],jid,pid,payload)
            except Exception:
                JOBS.pop(jid,None);raise
        if action=='shot_chat':JOBS[jid].update(shot_id=payload['shot_id'])
        if remote_shot:JOBS[jid]['remote_text']=True
        if action=='translate_h3':JOBS[jid].update(shot_id=payload['shot_id'],translation_source=payload['_translation_input']['chinese'],previous_english=payload['_previous_english'])
        if action in {'video','all_videos','render_sequence'}:JOBS[jid].update(shot_ids=[s['id'] for s in targets],completed_shot_ids=[])
        if action=='opening_frames':JOBS[jid].update(shot_ids=payload['shot_ids'],completed_shot_ids=[])
        if action=="all_assets":JOBS[jid].update(asset_plan=payload['asset_plan'],asset_prompt_revision=asset_views.PROMPT_REVISION,regenerate_assets=bool(payload.get('regenerate_assets')))
    threading.Thread(target=run_job, args=(jid, pid, action, payload), daemon=True).start()
    return JOBS[jid]


def update_job(jid, **values):
    if values.get("status") not in {"done","error","cancelled"}:check_cancel()
    bounds=getattr(TASK_LOCAL,"progress_range",None)
    if bounds and "progress" in values:values["progress"]=int(bounds[0]+(bounds[1]-bounds[0])*values["progress"]/100)
    with LOCK: JOBS[jid].update(values)


def run_job(jid, pid, action, payload):
    TASK_LOCAL.jid=jid
    TASK_LOCAL.project_id=pid
    TASK_LOCAL.text_config=payload.get('_text_config')
    TASK_LOCAL.video_settings=payload.get('_settings')
    TASK_LOCAL.video_edit_snapshot=action in {'video','all_videos','render_sequence','repair_tail','face_refine','opening_frames'}
    remote_shot=action in {'shot_chat','script_discuss','script_propose'} and payload.get('_text_config',{}).get('provider')=='deepseek'
    director.TASK_CONTEXT.check=check_cancel
    def remember_prompt(url,prompt_id):
        with LOCK:JOBS[jid].setdefault("comfy_prompts",[]).append((url,prompt_id))
    director.TASK_CONTEXT.prompt=remember_prompt
    try:
        update_job(jid, status="queued", message="正在连接 DeepSeek API" if remote_shot else "等待其他模型任务完成", progress=1)
        with (nullcontext() if remote_shot else MODEL_LOCK), power_guard.KeepAwake():
            check_cancel()
            update_job(jid, status="running", message="正在准备", progress=3)
            mode={"analyze":"text","script":"text","storyboard":"text","asset":"image","all_assets":"image","frames":"image","all_frames":"image","video":"video","all_videos":"video","face_refine":"video","review":"vision"}.get(action)
            if action=='storyboard':
                script=load_project(pid).get('script',{})
                scenes=script.get('scenes',[])
                duration=video_settings()['video_duration']
                if scenes and all(x.get('duration_seconds')==duration and x.get('video_prompt') for x in scenes) and len(scenes)*duration==script.get('duration_seconds'):
                    mode=None
            if action=='storyboard' and creative_chat.has_timed_plan(load_project(pid),payload.get('notes','')):mode=None
            if action in {'character_voice','translate_h3','creative_chat','creative_draft','shot_chat'}:mode='text'
            if action in {'asset','all_assets'}:validate_asset_generation(load_project(pid),action,payload)
            if mode and not remote_shot:prepare_model_mode(mode)
            try:
                if action == 'canvas_assistant': canvas_assistant.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'character_voice': character_states.generate_voice(sys.modules[__name__],jid,pid,payload)
                elif action in {'creative_chat','creative_draft'}:creative_chat.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'shot_chat':shot_chat.run(sys.modules[__name__],jid,pid,payload)
                elif action in {'script_discuss','script_propose'}:script_workspace.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'translate_h3':h3_translation.run(sys.modules[__name__],jid,pid,payload)
                elif action == "analyze": do_analyze(jid, pid, payload)
                elif action == "script": do_script(jid, pid, payload)
                elif action == "asset": do_asset(jid, pid, payload)
                elif action == "all_assets": do_all_assets(jid, pid, payload)
                elif action == "storyboard": do_storyboard(jid, pid, payload)
                elif action == "frames": do_frames(jid, pid, payload)
                elif action == "all_frames": do_all_frames(jid, pid, payload)
                elif action == "video": do_video(jid, pid, payload)
                elif action == "all_videos": do_all_videos(jid, pid, payload)
                elif action == "assemble": do_assemble(jid, pid, payload)
                elif action == 'color_match':video_color_match.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'lip_sync':video_lipsync.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'repair_tail':tail_repair.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'opening_frames':opening_frames.run(sys.modules[__name__],jid,pid,payload)
                elif action == "render_sequence": do_render_sequence(jid, pid, payload)
                elif action == 'enhance_video':video_enhance.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'canvas_audio_video':canvas_audio_video.run(sys.modules[__name__],jid,pid,payload)
                elif action == 'canvas_image':canvas_images.generate(sys.modules[__name__],jid,pid,payload)
                elif action == 'canvas_upscale':canvas_images.upscale(sys.modules[__name__],jid,pid,payload)
                elif action in {'canvas_video_generate','canvas_video_upscale','canvas_extract_frame','canvas_trim_video'}:canvas_videos.run(sys.modules[__name__],jid,pid,action,payload)
                elif action == "face_refine": face_refine.run(sys.modules[__name__],jid,pid,payload,payload.get('_settings'))
                elif action == "review": do_review(jid, pid, payload)
                else: raise ValueError("未知任务")
            finally:
                def release_models():
                    if remote_shot:return
                    if mode=='vision' or (mode=='text' and (TASK_LOCAL.text_config or text_models.load())['provider']=='local'):
                        unload_ollama(director.CFG["ollama_model"]);unload_ollama(VISION_MODEL)
                    elif mode == "image":
                        owned={prompt_id for url,prompt_id in JOBS[jid].get('comfy_prompts',[]) if url==director.CFG['qwen_image_url']}
                        stop_comfy("qwen_image",allowed_prompt_ids=owned)
                    elif mode == "video":
                        if sys.exc_info()[0] is not None or not load_settings().get('h3c_resident',True):
                            task_diagnostics.cleanup(h3_native.stop_all)
                        ensure_comfy_idle()
                task_diagnostics.cleanup(release_models)
        check_cancel();update_job(jid, status="done", message="生成完成；期间稿件已修改，本次视频已保留在历史版本" if JOBS[jid].get('superseded_shot_ids') else ("完成；面部精修有跳过项，请查看各段提示" if JOBS[jid].get("face_refine_skipped") else "完成"), progress=100)
    except tail_repair.ReviewRequired as e:
        update_job(jid,status="done",message=str(e),progress=100,needs_tail_review=e.shot_id)
    except Exception as e:
        cancelled=JOBS[jid].get("cancel_requested") or isinstance(e,Cancelled)
        status="cancelled" if cancelled else "error"
        diagnostic_path=Path('logs')/f'job-{jid}.json'
        diagnostic={'job_id':jid,'project_id':pid,'action':action,'shot_id':payload.get('shot_id'),
                    'created_at':JOBS[jid].get('created_at'),'failed_at':now(),'status':status,
                    'last_stage':JOBS[jid].get('message'),'error_type':type(e).__name__,
                    'error':str(e),'traceback':traceback.format_exc()}
        saved=task_diagnostics.write(project_dir(pid)/diagnostic_path,diagnostic)
        if not saved:print(diagnostic['traceback'],file=sys.stderr)
        message="已停止，已完成文件保留" if cancelled else str(e)
        if saved:message+='；错误记录：'+str(diagnostic_path)
        update_job(jid,status=status,message=message,progress=100,diagnostic_path=str(diagnostic_path) if saved else None)
    finally:
        TASK_LOCAL.jid=None
        TASK_LOCAL.project_id=None
        TASK_LOCAL.text_config=None
        TASK_LOCAL.progress_range=None
        TASK_LOCAL.video_settings=None
        TASK_LOCAL.video_edit_snapshot=False
        director.TASK_CONTEXT.check=None;director.TASK_CONTEXT.prompt=None


def do_analyze(jid, pid, payload):
    p = load_project(pid)
    if not p.get("script"):raise ValueError("请先根据需求生成并保存剧本，再提取人物与元素")
    if p.get("uploads"):unload_ollama(director.CFG["ollama_model"])
    refs = []
    for i, item in enumerate(p.get("uploads", [])):
        path = project_dir(pid) / item["path"]
        if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            update_job(jid, message=f"理解参考图 {i+1}/{len(p['uploads'])}", progress=8 + i * 8)
            schema = {"type":"object","properties":{"description":{"type":"string"},"identity":{"type":"string"},"visual_details":{"type":"string"}},"required":["description","identity","visual_details"]}
            try: item["vision"] = ollama_json("分析这张创作参考图。客观描述人物或物品身份、外形、材质、服装、颜色和可保持一致性的特征。输出 JSON。", schema, VISION_MODEL, [path])
            except Exception as e: item["vision"] = {"description":"待人工描述", "identity":item.get("name","参考图"), "visual_details":str(e)}
            refs.append(item["vision"])
    if refs:unload_ollama(VISION_MODEL)
    update_job(jid, message="提取跨场重复人物与物品 · 正在读取剧本，等待模型输出", progress=35)
    schema=element_analysis.schema()
    prompt=element_analysis.prompt(p['script'],refs,payload.get('notes',''),video_settings()['video_duration'])
    prompt+='\n每个人物另写voice_prompt英文音色提示词，包含音高、共鸣、质感、语速和口音，跨镜头保持一致。不声称克隆真人音色。'
    prompt+='\n每个场景另写spatial_anchor：一个符合剧本、明显且固定的空间参照物，例如柱子、灯、沙发或海边灯塔；不得与剧本已有参照物冲突。'
    result=ollama_json(prompt,schema)
    text_models.validate_result(result,schema)
    result=element_analysis.recurring_only(result,len(p['script'].get('scenes',[])))
    old=p.get("analysis",{})
    for kind in ("characters","key_objects","locations"):
        previous={x["name"]:x["id"] for x in old.get(kind,[])}
        for item in result.get(kind,[]):item["id"]=previous.get(item["name"],kind+"_"+uuid.uuid4().hex[:8])
        by_id={item['id']:item for item in result.get(kind,[])}
        for prior in old.get(kind,[]):
            if prior.get('custom'):
                if prior['id'] in by_id:by_id[prior['id']].update(prior)
                else:result.setdefault(kind,[]).append(prior)
            elif kind=='locations' and prior.get('spatial_anchor') and prior['id'] in by_id:
                by_id[prior['id']]['spatial_anchor']=prior['spatial_anchor']
    if old:p.setdefault("analysis_history",[]).append(old)
    old_voices={c['id']:c.get('voice_prompt') for c in old.get('characters',[])}
    for scene in result.get('locations',[]):scene.setdefault('spatial_anchor','一根有明显特征的立柱')
    for c in result.get('characters',[]):c['voice_prompt']=old_voices.get(c['id']) or c.get('voice_prompt') or character_states.DEFAULT_VOICE
    p["analysis"] = result
    p["elements_script_snapshot"]=json.dumps(p["script"],ensure_ascii=False,sort_keys=True)
    p["uploads"] = p.get("uploads", [])
    p["stage"] = "elements"
    sync_shot_elements(p)
    save_project(p)
    update_job(jid, message="人物与元素清单已生成", progress=95)


def spatial_anchor_instructions(p):
    anchors=[{'scene':e.get('name'),'anchor':e.get('spatial_anchor') or '一根有明显特征的立柱'} for e in p.get('analysis',{}).get('locations',[])]
    return ('空间规则：每个场景选定一个固定且明显的空间参照物（如立柱、落地灯或沙发）。'
            '所有人物与物体的位置、走位起点和终点都写相对该参照物的方向及距离；'
            '约定方向以该场景初始3/4建立镜头为固定坐标，镜头转动不改变左右定义。'
            '不要每个镜头更换参照物或凭空改变道具布局。新场景须在action中先定义参照物，再写位置。'
            '现有场景参照物：'+json.dumps(anchors,ensure_ascii=False))


def add_custom_entity(pid,data):
    with PROJECT_LOCK:
        ensure_project_editable(pid);p=load_project(pid)
        kind=data.get('kind');name=str(data.get('name','')).strip()[:100]
        if kind not in ('characters','key_objects','locations') or not name:raise ValueError('请选择类型并填写名称')
        item={'id':kind+'_'+uuid.uuid4().hex[:8],'name':name,'custom':True}
        item['appearance' if kind=='characters' else 'description']=str(data.get('description',''))[:8000]
        if kind=='characters':item.update(wardrobe='',voice_prompt=character_states.DEFAULT_VOICE)
        if kind=='locations':
            anchor=str(data.get('spatial_anchor','')).strip()[:1000]
            if not anchor:raise ValueError('场景必须填写一个明显的固定参照物')
            item['spatial_anchor']=anchor
        p.setdefault('analysis',{}).setdefault(kind,[]).append(item)
        save_project(p);return p


def do_script(jid, pid, payload):
    p = load_project(pid); update_job(jid, message="编写剧本", progress=20)
    if not p.get("brief","").strip():raise ValueError("请先填写创作需求")
    schema={"type":"object","required":["synopsis","duration_seconds","scenes"],"properties":{"synopsis":{"type":"string"},"duration_seconds":{"type":"integer"},"scenes":{"type":"array","items":{"type":"object","required":["scene","location","time","action","dialogue"],"properties":{"scene":{"type":"integer"},"location":{"type":"string"},"time":{"type":"string"},"action":{"type":"string"},"dialogue":{"type":"string"},"sound":{"type":"string"}}}}}}
    prompt=f"你是专业编剧。根据已确认的需求写可拍摄的短片剧本。明确场景、动作、对白和声音；严格遵守人物与关键物品设定。输出 JSON。\n需求：{p['brief']}\n设定：{json.dumps(p.get('analysis',{}),ensure_ascii=False)}\n用户修改意见：{payload.get('notes','')}\n已有剧本：{json.dumps(p.get('script',{}),ensure_ascii=False)}"
    result=ollama_json(prompt+'\n'+spatial_anchor_instructions(p),schema)
    if p.get("script"):p.setdefault("script_history",[]).append(p["script"])
    p["script"]=result; p["stage"]="script"; save_project(p)
    update_job(jid,message="剧本已更新",progress=95)


def entity_from_project(p, eid):
    if not isinstance(eid,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",eid):raise ValueError("元素编号不正确")
    a=p.get("analysis",{})
    for kind in ("characters","key_objects","locations"):
        for item in a.get(kind,[]):
            if item.get("id")==eid:return kind,item
    raise ValueError("未找到人物或元素")


def project_path(pid,relative=""):
    root=project_dir(pid).resolve();target=(root/relative).resolve()
    if not target.is_relative_to(root):raise ValueError("路径超出项目目录")
    return target


def asset_record(p,eid):
    asset=p.setdefault("assets",{}).setdefault(eid,{"images":[]})
    if "versions" not in asset:
        asset["versions"]=[{"id":"legacy","created_at":asset.get("updated_at",p.get("updated_at","")),"images":list(asset.get("images",[])),"status":"done","mode":"text"}] if asset.get("images") else []
    asset.setdefault("selected_images",[])
    # Separate redraw inputs from final candidates. Legacy explicit video picks
    # remain candidates; ordinary source uploads are never silently promoted.
    for upload in p.get('uploads',[]):
        if upload.get('entity_id')==eid and upload['path'] in asset['selected_images'] and not any(upload['path'] in v.get('images',[]) for v in asset['versions']):
            asset['versions'].append({'id':'imported-legacy-'+upload.get('id',uuid.uuid5(uuid.NAMESPACE_URL,upload['path']).hex[:8]),
                'created_at':upload.get('created_at',p.get('updated_at','')),'images':[upload['path']],
                'status':'done','mode':'import','origin':'legacy_manual_selection'})
    if 'source_images' not in asset:
        if 'source_image' in asset:source=asset['source_image'];sources=[source] if source else []
        elif asset.get('reference_mode')=='image' and asset.get('primary_image'):sources=[asset['primary_image']]
        else:sources=[u['path'] for u in p.get('uploads',[]) if u.get('entity_id')==eid and u.get('usage')!='element_result']
        asset['source_images']=list(dict.fromkeys(sources))
    return asset


def input_candidates(p,eid):
    a=asset_record(p,eid)
    deleted={r['path'] for r in a.get('deleted_images',[]) if r.get('role')=='input'}
    return set(a['source_images'])|{u['path'] for u in p.get('uploads',[]) if u.get('entity_id')==eid and u.get('usage')!='element_result' and u['path'] not in deleted}


def generation_sources(p,eid,payload=None):
    a=asset_record(p,eid);payload=payload or {}
    sources=payload.get('source_images',([payload['source_image']] if payload.get('source_image') else a['source_images'])) if payload.get('state_name') else a['source_images']
    if not isinstance(sources,list) or not sources or any(not isinstance(x,str) or x not in a['source_images'] for x in sources):raise ValueError('图生图只使用上方参考图框中的图片，请先拖入或上传参考图')
    if any(not project_path(p['id'],x).is_file() for x in sources):raise ValueError('图生图参考原片缺失，请重新上传')
    return list(dict.fromkeys(sources))


def entity_images(p,eid):
    asset=asset_record(p,eid)
    return list(dict.fromkeys([u["path"] for u in p.get("uploads",[]) if u.get("entity_id")==eid]+[path for version in asset["versions"] for path in version["images"]]))


def ensure_project_editable(pid):
    own=getattr(TASK_LOCAL,"jid",None)
    def own_assistant(j):
        return own is not None and j.get("id")==own and j.get("action")=="canvas_assistant" and getattr(TASK_LOCAL,"project_id",None)==pid
    if any(j.get("project_id")==pid and j.get("status") in {"queued","running"} and not own_assistant(j) for j in JOBS.values()):
        raise ValueError("项目有任务正在执行，请先停止或等待完成再修改")


def edit_entity(pid,eid,data):
    with PROJECT_LOCK:
        ensure_project_editable(pid);p=load_project(pid);kind,item=entity_from_project(p,eid)
        old_description=dict(item)
        old_primary=p.get('assets',{}).get(eid,{}).get('primary_image')
        old_selected=list(p.get('assets',{}).get(eid,{}).get('selected_images',[]))
        imported_layout_changed=False
        for key in ("name","appearance","wardrobe","personality","role","description","story_function","voice_prompt","spatial_anchor"):
            if key in data:item[key]=str(data[key])[:8000]
        if kind=='characters' and 'character_description' in data:
            description=str(data['character_description'])
            if len(description)>16000:raise ValueError('人物描述最多16000字')
            original='\n\n'.join(str(item[k]) for k in ('appearance','wardrobe') if item.get(k))
            if description!=original:
                item['appearance']=description;item['wardrobe']=''
        asset=asset_record(p,eid)
        if 'source_image' in data:
            source=data['source_image']
            if not isinstance(source,str) or (source and source not in input_candidates(p,eid)):raise ValueError('请选择参考图框中的原图')
            asset['source_image']=source;asset['source_images']=[source] if source else []
        if 'source_images' in data:
            sources=data['source_images']
            if not isinstance(sources,list) or any(not isinstance(x,str) or x not in input_candidates(p,eid) for x in sources):raise ValueError('只能添加本元素已有的输入参考图')
            asset['source_images']=list(dict.fromkeys(sources));asset['source_image']='' # No privileged first source.
        if 'source_face_crop' in data:
            if kind!='characters':raise ValueError('正脸原图裁切仅用于人物')
            asset['source_face_crop']=character_sheet_layout.validated_crop(data['source_face_crop'])
        if 'source_layout' in data:
            spec=data['source_layout']
            if kind!='characters' or not isinstance(spec,dict) or spec.get('path') not in asset['source_images'] or spec.get('layout') not in ('auto','',*single_image_edit.LAYOUTS):raise ValueError('请选择本人物参考图及有效布局')
            ref=spec['path'];layout=spec['layout']
            if layout=='auto':
                asset.setdefault('source_layouts',{}).pop(ref,None)
                asset.setdefault('source_panel_edges',{}).pop(ref,None)
            else:
                asset.setdefault('source_layouts',{})[ref]=layout
                edges=spec.get('edges')
                if edges is None and layout in {'four-view','four-view-headless-front'}:edges=single_image_edit.detect_panel_edges(project_path(pid,ref))
                if edges is not None and layout:asset.setdefault('source_panel_edges',{})[ref]=single_image_edit.validated_edges(edges,layout)
                else:asset.setdefault('source_panel_edges',{}).pop(ref,None)
        if "reference_views" in data:asset["reference_views"]=validate_reference_views(data["reference_views"])
        if 'approve_view_version' in data:
            version=next((v for v in asset['versions'] if v.get('id')==data['approve_view_version']),None)
            paths=asset_views.complete_views(version) if version else []
            if not paths or not all(project_path(pid,path).is_file() for path in paths):raise ValueError('需要完整且文件存在的四视图才能确认')
            version['views_verified']=True
            asset['selected_images']=paths;asset['primary_image']=paths[0]
        if "selected_images" in data:
            selected=data["selected_images"]
            result_paths={path for v in asset['versions'] for path in v.get('images',[])}
            if not isinstance(selected,list) or any(not isinstance(x,str) or x not in result_paths for x in selected):raise ValueError("视频参考只能选择下方生成图区域的图片；原图请先导入生成图区")
            asset["selected_images"]=list(dict.fromkeys(selected))
            for version in asset['versions']:
                if version.get('layout_review',{}).get('status')=='needs_review' and any(path in selected for path in version['images']):
                    version['layout_review'].update(status='user_selected',selected_at=now())
            if asset.get("primary_image") not in selected:asset["primary_image"]=selected[0] if selected else ""
        if 'import_layout' in data:
            spec=data['import_layout']
            if not isinstance(spec,dict) or spec.get('layout') not in {'','four-view','four-view-headless-front','face-front-body-back'}:raise ValueError('导入图片布局不正确')
            version=next((v for v in asset['versions'] if v.get('mode')=='import' and spec.get('path') in v.get('images',[])),None)
            if kind!='characters' or not version:raise ValueError('只能设置人物导入图片的布局')
            imported_layout_changed=version.get('reference_layout','')!=spec['layout'] and spec['path'] in asset['selected_images']
            if spec['layout']:version['reference_layout']=spec['layout']
            else:version.pop('reference_layout',None)
        if "primary_image" in data:
            if data["primary_image"] not in asset["selected_images"]:raise ValueError("重绘原图必须先勾选")
            asset["primary_image"]=data["primary_image"]
        if "reference_mode" in data:
            if data["reference_mode"] not in {"text","image"}:raise ValueError("参考模式不正确")
            asset["reference_mode"]=data["reference_mode"]
        if "denoise" in data:
            value=float(data["denoise"])
            if not .2<=value<=.95:raise ValueError("重绘幅度需在 0.2–0.95 之间")
            asset["denoise"]=value
        if old_description!=item or old_primary!=asset.get('primary_image') or old_selected!=asset.get('selected_images') or 'approve_view_version' in data or imported_layout_changed:
            for shot in ordered_shots(p):
                associate_shot_references(p,shot)
                if eid in shot.get('element_ids',[]) and (old_description!=item or shot.get('use_element_references',True)):
                    if shot.get('video'):shot.update(video_stale=True,stale_reason='元素参考设定已更改')
                    video_workflow.invalidate(sys.modules[__name__],p,shot,'上游元素参考图已更改')
        save_project(p);return p


def reference_graph(pid,relative,prompt,width,height,seed,steps,denoise=.65,character_sheet=False,
                    character_view=None,reference_layout=None,reference_crop=None,reference_edges=None,character_denoise=None):
    if not relative:return director.image_graph(prompt,width,height,seed,steps)
    single_image_edit.require_ready(director.CFG)
    refs=sorted(set(relative if isinstance(relative,list) else [relative]))
    # Single-source asset redraw always uses Z-Image; Qwen multi-image tails are independent.
    graph=director.z_image_graph(prompt,width,height,seed,8)
    latent=None
    for i,ref in enumerate(refs):
        source=project_path(pid,ref)
        if not source.is_file() or source.suffix.lower() not in {".png",".jpg",".jpeg",".webp"}:raise ValueError("参考图片不存在或格式不支持")
        layout=reference_layout.get(ref) if isinstance(reference_layout,dict) else reference_layout
        edges=reference_edges.get(ref) if isinstance(reference_edges,dict) else reference_edges
        name=single_image_edit.prepare_source(source,comfy_project_paths(pid)['input'],width,height,view=character_view,layout=layout,crop=reference_crop,edges=edges)
        load_id,encode_id=('12','8') if i==0 else (str(20+i*3),str(21+i*3))
        graph[load_id]={"class_type":"LoadImage","inputs":{"image":name}}
        graph[encode_id]={"class_type":"VAEEncode","inputs":{"pixels":[load_id,0],"vae":["3",0]}}
        if i:
            blend_id=str(22+i*3)
            # Comfy LatentBlend weights samples1 by blend_factor, samples2 by 1-factor.
            graph[blend_id]={"class_type":"LatentBlend","inputs":{"samples1":latent,"samples2":[encode_id,0],"blend_factor":i/(i+1)}}
            latent=[blend_id,0]
        else:latent=[encode_id,0]
    graph['9']['inputs']['latent_image']=latent
    graph["9"]["inputs"]["denoise"]=(single_image_edit.CHARACTER_DENOISE if character_denoise is None else character_denoise) if character_sheet else denoise
    return graph


def do_asset(jid,pid,payload,keep_models=False):
    p=load_project(pid); kind,item=entity_from_project(p,payload["entity_id"])
    validate_asset_generation(p,'asset',payload)
    settings=load_settings();size=settings["reference_size"];steps=settings["image_steps"]
    asset=asset_record(p,item["id"])
    count=validate_reference_views(payload.get("reference_views",asset.get("reference_views",1)))
    if count==0:raise ValueError("该元素已选择跳过，请先选择单张或四视图")
    sheet=kind=='characters'
    if sheet:count=1
    state_name=str(payload.get('state_name','')).strip()[:100]
    state_prompt=str(payload.get('state_prompt','')).strip()[:4000]
    if state_name and (not sheet or not state_prompt):raise ValueError('角色状态需要人物和变化提示词')
    mode=asset.get("reference_mode","text");reference=""
    if state_name:
        mode=payload.get('state_mode','image')
        if mode not in {'text','image'}:raise ValueError('角色状态生成方式不正确')
    references=generation_sources(p,item['id'],payload) if mode=='image' else []
    reference=references[0] if len(references)==1 else references if references else ''
    version_id=datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6]
    out=project_path(pid,f"assets/{item['id']}/{version_id}");out.mkdir(parents=True,exist_ok=True)
    views=[('character-sheet-4view','人物四视图')] if sheet else list(asset_views.LABELS.items())[:count]
    width,height=(min(1536,size*2),size) if sheet else (size,size)
    generated=[];seed_base=int(uuid.uuid4().hex[:8],16)
    version={"id":version_id,"created_at":now(),"images":generated,"status":"running","mode":mode,"reference":reference,"seed":seed_base,"entity":dict(item),"denoise":asset.get("denoise",.65)}
    version['reference_images']=references
    version["view_count"]=count
    if state_name:version.update(state_name=state_name,state_prompt=state_prompt)
    version.update(prompt_revision=asset_views.PROMPT_REVISION,views_verified=False,prompts={})
    version['generation_settings']={'backend':director.CFG.get('image_backend','qwen_image'),'width':width,'height':height,'steps':steps,'effective_denoise':asset.get('denoise',.65) if mode=='image' else 1.0,'shared_seed':kind=='characters'}
    if mode=='image':version['generation_settings'].update(backend='z_image',steps=8,effective_denoise=single_image_edit.CHARACTER_DENOISE if sheet else asset.get('denoise',.65),reference_conditioning=single_image_edit.CONDITIONING,reference_weights=[1/len(references)]*len(references),reference_strategy='equal_vae_latent_blend' if len(references)>1 else 'single_vae_redraw')
    if sheet:version['reference_layout']=asset_views.CHARACTER_SHEET_LAYOUT
    asset["versions"].append(version);asset["images"]=generated;save_project(p)
    try:
        for i,(name,view) in enumerate(views):
            backend=version['generation_settings']['backend']
            model_name='Qwen-Image-Edit-2511' if backend=='qwen_image_edit_2511' else 'Z-Image-Turbo' if backend=='z_image' else 'Qwen-Image'
            update_job(jid,message=f"{model_name} 正在生成 {item['name']}：{name}",image_backend=backend,image_model=model_name,progress=10+i*20)
            prompt=asset_views.character_sheet_prompt(item) if sheet else asset_views.prompt(kind,item,name,p.get('analysis',{}).get('visual_style','cinematic realistic'))
            if state_name:prompt+='\nPreserve the '+('source character identity' if mode=='image' else 'described character identity')+'. Apply the following state or costume changes, overriding conflicting base clothing details: '+state_prompt+' Keep ONE row of four panels in widths 2:1:1:1: one large facial close-up, head-omitted front body below the neck through both feet, complete side full body, complete rear full body. No extra images. The front head area is empty grey; no injury.'
            version['prompts'][name]=prompt
            seed=seed_base if kind=='characters' else seed_base+i
            if sheet:
                target=character_sheet_layout.generate(sys.modules[__name__],jid,p,item,version,out,reference,steps,size,state_prompt)
            else:
                graph=reference_graph(pid,reference,prompt,width,height,seed,steps,asset.get("denoise",.65))
                h=director.queue_and_wait(director.CFG["qwen_image_url"],graph,f"参考图 {name}")
                im=director.first_output(h,"images");src=comfy_project_paths(pid)['output']/im.get("subfolder","")/im["filename"]
                target=out/f"{name}.png";shutil.copy2(src,target)
            generated.append(str(target.relative_to(project_dir(pid).resolve())))
            asset["updated_at"]=now();save_project(p)
        version["status"]="done"
    except Exception as e:
        version["status"]="cancelled" if isinstance(e,Cancelled) or STOPPING.is_set() or JOBS.get(jid,{}).get("cancel_requested") else "error"
        raise
    finally:
        save_project(p)
        if not keep_models:director.free_models(director.CFG["qwen_image_url"])


def all_entities(p):
    return [x for k in ("characters","key_objects","locations") for x in p.get("analysis",{}).get(k,[])]


def ordered_shots(p):
    return sorted(p.get("shots",[]),key=lambda s:int(s["shot"]))


def validate_reference_views(value):
    if type(value) is not int or value not in {0,1,4}:raise ValueError("参考图数量只能选择跳过、1张或4张")
    return value


def normalize_asset_plan(p,plan=None):
    defaults={e["id"]:p.get("assets",{}).get(e["id"],{}).get("reference_views",1) for kind in ("characters","key_objects","locations") for e in p.get("analysis",{}).get(kind,[])}
    characters={e['id'] for e in p.get('analysis',{}).get('characters',[])}
    def actual(eid,value):
        count=validate_reference_views(value)
        return 1 if count and eid in characters else count
    if plan is None:return {eid:actual(eid,count) for eid,count in defaults.items()}
    if not isinstance(plan,dict) or any(eid not in defaults for eid in plan):raise ValueError("生成清单包含未知元素")
    return {eid:actual(eid,plan.get(eid,0)) for eid in defaults}


def do_all_assets(jid,pid,payload):
    p=load_project(pid);entities=all_entities(p)
    validate_asset_generation(p,'all_assets',payload)
    plan=normalize_asset_plan(p,payload.get("asset_plan"))
    if not entities:raise ValueError("请先从剧本提取人物与元素")
    active_backend=None
    try:
        for item in entities:
            count=plan[item["id"]]
            if not count:continue
            check_cancel();fresh=load_project(pid);a=asset_record(fresh,item["id"])
            if not payload.get('regenerate_assets') and reusable_asset(fresh,item['id'],count):continue
            backend='z_image' if a.get('reference_mode')=='image' else director.CFG.get('image_backend','qwen_image')
            if active_backend and active_backend!=backend:
                stop_comfy('qwen_image');ensure_comfy_started('qwen_image')
            do_asset(jid,pid,{"entity_id":item["id"],"reference_views":count},keep_models=True)
            active_backend=backend
    finally:director.free_models(director.CFG["qwen_image_url"])


def reusable_asset(p,eid,count):
    character=entity_from_project(p,eid)[0]=='characters'
    a=asset_record(p,eid)
    if any(v.get('mode')=='import' and not v.get('state_name') and v.get('status')=='done'
           and len(v.get('images',[]))>=count and any(path in a['selected_images'] for path in v['images'])
           and all(project_path(p['id'],path).is_file() for path in v['images']) for v in a['versions']):return True
    return any(not v.get('state_name') and v.get('prompt_revision',0)>=(asset_views.PROMPT_REVISION if character else 5)
               and not (character and character_image_edit.legacy_redraw(v))
               and v.get('layout_review',{}).get('status') not in {'needs_revision','needs_review'}
               and v.get('status')=='done' and len(v.get('images',[]))>=count
               and all(project_path(p['id'],f).is_file() for f in v['images'])
               for v in asset_record(p,eid)['versions'])


def validate_asset_generation(p,action,payload):
    if action=='all_assets':
        plan=normalize_asset_plan(p,payload.get('asset_plan'))
        for eid,count in plan.items():
            if count and (payload.get('regenerate_assets') or not reusable_asset(p,eid,count)):
                validate_asset_generation(p,'asset',{'entity_id':eid})
        return
    kind,item=entity_from_project(p,payload.get('entity_id'))
    asset=asset_record(p,item['id'])
    mode=payload.get('state_mode','image') if payload.get('state_name') else asset.get('reference_mode','text')
    if mode not in {'text','image'}:raise ValueError('角色状态生成方式不正确')
    if mode=='image':
        single_image_edit.require_ready(director.CFG)
        generation_sources(p,item['id'],payload)


def do_storyboard(jid,pid,payload):
    p=load_project(pid); update_job(jid,message="把剧本拆成镜头",progress=25)
    if creative_chat.has_timed_plan(p,payload.get("notes","")):return creative_chat.storyboard(sys.modules[__name__],jid,p)
    if not p.get("script"):raise ValueError("请先生成或保存剧本；文字任务不需要参考图")
    p.setdefault('analysis',{})
    seconds=float(p["script"].get("duration_seconds",0))
    if not math.isfinite(seconds) or not 0<seconds<=300:raise ValueError("剧本 duration_seconds 需为 1–300 秒，更长影片请分成多个项目")
    duration=video_settings()['video_duration']
    count=math.ceil(seconds/duration)
    entities=all_entities(p);ids=[e["id"] for e in entities]
    fields={k:{"type":"string"} for k in ("title","description","motion_prompt","dialogue","camera")}
    id_schema={"type":"string",**({'enum':ids} if ids else {})}
    fields["element_ids"]={"type":"array","items":id_schema}
    fields['source_scene_indices']={'type':'array','minItems':1,'items':{'type':'integer','enum':list(range(1,len(p['script'].get('scenes',[]))+1))}}
    fields["character_actions"]={"type":"array","items":{"type":"object","required":["character_id","action","element_ids"],"properties":{"character_id":{"type":"string"},"action":{"type":"string"},"element_ids":{"type":"array","items":id_schema}}}}
    schema={"type":"object","required":["shots"],"properties":{"shots":{"type":"array","minItems":count,"maxItems":count,"items":{"type":"object","required":list(fields),"properties":fields}}}}
    prompt=f"你是分镜导演。按剧情先后把剧本拆成恰好 {count} 个视频任务，每段严格 {duration} 秒，总长 {count*duration} 秒。不足 {duration} 秒的尾段以自然停顿补足，不能遗漏剧情。每段列出全部使用的 element_ids（人物、物品、场景），character_actions 逐人物说明 0–{duration} 秒的动作及调用的物品/场景 ID，ID 必须来自设定。camera 用中文写景别、角度、构图和运镜。start_prompt/end_prompt 用英文完整描述首尾帧；motion_prompt 用英文逐时段写动作、镜头、声音、物理约束。完整复述人物外貌服装与元素特征，不写 same/as before。不要让单段承担超出 {duration} 秒的动作或对白。输出 JSON。\n设定：{json.dumps(p['analysis'],ensure_ascii=False)}\n剧本：{json.dumps(p['script'],ensure_ascii=False)}\n修改意见：{payload.get('notes','')}"
    prompt=prompt.replace("start_prompt/end_prompt 用英文完整描述首尾帧；","")
    # The saved task duration, rather than a hard-coded five seconds, drives every stage.
    prompt+="\n直接生成文字视频任务，不生成或输出首尾帧提示词。用文字描述跨镜头动作、人物、环境的连续性；换场按剧本安排。"
    prompt+='\n每个镜头的source_scene_indices必须填写来源剧本场次在scenes数组中的序号（从1开始）；一场拆多镜头可重复该序号，一个镜头合并多场可列多个序号。它用于按出场表关联元素，不要以镜头序号代替。'
    prompt+='\n'+spatial_anchor_instructions(p)
    if not ids:prompt+='\n尚无元素清单，element_ids与character_actions返回空数组；在description和motion_prompt中完整描述人物、物品与场景。参考图不是文字任务的前置条件。'
    scenes=p['script'].get('scenes',[])
    if len(scenes)==count and all(s.get('duration_seconds')==duration and s.get('video_prompt') for s in scenes):
        # Authored, timed prompts are already tasks; no model or image generation needed.
        raw=[]
        for i,s in enumerate(scenes):
            raw.append(dict(title=s.get('title',f'镜头{i+1}'),description=s.get('action',''),camera=s.get('camera',''),
                motion_prompt=s['video_prompt'],dialogue=s.get('dialogue',''),element_ids=[],character_actions=[],source_scene_indices=[i+1],
                keyframe_prompt=s.get('keyframe_prompt',''),scene_prompt=s.get('scene_prompt',''),
                transition='continue' if s.get('inherit_previous_frame') else 'cut',
                inherit_previous=i>0))
        result={'shots':raw}
    else:
        prompt+=h3_prompt_skill.instructions(duration)
        result=ollama_json(prompt,schema)
        try:h3_prompt_skill.validate_shots(result)
        except ValueError as error:
            update_job(jid,message='H3 SKILL 格式校验未通过，正在纠正一次',progress=50)
            result=ollama_json(prompt+'\n上次输出格式错误：'+str(error)+'\n请重新生成完整合规 JSON。',schema)
            h3_prompt_skill.validate_shots(result)
        for shot in result['shots']:shot['h3_prompt_skill_revision']=h3_prompt_skill.REVISION
    shots=normalize_video_shots(p,result["shots"],count,duration)
    if p.get("shots"):p.setdefault("storyboard_history",[]).append({"shots":p["shots"],"final_video":p.get("final_video"),"created_at":now()})
    p["shots"]=shots;p.pop("final_video",None);p.pop("final_review",None)
    p["planned_duration"]=count*duration
    p['shot_duration']=duration
    p["storyboard_script_snapshot"]=json.dumps(p["script"],ensure_ascii=False,sort_keys=True)
    p["storyboard_elements_snapshot"]=json.dumps(p["analysis"],ensure_ascii=False,sort_keys=True)
    p["stage"]="storyboard"; save_project(p); update_job(jid,message="分镜脚本已生成",progress=95)


def normalize_five_second_shots(p,shots,count):
    return normalize_video_shots(p,shots,count,5)


def normalize_video_shots(p,shots,count,duration):
    duration=video_timing.validate_duration(duration)
    if len(shots)!=count:raise ValueError("模型返回的任务数量不正确，请重新拆分")
    entities={e["id"]:e for e in all_entities(p)};chars={e["id"] for e in p["analysis"].get("characters",[])}
    revision=uuid.uuid4().hex[:8]
    for i,s in enumerate(shots,1):
        used=list(s.get("element_ids",[]))
        for actor in s.get("character_actions",[]):
            if actor["character_id"] not in chars:raise ValueError("分镜引用了未知人物，请重新拆分")
            used.extend([actor["character_id"],*actor.get("element_ids",[])])
        used=list(dict.fromkeys(used))
        if any(e not in entities for e in used):raise ValueError("分镜引用了未知元素，请重新拆分")
        if (set(used)&chars)!={a["character_id"] for a in s.get("character_actions",[])}:raise ValueError("分镜缺少出场人物的动作描述，请重新拆分")
        s.update(id=f"shot-{i:02d}-{revision}",shot=i,duration=duration,exact_duration=True,timeline_start=(i-1)*duration,timeline_end=i*duration,status="planned",element_ids=used)
        sources=s.get('source_scene_indices')
        if sources is not None:
            if not sources or any(type(n) is not int or not 1<=n<=len(p.get('script',{}).get('scenes',[])) for n in sources):
                raise ValueError('分镜来源场次无效，请重新拆分')
            s.update(source_scene_indices=sorted(set(sources)),source_script_key=shot_elements.script_key(p['script']))
        s['inherit_previous']=i>1
        shot_elements.resolve(p,s)
        used=s['element_ids']
        refs=[p.get("assets",{}).get(e,{}).get("primary_image") for e in used]
        s["reference_images"]=[r for r in refs if r]
        character_refs=[p.get("assets",{}).get(e,{}).get("primary_image") for e in used if e in chars]
        s["reference_image"]=next((r for r in character_refs if r),next(iter(s["reference_images"]),""))
        s["auto_reference"]=True
        s["transition"]="cut" if i==1 else ("cut" if s.get("transition")=="cut" else "continue")
    return shots


def previous_continuous_shot(p,s):
    shots=ordered_shots(p)
    index=next((i for i,x in enumerate(shots) if x is s or x.get("id")==s.get("id")),0)
    if index==0 or s.get("transition")=="cut":return None
    previous=shots[index-1]
    if "transition" not in s:
        locations={e["id"] for e in p.get("analysis",{}).get("locations",[])}
        before=set(previous.get("element_ids",[]))&locations;after=set(s.get("element_ids",[]))&locations
        if before and after and before!=after:return None
    return previous


def associate_shot_references(p,s):
    shot_elements.resolve(p,s)
    bindings=asset_views.reference_bindings(p,s)
    s["reference_bindings"]=bindings;s["reference_images"]=list(dict.fromkeys(b["image"] for b in bindings))
    chars={e["id"] for e in p.get("analysis",{}).get("characters",[])}
    bindings.sort(key=lambda b:b["entity_id"] not in chars)
    if s.get("auto_reference",True):s["reference_image"]=bindings[0]["image"] if bindings else ""
    if s.get('element_association_warning') and s.get('auto_elements',True):
        s.setdefault('reference_warnings',[]).append(s['element_association_warning'])
        s.setdefault('reference_blockers',[]).append(s['element_association_warning'])
    return s.get("reference_image","")


def sync_shot_elements(p):
    for shot in ordered_shots(p):
        before=(list(shot.get('element_ids',[])),list(shot.get('reference_images',[])))
        associate_shot_references(p,shot)
        after=(shot.get('element_ids',[]),shot.get('reference_images',[]))
        if shot.get('video') and before!=after:
            shot.update(video_stale=True,stale_reason='镜头自动关联元素已更新')
            video_workflow.invalidate(sys.modules[__name__],p,shot,'上游镜头元素关联已更新')


def invalidate_following_videos(p,s):
    shots=ordered_shots(p);index=next((i for i,x in enumerate(shots) if x is s or x.get("id")==s.get("id")),0)
    for following in shots[index+1:]:
        if previous_continuous_shot(p,following) is None:break
        if following.get("video"):
            following.setdefault("media_history",[]).append({k:following[k] for k in ("video","source_video","review","start_frame","end_frame") if k in following})
        for key in ("video","source_video","review","continuity_source_video"):following.pop(key,None)
        following["status"]="frames_ready" if following.get("end_frame") else "planned"
    p.pop("final_video",None);p.pop("final_review",None)


def extract_video_tail(pid,video,shot_id):
    out=project_dir(pid)/"frames";out.mkdir(exist_ok=True)
    target=out/f"{shot_id}_actual_tail_{uuid.uuid4().hex[:8]}.png"
    # Decode the final second and overwrite the same PNG until the final decoded frame.
    run_ffmpeg([get_ffmpeg(),"-y","-sseof","-1","-i",str(project_path(pid,video)),"-an","-fps_mode","passthrough","-update","1",str(target)])
    if not target.is_file():raise RuntimeError("未能提取上一段实际尾帧")
    return str(target.relative_to(project_dir(pid)))


def shot_prompt(p,s,prompt):
    specs=[]
    for eid in s.get("element_ids",[]):
        kind,item=entity_from_project(p,eid)
        specs.append(item.get('name',eid)+': '+asset_views.visual_description(kind,item))
    actions=[]
    for action in s.get('character_actions',[]):
        name=next((e.get('name',e['id']) for e in all_entities(p) if e['id']==action.get('character_id')), 'Subject')
        actions.append(name+': '+str(action.get('action','')))
    return (prompt+'\n'+character_states.voices(p,s)+'\nSubject appearance (context only, not printed labels): '+'; '.join(specs)
            +'\nCharacter actions: '+'; '.join(actions)+'\nCamera: '+s.get('camera','')
            +'\n'+director.NO_VISIBLE_TEXT)


def find_shot(p,sid):
    for s in p.get("shots",[]):
        if s["id"]==sid:return s
    raise ValueError("未找到镜头")


def delete_shot_video(pid,sid):
    with PROJECT_LOCK:
        ensure_project_editable(pid);p=load_project(pid);shot=find_shot(p,sid)
        if not shot.get("video"):raise ValueError("该镜头没有可删除的视频")
        result={k:shot[k] for k in ("video","source_video","review","video_mode","continuity_source_video") if k in shot}
        record={"id":uuid.uuid4().hex,"deleted_at":now(),"result":result}
        project_storage.recycle_video(sys.modules[__name__],pid,record)
        shot.setdefault("deleted_videos",[]).append(record)
        for key in result:shot.pop(key,None)
        shot["status"]="planned"
        if p.get("final_video"):
            p.setdefault("invalidated_final_videos",[]).append({"video":p.pop("final_video"),"review":p.pop("final_review",None),"reason":"镜头视频被删除","created_at":now()})
        p.pop("final_review",None)
        video_workflow.invalidate(sys.modules[__name__],p,shot,'上一段视频已删除')
        save_project(p);return project_view(p)


def delete_video_version(pid,sid,version_id):
    """Hide one historical take without changing current continuity or finished films."""
    with PROJECT_LOCK:
        ensure_project_editable(pid);p=load_project(pid);shot=find_shot(p,sid)
        version=next((v for v in video_choices.versions(shot) if v['id']==version_id),None)
        if not version:raise ValueError("该历史版本不存在或已删除，请刷新页面")
        if version['current']:raise ValueError("该版本是当前视频，请使用当前视频的删除按钮")
        result={k:version[k] for k in video_choices.RESULT_FIELDS if k in version}
        record={"id":uuid.uuid4().hex,"deleted_at":now(),"scope":"history",
                "version_id":version_id,"version_number":version['number'],"result":result}
        project_storage.recycle_video(sys.modules[__name__],pid,record)
        shot.setdefault('deleted_videos',[]).append(record)
        if video_choices.selection(p,shot)==version_id:
            p.setdefault('assembly_choices',{})[sid]=None
        save_project(p);return project_view(p)


def restore_shot_video(pid,sid,record_id):
    with PROJECT_LOCK:
        ensure_project_editable(pid);p=load_project(pid);shot=find_shot(p,sid)
        records=shot.get("deleted_videos",[]);record=next((r for r in records if r["id"]==record_id),None)
        if record is None:raise ValueError("未找到视频回收记录")
        historical=record.get('scope')=='history'
        if shot.get("video") and not historical:raise ValueError("该镜头已有视频，请先删除当前版本再恢复，避免覆盖")
        result=record["result"]
        if not project_path(pid,result["video"]).is_file():
            recovered=record.get('recovery_files',{}).get('video')
            if not recovered or not project_path(pid,recovered).is_file():raise ValueError("原视频文件已被移动或删除，无法恢复")
            target=project_path(pid,result['video']);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(project_path(pid,recovered),target)
        if historical:
            if not any(v.get('video')==result['video'] for v in shot.get('media_history',[])):
                shot.setdefault('media_history',[]).append(result)
        else:
            shot.update(result);shot["status"]="video_ready"
            video_workflow.invalidate(sys.modules[__name__],p,shot,'上一段视频版本已恢复，请检查衔接')
        records.remove(record)
        save_project(p);return project_view(p)


def do_frames(jid,pid,payload):
    p=load_project(pid); s=find_shot(p,payload["shot_id"]); out=project_dir(pid)/"frames";out.mkdir(exist_ok=True)
    settings=load_settings();width=settings["image_width"];height=settings["image_height"];steps=settings["image_steps"]
    try:
        generate_frames_for_shot(jid,pid,p,s,out,width,height,steps,15,40)
    finally:director.free_models(director.CFG["qwen_image_url"])
    s["status"]="frames_ready";save_project(p)


def generate_frames_for_shot(jid,pid,p,s,out,width,height,steps,base_progress,step_progress):
    invalidate_following_videos(p,s)
    if s.get("video"):
        s.setdefault("media_history",[]).append({k:s[k] for k in ("start_frame","end_frame","video","source_video","review") if k in s})
        for key in ("video","source_video","review"):s.pop(key,None)
    s["status"]="generating_frames"
    p.pop("final_video",None);p.pop("final_review",None)
    if s.get("exact_duration"):
        settings=load_settings();width=settings["video_width"]*2;height=settings["video_height"]*2
    reference=associate_shot_references(p,s)
    if not reference and s.get("auto_reference"):
        chars={e["id"] for e in p.get("analysis",{}).get("characters",[])}
        ids=sorted(s.get("element_ids",[]),key=lambda eid:eid not in chars)
        reference=next((p.get("assets",{}).get(eid,{}).get("primary_image") for eid in ids if p.get("assets",{}).get(eid,{}).get("primary_image")),"")
        s["reference_image"]=reference
    if reference:
        selected=[r for asset in p.get("assets",{}).values() for r in asset.get("selected_images",[])]
        if reference not in selected:raise ValueError("镜头参考图已取消选用，请重新选择")
    for i,(kind,prompt) in enumerate((("start",s["start_prompt"]),("end",s["end_prompt"]))):
        previous=previous_continuous_shot(p,s)
        if kind=="start" and previous:
            source=previous.get("end_frame")
            if previous.get("video"):source=extract_video_tail(pid,previous["video"],previous["id"])
            if not source or not project_path(pid,source).is_file():raise ValueError("连续镜头请先生成上一段尾帧，或将本镜头设为切镜／换场")
            s["start_frame"]=source;s["continuity_source_shot"]=previous["id"];save_project(p);continue
        update_job(jid,message=f"生成 {s['title']} {kind} 帧（模型保持加载）",progress=min(94,base_progress+i*step_progress))
        graph=reference_graph(pid,reference,shot_prompt(p,s,prompt),width,height,2000+int(s["shot"])*2+i,steps,.8)
        h=director.queue_and_wait(director.CFG["qwen_image_url"],graph,f"{kind} frame")
        im=director.first_output(h,"images");src=comfy_project_paths(pid)['output']/im.get("subfolder","")/im["filename"]
        target=out/f"{s['id']}_{kind}_{uuid.uuid4().hex[:8]}.png";shutil.copy2(src,target);s[f"{kind}_frame"]=str(target.relative_to(project_dir(pid)))
        save_project(p)


def do_all_frames(jid,pid,payload):
    p=load_project(pid);shots=ordered_shots(p)
    if not shots:raise ValueError("还没有分镜")
    out=project_dir(pid)/"frames";out.mkdir(exist_ok=True);settings=load_settings()
    try:
        for index,s in enumerate(shots):
            check_cancel()
            previous=previous_continuous_shot(p,s)
            linked=not previous or s.get("continuity_source_shot")==previous.get("id")
            if payload.get("resume") and linked and s.get("status") in {"frames_ready","video_ready","reviewed"} and all(s.get(k) and project_path(pid,s[k]).is_file() for k in ("start_frame","end_frame")):continue
            generate_frames_for_shot(jid,pid,p,s,out,settings["image_width"],settings["image_height"],settings["image_steps"],8+int(index*84/len(shots)),int(42/len(shots)))
            s["status"]="frames_ready";save_project(p)
    finally:director.free_models(director.CFG["qwen_image_url"])


def generate_video_for_shot(jid,pid,p,s,settings,label,progress):
    return video_workflow.render(sys.modules[__name__],jid,p,s,settings,label,progress)


def do_video(jid,pid,payload):
    p=load_project(pid);s=find_shot(p,payload["shot_id"]);settings=video_settings()
    try:
        result=generate_video_for_shot(jid,pid,p,s,settings,"H3 视频",15)
        face_refine.after(sys.modules[__name__],jid,pid,s['id'],result,settings)
    except BaseException:
        task_diagnostics.cleanup(h3_native.stop_all)
        raise
    if not settings.get('h3c_resident',True):h3_native.stop_all()
    if jid in JOBS:update_job(jid,completed_shot_ids=[s["id"]])
    if settings.get('video_upscale') and not (result or {}).get('superseded'):video_enhance.run(sys.modules[__name__],jid,pid,{'shot_id':s['id'],'scale':settings['video_upscale']})


def do_all_videos(jid,pid,payload):
    p=load_project(pid);shots=video_choices.generation_shots(sys.modules[__name__],p,payload);settings=video_settings()
    if not shots:raise ValueError("还没有分镜")
    missing=[str(s.get("shot")) for s in shots if not s.get("description") and not s.get("motion_prompt")]
    if missing:raise ValueError("这些镜头还没有文字内容："+"、".join(missing))
    try:
        for index,s in enumerate(shots):
            check_cancel()
            p=load_project(pid);s=find_shot(p,s['id'])
            if payload.get("resume") and s.get("video") and not s.get('video_stale') and project_path(pid,s["video"]).is_file():
                if jid in JOBS:update_job(jid,completed_shot_ids=[*JOBS[jid].get("completed_shot_ids",[]),s["id"]])
                continue
            result=generate_video_for_shot(jid,pid,p,s,settings,f"H3 视频 {index+1}/{len(shots)} · 第 {s.get('shot')} 段",8+int(index*86/len(shots)))
            face_refine.after(sys.modules[__name__],jid,pid,s['id'],result,settings)
            if jid in JOBS:update_job(jid,completed_shot_ids=[*JOBS[jid].get("completed_shot_ids",[]),s["id"]])
    except BaseException:
        task_diagnostics.cleanup(h3_native.stop_all)
        raise
    if not settings.get('h3c_resident',True):h3_native.stop_all()


def do_render_sequence(jid,pid,payload):
    p=load_project(pid)
    if not p.get("shots"):raise ValueError("请先拆分视频任务")
    if not all(s.get("exact_duration") for s in p["shots"]):raise ValueError("旧分镜请先按新流程重新拆分视频任务，已有文件会保留")
    for key,snapshot in (("script","storyboard_script_snapshot"),):
        if p.get(snapshot)!=json.dumps(p.get(key),ensure_ascii=False,sort_keys=True):raise ValueError("剧本已修改，请重新拆分任务后再生成")
    if p.get("script",{}).get("required_aspect")=="16:9":
        settings=video_settings()
        if settings["video_width"]*9!=settings["video_height"]*16:raise ValueError("此项目要求16:9横屏，请先在生成设置中将视频宽高设为512×288等16:9尺寸；未启动模型")
    try:
        TASK_LOCAL.progress_range=(3,99)
        check_cancel();prepare_model_mode("video")
        do_all_videos(jid,pid,{**payload,"resume":"shot_ids" not in payload})
    finally:
        TASK_LOCAL.progress_range=None
        for key in ("qwen_image",):
            # The stop controller handles owned active prompts on cancellation.
            try:task_diagnostics.cleanup(lambda:stop_comfy(key))
            except ValueError:pass


def get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:
        raise RuntimeError("视频处理环境不可用，请通过“启动_AI影视工作台.command”重新打开工作台") from error


def verify_video_processing():
    ffmpeg=get_ffmpeg()
    try:
        subprocess.run([ffmpeg,'-version'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10,check=True)
    except (OSError,subprocess.SubprocessError) as error:
        raise RuntimeError('视频处理组件启动检查失败，工作台未启动；请查看启动日志') from error
    return ffmpeg


def run_ffmpeg(command):
    check_cancel()
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        while process.poll() is None:check_cancel();time.sleep(.2)
        if process.returncode:raise RuntimeError("视频处理失败")
        check_cancel()
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


def do_assemble(jid,pid,payload):
    if 'clips' in payload:return video_choices.assemble(sys.modules[__name__],jid,pid,payload)
    p=load_project(pid); videos=[]
    audio_options=project_audio.mux_options(sys.modules[__name__],p)
    for s in ordered_shots(p):
        if s.get('video_stale'):raise ValueError(f"镜头 {s.get('shot')} 的上游参考已变化，请先重新生成")
        if not s.get("video"): raise ValueError(f"镜头 {s.get('shot')} 尚未生成视频")
        videos.append((project_dir(pid)/s["video"]).resolve())
    if not videos: raise ValueError("还没有可串联的视频")
    update_job(jid,message="正在串联全部镜头",progress=35)
    out=project_dir(pid)/"final";out.mkdir(exist_ok=True);concat=out/"concat.txt"
    concat.write_text("".join("file '"+str(v).replace("'","'\\''")+"'\n" for v in videos),encoding="utf-8")
    target=out/f"final_cut_{uuid.uuid4().hex[:8]}.mp4"
    exact=bool(audio_options) or all(s.get("exact_duration") for s in p["shots"])
    options=["-vf","setpts=PTS-STARTPTS,fps=24:start_time=0","-af","asetpts=PTS-STARTPTS","-t",str(sum(video_timing.shot_duration(s) for s in p['shots'])),"-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac"] if exact else ["-c","copy"]
    run_ffmpeg([get_ffmpeg(),"-y","-f","concat","-safe","0","-i",str(concat),*audio_options,*options,str(target)])
    p["final_video"]=str(target.relative_to(project_dir(pid)));p["stage"]="video";save_project(p)
    if video_settings().get('video_upscale'):
        video_enhance.run(sys.modules[__name__],jid,pid,{'shot_id':'__final__','scale':video_settings()['video_upscale']})


def do_review(jid,pid,payload):
    p=load_project(pid);is_final=payload.get("shot_id")=="__final__"
    s={"id":"final","title":"最终合片","video":p.get("final_video"),"shots":p.get("shots",[])} if is_final else find_shot(p,payload["shot_id"])
    if not s.get("video"):raise ValueError("请先生成视频")
    update_job(jid,message="抽取视频检查帧",progress=15)
    video=project_dir(pid)/s["video"]; frames=project_dir(pid)/"reviews"/s["id"];frames.mkdir(parents=True,exist_ok=True)
    ffmpeg=get_ffmpeg()
    pattern=str(frames/"frame_%02d.jpg")
    run_ffmpeg([ffmpeg,"-y","-i",str(video),"-vf","fps=1,scale=640:-1",pattern])
    images=sorted(frames.glob("*.jpg"))[:8];update_job(jid,message="视觉模型检查连续性与漏洞",progress=45)
    schema={"type":"object","required":["decision","score","summary","issues","confirmation_questions"],"properties":{"decision":{"type":"string","enum":["pass","revise","reject"]},"score":{"type":"integer"},"summary":{"type":"string"},"issues":{"type":"array","items":{"type":"object","required":["severity","time","problem","suggestion"],"properties":{"severity":{"type":"string"},"time":{"type":"string"},"problem":{"type":"string"},"suggestion":{"type":"string"}}}},"confirmation_questions":{"type":"array","items":{"type":"string"}}}}
    prompt=f"你是严格的影视质检员。以下图片按时间顺序抽自同一个视频。对照分镜和连续性要求，检查人物身份/服装/手指、关键物品、空间关系、运动逻辑、画面闪烁、变形、穿帮、首尾帧匹配。只报告肉眼明确可见的问题；给出是否通过和需要用户确认的问题。输出 JSON。\n分镜：{json.dumps(s,ensure_ascii=False)}\n项目设定：{json.dumps(p.get('analysis',{}),ensure_ascii=False)}"
    result=ollama_json(prompt,schema,VISION_MODEL,images)
    if is_final:p["final_review"]=result
    else:s["review"]=result;s["status"]="reviewed"
    save_project(p)


def service_status(url):
    try: json_request(url, timeout=2); return True
    except Exception: return False


def ollama_model_available(name):
    try:
        tags=json_request(director.CFG["ollama_url"]+"/api/tags",timeout=2).get("models",[])
        return any(m.get("name")==name or m.get("model")==name for m in tags)
    except Exception:return False


def project_view(p):
    p["storage_path"]=str(project_dir(p["id"]))
    import canvas_image_references
    for kind in ('characters','locations','key_objects'):
        for item in p.get('analysis',{}).get(kind,[]):
            if 'canvas_redraw_links' not in item and item.get('canvas_origin',{}).get('operation')=='extract_frame':
                item['canvas_redraw_links']=canvas_image_references.links(sys.modules[__name__],p,item)
    p['opening_frame_catalog']=opening_frames.view(sys.modules[__name__],p)
    p['character_image_edit']=single_image_edit.status(director.CFG)
    for eid in list(p.get("assets",{})):asset_record(p,eid)
    first=next(iter(ordered_shots(p)),None)
    for shot in p.get("shots",[]):
        associate_shot_references(p,shot)
        shot.setdefault("transition","continue" if previous_continuous_shot(p,shot) else "cut")
        shot.setdefault('inherit_previous',shot is not first)
        shot.setdefault('use_element_references',True)
        shot.setdefault('manual_reference_images',[])
        shot['video_references'],shot['previous_tail_pending']=video_workflow.references(sys.modules[__name__],p,shot)
        shot['tail_repair_view']=tail_repair.view(sys.modules[__name__],p,shot)
        shot['audio_reference_timing']=project_audio.reference_timing(p,shot)
        shot['video_versions']=video_choices.versions(shot)
        shot['assembly_version_id']=video_choices.selection(p,shot)
    for item in p.get('canvas_videos',[]):
        item['video_references']=canvas_videos.refs(sys.modules[__name__],p,item)
        item['video_versions']=video_choices.versions(item)
    return p


class Handler(BaseHTTPRequestHandler):
    def parse_request(self):
        if not super().parse_request():return False
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host','') not in allowed:
            self.send_error(403);return False
        return True
    def log_message(self, fmt, *args): pass
    def send_json(self,obj,status=200):
        data=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def body(self):
        n=int(self.headers.get("Content-Length","0"));return json.loads(self.rfile.read(n) or b"{}")
    def do_DELETE(self):
        path=unquote(urlparse(self.path).path)
        origin=self.headers.get("Origin")
        if origin and urlparse(origin).netloc!=self.headers.get("Host"):return self.send_json({"error":"不允许跨站操作"},403)
        image_match=re.fullmatch(r"/api/projects/([^/]+)/entities/([^/]+)/images",path)
        if image_match:
            try:
                data=self.body();return self.send_json(asset_images.delete(sys.modules[__name__],*image_match.groups(),data.get('path'),role=data.get('role','result')))
            except (FileNotFoundError,ValueError) as e:return self.send_json({'error':str(e)},409)
        version_match=re.fullmatch(r"/api/projects/([^/]+)/videos/([^/]+)/versions/([^/]+)",path)
        if version_match:
            try:return self.send_json(delete_video_version(*version_match.groups()))
            except FileNotFoundError as e:return self.send_json({"error":str(e)},404)
            except ValueError as e:return self.send_json({"error":str(e)},409)
        video_match=re.fullmatch(r"/api/projects/([^/]+)/videos/([^/]+)",path)
        if video_match:
            try:return self.send_json(delete_shot_video(*video_match.groups()))
            except FileNotFoundError as e:return self.send_json({"error":str(e)},404)
            except ValueError as e:return self.send_json({"error":str(e)},409)
        m=re.fullmatch(r"/api/projects/([^/]+)",path)
        if not m:return self.send_error(404)
        try:return self.send_json(delete_project(m.group(1)))
        except FileNotFoundError as e:return self.send_json({"error":str(e)},404)
        except ValueError as e:return self.send_json({"error":str(e)},409)
    def chat_stream(self,data):
        payload=chat_payload(data.get("messages",[]));payload["stream"]=True
        self.send_response(200)
        self.send_header("Content-Type","application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Connection","close");self.end_headers();self.close_connection=True
        def emit(event):
            self.wfile.write((json.dumps(event,ensure_ascii=False)+"\n").encode());self.wfile.flush()
        started=time.monotonic()
        try:
            if text_models.load()['provider']!='local':
                emit({'status':'文字API正在处理…'})
                reply=qwen_chat(data.get('messages',[]))
                emit({'delta':reply['content']})
                emit({'done':True,'seconds':round(time.monotonic()-started,1),'load_seconds':0,'tokens_per_second':0})
                return
            emit({"status":"正在释放其他模型；首次加载 Qwen 可能较慢…"})
            prepare_model_mode("text")
            emit({"status":"Qwen 正在处理（离线模式）…"})
            for event in ollama_events(payload):
                content=event.get("message",{}).get("content","")
                if content:emit({"delta":content})
                if event.get("done"):
                    count=event.get("eval_count",0);duration=event.get("eval_duration",0)/1e9
                    emit({"done":True,"seconds":round(time.monotonic()-started,1),"load_seconds":round(event.get("load_duration",0)/1e9,1),"tokens_per_second":round(count/duration,1) if duration else 0,"truncated":event.get("done_reason")=="length"})
                    return
            raise RuntimeError("模型连接提前结束，请重试")
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            try:emit({"error":"已停止回答并释放模型" if STOPPING.is_set() else str(e),"cancelled":STOPPING.is_set()})
            except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path=='/api/identity':return self.send_json({'application':'jingliu-native-canvas','version':'0.2.0'})
        if path=='/api/asset-library':return self.send_json(asset_library.catalog())
        m=re.fullmatch(r'/asset-library-media/([^/]+)/([^/]+)',path)
        if m:
            try:return self.send_file(asset_library.media_file(m.group(1),m.group(2)))
            except (ValueError,FileNotFoundError):return self.send_error(404)
        if path=='/api/character-library':return self.send_json(character_library.catalog())
        m=re.fullmatch(r'/character-library-media/([^/]+)/([^/]+)',path)
        if m:
            try:return self.send_file(character_library.media_file(m.group(1),m.group(2)))
            except (ValueError,FileNotFoundError):return self.send_error(404)
        if path=='/api/canvas-assistant/models':return self.send_json(canvas_assistant.models(sys.modules[__name__]))
        m=re.fullmatch(r'/api/projects/([^/]+)/canvas-assistant',path)
        if m:
            try:return self.send_json(canvas_assistant.history(sys.modules[__name__],m.group(1)))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},404)
        if path=='/api/canvas-models':
            import canvas_models
            return self.send_json(canvas_models.catalog(sys.modules[__name__]))
        if path=='/api/musetalk':return self.send_json(musetalk_backend.status())
        m=re.fullmatch(r'/api/projects/([^/]+)/lip-sync/catalog',path)
        if m:
            try:return self.send_json(video_lipsync.catalog(load_project(m.group(1))))
            except (ValueError,FileNotFoundError):return self.send_json({'error':'项目不存在'},404)
        if path=='/api/text-model':return self.send_json(text_models.public())
        if path=="/api/capabilities":return self.send_json({"infinite_canvas":True,"canvas_video_tools":True,"character_library":True,"asset_library":True,"canvas_images":True,"canvas_image_edit":character_image_edit.status(director.CFG),"canvas_upscale":video_enhance.status(),"h3_translation":True,"h3_translation_model":director.CFG["ollama_model"] if text_models.load()["provider"]=="local" else text_models.load()["model"],"asset_plan":True,"character_sheet_revision":asset_views.PROMPT_REVISION,"character_state_modes":["text","image"],"character_image_edit":single_image_edit.status(director.CFG),"asset_image_delete":True,"asset_image_regions":True,"character_source_layouts":True,"video_choices":True,"video_color_match":True,"video_lipsync":True,"face_refine":face_refine.status(),"tail_repair":True,"tail_qwen_redraw":True,"opening_qwen_frames":True,"shot_chat":True,"shot_chat_parallel":True,"script_workspace":True})
        if path=='/api/video-backends':return self.send_json({'selected':load_settings()['video_backend'],'esrgan':video_enhance.status(),'h3c':{**h3_native.status(),'max_references':9,'generation_modes':list(video_modes.MODES)}})
        if path=="/api/status":
            try:resident=ollama_resident_models()
            except Exception:resident=None
            names=None if resident is None else [m.get('model') or m['name'] for m in resident]
            with LOCK:image_job=next((j for j in JOBS.values() if j.get('status')=='running' and j.get('image_model')), {})
            return self.send_json({"ollama":service_status(director.CFG["ollama_url"]+"/api/tags"),"ollama_loaded_models":names,
                "text_model":director.CFG['ollama_model'],"h3c_running":bool(h3_native.running_pids()),"h3c_resident":h3_native.h3_resident.state(),
                "qwen_image":service_status(director.CFG["qwen_image_url"]+"/system_stats"),"h3c":h3_native.status()["ready"],"vision_ready":ollama_model_available(VISION_MODEL),"vision_model":VISION_MODEL,"image_backend":director.CFG.get("image_backend","qwen_image"),"image_model":"Z-Image-Turbo" if director.CFG.get("image_backend")=="z_image" else "Qwen-Image","active_image_model":image_job.get('image_model')})
        if path=="/api/settings":return self.send_json(load_settings())
        if path=="/api/runtime":
            with LOCK:jobs=[dict(j) for j in JOBS.values() if j.get("status") in {"queued","running"}]
            return self.send_json({"stop":dict(STOP_STATE),"busy":MODEL_LOCK.locked(),"jobs":jobs})
        if path=="/api/projects":
            items=[]
            for f in PROJECTS.glob("*/project.json"):
                try:
                    p=json.loads(f.read_text());items.append({k:p.get(k) for k in ("id","title","brief","stage","updated_at")})
                except: pass
            return self.send_json(sorted(items,key=lambda x:x.get("updated_at", ""),reverse=True))
        m=re.fullmatch(r"/api/projects/([^/]+)",path)
        if m:
            try:return self.send_json(project_view(load_project(m.group(1))))
            except:return self.send_json({"error":"项目不存在"},404)
        m=re.fullmatch(r"/api/jobs/([^/]+)",path)
        if m:return self.send_json(JOBS.get(m.group(1),{"error":"任务不存在"}),200 if m.group(1) in JOBS else 404)
        if path.startswith("/media/"):
            rel=Path(path[7:]);target=(PROJECTS/rel).resolve()
            if not target.is_relative_to(PROJECTS.resolve()) or not target.is_file():return self.send_error(404)
            return self.send_file(target)
        target=(STATIC/("canvas.html" if path=="/" else path.lstrip("/"))).resolve()
        if target.is_relative_to(STATIC.resolve()) and target.is_file():return self.send_file(target)
        self.send_error(404)
    def send_file(self,path):
        size=path.stat().st_size;start=0;end=size-1;partial=self.headers.get('Range')
        if partial:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',partial)
            try:
                if not match or not any(match.groups()) or not size:raise ValueError()
                left,right=match.groups()
                if left:
                    start=int(left);end=min(int(right),size-1) if right else size-1
                else:
                    if int(right)<=0:raise ValueError()
                    start=max(0,size-int(right))
                if start>=size or end<start:raise ValueError()
            except ValueError:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
        if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as stream:
                stream.seek(start);remaining=end-start+1
                while remaining>0:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        path=unquote(urlparse(self.path).path)
        origin=self.headers.get("Origin")
        if origin and urlparse(origin).netloc!=self.headers.get("Host"):return self.send_json({"error":"不允许跨站操作"},403)
        image_match=re.fullmatch(r"/api/projects/([^/]+)/entities/([^/]+)/images/restore",path)
        if image_match:
            try:return self.send_json(asset_images.restore(sys.modules[__name__],*image_match.groups(),self.body().get('record_id')))
            except (FileNotFoundError,ValueError) as e:return self.send_json({'error':str(e)},409)
        choice_match=re.fullmatch(r"/api/projects/([^/]+)/videos/([^/]+)/choice",path)
        if choice_match:
            try:return self.send_json(video_choices.save_choice(sys.modules[__name__],*choice_match.groups(),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        video_match=re.fullmatch(r"/api/projects/([^/]+)/videos/([^/]+)/restore",path)
        if video_match:
            try:return self.send_json(restore_shot_video(*video_match.groups(),self.body().get("record_id")))
            except FileNotFoundError as e:return self.send_json({"error":str(e)},404)
            except ValueError as e:return self.send_json({"error":str(e)},409)
        if path=="/api/stop":return self.send_json(request_stop(),202)
        if path=='/api/text-model/test':
            if not MODEL_LOCK.acquire(blocking=False):return self.send_json({'error':'模型任务运行中，请稍后测试'},409)
            try:
                c=text_models.load()
                if c['provider']=='local':
                    if not service_status(director.CFG['ollama_url']+'/api/tags'):raise ValueError('本地Ollama服务未连接')
                else:text_models.request(c,[{'role':'user','content':'Return JSON with ok set to true.'}],{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']},sys.modules[__name__])
                return self.send_json({'message':'已保存的文字模型连接测试通过'})
            except Exception as e:return self.send_json({'error':str(e)},400)
            finally:MODEL_LOCK.release()
        if path=='/api/text-model':
            try:
                with LOCK:
                    if MODEL_LOCK.locked() or any(j.get('status') in ('queued','running') for j in JOBS.values()):raise ValueError('任务运行中，请完成或停止后切换文字模型')
                    return self.send_json(text_models.save(self.body()))
            except Exception as e:return self.send_json({'error':str(e)},400)
        if path=="/api/settings":
            try:
                data=self.body()
                with LOCK:
                    if MODEL_LOCK.locked() or STOPPING.is_set() or any(j.get('status') in ('queued','running') for j in JOBS.values()):
                        return self.send_json({'error':'任务运行中，参数草稿请在任务结束后保存；不会中断当前生成'},409)
                    return self.send_json(save_settings(data))
            except Exception as e:return self.send_json({"error":str(e)},400)
        if path=="/api/chat":
            if STOPPING.is_set():return self.send_json({"error":"正在释放模型，请稍后重试"},409)
            if not MODEL_LOCK.acquire(blocking=False):return self.send_json({"error":"当前有生成任务运行，完成后再开始聊天，避免模型同时占用内存。"},409)
            try:
                data=self.body()
                if data.get("stream"):return self.chat_stream(data)
                prepare_model_mode("text")
                return self.send_json({"message":qwen_chat(data.get("messages",[]))})
            except Exception as e:return self.send_json({"error":str(e)},400)
            finally:MODEL_LOCK.release()
        if path=="/api/projects":
            return self.send_json(create_project(self.body()),201)
        m=re.fullmatch(r"/api/projects/([^/]+)/creative/import",path)
        if m:
            try:return self.send_json(creative_chat.import_draft(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r"/api/projects/([^/]+)/script-workspace/(save|apply|export)",path)
        if m:
            try:
                handler={'save':script_workspace.save,'apply':script_workspace.apply,'export':script_workspace.export}[m.group(2)]
                return self.send_json(handler(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r'/api/projects/([^/]+)/asset-library/(save|import)',path)
        if m:
            try:return self.send_json((asset_library.save if m.group(2)=='save' else asset_library.import_asset)(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r'/api/projects/([^/]+)/character-library/(save|import)',path)
        if m:
            try:return self.send_json((character_library.save if m.group(2)=='save' else character_library.import_appearance)(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r"/api/projects/([^/]+)/canvas/(layout|edit|image|video|node)",path)
        if m:
            try:
                handler={'layout':canvas_workspace.save_layout,'edit':canvas_workspace.edit,'image':canvas_images.edit,'video':canvas_videos.edit,'node':canvas_nodes.edit}[m.group(2)]
                return self.send_json(handler(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError,TypeError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r"/api/projects/([^/]+)/custom-entity",path)
        if m:
            try:return self.send_json(project_view(add_custom_entity(m.group(1),self.body())))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},400)
        m=re.fullmatch(r"/api/projects/([^/]+)/action",path)
        if m:
            try:
                data=self.body();return self.send_json(start_job(m.group(1),data["action"],data),202)
            except (FileNotFoundError,ValueError) as e:return self.send_json({"error":str(e)},400)
        m=re.fullmatch(r'/api/projects/([^/]+)/lip-sync/review',path)
        if m:
            try:return self.send_json(video_lipsync.save_review(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r'/api/projects/([^/]+)/lip-sync/info',path)
        if m:
            try:return self.send_json(video_lipsync.media_info(sys.modules[__name__],load_project(m.group(1)),self.body()))
            except (ValueError,FileNotFoundError,subprocess.SubprocessError) as e:return self.send_json({'error':str(e)},400)
        m=re.fullmatch(r"/api/projects/([^/]+)/tail-repair/(settings|approve)",path)
        if m:
            try:
                handler=tail_repair.save_defaults if m.group(2)=='settings' else tail_repair.approve
                return self.send_json(handler(sys.modules[__name__],m.group(1),self.body()))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},409)
        m=re.fullmatch(r"/api/projects/([^/]+)/save",path)
        if m:
            try:
                with PROJECT_LOCK:
                    ensure_project_editable(m.group(1));p=load_project(m.group(1));data=self.body()
                    project_view(p)
                    if 'shots' in data:data['shots']=shot_elements.merge_edits(p,data['shots'])
                    old_shots={s.get("id"):dict(s) for s in p.get("shots",[])}
                    for k in ("title","brief","analysis","script","shots","uploads"):
                        if k in data:p[k]=data[k]
                    if 'analysis' in data or 'script' in data:sync_shot_elements(p)
                    if "shots" in data:
                        project_audio.validate_timeline(p)
                        video_timing.update_timelines(p,old_shots)
                        for shot in p["shots"]:
                            old=old_shots.get(shot.get("id"),{})
                            video_workflow.references(sys.modules[__name__],p,shot)
                            if video_timing.shot_duration(old)!=shot['duration'] or any(old.get(k)!=shot.get(k) for k in ("description","motion_prompt","camera","dialogue","element_ids","character_actions","inherit_previous","use_element_references","manual_reference_images","reference_angle_mode","excluded_reference_images","character_states","audio_segment")) or video_modes.configuration(old)!=video_modes.configuration(shot):
                                video_workflow.invalidate(sys.modules[__name__],p,shot,'上游镜头内容或参考图已修改')
                                video_choices.archive(shot)
                                for key in ("video","source_video","review","continuity_source_shot","continuity_source_video"):shot.pop(key,None)
                                shot["status"]="planned";p.pop("final_video",None);p.pop("final_review",None)
                    save_project(p);return self.send_json(project_view(p))
            except (ValueError,FileNotFoundError) as e:return self.send_json({"error":str(e)},409)
        m=re.fullmatch(r"/api/projects/([^/]+)/entities/([^/]+)/sheet-layout",path)
        if m:
            try:return self.send_json(project_view(character_sheet_layout.revise(sys.modules[__name__],m.group(1),m.group(2),self.body())))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},400)
        m=re.fullmatch(r"/api/projects/([^/]+)/entities/([^/]+)/reuse-source",path)
        if m:
            try:return self.send_json(project_view(character_sheet_layout.reuse_source(sys.modules[__name__],m.group(1),m.group(2),self.body())))
            except (ValueError,FileNotFoundError) as e:return self.send_json({'error':str(e)},400)
        m=re.fullmatch(r"/api/projects/([^/]+)/entities/([^/]+)",path)
        if m:
            try:return self.send_json(project_view(edit_entity(m.group(1),m.group(2),self.body())))
            except (ValueError,FileNotFoundError) as e:return self.send_json({"error":str(e)},400)
        m=re.fullmatch(r"/api/projects/([^/]+)/reveal",path)
        if m:
            try:
                target=project_path(m.group(1),str(self.body().get("path","")))
                if not target.exists():raise ValueError("文件尚未生成")
                subprocess.run(["/usr/bin/open",*(["-R"] if target.is_file() else []),str(target)],check=True)
                return self.send_json({"path":str(target)})
            except Exception as e:return self.send_json({"error":str(e)},400)
        m=re.fullmatch(r"/api/projects/([^/]+)/upload",path)
        if m:return self.handle_upload(m.group(1))
        m=re.fullmatch(r"/api/projects/([^/]+)/upload-media",path)
        if m:return self.handle_media_upload(m.group(1))
        self.send_error(404)
    def handle_media_upload(self,pid):
        target=None;saved=False
        try:
            ensure_project_editable(pid);load_project(pid)
            if int(self.headers.get('Content-Length','0'))>152*1024*1024:
                raise ValueError('参考视频或音频不能超过 150MB')
            upload_temp=project_path(pid,'temp/uploads');upload_temp.mkdir(parents=True,exist_ok=True)
            class ProjectMediaUpload(cgi.FieldStorage):
                def make_file(self):
                    return tempfile.TemporaryFile(mode='wb+' if self._binary_file else 'w+',dir=upload_temp)
                def __exit__(self,*args):
                    for field in [self,*(self.list or [])]:
                        if field.file is not None:field.file.close()
            with ProjectMediaUpload(fp=self.rfile,headers=self.headers,environ={'REQUEST_METHOD':'POST','CONTENT_TYPE':self.headers.get('Content-Type')}) as form:
                kind=form.getvalue('kind')
                if kind not in {'silent_video','video','audio'}:raise ValueError('请选择视频或音频参考类型')
                item=form['file'];name=Path(item.filename or 'media').name;suffix=Path(name).suffix.lower()
                allowed=video_modes.AUDIO_EXTENSIONS if kind=='audio' else video_modes.VIDEO_EXTENSIONS
                if suffix not in allowed:raise ValueError('参考媒体格式不支持')
                uploads=project_dir(pid)/'uploads';uploads.mkdir(exist_ok=True)
                target=uploads/(uuid.uuid4().hex+suffix);total=0
                with target.open('wb') as stream:
                    while True:
                        chunk=item.file.read(1024*1024)
                        if not chunk:break
                        total+=len(chunk)
                        if total>150*1024*1024:raise ValueError('参考视频或音频不能超过 150MB')
                        stream.write(chunk)
                metadata=canvas_videos.upload_info(target,kind,h3_native.FFPROBE) if form.getvalue('scope')=='canvas' else video_modes.probe(target,kind,h3_native.FFPROBE)
                entry={'id':uuid.uuid4().hex[:8],'name':name,'entity_id':'','path':str(target.relative_to(project_dir(pid))),
                       'kind':kind,**metadata,'created_at':now()}
                with PROJECT_LOCK:
                    ensure_project_editable(pid);p=load_project(pid)
                    p.setdefault('uploads',[]).append(entry);save_project(p);saved=True
                self.send_json(entry,201)
        except (ValueError,KeyError,FileNotFoundError) as error:
            self.send_json({'error':str(error)},400)
        finally:
            if target is not None and not saved:target.unlink(missing_ok=True)

    def handle_upload(self,pid):
        try:
            ensure_project_editable(pid);load_project(pid)
            upload_temp=project_path(pid,'temp/uploads');upload_temp.mkdir(parents=True,exist_ok=True)
        except (ValueError,FileNotFoundError) as e:return self.send_json({"error":str(e)},409)
        if int(self.headers.get("Content-Length","0"))>32*1024*1024:return self.send_json({"error":"图片不能超过 32MB"},400)
        class ProjectUpload(cgi.FieldStorage):
            def make_file(self):
                return tempfile.TemporaryFile(mode='wb+' if self._binary_file else 'w+',dir=upload_temp)
        form=ProjectUpload(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("Content-Type")})
        try:
            with PROJECT_LOCK:
                ensure_project_editable(pid);p=load_project(pid)
                eid=form.getvalue("entity_id") or ""
                if eid:entity_from_project(p,eid)
                role=form.getvalue('asset_role') or 'input'
                if role not in {'input','result'} or (role=='result' and not eid):raise ValueError('图片目标区域不正确')
                asset=asset_record(p,eid) if eid else None
                sid=form.getvalue('shot_id') or ''
                if eid and sid:raise ValueError('元素原图和镜头补充图需分别上传')
                shot=find_shot(p,sid) if sid else None
                item=form["file"];name=Path(item.filename or "reference.png").name;content=item.file.read()
                import imghdr
                kind=imghdr.what(None,content)
                if kind not in {"png","jpeg","webp"}:raise ValueError("请上传有效的 PNG、JPG 或 WEBP 图片")
                uploads=project_dir(pid)/"uploads";uploads.mkdir(exist_ok=True)
                target=uploads/(uuid.uuid4().hex+{"png":".png","jpeg":".jpg","webp":".webp"}[kind]);target.write_bytes(content)
                entry={"id":uuid.uuid4().hex[:8],"name":form.getvalue("name") or name,"entity_id":eid,"path":str(target.relative_to(project_dir(pid))),"created_at":now()}
                if eid:entry['usage']='element_result' if role=='result' else 'image_edit_source'
                p.setdefault("uploads",[]).append(entry)
                if shot is not None:
                    shot.setdefault('manual_reference_images',[]).append(entry['path'])
                    if shot.get('video'):shot.update(video_stale=True,stale_reason='参考图已修改')
                    video_workflow.invalidate(sys.modules[__name__],p,shot,'上游参考图已修改')
                if eid:
                    asset=asset_record(p,eid)
                    if role=='result':
                        entry['usage']='element_result'
                        version={'id':datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6],
                                 'created_at':now(),'images':[entry['path']],'status':'done','mode':'import','origin':'external_image','name':entry['name'],'view_count':1}
                        asset['versions'].append(version);asset['images']=version['images']
                    else:
                        if entry['path'] not in asset['source_images']:asset['source_images'].append(entry['path'])
                        asset['source_image']='';asset['reference_mode']='image';entry['usage']='image_edit_source'
                save_project(p);self.send_json(entry,201)
        except (ValueError,KeyError,FileNotFoundError) as e:self.send_json({"error":str(e)},400)


def cleanup_models():
    musetalk_backend.stop_all()
    h3_native.stop_all()
    # 工作台退出时释放所有模型占用的内存：只卸载 /api/ps 里已在运行的模型，不会新加载任何模型
    try:
        for m in json_request(director.CFG["ollama_url"]+"/api/ps",timeout=5).get("models",[]):
            try:json_request(director.CFG["ollama_url"]+"/api/generate",{"model":m.get("model") or m.get("name"),"keep_alive":0},timeout=30)
            except Exception:pass
    except Exception:pass
    for url in (director.CFG["qwen_image_url"],):
        try:json_request(url+"/free",{"unload_models":True,"free_memory":True},timeout=15)
        except Exception:pass


def main():
    import fcntl
    instance=(DATA/'instance.lock').open('a')
    try:fcntl.flock(instance,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('这个数据目录已有运行中的镜流画布')
    ffmpeg=verify_video_processing()
    print(f'Python 环境：{sys.prefix}\n视频处理组件已验证：{ffmpeg}',flush=True)
    port=int(os.environ.get("STUDIO_PORT","18772"));server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    from sample_canvas import install_sample
    install_sample(sys.modules[__name__])
    def shutdown(signum,frame):
        try:
            musetalk_backend.stop_all();h3_native.stop_all()
            for child in list(COMFY_PROCESSES.values()):
                if child.poll() is None:child.terminate()
        except Exception:pass
        os._exit(0)
    # 关闭工作台（Ctrl-C、关闭终端窗口、kill）时自动卸载全部模型，把内存还给系统
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,shutdown)
    print(f"AI 影视工作台：http://127.0.0.1:{port}",flush=True);server.serve_forever()

if __name__=="__main__":main()
