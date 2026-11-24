import React,{useRef,useState,useLayoutEffect} from 'react';
import {Handle,Position,NodeToolbar} from '@xyflow/react';
import {SourcePort} from './source-port.jsx';

export const videoPaths=s=>[...new Set([...(s.video_versions||s.media_history||[]).map(v=>v.video),s.video,...(s.enhanced_versions||[]).map(v=>v.video)].filter(Boolean))];

export function referenceRows(n){
 const counts={};
 return (n.item.video_references||[]).map((r,i)=>{
  const path=r.preview_path||r.path,kind=r.kind||'image';
  const name=(r.source==='element'?r.label?.split(' · ')[0]:r.label)||path.split('/').at(-1);
  counts[name]=(counts[name]||0)+1;
  return {...r,originalPath:r.path,path,kind,name,token:'@'+name+(counts[name]>1?'·'+counts[name]:'')};
 });
}

export function VideoCard({n,c,selected}){
 const id=n.id,s=n.item,v=c.values(n),path=c.videoPreview(n),list=videoPaths(s),references=referenceRows(n);
 const player=useRef(null),input=useRef(null),caret=useRef(null);
 const [mediaDuration,setMediaDuration]=useState(0),[trimStart,setTrimStart]=useState(0),[trimEnd,setTrimEnd]=useState(5);
 const [tool,setTool]=useState(''),[query,setQuery]=useState(null),[active,setActive]=useState(0);
 const request=v.canvas_request||'';
 useLayoutEffect(()=>{if(caret.current!==null){input.current?.focus();input.current?.setSelectionRange(caret.current,caret.current);caret.current=null}},[request]);
 const matches=query===null?[]:references.filter(r=>r.name.toLowerCase().includes(query.text.toLowerCase()));
 const insert=r=>{
  const field=input.current,start=query?.start??field?.selectionStart??request.length,end=field?.selectionEnd??request.length;
  const token=r.token;
  const next=request.slice(0,start)+token+' '+request.slice(end);
  const bindings=[...(v.canvas_mentions||[]).filter(x=>x.token!==token),{token,path:r.path}];
  caret.current=start+token.length+1;c.editDraft(n,'canvas_request',next);c.editDraft(n,'canvas_mentions',bindings);
  setQuery(null);
 };
 const change=e=>{
  c.editDraft(n,'canvas_request',e.target.value);
  const before=e.target.value.slice(0,e.target.selectionStart),found=before.match(/@([^@\n]*)$/);
  const bound=found&&(v.canvas_mentions||[]).some(b=>found[0].startsWith(b.token+' '));
  setQuery(found&&!bound?{start:before.length-found[0].length,text:found[1]}:null);setActive(0);
 };
 const extract=frame=>{c.videoAction(n,'canvas_extract_frame',{frame,time:player.current?.currentTime||0,video:path});setTool('')};
 return <div className={`video-card ${selected?'picked':''}`}>
  <NodeToolbar isVisible={selected} position={Position.Top} offset={14} className="video-toolbar nodrag nowheel">
   <button disabled={!path||c.mutating} aria-expanded={tool==='upscale'} onClick={()=>setTool(tool==='upscale'?'':'upscale')}>↗ 提升分辨率</button>
   <button disabled={!path||c.mutating} aria-expanded={tool==='frame'} onClick={()=>setTool(tool==='frame'?'':'frame')}>▣ 抽帧</button>
   <button disabled={!path||c.mutating||!mediaDuration} aria-expanded={tool==='trim'} onClick={()=>{setTrimStart(0);setTrimEnd(Math.min(5,mediaDuration));setTool(tool==='trim'?'':'trim')}}>✂ 截取片段</button>
   {path&&<a href={c.media(path)} download>↓ 下载</a>}
   {tool==='upscale'&&<div className="video-tool-popover"><span>保留原片，在右侧生成新视频</span>{[2,4].map(scale=><button key={scale} onClick={()=>{c.videoAction(n,'canvas_video_upscale',{scale,video:path});setTool('')}}>{scale}× 分辨率</button>)}</div>}
   {tool==='frame'&&<div className="video-tool-popover"><span>在右侧生成独立图片</span><button onClick={()=>extract('first')}>首帧</button><button onClick={()=>extract('last')}>尾帧</button><button onClick={()=>extract('current')}>当前帧 · {(player.current?.currentTime||0).toFixed(2)}s</button></div>}
   {tool==='trim'&&<div className="video-tool-popover trim-popover"><span>原视频 {mediaDuration.toFixed(2)} 秒 · 保留原片</span><label>起点（秒）<input aria-label="截取起点" type="number" min="0" max={mediaDuration} step="0.1" value={trimStart} onChange={e=>setTrimStart(Number(e.target.value))}/></label><button onClick={()=>setTrimStart(Number((player.current?.currentTime||0).toFixed(2)))}>当前画面设为起点</button><label>终点（秒）<input aria-label="截取终点" type="number" min="0" max={mediaDuration} step="0.1" value={trimEnd} onChange={e=>setTrimEnd(Number(e.target.value))}/></label><button onClick={()=>setTrimEnd(Number((player.current?.currentTime||0).toFixed(2)))}>当前画面设为终点</button><span>片段 {Math.max(0,trimEnd-trimStart).toFixed(2)} 秒 · 可独立修改提示词与参考图</span><button className="primary" disabled={c.mutating||trimStart<0||trimEnd>mediaDuration+.02||trimEnd-trimStart<.1} onClick={()=>{c.videoAction(n,'canvas_trim_video',{video:path,start:trimStart,end:trimEnd});setTool('')}}>截取到右侧新窗口</button></div>}
  </NodeToolbar>
  <Handle type="target" position={Position.Left} id="reference" aria-label="视频参考输入"/>
  <SourcePort n={n} c={c} type="video"/>
  <div className="card-head drag-handle"><span className="type-symbol">▷</span><strong>{v.title||'视频镜头'}</strong><span className="card-type">视频</span></div>
  <div className="video-preview nodrag" tabIndex={0} role="group" aria-label={`打开 ${s.title||'视频'} 创作窗口`} onClick={()=>c.activate(id)} onKeyDown={e=>{if(e.key==='Enter')c.activate(id)}}>
   {path&&path!==s.video&&<span className="video-history-badge">历史版本</span>}
   {path?<video key={path} ref={player} onLoadedMetadata={e=>setMediaDuration(Number.isFinite(e.currentTarget.duration)?e.currentTarget.duration:0)} src={c.media(path)} controls preload="metadata"/>:<div className="blank-image"><span>▷</span><b>点击，开始创作视频</b><small>连接素材 · 用 @ 描述你想要的画面</small></div>}
  </div>
  {selected&&<div className="video-dialogue nodrag nowheel">
   {s.canvas_origin?.operation==='audio_to_video'&&<div className="trim-note">黑屏 MP4 · 保留完整声音；作为 H3 参考时需 2–15 秒，长音频可先截取片段。</div>}
   {s.canvas_origin?.operation==='trim'&&<div className="trim-note">截取片段 {s.canvas_origin.duration.toFixed(2)} 秒；重新生成使用下方 5–15 秒时长。</div>}
   <div className="reference-heading"><span>参考素材 · {references.length}</span><button onClick={()=>c.importVideo(n)}>＋ 导入视频</button></div>
   <div className="pinned-references" aria-label="已连接的参考素材">
    {references.map((r,i)=><div key={r.path+i} className={'reference-tile '+(r.missing?'missing':'')}><button className="reference-insert" title={r.token+' · 点击引用'} onClick={()=>insert(r)}>
     {r.kind==='image'||r.kind==='anchor'?<img src={c.media(r.path)} alt={r.name}/>:r.kind==='audio'?<span className="reference-icon">♫</span>:<video src={c.media(r.path)} preload="metadata" muted/>}
     <span>{r.token}</span><small>{r.missing?'文件缺失':r.kind==='audio'?'声音':r.kind==='image'||r.kind==='anchor'?'图片':r.kind==='video'?'视频＋声音':'视频'}</small>
    </button><button className="reference-remove" aria-label={`取消关联 ${r.name}`} title="取消关联并断开连线" disabled={c.mutating} onClick={e=>{e.stopPropagation();setQuery(null);c.removeReference(n,r)}}>×</button></div>)}
    {!references.length&&<p>从图片或视频右侧拖线到这里，素材会自动固定在上方。</p>}
   </div>
   <div className="video-prompt-wrap"><textarea ref={input} aria-label={`${s.title||'视频'}生成要求`} placeholder="例如：以图片 @豆包 为女主，替换视频 @视频 1.mp4 中的女生，保留原运镜。" value={request} onBlur={()=>setQuery(null)} onChange={change} onKeyDown={e=>{
    if(query!==null&&matches.length){
     if(['ArrowDown','ArrowUp','Enter','Escape'].includes(e.key)){e.preventDefault();e.stopPropagation()}
     if(e.key==='ArrowDown')setActive((active+1)%matches.length);
     if(e.key==='ArrowUp')setActive((active+matches.length-1)%matches.length);
     if(e.key==='Enter')insert(matches[active%matches.length]);
     if(e.key==='Escape')setQuery(null);
    }
   }}/>
   {query!==null&&<div className="mention-menu" role="listbox" aria-label="选择引用素材">{matches.length?matches.map((r,i)=><button role="option" aria-selected={i===active} className={i===active?'active':''} key={r.path+i} onMouseDown={e=>e.preventDefault()} onClick={()=>insert(r)}>{r.kind==='image'||r.kind==='anchor'?'▧':r.kind==='audio'?'♫':'▷'} {r.token}</button>):<span>没有匹配素材，先连接图片或视频</span>}</div>}
   </div>
   <div className="video-compose-actions"><button className="mention-trigger" onClick={()=>{const pos=input.current?.selectionStart??request.length;input.current?.focus();setQuery({start:pos,text:''})}}>@ 素材</button><label><input aria-label="视频时长" className="duration" type="number" min="5" max="15" value={v.duration??10} onChange={e=>c.editDraft(n,'duration',Number(e.target.value))}/> 秒</label><button disabled={c.mutating} onClick={()=>c.save(n)}>保存</button><button className="generate" disabled={c.mutating} onClick={()=>c.generate(n)}>▷ 生成视频</button></div>
   <details className="video-details"><summary>原镜头要求与版本</summary><label>名称<input value={v.title||''} onChange={e=>c.editDraft(n,'title',e.target.value)}/></label><p>{v.description||'生成要求保存在上方输入框。'}</p>
    {!!list.length&&<label>预览版本<select aria-label="预览视频版本" value={path} onChange={e=>c.setPreview(id,e.target.value)}>{list.map((p,i)=><option key={p} value={p}>{i+1} · {p.split('/').at(-1)}{p===s.video?' · 当前':''}</option>)}</select></label>}
    {!s.canvas_standalone&&<a href={`/index.html?project=${c.project.id}&stage=storyboard`} target="_blank" rel="noreferrer">剧本、音轨与详细设置 ↗</a>}
    <small>视频参考用于重新生成画面，具体替换效果需预览确认。</small>
   </details>
   {c.drafts[id]&&<div className="draft-line">草稿已暂存 <button onClick={()=>c.discard(n)}>放弃修改</button></div>}
   {s.video_stale&&<div className="stale-note">旧版本 · 参考或剧本已改变</div>}
  </div>}
 </div>
}
