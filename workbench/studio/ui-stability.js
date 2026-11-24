// Polling must not replace unchanged DOM, reset media, or steal the scroll position.
function setStableText(node,value){
  if(!node)return;const text=String(value??'');
  if(node.textContent!==text)node.textContent=text;
}
function setStableHTML(node,html){
  if(node._renderedHTML===html)return false;
  node.innerHTML=html;node._renderedHTML=html;return true;
}
function setStableProgress(node,percent){
  const width=Math.max(0,Math.min(100,Number(percent)||0))+'%';
  if(node.style.width!==width)node.style.width=width;
}
function renderKeyedHTML(container,rows){
  delete container._renderedHTML;
  const existing=new Map([...container.children].filter(n=>n.dataset.renderKey).map(n=>[n.dataset.renderKey,n]));
  const wanted=new Set(rows.map(row=>row.key));
  for(const child of [...container.children])if(!wanted.has(child.dataset.renderKey))child.remove();
  let cursor=container.firstElementChild;
  for(const row of rows){
    let node=existing.get(row.key);
    if(!node||node._renderedHTML!==row.html){
      const template=document.createElement('template');template.innerHTML=row.html;
      const replacement=template.content.firstElementChild;
      replacement.dataset.renderKey=row.key;replacement._renderedHTML=row.html;
      if(node){if(node===cursor)cursor=replacement;node.replaceWith(replacement)}node=replacement;
    }
    if(node!==cursor)container.insertBefore(node,cursor);
    cursor=node.nextElementSibling;
  }
}
function syncShotStatus(){
  if(typeof syncTailRepair==='function')syncTailRepair();
  if(typeof syncShotAudio==='function')syncShotAudio();
  for(const card of $$('#shotsGrid [data-shot-id]')){
    const shot=project.shots.find(s=>s.id===card.dataset.shotId);if(!shot)continue;
    setStableText(card.querySelector('.shot-duration'),`${shot.duration??10} 秒 · ${({planned:'待生成视频',frames_ready:'待生成视频',video_ready:'视频已就绪',reviewed:'已质检'})[shot.status]||shot.status}`);
  }
}
