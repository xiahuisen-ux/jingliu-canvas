const lipDrafts=new Map();
let lipViewProject=null,lipCatalog={videos:[],audios:[]},lipReady=false,lipFps=24,lipLoading=0,lipSyncTimer=null;
function lipDefaultParameters(){
  try{const v=JSON.parse(localStorage.getItem('mirrorflow-musetalk-defaults-v1'));if(v&&Number.isInteger(v.batch_size)&&v.batch_size>=1&&v.batch_size<=8&&Number.isInteger(v.extra_margin)&&v.extra_margin>=0&&v.extra_margin<=40)return {batch_size:v.batch_size,extra_margin:v.extra_margin};}catch{}
  return {batch_size:4,extra_margin:10};
}
function lipDraft(){
  if(!project)return null;
  if(!lipDrafts.has(project.id))lipDrafts.set(project.id,{video:'',audio:'',offset_ms:0,markers:[],region:null,...lipDefaultParameters(),reviews:{},loadedVideo:''});
  return lipDrafts.get(project.id);
}
function lipPause(){const v=$('#lipPlayer'),a=$('#lipAudio');v?.pause();a?.pause();clearTimeout(lipSyncTimer);lipSyncTimer=null;}
function lipAudioTime(videoTime,offset){return videoTime-offset/1000;}
function lipSyncAudio(force=false){
  const d=lipDraft(),v=$('#lipPlayer'),a=$('#lipAudio');if(!d||!v.src||!a.src)return;
  const target=lipAudioTime(v.currentTime,d.offset_ms);
  a.playbackRate=v.playbackRate;
  if(target<0||target>=a.duration){a.pause();return;}
  if(force||Math.abs(a.currentTime-target)>.12)a.currentTime=Math.max(0,target);
  if(!v.paused&&a.paused)a.play().catch(()=>{});
}
function lipStartAudio(){
  clearTimeout(lipSyncTimer);lipSyncAudio(true);
  const d=lipDraft(),v=$('#lipPlayer');if(!d||v.paused)return;
  const target=lipAudioTime(v.currentTime,d.offset_ms);
  if(target<0)lipSyncTimer=setTimeout(()=>lipSyncAudio(true),-target*1000/v.playbackRate);
}
function lipClock(){
  const v=$('#lipPlayer'),duration=Number.isFinite(v.duration)?v.duration:0;
  $('#lipTime').textContent=`${v.currentTime.toFixed(3)} / ${duration.toFixed(3)} 秒`;
  $('#lipSeek').max=duration;$('#lipSeek').value=v.currentTime;
  if(!v.paused)lipSyncAudio();
}
function lipStep(direction){const v=$('#lipPlayer');lipPause();v.currentTime=Math.max(0,Math.min(Number.isFinite(v.duration)?v.duration:0,v.currentTime+direction/lipFps));lipClock();}
function lipOffset(value){
  const d=lipDraft(),n=Number(value);if(!d||!Number.isFinite(n)||n < -5000||n>5000)return false;
  d.offset_ms=Math.round(n);$('#lipOffset').value=d.offset_ms;$('#lipOffsetRange').value=Math.max(-2000,Math.min(2000,d.offset_ms));lipStartAudio();return true;
}
function renderLipMarkers(){
  const d=lipDraft();if(!d)return;
  $('#lipMarkers').innerHTML=d.markers.map((m,i)=>`<div class="lip-marker"><button class="ghost" data-lip-time="${m.time}">${m.time.toFixed(3)}s</button><span>${esc(m.note)}</span><button class="ghost" data-lip-remove="${i}" aria-label="删除校对标记">×</button></div>`).join('')||'<p class="muted">暂停在问题帧，添加校对备注。</p>';
  for(const b of $$('[data-lip-time]'))b.onclick=()=>{lipPause();$('#lipPlayer').currentTime=Number(b.dataset.lipTime);};
  for(const b of $$('[data-lip-remove]'))b.onclick=()=>{d.markers.splice(Number(b.dataset.lipRemove),1);renderLipMarkers();};
}
async function lipSetVideo(){
  lipPause();const d=lipDraft(),pid=project.id,source=d.video,token=++lipLoading;
  $('#lipPlayer').removeAttribute('src');$('#lipAudio').removeAttribute('src');
  if(!source){$('#lipPlayer').load();$('#lipExport').disabled=true;return;}
  if(d.loadedVideo!==source){
    if(d.loadedVideo)d.reviews[d.loadedVideo]={markers:d.markers.map(m=>({...m})),offset_ms:d.offset_ms,region:d.region};
    const review=d.reviews[source]||project.lipsync_reviews?.[source];d.markers=(review?.markers||[]).map(m=>({...m}));d.region=review?.region||null;lipOffset(review?.offset_ms||0);d.loadedVideo=source;
  }
  $('#lipRegionCanvas').hidden=true;$('#lipRegionHelp').hidden=true;lipRegionLabel();
  renderLipMarkers();
  $('#lipPlayer').src=media(source);$('#lipPlayer').muted=true;
  lipSetAudio();$('#lipExport').disabled=false;$('#lipGenerate').disabled=!lipReady;
  try{
    const info=await api(`/api/projects/${pid}/lip-sync/info`,{method:'POST',body:JSON.stringify({video:source})});
    if(token!==lipLoading||project?.id!==pid)return;
    lipFps=info.fps||24;$('#lipFrameRate').textContent=`视频帧率 ${lipFps.toFixed(3)} fps · 每帧 ${(1000/lipFps).toFixed(1)} 毫秒${info.variable_fps?' · 可变帧率，步进按平均帧率':''}`;
  }catch(e){if(token===lipLoading){lipFps=24;$('#lipFrameRate').textContent='帧率读取失败，暂按 24 fps 步进：'+e.message;}}
}
function lipSetAudio(){lipPause();const d=lipDraft();if(d?.video)$('#lipAudio').src=media(d.audio||d.video);else $('#lipAudio').removeAttribute('src');}
async function renderLipSync(force=false){
  const pid=project?.id;$('#lipNoProject').hidden=!!pid;$('#lipWorkspace').hidden=!pid;if(!pid){lipPause();lipViewProject=null;return;}
  if(lipViewProject===pid&&!force){renderLipResults();return;}
  lipPause();lipViewProject=pid;
  try{
    const [rows,backend]=await Promise.all([api(`/api/projects/${pid}/lip-sync/catalog`),api('/api/musetalk')]);
    if(project?.id!==pid)return;
    lipCatalog=rows;lipReady=backend.ready;const d=lipDraft();
    if(!rows.videos.some(v=>v.path===d.video))d.video=rows.videos[0]?.path||'';
    if(d.audio&&!rows.audios.some(a=>a.path===d.audio))d.audio='';
    $('#lipVideoSource').innerHTML=rows.videos.map(v=>`<option value="${esc(v.path)}">${esc(v.label)}</option>`).join('')||'<option value="">暂无视频，请上传或先生成</option>';
    $('#lipAudioSource').innerHTML='<option value="">所选视频原声</option>'+rows.audios.map(a=>`<option value="${esc(a.path)}">${esc(a.label)}</option>`).join('');
    $('#lipVideoSource').value=d.video;$('#lipAudioSource').value=d.audio;$('#lipBackend').textContent=backend.message+(backend.ready&&!backend.validated?' · 实际效果与速度待验收':'');
    $('#lipBatch').value=d.batch_size;$('#lipMargin').value=d.extra_margin;
    await lipSetVideo();renderLipResults();
  }catch(e){$('#lipStatus').textContent=e.message;lipViewProject=null;}
}
async function lipUpload(file,kind){
  if(!file||!project)return;const pid=project.id;
  if(file.size>150*1024*1024){toast('文件不能超过 150MB');return;}
  const d=lipDraft();$('#lipStatus').textContent='正在上传素材…';
  try{const form=new FormData();form.append('file',file);form.append('kind',kind);
    const r=await fetch(`/api/projects/${pid}/upload-media`,{method:'POST',body:form}),entry=await r.json();if(!r.ok)throw new Error(entry.error||'上传失败');
    if(project?.id!==pid)return;
    if(kind==='audio')d.audio=entry.path;else d.video=entry.path;
    const fresh=await api(`/api/projects/${pid}`);if(project?.id!==pid)return;project=fresh;await renderLipSync(true);$('#lipStatus').textContent='素材已保存到本工程';
  }catch(e){if(project?.id===pid)$('#lipStatus').textContent=e.message;}
}
async function lipRun(mode){
  if(!project)return;const d=lipDraft();
  if(!$('#lipOffset').checkValidity()||!lipOffset($('#lipOffset').value)){toast('声音偏移需在 -5000 至 5000 毫秒之间');return;}
  if(!d.video){toast('请先选择视频');return;}
  if(!$('#lipBatch').checkValidity()||!$('#lipMargin').checkValidity()){toast('请检查 MuseTalk 1.5 参数');return;}
  d.batch_size=Number($('#lipBatch').value);d.extra_margin=Number($('#lipMargin').value);lipPause();
  try{const payload={action:'lip_sync',mode,video:d.video,audio:d.audio,offset_ms:d.offset_ms,batch_size:d.batch_size,extra_margin:d.extra_margin};
    payload.region=d.region;
    const job=await api(`/api/projects/${project.id}/action`,{method:'POST',body:JSON.stringify(payload)});watchJob(job);$('#lipStatus').textContent='处理已提交，进度显示在项目监督栏';
  }catch(e){$('#lipStatus').textContent=e.message;toast(e.message);}
}
function lipSkipNote(r){return r.metrics?.skipped_frames?.length?`<p class="reference-warning">${r.metrics.skipped_frames.length} / ${r.metrics.frames} 帧未检测到人脸，已保留这些帧的原画面；请检查嘴型连续性。</p>`:'';}
function renderLipResults(){
  if(!project)return;
  const rows=[...(project.lipsync_results||[])].reverse();
  setStableHTML($('#lipResults'),rows.map(r=>`<article class="lip-result"><h3>${r.mode==='musetalk'?'MuseTalk 1.5 嘴型版':'音轨同步版'} · ${esc(r.created_at)} · 偏移 ${r.offset_ms}ms</h3>${lipSkipNote(r)}<div class="lip-compare"><figure><video controls preload="metadata" src="${media(r.source_video)}"></video><figcaption>原片</figcaption></figure><figure><video controls preload="metadata" src="${media(r.video)}"></video><figcaption>校对结果 · ${Number(r.duration).toFixed(3)} 秒</figcaption></figure></div><div class="toolbar"><button class="ghost" data-lip-compare="${esc(r.id)}">同步播放对比</button><button class="ghost" data-lip-result="${esc(r.video)}">继续校对此版本</button><a class="ghost" href="${media(r.video)}" download>下载视频</a>${r.shot_id?'<button class="ghost" data-stage-jump="video">去 05 选版合成</button>':''}</div></article>`).join('')||'<p class="muted">尚未导出校对结果。原视频会始终保留。</p>');
  for(const b of $$('[data-lip-result]'))b.onclick=async()=>{lipDraft().video=b.dataset.lipResult;await renderLipSync(true);};
  for(const b of $$('#lipResults [data-stage-jump]'))b.onclick=()=>showStage('video');
  for(const b of $$('[data-lip-compare]'))b.onclick=()=>{lipPause();const players=[...b.closest('article').querySelectorAll('video')];players.forEach((v,i)=>{v.currentTime=0;v.muted=i===0;v.play().catch(()=>{});});};
}
function bindLipSync(){
  $('#lipRefresh').onclick=()=>renderLipSync(true);
  $('#lipVideoSource').onchange=e=>{lipDraft().video=e.target.value;lipSetVideo();};
  $('#lipAudioSource').onchange=e=>{lipDraft().audio=e.target.value;lipSetAudio();};
  $('#lipUploadVideo').onclick=()=>$('#lipVideoFile').click();$('#lipUploadAudio').onclick=()=>$('#lipAudioFile').click();
  $('#lipVideoFile').onchange=e=>{lipUpload(e.target.files[0],'video');e.target.value='';};$('#lipAudioFile').onchange=e=>{lipUpload(e.target.files[0],'audio');e.target.value='';};
  $('#lipPlayer').onplay=lipStartAudio;$('#lipPlayer').onvolumechange=()=>{if(!$('#lipPlayer').muted)$('#lipPlayer').muted=true;};$('#lipPlayer').onpause=()=>{$('#lipAudio').pause();clearTimeout(lipSyncTimer);};
  $('#lipPlayer').onseeking=()=>{$('#lipAudio').pause();clearTimeout(lipSyncTimer);};$('#lipPlayer').onseeked=()=>{lipClock();lipStartAudio();};$('#lipPlayer').ontimeupdate=lipClock;$('#lipPlayer').onloadedmetadata=lipClock;
  $('#lipAudio').onloadedmetadata=()=>lipSyncAudio(true);
  $('#lipPlayer').onerror=()=>{$('#lipStatus').textContent='视频无法预览，请检查素材格式或刷新后重新选择';};
  $('#lipPrevious').onclick=()=>lipStep(-1);$('#lipNext').onclick=()=>lipStep(1);$('#lipPlay').onclick=()=>{const v=$('#lipPlayer');if(!v.src)return;if(v.paused)v.play().catch(e=>toast(e.message));else lipPause();};
  $('#lipSpeed').onchange=e=>{$('#lipPlayer').playbackRate=Number(e.target.value);lipStartAudio();};$('#lipSeek').oninput=e=>{lipPause();$('#lipPlayer').currentTime=Number(e.target.value);lipClock();};
  $('#lipOffset').oninput=e=>lipOffset(e.target.value);$('#lipOffsetRange').oninput=e=>lipOffset(e.target.value);$('#lipReset').onclick=()=>lipOffset(0);
  for(const b of $$('[data-lip-nudge]'))b.onclick=()=>lipOffset(lipDraft().offset_ms+Number(b.dataset.lipNudge)*1000/lipFps);
  $('#lipAddMark').onclick=()=>{const d=lipDraft(),note=$('#lipNote').value.trim();if(!d?.video||!note)return;lipPause();d.markers.push({time:$('#lipPlayer').currentTime,note});d.markers.sort((a,b)=>a.time-b.time);$('#lipNote').value='';renderLipMarkers();};
  $('#lipSaveReview').onclick=async()=>{const d=lipDraft(),pid=project?.id;if(!d?.video)return;try{await api(`/api/projects/${pid}/lip-sync/review`,{method:'POST',body:JSON.stringify({video:d.video,offset_ms:d.offset_ms,markers:d.markers,region:d.region})});if(project?.id!==pid)return;project.lipsync_reviews??={};project.lipsync_reviews[d.video]={offset_ms:d.offset_ms,markers:d.markers.map(m=>({...m})),region:d.region};toast('校对记录已保存到工程');}catch(e){toast(e.message);}};
  $('#lipExport').onclick=()=>lipRun('audio_sync');$('#lipGenerate').onclick=()=>lipRun('musetalk');
  $('#lipSelectRegion').onclick=lipRegionPicker;$('#lipClearRegion').onclick=()=>{if(lipDraft())lipDraft().region=null;lipRegionLabel();$('#lipRegionCanvas').hidden=true;$('#lipRegionHelp').hidden=true;};
}

