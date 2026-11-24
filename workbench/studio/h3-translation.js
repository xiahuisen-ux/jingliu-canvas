function h3TranslationModelName(){return typeof textConfig!=='undefined'&&textConfig.provider!=='local'?(textConfig.provider==='deepseek'?'DeepSeek':textConfig.provider==='openai'?'OpenAI':'文字 API'):'Qwen3.8'}
function refreshH3TranslationLabels(){for(const button of $$('[data-translate-h3]'))button.textContent='一键生成英文 · '+h3TranslationModelName()}
function h3DraftSource(card){
  return {...parseShotPrompt(card.querySelector('[data-complete-prompt]').value),duration:Number(card.querySelector('[data-task-field="duration"]').value)};
}
function h3SameSource(a,b){return ['description','camera','dialogue','duration'].every(k=>a?.[k]===b?.[k])}
function updateH3TranslationStatus(card){
  const shot=project.shots.find(s=>s.id===card.dataset.shotId),status=card.querySelector('[data-translation-status]');
  if(!shot||!status)return;
  try{
    const paired=shot.h3_editor_source;
    const source=paired?{...paired.fields,duration:paired.duration}:shot.h3_translation?.source;
    if(source){
      status.textContent=h3SameSource(h3DraftSource(card),source)
        ?'本段中文与英文已配套保存；可继续修改英文。对白与歌词保留原文，录音不会随文字重制。'
        :'中文已修改，英文尚未同步，请重新生成英文；原录音不会自动更新。';
    }
  }catch(e){status.textContent=e.message}
}
function bindH3Translation(){
  refreshH3TranslationLabels();
  for(const card of $$('#shotsGrid [data-shot-id]')){
    const button=card.querySelector('[data-translate-h3]');if(!button)continue;
    button.onclick=()=>translateH3Shot(card);
    for(const input of card.querySelectorAll('[data-complete-prompt], [data-task-field="duration"]'))input.addEventListener('input',()=>updateH3TranslationStatus(card));
    updateH3TranslationStatus(card);
  }
}
async function translateH3Shot(card){
  const pid=project.id,id=card.dataset.shotId,button=card.querySelector('[data-translate-h3]'),status=card.querySelector('[data-translation-status]');
  button.disabled=true;
  try{
    const capability=await api('/api/capabilities');
    if(!capability.h3_translation)throw new Error('服务尚未启用英文翻译，请重新启动工作台后刷新');
    await saveTextShots(id);
    if(project.id!==pid)throw new Error('工程已切换，未启动翻译');
    const baseline=JSON.parse(JSON.stringify(project));
    const payload={action:'translate_h3',shot_id:id};
    const job=await api(`/api/projects/${pid}/action`,{method:'POST',body:JSON.stringify(payload)});
    status.textContent=h3TranslationModelName()+' 正在按 H3 规范生成英文，可继续查看其他段落。';
    card.querySelector('[data-translation-result]').hidden=true;
    rememberProgress(job,baseline,payload);watchJob(job);
  }catch(e){button.disabled=false;status.textContent=e.message;toast(e.message)}
}
function finishH3Translation(job){
  const card=$$('#shotsGrid [data-shot-id]').find(c=>c.dataset.shotId===job.shot_id);
  if(!card)return;
  const button=card.querySelector('[data-translate-h3]');if(button)button.disabled=false;
  const status=card.querySelector('[data-translation-status]');
  if(job.status!=='done'){if(status)status.textContent=job.message;return}
  const shot=project.shots.find(s=>s.id===job.shot_id),english=card.querySelector('[data-english-prompt]');
  if(!shot||!english)return;
  let same=false;try{same=h3SameSource(h3DraftSource(card),job.translation_source)}catch{}
  if(same&&shotEnglishDraft(card).trim()===(job.previous_english||'').trim()){
    setShotEnglishDraft(card,shot.motion_prompt);updateH3TranslationStatus(card);
    updateShotReferencePreview(card);return;
  }
  // Leave both live drafts intact when the user edits during inference.
  const result=card.querySelector('[data-translation-result]');result.hidden=false;
  status.textContent='英文已保存，但你在翻译期间修改了草稿；当前输入保留。可对照下方结果，或保存新中文后重新翻译。';
  result.innerHTML=`<details open><summary>查看本次生成的英文</summary><textarea readonly rows="10" aria-label="本次生成的英文">${esc(shot.motion_prompt)}</textarea><button class="ghost" data-adopt-translation>用本次结果替换英文草稿</button></details>`;
  result.querySelector('[data-adopt-translation]').onclick=()=>{setShotEnglishDraft(card,shot.motion_prompt);result.hidden=true;updateH3TranslationStatus(card);updateShotReferencePreview(card,true)};
}
