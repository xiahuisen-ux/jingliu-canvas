function renderCustomEntities(){
  const root=$('#entitySections');
  root.insertAdjacentHTML('afterbegin',`<details class="reference-controls custom-entity-form"><summary>＋ 添加自定义人物、物品或场景</summary><label>类型<select id="customKind"><option value="characters">人物</option><option value="key_objects">物品</option><option value="locations">场景</option></select></label><label>名称<input id="customName"></label><label>外观／场景描述<textarea id="customDescription"></textarea></label><label>场景固定参照物（添加场景时必填）<input id="customAnchor" placeholder="例如：房间中央的红色落地灯"></label><button type="button" class="primary" id="addCustomEntity">添加并同步到视频任务</button><p class="muted">全能参考模式下，人物、物品和场景图片作为外观参考；首帧模式需在各段单独指定首帧图片。新增后可在各段调用列表中勾选；构图、站位、动作与运镜按视频任务文字执行。场景参考图优先3/4斜角。</p></details>`);
  $('#addCustomEntity').onclick=async()=>{const button=$('#addCustomEntity'),pid=project.id;button.disabled=true;try{const saved=await api(`/api/projects/${pid}/custom-entity`,{method:'POST',body:JSON.stringify({kind:$('#customKind').value,name:$('#customName').value,description:$('#customDescription').value,spatial_anchor:$('#customAnchor').value})});if(project?.id!==pid)return;project=saved;renderAnalysis();renderUploads();syncTaskElementChoices();renderInspector();toast('已添加并同步到视频任务调用列表，请按镜头勾选')}catch(e){toast(e.message)}finally{button.disabled=false}};
  for(const scene of project.analysis?.locations||[]){
    const card=$(`[data-entity-card="${CSS.escape(scene.id)}"]`);if(card)card.insertAdjacentHTML('beforeend',`<label>固定空间参照物<textarea data-field="spatial_anchor">${esc(scene.spatial_anchor||'一根有明显特征的立柱')}</textarea></label><p class="muted">场景主图为3/4斜角；保存文字后，后续AI剧本与分镜使用该参照物。已有剧本不自动改写。</p>`);
  }
}

function renderCharacterControls(){
  for(const character of project.analysis?.characters||[]){
    const card=$(`[data-entity-card="${CSS.escape(character.id)}"]`);if(!card)continue;
    const images=elementSourceImages(character.id);
    card.querySelector('[data-character-controls]').innerHTML=`<details class="character-voice"><summary>角色音色特征<span>编辑 / AI 生成</span></summary><label>音色描述<textarea data-field="voice_prompt" rows="3" placeholder="例如：温柔明亮的女声，语速舒缓，普通话清晰">${esc(character.voice_prompt||'Natural mid-register voice, clear articulation, moderate pace, standard Mandarin pronunciation. Keep vocal identity consistent.')}</textarea></label><div class="character-inline-actions"><button type="button" class="ghost" data-voice-generate>AI 生成描述</button><button class="ghost" data-save-entity="${esc(character.id)}">保存音色</button></div></details>
      <section class="character-state-editor"><div class="character-generate-row"><button type="button" class="primary" data-state-generate>生成角色其他状态图</button><select data-state-mode aria-label="其他状态生成方式"><option value="text" ${images.length?'':'selected'}>文生图</option><option value="image" ${images.length?'selected':''}>图生图</option></select></div>
      <p class="asset-help" data-state-edit-note ${images.length&&project.character_image_edit?.ready===false?'':'hidden'}>状态图生图需安装并启用图像编辑模型。</p>
      <input data-state-name aria-label="状态名称" placeholder="状态名称，例如：换装、机甲、年老">
      <textarea data-state-prompt aria-label="状态文字描写" rows="3" placeholder="文字描写：描述新状态、服装变化和需要保留的特征"></textarea>
      <p data-state-source-label class="asset-help">图生图只参考上方原图框中的 ${images.length} 张图片，不使用下方成品图。</p>
      ${characterResult(character,true)}</section>`;
    async function start(button,action,extra={}){
      const pid=project.id;button.disabled=true;
      try{await saveEntity(character.id,{},false);if(project?.id!==pid)return;const job=await api(`/api/projects/${pid}/action`,{method:'POST',body:JSON.stringify({action,entity_id:character.id,...extra})});if(project?.id===pid)watchJob(job)}catch(error){toast(error.message)}finally{button.disabled=false}
    }
    card.querySelector('[data-voice-generate]').onclick=event=>start(event.currentTarget,'character_voice');
    card.querySelector('[data-state-mode]').onchange=event=>{card.querySelector('[data-state-source-label]').hidden=event.target.value!=='image';card.querySelector('[data-state-edit-note]').hidden=event.target.value!=='image'||project.character_image_edit?.ready!==false};
    card.querySelector('[data-state-generate]').onclick=event=>{
      const state_name=card.querySelector('[data-state-name]').value.trim(),state_prompt=card.querySelector('[data-state-prompt]').value.trim(),state_mode=card.querySelector('[data-state-mode]').value,source_images=elementSourceImages(character.id);
      if(!state_name||!state_prompt)return toast('请填写状态名称和文字描写');
      if(state_mode==='image'&&!source_images.length)return toast('图生图需要先在上方参考框中上传原图');
      start(event.currentTarget,'asset',{state_name,state_prompt,state_mode,reference_views:1,source_images:state_mode==='image'?source_images:[]});
    };
  }
}

function renderCharacterStateSelectors(){
  for(const card of $$('#shotsGrid [data-shot-id]')){
    const shot=project.shots.find(s=>s.id===card.dataset.shotId);
    const chars=project.analysis?.characters||[];
    const prior=card.querySelector('[data-character-states]');
    const draft=prior?Object.fromEntries([...prior.querySelectorAll('select')].map(select=>[select.dataset.characterState,select.value])):shot.character_states||{};
    const holder=document.createElement('section');holder.className='reference-controls';holder.dataset.characterStates='';
    holder.title='仅对本镜头勾选调用的人物生效';
    holder.innerHTML=chars.map(c=>`<label>${esc(c.name)} · 角色状态<select data-character-state="${esc(c.id)}"><option value="">基础角色参考图</option>${(project.assets?.[c.id]?.versions||[]).filter(v=>v.state_name&&v.status==='done').map(v=>`<option value="${esc(v.id)}" ${draft[c.id]===v.id?'selected':''}>${esc(v.state_name+' · '+v.created_at)}</option>`).join('')}</select></label>`).join('');
    if(prior)prior.replaceWith(holder);else (card.querySelector('[data-state-slot]')||card.querySelector('.text-shot-body')).append(holder);
    holder.querySelectorAll('select').forEach(select=>select.onchange=()=>updateShotReferencePreview(card,true));
  }
}
