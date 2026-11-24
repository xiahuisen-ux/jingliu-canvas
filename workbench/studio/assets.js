// Local asset editing, version history and recoverable task controls.
let stopBusy=false, previewPath='', runtimeBusy=false, runtimeRefreshing=false;
function entityAsset(id){return project.assets?.[id]||{images:[],versions:[],selected_images:[]}}
function entityVersions(asset){return asset.versions||(asset.images?.length?[{id:'legacy',created_at:asset.updated_at,images:asset.images,status:'done'}]:[])}
function imageLabel(path){const uploaded=project?.uploads?.find(u=>u.path===path);if(uploaded?.name)return uploaded.name;const names={'character-sheet':'原有三栏设定图','character-sheet-4view':'人物设定图',front:'正面','three-quarter':'45° 斜侧面',side:'侧面',back:'背面'};const name=path.split('/').pop();return names[name.replace(/\.[^.]+$/,'')]||name}
function imageTile(path,eid){const a=entityAsset(eid),selected=a.selected_images?.includes(path);return `<div class="reference-tile ${selected?'selected':''}"><button class="image-preview-button" data-preview="${esc(path)}" aria-label="预览 ${esc(imageLabel(path))}"><img loading="lazy" src="${media(path)}" alt="${esc(imageLabel(path))}"></button><label class="reference-check"><input type="checkbox" data-select-reference="${esc(eid)}" value="${esc(path)}" ${selected?'checked':''}>用于视频 · ${esc(imageLabel(path))}</label><button class="ghost delete-asset-image" data-delete-asset-image="${esc(eid)}" data-path="${esc(path)}">删除图片</button></div>`}
function elementSourceImages(id){const a=entityAsset(id);if(Array.isArray(a.source_images))return a.source_images;const source=a.source_image??(a.reference_mode==='image'?a.primary_image:'');if(source!==undefined)return source?[source]:[];return (project.uploads||[]).filter(u=>u.entity_id===id&&u.usage!=='element_result').map(u=>u.path)}
function inputSourceTile(path,eid,character=false){
  const upload=project.uploads?.find(u=>u.path===path),layouts=entityAsset(eid).source_layouts||{},layout=Object.hasOwn(layouts,path)?layouts[path]:'auto';
  const choices=[['auto','自动识别分栏'],['','普通单人图'],['four-view-headless-front','四视图 · 特写 / 去头正面 / 侧面 / 背面'],['four-view','四视图 · 完整正面'],['face-front-body-back','原有三栏图']];
  return `<div class="input-reference-tile"><button class="image-preview-button" data-preview="${esc(path)}" aria-label="放大参考图"><img loading="lazy" src="${media(path)}" alt="${esc(upload?.name||imageLabel(path))}"></button><span>${esc(upload?.name||imageLabel(path))}</span>${character?`<label class="asset-help">参考图内容<select data-source-layout="${esc(eid)}" data-path="${esc(path)}">${choices.map(([value,label])=>`<option value="${value}" ${layout===value?'selected':''}>${label}</option>`).join('')}</select></label><button class="ghost" data-reuse-source="${esc(eid)}" data-path="${esc(path)}">原图转成品 · 不重绘</button>`:''}<button class="ghost delete-asset-image" data-delete-input-image="${esc(eid)}" data-path="${esc(path)}">删除原图</button></div>`;
}
function elementInputZone(x,character=true){const images=elementSourceImages(x.id);return `<section class="character-reference element-drop-zone" data-asset-drop="input" data-drop-entity="${esc(x.id)}" aria-label="${esc(x.name)} · 图生图原图"><div class="character-section-heading"><span>参考图 <small>（可有可无）</small></span><label class="upload-reference-button">上传参考图<input type="file" data-entity-upload="${esc(x.id)}" data-asset-role="input" accept="image/png,image/jpeg,image/webp" multiple hidden></label></div><div class="input-reference-list">${images.length?images.map(path=>inputSourceTile(path,x.id,character)).join(''):'<div class="character-reference-empty">拖入图生图参考照片<span>也可以点击上传；支持多张</span></div>'}</div><p class="asset-help">${character?'同一人物、同一造型。已有四视图会按栏读取；满意的原图可直接转成品。':'可拖入照片；图生图只使用此框中的原图。'}勾选下方成品后才用于视频。</p></section>`}
function resultVersions(id){const a=entityAsset(id),versions=entityVersions(a).map(v=>({...v,images:[...(v.images||[])]}));for(const path of a.selected_images||[]){if(!versions.some(v=>v.images.includes(path))&&project.uploads?.some(u=>u.entity_id===id&&u.path===path))versions.push({id:'legacy-import-'+path,images:[path],status:'done',mode:'import'});}return versions;}
function elementResultZone(x,state=false,character=true){
  const versions=resultVersions(x.id).filter(v=>!!v.state_name===state),latest=versions.at(-1),results=[...versions].reverse().filter(v=>v.images?.length);
  return `<section class="character-result ${state?'':'element-drop-zone'}" data-character-result="${state?'state':'base'}" ${state?'':`data-asset-drop="result" data-drop-entity="${esc(x.id)}"`} aria-label="${esc(x.name)} · ${state?'状态图':'生成图与视频参考'}"><div class="character-section-heading"><span>${state?'状态图预览':'生成图预览'}</span>${state?'':`<label class="upload-reference-button">导入成品图<input type="file" data-entity-upload="${esc(x.id)}" data-asset-role="result" accept="image/png,image/jpeg,image/webp" multiple hidden></label>`}</div><p class="asset-help">${state?'选择此状态供视频使用。':'可拖入成品图片。所有版本向下排列，勾选需要用于后续视频的图片；未勾选不采用。'}</p><div class="character-result-gallery element-result-list">${results.length?results.map(v=>`<article class="element-result-version" data-result-version="${esc(v.id)}"><div class="character-section-heading"><span>${esc(v.state_name|| (v.mode==='import'?'导入图片':v.id==='legacy'?'原有图片':'生成版本'))}</span><small>${esc((v.created_at||'').replace('T',' '))}${v.reference_layout?' · 四视图布局 · 待核对':''}</small></div>${v.images.map(path=>imageTile(path,x.id)+(character&&v.mode==='import'?`<label class="asset-help">图片布局<select data-import-layout="${esc(x.id)}" data-path="${esc(path)}">${[['','普通图片'],['four-view-headless-front','四视图 · 正面无头部'],['four-view','四视图 · 完整正面'],['face-front-body-back','原有三栏图']].map(([value,label])=>`<option value="${value}" ${(v.reference_layout||'')===value?'selected':''}>${label}</option>`).join('')}</select></label>`:'')).join('')}${v.status==='done'&&v.images.length===4?`<button class="ghost" data-approve-views="${esc(x.id)}" data-version="${esc(v.id)}">确认并采用本组四张角度图</button>`:''}${faceReferencePreview(v)}${sheetLayoutControls(x,v)}${['needs_revision','needs_review'].includes(v.layout_review?.status)?`<p class="asset-help">布局待修正：${esc(v.layout_review.summary)}</p>`:''}${v.mode==='image'&&!v.generation_settings?.reference_conditioning?'<p class="asset-help">旧版局部重绘结果，尚未验证为四视图。</p>':''}</article>`).join(''):character?characterEmptyPreview(state):'<div class="character-reference-empty">拖入成品图或开始生成<span>选用后才参与视频制作</span></div>'}</div>${latest&&latest.status!=='done'?`<p class="asset-help" role="status">${latest.status==='running'?`正在生成${latest.view_progress?` · 已完成 ${latest.view_progress.completed||0}/${latest.view_progress.total||4}` :''}`:latest.status==='cancelled'?'上次生成已停止':'上次生成未完成'}</p>`:''}</section>`;
}
function faceReferencePreview(v){
  if(v.face_reference_sheet)return `<details class="face-reference-preview" open><summary>面部精修专用 · 单张三视图（正面／侧面／背面）</summary><button class="image-preview-button face-reference-sheet" data-preview="${esc(v.face_reference_sheet)}"><img loading="lazy" src="${media(v.face_reference_sheet)}" alt="正面、侧面、背面头部特写三联图"></button><p class="asset-help">三种头部角度合在一张图片，可点击放大。随所选人物版本用于面部精修。</p></details>`;
  if(!v.face_references)return '';
  return `<details class="face-reference-preview"><summary>面部精修专用 · 旧版独立头部参考</summary><div class="asset-thumbnails">${Object.entries(v.face_references).map(([view,path])=>`<button class="image-preview-button" data-preview="${esc(path)}"><img loading="lazy" src="${media(path)}" alt="${esc(view)}"></button>`).join('')}</div><p class="asset-help">旧图保留；新生成结果使用单张头部三联图。</p></details>`;
}
function entityEditorCard(kind,x){
  if(kind==='characters')return characterEditorCard(x);
  const a=entityAsset(x.id),versions=entityVersions(a);
  const field=(key,label,value,multiline=false)=>`<label>${label}${multiline?`<textarea data-field="${key}" rows="3">${esc(value||'')}</textarea>`:`<input data-field="${key}" value="${esc(value||'')}">`}</label>`;
  return `<article class="entity-card entity-editor" data-entity-card="${esc(x.id)}"><span class="tag">${kind==='key_objects'?'物品':'场景'}</span>${field('name','名称',x.name)}${field('description','描述（可直接修改）',x.description,true)}<button class="ghost" data-save-entity="${esc(x.id)}">保存文字</button>${elementInputZone(x,false)}<div class="reference-controls"><label>生成方式<select data-field="reference_mode"><option value="text" ${a.reference_mode!=='image'?'selected':''}>按文字生成</option><option value="image" ${a.reference_mode==='image'?'selected':''}>参考上框原图生成</option></select></label><label>重绘幅度<input data-field="denoise" type="number" min="0.2" max="0.95" step="0.05" value="${a.denoise??.65}"></label></div><label>参考图数量<select data-field="reference_views"><option value="0" ${referenceViewCount(kind,a)===0?'selected':''}>跳过</option><option value="1" ${referenceViewCount(kind,a)===1?'selected':''}>单张参考图</option><option value="4" ${referenceViewCount(kind,a)===4?'selected':''}>四视参考图</option></select></label><button class="primary generate-asset" data-generate-entity="${esc(x.id)}">保存修改并生成参考图</button>${elementResultZone(x,false,false)}${deletedImageControls(x.id)}<div class="asset-location"><code>${esc(project.storage_path||'')}/assets/${esc(x.id)}</code><button class="ghost" data-reveal="${versions.length?'assets/'+esc(x.id):''}">打开文件夹</button></div></article>`;
}