function lipRegionLabel(){const r=lipDraft()?.region;$('#lipRegionNote').textContent=r?`已圈选人物区域（宽 ${Math.round(r[2]*100)}% / 高 ${Math.round(r[3]*100)}%）`:'自动检测；多人画面请圈选说话人物。';}
function lipRegionPicker(){
  const v=$('#lipPlayer'),c=$('#lipRegionCanvas');if(!v.videoWidth||v.readyState<2){toast('请等视频画面加载后再圈选');return;}
  lipPause();c.width=v.videoWidth;c.height=v.videoHeight;c.hidden=false;$('#lipRegionHelp').hidden=false;
  const ctx=c.getContext('2d');let start=null;
  function paint(region){ctx.drawImage(v,0,0,c.width,c.height);if(region){ctx.strokeStyle='#ffc76b';ctx.lineWidth=Math.max(2,c.width/250);ctx.strokeRect(region[0]*c.width,region[1]*c.height,region[2]*c.width,region[3]*c.height);}}
  function position(e){const b=c.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-b.left)/b.width)),Math.max(0,Math.min(1,(e.clientY-b.top)/b.height))];}
  function rect(end){return [Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.abs(end[0]-start[0]),Math.abs(end[1]-start[1])];}
  paint(lipDraft().region);
  c.onpointerdown=e=>{start=position(e);c.setPointerCapture(e.pointerId);};
  c.onpointermove=e=>{if(start)paint(rect(position(e)));};
  c.onpointerup=e=>{if(!start)return;const r=rect(position(e));start=null;if(r[2]<.03||r[3]<.03){paint(lipDraft().region);toast('圈选区域太小，请包含完整脸部和下巴');return;}lipDraft().region=r;paint(r);lipRegionLabel();};
  c.onpointercancel=()=>{start=null;paint(lipDraft().region);};
}
