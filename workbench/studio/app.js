const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let projects=[], project=null, stage='brief', currentJob=null, pollTimer=null, settings={}, chatBusy=false;
let chatStatus='',chatStats='',chatStarted=0;
let chatHistory=[];try{const saved=JSON.parse(localStorage.getItem('mirrorflow-chat')||'[]');if(Array.isArray(saved))chatHistory=saved.filter(m=>m&&['user','assistant'].includes(m.role)&&typeof m.content==='string').slice(-20)}catch{}
let statusRefreshing=false, jobWatchVersion=0;
const api=async(path,opt={})=>{const r=await fetch(path,{headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});const d=await r.json();if(!r.ok)throw new Error(d.error||`请求失败 ${r.status}`);return d};
const media=path=>project?`/media/${project.id}/${path.split('/').map(encodeURIComponent).join('/')}`:'';
function toast(msg){const t=$('#toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2400)}
function esc(v=''){return String(v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}

async function boot(){await Promise.all([refreshProjects(),loadSettings()]);bind();renderChat();renderCreativeChat();$('#emptyState').classList.add('hidden');$('#projectView').classList.remove('hidden');registerWebMCP();refreshStatus();setInterval(refreshStatus,15000);const params=new URLSearchParams(location.search);if(params.get('project')){await openProject(params.get('project'));if(['brief','script','elements','storyboard','video','lipsync'].includes(params.get('stage')))showStage(params.get('stage'));}}
function bind(){
  bindTextModelUI();
  bindCreativeChat();
  bindScriptWorkspace();
  bindAssetUI();
  bindLipSync();
  $('#openProjectFolder').onclick=()=>project&&revealFile('');
  $('#openProjectTrash').onclick=()=>project&&revealFile('回收站');
  bindVideoBackendUI();
  $('#newProject').onclick=()=>$('#newDialog').showModal();
  $('#createProject').onclick=async e=>{e.preventDefault();const p=await api('/api/projects',{method:'POST',body:JSON.stringify({title:$('#newTitle').value,brief:$('#newBrief').value})});$('#newDialog').close();await refreshProjects();await openProject(p.id)};
  $$('#stagebar button').forEach(b=>b.onclick=()=>showStage(b.dataset.stage));
  $$('[data-stage-jump]').forEach(b=>b.onclick=()=>showStage(b.dataset.stageJump));
  $$('[data-action]').forEach(b=>b.onclick=()=>runAction(b.dataset.action,b.dataset));
  $('#chooseFiles').onclick=()=>$('#fileInput').click();$('#fileInput').onchange=e=>uploadFiles(e.target.files);
  const z=$('#uploadZone');z.ondragover=e=>{e.preventDefault();z.classList.add('drag')};z.ondragleave=()=>z.classList.remove('drag');z.ondrop=e=>{e.preventDefault();z.classList.remove('drag');uploadFiles(e.dataTransfer.files)};
  $('#saveScript').onclick=saveScript;
  $('#projectTitle').onchange=async()=>{project.title=$('#projectTitle').value;project=await api(`/api/projects/${project.id}/save`,{method:'POST',body:JSON.stringify({title:project.title})});await refreshProjects();toast('项目名称已保存')};
  $('#openSettings').onclick=()=>{$('#settingsDialog').showModal();fillSettings();fillBackendSettings()};
  $('#imagePreset').onchange=()=>applySizePreset('image');$('#videoPreset').onchange=()=>applySizePreset('video');
  ['imageWidth','imageHeight'].forEach(id=>$('#'+id).oninput=()=>$('#imagePreset').value='custom');
  ['videoWidth','videoHeight'].forEach(id=>$('#'+id).oninput=()=>$('#videoPreset').value='custom');
  $('#saveSettings').onclick=saveGenerationSettings;
  $('#openChat').onclick=()=>{$('#chatDialog').showModal();renderChat();setTimeout(()=>$('#chatInput').focus(),50)};
  $('#closeChat').onclick=()=>$('#chatDialog').close();$('#sendChat').onclick=sendChat;$('#clearChat').onclick=()=>{chatHistory=[];persistChat();renderChat()};
  $('#chatInput').onkeydown=e=>{if(e.metaKey&&e.key==='Enter'){e.preventDefault();sendChat()}};
}
async function loadSettings(){settings=await api('/api/settings')}
function updateDurationHints(){const s=project?.script,d=settings.video_duration||10;$('#taskPlanHint').textContent=s?.scenes?.length?`整片 ${s.duration_seconds||'待定'} 秒 · ${s.scenes.length} 段。02 输出按各段已填写时长（5–15 秒）建立任务，保留原声需保持分段时长。`:`请先导入剧本，默认每段 ${d} 秒，可在右侧讨论分段与镜头。`;}

function fillSettings(){for(const [id,key] of Object.entries({referenceSize:'reference_size',imageWidth:'image_width',imageHeight:'image_height',imageSteps:'image_steps',videoWidth:'video_width',videoHeight:'video_height',videoDuration:'video_duration'}))$('#'+id).value=settings[key];const ip=`${settings.image_width}x${settings.image_height}`;$('#imagePreset').value=[...$('#imagePreset').options].some(o=>o.value===ip)?ip:'custom';const vp=`${settings.video_width}x${settings.video_height}`;$('#videoPreset').value=[...$('#videoPreset').options].some(o=>o.value===vp)?vp:'custom'}
function applySizePreset(kind){const value=$('#'+kind+'Preset').value;if(value==='custom')return;const parts=value.split('x').map(Number);if(kind==='image'){$('#imageWidth').value=parts[0];$('#imageHeight').value=parts[1]}else{$('#videoWidth').value=parts[0];$('#videoHeight').value=parts[1]}}
async function saveGenerationSettings(e){
  e.preventDefault();if(!$('#settingsDialog form').reportValidity())return;
  const body={reference_size:+$('#referenceSize').value,image_width:+$('#imageWidth').value,image_height:+$('#imageHeight').value,image_steps:+$('#imageSteps').value,video_width:+$('#videoWidth').value,video_height:+$('#videoHeight').value,video_duration:+$('#videoDuration').value,video_backend:'h3c',h3c_steps:+$('#h3cSteps').value,video_upscale:+$('#videoUpscale').value};
  body.h3c_swap_limit_gib=+$('#h3cSwapLimit').value;
  body.h3c_ssd_streaming=$('#h3cStreaming').checked;
  body.h3c_resident=$('#h3cResident').checked;
  if(settings.h3c_layers!=null)Object.assign(body,{h3c_layers:+$('#h3cLayers').value,h3c_reuse:+$('#h3cReuse').value,h3c_reference_video_max_pixels:+$('#h3cRefVideoPixels').value});
  if($('#h3cFaceRefine')){body.h3c_face_refine=$('#h3cFaceRefine').checked;body.h3c_face_preserve_mouth=$('#h3cFaceMouth').checked;body.h3c_face_steps=+$('#h3cFaceSteps').value;body.h3c_face_size=+$('#h3cFaceSize').value;body.h3c_face_denoise=+$('#h3cFaceDenoise').value;}
  body.h3c_stall_minutes=+$('#h3cStallMinutes').value;
  try{settings=await api('/api/settings',{method:'POST',body:JSON.stringify(body)});if(project)renderInspector();$('#settingsDialog').close();toast(`已保存：${settings.video_backend} · 默认 ${settings.video_duration} 秒 · 视频 ${settings.video_width}×${settings.video_height}`)}catch(err){toast(err.message)}
}
function persistChat(){localStorage.setItem('mirrorflow-chat',JSON.stringify(chatHistory.slice(-20)))}
function renderChat(){
  const box=$('#chatMessages'),atBottom=box.scrollHeight-box.clientHeight-box.scrollTop<48;
  setStableText($('#chatProgress'),chatBusy?`${chatStatus} · ${Math.floor((Date.now()-chatStarted)/1000)} 秒`:chatStats);
  if(!chatHistory.length&&!chatBusy){setStableHTML(box,'<div class="chat-empty">可以问写作、知识解释、方案分析、代码或日常问题。当前未接入联网搜索，无法直接查网页或查找剧照。</div>');return}
  const rows=chatHistory.map((m,i)=>({key:String(i),html:`<div class="chat-message ${m.role}"><span>${m.role==='user'?'你':esc(textModelLabel())}</span><p>${esc(m.content).replace(/\n/g,'<br>')||'等待首字…'}</p></div>`}));
  renderKeyedHTML(box,rows);
  // Follow replies only when already near the bottom; never pull someone away from older text.
  if(atBottom)box.scrollTop=box.scrollHeight;
}
async function sendChat(){
  const input=$('#chatInput'),content=input.value.trim();if(!content||chatBusy)return;
  chatHistory.push({role:'user',content});chatHistory=chatHistory.slice(-20);
  const messages=chatHistory.slice(),reply={role:'assistant',content:''};chatHistory.push(reply);
  input.value='';chatBusy=true;chatStarted=Date.now();chatStatus='准备模型';chatStats='';renderChat();
  $('#sendChat').disabled=true;$('#clearChat').disabled=true;const timer=setInterval(renderChat,1000);
  let done=false;
  try{
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages,stream:true})});
    if(!response.ok){const error=await response.json();throw new Error(error.error||'请求失败')}
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
    while(true){const part=await reader.read();buffer+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines){if(!line.trim())continue;const event=JSON.parse(line);if(event.error)throw new Error(event.error);if(event.status)chatStatus=event.status;if(event.delta){reply.content+=event.delta;chatStatus='正在回答'}if(event.done){done=true;chatStats=`完成 · ${event.seconds} 秒 · 加载 ${event.load_seconds} 秒 · ${event.tokens_per_second} token/秒${event.truncated?' · 已达单次长度上限，可发送“继续”':''}`}}renderChat();if(part.done)break}
    if(!done)throw new Error('连接提前结束');persistChat();
  }catch(err){if(!reply.content){chatHistory.splice(-2);input.value=content}else{reply.content+='\n[回答中断，请重试]';persistChat()}chatStats='未完成：'+err.message;toast('暂时无法完成：'+err.message)}
  finally{clearInterval(timer);chatBusy=false;$('#sendChat').disabled=false;$('#clearChat').disabled=false;renderChat();refreshStatus()}
}
async function refreshProjects(){projects=await api('/api/projects');$('#projectList').innerHTML=projects.map(p=>`<div class="project-row"><button class="project-item ${project?.id===p.id?'active':''}" data-id="${esc(p.id)}"><strong>${esc(p.title)}</strong><small>${esc(p.stage||'brief')} · ${esc((p.updated_at||'').slice(5,16).replace('T',' '))}</small></button><button class="project-delete" data-delete="${esc(p.id)}" aria-label="删除项目 ${esc(p.title)}" title="移入项目回收站">删除</button></div>`).join('')||'<p class="muted">还没有项目</p>';$$('.project-item').forEach(b=>b.onclick=()=>openProject(b.dataset.id));$$('[data-delete]').forEach(b=>b.onclick=()=>deleteProject(b.dataset.delete))}
async function deleteProject(id){const target=projects.find(p=>p.id===id);if(!target||!confirm(`删除项目“${target.title}”？\n剧本、参考图和视频将移入这个工程自己的“回收站”，可以恢复；不会删除模型或其他工程。`))return;try{await api(`/api/projects/${encodeURIComponent(id)}`,{method:'DELETE'});if(project?.id===id){project=null;clearInterval(pollTimer);$('#jobCard').classList.add('hidden');$('#projectView').classList.add('hidden');$('#emptyState').classList.remove('hidden');$('#projectTitle').value='未选择项目';$('#projectTitle').disabled=true;$('#projectStorage').textContent='';$('#openProjectFolder').disabled=true;$('#openProjectTrash').disabled=true;$('#projectMeta').textContent='创建项目后开始';$('#progressList').innerHTML='';$('#continuityList').innerHTML='';$('#briefInput').value='';$('#uploads').innerHTML='';$('#emptyState').classList.add('hidden');$('#projectView').classList.remove('hidden');showStage('brief');renderCreativeChat()}await refreshProjects();toast('已移入该工程自己的“回收站”，可恢复')}catch(e){toast(e.message)}}
async function refreshStatus(){
  if(statusRefreshing)return;statusRefreshing=true;
  try{
    const s=await api('/api/status');await loadTextModel();if(textConfig.provider!=='local')s.ollama=textConfig.key_configured;
    const key=n=>n?.split('/').pop().includes(':')?n:n+':latest',loaded=n=>s.ollama_loaded_models?.some(m=>key(m)===key(n));
    const residency=n=>s.ollama_loaded_models==null?'状态未知':loaded(n)?'已加载':'已卸载';
    const pills=[
      [textConfig.provider==='local'?'Qwen':textModelLabel(),textConfig.provider==='local'?residency(s.text_model):(s.ollama?'已配置':'缺少密钥'),textConfig.provider==='local'?loaded(s.text_model):s.ollama],
      [s.active_image_model||s.image_model||'生图',s.qwen_image?'服务运行':'已关闭',s.qwen_image],
      ['h3.c 视频',s.h3c_resident?.running?(s.h3c_resident.busy?'正在生成':'常驻待命 · 缓存保留'):s.h3c_running?'正在运行':s.h3c?'已卸载 · 可用':'未就绪',s.h3c_running],
      ['质检',s.vision_ready?residency(s.vision_model):'未安装',loaded(s.vision_model)]
    ];
    for(const name of s.ollama_loaded_models||[])if(![s.text_model,s.vision_model].some(n=>key(n)===key(name)))pills.push([name,'已加载',true]);
    setStableHTML($('#servicePills'),pills.map(([name,label,active])=>`<span class="service-pill ${active?'online':''}" title="绿色表示模型已加载或服务正在运行；卸载不会删除磁盘权重">${esc(name)} · ${esc(label)}</span>`).join(''));
    const z=s.image_backend==='z_image';setStableText($('#settingsDialog h3'),(s.image_model||'Qwen-Image')+' 图片');setStableText($('#imageSteps option[value="4"]'),z?'4 · 快速试验':'4 · Lightning 推荐');setStableText($('#imageSteps option[value="8"]'),z?'8 · Turbo 推荐':'8 · 实验');setStableText($('#settingsDialog .settings-warning'),z?'当前使用 Z-Image-Turbo，推荐 8 步；不加载 Qwen Lightning LoRA。参考图重绘不保证人物身份一致。':'当前使用 4 步 Lightning；增加步数会更慢，画质不一定更好。');
  }catch{}finally{statusRefreshing=false}
}
async function openProject(id){project=await api(`/api/projects/${id}`);$('#emptyState').classList.add('hidden');$('#projectView').classList.remove('hidden');$('#projectTitle').disabled=false;render();await refreshProjects();showStage('brief');$('.workspace').scrollTop=0;resumeCreativeJob();resumeScriptDiscussion()}
function showStage(s){if(!project&&s!=='brief'){toast('请先创建或打开工程');return}if(stage==='lipsync'&&s!=='lipsync')lipPause();stage=s;$$('#stagebar button').forEach(b=>b.classList.toggle('active',b.dataset.stage===s));$$('.stage-panel').forEach(p=>p.classList.toggle('active',p.dataset.panel===s));if(project)project.stage=s;if(s==='lipsync')renderLipSync()}
function render(){
  if($('#productionProgress')&&$('#productionProgress').dataset.projectId!==project.id)$('#productionProgress').hidden=true;
  if($('#openCanvas'))$('#openCanvas').href='/?project='+encodeURIComponent(project.id);
  $('#projectTitle').value=project.title;$('#projectMeta').textContent=`更新于 ${project.updated_at?.replace('T',' ')||'刚刚'} · ${project.id}`;$('#briefInput').value=project.brief||'';
  $('#projectStorage').textContent=project.storage_path||'';$('#openProjectFolder').disabled=false;$('#openProjectTrash').disabled=false;
  renderUploads();renderAnalysis();renderScript();renderShots();attachShotReferences();renderVideos();renderInspector();renderCreativeChat();
  if(stage==='lipsync')renderLipSync();
}
function renderUploads(){
  const entities=project.analysis?[...(project.analysis.characters||[]),...(project.analysis.key_objects||[]),...(project.analysis.locations||[])]:[];
  const html=(project.uploads||[]).map(u=>{
    const image=/\.(png|jpe?g|webp)$/i.test(u.path),video=/\.(mp4|mov|webm|mkv)$/i.test(u.path),audio=/\.(wav|mp3|m4a|flac|ogg|aiff?)$/i.test(u.path);
    const preview=image?`<img src="${media(u.path)}" alt="${esc(u.name)}">`:video?`<video controls preload="metadata" src="${media(u.path)}"></video>`:audio?`<audio controls preload="metadata" src="${media(u.path)}"></audio>`:'';
    return `<div class="upload-card">${preview}<span>${esc(u.name)}</span>${image&&entities.length?`<select data-upload="${u.id}"><option value="">未绑定</option>${entities.map(e=>`<option value="${e.id}" ${u.entity_id===e.id?'selected':''}>${esc(e.name)}</option>`).join('')}</select>`:''}</div>`;
  }).join('');$('#uploads').innerHTML=html;
  $$('[data-upload]').forEach(s=>s.onchange=async()=>{const u=project.uploads.find(x=>x.id===s.dataset.upload);u.entity_id=s.value;project=await api(`/api/projects/${project.id}/save`,{method:'POST',body:JSON.stringify({uploads:project.uploads})});toast('参考图已绑定')});
}
function renderAnalysis(){const a=project.analysis||{};
  $('#analysisSummary').innerHTML=[[a.logline,'故事核心'],[a.genre,'类型'],[a.format,'规格'],[a.visual_style,'视觉方向']].map(([v,k])=>`<div class="summary-cell"><small>${k}</small>${esc(v)}</div>`).join('');
  const groups=[['characters','人物'],['key_objects','关键物品'],['locations','场景']];$('#entitySections').innerHTML=groups.map(([key,title])=>`<div class="entity-group"><h2>${title} · ${(a[key]||[]).length}</h2><div class="entity-grid editable-entities">${(a[key]||[]).map(x=>entityEditorCard(key,x)).join('')}</div></div>`).join('');
  renderCustomEntities();renderCharacterControls();renderOpeningFrames();
}
function entityCard(kind,x){const asset=project.assets?.[x.id];const detail=kind==='characters'?`${x.appearance||''} ${x.wardrobe||''}`:x.description||'';return `<article class="entity-card"><span class="tag">${kind==='characters'?'人物':kind==='key_objects'?'物品':'场景'}</span><h3>${esc(x.name)}</h3><p>${esc(detail)}</p>${asset?`<div class="asset-thumbs">${asset.images.map(i=>`<img src="${media(i)}">`).join('')}</div>`:''}<div class="entity-actions"><small class="muted">${asset?'多角度参考已生成':'尚未生成参考图'}</small><button class="ghost" data-entity="${x.id}">${asset?'重新生成':'生成四视图'}</button></div></article>`}
function renderScript(){renderScriptWorkspace()}
async function saveScript(){try{await saveScriptWorkspace();toast('剧本已保存')}catch(e){toast(e.message)}}
function sortedShots(){return [...(project.shots||[])].sort((a,b)=>Number(a.shot)-Number(b.shot))}
function elementName(id){return [...(project.analysis?.characters||[]),...(project.analysis?.key_objects||[]),...(project.analysis?.locations||[])].find(e=>e.id===id)?.name||id}
function shotDetails(s){return `<p><b>调用元素：</b>${esc((s.element_ids||[]).map(elementName).join('、')||'旧分镜未标注')}</p>${(s.character_actions||[]).map(a=>`<p><b>${esc(elementName(a.character_id))}：</b>${esc(a.action)}<br><small>使用：${esc((a.element_ids||[]).map(elementName).join('、')||'无道具' )}</small></p>`).join('')}<p><b>镜头安排：</b>${esc(s.camera||'见运动提示词')}</p>${s.dialogue?`<p><b>对白：</b>${esc(s.dialogue)}</p>`:''}`}
function renderShots(){renderTextShots()}
function renderVideos(){renderVideoChoices()}
function reviewHtml(r){if(!r)return '<div class="review"><h3>尚未质检</h3><p class="muted">视频生成后调用视觉模型检查。</p></div>';return `<div class="review ${r.decision}"><h3>${r.decision==='pass'?'通过':r.decision==='revise'?'建议修改':'不通过'} · ${r.score}/100</h3><p>${esc(r.summary)}</p>${(r.issues||[]).map(i=>`<div class="issue"><b>${esc(i.time)} · ${esc(i.severity)}</b><br>${esc(i.problem)}<br><span class="muted">${esc(i.suggestion)}</span></div>`).join('')}${(r.confirmation_questions||[]).map(q=>`<p>待确认：${esc(q)}</p>`).join('')}</div>`}
function renderInspector(){updateDurationHints();const a=project.analysis;const entities=[...(a?.characters||[]),...(a?.key_objects||[]),...(a?.locations||[])];const stages=[['创作讨论',!!(project.brief||project.creative_workspace?.messages?.length)],['剧本',!!project.script],['元素文字（可选）',entities.length>0],['参考图（可选）',entities.length>0&&entities.every(e=>project.assets?.[e.id]?.primary_image)],['视频任务',!!project.shots?.length],['全部视频',project.shots?.length>0&&project.shots.every(s=>s.video&&!s.video_stale)],['顺序合片',!!project.final_video]];$('#progressList').innerHTML=stages.map(([n,d])=>`<div class="progress-row ${d?'done':''}"><span>${d?'✓':'○'} ${n}</span><small>${d?'完成':'待处理'}</small></div>`).join('');$('#continuityList').innerHTML=entities.map(x=>`<div class="continuity-item"><strong>${esc(x.name)}</strong><span>${esc(x.role||x.story_function||'场景元素')}</span></div>`).join('')||'<p class="muted">保存剧本后提取人物与元素。</p>';$('#contextTip').textContent=`默认每段 ${settings.video_duration||10} 秒（5–15 秒可调），按编号依次生成；h3.c Metal · ${settings.video_width}×${settings.video_height} / ${settings.h3c_steps} 步。每段可选文生、首帧或全能参考；首帧与全能参考模式可采用上一段实际尾帧。`}
async function uploadFiles(files){if(!project)return;for(const f of files){const form=new FormData();form.append('file',f);form.append('name',f.name);await fetch(`/api/projects/${project.id}/upload`,{method:'POST',body:form})}project=await api(`/api/projects/${project.id}`);renderUploads();toast('参考图已上传')}
async function runAction(action,data={}){
  if(!project)return;
  if(action==='all_assets'&&!data.assetPlan){openAssetPlan();return;}
  try{
    const payload={action};
    if(action==='opening_frames'){await ensureOpeningFramesBackend();payload.shot_ids=data.shotIds;payload.force=!!data.force;}
    if(action==='render_sequence'){
      await ensureVideoChoices();payload.shot_ids=data.shotIds||selectedGenerationIds();
      if(!payload.shot_ids.length)throw new Error('请先勾选要生成的段落');
      if(stage==='storyboard')await saveTextShots(payload.shot_ids);
    }
    if(action==='assemble'){await ensureVideoChoices();payload.clips=selectedAssemblyClips();if(!payload.clips.length)throw new Error('请先选择合成视频版本')}
    if(action==='color_match'){
      if(!(await api('/api/capabilities')).video_color_match)throw new Error('色彩对齐需要新版服务，请在当前任务结束并更新后刷新');
      Object.assign(payload,colorMatchPayload());
    }
    if(['asset','all_assets'].includes(action)){
      let supported=false,caps={};try{caps=await api('/api/capabilities');supported=caps.asset_plan;}catch{}
      if(!supported)throw new Error('选择生成数量需要新版服务：请等当前任务结束后重启工作台，现有生成不受影响');
      const characters=new Set((project.analysis?.characters||[]).map(c=>c.id));
      const needsHeads=action==='asset'?characters.has(data.entityId):Object.entries(data.assetPlan||{}).some(([id,n])=>n>0&&characters.has(id));
      if(needsHeads&&(caps.character_sheet_revision||0)<12)throw new Error('人物三视图头部参考等待当前任务结束后更新工作台');
    }
    if(action==='script'){
      const changes={brief:$('#briefInput').value};
      if(stage==='script'&&$('#scriptEditor').value.trim())changes.script=JSON.parse($('#scriptEditor').value);
      project=await api(`/api/projects/${project.id}/save`,{method:'POST',body:JSON.stringify(changes)});
      payload.notes=stage==='brief'?$('#analysisNotes').value:$('#scriptNotes').value;
    }
    if(action==='analyze'){
      if(stage==='script'){
        const script=JSON.parse($('#scriptEditor').value);
        project=await api(`/api/projects/${project.id}/save`,{method:'POST',body:JSON.stringify({script})});
      }
    }
    if(action==='all_assets'){
      payload.asset_plan=data.assetPlan;
      payload.regenerate_assets=!!data.regenerateAssets;
      for(const card of $$('#entitySections [data-entity-card]'))await saveEntity(card.dataset.entityCard,{},false);
    }
    if(action==='storyboard'){
      if(stage==='script')project=await api(`/api/projects/${project.id}/save`,{method:'POST',body:JSON.stringify({script:JSON.parse($('#scriptEditor').value)})});
      payload.notes=$('#storyNotes').value;
    }
    if(action==='asset')payload.entity_id=data.entityId;
    if(['frames','video','review','enhance_video','repair_tail','face_refine'].includes(action))payload.shot_id=data.shotId; if(action==='enhance_video')payload.scale=data.scale;if(action==='repair_tail')payload.force=!!data.force;
    const baseline=JSON.parse(JSON.stringify(project));
    const job=await api(`/api/projects/${project.id}/action`,{method:'POST',body:JSON.stringify(payload)});rememberProgress(job,baseline,payload);watchJob(job);
  }catch(e){toast(e.message)}
}
function watchJob(job){
  const watchVersion=++jobWatchVersion;let polling=false;
  currentJob=job;$('#jobCard').classList.remove('hidden');$('#jobTitle').textContent=labels[job.action]||'模型处理中';clearInterval(pollTimer);
  if(job.action==='render_sequence'&&project?.id===job.project_id)showStage('video');
  pollTimer=setInterval(async()=>{
    if(polling||watchVersion!==jobWatchVersion)return;polling=true;
    try{
    const j=await api(`/api/jobs/${job.id}`);if(watchVersion!==jobWatchVersion)return;
    currentJob=j;setStableText($('#jobMessage'),j.message);
    let snapshot=null;
    if(project?.id===j.project_id){
      snapshot=await api(`/api/projects/${j.project_id}`);
      if(project?.id!==j.project_id||watchVersion!==jobWatchVersion)return;
      renderProductionProgress(j,snapshot);
      if(!['asset','all_assets','frames','all_frames','video','all_videos','render_sequence','benchmark_video'].includes(j.action)){setStableText($('#jobPercent'),j.progress+'%');setStableProgress($('#jobProgress'),j.progress)}
      // Do not redraw editable descriptions while someone is typing.
      if(['asset','all_assets'].includes(j.action)){
        for(const card of $$('#entitySections [data-entity-card]')){
          const versions=progressVersions(snapshot.assets?.[card.dataset.entityCard]);
          const v=versions.at(-1);let badge=card.querySelector('.entity-live-progress');
          if(!badge){badge=document.createElement('p');badge.className='entity-live-progress';card.prepend(badge);}
          const count=j.asset_plan?.[card.dataset.entityCard]??v?.view_count??4;
          setStableText(badge,count===0?'本批跳过':v?.status==='running'&&v.view_progress?`人物参考已完成 ${v.view_progress.completed}/${v.view_progress.total||4} · ${v.view_progress.label}`:v?`${v.status==='done'?'已完成':v.status==='running'?'生成中':'已保存'} ${v.images.length}/${v.view_count??(v.status==='done'?v.images.length:count)} 张`:`等待生成 · 0/${count} 张`);
        }
      }
    }else{if($('#productionProgress'))$('#productionProgress').hidden=true;setStableText($('#jobPercent'),j.progress+'%');setStableProgress($('#jobProgress'),j.progress)}
    if(['render_sequence','color_match'].includes(j.action)&&project?.id===j.project_id&&j.status==='running'){
      if(snapshot&&JSON.stringify(snapshot.shots)!==JSON.stringify(project.shots)){project=snapshot;syncShotStatus();renderVideos();renderInspector()}
    }
    if(['done','error','cancelled'].includes(j.status)){
      clearInterval(pollTimer);pollTimer=null;
      if(project?.id===j.project_id&&snapshot){project=snapshot;if(j.action==='lip_sync'){renderVideos();renderLipResults();renderInspector();$('#lipStatus').textContent=j.message;}else if(j.action==='opening_frames'){renderOpeningFrames();refreshOpeningShotPanels();renderInspector()}else if(['video','all_videos','render_sequence','assemble','color_match','review','enhance_video','repair_tail'].includes(j.action)){syncShotStatus();renderVideos();renderInspector()}else if(j.action==='translate_h3'){finishH3Translation(j);renderVideos();renderInspector()}else render()}
      $('#jobCard').classList.toggle('hidden',j.status==='done'&&!j.needs_tail_review);
      if(j.needs_tail_review){$('#jobTitle').textContent='尾帧待预览采用';$('#jobPercent').textContent='待确认';showStage('storyboard')}
      if(j.status!=='done'){$('#jobPercent').textContent=j.status==='error'?'失败':'已停止';$('#jobTitle').textContent=(labels[j.action]||'任务')+' · '+(j.status==='error'?'失败':'已停止');}
      toast(j.needs_tail_review?j.message:j.status==='done'?'任务完成':j.message);
      if(j.status!=='done')return;
      if(['analyze','all_assets','opening_frames'].includes(j.action))showStage('elements');
      if(j.action==='script')showStage('script');
      if(['storyboard','frames','all_frames'].includes(j.action))showStage('storyboard');
      if(!j.needs_tail_review&&['video','all_videos','render_sequence','assemble','color_match','review','enhance_video'].includes(j.action))showStage('video');
    }
  }catch(e){if(watchVersion===jobWatchVersion)setStableText($('#jobMessage'),'连接暂时中断：'+e.message)}finally{polling=false}
  },1500);
}
const labels={lip_sync:'视频口型校对',opening_frames:'生成剧情首帧参考',face_refine:'H3 面部精修',translate_h3:'生成 H3 英文提示词',repair_tail:'尾帧优化与预览',analyze:'从剧本提取元素',script:'编写剧本',asset:'生成多角度参考',all_assets:'依次生成元素参考图',storyboard:'拆分视频任务',frames:'生成首尾帧',all_frames:'批量生成全部首尾帧',video:'生成视频',all_videos:'批量生成全部视频',render_sequence:'依次生成所选视频',assemble:'合成所选视频',color_match:'对齐视频色彩',review:'检查视频漏洞'};

