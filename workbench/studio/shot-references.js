// Preview the current editor draft, never the last generation's saved reference list.
const shotViewNames={'front':'正面','three-quarter':'45° 斜侧面','side':'侧面','back':'背面'};
function shotViewKey(path){return path.split('/').at(-1).replace(/\.[^.]+$/,'')}
function draftNeedsMultiview(shot){
  if(shot.reference_angle_mode==='multi')return true;
  if(shot.reference_angle_mode==='main')return false;
  const text=[shot.camera,shot.motion_prompt,shot.description].join(' ').toLowerCase()
    .replace(/(?:不|无|避免|禁止)(?:进行)?(?:环绕|绕拍|旋转|转头|转身)/g,'')
    .replace(/\b(?:no|without)\s+(?:camera\s+)?(?:rotation|orbit(?:ing)?)\b/g,'');
  return /环绕|绕拍|绕行|旋转|转头|转身|摇镜|弧形运镜|侧面.*正面|正面.*侧面|\b(?:orbit\w*|rotat\w*|arc(?:ing)?|turn(?:s|ing)?\s+(?:his|her|their|the)\s+(?:head|body))\b/.test(text);
}
function resolveDraftElementImages(p,shot){
  const images=[],warnings=shot.auto_elements!==false&&shot.element_association_warning?[shot.element_association_warning]:[],multi=draftNeedsMultiview(shot);
  const excluded=new Set(shot.excluded_reference_images||[]);
  if(shot.use_element_references===false)return {images,warnings,multi};
  const entities=['characters','key_objects','locations'].flatMap(k=>p.analysis?.[k]||[]);
  const characters=new Set((p.analysis?.characters||[]).map(e=>e.id));
  for(const id of shot.element_ids||[]){
    const allViews=multi||(characters.has(id)&&shot.reference_angle_mode!=='main');
    let asset=p.assets?.[id]||{};
    const state=shot.character_states?.[id],variant=state&&asset.versions?.find(v=>v.id===state&&v.state_name&&v.status==='done');
    if(variant?.images?.length)asset={...asset,primary_image:variant.images[0],selected_images:[variant.images[0]]};
    const selected=[...new Set(asset.selected_images||[])];
    const name=entities.find(e=>e.id===id)?.name||id,primary=selected.includes(asset.primary_image)?asset.primary_image:selected[0];
    if(!selected.length){warnings.push(`${name}：尚未选用参考图`);continue}
    const version=asset.versions?.find(v=>v.images?.includes(primary));
    const byView=new Map((version?.images||[]).map(path=>[shotViewKey(path),path]));
    const complete=version?.status==='done'&&Object.keys(shotViewNames).every(view=>byView.has(view));
    const available=Object.keys(shotViewNames).filter(view=>byView.has(view)).map(view=>byView.get(view));
    const paths=(shot.reference_angle_mode==='main'?[primary]:[...new Set([...selected,...(allViews&&available.includes(primary)?available:[])])]).filter(path=>!excluded.has(path));
    if(!paths.length)continue;
    if(version?.reference_layout||['character-sheet','character-sheet-4view'].includes(shotViewKey(primary))){
      for(const path of paths)images.push({path,label:`${name} · ${shotViewKey(path)==='character-sheet-4view'?'人物四视图':'原有三栏设定图'}`});
      continue;
    }
    if(allViews&&!complete)warnings.push(`${name}：缺少多视角，将使用现有 ${paths.length} 张参考图生成（不阻止生成）`);
    if(allViews&&complete&&!version.views_verified)warnings.push(`${name}：请先确认本组正面、45°、侧面、背面均正确`);
    for(const path of paths)images.push({path,label:`${name} · ${shotViewNames[shotViewKey(path)]||'参考图'}`});
  }
  return {images:[...new Map(images.map(i=>[i.path,i])).values()],warnings,multi};
}
function shotReferenceDraft(card){
  const shot={...project.shots.find(s=>s.id===card.dataset.shotId),...collectShotReferenceDraft(card)};
  shot.element_ids=[...card.querySelectorAll('[data-task-element]:checked')].map(el=>el.dataset.taskElement);
  if(card.querySelector('[data-character-state]'))shot.character_states=Object.fromEntries([...card.querySelectorAll('[data-character-state]')].map(el=>[el.dataset.characterState,el.value]));
  for(const el of card.querySelectorAll('[data-task-field]'))shot[el.dataset.taskField]=el.value;
  const editor=card.querySelector('[data-complete-prompt]');if(editor){try{Object.assign(shot,parseShotPrompt(editor.value))}catch{}}
  const english=card.querySelector('[data-english-prompt]');if(english&&!editor?.value.includes('【H3 英文提示词】'))shot.motion_prompt=english.value;
  return shot;
}
function referencePreviewTile(path,label,removeIndex=null,removableElement=false){
  return `<figure><button type="button" class="image-preview-button" data-ref-preview="${esc(path)}" aria-label="预览 ${esc(label)}"><img loading="lazy" src="${media(path)}" alt="${esc(label)}"></button>${removableElement?`<button type="button" class="reference-remove" data-exclude-reference="${esc(path)}" aria-label="取消参考 ${esc(label)}" title="不用于当前镜头（不删除原图）">×</button>`:''}<figcaption>${esc(label)}</figcaption>${removeIndex===null?'':`<button type="button" class="ghost" data-remove-manual="${removeIndex}">移除</button>`}</figure>`;
}
function excludeShotReference(card,path){
  card.excludedReferencePaths=[...new Set([...(card.excludedReferencePaths||[]),path])];
  card.manualReferencePaths=(card.manualReferencePaths||[]).filter(p=>p!==path);
  updateShotReferencePreview(card,true);
}
function updateShotReferencePreview(card,dirty=false){
  if(dirty)card.referenceDirty=true;
  const shot=shotReferenceDraft(card),resolved=resolveDraftElementImages(project,shot);
  updateShotModePreview(card,shot);
  card.querySelector('[data-element-preview]').innerHTML=resolved.images.map(r=>referencePreviewTile(r.path,r.label,null,true)).join('')||`<p class="muted">${shot.use_element_references===false?'已关闭元素参考图':'当前没有可用的元素参考图；可勾选元素或恢复已排除图片'}</p>`;
  if(card.excludedReferencePaths?.length)card.querySelector('[data-element-preview]').insertAdjacentHTML('beforeend',`<p class="muted reference-exclusions">已排除 ${card.excludedReferencePaths.length} 张图片，仅作用于本镜头。<button type="button" class="ghost" data-restore-reference-images>恢复已排除图片</button></p>`);
  const ordered=[...project.shots].sort((a,b)=>Number(a.shot)-Number(b.shot)),index=ordered.findIndex(s=>s.id===shot.id),previous=index>0?ordered[index-1]:null;
  const inherit=!!previous&&shot.inherit_previous!==false;
  const tail=inherit&&previous.video&&!previous.video_stale&&previous.tail_source_video===previous.video?previous.actual_tail_frame:null;
  card.querySelector('[data-tail-preview]').innerHTML=inherit?`<h4>上一段尾帧</h4>${tail?`<p class="muted">原始尾帧与修复接续图见卡片底部接续预览。</p>`:'<p class="muted">将在生成本段前，从上一段有效视频提取。</p>'}`:'';
  const manual=(card.manualReferencePaths||[]).filter(path=>!(card.excludedReferencePaths||[]).includes(path)),pending=card.pendingReferenceFiles||[];
  card.querySelector('[data-manual-preview]').innerHTML=manual.map((path,i)=>{
    const upload=project.uploads?.find(u=>u.path===path);
    return referencePreviewTile(path,upload?.name||`已添加的补充图 ${i+1}`,card.manualReferencePaths.indexOf(path));
  }).join('')+pending.map((item,i)=>`<figure><button type="button" class="image-preview-button" data-local-preview="${i}" aria-label="预览 ${esc(item.file.name)}"><img src="${esc(item.url)}" alt="${esc(item.file.name)}"></button><figcaption>${esc(item.file.name)} · 待保存</figcaption><button type="button" class="ghost" data-remove-pending="${i}">移除</button></figure>`).join('')||'<p class="muted">尚未添加外部照片</p>';
  const count=(!inherit&&shot.opening_reference_image?1:0)+new Set([...resolved.images.map(r=>r.path),...manual,...(tail?[tail]:[])]).size+pending.length;
  const warnings=[...resolved.warnings];
  if(shot.audio_segment&&shot.audio_segment.mode!=='generated'&&draftGenerationMode(shot)!=='omni_reference')warnings.push('本段音轨只在合成时使用；当前模式不输入声音参考，无法以原音引导口型');
  if(count+(inherit&&!tail?1:0)>9)warnings.push('h3.c 最多支持 9 张参考图（包含上一段尾帧），请减少引用数量');
  const extra=[...(card.omniMedia||[])];if(shot.audio_segment&&shot.audio_segment.mode!=='generated'&&!extra.some(r=>r.path===shot.audio_segment.path))extra.push({path:shot.audio_segment.path,kind:'audio'});const queued=(card.pendingModeFiles||[]).filter(r=>!r.target.endsWith('_image'));
  const videoCount=extra.filter(r=>r.kind!=='audio').length+queued.filter(r=>r.target!=='audio').length;
  const audioCount=extra.filter(r=>r.kind==='audio'||r.kind==='video').length+queued.filter(r=>r.target==='audio').length;
  if(videoCount>3||audioCount>3||count+extra.length+queued.length+(inherit&&!tail?1:0)>12)warnings.push('全能参考数量超限：视频最多3段、音频最多3路，全部素材合计最多12项');
  card.querySelector('[data-reference-warnings]').innerHTML=warnings.map(w=>`<p class="reference-warning">${esc(w)}</p>`).join('');
  card.querySelector('[data-reference-summary]').textContent=`${card.referenceDirty||pending.length?'当前预览（未保存）':'当前预览'}：元素 ${resolved.images.length} 张，补充 ${manual.length+pending.length} 张${inherit?tail?'，尾帧 1 张':'，尾帧待提取':shot.opening_reference_image?'，高清开场参考 1 张':''}。${card.excludedReferencePaths?.length?'已按单张图片排除，实际仅使用当前预览中的图片。':shot.reference_angle_mode==='main'?'手动覆盖：仅一张辅助参考图。':resolved.multi?'旋转／多角度镜头：人物设定图或旧多视角，其他元素使用可用多视角。':'人物优先使用已选设定图；旧四视图保留原规则，其他元素使用已选参考图。'} 生成要求：画面不含文字。`;
  if(extra.length||queued.length)card.querySelector('[data-reference-summary]').textContent+=` 视频 ${videoCount} 段，音频 ${audioCount} 路（含勾选的视频声音）。`;
  for(const button of card.querySelectorAll('[data-exclude-reference]'))button.onclick=()=>excludeShotReference(card,button.dataset.excludeReference);
  const restoreImages=card.querySelector('[data-restore-reference-images]');
  if(restoreImages)restoreImages.onclick=()=>{card.excludedReferencePaths=[];updateShotReferencePreview(card,true)};
  for(const button of card.querySelectorAll('[data-ref-preview]'))button.onclick=()=>showImagePreview(button.dataset.refPreview);
  for(const button of card.querySelectorAll('[data-local-preview]'))button.onclick=()=>{
    const item=card.pendingReferenceFiles[Number(button.dataset.localPreview)];
    const dialog=document.createElement('dialog');dialog.className='image-preview-dialog local-reference-preview';
    dialog.innerHTML='<button type="button" aria-label="关闭图片预览">关闭</button><p></p><img alt="补充参考图预览">';
    dialog.querySelector('p').textContent=item.file.name;dialog.querySelector('img').src=item.url;
    dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
  };
  for(const button of card.querySelectorAll('[data-remove-manual]')){button.disabled=!!card.refsUploading;button.onclick=()=>{card.manualReferencePaths.splice(Number(button.dataset.removeManual),1);updateShotReferencePreview(card,true)}}
  for(const button of card.querySelectorAll('[data-remove-pending]')){button.disabled=!!card.refsUploading;button.onclick=()=>{const [item]=card.pendingReferenceFiles.splice(Number(button.dataset.removePending),1);URL.revokeObjectURL(item.url);updateShotReferencePreview(card,true)}}
}
function addShotReferenceFiles(card,files){
  if(card.refsUploading)return toast('正在保存参考图，请稍候');
  card.pendingReferenceFiles??=[];
  for(const file of files){
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)){toast(`${file.name}：仅支持 PNG、JPG、WEBP 图片`);continue}
    if(file.size>30*1024*1024){toast(`${file.name}：图片不能超过 30MB`);continue}
    if(card.pendingReferenceFiles.some(x=>x.file.name===file.name&&x.file.size===file.size&&x.file.lastModified===file.lastModified))continue;
    card.pendingReferenceFiles.push({file,url:URL.createObjectURL(file)});
  }
  updateShotReferencePreview(card,true);
}
function bindShotReferencePreview(card){
  card.referenceDirty=false;
  const saved=project.shots.find(s=>s.id===card.dataset.shotId);
  const notice=document.createElement('p');notice.className='muted';
  notice.textContent=saved.auto_elements===false?'当前为手动元素清单。':`按来源场次自动关联${saved.source_scene_indices?.length?' · 第 '+saved.source_scene_indices.join('、')+' 场':''}；可手动增删，普通保存不会关闭自动关联。`;
  const restore=document.createElement('button');restore.type='button';restore.className='ghost';restore.textContent='恢复自动关联';
  restore.onclick=()=>{
    card.restoreAutoElements=true;card.elementSelectionDirty=false;
    for(const input of card.querySelectorAll('[data-task-element]'))input.checked=(saved.suggested_element_ids||[]).includes(input.dataset.taskElement);
    notice.textContent='已恢复按出场场次自动关联（待保存）';updateShotReferencePreview(card,true);
  };
  card.querySelector('.shot-references').prepend(notice,restore);
  for(const el of card.querySelectorAll('[data-task-element], [data-element-refs], [data-inherit-tail], [data-angle-mode]'))el.onchange=()=>{
    if(el.matches('[data-task-element]'))card.elementSelectionDirty=true;
    if(el.matches('[data-inherit-tail]')){card.tailSelectionDirty=true;if(el.checked){card.querySelector('[data-generation-mode]').value='first_frame';card.querySelector('[data-first-source]').value='previous_tail';}else if(card.querySelector('[data-first-source]').value==='previous_tail')card.querySelector('[data-first-source]').value='image';}
    updateShotReferencePreview(card,true);
  };
  for(const el of card.querySelectorAll('[data-task-field], [data-complete-prompt], [data-english-prompt]'))el.oninput=()=>updateShotReferencePreview(card,true);
  const input=card.querySelector('[data-shot-upload]'),drop=card.querySelector('[data-shot-drop]');
  input.onchange=()=>{addShotReferenceFiles(card,[...input.files]);input.value=''};
  drop.onkeydown=e=>{if(e.target===drop&&['Enter',' '].includes(e.key)){e.preventDefault();input.click()}};
  drop.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';drop.classList.add('drag-over')};
  drop.ondragleave=e=>{if(!drop.contains(e.relatedTarget))drop.classList.remove('drag-over')};
  drop.ondrop=e=>{e.preventDefault();e.stopPropagation();drop.classList.remove('drag-over');addShotReferenceFiles(card,[...e.dataTransfer.files])};
  updateShotReferencePreview(card);
}
async function uploadPendingShotReferences(card,pid){
  if(!card.pendingReferenceFiles?.length)return;
  card.refsUploading=true;updateShotReferencePreview(card);
  try{
    while(card.pendingReferenceFiles.length){
      const item=card.pendingReferenceFiles[0],data=new FormData();
      data.append('file',item.file);data.append('name',item.file.name);
      // Upload the file only; attach it to the shot atomically with the editor save.
      const response=await fetch(`/api/projects/${pid}/upload`,{method:'POST',body:data}),entry=await response.json();
      if(!response.ok)throw new Error(entry.error||'补充参考图上传失败');
      card.manualReferencePaths.push(entry.path);card.pendingReferenceFiles.shift();URL.revokeObjectURL(item.url);
      if(project.id!==pid)throw new Error('项目已切换；图片已保存在原项目上传目录，请返回原项目重新选择');
      project.uploads??=[];project.uploads.push(entry);updateShotReferencePreview(card,true);
    }
    renderUploads();
  }finally{card.refsUploading=false;if(project.id===pid&&card.isConnected)updateShotReferencePreview(card)}
}
function releaseShotReferencePreviews(){
  for(const card of $$('#shotsGrid [data-shot-id]'))for(const item of [...(card.pendingReferenceFiles||[]),...(card.pendingModeFiles||[])])URL.revokeObjectURL(item.url);
}
window.addEventListener('beforeunload',event=>{
  if($$('#shotsGrid [data-shot-id]').some(card=>card.pendingReferenceFiles?.length||card.pendingModeFiles?.length)){event.preventDefault();event.returnValue=''}
});
