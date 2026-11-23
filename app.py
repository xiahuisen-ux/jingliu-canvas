"""镜流轻量版 — Python 3.9+ 标准库本地服务。"""
import argparse
import contextlib
import fcntl
import json
import math
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from engines import BASE, comfy_url, prepare_comfy, h3_check, run_comfy, run_video

STORE = Path(os.environ.get('JINGLIU_DATA', Path.home()/'Library/Application Support/Jingliu Canvas'))
WEB = BASE/'web'
LOCK = threading.RLock()
BUSY = threading.Lock()
DEFAULTS = {'comfy':'http://127.0.0.1:8188','models':'','binary':''}
DEMO = {'boat.jpg','coast.jpg','sun.jpg','sail.mp4','cover.jpg'}
ID = re.compile(r'[a-zA-Z0-9_-]{1,80}')
MEDIA = re.compile(r'/media/[a-f0-9]{32}\.(png|jpg|webp|mp4)')


def load(name, fallback):
    f = STORE/name
    return json.loads(f.read_text()) if f.is_file() else fallback


def write(name, obj):
    dest = STORE/name
    tmp = dest.with_name(dest.name+'.'+secrets.token_hex(5)+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')
    os.replace(tmp,dest)


def media_path(url):
    if url.startswith('/demo/') and url[6:] in DEMO:
        return WEB/url[1:]
    if MEDIA.fullmatch(url):
        return STORE/url[1:]
    raise ValueError('素材路径无效')


def valid_project(v):
    nodes, edges = v['nodes'], v['edges']
    if not isinstance(nodes,list) or not isinstance(edges,list) or len(nodes)>300 or len(edges)>900:
        raise ValueError('画布最多容纳 300 个节点')
    by_id = {}
    for n in nodes:
        key = n['id']
        if not ID.fullmatch(key) or key in by_id or n['kind'] not in ('ref','image','edit','video'):
            raise ValueError('节点无效')
        if not all(isinstance(n[t],str) and len(n[t])<=limit for t,limit in [('name',120),('prompt',4000),('src',150)]):
            raise ValueError('节点内容无效')
        if n['src'] and not media_path(n['src']).is_file():
            raise ValueError('素材不存在')
        if not all(isinstance(n[t],(int,float)) and math.isfinite(n[t]) and abs(n[t])<=1e6 for t in ('x','y')):
            raise ValueError('位置无效')
        by_id[key] = n
    for pair in edges:
        a,b = pair
        if a not in by_id or b not in by_id or a==b or by_id[a]['kind']=='video' or by_id[b]['kind'] not in ('edit','video'):
            raise ValueError('连线无效')
    if len(set(tuple(edge) for edge in edges)) != len(edges) or any(sum(1 for _,b in edges if b==k)>3 for k in by_id):
        raise ValueError('每个节点最多接入三张不同的参考图')
    return {'nodes':nodes,'edges':edges}


class Conflict(Exception):
    pass


def project():
    return load('project.json',json.loads((WEB/'example.json').read_text()))


def inspect_mode(mode,cfg):
    if mode=='video':
        return h3_check(cfg)
    if mode not in ('image','edit'):
        raise ValueError('未知模型')
    try:
        return prepare_comfy(comfy_url(cfg['comfy']),mode)[1]
    except OSError:
        return ['未连接到本机 ComfyUI，请先启动服务并检查端口']


def submit(data):
    mode=data['mode']
    if mode not in ('image','edit','video'):raise ValueError('未知任务')
    refs=[media_path(x) for x in data['refs']]
    if len(refs)>3 or any(not x.is_file() or x.suffix=='.mp4' for x in refs):
        raise ValueError('请选择最多三张图片')
    if mode!='image' and not refs:raise ValueError('请先从图片的输出口接入参考图')
    prompt=data['prompt'].strip()
    if not prompt or len(prompt)>4000:raise ValueError('请输入 1 至 4000 字的提示词')
    cfg=load('settings.json',DEFAULTS)
    missing=inspect_mode(mode,cfg)
    if missing:raise ValueError('请先配置：'+'、'.join(missing))
    if not BUSY.acquire(blocking=False):raise ValueError('本机已有生成任务在执行')
    key=secrets.token_hex(16)
    dst=STORE/'media'/(key+('.mp4' if mode=='video' else '.png'))
    def report(msg,state='running',url=''):
        with LOCK:write('jobs/'+key+'.json',{'state':state,'message':msg,'url':url})
    def work():
        try:
            if mode=='video':run_video(cfg,prompt,refs,dst,report)
            else:run_comfy(cfg,mode,prompt,refs,dst,report)
            report('生成完成','done','/media/'+dst.name)
        except Exception as exc:report(str(exc),'error')
        finally:BUSY.release()
    try:
        report('准备生成')
        threading.Thread(target=work,daemon=True).start()
    except Exception:
        BUSY.release();raise
    return {'id':key}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def respond(self,status,data,kind='application/json; charset=utf-8'):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        with contextlib.suppress(BrokenPipeError,ConnectionResetError):self.wfile.write(body)
    def allowed(self):
        return self.headers.get('Host') in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port))
    def do_GET(self):
        if not self.allowed():return self.respond(403,{'error':'仅限本机访问'})
        path=unquote(urlsplit(self.path).path)
        try:
            if path=='/api/identity':return self.respond(200,{'app':'jingliu-canvas-v1'})
            if path=='/api/project':
                with LOCK:return self.respond(200,project())
            if path=='/api/settings':return self.respond(200,load('settings.json',DEFAULTS))
            if re.fullmatch(r'/api/job/[0-9a-f]{32}',path):
                job=load('jobs/'+path.rsplit('/',1)[1]+'.json',None)
                return self.respond(200 if job else 404,job or {'error':'任务不存在'})
            f=media_path(path) if path.startswith('/media/') else (WEB/(path[1:] or 'index.html')).resolve()
            if not (f.is_relative_to(WEB) or f.is_relative_to(STORE/'media')) or not f.is_file():
                return self.respond(404,{'error':'文件不存在'})
            return self.respond(200,f.read_bytes(),mimetypes.guess_type(str(f))[0] or 'application/octet-stream')
        except (OSError,ValueError) as exc:return self.respond(400,{'error':str(exc)})
    def do_POST(self):
        if not self.allowed() or self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
            return self.respond(403,{'error':'请从本地画布操作'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=16*1024*1024:raise ValueError('单个文件上限 16 MB')
            blob=self.rfile.read(size)
            if self.path=='/api/import':
                ext='png' if blob.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if blob.startswith(b'\xff\xd8\xff') else 'webp' if blob[:4]==b'RIFF' and blob[8:12]==b'WEBP' else None
                if not ext:raise ValueError('请选择 PNG、JPEG 或 WebP 图片')
                f=STORE/'media'/(secrets.token_hex(16)+'.'+ext);f.write_bytes(blob)
                return self.respond(200,{'url':'/media/'+f.name})
            data=json.loads(blob)
            if self.path=='/api/project':
                with LOCK:
                    old=project()
                    if data['rev']!=old['rev']:raise Conflict('另一个窗口已保存，请刷新后再编辑')
                    v=valid_project(data);v['rev']=old['rev']+1;write('project.json',v)
                    return self.respond(200,{'rev':v['rev']})
            if self.path=='/api/settings':
                with LOCK:
                    cfg=load('settings.json',DEFAULTS);cfg['comfy']=comfy_url(data['comfy']);write('settings.json',cfg)
                return self.respond(200,cfg)
            if self.path=='/api/pick':
                key=data['key']
                expr={'models':'POSIX path of (choose folder with prompt "选择包含 Ref2VA 的模型根目录")',
                      'binary':'POSIX path of (choose file with prompt "选择已编译的 h3 可执行文件")'}[key]
                r=subprocess.run(['/usr/bin/osascript','-e',expr],capture_output=True,text=True)
                with LOCK:
                    cfg=load('settings.json',DEFAULTS)
                    if r.returncode==0:
                        value=Path(r.stdout.strip())
                        if key=='binary' and value.name!='h3':raise ValueError('请选择名为 h3 的程序')
                        cfg[key]=str(value);write('settings.json',cfg)
                return self.respond(200,cfg)
            if self.path=='/api/check':return self.respond(200,{'missing':inspect_mode(data['mode'],load('settings.json',DEFAULTS))})
            if self.path=='/api/generate':return self.respond(202,submit(data))
            return self.respond(404,{'error':'接口不存在'})
        except Conflict as exc:return self.respond(409,{'error':str(exc)})
        except (KeyError,ValueError,TypeError,OSError) as exc:return self.respond(400,{'error':str(exc)})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18771);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    for name in ('media','jobs'): (STORE/name).mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    instance=(STORE/'instance.lock').open('a')
    try:fcntl.flock(instance,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('这个数据目录的画布已经打开')
    for file in (STORE/'jobs').glob('*.json'):
        v=load('jobs/'+file.name,{})
        if v.get('state')=='running':write('jobs/'+file.name,{'state':'error','message':'上次服务已退出，请查看模型工具的任务记录再决定是否重试','url':''})
    url='http://127.0.0.1:'+str(server.server_port)
    print('镜流无限画布  '+url,flush=True)
    if not args.no_browser:webbrowser.open(url)
    server.serve_forever()

if __name__=='__main__':main()
