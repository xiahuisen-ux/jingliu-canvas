// Conversations belong to a project and shot. Polling never rebuilds live editors.
const shotChatJobs=new Map(),shotChatDrafts=new Map(),shotChatPolling=new Set();
function shotChatKey(pid,id){return pid+'/'+id}
function shotChatCard(id){return $$('#shotsGrid [data-shot-id]').find(c=>c.dataset.shotId===id)}
function renderShotChat(card){
  const id=card.dataset.shotId,s=project.shots.find(s=>s.id===id),key=shotChatKey(project.id,id),j=shotChatJobs.get(key),box=card.querySelector('[data-shot-chat]');if(!s||!box)return;
  const busy=j&&['queued','running'].includes(j.status);
  if(!box.querySelector('[data-shot-chat-input]')){
    box.innerHTML=`<header><h3>DeepSeek · 本段编剧</h3><button class="ghost" type="button" data-shot-chat-settings>模型设置</button></header><p class="muted">视频生成期间也可讨论、改稿并自动生成 H3 英文。读取左侧文字与已保存的参考、时长；只提问时不另改剧情。</p><div class="shot-chat-messages" data-shot-chat-messages></div><p class="muted" data-shot-chat-status aria-live="polite"></p><div data-shot-chat-result hidden></div><label>讨论或修改要求<textarea data-shot-chat-input rows="4" placeholder="例如：改为女生侧后方过肩镜头，缓慢推近男生，保留对白与时间。"></textarea></label><button class="primary" type="button" data-shot-chat-send>发送 · 改稿并翻译</button><small>⌘ / Ctrl + Enter 发送。已开跑的视频继续使用提交时的稿件，新稿用于下次生成；录音不会自动重制。</small>`;
    const input=box.querySelector('[data-shot-chat-input]');input.value=shotChatDrafts.get(key)||'';
    input.oninput=()=>shotChatDrafts.set(key,input.value);
    input.onkeydown=e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();submitShotChat(card)}};
    box.querySelector('[data-shot-chat-send]').onclick=()=>submitShotChat(card);
    box.querySelector('[data-shot-chat-settings]').onclick=()=>$('#openTextModel').click();
  }
  const messages=[...(s.shot_chat?.messages||[])];if(busy&&j.submittedMessage)messages.push({role:'user',content:j.submittedMessage});
  const list=box.querySelector('[data-shot-chat-messages]'),bottom=list.scrollHeight-list.scrollTop-list.clientHeight<40;
  setStableHTML(list,messages.length?messages.map(m=>`<article class="shot-chat-message ${m.role==='user'?'user':'assistant'}"><strong>${m.role==='user'?'你':'DeepSeek'}</strong><div>${esc(m.content)}</div></article>`).join(''):'<p class="muted">先讨论这一段，或直接说出你想改的动作、表情和运镜。</p>');
  if(bottom)list.scrollTop=list.scrollHeight;
  box.querySelector('[data-shot-chat-send]').disabled=!!busy;
  setStableText(box.querySelector('[data-shot-chat-status]'),busy?j.message:j?.status==='error'||j?.status==='cancelled'?j.message:s.shot_chat_audio_notice||'改稿保留旧版本；可唯一对应的 02 场次会同步更新。');
}
async function submitShotChat(card){
  const pid=project.id,id=card.dataset.shotId,key=shotChatKey(pid,id),input=card.querySelector('[data-shot-chat-input]'),message=input.value.trim();
  if(!message||['queued','running'].includes(shotChatJobs.get(key)?.status))return;
  shotChatJobs.set(key,{status:'queued',message:'正在提交本段文字…'});renderShotChat(card);
  try{
    if(!(await api('/api/capabilities')).shot_chat_parallel)throw new Error('并行改稿服务尚未更新，请等待当前生成结束后更新工作台');
    if($('#scriptEditor').value.trim()&&JSON.stringify(JSON.parse($('#scriptEditor').value))!==JSON.stringify(project.script))throw new Error('02 剧本还有未保存的修改，请先保存后再让 DeepSeek 读取');
    if(project.id!==pid)throw new Error('工程已切换，未发送对话');
    const baseline=card.querySelector('[data-complete-prompt]').value;
    const shot=project.shots.find(s=>s.id===id),draft=parseShotPrompt(baseline);
    draft.motion_prompt=draft.motion_prompt??card.querySelector('[data-english-prompt]').value;
    const base=Object.fromEntries(['description','camera','dialogue','motion_prompt'].map(k=>[k,shot[k]||'']));
    const job=await api(`/api/projects/${pid}/action`,{method:'POST',body:JSON.stringify({action:'shot_chat',shot_id:id,message,draft,base,revision:shot.shot_chat?.revision||0})});
    Object.assign(job,{submittedMessage:message,baseline});shotChatJobs.set(key,job);
    if(input.value.trim()===message){input.value='';shotChatDrafts.set(key,'');}
    renderShotChat(card);pollShotChat(job);
  }catch(e){shotChatJobs.set(key,{status:'error',message:e.message});if(project.id===pid)renderShotChat(card);toast(e.message)}
}
function applyShotChatResult(card,shot,job){
  const editor=card.querySelector('[data-complete-prompt]'),result=card.querySelector('[data-shot-chat-result]');
  if(!job.shot_changed)return;
  const apply=()=>{editor.value=shotFullPromptText(shot);card.querySelector('[data-english-prompt]').value=shot.motion_prompt||'';result.hidden=true;updateH3TranslationStatus(card);updateShotReferencePreview(card,true)};
  if(job.baseline!==undefined&&editor.value===job.baseline){apply();return;}
  // An editor may contain new unsaved work or may have been restored after reload.
  if(editor.value===shotFullPromptText(shot))return;
  result.hidden=false;result.innerHTML=`<p class="reference-warning">改稿已保存。当前输入有新草稿，已保留；可查看并采用改稿结果。</p><details><summary>查看本次改稿</summary><pre>${esc(shotFullPromptText(shot))}</pre></details><button class="ghost" data-adopt-shot-chat>将本次改稿填入左侧</button>`;
  result.querySelector('[data-adopt-shot-chat]').onclick=apply;
}
async function pollShotChat(job){
  const pid=job.project_id,key=shotChatKey(pid,job.shot_id);if(shotChatPolling.has(key))return;shotChatPolling.add(key);
  let again=true;
  try{
    const j=await api(`/api/jobs/${job.id}`);Object.assign(j,{baseline:job.baseline,submittedMessage:job.submittedMessage});shotChatJobs.set(key,j);
    if(['done','error','cancelled'].includes(j.status)){
      again=false;
      if(project?.id===pid){const fresh=await api(`/api/projects/${pid}`);if(project?.id===pid){let cleanScript=false;try{cleanScript=JSON.stringify(JSON.parse($('#scriptEditor').value))===JSON.stringify(project.script)}catch{}project=fresh;if(cleanScript)renderScript();else if(j.script_synced)toast('02 已有改稿结果，但你正在编辑的 02 草稿已保留，请核对后保存');const card=shotChatCard(job.shot_id);if(card){if(j.status==='done')applyShotChatResult(card,fresh.shots.find(s=>s.id===job.shot_id),j);else if(!card.querySelector('[data-shot-chat-input]').value&&job.submittedMessage){card.querySelector('[data-shot-chat-input]').value=job.submittedMessage;shotChatDrafts.set(key,job.submittedMessage);}renderShotChat(card);}renderVideos();renderInspector();syncShotStatus();}}
    }else if(project?.id===pid){const card=shotChatCard(job.shot_id);if(card)renderShotChat(card);}
  }catch(e){
    if(e.message==='任务不存在'){again=false;shotChatJobs.set(key,{status:'error',message:'服务已重启，请检查已保存的剧本后重试'});if(project?.id===pid&&shotChatCard(job.shot_id))renderShotChat(shotChatCard(job.shot_id));}
    else again=true;
  }finally{shotChatPolling.delete(key);}
  if(again)setTimeout(()=>pollShotChat(job),1500);
}
function bindShotChats(){
  for(const card of $$('#shotsGrid [data-shot-id]'))renderShotChat(card);
  const pid=project.id;
  api('/api/runtime').then(r=>{for(const job of r.jobs.filter(j=>j.project_id===pid&&j.action==='shot_chat')){const key=shotChatKey(pid,job.shot_id);if(!shotChatJobs.has(key)){shotChatJobs.set(key,job);pollShotChat(job);}}}).catch(()=>{});
}
