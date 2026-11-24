"""Project-owned files and recoverable deletion; never touch shared model weights."""
import json
from pathlib import Path
import shutil
import os
import uuid

FOLDERS = {
    'assets': '生成的元素参考图（保留各版本）',
    'uploads': '上传的外部参考照片',
    'videos': '原始视频与生成日志',
    'frames': '从视频提取的实际尾帧',
    'enhanced': '增强后视频',
    'final': '最终合片',
    'reviews': '质检文件',
    'temp': '本工程临时文件与图片服务缓存',
    'logs': '本工程模型服务日志',
    '回收站': '本工程已删除视频及整工程恢复包',
}


def initialize(root, title=''):
    root=Path(root)
    for name in FOLDERS:
        target=root/name
        if target.is_symlink():raise ValueError('工程子目录不能是符号链接：'+name)
        target.mkdir(parents=True,exist_ok=True)
    guide=root/'工程目录说明.txt'
    if not guide.exists():
        guide.write_text('工程：'+title+'\nproject.json：剧本、镜头与素材索引，请勿单独删除。\n'+
                         '\n'.join(f'{k}/：{v}' for k,v in FOLDERS.items())+
                         '\n删除整个项目后，恢复包位于本工程回收站/工程-编号/。\n'+
                         '恢复时，关闭工作台，将恢复包内文件移回本工程根目录，不要覆盖已有文件。\n',encoding='utf-8')


def recycle_project(root):
    root=Path(root)
    if not (root/'project.json').is_file():raise FileNotFoundError('项目不存在')
    trash=root/'回收站'
    if trash.is_symlink():raise ValueError('回收站不能是符号链接')
    trash.mkdir(exist_ok=True)
    target=trash/('工程-'+uuid.uuid4().hex[:12]);target.mkdir()
    # Move the manifest last; rollback on failure. Existing per-video trash stays local.
    items=sorted((p for p in root.iterdir() if p!=trash),key=lambda p:p.name=='project.json')
    moved=[]
    try:
        for item in items:
            item.rename(target/item.name);moved.append(item.name)
    except Exception:
        for name in reversed(moved):(target/name).rename(root/name)
        target.rmdir()
        raise
    return target


def recycle_video(st,pid,record):
    folder=st.project_path(pid,'回收站/videos/'+record['id'])
    folder.mkdir(parents=True,exist_ok=True)
    files={}
    # Retain old paths used by histories; hard links keep a local recovery copy
    # without duplicating video bytes on the same volume.
    for key in ('video','source_video'):
        relative=record['result'].get(key)
        if not relative:continue
        source=st.project_path(pid,relative)
        if source.is_file():
            target=folder/(key+source.suffix)
            try:os.link(source,target)
            except OSError:shutil.copy2(source,target)
            files[key]=str(target.relative_to(st.project_dir(pid).resolve()))
    record['recovery_files']=files
    (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return folder
