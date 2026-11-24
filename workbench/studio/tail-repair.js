const tailModeNames={raw:'原始尾帧',review:'轻修复 · 先预览再采用',auto:'轻修复 · 连续自动采用',qwen_auto:'Qwen 多图重绘 · 自动接续',qwen_review:'Qwen 多图重绘 · 先预览再采用'};
const tailDefaultDrafts=new Map();
function tailDefaultDraft(){
  if(!tailDefaultDrafts.has(project.id))tailDefaultDrafts.set(project.id,{mode:'raw',reference:'',...project.tail_repair_defaults});
  return tailDefaultDrafts.get(project.id);
}
function tailOptions(choices,value,empty){return `<option value="">${empty}</option>`+choices.map(r=>`<option value="${esc(r.path)}" ${r.path===value?'selected':''}>${esc(r.label)}</option>`).join('')}
function renderTailDefaults(){
  const box=$('#tailRepairPanel');if(!box||!project)return;
  const d=tailDefaultDraft();
  setStableHTML(box,`<details class="tail-defaults"><summary>尾帧接续与固定颜色参考</summary><p class="muted">同一场景一直使用同一张颜色基准。默认设置只作用于后续生成，已有视频保留。</p><label>默认尾帧处理<select data-tail-default-mode>${Object.entries(tailModeNames).map(([v,n])=>`<option value="${v}" ${d.mode===v?'selected':''}>${n}</option>`).join('')}</select></label><label>固定颜色参考<select data-tail-default-ref>${tailOptions(shotImageChoices({}),d.reference,'可选：清晰的场景颜色基准（轻修复必填）')}</select></label><label class="mode-upload">上传颜色参考图片<input type="file" accept="image/png,image/jpeg,image/webp" data-tail-default-upload></label>${d.reference?`<div class="tail-reference-small"><img src="${media(d.reference)}" alt="固定颜色参考"></div>`:''}<button class="primary" data-tail-default-save>保存接续设置</button><p class="muted">轻修复：实际尾帧 → 有限幅度校色 → Real-ESRGAN 2×。先预览模式会在待确认处结束队列；采用后再勾选剩余段落生成。自动模式可连续运行，仍保留原图与修复版。不同场景可在各段覆盖参考图。Qwen 多图重绘：尾帧为主画面，读取本段已选的 1–2 位角色图作外貌参考；每位优先采用已选四视图，否则采用首张已选图。输出长边约 1280，8 步，完成后释放 Qwen 再启动 H3。自动接续仍需本段开启尾帧继承，不自动改变换镜设置。</p></details>`);
  box.querySelector('[data-tail-default-mode]').onchange=e=>{d.mode=e.target.value};
  box.querySelector('[data-tail-default-ref]').onchange=e=>{d.reference=e.target.value;renderTailDefaults();box.querySelector('details').open=true};
  box.querySelector('[data-tail-default-upload]').onchange=async e=>{
    try{
      const file=e.target.files[0];if(!file)return;
      if(file.size>30*1024*1024)throw new Error('图片不能超过 30MB');
      const pid=project.id,body=new FormData();body.append('file',file);
      const response=await fetch(`/api/projects/${pid}/upload`,{method:'POST',body}),entry=await response.json();
      if(!response.ok)throw new Error(entry.error||'上传失败');
      if(project.id!==pid)return;
      project.uploads??=[];project.uploads.push(entry);d.reference=entry.path;
      renderTailDefaults();box.querySelector('details').open=true;
    }catch(error){toast(error.message)}
  };
  box.querySelector('[data-tail-default-save]').onclick=async()=>{
    try{
      const pid=project.id;
      const saved=await api(`/api/projects/${pid}/tail-repair/settings`,{method:'POST',body:JSON.stringify(d)});
      if(project.id!==pid)return;
      project=saved;syncTailRepair();toast('接续设置已保存；已有视频保留');
    }catch(error){toast(error.message)}
  };
}
function tailShotControls(s,choices){
  return `<section class="tail-controls" data-tail-controls><h4>尾帧优化 · 用于本段接续</h4><label class="task-inherit"><input type="checkbox" data-tail-enable>启用尾帧优化 <small>Qwen-Image-Edit-2511 多图重绘：尾帧为主，角色图为参考</small></label><label>处理方式<select data-tail-mode><option value="">沿用工程默认</option>${Object.entries(tailModeNames).map(([v,n])=>`<option value="${v}" ${s.tail_repair_mode===v?'selected':''}>${n}</option>`).join('')}</select></label><details><summary>本段换用其他场景颜色基准</summary><select data-frame-choice="tail_reference_image">${tailOptions(choices,s.tail_reference_image,'沿用固定颜色参考')}</select><label class="mode-upload">上传颜色参考<input type="file" accept="image/png,image/jpeg,image/webp" data-mode-upload="tail_reference_image"></label></details><div data-tail-status></div><button class="ghost" type="button" data-tail-cut>换镜头：关闭尾帧继承</button><p class="muted">人物身份与服装继续读取原始高清人物图；尾帧提供姿态与构图。颜色调整后仍需在合成前检查前后片段的亮度衔接。</p></section><section class="tail-controls" data-opening-controls><label>换镜头高清开场参考（可选）<select data-frame-choice="opening_reference_image">${tailOptions(choices,s.opening_reference_image,'按人物参考与文字重新构图')}</select></label><label class="mode-upload">上传高清开场参考<input type="file" accept="image/png,image/jpeg,image/webp" data-mode-upload="opening_reference_image"></label><div data-opening-preview></div><p class="muted">全能参考保留原人物图与录音，以此图引导新构图；它不是强制首帧。需要严格首帧条件时可选“首帧生视频”，该模式不会输入录音参考。</p></section>`;
}
function updateTailRepair(card,shot){
  const controls=card.querySelector('[data-tail-controls]');if(!controls)return;
  const ordered=sortedShots(),index=ordered.findIndex(s=>s.id===shot.id),prev=ordered[index-1];
  const active=!!prev&&modeUsesPrevious(shot);
  controls.hidden=!active;
  const opening=card.querySelector('[data-opening-controls]');opening.hidden=draftGenerationMode(shot)!=='omni_reference'||active;
  const pendingOpen=(card.pendingModeFiles||[]).find(x=>x.target==='opening_reference_image');
  card.querySelector('[data-opening-preview]').innerHTML=pendingOpen?`<img class="tail-opening-image" src="${esc(pendingOpen.url)}" alt="待上传开场参考">`:shot.opening_reference_image?`<img class="tail-opening-image" src="${media(shot.opening_reference_image)}" alt="高清开场参考">`:'';
  const defaults=project.tail_repair_defaults||{},mode=shot.tail_repair_mode||defaults.mode||'raw',reference=shot.tail_reference_image||defaults.reference||'';
  const referenceLabel=project.uploads?.find(u=>u.path===reference)?.name||reference.split('/').at(-1);
  const saved=project.shots.find(s=>s.id===shot.id),v=saved.tail_repair_view||{};
  const matches=v.reference===reference&&v.mode===mode&&!(card.pendingModeFiles||[]).some(x=>x.target==='tail_reference_image');
  const result=matches?v.result:null,approved=matches&&v.approved;
  const qwen=mode.startsWith('qwen_');
  const enable=card.querySelector('[data-tail-enable]');if(enable){enable.checked=mode!=='raw';enable.onchange=()=>{card.querySelector('[data-tail-mode]').value=enable.checked?'qwen_auto':'raw';updateShotReferencePreview(card,true)}}
  const refs=matches?(v.character_references||[]):[];
  const original=result?.original||(prev?.tail_source_video===prev?.video&&!prev?.video_stale?prev?.actual_tail_frame:null);
  const box=card.querySelector('[data-tail-status]');
  setStableHTML(box,`<p>${esc(tailModeNames[mode])}${approved?' · 已采用修复版':result?' · 待预览采用':''}</p>${reference?`<p class="muted">固定基准：${esc(referenceLabel)}</p>`:mode!=='raw'&&!qwen?'<p class="reference-warning">请先在本页顶部保存固定颜色参考。</p>':qwen?'<p class="muted">未指定颜色基准，将保持尾帧原有色调。</p>':''}${(card.pendingModeFiles||[]).some(x=>x.target==='tail_reference_image')?'<p class="muted">颜色参考上传待保存</p>':''}${qwen?`<p class="muted">主画面：上一段实际尾帧。角色图仅参考外貌，不复制角色图姿势；每次约数分钟至十几分钟或更久。</p>${matches&&v.reference_error?`<p class="reference-warning">${esc(v.reference_error)}</p>`:""}${refs.length?`<div class="tail-character-refs">${refs.map(r=>`<figure><img src="${media(r.preview_path)}" alt="${esc(r.label)}角色参考"><figcaption>${esc(r.label)} · 外貌参考</figcaption></figure>`).join("")}</div>`:""}`:""}<div class="tail-compare">${original?`<figure><a href="${media(original)}" target="_blank"><img src="${media(original)}" alt="原始实际尾帧"></a><figcaption>原始实际尾帧</figcaption></figure>`:''}${result?`<figure><a href="${media(result.repaired)}" target="_blank"><img src="${media(result.repaired)}" alt="校色与高清修复后"></a><figcaption>${result.model==='Qwen-Image-Edit-2511'?'Qwen 多图重绘':'校色＋Real-ESRGAN 2×'} · <a href="${media(result.repaired)}" download>下载</a></figcaption></figure>`:''}</div>${mode!=='raw'?`<div class="shot-actions"><button class="ghost" data-tail-prepare ${!prev?.video||prev?.video_stale?'disabled':''}>${result?'重新生成优化尾帧':qwen?'保存并重绘尾帧':'保存并修复预览'}</button>${result&&['review','qwen_review'].includes(mode)&&!approved?'<button class="primary" data-tail-approve>采用修复尾帧</button>':''}</div>`:''}`);
  const prep=box.querySelector('[data-tail-prepare]');if(prep)prep.onclick=async()=>{try{const pid=project.id;await saveTextShots(shot.id);if(project.id===pid)await runAction('repair_tail',{shotId:shot.id,force:!!result})}catch(e){toast(e.message)}};
  const approve=box.querySelector('[data-tail-approve]');if(approve)approve.onclick=async()=>{
    try{const pid=project.id;const updated=await api(`/api/projects/${pid}/tail-repair/approve`,{method:'POST',body:JSON.stringify({shot_id:shot.id,signature:result.signature})});if(project.id!==pid)return;project=updated;syncTailRepair();toast('已采用；下一次生成将使用此修复尾帧')}catch(e){toast(e.message)}
  };
  card.querySelector('[data-tail-cut]').onclick=()=>{
    card.querySelector('[data-inherit-tail]').checked=false;card.tailSelectionDirty=true;
    if(draftGenerationMode(shot)==='first_frame')card.querySelector('[data-first-source]').value='image';
    updateShotReferencePreview(card,true);toast('已关闭继承，请选择新开场图片并保存本段设置');
  };
}
function syncTailRepair(){
  for(const card of $$('#shotsGrid [data-shot-id]'))if(card.querySelector('[data-tail-controls]'))updateTailRepair(card,shotReferenceDraft(card));
}
