"""Provider boundary. HTTP requests contain synthetic data only in the pilot."""
import json
import httpx

async def chunks(model,history,env):
    provider=model['provider']; key=getattr(env,'OPENAI_API_KEY' if provider=='openai' else 'ANTHROPIC_API_KEY','')
    if not key: raise RuntimeError('Provider key not configured')
    messages=list(history)
    system=model['system_prompt']
    if provider=='openai':
        url='https://api.openai.com/v1/chat/completions'
        headers={'Authorization':f'Bearer {key}'}
        if system: messages.insert(0,{'role':'system','content':system})
        body={'model':model['model_name'],'messages':messages,'stream':True,'stream_options':{'include_usage':True},'max_completion_tokens':model['max_tokens']}
    elif provider=='anthropic':
        url='https://api.anthropic.com/v1/messages'
        headers={'x-api-key':str(key),'anthropic-version':'2023-06-01'}
        body={'model':model['model_name'],'messages':messages,'stream':True,'max_tokens':model['max_tokens']}
        if system: body['system']=system
    else: raise RuntimeError('Unknown provider')
    headers['Content-Type']='application/json'
    done=False
    async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=15),follow_redirects=False) as client:
        async with client.stream('POST',url,headers=headers,json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data:'): continue
                raw=line[5:].strip()
                if raw=='[DONE]': done=True; break
                event=json.loads(raw)
                if event.get('error') or event.get('type')=='error': raise RuntimeError('Provider error')
                usage=model.get('_usage')
                if usage is not None:
                    if provider=='openai' and isinstance(event.get('usage'),dict):
                        reported=event['usage'];usage['input_tokens']=reported.get('prompt_tokens');usage['output_tokens']=reported.get('completion_tokens')
                    elif provider=='anthropic':
                        reported=event.get('message',{}).get('usage',{}) if event.get('type')=='message_start' else event.get('usage',{})
                        if isinstance(reported,dict):
                            if type(reported.get('input_tokens'))==int:usage['input_tokens']=reported['input_tokens']+int(reported.get('cache_creation_input_tokens') or 0)+int(reported.get('cache_read_input_tokens') or 0)
                            if type(reported.get('output_tokens'))==int:usage['output_tokens']=reported['output_tokens']
                if provider=='openai':
                    choices=event.get('choices') or []
                    if not choices: continue
                    text=choices[0].get('delta',{}).get('content') or ''
                else:
                    if event.get('type')=='message_stop': done=True; break
                    text=event.get('delta',{}).get('text','') if event.get('type')=='content_block_delta' else ''
                if text: yield text
    if not done: raise RuntimeError('Provider stream ended prematurely')


def configured(env,provider):
    return bool(getattr(env,{'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY'}[provider],''))

async def catalog(env,provider):
    """Only call fixed provider URLs. Never return credentials or upstream error bodies."""
    if not configured(env,provider): return []
    if provider=='openai':
        url='https://api.openai.com/v1/models'
        headers={'Authorization':'Bearer '+str(env.OPENAI_API_KEY)}
    elif provider=='anthropic':
        url='https://api.anthropic.com/v1/models?limit=100'
        headers={'x-api-key':str(env.ANTHROPIC_API_KEY),'anthropic-version':'2023-06-01'}
    else: raise ValueError('Unsupported provider')
    # Native Workers fetch avoids relying on socket-based transports in Pyodide.
    try:
        from js import fetch, Object, AbortSignal
        from pyodide.ffi import to_js
    except ImportError:
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            r=await client.get(url,headers=headers)
            r.raise_for_status()
            payload=r.json()
    else:
        options=to_js({'headers':headers,'redirect':'error','signal':AbortSignal.timeout(15000)},dict_converter=Object.fromEntries)
        r=await fetch(url,options)
        if not r.ok: raise RuntimeError('Provider catalog unavailable')
        payload=json.loads(await r.text())
    models=[]
    for item in payload.get('data',[])[:500]:
        id=item.get('id')
        if not isinstance(id,str) or not id or len(id)>200: continue
        if provider=='openai':
            # The API returns non-chat models too; this is a candidate filter, not a capability guarantee.
            if not id.startswith(('gpt-','chatgpt-','o1','o3','o4')) or any(x in id for x in ('audio','realtime','transcribe','tts','image','embedding','moderation','search','codex')): continue
        elif not id.startswith('claude-'): continue
        name=item.get('display_name') or id
        models.append({'id':id,'name':str(name)[:200]})
    return sorted(models,key=lambda x:x['name'].lower())
