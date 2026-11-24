// One human-readable document, separate reviewable proposals, and scoped drafts.
const scriptTopFields=[['synopsis','故事梗概'],['duration_seconds','全片时长（秒）'],['visual_style','画面风格'],['required_aspect','画幅'],['dialogue_policy','对白约定'],['assumptions','创作假设'],['character_bible','人物与声音设定'],['spatial_bible','空间与连续性设定']];
const scriptSceneFields=[['title','段落标题'],['duration_seconds','时长（秒）'],['location','场景'],['time','时间'],['opening','起始构图'],['action','剧情与逐秒动作'],['camera','镜头安排'],['dialogue','对白与歌词'],['sound','声音'],['ending','结束接续'],['inherit_previous_frame','继承上一段尾帧（是／否）']];
const scriptEditors=new Map(),scriptJobs=new Map(),scriptInputs=new Map();
let scriptDisplayed=null,scriptSubmitting=false,scriptWriting=false;
function scriptCopy(x){return x==null?x:JSON.parse(JSON.stringify(x))}
function scriptValue(s,k){return k==='inherit_previous_frame'?(s[k]?'是':'否'):String(s[k]??'')}
function scriptSections(s){
  const sections=scriptTopFields.filter(([key])=>['synopsis','duration_seconds'].includes(key)||s?.[key]).map(([key,label])=>({heading:`【${label}】`,object:s,key}));
  (s?.scenes||[]).forEach((scene,i)=>scriptSceneFields.filter(([key])=>!['opening','ending'].includes(key)||scene[key]).forEach(([key,label])=>sections.push({heading:`【第 ${i+1} 段 · ${label}】`,object:scene,key,index:i})));
  (s?.scenes||[]).forEach((scene,i)=>sections.push({heading:`【第 ${i+1} 段 · 英文 H3 提示词】`,object:scene,key:'video_prompt',index:i}));
  return sections;
}
function scriptDocumentText(script){if(!script)return '';return scriptSections(script).map(x=>x.heading+'\n'+scriptValue(x.object,x.key)).join('\n\n')}
function parseScriptDocument(text,base){
  if(!base)throw new Error('请先从 01 创作对话导入剧本');
  if(text===scriptDocumentText(base))return scriptCopy(base);
  const sections=scriptSections(base),matches=[...text.matchAll(/^【[^\n]+】\s*$/gm)];
  if(matches.length!==sections.length||matches.some((m,i)=>m[0].trim()!==sections[i].heading))throw new Error('请保留剧本中的【分区标题】与顺序；重排段落可交给右侧 DeepSeek');
  if(text.slice(0,matches[0].index).trim())throw new Error('请把新增正文写在对应【分区标题】下');
  const value=scriptCopy(base);let durationChanged=false;
  sections.forEach((s,i)=>{
    let v=text.slice(matches[i].index+matches[i][0].length,i+1<matches.length?matches[i+1].index:text.length).trim();
    if(v===scriptValue(s.object,s.key).trim())return;
    const target=s.index==null?value:value.scenes[s.index];
    if(s.key==='duration_seconds'){
      if(!/^\d+$/.test(v))throw new Error(s.heading+'需要填写整数秒数');
      v=Number(v);if(v<(s.index==null?5:5)||v>(s.index==null?300:15))throw new Error(s.heading+'超出允许时长');durationChanged=true;
    }
    if(s.key==='inherit_previous_frame'){if(!['是','否'].includes(v))throw new Error(s.heading+'只填写是或否');v=v==='是'}
    target[s.key]=v;
    if(s.index!=null){delete target.beats;delete value.creative_h3_plan;}
  });
  if(durationChanged){if(value.scenes.reduce((a,s)=>a+Number(s.duration_seconds||0),0)!==value.duration_seconds)throw new Error('各段时长之和必须等于全片时长');let t=0;for(const s of value.scenes){s.timeline_start=t;t+=s.duration_seconds;s.timeline_end=t;}}
  return value;
}
function scriptState(){return scriptEditors.get(project?.id)}
function captureScriptEditor(){
  const state=scriptState();if(!state)return null;
  state.text=$('#scriptDocument').value;state.dirty=state.text!==scriptDocumentText(state.base);
  try{const script=parseScriptDocument(state.text,state.base);$('#scriptEditor').value=JSON.stringify(script,null,2);state.error='';return script}
  catch(e){state.error=e.message;$('#scriptEditor').value=state.text;throw e}
}
function renderScriptWorkspace(force=false){
  const pid=project?.id;if(!pid)return;
  if(scriptDisplayed&&scriptDisplayed!==pid){scriptInputs.set(scriptDisplayed,$('#scriptChatInput').value);const previous=scriptEditors.get(scriptDisplayed);if(previous){previous.text=$('#scriptDocument').value;previous.dirty=previous.text!==scriptDocumentText(previous.base)}}
  let state=scriptEditors.get(pid);
  if(force||!state||(!state.dirty&&JSON.stringify(state.base)!==JSON.stringify(project.script))){state={base:scriptCopy(project.script),text:scriptDocumentText(project.script),dirty:false};scriptEditors.set(pid,state)}
  if(scriptDisplayed!==pid){$('#scriptChatInput').value=scriptInputs.get(pid)||'';scriptDisplayed=pid;}
  if($('#scriptDocument').value!==state.text)$('#scriptDocument').value=state.text;
  $('#scriptDocument').disabled=!state.base;
  try{captureScriptEditor()}catch{}
  updateScriptWorkspaceState();renderScriptDiscussion();updateDurationHints();
}
function updateScriptWorkspaceState(){
  const state=scriptState(),s=state?.base;
  setStableText($('#scriptWorkspaceSummary'),s?`${s.duration_seconds||'—'} 秒 · ${s.scenes?.length||0} 段`:'等待导入剧本');
  setStableText($('#scriptEditState'),state?.error||(!s?'先从 01 导入剧本':state?.dirty?'有未保存修改':'已保存'));
  $('#scriptEditState').classList.toggle('is-dirty',!!state?.dirty);
  setStableText($('#scriptExportNote'),project?.audio_timeline?'已绑定录音：分段时长不变可保留；修改对白不会自动重录。提取后到 03 选择或生成参考图。':'提取后进入 03 选择或生成参考图；输出任务后手动生成视频。');
}
function renderScriptDiscussion(){
  if(!project)return;
  const w=project.script_workspace||{},j=scriptJobs.get(project.id),busy=!!(scriptSubmitting||j&&['queued','running'].includes(j.status)),draft=w.draft;
  setStableText($('#scriptModelName'),typeof textModelLabel==='function'?textModelLabel():'DeepSeek API');
  const box=$('#scriptMessages'),bottom=box.scrollHeight-box.clientHeight-box.scrollTop<48;
  const messages=[...(w.messages||[])];if(busy&&j?.submittedMessage)messages.push({role:'user',content:j.submittedMessage});
  setStableHTML(box,messages.length?messages.map(m=>`<article class="creative-message ${m.role==='user'?'user':'assistant'}"><header>${m.role==='user'?'你':esc(m.model||'DeepSeek')}</header><div class="creative-content">${esc(m.content)}</div></article>`).join(''):'<div class="screenplay-welcome"><span class="eyebrow">一起推敲整片</span><h3>故事先聊透，镜头再落笔。</h3><p>可以调整某段，也可以讨论整片节奏。我会结合前后剧情，检查动作、机位与对白的衔接。</p><p>聊好后生成待确认稿，预览中文分镜和末尾英文，再确认应用。</p></div>');
  if(bottom)box.scrollTop=box.scrollHeight;
  $('#scriptProposal').hidden=!draft;
  if(draft){setStableText($('#scriptProposalSummary'),`${draft.script.duration_seconds} 秒 · ${draft.script.scenes.length} 段`);setStableText($('#scriptProposalNote'),draft.applied_at?'已应用，可继续讨论新一轮修改。':draft.revision!==w.revision?'已有新讨论，请重新生成待确认稿。':'尚未覆盖左侧，点击预览后确认。');}
  const noScript=!scriptState()?.base;
  $('#scriptSend').disabled=busy||noScript;$('#scriptBuildDraft').disabled=busy||noScript;
  $('#scriptPreviewDraft').disabled=busy||!draft;
  setStableText($('#scriptBuildDraft'),busy&&j?.action==='script_propose'?'正在整理中文与英文…':'生成待确认稿 · 含英文');
  setStableText($('#scriptChatStatus'),busy?(j?.message||'正在提交…'):j?.status==='error'?j.message:'视频生成期间可讨论；保存与应用整片修改需等待生成结束。');
}
async function saveScriptWorkspace(){
  if(scriptWriting)throw new Error('正在保存，请稍候');
  const pid=project?.id,script=captureScriptEditor(),state=scriptState();if(!script)throw new Error('请先导入剧本');
  if(!state.dirty)return project;
  const submitted=state.text;scriptWriting=true;
  try{const p=await api(`/api/projects/${pid}/script-workspace/save`,{method:'POST',body:JSON.stringify({base_script:state.base,script})});
    state.base=scriptCopy(p.script);state.dirty=state.text!==submitted;
    if(!state.dirty)state.text=scriptDocumentText(p.script);
    if(project?.id===pid){project=p;renderScriptWorkspace();renderInspector()}return p;
  }finally{scriptWriting=false;}
}
async function submitScriptDiscussion(action){
  const pid=project?.id,input=$('#scriptChatInput'),message=input.value.trim();if(!pid||scriptSubmitting||['queued','running'].includes(scriptJobs.get(pid)?.status))return;
  if(action==='script_discuss'&&!message)return;
  try{const script=captureScriptEditor(),state=scriptState();scriptSubmitting=true;renderScriptDiscussion();
    const job=await api(`/api/projects/${pid}/action`,{method:'POST',body:JSON.stringify({action,message,revision:project.script_workspace?.revision||0,base_script:state.base,script})});
    job.submittedMessage=message;scriptJobs.set(pid,job);
    if(project?.id===pid&&input.value.trim()===message){input.value='';scriptInputs.set(pid,'')}
    pollScriptDiscussion(job);
  }catch(e){toast(e.message)}finally{scriptSubmitting=false;if(project?.id===pid)renderScriptDiscussion()}
}
async function pollScriptDiscussion(job){
  const pid=job.project_id;
  try{const j=await api(`/api/jobs/${job.id}`);j.submittedMessage=job.submittedMessage;scriptJobs.set(pid,j);
    if(['done','error','cancelled'].includes(j.status)){
      if(project?.id===pid){const p=await api(`/api/projects/${pid}`);if(project?.id===pid){project.script_workspace=p.script_workspace;
        if(j.status!=='done'&&!$('#scriptChatInput').value&&job.submittedMessage)$('#scriptChatInput').value=job.submittedMessage;
        renderScriptDiscussion();}}
      if(j.status!=='done')toast(j.message);return;
    }if(project?.id===pid)renderScriptDiscussion();
  }catch(e){if(e.message==='任务不存在'){scriptJobs.set(pid,{status:'error',message:'服务已重启，当前编辑保留，请重新发送'});if(project?.id===pid)renderScriptDiscussion();return;}if(project?.id===pid)setStableText($('#scriptChatStatus'),'连接中断，正在重连；后台任务继续运行');}
  setTimeout(()=>pollScriptDiscussion(job),1500);
}
async function resumeScriptDiscussion(){if(!project)return;const pid=project.id;try{const r=await api('/api/runtime');const job=r.jobs.find(j=>j.project_id===pid&&['script_discuss','script_propose'].includes(j.action));if(job&&!scriptJobs.has(pid)){scriptJobs.set(pid,job);pollScriptDiscussion(job)}if(project?.id===pid)renderScriptDiscussion()}catch{}}
function previewScriptDraft(){
  const draft=project?.script_workspace?.draft;if(!draft)return;
  $('#scriptDraftText').textContent=scriptDocumentText(draft.script);
  $('#scriptDraftDialog').dataset.draftId=draft.id;$('#scriptDraftDialog').dataset.projectId=project.id;
  const stale=draft.revision!==project.script_workspace.revision||draft.applied_at;
  setStableText($('#scriptDraftNotice'),stale?'此稿已应用或有新讨论，可查看；请重新生成后再应用。':'确认后替换左侧整片剧本，并保留原稿历史。已有素材与视频保留，录音不会重制；再点击输出到 04 更新任务。');
  $('#scriptApplyDraft').disabled=!!stale;$('#scriptDraftDialog').showModal();
}
async function applyScriptDraft(){
  const dialog=$('#scriptDraftDialog'),pid=project?.id;if(pid!==dialog.dataset.projectId)return;
  const submitted=$('#scriptDocument').value;
  $('#scriptApplyDraft').disabled=true;
  try{const p=await api(`/api/projects/${pid}/script-workspace/apply`,{method:'POST',body:JSON.stringify({draft_id:dialog.dataset.draftId,editor_script:captureScriptEditor()})});
    if(project?.id===pid){project=p;renderScriptWorkspace($('#scriptDocument').value===submitted);renderInspector();dialog.close();toast('已确认应用，原剧本已保留历史')}
  }catch(e){toast(e.message);setStableText($('#scriptDraftNotice'),e.message);$('#scriptApplyDraft').disabled=false;}
}
async function exportScriptWorkspace(extract=false){
  const pid=project?.id;if(!pid)return;
  const b=$(extract?'#scriptExtract':'#scriptExport');b.disabled=true;
  try{
    await saveScriptWorkspace();if(project?.id!==pid)return;
    if(extract){const job=await api(`/api/projects/${pid}/action`,{method:'POST',body:JSON.stringify({action:'analyze'})});rememberProgress(job,scriptCopy(project),{action:'analyze'});watchJob(job);toast('正在提取元素，完成后进入 03 选择参考图');}
    else{const p=await api(`/api/projects/${pid}/script-workspace/export`,{method:'POST',body:JSON.stringify({base_script:project.script})});if(project?.id===pid){project=p;renderShots();attachShotReferences();renderVideos();renderInspector();showStage('storyboard');toast('已输出到 04；可选择段落后生成视频')}}
  }catch(e){toast(e.message)}finally{b.disabled=false;}
}
function bindScriptWorkspace(){
  $('#scriptDocument').oninput=()=>{try{captureScriptEditor()}catch{}updateScriptWorkspaceState()};
  $('#scriptChatInput').oninput=()=>scriptInputs.set(project?.id,$('#scriptChatInput').value);
  $('#scriptChatInput').onkeydown=e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();submitScriptDiscussion('script_discuss')}};
  $('#scriptSend').onclick=()=>submitScriptDiscussion('script_discuss');$('#scriptBuildDraft').onclick=()=>submitScriptDiscussion('script_propose');
  $('#scriptModelSettings').onclick=()=>$('#openTextModel').click();$('#scriptPreviewDraft').onclick=previewScriptDraft;$('#scriptApplyDraft').onclick=applyScriptDraft;
  for(const id of ['scriptCloseDraft','scriptKeepDiscussing'])$('#'+id).onclick=()=>$('#scriptDraftDialog').close();
  $('#scriptExtract').onclick=()=>exportScriptWorkspace(true);$('#scriptExport').onclick=()=>exportScriptWorkspace(false);
  $('#scriptJumpEnglish').onclick=()=>{const e=$('#scriptDocument'),pos=e.value.indexOf('【第 1 段 · 英文 H3 提示词】');if(pos<0)return;
    const style=getComputedStyle(e),measure=document.createElement('div');
    Object.assign(measure.style,{position:'absolute',visibility:'hidden',width:(e.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight))+'px',font:style.font,lineHeight:style.lineHeight,whiteSpace:'pre-wrap',overflowWrap:'break-word'});
    measure.textContent=e.value.slice(0,pos);document.body.append(measure);const offset=measure.getBoundingClientRect().height;measure.remove();
    e.focus();e.setSelectionRange(pos,pos);e.scrollTop=Math.max(0,offset-parseFloat(style.lineHeight));};
  $('#scriptReload').onclick=async()=>{if(scriptState()?.dirty&&!confirm('重新读取会放弃左侧未保存修改，继续吗？'))return;const pid=project?.id;try{const p=await api(`/api/projects/${pid}`);if(project?.id===pid){project=p;renderScriptWorkspace(true)}}catch(e){toast(e.message)}};
}
