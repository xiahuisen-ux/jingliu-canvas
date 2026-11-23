"""Local model adapters. Importing this module never loads or installs models."""
import copy
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from urllib import parse, request, error

BASE = Path(__file__).resolve().parent
ENGINES = {'image': 'z-image.json', 'edit': 'qwen-edit.json'}
FIELDS = {'UNETLoader': 'unet_name', 'UnetLoaderGGUF': 'unet_name', 'CLIPLoader': 'clip_name',
          'VAELoader': 'vae_name', 'LoraLoaderModelOnly': 'lora_name'}


def comfy_url(raw):
    u = parse.urlsplit(raw.strip())
    if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1') or
            u.username or u.password or u.query or u.fragment or u.path not in ('', '/')):
        raise ValueError('请输入本机 ComfyUI 的 HTTP 地址，例如 http://127.0.0.1:8188')
    port = u.port or 80
    return f'http://[{u.hostname}]:{port}' if ':' in u.hostname else f'http://{u.hostname}:{port}'


def fetch(url, data=None, content_type='application/json', timeout=12):
    req = request.Request(url, data=data, headers={'Content-Type': content_type})
    with request.urlopen(req, timeout=timeout) as response:
        return response.read()


def workflow(mode):
    return json.loads((BASE / 'workflows' / ENGINES[mode]).read_text())


def installed_name(options, name):
    # ComfyUI can report a model in a subdirectory using either path separator.
    return next((v for v in options if isinstance(v, str) and
                 v.replace(chr(92), '/').split('/')[-1].lower() == name.lower()), None)


def prepare_comfy(url, mode):
    graph = workflow(mode)
    info = json.loads(fetch(url + '/object_info', timeout=8))
    missing = []
    for node in graph.values():
        cls = node['class_type']
        if cls not in info:
            missing.append(cls)
            continue
        field = FIELDS.get(cls)
        if field:
            spec = info[cls]['input']['required'][field]
            opts = spec[0] if isinstance(spec[0], list) else (spec[1].get('options', []) if len(spec)>1 else [])
            name = installed_name(opts, node['inputs'][field])
            if name:
                node['inputs'][field] = name
            else:
                missing.append(node['inputs'][field])
    return graph, sorted(set(missing))


def h3_check(cfg):
    root = Path(cfg.get('models') or '.') / 'Ref2VA'
    missing = []
    binary = Path(cfg.get('binary') or '.')
    if binary.name != 'h3' or not binary.is_file() or not os.access(binary, os.X_OK):
        missing.append('h3.c 可执行文件 h3')
    for exe in ('ffmpeg', 'ffprobe'):
        if not shutil.which(exe):
            missing.append(exe)
    for rel in ('tokenizer/tokenizer.json','video_vae/source/model.safetensors',
                'audio_vae/model.safetensors','processor/preprocessor_config.json'):
        if not (root / rel).is_file():
            missing.append('Ref2VA/' + rel)
    for part in ('transformer', 'text_encoder'):
        try:
            directory = root / part
            index = json.loads((directory / 'model.safetensors.index.json').read_text())
            names = set(index['weight_map'].values())
            if not names or not all((directory / n).is_file() for n in names):
                raise ValueError('分片不完整')
        except (OSError, KeyError, ValueError, TypeError):
            missing.append(f'Ref2VA/{part} 权重与索引')
    return missing


def upload(url, path):
    boundary = 'jingliu' + secrets.token_hex(12)
    filename = secrets.token_hex(10) + path.suffix
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode()
    body = header + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    obj = json.loads(fetch(url+'/upload/image', body, 'multipart/form-data; boundary='+boundary))
    return '/'.join(filter(None, (obj.get('subfolder'), obj['name'])))


def run_comfy(cfg, mode, prompt, refs, dest, notify):
    url = comfy_url(cfg['comfy'])
    graph, missing = prepare_comfy(url, mode)
    if missing:
        raise ValueError('缺少 ' + '、'.join(missing))
    graph['6']['inputs']['text' if mode == 'image' else 'prompt'] = prompt
    graph['9']['inputs']['seed'] = secrets.randbits(31)
    if mode == 'edit':
        if not 1 <= len(refs) <= 3:
            raise ValueError('重绘需要 1 至 3 张参考图')
        for i in range(3):
            key = str(12+i)
            if i < len(refs):
                graph[key]['inputs']['image'] = upload(url, refs[i])
            else:
                del graph[key]
                for encoder in ('6','7'):
                    graph[encoder]['inputs'].pop('image'+str(i+1), None)
    payload = json.dumps({'prompt':graph,'client_id':secrets.token_hex(16)}).encode()
    pid = json.loads(fetch(url+'/prompt', payload))['prompt_id']
    notify('ComfyUI 已接收，正在生成')
    for _ in range(5400):
        history = json.loads(fetch(url+'/history/'+parse.quote(pid))).get(pid, {})
        if history.get('status',{}).get('status_str') == 'error':
            raise RuntimeError('ComfyUI 运行失败，请查看其任务记录')
        imgs = history.get('outputs',{}).get('11',{}).get('images',[])
        if imgs:
            args = {k:imgs[0][k] for k in ('filename','subfolder','type')}
            blob = fetch(url+'/view?'+parse.urlencode(args))
            if not blob.startswith(b'\x89PNG'):
                raise ValueError('预期得到 PNG，请检查 SaveImage 节点')
            dest.write_bytes(blob)
            return
        time.sleep(2)
    raise TimeoutError('等待 ComfyUI 超时，请检查其队列')


def run_video(cfg, prompt, refs, dest, notify):
    missing = h3_check(cfg)
    if missing:
        raise ValueError('缺少 ' + '、'.join(missing))
    if not 1 <= len(refs) <= 3:
        raise ValueError('请连接 1 至 3 张参考图')
    command = [cfg['binary'],'-d',cfg['models'],'-p',prompt,'--width','512','--height','288',
               '--seconds','5','--steps','8','-o',str(dest)]
    for ref in refs:
        command.extend(['--ref-image',str(ref)])
    notify('h3.c 正在本机生成，耗时取决于硬件')
    log = dest.with_suffix('.log')
    with log.open('w') as f:
        proc = subprocess.run(command,stdout=f,stderr=f,env={**os.environ,
            'H3_FFMPEG':shutil.which('ffmpeg'),'H3_FFPROBE':shutil.which('ffprobe')})
    if proc.returncode or not dest.is_file() or not dest.stat().st_size:
        raise RuntimeError('h3.c 未能导出视频，运行日志见 '+str(log))
