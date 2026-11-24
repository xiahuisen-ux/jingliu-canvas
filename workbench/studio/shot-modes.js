let shotModeBackendCheck;
async function ensureShotModeBackend(){
  shotModeBackendCheck??=api('/api/video-backends').then(state=>{
    if(!['text','first_frame','omni_reference'].every(mode=>state.h3c?.generation_modes?.includes(mode)))throw new Error('分段模式功能等待后端更新；请等当前生成任务结束并重启工作台后刷新页面');
    return true;
  }).catch(error=>{shotModeBackendCheck=null;throw error});
  return shotModeBackendCheck;
}
const generationModeNames={text:'文生视频',first_frame:'首尾帧生视频',omni_reference:'全能参考'};
function draftGenerationMode(shot){return shot.generation_mode||'omni_reference'}
function modeUsesPrevious(shot){return draftGenerationMode(shot)==='first_frame'?shot.first_frame_source==='previous_tail':draftGenerationMode(shot)==='omni_reference'&&shot.inherit_previous!==false}
function collectShotModeDraft(card){
  if(!card.querySelector('[data-generation-mode]'))return {};
  return {generation_mode:card.querySelector('[data-generation-mode]').value,
    first_frame_source:card.querySelector('[data-first-source]').value,
    first_frame_image:card.querySelector('[data-frame-choice="first_frame_image"]').value,
    last_frame_image:card.querySelector('[data-frame-choice="last_frame_image"]').value,
    tail_repair_mode:card.querySelector('[data-tail-mode]')?.value||'',
    tail_reference_image:card.querySelector('[data-frame-choice="tail_reference_image"]')?.value||'',
    opening_reference_image:card.querySelector('[data-frame-choice="opening_reference_image"]')?.value||'',
    omni_media:(card.omniMedia||[]).map(r=>({...r}))};
}
function shotImageChoices(s){
  const entries=new Map();
  const add=(path,label)=>{if(path&&/\.(png|jpe?g|webp)$/i.test(path)&&(!entries.has(path)||label))entries.set(path,label||path.split('/').at(-1))};
  for(const upload of project.uploads||[])add(upload.path,upload.name);
  for(const [id,asset] of Object.entries(project.assets||{})){
    const name=progressEntities(project).find(e=>e.id===id)?.name||id;
    for(const path of [...(asset.selected_images||[]),...(asset.versions||[]).flatMap(v=>v.images||[])])add(path,name+' · '+path.split('/').at(-1));
  }
  for(const shot of project.shots||[])for(const k of ['start_frame','end_frame','actual_tail_frame','first_frame_image','last_frame_image','opening_reference_image'])add(shot[k]);
  for(const result of project.opening_frames||[])add(result.image,'Qwen 剧情首帧 · '+(result.created_at||''));
  return [...entries].map(([path,label])=>({path,label}));
}
function renderShotModePanel(card,s,index){
  const foldOpen=card.querySelector('[data-frame-details]')?.open;
  card.querySelector('[data-mode-panel]')?.remove();
  card.omniMedia=(s.omni_media||[]).map(r=>({...r}));
  card.modeMediaHTML=null;
  card.pendingModeFiles??=[];
  const choices=shotImageChoices(s),frameControl=(key,label)=>`<div class="frame-input"><label>${label}<select data-frame-choice="${key}"><option value="">${key==='last_frame_image'?'不指定尾帧':'请选择图片'}</option>${choices.map(r=>`<option value="${esc(r.path)}" ${s[key]===r.path?'selected':''}>${esc(r.label)}</option>`).join('')}</select></label><label class="mode-upload">上传${key==='first_frame_image'?'首帧':'尾帧'}图片<input type="file" accept="image/png,image/jpeg,image/webp" data-mode-upload="${key}"></label><div class="shot-ref-thumbs" data-frame-preview="${key}"></div></div>`;
  (card.querySelector('[data-mode-slot]')||card.querySelector('.text-shot-body')).insertAdjacentHTML('afterbegin',`<section class="shot-mode-panel" data-mode-panel><div class="task-settings-row"><label class="mode-select-label">本段生成模式<select data-generation-mode>${Object.entries(generationModeNames).map(([value,label])=>`<option value="${value}" ${draftGenerationMode(s)===value?'selected':''}>${label}</option>`).join('')}</select></label><label>视频时长<select data-task-field="duration">${Array.from({length:11},(_,i)=>i+5).map(d=>`<option value="${d}" ${d===Number(s.duration??5)?'selected':''}>${d} 秒</option>`).join('')}</select></label></div><label class="task-inherit"><input type="checkbox" data-inherit-tail ${index?'':'disabled'} ${index&&modeUsesPrevious(s)?'checked':''}>自动继承上一段尾帧 <small>${index?'启用后切换为首尾帧模式；优先使用已采用的优化尾帧':'第一段不适用'}</small></label><p class="mode-description" data-mode-description aria-live="polite"></p><p class="reference-warning" data-mode-server-status></p><details class="task-fold" data-frame-details><summary>首帧／尾帧图片 <small>首尾帧模式使用 · 支持拖入图片</small></summary><div data-frame-mode><label>首帧来源<select data-first-source><option value="image" ${!['previous_tail','qwen'].includes(s.first_frame_source)?'selected':''}>上传或选择图片</option><option value="qwen" ${s.first_frame_source==='qwen'?'selected':''}>Qwen 多图重绘 · 按本段起始构图自动生成</option><option value="previous_tail" ${s.first_frame_source==='previous_tail'?'selected':''} ${index?'':'disabled'}>上一段视频的实际尾帧${index?'':'（第一段不可用）'}</option></select></label><div data-first-image-controls>${frameControl('first_frame_image','首帧图片')}</div><div class="qwen-opening-note muted" data-qwen-opening-preview></div><div class="shot-ref-thumbs" data-first-tail-preview></div>${frameControl('last_frame_image','尾帧图片（可选）')}<p class="muted">首帧确定开场构图，选填尾帧可约束结尾。建议图片比例与视频一致；人物设定图通常适合全能参考模式。</p></div></details></section>`);
  if(typeof tailShotControls==='function'){const slot=card.querySelector('[data-tail-slot]')||card.querySelector('[data-mode-panel]');slot.querySelectorAll('[data-tail-controls], [data-opening-controls]').forEach(x=>x.remove());slot.insertAdjacentHTML('beforeend',tailShotControls(s,choices));}
  card.querySelector('[data-frame-details]').open=foldOpen??draftGenerationMode(s)==='first_frame';
  ensureShotModeBackend().catch(error=>{const notice=card.querySelector('[data-mode-server-status]');if(notice)notice.textContent=error.message});
  const mediaBox=card.querySelector('[data-omni-media]');
  const savedMedia=(project.uploads||[]).filter(u=>/\.(mp4|mov|webm|mkv|wav|mp3|m4a|flac|ogg|aiff?)$/i.test(u.path));
  mediaBox.innerHTML=`<h4>视频与音频参考</h4><div class="mode-media-actions"><label class="mode-upload">添加参考视频<input type="file" multiple accept=".mp4,.mov,.webm,.mkv" data-mode-upload="silent_video"></label><label class="mode-upload">添加参考音频<input type="file" multiple accept=".wav,.mp3,.m4a,.flac,.ogg,.aif,.aiff" data-mode-upload="audio"></label></div><details class="muted"><summary>音视频参考规格</summary><p>最多9张图片、3段视频、3路音频，合计12项。视频／音频每段2–15秒、各类总时长不超过15秒；视频自带声音占一路音频。单文件最大150MB，音频须搭配图片或视频。长歌曲请先裁成片段，参考声音不等于原音直接混入成片。</p></details><details><summary>复用已上传的音视频</summary><label>复用项目内的视频或音频<select data-existing-media><option value="">选择已上传素材</option>${savedMedia.map(u=>`<option value="${esc(u.path)}">${esc(u.name)}${u.duration?" · "+Number(u.duration).toFixed(2)+"秒":""}</option>`).join('')}</select></label><button type="button" class="ghost" data-add-existing-media>添加到本段参考</button></details><div data-mode-media-list></div>`;
  card.querySelector('[data-add-existing-media]').onclick=()=>{const path=card.querySelector('[data-existing-media]').value;if(!path)return toast('请先选择项目素材');if(card.omniMedia.some(r=>r.path===path))return toast('本段已经引用此素材');card.omniMedia.push({path,kind:/\.(mp4|mov|webm|mkv)$/i.test(path)?'silent_video':'audio'});updateShotReferencePreview(card,true)};
  for(const input of card.querySelectorAll('[data-generation-mode], [data-first-source], [data-frame-choice], [data-tail-mode]'))input.onchange=()=>{
    if(input.dataset.frameChoice){
      for(const item of card.pendingModeFiles.filter(x=>x.target===input.dataset.frameChoice))URL.revokeObjectURL(item.url);
      card.pendingModeFiles=card.pendingModeFiles.filter(x=>x.target!==input.dataset.frameChoice);
    }
    if(input.matches('[data-generation-mode], [data-first-source]')){const mode=card.querySelector('[data-generation-mode]').value;const inherit=card.querySelector('[data-inherit-tail]');if(input.matches('[data-generation-mode]')&&mode==='first_frame'&&card.querySelector('[data-first-source]').value==='image'&&!card.querySelector('[data-frame-choice="first_frame_image"]').value)card.querySelector('[data-first-source]').value='qwen';if(mode==='text')inherit.checked=false;else if(mode==='first_frame')inherit.checked=card.querySelector('[data-first-source]').value==='previous_tail';card.tailSelectionDirty=true;}
    updateShotReferencePreview(card,true);
  };
  for(const area of card.querySelectorAll('.frame-input')){area.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy'};area.ondrop=e=>{e.preventDefault();e.stopPropagation();addShotModeFiles(card,[...e.dataTransfer.files],area.querySelector('[data-mode-upload]').dataset.modeUpload)}}
  for(const input of card.querySelectorAll('[data-mode-upload]'))input.onchange=()=>{addShotModeFiles(card,[...input.files],input.dataset.modeUpload);input.value=''};
}
function addShotModeFiles(card,files,target){
  if(card.refsUploading||card.modeUploading)return toast('正在保存素材，请稍候');
  card.pendingModeFiles??=[];
  const image=target.endsWith('_image');
  for(const file of files){
    const valid=image?/\.(png|jpe?g|webp)$/i.test(file.name):target==='audio'?/\.(wav|mp3|m4a|flac|ogg|aiff?)$/i.test(file.name):/\.(mp4|mov|webm|mkv)$/i.test(file.name);
    if(!valid||file.size>(image?30:150)*1024*1024){toast(`${file.name}：格式不支持或文件超过${image?30:150}MB`);continue}
    if(image){for(const item of card.pendingModeFiles.filter(x=>x.target===target))URL.revokeObjectURL(item.url);card.pendingModeFiles=card.pendingModeFiles.filter(x=>x.target!==target)}
    if(card.pendingModeFiles.some(x=>x.target===target&&x.file.name===file.name&&x.file.size===file.size&&x.file.lastModified===file.lastModified))continue;
    card.pendingModeFiles.push({target,file,url:URL.createObjectURL(file)});
  }
  updateShotReferencePreview(card,true);
}
function updateShotModePreview(card,shot){
  if(!card.querySelector('[data-mode-panel]'))return;
  if(typeof updateTailRepair==='function')updateTailRepair(card,shot);
  const mode=draftGenerationMode(shot),frame=mode==='first_frame';
  const frameDetails=card.querySelector('[data-frame-details]'),refDetails=card.querySelector('[data-refs-details]');
  if(frameDetails&&refDetails){if(card.lastFoldMode!==mode){frameDetails.open=frame;refDetails.open=mode==='omni_reference';card.lastFoldMode=mode;}card.querySelector('[data-refs-mode-note]').textContent=mode==='omni_reference'?'全能参考模式使用':mode==='first_frame'?'人物／场景图供 Qwen 首帧或尾帧重绘；H3 不接收此处音频／角色图':'文生模式只使用文字设定';}
  else{card.querySelector('.shot-references').hidden=mode!=='omni_reference';card.querySelector('[data-frame-mode]').hidden=!frame;}
  card.querySelector('[data-mode-description]').textContent={text:'仅使用镜头文字、人物与场景的文字设定，不输入图片、视频、音频，也不继承上一段画面。',first_frame:'可先由 Qwen 多图重绘生成高清首帧，再交给 H3 图生视频；也可手动选图或继承尾帧，尾帧约束可选。绑定原音用于后期混音。',omni_reference:'自由组合图片、视频和音频来参考人物、动作、场景或声音，按文字安排本段内容。'}[mode];
  const fromTail=shot.first_frame_source==='previous_tail';
  const fromQwen=shot.first_frame_source==='qwen';
  card.querySelector('[data-first-image-controls]').hidden=fromTail||fromQwen;
  const qwenBox=card.querySelector('[data-qwen-opening-preview]');qwenBox.hidden=!fromQwen;
  const row=project.opening_frame_catalog?.find(r=>r.id===shot.id);
  qwenBox.innerHTML=fromQwen?`<p>使用本段已保存起始构图与 03 已选元素成品图；修改内容后保存再生成。${esc(row?.opening||'请填写起始构图与状态。')}</p>${row?.result?referencePreviewTile(row.result.image,'已生成的 Qwen 首帧；输入一致时复用'):'<p>启动视频任务后先生成首帧，再释放 Qwen 并运行 H3。</p>'}${row?.error?`<p class="reference-warning">${esc(row.error)}</p>`:''}`:'';
  const ordered=[...project.shots].sort((a,b)=>a.shot-b.shot),index=ordered.findIndex(s=>s.id===shot.id),previous=ordered[index-1];
  let tail=previous?.video&&!previous.video_stale&&previous.tail_source_video===previous.video?previous.actual_tail_frame:null;
  const repaired=project.shots.find(s=>s.id===shot.id)?.tail_repair_view;
  if(repaired?.approved&&repaired.reference===(shot.tail_reference_image||project.tail_repair_defaults?.reference||'')&&repaired.mode===(shot.tail_repair_mode||project.tail_repair_defaults?.mode||'raw'))tail=repaired.result?.repaired||tail;
  card.querySelector('[data-first-tail-preview]').innerHTML=fromTail?(tail?referencePreviewTile(tail,'作为首帧的接续图（原图与修复版见下方）'):'<p class="muted">需要上一段有效视频；顺序生成时会自动提取其尾帧作为本段首帧。</p>'):'';
  for(const key of ['first_frame_image','last_frame_image']){
    const pending=(card.pendingModeFiles||[]).find(x=>x.target===key),path=shot[key];
    card.querySelector(`[data-frame-preview="${key}"]`).innerHTML=pending?`<figure><img src="${esc(pending.url)}" alt="${key==='first_frame_image'?'首帧':'尾帧'}待保存预览"><figcaption>${esc(pending.file.name)} · 待保存</figcaption><button type="button" class="ghost" data-remove-mode-pending="${card.pendingModeFiles.indexOf(pending)}">取消上传</button></figure>`:path?referencePreviewTile(path,key==='first_frame_image'?'本段首帧':'本段尾帧'):'';
  }
  const mediaHtml=(card.omniMedia||[]).map((r,i)=>{
    const upload=project.uploads?.find(u=>u.path===r.path),audio=r.kind==='audio';
    return `<article class="mode-media-item">${audio?`<audio controls preload="metadata" src="${media(r.path)}"></audio>`:`<video controls preload="metadata" src="${media(r.path)}"></video>`}<p>${esc(upload?.name||r.path.split('/').at(-1))}${upload?.duration?' · '+Number(upload.duration).toFixed(2)+'秒':''}</p>${audio?'':`<label><input type="checkbox" data-media-sound="${i}" ${r.kind==='video'?'checked':''} ${upload?.has_audio===false?'disabled':''}>同时参考视频声音${upload?.has_audio===false?'（此文件无音轨）':''}</label>`}<button type="button" class="ghost" data-remove-mode-media="${i}">移除引用</button></article>`;
  }).join('');
  const pendingMedia=(card.pendingModeFiles||[]).map((item,i)=>item.target.endsWith('_image')?'':`<p>${esc(item.file.name)} · 待保存 <button type="button" class="ghost" data-remove-mode-pending="${i}">取消上传</button></p>`).join('');
  // Preserve media controls/playback when an unrelated text field changes.
  const list=card.querySelector('[data-mode-media-list]'),html=mediaHtml+pendingMedia||`<p class="muted">${shot.audio_segment?.mode==='generated'?'本段按对白文字生成自然人声。':shot.audio_segment?'本段音轨已绑定（见上方播放器），可添加其他参考素材。':'尚未添加视频或音频参考'}</p>`;
  if(card.modeMediaHTML!==html){list.innerHTML=html;card.modeMediaHTML=html}
  for(const button of card.querySelectorAll('[data-remove-mode-pending]'))button.onclick=()=>{if(card.modeUploading)return;const [item]=card.pendingModeFiles.splice(Number(button.dataset.removeModePending),1);URL.revokeObjectURL(item.url);updateShotReferencePreview(card,true)};
  for(const button of card.querySelectorAll('[data-remove-mode-media]'))button.onclick=()=>{if(card.modeUploading)return;card.omniMedia.splice(Number(button.dataset.removeModeMedia),1);updateShotReferencePreview(card,true)};
  for(const input of card.querySelectorAll('[data-media-sound]'))input.onchange=()=>{card.omniMedia[Number(input.dataset.mediaSound)].kind=input.checked?'video':'silent_video';updateShotReferencePreview(card,true)};
}
async function uploadPendingShotModeFiles(card,pid){
  if(!card.pendingModeFiles?.length)return;
  card.modeUploading=true;
  try{
    while(card.pendingModeFiles.length){
      const item=card.pendingModeFiles[0],isImage=item.target.endsWith('_image'),data=new FormData();
      data.append('file',item.file);data.append('kind',item.target);
      const response=await fetch(`/api/projects/${pid}/${isImage?'upload':'upload-media'}`,{method:'POST',body:data}),entry=await response.json();
      if(!response.ok)throw new Error(entry.error||'素材上传失败');
      card.pendingModeFiles.shift();URL.revokeObjectURL(item.url);
      if(project.id!==pid)throw new Error('项目已切换；素材已保存在原项目上传目录');
      project.uploads??=[];project.uploads.push(entry);
      if(isImage){
        const select=card.querySelector(`[data-frame-choice="${item.target}"]`),option=document.createElement('option');
        option.value=entry.path;option.textContent=entry.name;select.append(option);select.value=entry.path;
      }else card.omniMedia.push({kind:item.target,path:entry.path});
      updateShotReferencePreview(card,true);
    }
    renderUploads();
  }finally{card.modeUploading=false}
}
