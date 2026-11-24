import React,{useRef,useState,useEffect} from 'react';
import {createPortal} from 'react-dom';
import {Handle,Position} from '@xyflow/react';
const choices=[['image','▧','图片'],['video','▷','视频'],['audio','♫','音频'],['character','♙','角色']];
export function SourcePort({n,c,type}){
 const [anchor,setAnchor]=useState({left:12,top:12});
 const down=useRef(null),open=c.portMenu===n.id;
 const toggle=e=>{const rect=e.currentTarget.getBoundingClientRect();setAnchor({left:Math.max(12,Math.min(rect.right+12,window.innerWidth-252)),top:Math.max(12,Math.min(rect.top-24,window.innerHeight-226))});c.setPortMenu((down.current?.open??open)?null:n.id)};
 useEffect(()=>{if(!open)return;const close=e=>{if(!e.target.closest('.source-menu,.source-port'))c.setPortMenu(null)};document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close)},[open]);
 return <>
  <Handle type="source" position={Position.Right} id={type} className="source-port" aria-label={`${n.item.name||n.item.title}输出接口`} role="button" tabIndex={0} aria-haspopup="menu" aria-expanded={open}
   onPointerDown={e=>{down.current={x:e.clientX,y:e.clientY,open};c.setPortMenu(null)}}
   onClick={e=>{e.stopPropagation();if(!down.current||Math.hypot(e.clientX-down.current.x,e.clientY-down.current.y)<6)toggle(e);down.current=null}}
   onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();toggle(e)}}}/>
  {open&&createPortal(<div style={anchor} className="source-menu nodrag nopan nowheel" onPointerDown={e=>e.stopPropagation()} onClick={e=>e.stopPropagation()}>
   <div className="source-menu-title">引用该节点生成</div><div role="menu" aria-label="引用该节点生成">{choices.map(([kind,icon,label])=><button key={kind} role="menuitem" disabled={c.mutating} onClick={()=>{c.setPortMenu(null);c.derive(n,kind)}}><span>{icon}</span>{label}</button>)}</div>
  </div>,document.body)}
 </>;
}
