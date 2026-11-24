"""Text-only provider adapter. Credentials never enter project data or public settings."""
import copy
import http.client
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import threading
from pathlib import Path
from portable_paths import DATA
from urllib.parse import urlparse

CONFIG = DATA / '.text-model.json'
LOCK = threading.RLock()
DEFAULT = dict(provider='local', base_url='https://api.openai.com/v1', model='',
               timeout=180, max_tokens=12000, structured=True, api_key='', local_num_ctx=32768)


def load():
    with LOCK:
        if not CONFIG.exists():
            return dict(DEFAULT)
        return {**DEFAULT, **json.loads(CONFIG.read_text())}


def key_for(c):
    env = {'openai':'OPENAI_API_KEY','deepseek':'DEEPSEEK_API_KEY'}.get(c['provider'],'MIRRORFLOW_API_KEY')
    return c.get('api_key') or os.environ.get(env, '')


def public(c=None):
    c = c or load()
    return {**{k:v for k,v in c.items() if k!='api_key'},
            'key_configured':bool(key_for(c)) if c['provider']!='local' else False}


def validate(c):
    if c['provider'] not in ('local','openai','deepseek','compatible'):
        raise ValueError('文字模型服务商不支持')
    c['base_url'] = str(c['base_url']).strip().rstrip('/')
    if c['provider']=='openai':
        c['base_url']='https://api.openai.com/v1'
    if c['provider']=='deepseek':
        c['base_url']='https://api.deepseek.com'
        c['structured']=False
        if not str(c.get('model','')).strip():c['model']='deepseek-flash'
    u=urlparse(c['base_url'])
    if (u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1'))) or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('API地址必须为HTTPS基础地址；本机地址可使用HTTP，不得包含密码或查询参数')
    c['model']=str(c['model']).strip()
    if c['provider']!='local' and not c['model']:
        raise ValueError('请填写服务商提供的模型ID')
    if type(c['timeout']) is not int or not 10<=c['timeout']<=600:
        raise ValueError('超时范围为10–600秒')
    if type(c['max_tokens']) is not int or not 256<=c['max_tokens']<=64000:
        raise ValueError('输出上限范围为256–64000 tokens')
    if type(c['structured']) is not bool:raise ValueError('结构化输出开关不正确')
    if type(c.get('local_num_ctx',32768)) is not int or c.get('local_num_ctx',32768) not in (16384,32768,65536):
        raise ValueError('本地上下文请选择16K、32K或64K')
    if not isinstance(c.get('api_key',''),str) or '\n' in c.get('api_key','') or '\r' in c.get('api_key',''):
        raise ValueError('API Key格式不正确')
    return c


def save(data):
    with LOCK:
        old=load()
        c={**old,**{k:v for k,v in data.items() if k in DEFAULT and k!='api_key'}}
        c=validate(c)
        # Never carry a stored credential to a different recipient.
        if (c['provider'],c['base_url'])!=(old['provider'],old['base_url']):c['api_key']=''
        if data.get('clear_key'):c['api_key']=''
        if data.get('api_key'):c['api_key']=data['api_key'].strip()
        validate(c)
        fd,tmp=tempfile.mkstemp(prefix='.text-model-',dir=CONFIG.parent)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,'w') as f:json.dump(c,f,ensure_ascii=False,indent=2)
            os.replace(tmp,CONFIG)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return public(c)


def strict_schema(schema):
    s=copy.deepcopy(schema)
    if s.get('type')=='object':
        s['additionalProperties']=False
        s['properties']={k:strict_schema(v) for k,v in s.get('properties',{}).items()}
        s['required']=list(s['properties'])
    if s.get('type')=='array':s['items']=strict_schema(s['items'])
    return s


def validate_result(value,schema,path='$'):
    """Validate the schema subset used by the workbench, including task counts."""
    kind=schema.get('type')
    valid={'object':isinstance(value,dict),'array':isinstance(value,list),
           'string':isinstance(value,str),'integer':type(value) is int,
           'number':type(value) in (int,float),'boolean':type(value) is bool}
    if kind in valid and not valid[kind]:raise ValueError(f'模型结果字段类型不正确：{path}')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(f'模型结果枚举不正确：{path}')
    if kind=='object':
        if any(k not in value for k in schema.get('required',[])):raise ValueError(f'模型结果缺少字段：{path}')
        for k,s in schema.get('properties',{}).items():
            if k in value:validate_result(value[k],s,path+'.'+k)
    if kind=='array':
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',float('inf')):raise ValueError(f'模型结果数量不正确：{path}')
        for i,v in enumerate(value):validate_result(v,schema['items'],f'{path}[{i}]')


def tls_context():
    """Use macOS's CA bundle when python.org's default store is empty."""
    context=ssl.create_default_context()
    # Respect explicitly configured trust stores; never disable verification.
    if (sys.platform=='darwin' and not context.cert_store_stats()['x509_ca']
            and not os.environ.get('SSL_CERT_FILE') and not os.environ.get('SSL_CERT_DIR')):
        bundle=Path('/etc/ssl/cert.pem')
        if bundle.is_file():context.load_verify_locations(cafile=str(bundle))
    return context


