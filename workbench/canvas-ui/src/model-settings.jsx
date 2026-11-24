import React,{useState,useEffect,useRef} from 'react';
import {sections,numeric,LIP_DEFAULTS_KEY,lipDefaults,changedValues,checkConflict,isBusy,modelSection,D_PROFILE} from './model-settings.mjs';
import './model-settings.css';

export function ModelBar({api,runtime,projectId}){
 const [models,setModels]=useState([]),[error,setError]=useState(false),[section,setSection]=useState(null),[revision,setRevision]=useState(0);
 useEffect(()=>{let live=true;const refresh=()=>api('/api/canvas-models').then(rows=>{if(live){setModels(rows);setError(false)}}).catch(()=>{if(live)setError(true)});refresh();window.addEventListener('focus',refresh);return()=>{live=false;window.removeEventListener('focus',refresh)}},[revision]);
 return <><section className="model-bar" aria-label="模型与参数设置">{models.map(group=><div className="model-group" key={group.category}>
  <button className="model-category" onClick={()=>setSection(modelSection(group.category))}>{group.category}<span>参数 ⚙</span></button>
  <div>{group.models.map((m,i)=><button className="model-entry" key={m.name} aria-label={`设置 ${m.name}`} title="点击设置模型参数（不会启动模型）" onClick={()=>setSection(modelSection(group.category,i))}><i className={m.ready===true?'ready':m.ready===false?'unavailable':'unknown'}/><b>{m.name}</b><small>{m.state}</small></button>)}</div>
 </div>)}{!models.length&&<button onClick={()=>setRevision(v=>v+1)}>{error?'模型状态读取失败 · 重试':'正在读取模型状态…'}</button>}{error&&!!models.length&&<button onClick={()=>setRevision(v=>v+1)}>重试状态</button>}</section>
 {section&&<ModelSettings key={section} section={section} api={api} runtime={runtime} projectId={projectId} onClose={()=>setSection(null)} onSaved={()=>setRevision(v=>v+1)}/>}</>;
}
function ModelSettings({section,api,runtime,projectId,onClose,onSaved}){
 const dialog=useRef(),savingRef=useRef(false),[base,setBase]=useState(null),[draft,setDraft]=useState({}),[error,setError]=useState(''),[status,setStatus]=useState(''),[saving,setSaving]=useState(false),[reload,setReload]=useState(0);
 const endpoint=section==='text'?'/api/text-model':'/api/settings';
 const busy=isBusy(runtime),local=section==='lipsync';
 useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus()},[]);
 useEffect(()=>{let live=true;setBase(null);setError('');Promise.resolve(local?lipDefaults(localStorage):api(endpoint)).then(data=>{if(live){setBase(data);setDraft(data)}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[reload]);
 const set=(key,value)=>{setDraft(old=>({...old,[key]:value}));setStatus('');setError('')};
 const patch=()=>changedValues(section,base,draft);
 const dirty=base&&sections[section].keys.some(k=>draft[k]!==base[k]);
 const close=()=>{if(!savingRef.current&&(!dirty||window.confirm('参数尚未保存，放弃本次修改？')))onClose()};
 const save=async e=>{
  e.preventDefault();if(savingRef.current||!base)return;savingRef.current=true;setSaving(true);setError('');setStatus('');
  try{
   const changes=patch();if(!Object.keys(changes).length){setStatus('参数没有变化');return}
   let result;
   if(local){const current=lipDefaults(localStorage);checkConflict(base,current,changes);result={...current,...changes};localStorage.setItem(LIP_DEFAULTS_KEY,JSON.stringify(result))}
   else{
    if(isBusy(await api('/api/runtime')))throw Error('任务仍在运行。草稿已保留，请在任务结束后保存；不会中断当前生成。');
    const current=await api(endpoint);checkConflict(base,current,changes);
    result=await api(endpoint,changes);
   }
   setBase(result);setDraft(result);setStatus(local?'已保存到当前浏览器；重新打开口型校对页时自动带入。':'已保存，后续任务使用新参数；现有图片和视频不变。');onSaved();
  }catch(e){setError(e.message)}finally{savingRef.current=false;setSaving(false)}
 };
 const number=(key,label,note)=>{const [min,max,step]=numeric[key];return <label className="parameter-field" key={key}><span>{label}</span><input type="number" required min={min} max={max} step={step} value={draft[key]??''} onChange={e=>set(key,e.target.value===''?'':Number(e.target.value))}/>{note&&<small>{note}</small>}</label>};
 const check=(key,label,note)=><label className="parameter-check"><input type="checkbox" checked={!!draft[key]} onChange={e=>set(key,e.target.checked)}/><span>{label}{note&&<small>{note}</small>}</span></label>;
 const select=(key,label,options)=><label className="parameter-field"><span>{label}</span><select value={draft[key]??''} onChange={e=>set(key,typeof options[0][0]==='number'?Number(e.target.value):e.target.value)}>{options.map(([value,text])=><option key={value} value={value}>{text}</option>)}</select></label>;
 const sizePresets=(kind,options)=><div className="parameter-presets"><span>快捷画幅</span>{options.map(([w,h])=><button key={w+'x'+h} type="button" onClick={()=>{set(kind+'_width',w);set(kind+'_height',h)}}>{w} × {h}</button>)}</div>;
 return <dialog ref={dialog} className="model-settings-dialog" onCancel={e=>{e.preventDefault();close()}} aria-labelledby="model-settings-title">
 <form onSubmit={save}><header><div><small>画布主工作台 / 模型参数</small><h2 id="model-settings-title">{sections[section].title}</h2></div><button type="button" aria-label="关闭模型设置" disabled={saving} onClick={close}>×</button></header>
 <div className="parameter-body">
 <p className="parameter-scope">{local?'对口型默认参数 · 仅保存到当前浏览器，不自动运行模型。':'全局模型参数 · 影响后续任务，不会重新生成已有作品。打开设置不会加载模型。'}</p>
 {!local&&busy&&<p className="parameter-warning" role="status">有任务正在运行：可以查看和编辑参数草稿，任务结束后才能保存。不停止、不重启当前模型。</p>}
 {!base&&!error&&<p>正在读取已保存参数…</p>}
 {base&&<fieldset disabled={saving}>
 {section==='text'&&<>
  <p>当前服务：{draft.provider==='local'?'本地 Ollama':draft.provider} · {draft.model||'配置的本地文字模型'}。{draft.key_configured?'后端已配置密钥，网页不读取密钥。':''}</p>
  {draft.provider==='local'?<>{select('local_num_ctx','本地文字任务上下文',[[16384,'16K'],[32768,'32K'],[65536,'64K']])}<p>输入和输出共用上下文；更长会增加内存占用。普通聊天与视觉任务有独立设置。</p></>:<>
   <label className="parameter-field"><span>模型 ID</span><input required value={draft.model||''} onChange={e=>set('model',e.target.value)}/><small>使用当前服务商账户可用的模型 ID，不会自动测试或产生调用费用。</small></label>
   <div className="parameter-grid">{number('timeout','请求超时（秒）')}{number('max_tokens','输出上限（tokens）')}</div>
   {draft.provider==='compatible'&&check('structured','严格 JSON Schema','不支持时关闭，改用 JSON 模式。')}
   <p className="parameter-warning">文字任务会发送到 {draft.base_url}。保存参数不会发起模型请求。</p>
  </>}
  <a className="parameter-link" href={'/index.html?'+new URLSearchParams({...(projectId?{project:projectId}:{}),modelSettings:'text'})} target="_blank" rel="noreferrer">更换服务商 / 管理密钥 ↗</a>
 </>}
 {['image','edit'].includes(section)&&<>
  <p>{section==='edit'?'有参考图时使用 Qwen 图像编辑。当前 Lightning 为固定 8 步、CFG 1、Euler / simple，不能把文生图步数误当编辑步数。':'无参考图时使用 Z-Image-Turbo；有参考图的画布重绘自动走 Qwen。'}</p>
  {sizePresets('image',[[1344,768],[768,1344],[1024,1024]])}
  <div className="parameter-grid">{number('image_width','图片宽度（像素）','384–1536，16 的倍数')}{number('image_height','图片高度（像素）','384–1536，16 的倍数')}
  {section==='image'&&number('image_steps','文生图采样步数','仅无参考图的文生图使用')}{section==='image'&&number('reference_size','旧元素参考图基础尺寸','512–1024；不改变画布单张图尺寸')}</div>
  <p>宽高由文生图和画布 Qwen 重绘共用；尺寸越大通常越耗时、越占内存。尾帧等专用流程可使用源图尺寸。</p>
 </>}
 {section==='video'&&<>
  {base.h3c_layers!=null?<>
   <div className="parameter-presets"><span>速度 / 质量</span><button type="button" onClick={()=>{for(const [k,v] of Object.entries(D_PROFILE))set(k,v)}}>D 档 · 15 步 / 45 层 / reuse 2</button><button type="button" onClick={()=>{set('h3c_layers',50);set('h3c_reuse',1);set('h3c_reference_video_max_pixels',0)}}>原始计算 · 50 层 / reuse 1</button></div>
   <div className="parameter-grid">{select('h3c_layers','DiT 活动层数',[[50,'50 层 · 完整'],[45,'45 层 · 均衡']])}{select('h3c_reuse','去噪复用（不减少输出帧数）',[[1,'1 · 每步计算'],[2,'2 · 间隔计算 / 外推']])}{select('h3c_reference_video_max_pixels','参考视频像素上限',[[0,'原生默认 · 最高约 768×1344'],[147456,'轻量 · 约 288×512'],[358400,'D 档 · 约 448×800'],[589824,'较细 · 约 576×1024']])}</div>
   <p>上限按面积控制并对齐 32 像素，横竖屏随原片；不提高小视频尺寸，不改原文件、时长或参考音轨。15 步 + reuse 2 计算 8 次新预测，其余步骤外推；动作、面部细节可能变化，尚未完成本机画质测速。</p>
  </>:<p className="parameter-warning">D 档接口等待后端部署；当前只能使用原有参数。</p>}
  {sizePresets('video',[[512,288],[832,480],[1024,576],[512,512]])}
  <div className="parameter-grid">{number('video_width','视频宽度（像素）','256–1344，32 的倍数')}{number('video_height','视频高度（像素）','256–1344，32 的倍数')}{number('video_duration','新视频默认时长（秒）','5–15 秒；已有节点时长不改')}{number('h3c_steps','H3 采样步数','4–50；更多步不保证身份与动作正确')}{select('video_upscale','分段流程自动超分',[[0,'关闭'],[2,'2 倍'],[4,'4 倍']])}</div>
  <p>原生输出固定 24 fps，最终导出 H.264 / CRF 18 / fast，音频 AAC 192k。D 档不启用 token 合并或低分辨率内部放大，保留原生多参考；4–7 步预览须选 reuse 1。分段自动超分不等于原生生成分辨率；画布视频可另建增强版。</p>
  {check('h3c_resident','H3 常驻与缓存','连续生成可复用进程；空闲时仍可能占内存。')}
  {check('h3c_ssd_streaming','SSD 逐层加载','降低常驻内存，但增加模型文件读取；关闭也不能保证系统零交换。')}
  <div className="parameter-grid">{number('h3c_swap_limit_gib','交换新增停止阈值（GiB）','2–30；这是保护阈值，不是可分配内存')}{number('h3c_stall_minutes','无进度保护（分钟）','5–60；不是总生成时间上限')}</div>
 </>}
 {section==='face'&&<>
  {check('h3c_face_refine','分段视频完成后自动精修','针对剧本分段流程；画布独立视频不会因打开此项自动精修。')}
  {check('h3c_face_preserve_mouth','保留原嘴部区域','减少破坏已有嘴型；不保证身份或对口型正确。')}
  <div className="parameter-grid">{number('h3c_face_size','面部处理尺寸','512–768，32 的倍数')}{number('h3c_face_steps','精修步数')}{number('h3c_face_denoise','重绘幅度','0.01–0.15；越大越可能改动面部')}</div>
  <p>仅在实际执行精修时加载模型；无法可靠识别的面部可能跳过，原片保留。手动精修入口仍在分段视频详情。</p>
 </>}
 {local&&<>
  <div className="parameter-grid">{number('batch_size','处理批量','1–8；越大越占内存')}{number('extra_margin','下巴额外边距（像素）','0–40')}</div>
  <p>MuseTalk 1.5 已安装，实际效果仍需预览验收。声音偏移、人物区域须在具体视频上设置；保存默认值不会启动对口型。</p>
  <a className="parameter-link" href={'/index.html?'+new URLSearchParams({...(projectId?{project:projectId}:{}),stage:'lipsync'})} target="_blank" rel="noreferrer">打开视频口型校对 · 选择视频与录音 ↗</a>
 </>}
 </fieldset>}
 {error&&<p className="parameter-error" role="alert">{error}{!base&&<button type="button" onClick={()=>setReload(v=>v+1)}>重试</button>}</p>}
 {status&&<p className="parameter-success" role="status">{status}</p>}
 </div><footer><span>{dirty?'有未保存修改':'已保存参数'}</span><button type="button" disabled={saving} onClick={close}>关闭</button><button type="submit" className="primary" disabled={!base||saving||(!local&&busy)}>{saving?'正在保存…':'保存参数'}</button></footer></form></dialog>;
}
