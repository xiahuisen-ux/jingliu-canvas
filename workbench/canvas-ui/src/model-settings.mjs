// Only expose parameters consumed by the existing backends. Never post a whole stale config.
export const LIP_DEFAULTS_KEY='mirrorflow-musetalk-defaults-v1';
export const D_PROFILE={h3c_steps:15,h3c_layers:45,h3c_reuse:2,h3c_reference_video_max_pixels:358400};
export const VIDEO_CHOICES={h3c_layers:[45,50],h3c_reuse:[1,2],h3c_reference_video_max_pixels:[0,147456,358400,589824]};
export const sections={
 text:{title:'文字模型',keys:['provider','base_url','model','timeout','max_tokens','structured','local_num_ctx']},
 image:{title:'Z-Image-Turbo · 文生图',keys:['image_width','image_height','image_steps','reference_size']},
 edit:{title:'Qwen-Image-Edit · 参考重绘',keys:['image_width','image_height']},
 video:{title:'MiniMax H3 · Metal 视频',keys:['video_width','video_height','video_duration','h3c_steps','h3c_layers','h3c_reuse','h3c_reference_video_max_pixels','video_upscale','h3c_resident','h3c_ssd_streaming','h3c_swap_limit_gib','h3c_stall_minutes']},
 face:{title:'H3 FaceRefine · 面部精修',keys:['h3c_face_refine','h3c_face_preserve_mouth','h3c_face_size','h3c_face_steps','h3c_face_denoise']},
 lipsync:{title:'MuseTalk 1.5 · 对口型',keys:['batch_size','extra_margin']},
};
export const numeric={
 image_width:[384,1536,16],image_height:[384,1536,16],image_steps:[4,12,1],reference_size:[512,1024,64],
 video_width:[256,1344,32],video_height:[256,1344,32],video_duration:[5,15,1],h3c_steps:[4,50,1],
 h3c_swap_limit_gib:[2,30,1],h3c_stall_minutes:[5,60,1],h3c_face_size:[512,768,32],h3c_face_steps:[4,20,1],h3c_face_denoise:[.01,.15,.01],
 timeout:[10,600,1],max_tokens:[256,64000,1],batch_size:[1,8,1],extra_margin:[0,40,1],
};
export function lipDefaults(storage){
 try{const v=JSON.parse(storage.getItem(LIP_DEFAULTS_KEY));if(v&&Number.isInteger(v.batch_size)&&v.batch_size>=1&&v.batch_size<=8&&Number.isInteger(v.extra_margin)&&v.extra_margin>=0&&v.extra_margin<=40)return {batch_size:v.batch_size,extra_margin:v.extra_margin}}catch{}
 return {batch_size:4,extra_margin:10};
}
export function changedValues(section,base,draft){
 if(section==='video'&&Number(draft.h3c_steps)<8&&Number(draft.h3c_reuse??1)>1)throw Error('4–7 步预览请使用 reuse 1；reuse 2 至少 8 步');
 const patch={};for(const key of sections[section].keys){
  if(draft[key]===base[key])continue;
  let value=draft[key];
  if(VIDEO_CHOICES[key]&&!VIDEO_CHOICES[key].includes(value))throw Error(`${key}：请选择有效档位`);
  if(numeric[key]){
   const [min,max,step]=numeric[key];
   if(value===''||value==null||!Number.isFinite(Number(value)))throw Error('请填写有效数值');
   value=Number(value);const ticks=(value-min)/step;
   if(value<min||value>max||Math.abs(ticks-Math.round(ticks))>1e-6)throw Error(`${key}：范围 ${min}–${max}，步长 ${step}`);
  }
  if(value!==base[key])patch[key]=value;
 }return patch;
}
export function checkConflict(base,current,patch){
 if(Object.keys(patch).some(k=>current[k]!==base[k]))throw Error('这些参数已在其他窗口修改。请关闭后重新打开，读取最新值再保存。');
}
export function isBusy(runtime){return !!runtime.busy||runtime.stop?.status==='stopping'||(runtime.jobs||[]).some(j=>['queued','running'].includes(j.status))}
export function modelSection(category,index=0){return ({文字模型:'text',图片模型:index?'edit':'image',视频模型:'video',面部模型:'face',对口型模型:'lipsync'})[category]}
