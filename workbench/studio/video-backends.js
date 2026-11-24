function bindVideoBackendUI(){
  $('#settingsDialog .settings-grid').insertAdjacentHTML('beforeend',`<section><h3>视频后端</h3><p><strong>h3.c Metal · 原生多图参考</strong></p><label>h3.c 采样步数<input id="h3cSteps" type="number" min="4" max="50" value="8"></label><label>单段生成／合片后自动增强<select id="videoUpscale"><option value="0">关闭，仅手动增强</option><option value="2">Real-ESRGAN 2×</option><option value="4">Real-ESRGAN 4×</option></select></label><p class="muted">批量镜头先生成原片，合片后统一增强；原片不覆盖。2× 输出由 4× 写实模型处理后缩小。</p><p id="nativeBackendState" class="muted"></p><p class="muted">每段可独立选择文生视频、首帧生视频或全能参考。模型按需启动，任务串行执行；常驻开启时，成功后保留缓存。</p></section>`);
}
function fillBackendSettings(){
  if(!$('#h3cLayers'))$('#h3cSteps').closest('label').insertAdjacentHTML('afterend',`<fieldset id="h3cPerformance"><legend>D 档性能参数</legend><button type="button" id="h3cPresetD">D 档：15 步 / 45 层 / reuse 2</button><label>活动层数<select id="h3cLayers"><option value="50">50 层 · 完整</option><option value="45">45 层 · 均衡</option></select></label><label>去噪复用<select id="h3cReuse"><option value="1">1 · 每步计算</option><option value="2">2 · 间隔计算 / 外推</option></select></label><label>参考视频像素上限<select id="h3cRefVideoPixels"><option value="0">原生默认 · 约 768×1344</option><option value="147456">轻量 · 约 288×512</option><option value="358400">D 档 · 约 448×800</option><option value="589824">较细 · 约 576×1024</option></select></label><p class="muted">按原片比例对齐 32 像素；只缩小模型输入，不改原文件、时长或音轨。4–7 步预览须用 reuse 1；新参数只影响后续任务。加速可能影响动作和细节，仍需实片对照。</p></fieldset>`);
  $('#h3cPerformance').disabled=settings.h3c_layers==null;
  $('#h3cLayers').value=settings.h3c_layers??50;
  $('#h3cReuse').value=settings.h3c_reuse??1;
  $('#h3cRefVideoPixels').value=settings.h3c_reference_video_max_pixels??0;
  $('#h3cPresetD').onclick=()=>{$('#h3cSteps').value=15;$('#h3cLayers').value=45;$('#h3cReuse').value=2;$('#h3cRefVideoPixels').value=358400;};
  if(!$('#h3cStreaming'))$('#h3cSteps').closest('label').insertAdjacentHTML('afterend',`<label><input id="h3cStreaming" type="checkbox">逐层加载（降低内存占用）</label><p class="muted">每次只驻留两层视频权重，减少内存挤占；增加 SSD 读取，实际速度取决于镜头大小。</p><label>无新进度自动停止（分钟）<input id="h3cStallMinutes" type="number" min="5" max="60" step="1" value="10"></label><p class="muted">两分钟无新进度时提醒，达到此时间停止并释放模型。逐层加载会显示实际完成层数；慢速计算也可能触发保护。</p>`);
  if(!$('#h3cResident'))$('#h3cSteps').closest('label').insertAdjacentHTML('afterend',`<label><input id="h3cResident" type="checkbox">H3 常驻进程与缓存</label><p class="muted">成功后保留进程和可复用缓存；相同提示词与素材可跳过部分准备。更换素材会重新编码。点击“停止并释放模型”或切换生图、本地文字模型时释放内存。关闭后当前任务完成再释放。</p>`);
  if(!$('#h3cFaceRefine'))$('#h3cSteps').closest('label').insertAdjacentHTML('afterend',`<details class="face-refine-settings"><summary>H3 FaceRefine · 面部精修</summary><label><input id="h3cFaceRefine" type="checkbox">每段视频完成后自动精修面部</label><p class="muted">先保留原片，再逐个人物追踪、局部精修并回贴，完成后继续下一段。精修版与原片可比较；参考匹配不确定的人脸保留原片。卡通脸可能漏检。精修增加生成时间。</p><label><input id="h3cFaceMouth" type="checkbox">保留嘴部附近原像素，优先保持口型</label><div class="face-refine-fields"><label>面部精修画布<select id="h3cFaceSize"><option value="512">512×512</option><option value="768">768×768</option></select></label><label>面部精修步数<input id="h3cFaceSteps" type="number" min="4" max="20" value="6"></label><label>面部重绘幅度<input id="h3cFaceDenoise" type="number" min="0.01" max="0.15" step="0.01" value="0.05"></label></div><p class="muted">幅度越大，细节重建越强，也更可能改变五官和表情。新生成人物另存正面／侧面／背面头部参考；旧版可先用已有正面特写。</p><p id="faceRefineState" class="muted"></p></details>`);
  $('#h3cFaceRefine').checked=settings.h3c_face_refine??false;
  $('#h3cFaceMouth').checked=settings.h3c_face_preserve_mouth??true;
  $('#h3cFaceSteps').value=settings.h3c_face_steps??6;
  $('#h3cFaceSize').value=settings.h3c_face_size??512;
  $('#h3cFaceDenoise').value=settings.h3c_face_denoise??0.05;
  api('/api/capabilities').then(s=>{$('#h3cFaceRefine').disabled=!s.face_refine?.ready;$('#faceRefineState').textContent=s.face_refine?.ready?'Metal 面部精修已就绪 · 可选，默认关闭':'面部精修等待工作台更新；当前任务继续原流程'}).catch(()=>{});
  $('#h3cResident').checked=settings.h3c_resident??true;
  $('#h3cStreaming').checked=settings.h3c_ssd_streaming??false;
  $('#h3cStallMinutes').value=settings.h3c_stall_minutes??10;
  if(!$('#h3cSwapLimit'))$('#h3cSteps').closest('label').insertAdjacentHTML('afterend',`<label>交换内存新增停止阈值（GiB）<input id="h3cSwapLimit" type="number" min="2" max="30" step="1" value="8"></label><p class="muted">默认新增 4 GiB 提醒、超过 8 GiB 停止。提醒线为停止阈值的一半，最多 4 GiB。按每段开始时的全系统交换用量计算，其他应用也会影响；不是 SSD 写入速度或寿命指标。调高允许更多交换，可能更慢。仅对新启动的任务生效。</p>`);
  $('#h3cSwapLimit').value=settings.h3c_swap_limit_gib??8;
  $('#h3cSteps').value=settings.h3c_steps||8;$('#videoUpscale').value=settings.video_upscale||0;
  api('/api/video-backends').then(s=>{$('#nativeBackendState').textContent=(s.h3c.ready?'h3.c 与两套原生模型已就绪':'h3.c 尚未就绪：'+JSON.stringify(s.h3c.missing))+'；Real-ESRGAN '+(s.esrgan?.ready?'已就绪':'未安装完整')}).catch(e=>$('#nativeBackendState').textContent=e.message);
}
function collectShotReferenceDraft(card){
  if(!card.querySelector('[data-element-refs]'))return {};
  return {...collectShotModeDraft(card),inherit_previous:card.querySelector('[data-inherit-tail]').checked,
    ...(card.tailSelectionDirty?{inherit_previous_manual:true}:{}),
    use_element_references:card.querySelector('[data-element-refs]').checked,
    reference_angle_mode:card.querySelector('[data-angle-mode]').value,
    excluded_reference_images:[...(card.excludedReferencePaths||[])],
    manual_reference_images:[...(card.manualReferencePaths||[])]};
}
function renderShotReferencePanels(onlyId){
  for(const [index,card] of $$('#shotsGrid [data-shot-id]').entries()){
    if(onlyId&&!(Array.isArray(onlyId)?onlyId.includes(card.dataset.shotId):card.dataset.shotId===onlyId))continue;
    const s=project.shots.find(x=>x.id===card.dataset.shotId);
    card.manualReferencePaths=[...(s.manual_reference_images||[])];
    card.excludedReferencePaths=[...(s.excluded_reference_images||[])];
    const paragraph=card.querySelector('[data-reference-placeholder], .shot-references');
    paragraph.outerHTML=`<section class="shot-references"><h3>全能参考素材</h3><p class="muted">人物图参考外貌与服装，场景图参考环境特征；均不是主参考图或首帧。构图、站位、动作与运镜按任务文字执行。</p><label><input type="checkbox" data-element-refs ${s.use_element_references!==false?'checked':''}>使用本镜头勾选的人物、物品与场景辅助参考图</label><details class="task-reference-options"><summary>参考图选择策略</summary><label>参考角度策略<select data-angle-mode>${[['auto','自动：人物设定图／旧四视图；其他元素按运镜'],['multi','强制使用整组四视图'],['main','仅一张参考图（手动覆盖）']].map(([v,n])=>`<option value="${v}" ${(s.reference_angle_mode||'auto')===v?'selected':''}>${n}</option>`).join('')}</select></label></details><p class="muted" data-reference-summary aria-live="polite"></p><div data-reference-warnings></div><h4>调用元素 · 即时预览</h4><div class="shot-ref-thumbs" data-element-preview></div><div data-tail-preview></div><details class="manual-reference-box"><summary>补充参考图 · 上传外部照片（可选）</summary><label class="shot-upload-drop" data-shot-drop tabindex="0">将其他照片拖到这里，或点击选择<input type="file" multiple accept="image/png,image/jpeg,image/webp" data-shot-upload="${esc(s.id)}"><small>PNG / JPG / WEBP，每张最多 30MB；支持多张</small></label><div class="shot-ref-thumbs" data-manual-preview></div><p class="muted">与元素图库独立。点击图片可放大，移除仅取消本镜头引用，不删除原文件。选择后请点击“保存本段设置”。</p></details><section class="mode-media-box" data-omni-media></section>${s.video_stale?`<p class="reference-warning">需要重新生成：${esc(s.stale_reason||'上游参考已变化')}。原视频文件保留。</p>`:''}<p class="muted">${s.video_result?`上次后端：${esc(s.video_result.backend)} · ${s.video_result.seconds} 秒`:''}</p>${(s.video_comparisons||[]).map(c=>`<details open><summary>历史对照（只读） · ${esc(c.created_at)}</summary><p class="muted">${esc(c.note||'')}</p><div class="comparison-results">${c.results.map(r=>`<article><b>${esc(r.backend)} · ${r.status==='done'?r.seconds+' 秒':'失败'}</b>${r.video?`<video controls preload="metadata" src="${media(r.video)}"></video>`:`<p>${esc(r.message||'等待完成')}</p>`}</article>`).join('')}</div></details>`).join('')}</section>`;
    renderShotModePanel(card,s,index);
    bindShotReferencePreview(card);
  }
}
