// Qwen composition references belong to shots, never to character source boxes.
const openingFrameSelections=new Map();
function openingFrameRows(){return project?.opening_frame_catalog||[]}
async function ensureOpeningFramesBackend(){if(!(await api('/api/capabilities')).opening_qwen_frames)throw new Error('Qwen 剧情首帧需要新版工作台，请刷新后重试')}
function renderOpeningFrames(){
  const box=$('#openingFramesPanel');if(!box||!project)return;
  const rows=openingFrameRows();
  if(!openingFrameSelections.has(project.id))openingFrameSelections.set(project.id,new Set());
  const chosen=openingFrameSelections.get(project.id);
  setStableHTML(box,`<section class="opening-frames"><div class="section-head"><div><h2>剧情首帧参考 · Qwen 多图重绘</h2><p class="muted">按各段已保存的起始构图，结合 2–3 个已选人物、物品或场景成品图生成单张高清开场图。只生成勾选段落，原视频与旧图保留。</p></div></div><div class="toolbar"><button class="ghost" data-opening-select="missing">选择缺少有效首帧的段落</button><button class="ghost" data-opening-select="all">全选可生成段落</button><button class="ghost" data-opening-select="none">清空</button><button class="primary" data-opening-generate>生成所选首帧</button></div><label class="task-inherit"><input type="checkbox" data-opening-force>重新生成已存在的首帧 <small>不勾选时复用构图、参考和尺寸一致的结果</small></label><p class="muted">先在下方勾选元素成品图，并保存剧本／04 的起始构图。首帧画幅随视频设置，长边至少约 1280；8 步。Qwen 完成后释放模型，再启动 H3。首尾帧模式不向 H3 输入录音参考，绑定原音仍用于后期混音。</p><div class="opening-frame-grid">${rows.map(row=>`<article class="opening-frame-card"><label class="task-inherit"><input type="checkbox" data-opening-shot="${esc(row.id)}" ${chosen.has(row.id)?'checked':''} ${row.ready?'':'disabled'}>第 ${esc(row.shot)} 段 · ${esc(row.title||'')}</label><p class="opening-state">${esc(row.opening||'未填写起始构图与状态')}</p>${row.ready?`<small>${row.width}×${row.height} · ${row.result?'有效首帧已生成':'待生成'}</small><div class="opening-ref-list">${(row.references||[]).map(r=>`<figure><img loading="lazy" src="${media(r.preview_path)}" alt="${esc(r.label)}参考"><figcaption>${esc(r.label)}</figcaption></figure>`).join('')}</div>`:`<p class="reference-warning">${esc(row.error)}</p>`}${row.result?openingResultTile(row,row.result,true):''}${row.versions?.length?`<details><summary>首帧版本 · ${row.versions.length}</summary>${[...row.versions].reverse().filter(v=>v.image!==row.result?.image).map(v=>openingResultTile(row,v,false)).join('')||'<p class="muted">暂无其他版本</p>'}</details>`:''}</article>`).join('')||'<p class="muted">保存逐段剧本后在这里选择首帧；尚未输出 04 时也可先生成。</p>'}</div></section>`);
  for(const input of box.querySelectorAll('[data-opening-shot]'))input.onchange=()=>{input.checked?chosen.add(input.dataset.openingShot):chosen.delete(input.dataset.openingShot)};
  for(const button of box.querySelectorAll('[data-opening-select]'))button.onclick=()=>{chosen.clear();if(button.dataset.openingSelect!=='none')for(const row of rows)if(row.ready&&(button.dataset.openingSelect==='all'||!row.result))chosen.add(row.id);renderOpeningFrames()};
  box.querySelector('[data-opening-generate]').onclick=async()=>{
    try{await ensureOpeningFramesBackend();const shotIds=rows.filter(r=>r.ready&&chosen.has(r.id)).map(r=>r.id);if(!shotIds.length)throw new Error('请先勾选需要生成首帧的段落');await runAction('opening_frames',{shotIds,force:box.querySelector('[data-opening-force]').checked})}catch(e){toast(e.message)}
  };
  for(const button of box.querySelectorAll('[data-opening-preview]'))button.onclick=()=>showImagePreview(button.dataset.openingPreview);
  for(const button of box.querySelectorAll('[data-opening-adopt]'))button.onclick=async()=>{
    try{
      const pid=project.id,sid=button.dataset.openingAdopt;
      const fresh=await api(`/api/projects/${pid}`);if(project?.id!==pid)return;
      const row=fresh.opening_frame_catalog?.find(r=>r.id===sid);
      if(!row?.result||row.result.image!==button.dataset.path)throw new Error('构图或参考已变化，请重新生成首帧');
      const shot=fresh.shots.find(s=>s.id===sid);if(!shot)throw new Error('请先输出 04 视频任务，再选用首帧');
      const changes=button.dataset.role==='reference'?{generation_mode:'omni_reference',inherit_previous:false,opening_reference_image:row.result.image}: {generation_mode:'first_frame',first_frame_source:'image',first_frame_image:row.result.image};
      const updated=await api(`/api/projects/${pid}/save`,{method:'POST',body:JSON.stringify({shots:fresh.shots.map(s=>s.id===sid?{...s,...changes}:s)})});
      if(project?.id!==pid)return;project=updated;renderOpeningFrames();refreshOpeningShotPanels(sid,changes);renderVideos();renderInspector();
      toast(button.dataset.role==='reference'?'已设置开场参考；用于不继承尾帧的全能参考段落':'已用作本段首帧，并切为首尾帧模式；原视频保留为历史版');
    }catch(e){toast(e.message)}
  };
}
function refreshOpeningShotPanels(adoptedId=null,changes={}){
  for(const card of $$('#shotsGrid [data-shot-id]')){
    if(!card.querySelector('[data-mode-panel]'))continue;
    const draft=shotReferenceDraft(card);
    if(card.dataset.shotId===adoptedId)Object.assign(draft,changes);
    const index=sortedShots().findIndex(s=>s.id===card.dataset.shotId);
    renderShotModePanel(card,draft,index);updateShotReferencePreview(card,true);
  }
}
function openingResultTile(row,result,current){
  const realShot=project.shots?.some(s=>s.id===row.id);
  return `<figure class="opening-result"><button class="image-preview-button" data-opening-preview="${esc(result.image)}"><img loading="lazy" src="${media(result.image)}" alt="第 ${esc(row.shot)} 段剧情首帧"></button><figcaption>${current?'当前有效首帧':result.superseded?'旧输入版本':'历史版本'} · ${esc(result.created_at?.replace('T',' ')||'')} · <a href="${media(result.image)}" download>下载高清图</a></figcaption>${current&&realShot?`<div class="toolbar"><button class="ghost" data-opening-adopt="${esc(row.id)}" data-path="${esc(result.image)}" data-role="anchor">用作本段首帧</button><button class="ghost" data-opening-adopt="${esc(row.id)}" data-path="${esc(result.image)}" data-role="reference">用作全能开场参考</button></div>`:current?'<small>输出 04 任务后可选择本图；自动 Qwen 首帧也会复用它。</small>':''}</figure>`;
}
