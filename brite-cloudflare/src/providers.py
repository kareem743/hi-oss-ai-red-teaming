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
        body={'model':model['model_name'],'messages':messages,'stream':True,'max_completion_tokens':model['max_tokens']}
    elif provider=='anthropic':
        url='https://api.anthropic.com/v1/messages'
        headers={'x-api-key':str(key),'anthropic-version':'2023-06-01'}
        body={'model':model['model_name'],'messages':messages,'stream':True,'max_tokens':model['max_tokens']}
        if system: body['system']=system
    else: raise RuntimeError('Unknown provider')
    headers['Content-Type']='application/json'
    done=False
    async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=15)) as client:
        async with client.stream('POST',url,headers=headers,json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data:'): continue
                raw=line[5:].strip()
                if raw=='[DONE]': done=True; break
                event=json.loads(raw)
                if event.get('error') or event.get('type')=='error': raise RuntimeError('Provider error')
                if provider=='openai':
                    choices=event.get('choices') or []
                    if not choices: continue
                    text=choices[0].get('delta',{}).get('content') or ''
                else:
                    if event.get('type')=='message_stop': done=True; break
                    text=event.get('delta',{}).get('text','') if event.get('type')=='content_block_delta' else ''
                if text: yield text
    if not done: raise RuntimeError('Provider stream ended prematurely')