function characterDescription(x){return [x.appearance,x.wardrobe].filter(Boolean).join('\n\n')}
function characterImages(id){return elementSourceImages(id)}
function characterSourceOptions(id,source){return '<option value="">选择参考原图</option>'+elementSourceImages(id).map(path=>`<option value="${esc(path)}" ${path===source?'selected':''}>${esc(project.uploads?.find(u=>u.path===path)?.name||imageLabel(path))}</option>`).join('')}

function characterEmptyPreview(state=false){return `<div class="character-empty-preview"><div class="four-view-guide" aria-hidden="true"><span>脸部高清特写</span><span>人物正视图<small>颈部以下 · 无头部</small></span><span>人物侧视图</span><span>人物背视图</span></div><small>${state?'状态图将显示在这里':'单张四视图 · 左侧特写加宽 · 正视无头部'}</small></div>`}
function sheetLayoutControls(x,result){
  const l=result?.layout_editor;if(!l)return '';
  const labels={face:'高清正脸',front:'正视图',side:'侧视图',back:'背视图'};
  return `<details class="sheet-layout-editor" data-layout-height="${Number(l.height)||1024}"><summary>调整四视图裁切</summary><p class="asset-help">固定四栏 2:1:1:1。下方实时预览；正面颈线以上遮除，侧面和背面保留完整头部。原片保留，保存会另建版本。</p><canvas data-sheet-preview width="1000" height="400" aria-label="四视图裁切实时预览"></canvas><p class="asset-help" data-sheet-preview-status></p><div class="sheet-crop-panels">${Object.entries(labels).map(([key,label])=>`<label>${label}原片<img data-layout-source="${key}" src="${media(l.sources[key])}" alt="${label}裁切来源"><span>裁切：左、上、右、下（0–1）</span><input data-view-crop="${key}" value="${esc((l.crops?.[key]||[0,0,1,1]).join(','))}"></label>`).join('')}</div><label>正面颈线（裁切后从上往下，%）<input type="number" min="5" max="75" step="1" data-front-neck value="${Math.round(l.front_neck*100)}"></label><label>视频参考的侧背头部遮除线（裁切后，%）<input type="number" min="5" max="75" step="1" data-side-neck value="${Math.round(l.side_neck*100)}"></label><button class="ghost" data-sheet-layout="${esc(x.id)}" data-version="${esc(result.id)}">保存裁切为新图</button></details>`;
}
function parseSheetCrop(value){
  const parts=value.trim().split(/[,，\s]+/),crop=parts.map(Number);
  if(parts.length!==4||parts.some(v=>!v)||!crop.every(Number.isFinite)||!(0<=crop[0]&&crop[0]<crop[2]&&crop[2]<=1&&0<=crop[1]&&crop[1]<crop[3]&&crop[3]<=1))throw new Error('裁切需要四个0–1之间的比例：左、上、右、下');
  return crop;
}
function sheetLayoutDraft(box){
  const crops=Object.fromEntries([...box.querySelectorAll('[data-view-crop]')].map(input=>[input.dataset.viewCrop,parseSheetCrop(input.value)]));
  const front_neck=Number(box.querySelector('[data-front-neck]').value)/100,side_neck=Number(box.querySelector('[data-side-neck]').value)/100;
  if(![front_neck,side_neck].every(v=>Number.isFinite(v)&&v>=.05&&v<=.75))throw new Error('颈部位置须在5%到75%之间');
  return {crops,front_neck,side_neck};
}
function drawSheetLayoutPreview(box){
  const status=box.querySelector('[data-sheet-preview-status]');
  try{
    const draft=sheetLayoutDraft(box),canvas=box.querySelector('[data-sheet-preview]'),ctx=canvas.getContext('2d'),height=canvas.height,unit=height/2,margin=16*height/Number(box.dataset.layoutHeight);
    ctx.fillStyle='rgb(166,166,166)';ctx.fillRect(0,0,canvas.width,height);
    let loaded=0;
    ['face','front','side','back'].forEach((key,index)=>{
      const img=box.querySelector(`[data-layout-source="${key}"]`);if(!img.complete||!img.naturalWidth)return;loaded++;
      const crop=draft.crops[key],sx=Math.round(crop[0]*img.naturalWidth),sy=Math.round(crop[1]*img.naturalHeight),w=Math.round(crop[2]*img.naturalWidth)-sx,h=Math.round(crop[3]*img.naturalHeight)-sy;
      if(w<1||h<1)throw new Error('裁切范围过小');
      const source=document.createElement('canvas');source.width=w;source.height=h;const sc=source.getContext('2d');sc.drawImage(img,sx,sy,w,h,0,0,w,h);
      if(key==='front'){sc.fillStyle='rgb(166,166,166)';sc.fillRect(0,0,w,Math.round(h*draft.front_neck)+1);}
      const bw=key==='face'?2*unit:unit,scale=Math.min((bw-margin)/w,(height-margin)/h),fw=w*scale,fh=h*scale,left=index===0?0:(index+1)*unit;
      ctx.drawImage(source,left+(bw-fw)/2,(height-fh)/2,fw,fh);
    });
    status.textContent=loaded===4?'预览与保存使用同一裁切范围。请把正面颈线调到头部完全消失的位置。':'正在读取视图原片…';
  }catch(e){status.textContent=e.message;}
}
function characterResult(x,state=false){return elementResultZone(x,state,true)}
function characterEditorCard(x){
  const a=entityAsset(x.id),versions=entityVersions(a);
  return `<article class="entity-card entity-editor character-editor" data-entity-card="${esc(x.id)}"><header class="character-heading"><span class="tag">人物</span><input data-field="name" aria-label="人物名称" placeholder="人物名称" value="${esc(x.name)}"><button class="ghost" data-save-entity="${esc(x.id)}">保存</button></header><label>外貌 / 身份 / 服饰 / 配饰<textarea data-field="character_description" rows="4" maxlength="16000">${esc(characterDescription(x))}</textarea></label>${elementInputZone(x)}<p class="asset-help">一个人物：一张四视图＋一张面部特写三联图（正面 / 侧面 / 背面）</p><div class="character-generate-row"><button class="primary" data-generate-entity="${esc(x.id)}">开始生成</button><select data-field="reference_mode" aria-label="人物生成方式"><option value="text" ${a.reference_mode!=='image'?'selected':''}>文生图</option><option value="image" ${a.reference_mode==='image'?'selected':''}>图生图</option></select></div><p class="asset-help" data-character-edit-note ${a.reference_mode==='image'&&project.character_image_edit?.ready===false?'':'hidden'}>图生图暂不可用：缺少 Z-Image-Turbo 模型文件。</p>${characterResult(x)}${deletedImageControls(x.id)}<div data-character-controls></div><details class="character-advanced"><summary>更多设置</summary><div class="character-advanced-body"><p class="asset-help">图生图使用上框原图。多张参考请保持同一人物和造型；人物输出一张四视图和一张头部特写三联图；内部共6轮生成后固定拼版；生成后检查脸型、服装及角度。</p><label>批量生成<select data-field="reference_views"><option value="1" ${referenceViewCount('characters',a)?'selected':''}>包含此人物 · 1张四视图</option><option value="0" ${referenceViewCount('characters',a)?'':'selected'}>跳过此人物</option></select></label><label>正脸输入区域：左、上、右、下（0–1）<input data-field="source_face_crop" value="${esc((a.source_face_crop||[0,0,1,1]).join(','))}"></label><div class="asset-location"><code>${esc(project.storage_path||'')}/assets/${esc(x.id)}</code><button class="ghost" data-reveal="${versions.length?'assets/'+esc(x.id):''}">打开文件夹</button></div></div></details></article>`;
}

