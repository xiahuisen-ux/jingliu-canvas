// Project-owned conversation, asynchronous jobs and explicit draft import.
const creativeJobs=new Map(),creativeInputs=new Map();
let creativeDisplayedProject=null,creativeSubmitting=false;
function creativeKey(){return project?.id||'new'}
function refreshCreativeModel(){if($('#creativeModelName'))setStableText($('#creativeModelName'),textModelLabel())}
function draftPreview(d){
  if(!d)return '<p class="creative-placeholder">从一个想法开始。<br>聊好人物、故事和时长后，<br>在这里整理成完整分镜。</p>';
  const s=d.script;
  return `<div class="creative-scene-summary"><strong>${s.duration_seconds} 秒 · ${s.scenes.length} 段</strong><p>${esc(s.synopsis)}</p></div><div class="creative-draft-scroll"><details><summary>创作假设 · 人物 · 场景方向</summary><pre>${esc([s.assumptions,s.character_bible,s.spatial_bible].join('\n\n'))}</pre></details>${s.scenes.map(x=>`<details><summary>${x.scene}. ${esc(x.title)} · ${x.timeline_start}–${x.timeline_end}秒</summary><pre>${esc(x.action)}\n\n对白：${esc(x.dialogue)}\n镜头：${esc(x.camera)}\n声音：${esc(x.sound)}</pre><details><summary>英文 H3 提示词</summary><pre>${esc(x.video_prompt)}</pre></details></details>`).join('')}</div>`;
}
function renderCreativeChat(){
  const key=creativeKey(),w=project?.creative_workspace||{},job=creativeJobs.get(key),busy=job&&['queued','running'].includes(job.status);
  if(creativeDisplayedProject!==key){if(creativeDisplayedProject)creativeInputs.set(creativeDisplayedProject,$('#creativeInput').value);$('#creativeInput').value=creativeInputs.get(key)||'';creativeDisplayedProject=key;}
  refreshCreativeModel();
  const box=$('#creativeMessages'),atBottom=box.scrollHeight-box.clientHeight-box.scrollTop<48;
  const messages=[...(w.messages||[])];if(busy&&job.submittedMessage)messages.push({role:'user',content:job.submittedMessage});
  if(messages.length){renderKeyedHTML(box,messages.map((m,i)=>({key:String(i),html:`<article class="creative-message ${m.role==='user'?'user':'assistant'}"><header>${m.role==='user'?'你':esc(m.model||'编剧助手')}</header><div class="creative-content">${esc(m.content)}</div></article>`})));}
  else setStableHTML(box,`<div class="creative-welcome"><span class="eyebrow">从想法到镜头</span><h2>这次，我们拍一个怎样的故事？</h2><p>可以先聊剧情，也可以直接发来剧本。我会和你一起安排人物表情、对白节奏、逐秒动作和运镜。</p><p>按 H3 官方格式整理英文提示词；中文剧本供你审阅和修改。</p><div class="creative-suggestions"><button class="ghost" data-creative-example="我想拍一支30秒短片，请先和我讨论故事方向。">从新故事开始</button><button class="ghost" data-creative-example="请先阅读本工程已保存的剧本，帮我检查对白、动作与运镜安排，先给修改建议。">讨论已有剧本</button></div></div>`);
  $$('[data-creative-example]').forEach(b=>b.onclick=()=>{$('#creativeInput').value=b.dataset.creativeExample;$('#creativeInput').focus()});
  if(atBottom)box.scrollTop=box.scrollHeight;
  setStableHTML($('#creativeDraftPreview'),draftPreview(w.draft));
  const stale=w.draft&&w.draft.conversation_revision!==w.revision;
  const draftPending=busy&&job.action==='creative_draft';
  $('#creativeSend').disabled=!!busy;$('#creativeBuild').disabled=!!busy;$('#creativeImport').disabled=!!busy||!w.draft||!!stale||!!w.draft.imported_at;
  $('#creativeStop').hidden=!busy;setStableText($('#creativeBuild'),draftPending?'正在整理…':'整理剧本分镜');
  setStableText($('#creativeStatus'),busy?job.message:job&&job.status!=='done'?job.message:'讨论记录随工程保存');
  setStableText($('#creativeImportNote'),w.draft?.imported_at?'此草稿已导入 02 剧本，可继续讨论后整理新版本。':stale?'有新的讨论，请重新整理后再导入。':project?.script?'导入会更新 02 剧本并保留原版本；旧视频和素材保留，已有任务需重新拆分。':'导入前可继续讨论修改；不会自动生成视频。');
}
async function submitCreative(action){
  const input=$('#creativeInput'),message=input.value.trim();
  if(action==='creative_chat'&&!message)return;
  if(creativeSubmitting||['queued','running'].includes(creativeJobs.get(creativeKey())?.status))return;
  creativeSubmitting=true;
  $('#creativeSend').disabled=true;$('#creativeBuild').disabled=true;
  let pid=project?.id;
  try{
    if(!project){if(!message)throw new Error('请先输入故事想法');const p=await api('/api/projects',{method:'POST',body:JSON.stringify({title:message.slice(0,24),brief:''})});await openProject(p.id);pid=p.id;input.value=message;}
    if($('#briefInput').value!==(project.brief||''))throw new Error('原始需求有未保存修改，请先点“保存原始需求”');
    const revision=project.creative_workspace?.revision||0;
    creativeJobs.set(pid,{pending:true,status:'queued',message:'提交中…'});
    const job=await api(`/api/projects/${pid}/action`,{method:'POST',body:JSON.stringify({action,message,revision})});
    job.submittedMessage=message;creativeJobs.set(pid,job);creativeInputs.set(pid,'');if(project?.id===pid&&input.value===message)input.value='';
    pollCreativeJob(job);renderCreativeChat();
  }catch(e){if(pid)creativeJobs.delete(pid);toast(e.message);renderCreativeChat()}finally{creativeSubmitting=false;}
}
async function pollCreativeJob(job){
  const pid=job.project_id;
  try{
    const j=await api(`/api/jobs/${job.id}`);j.submittedMessage=job.submittedMessage;creativeJobs.set(pid,j);
    if(['done','error','cancelled'].includes(j.status)){
      if(project?.id===pid){const p=await api(`/api/projects/${pid}`);if(project?.id===pid){project.creative_workspace=p.creative_workspace;if(j.status!=='done'&&!$('#creativeInput').value&&job.submittedMessage){$('#creativeInput').value=job.submittedMessage;creativeInputs.set(pid,job.submittedMessage);}renderCreativeChat();}}
      if(j.status!=='done')toast(j.message);await refreshProjects();return;
    }
    if(project?.id===pid)renderCreativeChat();
  }catch(e){if(e.message==='任务不存在'){creativeJobs.set(pid,{status:'error',message:'服务已重启，请检查已有记录后重试'});if(project?.id===pid)renderCreativeChat();return;}if(project?.id===pid)setStableText($('#creativeStatus'),'连接中断，正在重连；后台任务继续运行');}
  setTimeout(()=>pollCreativeJob(job),1500);
}
async function resumeCreativeJob(){
  if(!project)return;const pid=project.id;
  try{const r=await api('/api/runtime');const job=r.jobs.find(j=>j.project_id===pid&&['creative_chat','creative_draft'].includes(j.action));if(job&&!creativeJobs.has(pid)){creativeJobs.set(pid,job);pollCreativeJob(job);}if(project?.id===pid)renderCreativeChat();}catch{}
}
function bindCreativeChat(){
  $('#creativeSend').onclick=()=>submitCreative('creative_chat');$('#creativeBuild').onclick=()=>submitCreative('creative_draft');
  $('#creativeInput').oninput=()=>creativeInputs.set(creativeKey(),$('#creativeInput').value);
  $('#creativeInput').onkeydown=e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();submitCreative('creative_chat')}};
  $('#creativeModel').onclick=()=>$('#openTextModel').click();
  $('#creativeStop').onclick=async()=>{try{await api('/api/stop',{method:'POST',body:'{}'});}catch(e){toast(e.message)}};
  $('#creativeSaveBrief').onclick=async()=>{if(!project){toast('先发一条消息或新建工程');return}const pid=project.id;try{const p=await api(`/api/projects/${pid}/save`,{method:'POST',body:JSON.stringify({brief:$('#briefInput').value})});if(project?.id===pid)project.brief=p.brief;toast('原始需求已保存')}catch(e){toast(e.message)}};
  $('#creativeImport').onclick=async()=>{
    const pid=project?.id,d=project?.creative_workspace?.draft;if(!pid||!d)return;
    if(project.script&&!confirm('将本草稿导入 02 剧本？原剧本保留历史，已有视频与素材保留；后续生成需要重新拆分任务。'))return;
    $('#creativeImport').disabled=true;
    try{const p=await api(`/api/projects/${pid}/creative/import`,{method:'POST',body:JSON.stringify({draft_id:d.id})});if(project?.id===pid){project=p;renderScript();renderInspector();renderCreativeChat();showStage('script');}await refreshProjects();toast('已导入 02 剧本');}catch(e){toast(e.message);renderCreativeChat()}
  };
}
