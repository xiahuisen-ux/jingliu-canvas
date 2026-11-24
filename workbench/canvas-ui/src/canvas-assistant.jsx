import React,{useState,useEffect,useRef} from 'react';
const names={audio_to_video:'音频转黑屏视频',create_node:'新建节点',edit_node:'修改信息',derive_node:'创建关联节点',connect_reference:'连接参考',remove_reference:'取消参考',copy_node:'复制节点',delete_node:'移出画布',restore_node:'恢复节点',extract_frame:'抽帧',trim_video:'截取片段',generate_image:'生成图片',generate_video:'生成视频',upscale:'提升分辨率',save_library:'保存资产',list_library:'读取资产库',import_library:'导入资产'};
const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}};
const put=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value))}catch{}};
export function CanvasAssistant({project,open,onClose,api,items,selected,onPrepare,onJob,onUpdate,onLocate,notify,locked}){
 const pid=project?.id,key='mirrorflow-assistant-draft:'+pid;
 const [models,setModels]=useState([]),[mode,setMode]=useState(()=>read('mirrorflow-assistant-model','configured')),[draft,setDraft]=useState(()=>read(key,'')),[refs,setRefs]=useState([]),[data,setData]=useState(null),[sending,setSending]=useState(false),[error,setError]=useState(''),[pick,setPick]=useState(false),[pendingJob,setPendingJob]=useState(null);
 const callbacks=useRef({}),alive=useRef(true),list=useRef(),version=useRef(null),fetching=useRef(false),sendingRef=useRef(false);callbacks.current={onUpdate,notify,onPrepare,onJob,onLocate};
 const endpoint='/api/projects/'+encodeURIComponent(pid)+'/canvas-assistant';
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
 const refresh=async()=>{if(!pid||fetching.current)return;fetching.current=true;try{const value=await api(endpoint);if(!alive.current)return;setData(value);setError('');if(version.current!==null&&version.current!==value.revision)callbacks.current.onUpdate(pid);version.current=value.revision;if(value.turns.some(t=>t.job_id===pendingJob))setPendingJob(null)}catch(e){if(alive.current)setError(e.message)}finally{fetching.current=false}};
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{if(!pid||!open)return;refreshRef.current();const timer=setInterval(()=>refreshRef.current(),1800);return()=>clearInterval(timer)},[pid,open]);
 useEffect(()=>{if(!open)return;let live=true;api('/api/canvas-assistant/models').then(value=>{if(live)setModels(value)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[open]);
 useEffect(()=>{list.current?.scrollTo({top:list.current.scrollHeight,behavior:'smooth'})},[data?.revision,sending]);
 const active=data?.turns.some(t=>['running','queued'].includes(t.status))||pendingJob;
 const add=rows=>{const valid=rows.filter(x=>x.path);if(!valid.length){notify('先选择已有图片、视频或音频的节点，再引用素材');return}setRefs(old=>[...new Map([...old,...valid].map(x=>[x.id,x])).values()].slice(0,4));setPick(false)};
 const change=value=>{setDraft(value);put(key,value)};
 const send=async e=>{e.preventDefault();if(sendingRef.current||active||!draft.trim()||!data)return;sendingRef.current=true;setSending(true);setError('');try{await callbacks.current.onPrepare();if(!alive.current)return;const j=await api('/api/projects/'+encodeURIComponent(pid)+'/action',{action:'canvas_assistant',message:draft,mode,revision:data.revision,selected_nodes:selected,attachments:refs.map(r=>({node_id:r.id,path:r.path}))});if(!alive.current)return;change('');setRefs([]);setPendingJob(j.id);callbacks.current.onJob(j);await refreshRef.current()}catch(e){if(alive.current)setError(e.message)}finally{sendingRef.current=false;if(alive.current)setSending(false)}};
 const current=models.find(x=>x.id===mode);
 return <aside className="canvas-assistant" aria-label="画布助手" hidden={!open}>
  <header><div><span className="assistant-mark">✳</span><strong>画布助手</strong><small>从想法到画面</small></div><button aria-label="收起画布助手" onClick={onClose}>×</button></header>
  <div className="assistant-model"><label htmlFor="assistant-model-select">对话模型</label><select id="assistant-model-select" value={mode} disabled={sending||!!active} onChange={e=>{setMode(e.target.value);put('mirrorflow-assistant-model',e.target.value)}}>{!models.length&&<option value={mode}>正在读取模型…</option>}{models.map(m=><option key={m.id} value={m.id} disabled={!m.ready}>{m.label} · {m.name}{m.ready?'':' · 未就绪'}</option>)}</select><small>{mode==='local_vision'?'本机看图 · 视频首 / 中 / 尾帧 · 音频仅元数据':mode==='local_text'?'本机文字 · 读取节点信息与提示词':'使用已配置文字模型 · 发送画布文字和对话'}</small></div>
  <div className="assistant-transcript" ref={list} role="log" aria-label="画布对话记录">
   {!data?.turns.length&&<div className="assistant-welcome"><span>✧</span><h2>把下一步，交给对话。</h2><p>我可以读取画布，帮你创建节点、连接参考、修改提示词，调用抽帧、截取和生成工具。</p><div>{['新建一个雨夜街道场景节点，先写提示词','把选中的视频提取尾帧，保留人物和场景参考','查看资产库中有哪些可用素材'].map(text=><button key={text} onClick={()=>change(text)}>{text}<span>↗</span></button>)}</div><small>引用素材后，可切换本地多模态来分析画面。</small></div>}
   {data?.turns.map(turn=><article className="assistant-turn" key={turn.id}><div className="assistant-user"><p>{turn.message}</p>{turn.attachments?.length>0&&<small>引用 {turn.attachments.length} 个素材 · {turn.mode==='local_vision'?'多模态':'文字'}</small>}</div>{turn.events.map((ev,i)=><details className={'assistant-tool '+ev.status} key={i}><summary><span>{ev.status==='done'?'✓':ev.status==='error'?'!':'◌'}</span>{names[ev.tool]||ev.tool}<small>{ev.status==='done'?'已完成':ev.status==='error'?'未完成':'执行中'}</small></summary><pre>{JSON.stringify(ev.arguments,null,2)}</pre>{ev.error&&<p>{ev.error}</p>}{ev.status==='done'&&ev.result?.node_id&&<button onClick={()=>callbacks.current.onLocate(ev.result.node_id)}>在画布中查看 ↗</button>}</details>)}{turn.response&&<div className={'assistant-answer '+turn.status}><span>✳</span><p>{turn.response}</p></div>}{['running','queued'].includes(turn.status)&&<p className="assistant-thinking">◌ 正在处理，可在画布任务条中停止…</p>}</article>)}
   {(sending||pendingJob)&&<p className="assistant-thinking">◌ 正在提交并连接模型…</p>}
  </div>
  <form className="assistant-compose" onSubmit={send}>
   {error&&<div className="assistant-error" role="alert">{error}<button type="button" onClick={()=>refreshRef.current()}>刷新对话</button></div>}
   {!!selected.length&&<small className="assistant-selection">已选中 {selected.length} 个画布节点 · 发送前保存节点草稿</small>}
   {!!refs.length&&<div className="assistant-refs">{refs.map(r=><div key={r.id}>{r.kind==='image'?<img src={r.url} alt=""/>:<b>{r.kind==='video'?'▷':'♫'}</b>}<span>{r.name}</span><button type="button" aria-label={'取消助手引用 '+r.name} onClick={()=>setRefs(old=>old.filter(x=>x.id!==r.id))}>×</button></div>)}</div>}
   {pick&&<div className="assistant-picker"><strong>引用画布素材 · 最多4个</strong>{items.filter(x=>x.path).map(x=><button type="button" key={x.id} onClick={()=>add([x])}>{x.kind==='image'?'▧':x.kind==='video'?'▷':'♫'} {x.name}</button>)}{!items.some(x=>x.path)&&<p>请先在画布导入素材。</p>}</div>}
   <textarea aria-label="给画布助手的要求" placeholder="例如：把这个视频截取 1–4 秒，再提取尾帧…" maxLength={8000} value={draft} onChange={e=>change(e.target.value)} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form.requestSubmit()}}}/>
   <div className="assistant-compose-actions"><button type="button" title="引用画布素材" onClick={()=>setPick(!pick)}>＋ 素材</button><button type="button" onClick={()=>add(items.filter(x=>selected.includes(x.id)))}>引用选中</button><button className="primary" type="submit" disabled={!pid||!data||!draft.trim()||sending||!!active||locked||!current?.ready}>发送 ↑</button></div>
   <small>⌘ / Ctrl + Enter 发送 · 操作结果保留在画布，删除可撤销</small>
  </form>
 </aside>
}
