let textConfig={provider:'local',model:''};
function textModelLabel(){return textConfig.provider==='local'?'本地 Qwen':`${textConfig.provider==='openai'?'OpenAI':textConfig.provider==='deepseek'?'DeepSeek':'兼容API'} · ${textConfig.model}`}
function textPrivacy(c){
  if(c.provider==='local')return '本地模式：需求、剧本、素材由本机模型处理。';
  return `云端文字模式：提交的需求、剧本、元素描述、提示词和聊天内容将发送至 ${c.base_url}（${c.model||'模型待设置'}）。参考图片在本机分析，其文字描述可能随任务发送；图片与视频文件仍在本机生成。API调用按服务商规则计费。`;
}
async function loadTextModel(){
  try{textConfig=await api('/api/text-model');
    const footer=$('.rail-footer');
    setStableText(footer.querySelector('span'),textConfig.provider==='local'?'本地模式':'云端文字模式');
    setStableText(footer.querySelector('.privacy'),textConfig.provider==='local'?'素材不离开电脑':'任务文字发送至所选API');footer.title=textPrivacy(textConfig);
    setStableText($('#textDataNotice'),textPrivacy(textConfig));
    if(typeof refreshH3TranslationLabels==='function')refreshH3TranslationLabels();
    if(typeof refreshCreativeModel==='function')refreshCreativeModel();
    setStableText($('#openChat'),'通用问答');
    setStableText($('#chatDialog h2'),textModelLabel()+' 对话');
    setStableText($('#chatDialog .eyebrow'),textConfig.provider==='local'?'本地文字模型 · 未接入搜索':'云端文字模型 · 未接入搜索');
    setStableText($('#chatDialog > .chat-note:last-child'),textPrivacy(textConfig)+' 未接入搜索，不能实时查阅网页。');
  }catch(e){if(!$('#textDataNotice').textContent)setStableText($('#textDataNotice'),'无法读取文字模型模式；请检查工作台服务后再提交任务。')}
}
function bindTextModelUI(){
  const dialog=document.createElement('dialog');dialog.id='textModelDialog';dialog.className='settings-dialog';
  dialog.innerHTML=`<form method="dialog"><div class="dialog-head"><h2>文字模型设置</h2><button value="cancel" aria-label="关闭">×</button></div>
  <label>服务商<select id="textProvider"><option value="local">本地 Qwen（Ollama）</option><option value="deepseek">DeepSeek 官方 API</option><option value="openai">OpenAI Responses API</option><option value="compatible">OpenAI兼容 Chat Completions API</option></select></label>
  <div id="localTextFields"><label>本地文字任务上下文<select id="localTextContext"><option value="16384">16K · 16384 tokens</option><option value="32768">32K · 32768 tokens（推荐）</option><option value="65536">64K · 65536 tokens</option></select></label><p class="muted">输入与输出共用上下文。越长越占内存，且需模型支持；工作流输出上限为8192 tokens。参考图理解与普通对话保持各自的上下文设置。</p></div>
  <div id="cloudTextFields"><label>API基础地址<input id="textBase" type="url" placeholder="https://服务商域名/v1"></label>
  <label>模型ID<input id="textModel" list="textModelSuggestions" placeholder="填写账户可用的模型ID"></label><datalist id="textModelSuggestions"></datalist><p id="deepseekHelp" class="muted" hidden>DeepSeek 默认使用 deepseek-flash，关闭深度思考；可改为 deepseek-v4-pro。使用 JSON 模式并在本机校验结果。<a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer">获取 API Key</a></p>
  <label>API Key<input id="textKey" type="password" autocomplete="new-password" placeholder="留空保留已保存密钥"></label><p id="textKeyState" class="muted"></p>
  <label><input id="textClearKey" type="checkbox">清除已保存密钥</label>
  <div class="size-row"><label>请求超时（秒）<input id="textTimeout" type="number" min="10" max="600"></label><label>输出上限（tokens）<input id="textTokens" type="number" min="256" max="64000"></label></div>
  <label><input id="textStructured" type="checkbox">兼容接口支持严格JSON Schema（不支持时取消，改用JSON模式）</label></div>
  <p id="textModeHelp" class="settings-warning"></p><p class="muted">密钥只保存在本机后端，不返回网页、不写入项目。也可使用后端环境变量 DEEPSEEK_API_KEY、OPENAI_API_KEY 或 MIRRORFLOW_API_KEY。更换服务商或地址会清除已保存密钥。</p>
  <p id="textSaveStatus" role="status"></p><div class="dialog-actions"><button value="cancel">取消</button><button type="button" class="primary" id="saveTextModel">保存文字模型</button><button type="button" id="testTextModel">测试已保存连接</button></div></form>`;
  document.body.append(dialog);
  let previousProvider;
  const update=()=>{
    const provider=$('#textProvider').value,deepseek=provider==='deepseek';
    $('#localTextFields').hidden=provider!=='local';$('#cloudTextFields').hidden=provider==='local';
    $('#textBase').disabled=['openai','deepseek'].includes(provider);
    if(provider==='openai')$('#textBase').value='https://api.openai.com/v1';
    if(deepseek){$('#textBase').value='https://api.deepseek.com';if(previousProvider!==provider)$('#textModel').value='deepseek-flash';$('#textStructured').checked=false;}
    $('#textStructured').disabled=deepseek;$('#deepseekHelp').hidden=!deepseek;
    $('#textModelSuggestions').innerHTML=deepseek?'<option value="deepseek-flash"></option><option value="deepseek-v4-pro"></option>':'';
    if(previousProvider&&previousProvider!==provider){$('#textKey').value='';$('#textKeyState').textContent=provider===textConfig.provider&&textConfig.key_configured?'后端已配置密钥（不会显示）':'请填写此服务商的 API Key';}
    previousProvider=provider;
    $('#textModeHelp').textContent=textPrivacy({provider,base_url:$('#textBase').value,model:$('#textModel').value});
  };
  $('#openTextModel').onclick=async()=>{await loadTextModel();$('#localTextContext').value=String(textConfig.local_num_ctx||32768);$('#textProvider').value=textConfig.provider;previousProvider=textConfig.provider;$('#textBase').value=textConfig.base_url||'';$('#textModel').value=textConfig.model||'';$('#textKey').value='';$('#textClearKey').checked=false;$('#textTimeout').value=textConfig.timeout||180;$('#textTokens').value=textConfig.max_tokens||12000;$('#textStructured').checked=textConfig.structured!==false;$('#textKeyState').textContent=textConfig.key_configured?'后端已配置密钥（不会显示）':'后端尚未配置密钥';$('#textSaveStatus').textContent='';update();dialog.showModal()};
  ['textProvider','textBase','textModel'].forEach(id=>$('#'+id).onchange=update);
  $('#saveTextModel').onclick=async()=>{try{
    textConfig=await api('/api/text-model',{method:'POST',body:JSON.stringify({provider:$('#textProvider').value,base_url:$('#textBase').value,model:$('#textModel').value,api_key:$('#textKey').value,clear_key:$('#textClearKey').checked,timeout:Number($('#textTimeout').value),max_tokens:Number($('#textTokens').value),structured:$('#textStructured').checked,local_num_ctx:Number($('#localTextContext').value)})});
    $('#textKey').value='';$('#textClearKey').checked=false;await loadTextModel();$('#textSaveStatus').textContent='已保存。'+(textConfig.provider!=='local'&&!textConfig.key_configured?'请配置密钥后使用。':'');refreshStatus();
  }catch(e){$('#textSaveStatus').textContent=e.message}};
  $('#testTextModel').onclick=async()=>{const b=$('#testTextModel');b.disabled=true;$('#textSaveStatus').textContent='正在测试已保存的配置（只发送固定测试文字）…';try{const r=await api('/api/text-model/test',{method:'POST',body:'{}'});$('#textSaveStatus').textContent=r.message}catch(e){$('#textSaveStatus').textContent=e.message}finally{b.disabled=false}};
  dialog.addEventListener('close',()=>{$('#textKey').value=''});
  loadTextModel();
  if(new URLSearchParams(location.search).get('modelSettings')==='text')$('#openTextModel').click();
}
