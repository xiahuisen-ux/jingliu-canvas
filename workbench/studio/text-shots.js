const shotPromptSections=[['description','剧情与逐秒动作'],['camera','镜头'],['dialogue','对白与歌词']];
function shotPromptText(shot){return shotPromptSections.map(([key,label])=>'【'+label+'】\n'+(shot[key]||'')).join('\n\n')}
const shotEnglishHeading='【H3 英文提示词】';
function shotFullPromptText(shot){return shotPromptText(shot)+'\n\n'+shotEnglishHeading+'\n'+(shot.motion_prompt||'')}
function parseShotPrompt(text){
  const sections=[...shotPromptSections];if(text.includes(shotEnglishHeading))sections.push(['motion_prompt','H3 英文提示词']);
  const marks=sections.map(([,label])=>'【'+label+'】'),positions=marks.map(mark=>text.indexOf(mark));
  if(positions.some((p,i)=>p<0||(i&&p<=positions[i-1]))||marks.some(mark=>text.indexOf(mark)!==text.lastIndexOf(mark)))throw new Error('请保留提示词分区标题，内容可自由修改');
  return Object.fromEntries(sections.map(([key],i)=>[key,text.slice(positions[i]+marks[i].length,i+1<positions.length?positions[i+1]:text.length).trim()]));
}
function shotEnglishDraft(card){const draft=parseShotPrompt(card.querySelector('[data-complete-prompt]').value);return draft.motion_prompt??card.querySelector('[data-english-prompt]').value}
function setShotEnglishDraft(card,text){const editor=card.querySelector('[data-complete-prompt]');editor.value=shotFullPromptText({...parseShotPrompt(editor.value),motion_prompt:text});card.querySelector('[data-english-prompt]').value=text}
function shotAudioKey(s){return JSON.stringify([s.audio_segment?.status,s.audio_segment?.mode,s.audio_segment?.path,s.audio_segment?.label,s.audio_segment?.entry_note,s.timeline_start,s.timeline_end,s.audio_reference_timing,project.audio_timeline?.song_start,s.audio_segment?.mode==='generated'?s.video:null,!!s.video_stale])}
function masterAudioKey(){const t=project.audio_timeline||{};return JSON.stringify([t.status,t.entry_note,t.mode,t.path,t.download_path,t.duration,t.generated_sources,(project.shots||[]).filter(s=>s.audio_segment?.mode==='generated').map(s=>[s.id,s.video,!!s.video_stale])])}
function syncShotAudio(){
  const master=$('#shotsGrid .master-audio');
  if(master&&master.dataset.audioKey!==masterAudioKey())master.outerHTML=masterAudioPreview();
  for(const card of $$('#shotsGrid [data-shot-id]')){
    const shot=project.shots.find(s=>s.id===card.dataset.shotId),box=card.querySelector('.shot-audio');
    if(shot&&box&&box.dataset.audioKey!==shotAudioKey(shot))box.outerHTML=shotAudioPreview(shot);
  }
}
function shotAudioPreview(s){
  const segment=s.audio_segment;if(!segment)return '';
  if(segment.status==='needs_revision')return `<div class="shot-audio" data-audio-key="${esc(shotAudioKey(s))}"><strong>本段音轨待制作 · 全片 ${s.timeline_start}–${s.timeline_end} 秒</strong><small>${esc(segment.entry_note||'音频尚未准备完成，请先更新音轨再生成本段。')}</small></div>`;
  if(segment.mode==='generated'){
    const ready=s.video&&!s.video_stale;
    const entry=project.audio_timeline?.song_start;
    const songNote=Number.isFinite(entry)&&entry>=segment.end?` 歌曲从全片第 ${entry} 秒进入，本段只安排对白。`:'';
    return `<div class="shot-audio" data-audio-key="${esc(shotAudioKey(s))}"><span>自然对白 · 全片 ${s.timeline_start}–${s.timeline_end} 秒</span>${ready?`<audio controls preload="metadata" src="${media(s.video)}"></audio>`:''}<small>${ready?'试听本段视频中的原生对白。':'对白随本段视频一起生成，完成后可试听。'}保留人物原声；不会用旧配音覆盖。${songNote}</small></div>`;
  }
  const t=s.audio_reference_timing,seconds=n=>Number(n.toFixed(3));
  const timing=t?`<small>录音从本段第 0 秒播放（全片第 ${seconds(t.global_start)} 秒）${Number.isFinite(t.source_start)?`；对应原录音 ${seconds(t.source_start)}–${seconds(t.source_end)} 秒`:''}。</small>${Number.isFinite(t.first_vocal_start)?`<small>本段人声${t.timing_verified?'':'约'}从第 ${seconds(t.first_vocal_start)} 秒进入；${esc([...new Set(t.cues.map(c=>c.name).filter(Boolean))].join('、'))}对口型，实际录音优先。</small>`:''}`:'';
  return `<div class="shot-audio" data-audio-key="${esc(shotAudioKey(s))}"><span>${esc(segment.label||'本段歌曲原音')} · 全片 ${s.timeline_start}–${s.timeline_end} 秒</span>${timing}${segment.entry_note?`<small>${esc(segment.entry_note)}</small>`:''}<audio controls preload="metadata" src="${media(segment.path)}"></audio><a href="${media(segment.path)}" download>下载本段音频</a><small>全能参考模式会传入此音轨和入声时序；其他模式仅合成原音。修改台词文字不会重制音频。</small></div>`;
}
function masterAudioPreview(){
  const track=project.audio_timeline;if(!track)return '';
  if(track.status==='needs_revision')return `<section class="shot-audio master-audio" data-audio-key="${esc(masterAudioKey())}"><strong>整片音轨待完成 · ${track.duration} 秒</strong><small>${esc(track.entry_note||'部分段落音轨待制作；已有分段录音可在下方试听。')}</small></section>`;
  const pending=track.mode==='hybrid'&&(!track.path||(project.shots||[]).some(s=>s.audio_segment?.mode==='generated'&&(!s.video||s.video_stale||track.generated_sources?.[s.id]!==s.video)));
  if(pending)return `<section class="shot-audio master-audio" data-audio-key="${esc(masterAudioKey())}"><strong>整片音轨 · ${track.duration} 秒</strong><small>歌曲时序已准备，开场自然对白待生成。首段视频完成后自动组成完整音轨，提供试听和下载。</small></section>`;
  return `<section class="shot-audio master-audio" data-audio-key="${esc(masterAudioKey())}"><strong>整片音轨 · ${track.duration} 秒</strong><audio controls preload="metadata" src="${media(track.path)}"></audio><a href="${media(track.download_path||track.path)}" download>下载完整音频</a><small>对白、歌曲与本段口型均以这条音轨为准。逐词时间码为自动定位，成片需试听核对。</small></section>`;
}
function renderTextShots(){
  if(typeof renderTailDefaults==='function')renderTailDefaults();
  releaseShotReferencePreviews();
  const entities=progressEntities(project),shots=sortedShots();
  if(typeof renderGenerationPickers==='function')renderGenerationPickers();
  $('#shotsGrid').innerHTML=masterAudioPreview()+shots.map((s,index)=>`<article class="shot-card task-${index%2?'even':'odd'}" data-shot-id="${esc(s.id)}"><div class="shot-head"><span class="shot-no">任务 ${String(s.shot).padStart(2,'0')}</span><span class="shot-title">${esc(s.title)}</span><span class="shot-duration">${s.duration} 秒 · ${esc(({planned:'待生成',video_ready:'视频已就绪',reviewed:'已质检'})[s.status]||s.status)}</span></div><div class="text-shot-body">
  <div data-mode-slot></div>
  <details class="task-fold" data-refs-details><summary>人物／场景与参考音频 <small data-refs-mode-note></small></summary><fieldset><legend>直接调用元素</legend><div class="task-elements">${entities.map(e=>`<label><input type="checkbox" data-task-element="${esc(e.id)}" ${(s.element_ids||[]).includes(e.id)?'checked':''}>${esc(e.name)}</label>`).join('')}</div></fieldset><div data-state-slot></div><p data-reference-placeholder></p>${shotAudioPreview(s)}</details>
  <div class="task-writing-row"><section class="task-writing"><h3>剧情 · 运镜 · 对白 · H3 提示词</h3><label class="task-editor-label">在同一框内编辑，保留分区标题<textarea data-complete-prompt rows="22" spellcheck="false">${esc(shotFullPromptText(s))}</textarea></label><textarea data-english-prompt hidden>${esc(s.motion_prompt||'')}</textarea><div class="shot-actions"><button class="ghost" data-translate-h3="${esc(s.id)}">一键生成英文</button></div><p class="muted" data-translation-status aria-live="polite">改好中文后可一键生成英文；对白、歌词保留原文。</p><div data-translation-result hidden></div></section><aside class="shot-chat" data-shot-chat></aside></div>
  <div data-tail-slot></div><div class="shot-actions task-footer"><button class="ghost" data-save-task="${esc(s.id)}">保存本段设置</button><button class="primary" data-text-video="${esc(s.id)}">保存并生成视频</button></div></div></article>`).join('')||'<p class="muted">先按剧本和设置时长拆分视频任务。</p>';
  $$('[data-save-task]').forEach(b=>b.onclick=async()=>{try{await saveTextShots(b.dataset.saveTask);toast('文字与调用元素已保存')}catch(e){toast(e.message)}});
  $$('[data-text-video]').forEach(b=>b.onclick=async()=>{try{await saveTextShots(b.dataset.textVideo);await runAction('video',{shotId:b.dataset.textVideo})}catch(e){toast(e.message)}});
  renderShotReferencePanels();
  renderCharacterStateSelectors();
  if(typeof bindH3Translation==='function')bindH3Translation();
  if(typeof bindShotChats==='function')bindShotChats();
  $$('[data-save-task]').forEach(b=>b.textContent='保存本段设置');
}
let savingTextShots=false;
function syncTaskElementChoices(){
  const entities=progressEntities(project);
  for(const card of $$('#shotsGrid [data-shot-id]')){
    const list=card.querySelector('.task-elements');if(!list)continue;
    const checked=new Set([...list.querySelectorAll('[data-task-element]:checked')].map(input=>input.dataset.taskElement));
    list.innerHTML=entities.map(e=>`<label><input type="checkbox" data-task-element="${esc(e.id)}" ${checked.has(e.id)?'checked':''}>${esc(e.name)}</label>`).join('');
    for(const input of list.querySelectorAll('[data-task-element]'))input.onchange=()=>{card.elementSelectionDirty=true;updateShotReferencePreview(card,true);};
  }
  renderCharacterStateSelectors();
  for(const card of $$('#shotsGrid [data-shot-id]')){if(card.querySelector('[data-element-preview]'))updateShotReferencePreview(card);}
}
function elementSelectionChanges(prior,selectedIds,dirty,restore){
  const changes=restore?{auto_elements:true,added_element_ids:[],excluded_element_ids:[]}:{};
  if(dirty&&(restore||prior.auto_elements!==false)){
    const suggested=new Set(prior.suggested_element_ids||[]),selected=new Set(selectedIds);
    changes.added_element_ids=[...selected].filter(id=>!suggested.has(id));
    changes.excluded_element_ids=[...suggested].filter(id=>!selected.has(id));
  }
  return changes;
}
async function saveTextShots(onlyId){
  if(savingTextShots)throw new Error('正在保存镜头，请稍候');
  savingTextShots=true;
  const pid=project.id;
  try{
  await ensureShotModeBackend();
  if(project.id!==pid)throw new Error('项目已切换，未保存镜头修改');
  for(const card of $$('#shotsGrid [data-shot-id]')){
    if(onlyId&&!(Array.isArray(onlyId)?onlyId.includes(card.dataset.shotId):card.dataset.shotId===onlyId))continue;
    await uploadPendingShotReferences(card,pid);
    await uploadPendingShotModeFiles(card,pid);
  }
  if(project.id!==pid)throw new Error('项目已切换，未保存镜头修改');
  const drafts=new Map();
  for(const card of $$('#shotsGrid [data-shot-id]')){
    if(onlyId&&!(Array.isArray(onlyId)?onlyId.includes(card.dataset.shotId):card.dataset.shotId===onlyId))continue;
    const changes=parseShotPrompt(card.querySelector('[data-complete-prompt]').value);changes.motion_prompt=(changes.motion_prompt??card.querySelector('[data-english-prompt]').value).trim();for(const el of card.querySelectorAll('[data-task-field]'))changes[el.dataset.taskField]=el.dataset.taskField==='duration'?Number(el.value):el.value;
    changes.character_states=Object.fromEntries([...card.querySelectorAll('[data-character-state]')].map(input=>[input.dataset.characterState,input.value]));
    changes.element_ids=[...card.querySelectorAll('[data-task-element]:checked')].map(el=>el.dataset.taskElement);
    const prior=project.shots.find(s=>s.id===card.dataset.shotId);
    // Keep structured actor actions only for explicitly selected actors/props.
    changes.character_actions=(prior.character_actions||[]).filter(a=>changes.element_ids.includes(a.character_id)).map(a=>({...a,element_ids:(a.element_ids||[]).filter(id=>changes.element_ids.includes(id))}));
    if(changes.description!==(prior.description||'')||changes.motion_prompt!==(prior.motion_prompt||''))changes.character_actions=[];
    Object.assign(changes,elementSelectionChanges(prior,changes.element_ids,card.elementSelectionDirty,card.restoreAutoElements));
    Object.assign(changes,collectShotReferenceDraft(card));drafts.set(card.dataset.shotId,changes);
  }
  if(!drafts.size)return;
  const shots=project.shots.map(s=>drafts.has(s.id)?{...s,...drafts.get(s.id)}:s);
  const saved=await api(`/api/projects/${pid}/save`,{method:'POST',body:JSON.stringify({shots})});
  if(project.id!==pid)return;
  project=saved;
  for(const card of $$('#shotsGrid [data-shot-id]')){
    if(!drafts.has(card.dataset.shotId))continue;
    card.restoreAutoElements=false;card.elementSelectionDirty=false;
    const shot=project.shots.find(s=>s.id===card.dataset.shotId);
    for(const input of card.querySelectorAll('[data-task-element]'))input.checked=(shot.element_ids||[]).includes(input.dataset.taskElement);
  }
  renderInspector();renderVideos();renderShotReferencePanels(onlyId);for(const card of $$('#shotsGrid [data-shot-id]')){if(!drafts.has(card.dataset.shotId))continue;const shot=project.shots.find(s=>s.id===card.dataset.shotId);const editor=card.querySelector('[data-complete-prompt]');if(editor)editor.value=shotFullPromptText(shot);const english=card.querySelector('[data-english-prompt]');if(english)english.value=shot.motion_prompt||'';const head=card.querySelector('.shot-duration');if(head)head.textContent=shot.duration+' 秒 · '+(shot.status==='planned'?'待生成视频':'已保存');}
  }finally{savingTextShots=false}
}
