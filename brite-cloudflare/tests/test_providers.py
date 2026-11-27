import asyncio,json
from types import SimpleNamespace
import httpx,pytest
from src import providers
ENV=SimpleNamespace(OPENAI_API_KEY='fake-openai',ANTHROPIC_API_KEY='fake-anthropic')
MODEL=dict(provider='openai',model_name='gpt-test',system_prompt='Synthetic only',max_tokens=100)
HISTORY=[{'role':'user','content':'Fictional question'}]

def mock(monkeypatch,handler):
    client=httpx.AsyncClient
    monkeypatch.setattr(providers.httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(handler),**kw))

@pytest.mark.parametrize('provider,endpoint,events',[
 ('openai','https://api.openai.com/v1/chat/completions',['{"choices":[{"delta":{"content":"hello"}}]}','[DONE]']),
 ('anthropic','https://api.anthropic.com/v1/messages',['{"type":"content_block_delta","delta":{"text":"hello"}}','{"type":"message_stop"}'])
])
def test_stream_provider_contract(monkeypatch,provider,endpoint,events):
    def handler(req):
        assert str(req.url)==endpoint
        body=json.loads(req.content)
        assert body['stream'] is True and body['model']=='gpt-test'
        if provider=='openai':
            assert req.headers['authorization']=='Bearer fake-openai'
            assert body['messages'][0]['role']=='system'
            assert body['max_completion_tokens']==100
        else:
            assert req.headers['x-api-key']=='fake-anthropic'
            assert body['system']=='Synthetic only' and body['max_tokens']==100
        return httpx.Response(200,text=''.join('data: '+e+'\n\n' for e in events))
    mock(monkeypatch,handler)
    async def go():return ''.join([x async for x in providers.chunks(dict(MODEL,provider=provider),HISTORY,ENV)])
    assert asyncio.run(go())=='hello'
    assert len(HISTORY)==1

@pytest.mark.parametrize('status,body,kind',[(429,'busy',httpx.HTTPStatusError),(200,'data: {"error":"failed"}\n\n',RuntimeError),(200,'data: {"choices":[]}\n\n',RuntimeError),(200,'data: invalid\n\n',ValueError)])
def test_stream_failure(monkeypatch,status,body,kind):
    mock(monkeypatch,lambda req:httpx.Response(status,text=body))
    async def go():return [x async for x in providers.chunks(MODEL,HISTORY,ENV)]
    with pytest.raises(kind):asyncio.run(go())

@pytest.mark.parametrize('provider,items,expected',[
 ('openai',[{'id':'gpt-test'},{'id':'text-embedding-x'},{'id':'gpt-image-1'},{'id':'o3-mini'}],['gpt-test','o3-mini']),
 ('anthropic',[{'id':'claude-test','display_name':'Claude Test'},{'id':'other'}],['claude-test'])
])
def test_catalog_filters(monkeypatch,provider,items,expected):
    def handler(req):
        assert req.url.host==('api.openai.com' if provider=='openai' else 'api.anthropic.com')
        assert req.url.path=='/v1/models'
        return httpx.Response(200,json={'data':items})
    mock(monkeypatch,handler)
    assert [x['id'] for x in asyncio.run(providers.catalog(ENV,provider))]==expected

def test_no_key_no_provider_request(monkeypatch):
    mock(monkeypatch,lambda req:pytest.fail('Network must not be called'))
    env=SimpleNamespace()
    assert asyncio.run(providers.catalog(env,'openai'))==[]
    async def go():return [x async for x in providers.chunks(MODEL,HISTORY,env)]
    with pytest.raises(RuntimeError):asyncio.run(go())
