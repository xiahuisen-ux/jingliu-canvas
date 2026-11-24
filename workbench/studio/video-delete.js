async function deleteShotVideo(id){
  const shot=project?.shots.find(s=>s.id===id);if(!shot?.video)return;
  if(!confirm(`删除第 ${shot.shot} 段“${shot.title}”的视频？\n文字任务、元素和图片保留。视频从当前结果中移除，原文件保留，可在本卡片恢复。已有合片将标记失效，需要重新合片。`))return;
  const pid=project.id;
  try{const fresh=await api(`/api/projects/${encodeURIComponent(pid)}/videos/${encodeURIComponent(id)}`,{method:'DELETE'});if(project?.id===pid){project=fresh;renderVideos();renderShots();renderInspector();if($('#productionProgress'))$('#productionProgress').hidden=true;}toast('视频已移入回收记录，可恢复；原文件保留')}catch(e){toast(e.message)}
}
async function deleteVideoVersion(id,versionId){
  const shot=project?.shots.find(s=>s.id===id),version=shot?.video_versions?.find(v=>v.id===versionId);
  if(!version||version.current)return;
  if(!confirm(`删除第 ${shot.shot} 段“${shot.title}”的历史版本 ${version.number}？\n原文件保留，可在本卡片恢复。如果此版本已选合成，将取消本段合成选择；其他版本和已有成片保留。`))return;
  const pid=project.id;
  try{const fresh=await api(`/api/projects/${encodeURIComponent(pid)}/videos/${encodeURIComponent(id)}/versions/${encodeURIComponent(versionId)}`,{method:'DELETE'});if(project?.id===pid){project=fresh;renderVideos();renderInspector();}toast('历史版本已删除，可在本段卡片恢复；原文件保留')}catch(e){toast(e.message)}
}
async function restoreShotVideo(id,recordId){
  const pid=project.id;
  try{const fresh=await api(`/api/projects/${encodeURIComponent(pid)}/videos/${encodeURIComponent(id)}/restore`,{method:'POST',body:JSON.stringify({record_id:recordId})});if(project?.id===pid){project=fresh;renderVideos();renderShots();renderInspector();}toast('视频已恢复，需要时可重新合片')}catch(e){toast(e.message)}
}
function deletedVideoControls(s){return (s.deleted_videos||[]).map(r=>`<button class="ghost" data-restore-shot-video="${esc(s.id)}" data-record-id="${esc(r.id)}" ${s.video&&r.scope!=='history'?'disabled':''}>${r.scope==='history'?'恢复历史版本 '+esc(r.version_number):'恢复已删视频'} · ${esc(r.deleted_at.replace('T',' '))}</button>`).join('');}
function bindVideoDeleteButtons(){
  bindVideoEnhancements();
  $$('[data-delete-video-version]').forEach(b=>b.onclick=()=>deleteVideoVersion(b.dataset.versionShot,b.dataset.deleteVideoVersion));
  $$('[data-delete-shot-video]').forEach(b=>b.onclick=()=>deleteShotVideo(b.dataset.deleteShotVideo));
  $$('[data-restore-shot-video]').forEach(b=>b.onclick=()=>restoreShotVideo(b.dataset.restoreShotVideo,b.dataset.recordId));
}
