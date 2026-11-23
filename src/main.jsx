import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow, ReactFlowProvider, Handle, Position, Background, Controls, useReactFlow} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';

const title = {ref:'参考图', image:'文生图', edit:'图像重绘', video:'视频生成'};
const engines = {image:'Z-Image-Turbo', edit:'Qwen-Image-Edit-2511', video:'MiniMax H3'};
const modelTypes = Object.keys(engines);
async function api(route, data) {
  const config = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)};
  const response = await fetch(route, config);
  const value = await response.json();
  if (!response.ok) { const err = new Error(value.error || '请求失败'); err.status=response.status; throw err; }
  return value;
}
function Card({data, selected}) {
  const n=data.item, isVideo=n.kind==='video', isTarget=isVideo||n.kind==='edit';
  return <div className={'card '+(isVideo?'film ':'')+(selected?'active':'')}>
    {isTarget&&<Handle type="target" position={Position.Left} aria-label="参考图输入"/>}
    <div className="grip"><span className={'swatch '+n.kind}/><b>{n.name}</b><small>{title[n.kind]}</small></div>
    {isVideo && n.src ? <video className="nodrag nowheel" controls playsInline preload="metadata" poster={n.src==='/demo/sail.mp4'?'/demo/cover.jpg':undefined} src={n.src}/> :
      n.src ? <img src={n.src} draggable="false" alt={n.name}/> : <div className="placeholder">等待{title[n.kind]}</div>}
    {isVideo&&<div className="cardfoot">{n.src==='/demo/sail.mp4'?'内置动画样片 · 5 秒':engines.video}<span>{data.count} 张参考</span></div>}
    {!isVideo&&<Handle type="source" position={Position.Right} aria-label="图片输出"/>}
  </div>;
}
const nodeTypes={asset:Card};

