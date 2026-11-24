"""Standalone CPU tracking / MPS compositing using pinned H3 FaceRefine nodes.

This never loads a diffusion model. The workbench calls h3-worker separately.
Only the two upstream image/transform nodes are used; their small Comfy services
are supplied here so no second ComfyUI server or video backend is started.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import types

os.environ['YOLO_AUTOINSTALL']='false'
os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD']='1'
import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parent
torch.set_num_threads(4)

def progress(stage,**details):
    print('@face-refine@'+json.dumps({'stage':stage,**details},ensure_ascii=False),flush=True)

def load_nodes():
    comfy=types.ModuleType('comfy');comfy.__path__=[]
    nested=types.ModuleType('comfy.nested_tensor')
    mm=types.ModuleType('comfy.model_management')
    mm.throw_exception_if_processing_interrupted=lambda:None
    mm.get_torch_device=lambda:torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    comfy.nested_tensor=nested;comfy.model_management=mm
    sys.modules.update({'comfy':comfy,'comfy.nested_tensor':nested,'comfy.model_management':mm})
    folders=types.ModuleType('folder_paths');folders.models_dir=str(ROOT/'models')
    folders.get_filename_list=lambda key:['face_yolov8n.pt']
    folders.get_full_path=lambda key,name:str(ROOT/'models'/name) if name=='face_yolov8n.pt' else None
    sys.modules['folder_paths']=folders
    spec=importlib.util.spec_from_file_location('h3_face_upstream',ROOT/'upstream/nodes.py')
    nodes=importlib.util.module_from_spec(spec);spec.loader.exec_module(nodes)
    return nodes

def read_video(path):
    cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS);frames=[]
    try:
        if abs(fps-24)>0.05:raise ValueError('面部精修仅接受工作台24fps原片')
        while True:
            ok,bgr=cap.read()
            if not ok:break
            frames.append(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
            if len(frames)>362:raise ValueError('面部精修单段不能超过15秒')
    finally:cap.release()
    if len(frames)<5:raise ValueError('视频帧数不足或解码失败')
    return torch.from_numpy(np.stack(frames)).float()/255

def write_video(images,path,ffmpeg,*,source_audio=None,pad=False):
    images=images.detach().cpu();count,h,w,_=images.shape
    command=[ffmpeg,'-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}',
             '-r','24','-i','pipe:0']
    if source_audio:
        command+=['-i',str(source_audio),'-map','0:v:0','-map','1:a:0?','-c:v','libx264',
                  '-preset','fast','-crf','16','-pix_fmt','yuv420p','-c:a','copy','-t',str(count/24)]
    else:command+=['-an','-c:v','ffv1','-level','3']
    command+=[str(path)]
    child=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        total=count
        if pad:
            while total%17!=5:total+=1
        for i in range(total):
            frame=(images[min(i,count-1)].clamp(0,1)*255).round().byte().numpy()
            child.stdin.write(frame.tobytes())
        child.stdin.close();error=child.stderr.read().decode(errors='replace')
        if child.wait()!=0:raise RuntimeError('视频编码失败：'+error[-1000:])
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=5)
        child.stderr.close()
    return total

def descriptor(image):
    rgb=(image.detach().cpu().clamp(0,1)*255).byte().numpy() if isinstance(image,torch.Tensor) else image
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    hist=cv2.calcHist([hsv],[0,1],None,[12,4],[0,180,0,256]).ravel()
    hist=np.sqrt(hist/max(hist.sum(),1));return hist/(np.linalg.norm(hist)+1e-8)

def reference_descriptor(path,model):
    bgr=cv2.imread(str(path))
    if bgr is None:raise ValueError('头部参考图无法读取：'+str(path))
    found=model.predict(bgr,conf=.25,verbose=False,device='cpu')[0]
    if len(found.boxes):
        boxes=found.boxes.xyxy.tolist();x,y,r,b=max(boxes,key=lambda q:(q[2]-q[0])*(q[3]-q[1]))
        bgr=bgr[max(0,int(y)):int(b),max(0,int(x)):int(r)]
    else:
        h,w=bgr.shape[:2];bgr=bgr[h//5:4*h//5,w//5:4*w//5]
    return descriptor(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))

def prepare(request,nodes):
    images=read_video(request['source']);frames,h,w,_=images.shape
    out=Path(request['directory']);out.mkdir(parents=True,exist_ok=True)
    model=nodes._load_detector('face_yolov8n.pt');model.overrides['device']='cpu'
    all_boxes=[];all_confs=[]
    for i,frame in enumerate(images):
        bgr=cv2.cvtColor((frame.numpy()*255).astype(np.uint8),cv2.COLOR_RGB2BGR)
        detected=model.predict(bgr,conf=.25,verbose=False,device='cpu')[0]
        boxes=detected.boxes.xyxy.tolist() if len(detected.boxes) else []
        confs=detected.boxes.conf.tolist() if len(detected.boxes) else []
        valid=[(q,c) for q,c in zip(boxes,confs) if q[3]-q[1]>=18]
        all_boxes.append([q for q,c in valid]);all_confs.append([c for q,c in valid])
        if i%12==0:progress('追踪面部',completed=i,total=frames)
    if not any(all_boxes):
        result={'tracks':[],'warnings':['未检测到可精修人脸，原视频保留。卡通脸可能需要手动指定区域。']}
        (out/'prepared.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return
    # Lock subjects on the frame with the most eligible faces. Background faces
    # never become targets without a plausible match to a selected character.
    anchor=max(range(frames),key=lambda i:len(all_boxes[i]))
    profiles=request['characters'];features=[]
    for profile in profiles:features.append(reference_descriptor(profile['references']['front'],model))
    tracks=[];warnings=[];used=set()
    for candidate,box in enumerate(all_boxes[anchor]):
        x,y,r,b=map(int,box);feature=descriptor(images[anchor,y:b,x:r])
        scores=sorted([(float(np.dot(feature,f)),j) for j,f in enumerate(features)],reverse=True)
        if not scores:continue
        best,j=scores[0];gap=best-(scores[1][0] if len(scores)>1 else 0)
        if best<.6 or gap<.035 or j in used:
            warnings.append(f'第{candidate+1}个人脸参考匹配不确定，保留原片');continue
        profile=profiles[j]
        pick={'frames':frames,'src_size':[w,h],'boxes':all_boxes,'confs':all_confs,
              'segments':[[0,frames]],'picks':[{'frame':anchor,'box':candidate,'segment':[0,frames]}]}
        progress('裁剪 '+profile['name'])
        crops,transform,preview,report,cw,ch,count=nodes.H3FaceTrackCrop().run(
            images,'face_yolov8n.pt',.25,2.5,request['size'],request['size'],'manual',
            15,31,'gaussian','per_frame',identity_track=False,face_pick=pick,
            cut_detection='none',absent_shots='off')
        if not any(transform['detected']):continue
        used.add(j)
        index=len(tracks);crop=out/f'face-{index}-seed.mkv'
        aligned=write_video(crops,crop,request['ffmpeg'],pad=True)
        tp=out/f'face-{index}-transform.json';tp.write_text(json.dumps(transform))
        track={'entity_id':profile['id'],'name':profile['name'],'appearance':profile['appearance'],
               'references':profile['references'],'crop':str(crop),'transform':str(tp),
               'frames':frames,'aligned_frames':aligned,'width':cw,'height':ch,
               'match_score':best,'match_gap':gap,'report':report}
        tracks.append(track)
        write_video(preview,out/f'face-{index}-tracking.mp4',request['ffmpeg'],source_audio=request['source'])
    for j,profile in enumerate(profiles):
        if j not in used:warnings.append(profile['name']+'未找到可靠的人脸匹配，保留该人物原片区域')
    result={'tracks':tracks,'warnings':warnings}
    (out/'prepared.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    progress('面部追踪完成',faces=len(tracks))

def stitch(request,nodes):
    images=read_video(request['source']);out=images
    for track in request['tracks']:
        transform=json.loads(Path(track['transform']).read_text())
        refined=read_video(track['refined'])[:len(transform['boxes'])]
        if refined.shape[0]!=len(transform['boxes']):raise ValueError('精修帧数不足，拒绝错位回贴')
        mask=None
        if request.get('preserve_mouth',True):
            # Face-shaped upper region. The mouth/chin area stays from the source
            # instead of relying on a generative model to reproduce lip timing.
            _,ch,cw,_=refined.shape
            mask=torch.zeros((len(refined),ch,cw))
            for i,(x,y,w,h) in enumerate(transform['face_rect']):
                yy,xx=torch.meshgrid(torch.arange(ch),torch.arange(cw),indexing='ij')
                ellipse=((xx-(x+w/2))/(w*.55+1e-6))**2+((yy-(y+h*.42))/(h*.5+1e-6))**2<1
                ellipse &= yy<y+h*.58
                mask[i]=ellipse.float()
        progress('回贴 '+track['name'])
        out,=nodes.H3FaceStitch().run(out,refined,transform,'face_ellipse',0,6 if mask is not None else 16,
                                    .65,.85,'fade_out',masks=mask)
        if request.get('preserve_mouth',True):
            # Feathering must not leak generated pixels into the mouth region.
            # Restore the lower detected face directly in source coordinates.
            cw,ch=transform['canvas'];_,sh,sw,_=images.shape
            for i,((bx,by,bw,bh),(fx,fy,fw,fh)) in enumerate(zip(transform['boxes'],transform['face_rect'])):
                frame=(transform.get('source') or list(range(len(refined))))[i]
                left=max(0,math.floor(bx+(fx-fw*.1)/cw*bw))
                right=min(sw,math.ceil(bx+(fx+fw*1.1)/cw*bw))
                top=max(0,math.floor(by+(fy+fh*.58)/ch*bh))
                bottom=min(sh,math.ceil(by+(fy+fh*1.05)/ch*bh))
                if left<right and top<bottom:
                    out[frame,top:bottom,left:right]=images[frame,top:bottom,left:right]
    write_video(out,request['output'],request['ffmpeg'],source_audio=request['source'])
    progress('面部精修回贴完成')

if __name__=='__main__':
    phase,path=sys.argv[1:3];request=json.loads(Path(path).read_text())
    nodes=load_nodes()
    if phase=='prepare':prepare(request,nodes)
    elif phase=='stitch':stitch(request,nodes)
    else:raise ValueError('unknown phase')
