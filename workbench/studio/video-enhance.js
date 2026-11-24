function enhanceControls(item,id,source){
  const versions=(item.enhanced_versions||[]).filter(v=>v.source_video===source);
  return `<section class="video-enhancements"><button class="ghost" data-enhance-video="${esc(id)}" data-scale="2">Real-ESRGAN 增强 2×</button><button class="ghost" data-enhance-video="${esc(id)}" data-scale="4">增强 4×</button><p class="muted">原视频保留。增强用于细节与清晰度，不修复变脸；逐帧增强可能出现闪烁，请预览确认。</p>${versions.map(v=>`<details><summary>增强版 ${v.width}×${v.height} · ${v.seconds} 秒处理</summary><video controls preload="none" style="width:100%" src="${media(v.video)}"></video><a class="ghost" href="${media(v.video)}" download>保存增强视频</a><button class="ghost" data-reveal-enhanced="${esc(v.video)}">打开文件夹</button></details>`).join('')}</section>`;
}
function bindVideoEnhancements(){
  $$('[data-enhance-video]').forEach(b=>b.onclick=()=>runAction('enhance_video',{shotId:b.dataset.enhanceVideo,scale:+b.dataset.scale}));
  $$('[data-reveal-enhanced]').forEach(b=>b.onclick=()=>revealFile(b.dataset.revealEnhanced));
}
