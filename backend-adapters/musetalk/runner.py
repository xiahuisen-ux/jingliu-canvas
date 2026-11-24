"""MuseTalk 1.5 on MPS; aligned frame batches, Vision landmarks, no shell commands."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
os.environ.setdefault('MUSETALK_DEVICE','mps')
os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
os.environ.setdefault('MUSETALK_MASK_EVERY','1')
os.environ.setdefault('MUSETALK_USE_VISION','1')


def check():
    import torch
    import cv2
    import diffusers
    import transformers
    from musetalk.utils.vision_landmarks import AVAILABLE
    if not torch.backends.mps.is_available() or not AVAILABLE:raise RuntimeError('MPS 或 Apple Vision 不可用')
    x=torch.ones((2,2),device='mps');assert float((x+x).cpu().sum())==8
    print(json.dumps({'ready':True,'device':'mps','vision':AVAILABLE,'torch':torch.__version__,'diffusers':diffusers.__version__,'transformers':transformers.__version__}))


def detect(frame,region):
    import cv2
    import numpy as np
    from musetalk.utils.vision_landmarks import get_landmarks_68,Quartz,Vision,NSData
    h,w=frame.shape[:2];rect=(0,0,w,h)
    if region:
        x,y,rw,rh=region
        rect=(round(x*w),round(y*h),round((x+rw)*w),round((y+rh)*h))
    x0,y0,x3,y3=rect;crop=frame[y0:y3,x0:x3]
    ch,cw=crop.shape[:2];rgb=np.ascontiguousarray(crop[:,:,::-1])
    data=NSData.dataWithBytes_length_(rgb.tobytes(),rgb.nbytes)
    provider=Quartz.CGDataProviderCreateWithCFData(data)
    image=Quartz.CGImageCreate(cw,ch,8,24,cw*3,Quartz.CGColorSpaceCreateDeviceRGB(),Quartz.kCGBitmapByteOrderDefault,provider,None,False,Quartz.kCGRenderingIntentDefault)
    handler=Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image,None)
    request=Vision.VNDetectFaceLandmarksRequest.alloc().init();ok,_=handler.performRequests_error_([request],None)
    faces=request.results() if ok else []
    if len(faces)>1:raise ValueError('选定区域出现多个人脸，请回到第六页圈选单个说话人物，或分段处理')
    if not faces:return None
    points=get_landmarks_68(crop)
    if points is None:return None
    # Same nose/contour geometry used by upstream MuseTalk preprocessing.
    center=points[29,1];distance=points[:,1].max()-center
    box=(max(0,int(points[:,0].min()))+x0,max(0,int(center-distance))+y0,
         min(cw,int(points[:,0].max()))+x0,min(ch,int(points[:,1].max()))+y0)
    return box if box[2]-box[0]>16 and box[3]-box[1]>16 else None


def run(request):
    import cv2
    import numpy as np
    import torch
    from transformers import WhisperModel
    from musetalk.models.vae import VAE
    from musetalk.models.unet import UNet,PositionalEncoding
    from musetalk.utils.audio_processor import AudioProcessor
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.blending import get_image,reset_mask_cache

    cfg=request['runtime'];start=time.monotonic();torch.set_num_threads(4)
    device=torch.device('mps');dtype=torch.float32
    print('PROGRESS 5 加载 MuseTalk 1.5 / VAE / Whisper',flush=True)
    unet=UNet(cfg['unet_config'],cfg['checkpoint'],device=torch.device('cpu')).model.eval().to(device)
    vae=VAE(cfg['vae']);pe=PositionalEncoding().to(device);t=torch.tensor([0],device=device)
    whisper=WhisperModel.from_pretrained(cfg['whisper'],local_files_only=True).to(device).eval()
    processor=AudioProcessor(cfg['whisper']);fp=FaceParsing()
    audio_features,length=processor.get_audio_feature(request['audio'])
    cap=cv2.VideoCapture(request['video']);fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not count or fps<=0:raise RuntimeError('无法读取模型输入视频')
    if abs(fps-round(fps))>.01:raise RuntimeError('模型输入需先转换为整数帧率')
    chunks=processor.get_whisper_chunk(audio_features,device,dtype,whisper,length,fps=int(round(fps)))
    # Prepared audio is padded to the exact picture duration. No ping-pong loops.
    if len(chunks)<count-1:raise RuntimeError('配音特征不足以覆盖视频，未生成结果')
    result=Path(request['output']);result.parent.mkdir(parents=True,exist_ok=True)
    err=result.with_suffix('.ffmpeg.log');generated=0;skipped=[]
    with err.open('wb') as error_stream:
        encoder=subprocess.Popen([cfg['ffmpeg'],'-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}',
                                  '-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',str(result)],stdin=subprocess.PIPE,stderr=error_stream)
        try:
            frame_index=0;batch=max(1,int(request.get('batch_size',4)));margin=int(request.get('extra_margin',10));region=request.get('region')
            with torch.inference_mode():
                while frame_index<count:
                    frames=[];boxes=[];latents=[];features=[];indexes=[]
                    for j in range(min(batch,count-frame_index)):
                        ok,frame=cap.read()
                        if not ok:raise RuntimeError('视频解码提前结束')
                        box=detect(frame,region)
                        frames.append(frame);boxes.append(box)
                        if box is None:skipped.append(frame_index+j);continue
                        x1,y1,x2,y2=box;y2=min(height,y2+margin);boxes[-1]=(x1,y1,x2,y2)
                        crop=cv2.resize(frame[y1:y2,x1:x2],(256,256),interpolation=cv2.INTER_LANCZOS4)
                        latents.append(vae.get_latents_for_unet(crop));features.append(chunks[min(frame_index+j,len(chunks)-1)]);indexes.append(j)
                    if latents:
                        prediction=unet(torch.cat(latents),t,encoder_hidden_states=pe(torch.stack(features))).sample
                        faces=vae.decode_latents(prediction)
                        for j,face in zip(indexes,faces):
                            x1,y1,x2,y2=boxes[j];face=cv2.resize(face.astype(np.uint8),(x2-x1,y2-y1))
                            reset_mask_cache();combined=get_image(frames[j],face,boxes[j],mode='jaw',fp=fp)
                            if region:
                                rx,ry,rw,rh=region;ax,ay,bx,by=round(rx*width),round(ry*height),round((rx+rw)*width),round((ry+rh)*height)
                                frames[j][ay:by,ax:bx]=combined[ay:by,ax:bx]
                            else:frames[j]=combined
                            generated+=1
                    for frame in frames:encoder.stdin.write(frame.tobytes())
                    frame_index+=len(frames)
                    print(f'PROGRESS {10+int(80*frame_index/count)} 已处理 {frame_index}/{count} 帧，未识别人脸 {len(skipped)} 帧',flush=True)
            encoder.stdin.close();encoder.wait(timeout=60)
            if encoder.returncode:raise RuntimeError('模型输出编码失败')
            if not generated:raise ValueError('未检测到可处理的真人脸，原片保留；请圈选人物或换清晰单人镜头')
        finally:
            cap.release()
            if encoder.poll() is None:encoder.kill();encoder.wait()
    metrics={'model':'MuseTalk 1.5','device':'mps','precision':'float32','frames':count,'processed_frames':generated,
             'skipped_frames':skipped,'fps':fps,'region':request.get('region'),'seconds':time.monotonic()-start,
             'source_revision':cfg['revision'],'batch_size':batch,'extra_margin':margin}
    result.with_suffix('.metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
    print('PROGRESS 95 MuseTalk 处理完成，正在保留目标配音',flush=True)


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--check':check()
    else:
        with open(sys.argv[1]) as file:request=json.load(file)
        run(request)