function entityDraft(id){const card=$(`[data-entity-card="${CSS.escape(id)}"]`),data={};for(const field of card.querySelectorAll('[data-field]'))data[field.dataset.field]=field.dataset.field==='source_face_crop'?parseSheetCrop(field.value):['denoise','reference_views'].includes(field.dataset.field)?Number(field.value):field.value;return data}
async function saveEntity(id,extra={},redraw=true){const data={...entityDraft(id),...extra};const pid=project.id;const saved=await api(`/api/projects/${encodeURIComponent(pid)}/entities/${encodeURIComponent(id)}`,{method:'POST',body:JSON.stringify(data)});if(project?.id===pid){project=saved;syncTaskElementChoices();if(redraw){renderAnalysis();renderInspector()}}return saved}
async function revealFile(path){try{await api(`/api/projects/${project.id}/reveal`,{method:'POST',body:JSON.stringify({path})})}catch(e){toast(e.message)}}
function showImagePreview(path){previewPath=path;$('#previewImage').src=media(path);$('#previewImage').alt=imageLabel(path);$('#previewTitle').textContent=imageLabel(path);$('#previewPath').textContent=(project.storage_path||'')+'/'+path;$('#downloadImage').href=media(path);$('#downloadImage').download=path.split('/').pop();if(!$('#imagePreview').open)$('#imagePreview').showModal()}
async function stopModels(){if(stopBusy)return;stopBusy=true;setStopButtons(true);try{await api('/api/stop',{method:'POST',body:'{}'});$('#runtimeMessage').textContent='正在停止任务并释放模型…';toast('已请求停止，已完成的文件会保留')}catch(e){stopBusy=false;setStopButtons(false);toast(e.message)}}
function setStopButtons(busy){$$('[data-stop-models]').forEach(b=>{b.disabled=busy;b.textContent=busy?'正在停止…':'■ 停止并释放模型'})}
async function refreshRuntime(){
  if(runtimeRefreshing)return;runtimeRefreshing=true;
  try{
    const r=await api('/api/runtime');runtimeBusy=r.busy;
    if(stopBusy&&r.stop.status!=='stopping'){
      stopBusy=false;setStopButtons(false);toast(r.stop.message);
      const pid=project?.id;if(pid){const fresh=await api(`/api/projects/${pid}`);if(project?.id===pid){project=fresh;renderVideos();syncShotStatus();renderInspector()}}
    }
    setStableText($('#runtimeMessage'),r.stop.status==='stopping'?r.stop.message:r.stop.status==='error'?r.stop.message:r.busy?'模型任务进行中':r.stop.status==='done'?r.stop.message:'模型按需启动');
    if(!pollTimer){const job=r.jobs.find(j=>!['creative_chat','creative_draft','shot_chat','script_discuss','script_propose'].includes(j.action));if(job)watchJob(job);}
  }catch{}finally{runtimeRefreshing=false}
}
function attachShotReferences(){
  const options=[];for(const [eid,a] of Object.entries(project.assets||{})){const entity=[...(project.analysis?.characters||[]),...(project.analysis?.key_objects||[]),...(project.analysis?.locations||[])].find(e=>e.id===eid);for(const path of a.selected_images||[])options.push({path,name:`${entity?.name||eid} · ${imageLabel(path)} · ${path.split('/').slice(-2,-1)[0]}`})}
  $$('#shotsGrid .shot-copy').forEach(box=>{const shot=project.shots.find(s=>s.id===box.closest('[data-shot-id]').dataset.shotId);box.insertAdjacentHTML('beforeend',`<label class="shot-reference-label">镜头衔接<select data-shot-transition="${esc(shot.id)}"><option value="continue" ${shot.transition==='continue'?'selected':''}>连续：上一段实际尾帧 → 本段首帧</option><option value="cut" ${shot.transition!=='continue'?'selected':''}>切镜／换场：按剧本重新起帧</option></select></label><p class="muted">自动关联：${esc((shot.reference_bindings||[]).map(b=>elementName(b.entity_id)).join('、')||'暂无可用参考图')}。关联所有出场元素；当前图像接口仅输入一张主参考，其余为文字约束。连续镜头的首帧优先继承上一段画面。</p><label class="shot-reference-label">独立起帧／尾帧的主参考图<select data-shot-reference="${esc(shot.id)}"><option value="__auto__" ${shot.auto_reference!==false?'selected':''}>自动按出场人物与元素选择</option><option value="" ${shot.auto_reference===false&&!shot.reference_image?'selected':''}>不使用参考图（按文字生成）</option>${options.map(o=>`<option value="${esc(o.path)}" ${shot.auto_reference===false&&shot.reference_image===o.path?'selected':''}>${esc(o.name)}</option>`).join('')}</select></label>`)});
  $$('[data-shot-reference], [data-shot-transition]').forEach(el=>el.onchange=async()=>{try{const id=el.dataset.shotReference||el.dataset.shotTransition;const change=el.dataset.shotTransition?{transition:el.value}:{auto_reference:el.value==='__auto__',reference_image:el.value==='__auto__'?'':el.value};const shots=project.shots.map(s=>s.id===id?{...s,...change}:s);project=await api(`/api/projects/${project.id}/save`,{method:'POST',body:JSON.stringify({shots})});renderShots();attachShotReferences();toast('衔接与参考图设置已保存；受影响视频需要重新生成')}catch(e){toast(e.message);render()}});
}
function bindAssetUI(){
  $$('[data-action="all_assets"]').forEach(b=>b.textContent='批量生成参考图');
  $$('[data-stop-models]').forEach(b=>b.onclick=stopModels);
  $('#closePreview').onclick=()=>$('#imagePreview').close();$('#revealPreview').onclick=()=>revealFile(previewPath);
  $('#entitySections').addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    const id=button.dataset.saveEntity||button.dataset.generateEntity||button.dataset.primaryReference||button.dataset.approveViews||button.dataset.deleteAssetImage||button.dataset.deleteInputImage||button.dataset.restoreAssetImage||button.dataset.sheetLayout||button.dataset.reuseSource;
    try{
      if(button.dataset.reuseSource){button.disabled=true;await reuseSourceImage(id,button.dataset.path);return;}
      if(button.dataset.sheetLayout){const pid=project.id;const box=button.closest('.sheet-layout-editor'),draft=sheetLayoutDraft(box);button.disabled=true;await saveEntity(id,{},false);if(project?.id!==pid)return;const updated=await api(`/api/projects/${pid}/entities/${encodeURIComponent(id)}/sheet-layout`,{method:'POST',body:JSON.stringify({version_id:button.dataset.version,...draft})});if(project?.id!==pid)return;project=updated;renderAnalysis();toast('已保存新版本，请预览后勾选使用');return;}
      if(button.dataset.preview)return showImagePreview(button.dataset.preview);
      if(button.dataset.deleteAssetImage||button.dataset.deleteInputImage||button.dataset.restoreAssetImage){
        const pid=project.id,restore=!!button.dataset.restoreAssetImage;button.disabled=true;
        const inputRole=!!button.dataset.deleteInputImage||(restore&&entityAsset(id).deleted_images?.find(r=>r.id===button.dataset.record)?.role==='input');
        await saveEntity(id,{},false);if(project?.id!==pid)return;
        const updated=await api(`/api/projects/${pid}/entities/${encodeURIComponent(id)}/images${restore?'/restore':''}`,{method:restore?'POST':'DELETE',body:JSON.stringify(restore?{record_id:button.dataset.record}:{path:button.dataset.path,role:button.dataset.deleteInputImage?'input':'result'})});
        if(project?.id!==pid)return;project=updated;renderAnalysis();renderUploads();syncTaskElementChoices();renderInspector();
        toast(restore?(inputRole?'原图已恢复到图生图参考框':'成品图已恢复，可重新勾选用于视频'):(inputRole?'原图已移除，可在「已删除图片」中恢复':'成品图已删除，可在「已删除图片」中恢复'));return;
      }
      if('reveal' in button.dataset)return revealFile(button.dataset.reveal);
      if(!id)return;const card=button.closest('[data-entity-card]');if(button.dataset.generateEntity&&card&&card.querySelector('[data-field="reference_mode"]').value==='image'&&!elementSourceImages(id).length)return toast('图生图需要先在上方参考图框中拖入或上传图片');button.disabled=true;
      if(button.dataset.approveViews){if(!confirm('确认本组四张分别为正面、45°、侧面、背面，且主体一致、没有重复人物或文字？'))return;await saveEntity(id,{approve_view_version:button.dataset.version});toast('已选用整组四视图，旋转镜头自动调用')}
      else if(button.dataset.primaryReference){await saveEntity(id,{source_image:button.dataset.path});toast('图片重绘原图已更新')}
      else{const pid=project.id,isCharacter=button.closest('.character-editor');await saveEntity(id,button.dataset.generateEntity&&isCharacter?{reference_views:1}:{});if(project?.id!==pid)return;if(button.dataset.generateEntity)await runAction('asset',{entityId:id});else toast('文字已保存')}
    }catch(e){toast(e.message)}finally{button.disabled=false}
  });
  $('#entitySections').addEventListener('change',async event=>{
    const input=event.target;
    if(input.dataset.field==='reference_mode'){const card=input.closest('[data-entity-card]'),denoise=card.querySelector('[data-field="denoise"]'),note=card.querySelector('[data-character-edit-note]');if(denoise)denoise.disabled=input.value!=='image';if(note)note.hidden=input.value!=='image'||project.character_image_edit?.ready!==false;}
    if(input.dataset.field==='source_image'){
      const preview=input.closest('[data-entity-card]').querySelector('[data-source-preview]');
      preview.innerHTML=input.value?`<button class="image-preview-button character-source-preview" data-preview="${esc(input.value)}" aria-label="放大参考图"><img src="${media(input.value)}" alt="参考图预览"></button>`:'<div class="character-reference-empty">参考图预览<span>也可以直接用文字生成</span></div>';
    }
    if(input.dataset.field==='reference_views'&&!input.closest('.character-editor')){
      const button=input.closest('[data-entity-card]').querySelector('[data-generate-entity]');
      button.textContent=input.value==='4'?'保存修改并生成四视图':input.value==='1'?'保存修改并生成单张参考图':'已选择跳过';button.disabled=input.value==='0';
    }
    try{
      if(input.dataset.sourceLayout){await saveSourceLayout(input.dataset.sourceLayout,input.dataset.path,input.value)}
      if(input.dataset.importLayout){await saveEntity(input.dataset.importLayout,{import_layout:{path:input.dataset.path,layout:input.value}});toast('导入图片布局已保存')}
      if(input.dataset.selectReference){const id=input.dataset.selectReference,card=input.closest('[data-entity-card]');const paths=[...card.querySelectorAll('[data-select-reference]:checked')].map(e=>e.value);await saveEntity(id,{selected_images:paths});toast('选用参考图已保存')}
      if(input.dataset.entityUpload){await uploadElementFiles(input.dataset.entityUpload,input.dataset.assetRole||'input',input.files)}
    }catch(e){toast(e.message);if(input.dataset.selectReference)input.checked=!input.checked}
  });
  document.addEventListener('click',event=>{const img=event.target.closest('#shotsGrid img, #uploads img');if(!img||!project)return;const prefix=`/media/${project.id}/`;const path=new URL(img.src).pathname;if(path.startsWith(prefix))showImagePreview(decodeURIComponent(path.slice(prefix.length)))});
  $('#entitySections').addEventListener('input',event=>{const box=event.target.closest('.sheet-layout-editor');if(box)drawSheetLayoutPreview(box)});
  $('#entitySections').addEventListener('load',event=>{if(event.target.matches('[data-layout-source]'))drawSheetLayoutPreview(event.target.closest('.sheet-layout-editor'))},true);
  $('#entitySections').addEventListener('toggle',event=>{if(event.target.matches('.sheet-layout-editor')&&event.target.open)drawSheetLayoutPreview(event.target)},true);
  $('#entitySections').addEventListener('dragover',event=>{const zone=event.target.closest('[data-asset-drop]');if(zone){event.preventDefault();event.dataTransfer.dropEffect='copy';zone.classList.add('drag')}});
  $('#entitySections').addEventListener('dragleave',event=>{const zone=event.target.closest('[data-asset-drop]');if(zone&&!zone.contains(event.relatedTarget))zone.classList.remove('drag')});
  $('#entitySections').addEventListener('drop',event=>handleElementDrop(event));
  refreshRuntime();setInterval(refreshRuntime,2000);
}

