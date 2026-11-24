"""Run inside MuseTalk's deployment directory after installing its sources and weights."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parent
cfg=json.loads((root/'runtime.example.json').read_text())
for k in ('python','runner','source','checkpoint','unet_config','vae','whisper','face_parse','resnet'):
    cfg[k]=str(root/cfg[k])
cfg['ffmpeg']=shutil.which('ffmpeg') or subprocess.check_output(
    [cfg['python'],'-c','import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())'],text=True).strip()
expected={item['destination']:item.get('expected_sha256') or item.get('expected_sha256_prefix') for item in json.loads((root/'downloads.json').read_text())}
expected['source/models/face-parse-bisent/79999_iter.pth']='468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567'
for item in cfg['weight_files']:
    rel=item['path'];f=root/rel
    if not f.is_file() or f.stat().st_size!=item['size']:raise SystemExit('模型缺失或大小不符：'+str(f))
    if expected.get(rel):
        with f.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if not digest.startswith(expected[rel]):raise SystemExit('模型校验失败：'+str(f))
    item['path']=str(f)
subprocess.run([cfg['python'],cfg['runner'],'--check'],cwd=cfg['source'],check=True)
subprocess.run([cfg['ffmpeg'],'-version'],stdout=subprocess.DEVNULL,check=True)
cfg.update(weights_verified=True,environment_checked=True)
with tempfile.NamedTemporaryFile('w',dir=root,delete=False) as f:
    json.dump(cfg,f,ensure_ascii=False,indent=2)
Path(f.name).replace(root/'runtime.json')
print('MuseTalk 环境和权重检查通过。')
