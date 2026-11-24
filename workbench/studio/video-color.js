// Color matching is an optional post-process before manual assembly.
const colorMatchDrafts=new Map();
function colorAvailableShots(){return sortedShots().filter(s=>shotVideoVersions(s).length)}
function colorToken(sid,vid){return JSON.stringify([sid,vid])}
function colorTakeLabel(s,v){return `${String(s.shot).padStart(2,'0')} ${s.title||'视频'} · 版本 ${v.number}${v.video_result?.color_match?'（已校色）':''}`}
function colorMatchDraft(){
  if(!project)return null;
  const shots=colorAvailableShots();
  if(!colorMatchDrafts.has(project.id)){
    let saved;try{saved=JSON.parse(localStorage.getItem('video-color-'+project.id))}catch{}
    const valid=saved&&typeof saved==='object'&&Array.isArray(saved.targets)&&saved.versions&&typeof saved.versions==='object'&&saved.settings&&typeof saved.settings==='object';
    colorMatchDrafts.set(project.id,valid?saved:{reference:'',targets:shots.slice(1).map(s=>s.id),versions:{},settings:{strength:.65,brightness:0,contrast:1,saturation:1},select_results:true,open:true});
  }
  const draft=colorMatchDrafts.get(project.id),tokens=shots.flatMap(s=>shotVideoVersions(s).map(v=>colorToken(s.id,v.id)));
  if(!tokens.includes(draft.reference)){
    const s=shots[0],v=s&&(shotVideoVersions(s).find(v=>v.id===assemblyVersion(s))||shotVideoVersions(s).at(-1));
    draft.reference=v?colorToken(s.id,v.id):'';
  }
  const refSid=draft.reference?JSON.parse(draft.reference)[0]:null;
  draft.targets=draft.targets.filter(id=>id!==refSid&&shots.some(s=>s.id===id));
  for(const s of shots){
    const versions=shotVideoVersions(s);
    if(!versions.some(v=>v.id===draft.versions[s.id]))draft.versions[s.id]=(versions.find(v=>v.id===assemblyVersion(s))||versions.at(-1)).id;
  }
  return draft;
}
function rememberColorMatch(){try{localStorage.setItem('video-color-'+project.id,JSON.stringify(colorMatchDraft()))}catch{}}
function colorMatchPayload(){
  const d=colorMatchDraft();
  if(!d?.reference)throw new Error('请先生成视频，再选择参考版本');
  const [sid,vid]=JSON.parse(d.reference);
  const targets=colorAvailableShots().filter(s=>d.targets.includes(s.id)).map(s=>({shot_id:s.id,version_id:d.versions[s.id]}));
  if(!targets.length)throw new Error('请至少勾选一个其他段落进行色彩对齐');
  return {reference:{shot_id:sid,version_id:vid},targets,settings:{...d.settings},select_results:!!d.select_results};
}
function renderColorMatchPanel(){
  const box=$('#colorMatchPanel');if(!box||!project)return;
  const d=colorMatchDraft(),shots=colorAvailableShots(),ref=d.reference?JSON.parse(d.reference):[];
  const refShot=shots.find(s=>s.id===ref[0]),refVideo=refShot&&shotVideoVersions(refShot).find(v=>v.id===ref[1]);
  setStableHTML(box,`<details class="color-match" ${d.open?'open':''}><summary>合成前色彩对齐 <small>可选 · 保留原片</small></summary><div class="color-match-body">${shots.length<2?'<p class="muted">至少两个段落有视频后，可选择参考色，把其他段落往同一色调对齐。</p>':`<div class="color-main-controls"><label>参考视频<select id="colorReference">${shots.flatMap(s=>shotVideoVersions(s).map(v=>`<option value="${esc(colorToken(s.id,v.id))}" ${d.reference===colorToken(s.id,v.id)?'selected':''}>${esc(colorTakeLabel(s,v))}</option>`)).join('')}</select></label><label>匹配强度 <output id="colorStrengthValue">${Math.round(d.settings.strength*100)}%</output><input id="colorStrength" type="range" min="0" max="100" step="5" value="${Math.round(d.settings.strength*100)}"></label></div><details class="color-reference-preview"><summary>查看参考视频</summary><video controls preload="metadata" src="${media(refVideo.video)}"></video></details><div class="color-target-heading"><strong>选择需要对齐的段落与版本</strong><button class="ghost" id="colorSelectAll">全选其他段落</button><button class="ghost" id="colorSelectNone">清空</button></div><div class="color-targets">${shots.map(s=>`<div class="color-target"><label><input type="checkbox" data-color-target="${esc(s.id)}" ${d.targets.includes(s.id)?'checked':''} ${s.id===ref[0]?'disabled':''}><span>${String(s.shot).padStart(2,'0')} ${esc(s.title||'视频')}${s.id===ref[0]?'（参考，保持原样）':''}</span></label><select aria-label="第 ${s.shot} 段待校色版本" data-color-version="${esc(s.id)}" ${s.id===ref[0]?'disabled':''}>${shotVideoVersions(s).map(v=>`<option value="${esc(v.id)}" ${d.versions[s.id]===v.id?'selected':''}>版本 ${v.number}${v.video_result?.color_match?' · 已校色':''}</option>`).join('')}</select></div>`).join('')}</div><details class="color-fine"><summary>微调亮度、对比度、饱和度</summary><div>${[['brightness','亮度',-.2,.2,.01],['contrast','对比度',.5,1.5,.05],['saturation','饱和度',0,2,.05]].map(([key,label,min,max,step])=>`<label>${label}<input type="number" data-color-setting="${key}" value="${d.settings[key]}" min="${min}" max="${max}" step="${step}"></label>`).join('')}</div><p class="muted">作用于本次勾选的版本。匹配强度设为 0% 时，可只做微调。</p></details><label class="color-auto-select"><input id="colorSelectResults" type="checkbox" ${d.select_results?'checked':''}>完成后选用校色版参与合成</label><button class="primary" id="colorMatchStart" ${d.targets.length?'':'disabled'}>生成校色版本（${d.targets.length} 段）</button><p class="muted">参考整段的多帧色彩，固定映射以避免逐帧校色闪烁；保留声音、时长与原视频。完成后在下方比较、选用，再手动合成。构图差别大时可降低强度。</p>`}</div></details>`);
  const outer=box.querySelector('details.color-match');outer.ontoggle=()=>{d.open=outer.open;rememberColorMatch()};
  if(shots.length<2)return;
  $('#colorReference').onchange=e=>{d.reference=e.target.value;rememberColorMatch();renderColorMatchPanel()};
  $('#colorStrength').oninput=e=>{d.settings.strength=Number(e.target.value)/100;$('#colorStrengthValue').textContent=e.target.value+'%';rememberColorMatch()};
  for(const input of box.querySelectorAll('[data-color-target]'))input.onchange=()=>{d.targets=d.targets.filter(id=>id!==input.dataset.colorTarget);if(input.checked)d.targets.push(input.dataset.colorTarget);rememberColorMatch();renderColorMatchPanel()};
  for(const input of box.querySelectorAll('[data-color-version]'))input.onchange=()=>{d.versions[input.dataset.colorVersion]=input.value;rememberColorMatch()};
  for(const input of box.querySelectorAll('[data-color-setting]'))input.onchange=()=>{if(!input.value||!input.checkValidity()){toast('请输入允许范围内的微调数值');input.value=d.settings[input.dataset.colorSetting];return}d.settings[input.dataset.colorSetting]=Number(input.value);rememberColorMatch()};
  $('#colorSelectAll').onclick=()=>{d.targets=shots.filter(s=>s.id!==ref[0]).map(s=>s.id);rememberColorMatch();renderColorMatchPanel()};
  $('#colorSelectNone').onclick=()=>{d.targets=[];rememberColorMatch();renderColorMatchPanel()};
  $('#colorSelectResults').onchange=e=>{d.select_results=e.target.checked;rememberColorMatch()};
  $('#colorMatchStart').onclick=()=>runAction('color_match');
}