function deletedImageControls(eid){
  const records=entityAsset(eid).deleted_images||[];
  return records.length?`<details class="deleted-asset-images"><summary>已删除图片 · ${records.length} 张</summary>${[...records].reverse().map(r=>`<div class="deleted-image-row"><span>${r.role==='input'?'原图':'成品图'} · ${esc(imageLabel(r.path))} · ${esc(r.deleted_at?.replace('T',' ')||'')}</span><button class="ghost" data-restore-asset-image="${esc(eid)}" data-record="${esc(r.id)}">恢复图片</button></div>`).join('')}</details>`:'';
}

const elementUploadsInFlight=new Set();
function captureElementDrafts(){
  if(typeof document==='undefined')return [];
  return [...document.querySelectorAll('[data-entity-card]')].flatMap(card=>[...card.querySelectorAll('[data-field],[data-state-name],[data-state-prompt],[data-state-mode]')].map(input=>({id:card.dataset.entityCard,selector:input.dataset.field?`[data-field="${input.dataset.field}"]`:input.hasAttribute('data-state-name')?'[data-state-name]':input.hasAttribute('data-state-prompt')?'[data-state-prompt]':'[data-state-mode]',value:input.value,state:!input.dataset.field})));
}
function restoreElementDrafts(before,current,eid){
  for(const draft of current){const original=before.find(x=>x.id===draft.id&&x.selector===draft.selector);if(draft.id===eid&&!draft.state&&draft.value===original?.value)continue;const input=document.querySelector(`[data-entity-card="${CSS.escape(draft.id)}"] ${draft.selector}`);if(input)input.value=draft.value;}
}
function validElementFiles(files){
  return [...files].filter(file=>{if(!/\.(png|jpe?g|webp)$/i.test(file.name)||!['image/png','image/jpeg','image/webp',''].includes(file.type)){toast('请使用 PNG、JPG 或 WEBP 图片');return false}if(file.size>32*1024*1024){toast('图片不能超过 32MB');return false}return true});
}
async function handleElementDrop(event){
  const zone=event.target.closest('[data-asset-drop]');if(!zone)return;
  event.preventDefault();event.stopPropagation();zone.classList.remove('drag');
  try{await uploadElementFiles(zone.dataset.dropEntity,zone.dataset.assetDrop,event.dataTransfer.files)}catch(e){toast(e.message)}
}
async function uploadElementFiles(eid,role,files){
  if(!project)return;const pid=project.id,valid=validElementFiles(files);if(!valid.length)return;
  const key=pid+':'+eid;if(elementUploadsInFlight.has(key))throw new Error('该元素正在上传，请等待完成');
  elementUploadsInFlight.add(key);let changed=false;const before=captureElementDrafts();
  try{
    if(!(await api('/api/capabilities')).asset_image_regions)throw new Error('图片区域分离需要新版服务，请在更新后刷新页面');
    await saveEntity(eid,{},false);if(project?.id!==pid)return;
    for(const file of valid){
      if(project?.id!==pid)break;
      const form=new FormData();form.append('file',file);form.append('name',file.name);form.append('entity_id',eid);form.append('asset_role',role);
      const response=await fetch(`/api/projects/${pid}/upload`,{method:'POST',body:form}),entry=await response.json();if(!response.ok)throw new Error(entry.error||'上传失败');changed=true;
    }
    if(project?.id===pid)toast(role==='result'?'已导入生成图区，请勾选用于视频的图片':'已加入图生图参考框；不作为视频首帧或最终形象');
  }finally{
    elementUploadsInFlight.delete(key);
    if(changed&&project?.id===pid){const fresh=await api(`/api/projects/${pid}`);if(project?.id===pid){const current=captureElementDrafts();project=fresh;renderAnalysis();restoreElementDrafts(before,current,eid);renderUploads();syncTaskElementChoices();renderInspector()}}
  }
}

async function reuseSourceImage(eid,path){
  const pid=project.id,before=captureElementDrafts();
  await saveEntity(eid,{},false);if(project?.id!==pid)return;
  const updated=await api(`/api/projects/${pid}/entities/${encodeURIComponent(eid)}/reuse-source`,{method:'POST',body:JSON.stringify({path})});
  if(project?.id!==pid)return;const current=captureElementDrafts();project=updated;renderAnalysis();restoreElementDrafts(before,current,eid);toast('原图已转为成品，未重绘；勾选后用于视频');
}
async function saveSourceLayout(eid,path,value){
  const pid=project.id,before=captureElementDrafts();
  await saveEntity(eid,{source_layout:{path,layout:value}},false);
  if(project?.id!==pid)return;const current=captureElementDrafts();renderAnalysis();restoreElementDrafts(before,current,eid);toast('参考图布局已保存，生成时按对应视角读取');
}
