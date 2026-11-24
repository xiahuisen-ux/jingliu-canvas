import React,{useState,useEffect} from 'react';
const appearanceName=v=>v.appearance_name||(v.canvas_status&&v.canvas_status!=='初始'?v.canvas_status:'基础形象');
const libraryMedia=(role,file)=>`/character-library-media/${role}/${file}`;
export function CharacterPanel({n,c}){
 const v=c.values(n),path=c.preview(n),[roleId,setRoleId]=useState(n.item.character_library?.role_id||'');
 useEffect(()=>{if(n.item.character_library?.role_id)setRoleId(n.item.character_library.role_id)},[n.item.character_library?.role_id]);
 const rename=(name,appearance)=>{c.editDraft(n,'character_name',name);c.editDraft(n,'appearance_name',appearance);c.editDraft(n,'name',name+(appearance&&appearance!=='基础形象'?' · '+appearance:''))};
 const voiceMode=v.voice_mode||'text';
 return <div className="character-workspace">
  <section className="character-main-image"><span className="eyebrow">主图</span>{path?<img src={c.media(path)} alt={`${v.character_name||v.name}主图`}/>:<div className="character-placeholder">上传主图，建立角色形象</div>}<strong>{v.character_name||v.name}</strong><span>{appearanceName(v)}</span><button onClick={()=>c.chooseFile(n,'result')}>↥ 上传主图</button><button onClick={()=>{c.setCharacter(null);c.setViewer(n.id)}}>编辑图片与生成要求 ↗</button></section>
  <section className="character-profile">
   <label>角色名称<input aria-label="角色名称" value={v.character_name||v.name||''} onChange={e=>rename(e.target.value,appearanceName(v))}/></label>
   <label>形象名称<input aria-label="形象名称" value={appearanceName(v)} onChange={e=>rename(v.character_name||v.name,e.target.value)}/></label>
   <label>角色信息<textarea aria-label="角色信息" rows={3} placeholder="身份、性格与背景…" value={v.canvas_identity||''} onChange={e=>c.editDraft(n,'canvas_identity',e.target.value)}/></label>
   <fieldset className={'character-voice '+(voiceMode==='text'?'active':'')}><label className="voice-mode"><input type="radio" name="character-voice-mode" checked={voiceMode==='text'} onChange={()=>c.editDraft(n,'voice_mode','text')}/>文字音色</label><textarea aria-label="角色声线描述" rows={4} placeholder="例如：中低音，温暖略沙哑，语速舒缓，普通话…" value={v.voice_prompt||''} onChange={e=>c.editDraft(n,'voice_prompt',e.target.value)}/></fieldset>
   <fieldset className={'character-voice '+(voiceMode==='audio'?'active':'')}><label className="voice-mode"><input type="radio" name="character-voice-mode" checked={voiceMode==='audio'} onChange={()=>c.editDraft(n,'voice_mode','audio')}/>音频音色</label><button onClick={()=>c.uploadVoice(n)}>↥ 上传参考音频</button>{v.voice_audio&&<><audio controls preload="metadata" src={c.media(v.voice_audio)}/><button className="text-button" onClick={()=>{c.editDraft(n,'voice_audio','');c.editDraft(n,'voice_mode','text')}}>解除音频绑定</button></>}<small>使用2–15秒的清晰人声。连接到全能参考视频时带入音色；已绑定表演原音的镜头优先沿用原音。</small></fieldset>
   <label>存入角色库<select aria-label="选择角色库归属" value={roleId} onChange={e=>setRoleId(e.target.value)}><option value="">创建新角色</option>{c.library.map(role=><option value={role.id} key={role.id}>{role.name}</option>)}</select></label>
   <div className="character-save"><button disabled={c.mutating} onClick={()=>c.save(n)}>保存角色信息</button><button className="primary" disabled={c.mutating||!path} onClick={()=>c.saveToLibrary(n,roleId)}>保存到角色库</button></div>
   {c.drafts[n.id]&&<div className="draft-line">草稿已暂存 · 点击保存后应用</div>}
  </section>
 </div>;
}
export function CharacterLibrary({c}){
 return <div className="character-library"><p>保存的主图和参考音频保存在本机，可添加到任意工程。</p>{!c.library.length&&<div className="library-empty">角色库还是空的。打开人物的“角色信息”，完成后保存到这里。</div>}{c.library.map(role=><section key={role.id}><h3>{role.name}</h3><div className="library-appearances">{role.appearances.map(a=><article key={a.id}><img src={libraryMedia(role.id,a.image)} alt={role.name+' · '+a.name}/><strong>{a.name}</strong><small>{a.profile.voice_mode==='audio'?'参考音频音色':a.profile.voice_prompt?'文字音色':'未设置音色'}</small><button disabled={c.mutating} onClick={()=>c.useLibrary(role.id,a.id)}>添加到画布</button></article>)}</div></section>)}</div>;
}
export function CharacterVariant({n,c}){
 const [name,setName]=useState('新换装'),[prompt,setPrompt]=useState('');
 return <form className="character-variant" onSubmit={e=>{e.preventDefault();c.characterVariant(n,name,prompt)}}><p>以当前预览主图为参考，建立独立的关联形象；沿用角色身份、声线与参考音频。</p><label>形象名称<input aria-label="关联形象名称" required maxLength={100} value={name} onChange={e=>setName(e.target.value)} placeholder="雨夜外套 / 舞台造型 / 受伤状态"/></label><label>换装或状态要求<textarea aria-label="关联形象要求" required rows={5} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="保留脸部与体型，换上深绿色演出西装，手持萨克斯…"/></label><button className="primary wide" disabled={c.mutating} type="submit">＋ 创建关联形象</button><small>创建后在新节点点击“生成图片”。</small></form>;
}