def api_error_label(status,raw):
    """Map only known error identifiers, never echo provider messages."""
    label={401:'密钥无效',403:'无访问权限',402:'API余额不足，请检查服务商账户余额',429:'配额或速率限制',400:'模型或结构化输出参数不支持'}.get(status,'服务商请求失败')
    try:
        error=json.loads(raw).get('error',{})
        code=error.get('code');kind=error.get('type')
    except (ValueError,AttributeError):return label
    if status==429:
        if code=='credit_balance_exhausted':return 'API预付余额已耗尽，请检查API账单并补充额度；重复重试无效'
        if code in ('organization_spend_limit_exceeded','project_spend_limit_exceeded','organization_usage_limit_exceeded','billing_hard_limit_reached'):
            return 'API消费或用量限额已达到，请检查组织/项目限额；重复重试无效'
        if code=='insufficient_quota' or kind=='insufficient_quota':return 'API额度不足或已达到消费限额，请检查API账单与限额；重复重试无效'
        if code in ('rate_limit_exceeded','slow_down') or kind=='rate_limit_error':return '请求速率受限，请稍后重试'
    return label


def request(c,messages,schema,server):
    c=validate(dict(c));key=key_for(c)
    if not key:raise ValueError('尚未配置API Key，请在文字模型设置中保存密钥，或设置后端环境变量')
    if c['provider']=='openai':
        body={'model':c['model'],'input':messages,'store':False,'max_output_tokens':c['max_tokens']}
        if schema:body['text']={'format':{'type':'json_schema','name':'workbench','strict':True,'schema':strict_schema(schema)}}
        route='/responses'
    else:
        body={'model':c['model'],'messages':messages,'stream':False,'max_tokens':c['max_tokens']}
        if c['provider']=='deepseek':body['thinking']={'type':'disabled'}
        if schema:
            body['response_format']=({'type':'json_schema','json_schema':{'name':'workbench','strict':True,'schema':strict_schema(schema)}} if c['structured'] else {'type':'json_object'})
            body['messages']=[{'role':'system','content':'Return valid JSON matching this schema: '+json.dumps(schema)},*messages]
        route='/chat/completions'
    u=urlparse(c['base_url']);cls=http.client.HTTPSConnection if u.scheme=='https' else http.client.HTTPConnection
    options={'context':tls_context()} if u.scheme=='https' else {}
    conn=cls(u.hostname,u.port,timeout=c['timeout'],**options)
    expired=threading.Event()
    def expire():
        expired.set()
        try:
            if conn.sock:conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        conn.close()
    timer=threading.Timer(c['timeout'],expire);timer.daemon=True;timer.start()
    try:
        with server.CONNECTION_LOCK:server.ACTIVE_CONNECTIONS.add(conn)
        server.check_cancel()
        conn.request('POST',u.path.rstrip('/')+route,json.dumps(body).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+key})
        response=conn.getresponse()
        if response.status!=200:
            # Classify whitelisted codes only; never expose raw error bodies.
            label=api_error_label(response.status,response.read(65536))
            raise ValueError(f'文字API：{label}（HTTP {response.status}），请检查配置后重试')
        raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('文字API响应过大')
        result=json.loads(raw)
        server.check_cancel()
        if expired.is_set():raise TimeoutError()
        if c['provider']=='openai':
            if result.get('status')!='completed':raise ValueError('文字API输出未完成，请提高输出上限或缩短输入后重试')
            parts=[x for item in result.get('output',[]) for x in item.get('content',[])]
            if any(x.get('type')=='refusal' for x in parts):raise ValueError('模型未能处理此请求')
            text=''.join(x.get('text','') for x in parts if x.get('type')=='output_text')
        else:
            choice=result['choices'][0]
            if choice.get('finish_reason')!='stop':raise ValueError('文字API输出未完成，请检查输出上限或请求内容')
            text=choice['message'].get('content','')
        if not isinstance(text,str) or not text.strip():raise ValueError('文字API未返回有效文本')
        if not schema:return text
        text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
        value=json.loads(text);validate_result(value,schema);return value
    except (socket.timeout,TimeoutError):raise ValueError('文字API请求超时；已保存内容不变，可重试') from None
    except (KeyError,IndexError,json.JSONDecodeError):
        if expired.is_set():raise ValueError('文字API请求超时；已保存内容不变，可重试') from None
        raise ValueError('文字API返回格式不符合要求；请检查接口与模型') from None
    except ssl.SSLCertVerificationError:
        raise ValueError('文字API证书校验失败；请检查本机CA证书或代理证书，勿关闭HTTPS校验') from None
    except (OSError,http.client.HTTPException):
        if expired.is_set():raise ValueError('文字API请求超时；已保存内容不变，可重试') from None
        raise ValueError('文字API连接失败；请检查网络和API地址') from None
    finally:
        timer.cancel()
        with server.CONNECTION_LOCK:server.ACTIVE_CONNECTIONS.discard(conn)
        conn.close()