function App() {
  const flow=useReactFlow(), input=useRef(), clock=useRef(), serial=useRef(0), written=useRef(0), revision=useRef(0),
    saving=useRef(false), conflicted=useRef(false), live=useRef(null), taskRef=useRef(null);
  const [doc,setDoc]=useState(null),[selected,select]=useState('sail'),[saveLabel,setSaveLabel]=useState('已保存'),
    [notice,notify]=useState(''),[config,setConfig]=useState(null),[mode,setMode]=useState(null),[files,setFiles]=useState({}),
    [missing,setMissing]=useState(null),[checking,setChecking]=useState(false),[task,setTask]=useState(null),[edgePick,setEdgePick]=useState(null);
  const statusVersion=useRef(0);
  async function flush(){
    if(saving.current||conflicted.current||!live.current||written.current===serial.current)return;
    const ticket=serial.current; saving.current=true;
    let ok=false;
    try{const r=await api('/api/project',{...live.current,rev:revision.current});revision.current=r.rev;written.current=ticket;ok=true}
    catch(err){conflicted.current=err.status===409; setSaveLabel('保存失败');notify(err.message)}
    finally{saving.current=false;if(ok){if(serial.current!==ticket)flush();else setSaveLabel('已保存')}}
  }
  function change(fn) {
    if(!live.current||conflicted.current)return;
    const next=fn(live.current);live.current=next;setDoc(next);serial.current++;setSaveLabel('保存中…');
    clearTimeout(clock.current);clock.current=setTimeout(flush,180);
  }
  function patch(id,fields){change(d=>({...d,nodes:d.nodes.map(n=>n.id===id?{...n,...fields}:n)}))}
  function remember(t){taskRef.current=t;setTask(t);if(t)localStorage.setItem('jingliu-active-task',JSON.stringify(t));else localStorage.removeItem('jingliu-active-task')}
  useEffect(()=>{
    Promise.all([api('/api/project'),api('/api/settings'),api('/models.json')]).then(([d,c,m])=>{
      live.current=d;revision.current=d.rev;setDoc(d);setConfig(c);setFiles(m);
      const pending=localStorage.getItem('jingliu-active-task');if(pending)remember(JSON.parse(pending))
    }).catch(err=>notify(err.message));
    const unload=ev=>{if(serial.current!==written.current){ev.preventDefault();ev.returnValue=''}};
    window.addEventListener('beforeunload',unload);return ()=>window.removeEventListener('beforeunload',unload);
  },[]);
  useEffect(()=>{
    if(!task?.id)return;let alive=true;let timer;
    async function poll(){
      try{const r=await api('/api/job/'+task.id);if(!alive)return;
        if(r.state==='done'){patch(task.node,{src:r.url});remember(null);notify('生成结果已放入节点');return}
        if(r.state==='error'){remember(null);notify(r.message);return}
        setTask(t=>t?{...t,message:r.message}:null)
      }catch(err){if(!alive)return;if(err.status===404){remember(null);notify(err.message);return}notify('等待本地服务恢复')}
      timer=setTimeout(poll,1800);
    }poll();return ()=>{alive=false;clearTimeout(timer)}
  },[task?.id]);
  const chosen=doc?.nodes.find(n=>n.id===selected);
  function connect({source,target}) {
    const d=live.current, src=d.nodes.find(n=>n.id===source), dst=d.nodes.find(n=>n.id===target);
    if(!src||!dst||src.kind==='video'||source===target||!['edit','video'].includes(dst.kind))return;
    if(!src.src){notify('请先为输出节点生成一张图片');return}
    if(d.edges.some(([a,b])=>a===source&&b===target))return;
    if(d.edges.filter(([,b])=>b===target).length>=3){notify('最多接入三张参考图');return}
    change(d=>({...d,edges:[...d.edges,[source,target]]}));notify('参考图已连接');
  }
  function add(kind,src='',name=title[kind]){
    const id=crypto.randomUUID(), pt=flow.screenToFlowPosition({x:innerWidth*.49,y:innerHeight*.46});
    change(d=>({...d,nodes:[...d.nodes,{id,kind,src,name,prompt:'',x:pt.x+Math.random()*50,y:pt.y+Math.random()*40}]}));select(id);setEdgePick(null);
  }
  async function upload(e){try{const f=e.target.files[0];if(!f)return;
    const res=await fetch('/api/import',{method:'POST',body:f}),r=await res.json();if(!res.ok)throw new Error(r.error);
    add('ref',r.url,f.name.replace(/\.[^.]+$/,''));notify('图片已加入画布');
  }catch(err){notify(err.message)}finally{e.target.value=''}}
  async function check(m,c=config){
    const v=++statusVersion.current;setChecking(true);setMissing(null);
    try{if(m!=='video')await api('/api/settings',{comfy:c.comfy});const r=await api('/api/check',{mode:m});
      if(statusVersion.current===v)setMissing(r.missing);return r.missing
    }catch(err){if(statusVersion.current===v)setMissing([err.message]);return [err.message]}
    finally{if(statusVersion.current===v)setChecking(false)}
  }
  function openSetup(m){setMode(m);check(m)}
  async function pick(key){try{const c=await api('/api/pick',{key});setConfig(c);await check('video',c)}catch(err){notify(err.message)}}
  async function generate(){
    if(!chosen||taskRef.current)return;
    const m=chosen.kind, node=chosen.id;
    try{
      if(!chosen.prompt.trim()){notify('先为这个节点写一句提示词');return}
      const refs=doc.edges.filter(([,b])=>b===node).map(([a])=>doc.nodes.find(n=>n.id===a)?.src).filter(Boolean);
      if(m!=='image'&&!refs.length){notify('请先连入一张参考图');return}
      const gaps=await check(m);
      if(gaps.length){setMode(m);return}
      const r=await api('/api/generate',{mode:m,refs,prompt:chosen.prompt});remember({id:r.id,node,message:'已提交本机生成任务'})
    }catch(err){notify(err.message)}
  }
  if(!doc)return <main className="loading">{notice||'正在打开本地工程…'}</main>;
  const nodes=doc.nodes.map(n=>({id:n.id,type:'asset',position:{x:n.x,y:n.y},selected:n.id===selected,
    data:{item:n,count:doc.edges.filter(([,b])=>b===n.id).length}}));
  const edges=doc.edges.map(([a,b])=>({id:a+'>'+b,source:a,target:b,selected:edgePick===a+'>'+b}));
  function delEdge(){change(d=>({...d,edges:d.edges.filter(([a,b])=>a+'>'+b!==edgePick)}));setEdgePick(null)}
  return <div className="shell"><header><div className="brand"><i>◈</i><b>镜流</b><span>无限画布</span></div><div className="headright"><span className="save"><em/>{saveLabel}</span><button onClick={()=>openSetup(chosen?.kind in engines?chosen.kind:'video')}>模型设置</button></div></header>
    <main className="layout"><section className="stage"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{padding:.18,maxZoom:1.12}}
      onNodeClick={(_,n)=>{select(n.id);setEdgePick(null)}} onPaneClick={()=>setEdgePick(null)}
      onEdgeClick={(_,edge)=>setEdgePick(edge.id)} onConnect={connect} deleteKeyCode={null} minZoom={.18} maxZoom={2.6}
      onNodesChange={changes=>{const moves=changes.filter(i=>i.type==='position'&&i.position);if(moves.length)change(d=>({...d,nodes:d.nodes.map(n=>{const m=moves.find(i=>i.id===n.id);return m?{...n,x:m.position.x,y:m.position.y}:n})}))}}
      defaultEdgeOptions={{style:{stroke:'#9c8fc1',strokeWidth:2.3},interactionWidth:24}}><Background color="#454650" gap={22} size={1.15}/><Controls showInteractive={false}/></ReactFlow>
      <div className="toolbar"><button onClick={()=>input.current.click()}>＋ 导入图片</button><button onClick={()=>add('image')}>文生图</button><button onClick={()=>add('edit')}>图像重绘</button><button onClick={()=>add('video')}>视频节点</button></div>
      <input ref={input} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={upload}/>
      {edgePick&&<button className="unlink" onClick={delEdge}>断开选中连线</button>}
    </section><aside><div className="asideLabel">节点属性</div>{chosen?<><h1>{chosen.name}</h1><p className="muted">{engines[chosen.kind]||'输入素材'}</p>
      <label>节点名称<input maxLength={120} value={chosen.name} onChange={e=>patch(chosen.id,{name:e.target.value})}/></label>
      {chosen.kind!=='ref'?<><label>提示词<textarea value={chosen.prompt} maxLength={4000} placeholder="描述画面、动作和运镜" onChange={e=>patch(chosen.id,{prompt:e.target.value})}/></label>
      {chosen.kind!=='image'&&<><p className="label">参考图 · {doc.edges.filter(([,b])=>b===selected).length} / 3</p><div className="refs">{doc.edges.filter(([,b])=>b===selected).map(([a])=>{const n=doc.nodes.find(i=>i.id===a);return <img key={a} alt={n.name} title={n.name} src={n.src}/>})}</div><p className="hint">从图片右侧圆点拖到这个节点的左侧圆点。</p></>}
      <button className="primary" disabled={!!task||checking} onClick={generate}>{task?task.message:checking?'检测中…':chosen.kind==='video'?'生成五秒视频':'生成图片'}</button></>:<p className="hint">拖动图片右侧圆点，接到视频或重绘节点。</p>}
      {chosen.src&&<a className="download" href={chosen.src} download>下载{chosen.kind==='video'?'视频':'图片'} ↓</a>}
      <button className="remove" disabled={task?.node===chosen.id} onClick={()=>{const id=chosen.id;change(d=>({...d,nodes:d.nodes.filter(n=>n.id!==id),edges:d.edges.filter(pair=>!pair.includes(id))}));select(null)}}>移除节点</button></>:<p className="hint">点选画布上的节点查看属性。</p>}
    </aside></main>
    {notice&&<div className="toast" role="status">{notice}<button aria-label="关闭提示" onClick={()=>notify('')}>×</button></div>}
    {mode&&<div className="cover"><section className="dialog" role="dialog" aria-label="模型设置"><div className="dialoghead"><h2>模型设置</h2><button onClick={()=>{statusVersion.current++;setChecking(false);setMode(null)}} aria-label="关闭设置">×</button></div>
      <nav>{modelTypes.map(m=><button className={m===mode?'on':''} key={m} onClick={()=>openSetup(m)}>{title[m]}</button>)}</nav><h3>{engines[mode]}</h3>
      {mode==='video'?<>{[['models','模型目录'],['binary','h3 可执行文件']].map(([key,label])=><div className="pathrow" key={key}><span>{label}</span><code>{config[key]||'尚未选择'}</code><button onClick={()=>pick(key)}>选择…</button></div>)}</>:<label>本机 ComfyUI 地址<input value={config.comfy} onChange={e=>{setConfig({...config,comfy:e.target.value});setMissing(null)}}/></label>}
      <button onClick={()=>check(mode)} disabled={checking}>{checking?'正在检测…':'检测连接'}</button>
      {missing&&<div className={'result '+(!missing.length?'good':'')}>{missing.length?'待配置 · '+missing.join('、'):'检测通过，可以使用'}</div>}
      <h4>按需下载</h4>{mode!=='video'&&<p><a href="https://github.com/Comfy-Org/ComfyUI" target="_blank" rel="noreferrer">ComfyUI ↗</a>{mode==='edit'&&<>　<a href="https://github.com/city96/ComfyUI-GGUF" target="_blank" rel="noreferrer">ComfyUI-GGUF 节点 ↗</a></>}</p>}
      {(files[mode]||[]).map(f=><div className="file" key={f.label}><a href={f.url} target="_blank" rel="noreferrer">{f.label} ↗</a><small>{f.folder}　{f.size}</small></div>)}
    </section></div>}
  </div>
}
createRoot(document.querySelector('#root')).render(<ReactFlowProvider><App/></ReactFlowProvider>);