function registerWebMCP(){
  const context=document.modelContext;
  if(!context?.registerTool)return;
  const register=tool=>Promise.resolve(context.registerTool(tool)).catch(()=>{});
  register({
    name:'create_film_project',title:'新建影视项目',
    description:'用项目名称和创意文本新建本地影视项目，并在工作台中打开。',
    inputSchema:{type:'object',properties:{title:{type:'string'},brief:{type:'string'}},required:['title','brief'],additionalProperties:false},
    annotations:{readOnlyHint:false,untrustedContentHint:false},
    async execute(input){
      if(!input||typeof input.title!=='string'||typeof input.brief!=='string')throw new Error('title 和 brief 必须是字符串');
      const p=await api('/api/projects',{method:'POST',body:JSON.stringify({title:input.title,brief:input.brief})});
      await refreshProjects();await openProject(p.id);return {project_id:p.id,title:p.title,stage:p.stage};
    }
  });
  register({
    name:'read_current_film_project',title:'读取当前影视项目',
    description:'读取工作台中当前项目的阶段、人物、元素、镜头和视频完成情况。',
    inputSchema:{type:'object',properties:{},additionalProperties:false},
    annotations:{readOnlyHint:true,untrustedContentHint:true},
    async execute(){
      if(!project)return {open:false};
      const fresh=await api(`/api/projects/${project.id}`);
      return {open:true,id:fresh.id,title:fresh.title,stage:fresh.stage,characters:(fresh.analysis?.characters||[]).map(x=>({id:x.id,name:x.name})),objects:(fresh.analysis?.key_objects||[]).map(x=>({id:x.id,name:x.name})),shot_count:(fresh.shots||[]).length,video_count:(fresh.shots||[]).filter(x=>x.video).length,has_final_video:!!fresh.final_video};
    }
  });
  register({
    name:'start_film_pipeline_step',title:'启动影视制作步骤',
    description:'使用 script 编写剧本后可直接 storyboard 建立文字任务；analyze 提取元素和 all_assets 生参考图为独立可选步骤；render_sequence 只顺序生成选中段落，不自动合片；assemble 手动合成选中版本。任务在后台运行。',
    inputSchema:{type:'object',properties:{action:{type:'string',enum:['analyze','script','all_assets','storyboard','all_videos','render_sequence','assemble','review']},notes:{type:'string'}},required:['action'],additionalProperties:false},
    annotations:{readOnlyHint:false,untrustedContentHint:false},
    async execute(input){
      if(!project)throw new Error('请先打开一个项目');
      if(input.action==='all_assets'){openAssetPlan();return {status:'awaiting_selection',message:'请在生成清单中选择每个元素的参考图数量并确认'};}
      const payload={action:input.action};
      if(input.notes)payload.notes=input.notes;
      if(input.action==='review')payload.shot_id='__final__';
      if(['render_sequence','assemble'].includes(input.action))await ensureVideoChoices();
      if(input.action==='render_sequence'){payload.shot_ids=selectedGenerationIds();if(!payload.shot_ids.length)throw new Error('请先在工作台勾选要生成的段落')}
      if(input.action==='assemble')payload.clips=selectedAssemblyClips();
      const job=await api(`/api/projects/${project.id}/action`,{method:'POST',body:JSON.stringify(payload)});
      watchJob(job);return {job_id:job.id,action:job.action,status:job.status};
    }
  });
}
boot().catch(error=>{toast('工作台初始化失败：'+error.message);console.error(error)});
