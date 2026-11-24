// Generation choices are local drafts; assembly takes are saved by the server.
const generationChoices=new Map();
function generationSelection(){
  if(!project)return new Set();
  if(!generationChoices.has(project.id)){
    let saved;try{saved=JSON.parse(localStorage.getItem('video-generation-'+project.id))}catch{}
    const ids=Array.isArray(saved)?saved:sortedShots().filter(s=>!s.video||s.video_stale).map(s=>s.id);
    generationChoices.set(project.id,new Set(ids));
  }
  const selected=generationChoices.get(project.id),valid=new Set(sortedShots().map(s=>s.id));
  for(const id of selected)if(!valid.has(id))selected.delete(id);
  return selected;
}
function selectedGenerationIds(){const selected=generationSelection();return sortedShots().filter(s=>selected.has(s.id)).map(s=>s.id)}
function rememberGenerationSelection(){try{localStorage.setItem('video-generation-'+project.id,JSON.stringify(selectedGenerationIds()))}catch{}}
function renderGenerationPickers(){
  const selected=generationSelection(),shots=sortedShots();
  for(const box of $$('[data-generation-picker]')){
    setStableHTML(box,`<div class="generation-picker-head"><strong>选择这次要生成的段落</strong><div><button class="ghost" data-pick-generation="all">全选</button><button class="ghost" data-pick-generation="missing">只选未完成</button><button class="ghost" data-pick-generation="none">清空</button></div></div><div class="generation-chips">${shots.map(s=>`<label><input type="checkbox" data-generate-shot="${esc(s.id)}" ${selected.has(s.id)?'checked':''}><b>${String(s.shot).padStart(2,'0')}</b> ${esc(s.title)} <small>${s.video&&!s.video_stale?'已有视频，可再生成':'待生成'}</small></label>`).join('')||'<span class="muted">先建立视频任务。</span>'}</div><p class="muted">按段号依次生成所选段落；已有视频会新增一个版本。完成后自行挑选合成，不会自动合片。</p>`);
    for(const input of box.querySelectorAll('[data-generate-shot]'))input.onchange=()=>{input.checked?selected.add(input.dataset.generateShot):selected.delete(input.dataset.generateShot);rememberGenerationSelection();renderGenerationPickers()};
    for(const button of box.querySelectorAll('[data-pick-generation]'))button.onclick=()=>{selected.clear();for(const s of shots)if(button.dataset.pickGeneration==='all'||button.dataset.pickGeneration==='missing'&&(!s.video||s.video_stale))selected.add(s.id);rememberGenerationSelection();renderGenerationPickers()};
  }
  for(const button of $$('[data-action="render_sequence"]')){setStableText(button,`依次生成所选段落（${selected.size}）`);button.disabled=!selected.size}
}
function shotVideoVersions(s){return s.video_versions|| (s.video?[{id:s.video,video:s.video,number:1,current:true,review:s.review}]:[])}
function assemblyVersion(s){return 'assembly_version_id' in s?s.assembly_version_id:(shotVideoVersions(s).find(v=>v.current)?.id??null)}
function selectedAssemblyClips(){return sortedShots().flatMap(s=>{const v=shotVideoVersions(s).find(v=>v.id===assemblyVersion(s));return v?[{shot_id:s.id,version_id:v.id}]:[]})}
async function ensureVideoChoices(){if(!(await api('/api/capabilities')).video_choices)throw new Error('当前任务完成后将更新服务；请暂勿提交分段生成或合成')}
async function saveVideoChoice(sid,versionId){
  const pid=project.id;
  try{await ensureVideoChoices();const fresh=await api(`/api/projects/${encodeURIComponent(pid)}/videos/${encodeURIComponent(sid)}/choice`,{method:'POST',body:JSON.stringify({version_id:versionId})});if(project?.id===pid){project=fresh;renderVideos();renderInspector()}}
  catch(e){toast(e.message);if(project?.id===pid)renderVideos()}
}
function videoChoiceCard(s){
  const versions=shotVideoVersions(s),selected=assemblyVersion(s),chosen=versions.find(v=>v.id===selected);
  return `<article class="video-card video-choice-card"><div class="video-choice-head"><div><span class="shot-no">第 ${String(s.shot).padStart(2,'0')} 段</span><h2>${esc(s.title||'视频')}</h2><small>${versions.length} 个版本 · 计划 ${s.duration??10} 秒</small></div><label class="assembly-include"><input type="checkbox" data-assembly-shot="${esc(s.id)}" ${chosen?'checked':''} ${versions.length?'':'disabled'}>参与合成</label><button class="ghost" data-regenerate-shot="${esc(s.id)}">再生成一版</button></div>${s.face_refine_report?.status==='skipped'?`<p class="reference-warning">面部精修已跳过：${esc((s.face_refine_report.warnings||[]).join('；')||'没有可用的人物参考')} · 原片保留</p>`:''}${s.video_stale?`<p class="reference-warning">当前镜头设置已变化，已有视频仍可预览并手动选入合片；继续生成时需核对尾帧衔接。</p>`:''}<div class="video-version-grid">${versions.map(v=>`<section class="video-version ${v.id===selected?'selected':''}"><label class="video-version-label"><input type="radio" name="take-${esc(s.id)}" data-assembly-version="${esc(v.id)}" data-choice-shot="${esc(s.id)}" ${v.id===selected?'checked':''}>版本 ${v.number}${v.id===selected?' · 已选合成':''}${v.current?' · 最新生成':''}</label><video controls preload="metadata" src="${media(v.video)}"></video>${v.video_result?.lip_sync?`<span class="color-version-badge">${v.video_result.lip_sync.mode==='musetalk'?'MuseTalk 1.5 嘴型版':'音轨同步版'} · ${v.video_result.lip_sync.offset_ms}ms</span>`:''}${v.video_result?.color_match?`<span class="color-version-badge">已校色 · 参考第 ${esc(v.video_result.color_match.reference.shot)} 段 · ${Math.round(v.video_result.color_match.settings.strength*100)}%</span>`:''}${v.video_result?.superseded?'<small class="reference-warning">生成期间已改稿 · 本版使用旧稿</small>':''}${v.video_result?.face_refine?`<span class="color-version-badge">H3 面部精修${(v.video_result.references||[]).filter(r=>(v.video_result.faces||[]).includes(r.id)).map(r=>r.name).length?' · '+esc((v.video_result.references||[]).filter(r=>(v.video_result.faces||[]).includes(r.id)).map(r=>r.name).join('、')):''}</span>${v.video_result.warnings?.length?`<small class="reference-warning">${esc(v.video_result.warnings.join('；'))}</small>`:''}`:''}<small>${v.created_at?esc(v.created_at.replace('T',' ')):'历史版本'}${v.duration?' · '+v.duration+' 秒':''}</small><div class="shot-actions">${v.current?`<button class="ghost" data-face-refine-shot="${esc(s.id)}">仅精修面部</button>`:''}<a class="ghost" href="${media(v.video)}" download>下载</a><button class="ghost" data-reveal-video="${esc(v.video)}">打开文件夹</button>${v.current?`<button class="ghost" data-review="${esc(s.id)}">检查漏洞</button><button class="ghost" data-delete-shot-video="${esc(s.id)}">删除视频</button>`:`<button class="ghost" data-delete-video-version="${esc(v.id)}" data-version-shot="${esc(s.id)}">删除版本</button>`}</div>${v.review?`<details><summary>质检结果</summary>${reviewHtml(v.review)}</details>`:''}</section>`).join('')||'<div class="frame">本段尚未生成，可在上方勾选后生成。</div>'}</div><div class="shot-actions">${deletedVideoControls(s)}</div>${s.video&&!s.video_stale?`<details class="version-enhancement"><summary>增强最新生成版本</summary>${enhanceControls(s,s.id,s.video)}</details>`:''}</article>`;
}
function renderVideoChoices(){
  const shots=sortedShots(),aspect=`${settings.video_width||16} / ${settings.video_height||9}`;
  $('#videoTimeline').style.setProperty('--video-aspect',aspect);$('#finalCut').style.setProperty('--video-aspect',aspect);
  const sources=project.final_sources;
  setStableHTML($('#finalCut'),project.final_video?`<article class="shot-card"><div class="shot-head"><span class="shot-no">FINAL CUT</span><span class="shot-title">已合成的视频${sources?.length?' · '+sources.length+' 段':''}</span></div><div class="shot-body"><video controls preload="metadata" style="width:100%;border-radius:8px" src="${media(project.final_video)}"></video><div>${reviewHtml(project.final_review)}<a class="ghost" href="${media(project.final_video)}" download>下载合成视频</a><button class="ghost" data-final-review>检查整片漏洞</button><button class="ghost" id="revealFinal">打开保存位置</button></div></div></article>${enhanceControls(project,'__final__',project.final_video)}`:'');
  renderKeyedHTML($('#videoTimeline'),shots.map(s=>({key:project.id+'/'+s.id,html:videoChoiceCard(s)})).concat(shots.length?[]:[{key:'empty',html:'<p class="muted">建立任务后，每段的所有视频版本会在这里显示。</p>'}]));
  const count=selectedAssemblyClips().length;
  for(const b of $$('[data-action="assemble"]')){setStableText(b,`合成所选视频（${count} 段）`);b.disabled=!count}
  for(const input of $$('[data-assembly-shot]')){const s=shots.find(s=>s.id===input.dataset.assemblyShot);input.checked=shotVideoVersions(s).some(v=>v.id===assemblyVersion(s));input.onchange=()=>{const s=shots.find(s=>s.id===input.dataset.assemblyShot),versions=shotVideoVersions(s);saveVideoChoice(s.id,input.checked?(versions.find(v=>v.current)||versions.at(-1))?.id:null)};}
  for(const input of $$('[data-assembly-version]')){input.checked=assemblyVersion(shots.find(s=>s.id===input.dataset.choiceShot))===input.dataset.assemblyVersion;input.onchange=()=>saveVideoChoice(input.dataset.choiceShot,input.dataset.assemblyVersion);}
  for(const b of $$('[data-regenerate-shot]'))b.onclick=()=>runAction('render_sequence',{shotIds:[b.dataset.regenerateShot]});
  for(const b of $$('[data-face-refine-shot]'))b.onclick=async()=>{try{if(!(await api('/api/capabilities')).face_refine?.ready)throw Error('面部精修等待工作台更新');await runAction('face_refine',{shotId:b.dataset.faceRefineShot})}catch(e){toast(e.message)}};
  for(const b of $$('[data-review]'))b.onclick=()=>runAction('review',{shotId:b.dataset.review});
  for(const b of $$('[data-reveal-video]'))b.onclick=()=>revealFile(b.dataset.revealVideo);
  const f=$('[data-final-review]');if(f)f.onclick=()=>runAction('review',{shotId:'__final__'});
  if($('#revealFinal'))$('#revealFinal').onclick=()=>revealFile(project.final_video);
  bindVideoDeleteButtons();renderGenerationPickers();if(typeof renderColorMatchPanel==='function')renderColorMatchPanel();
}
