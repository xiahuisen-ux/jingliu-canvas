// Read-only progress tracking. No model calls or backend restarts required.
const productionProgress = new Map();
function progressEntities(p){return ['characters','key_objects','locations'].flatMap(k=>(p.analysis?.[k]||[]).map(e=>({...e,kind:k})));}
function progressVersions(a){return a?.versions||(a?.images?.length?[{images:a.images,status:'done'}]:[]);}
function progressTime(seconds){if(!Number.isFinite(seconds))return '正在估算';const m=Math.max(1,Math.ceil(seconds/60));return m<60?`约 ${m} 分钟`:`约 ${Math.floor(m/60)} 小时 ${m%60} 分钟`;}
function progressSnapshot(p){return Object.fromEntries((p.shots||[]).map(s=>[s.id,{start_frame:s.start_frame,end_frame:s.end_frame,video:s.video}]));}
function rememberProgress(job,p,payload={}){
  const state={baseline:progressSnapshot(p),payload,phases:{}};
  productionProgress.set(job.id,state);saveProgressState(job.id,state);
}
function saveProgressState(id,state){try{localStorage.setItem('production-progress-'+id,JSON.stringify(state));}catch{}}
function progressState(job){
  if(!productionProgress.has(job.id)){let saved;try{saved=JSON.parse(localStorage.getItem('production-progress-'+job.id));}catch{}productionProgress.set(job.id,saved||{payload:{},phases:{}});}
  return productionProgress.get(job.id);
}
function productionStats(job,p,stamp=Date.now()){
  const state=progressState(job),action=job.action,assetMode=['asset','all_assets'].includes(action);
  if(action==='benchmark_video'){
    const results=(p.shots||[]).flatMap(s=>s.video_comparisons||[]).find(c=>c.job_id===job.id)?.results||[];
    return {phase:'后端对照',unit:'项',total:2,done:results.length,remaining:2-results.length,groups:[`成功 ${results.filter(r=>r.status==='done').length}，失败 ${results.filter(r=>r.status==='error').length}`],elapsed:Math.max(0,(stamp-Date.parse(job.created_at))/1000),eta:null,percent:results.length*50};
  }
  if(!assetMode&&!['frames','all_frames','video','all_videos','render_sequence'].includes(action))return null;
  let total=0,done=0,groups=[],phase='',unit='',sampleDone=0,sampleStart=0;
  if(assetMode){
    let entities=progressEntities(p);
    const plan=job.asset_plan||state.payload.asset_plan;
    if(plan)entities=entities.filter(e=>(plan[e.id]||0)>0);
    if(action==='asset')entities=entities.filter(e=>state.payload.entity_id?e.id===state.payload.entity_id:progressVersions(p.assets?.[e.id]).some(v=>v.created_at>=job.created_at));
    const counts=entities.map(e=>{
      const versions=progressVersions(p.assets?.[e.id]),recent=versions.filter(v=>v.created_at>=job.created_at).at(-1);
      const target=plan?.[e.id]??(e.kind==='characters'?1:action==='asset'?(recent?.view_count??p.assets?.[e.id]?.reference_views??1):4);
      const requiredRevision=e.kind==='characters'?job.asset_prompt_revision:Math.min(job.asset_prompt_revision||0,5);
      const complete=!job.regenerate_assets&&versions.some(v=>!v.state_name&&v.status==='done'&&!['needs_revision','needs_review'].includes(v.layout_review?.status)&&!(e.kind==='characters'&&v.mode==='image'&&!v.generation_settings?.reference_conditioning)&&v.images?.length>=target&&((v.mode==='import'&&v.images.some(path=>p.assets?.[e.id]?.selected_images?.includes(path)))||!requiredRevision||v.prompt_revision>=requiredRevision));
      const n=recent?Math.min(target,recent.images.length):(action==='all_assets'&&complete?target:0);
      if(recent){sampleDone+=recent.images.length;const t=Date.parse(recent.created_at);if(t&&(!sampleStart||t<sampleStart))sampleStart=t;}
      if(recent?.view_progress){
        const v=recent.view_progress;
        return {...e,n:Math.min(v.total,recent.status==='done'?v.total:v.completed),target:v.total,views:true};
      }
      return {...e,n,target};
    });
    total=counts.reduce((n,e)=>n+e.target,0);done=counts.reduce((n,e)=>n+e.n,0);unit=counts.some(e=>e.views)?'视图 / 张':'张';phase='元素参考图';
    groups=['characters','key_objects','locations'].map((k,i)=>{const rows=counts.filter(e=>e.kind===k);return rows.length?`${['人物','物品','场景'][i]} ${rows.filter(e=>e.n===e.target).length}/${rows.length} 项完成`:'';}).filter(Boolean);
  }else{
    let shots=p.shots||[];
    const selectedIds=job.shot_ids||state.payload.shot_ids;
    if(selectedIds)shots=shots.filter(s=>selectedIds.includes(s.id));
    if(!selectedIds&&['frames','video'].includes(action))shots=shots.filter(s=>state.payload.shot_id?s.id===state.payload.shot_id:(s.status==='generating_frames'||job.message?.includes(s.title)));
    // A recovered single-shot video has no target ID in the old job API.
    if(!shots.length&&['frames','video'].includes(action))return {pending:true,elapsed:Math.max(0,(stamp-Date.parse(job.created_at))/1000)};
    const sequence=action==='render_sequence';
    const videoPhase=['video','all_videos'].includes(action)||sequence;
    phase=videoPhase?'视频镜头':'首尾关键帧';unit=videoPhase?'段':'张';
    const keys=videoPhase?['video']:['start_frame','end_frame'];total=shots.length*keys.length;
    done=shots.reduce((n,s)=>n+keys.filter(k=>s[k]&&!(k==='video'&&s.video_stale)&&(selectedIds&&job.completed_shot_ids?job.completed_shot_ids.includes(s.id):(sequence&&!selectedIds||!state.baseline||s[k]!==state.baseline[s.id]?.[k]))).length,0);
    groups=[`镜头 ${shots.filter(s=>keys.every(k=>s[k]&&!(k==='video'&&s.video_stale)&&(selectedIds&&job.completed_shot_ids?job.completed_shot_ids.includes(s.id):(sequence&&!selectedIds||!state.baseline||s[k]!==state.baseline[s.id]?.[k])))).length}/${shots.length} 项完成`];
    if(!state.baseline&&!sequence)groups.push('重新连接：数量按当前项目已保存结果统计');
    if(sequence)groups.push('所选段落依次生成 · 完成后手动选版合成');
  }
  const remaining=Math.max(0,total-done),elapsed=Math.max(0,(stamp-Date.parse(job.created_at))/1000);
  let rate=null;
  if(assetMode&&sampleDone&&sampleStart)rate=(stamp-sampleStart)/1000/sampleDone;
  else{
    const track=state.phases[phase]||(state.phases[phase]={start:stamp,initial:done});
    if(done>track.initial)rate=(stamp-track.start)/1000/(done-track.initial);
  }
  saveProgressState(job.id,state);
  return {phase,unit,total,done,remaining,groups,elapsed,eta:rate&&remaining?rate*remaining:null,percent:total?Math.floor(done/total*100):0};
}
function renderProductionProgress(job,p){
  const stats=productionStats(job,p);let box=$('#productionProgress');
  if(!box){box=document.createElement('section');box.id='productionProgress';box.className='production-progress';$('#projectView').prepend(box);}
  if(!box.querySelector('[data-progress-heading]'))box.innerHTML='<div class="production-heading"><strong data-progress-heading></strong><span data-progress-status></span></div><div class="progress" data-progress-track><i></i></div><p data-progress-groups></p><p data-progress-message></p><p data-progress-eta></p><small>按已保存成果计数；预估随实际速度更新，模型加载和复杂镜头可能延长时间。完整流水线分阶段估时。</small>';
  box.dataset.projectId=p.id;box.hidden=!stats;if(!stats)return;
  const terminal=['done','error','cancelled'].includes(job.status),status=job.status==='done'?'已完成':job.status==='error'?'任务失败':job.status==='cancelled'?'已停止':job.status==='queued'?'排队中':'进行中';
  const heading=stats.pending?'正在读取当前镜头进度':`${stats.phase} · 已完成 ${stats.done} / ${stats.total} ${stats.unit} · 剩余 ${stats.remaining} ${stats.unit}`;
  const eta=terminal?status:job.status==='queued'?'等待模型任务，暂不估时':stats.pending?'正在估算':stats.remaining===0?'正在收尾／准备下一阶段':`本阶段预计剩余：${progressTime(stats.eta)}`;
  setStableText(box.querySelector('[data-progress-heading]'),heading);
  setStableText(box.querySelector('[data-progress-status]'),status);
  box.querySelector('[data-progress-track]').hidden=!!stats.pending;
  box.querySelector('[data-progress-groups]').hidden=!!stats.pending;
  setStableText(box.querySelector('[data-progress-groups]'),stats.groups?.join(' · ')||'');
  setStableText(box.querySelector('[data-progress-message]'),job.message||'正在准备模型');
  setStableText(box.querySelector('[data-progress-eta]'),`${eta} · 已用 ${progressTime(stats.elapsed).replace('约 ','')}`);
  if(!stats.pending){setStableProgress(box.querySelector('.progress i'),stats.percent);setStableText($('#jobPercent'),stats.percent+'%');setStableProgress($('#jobProgress'),stats.percent);}
}
