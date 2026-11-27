import asyncio,httpx
from types import SimpleNamespace
from tests.local_runtime import LocalD1,runtime
from src import vault,providers,demo
from src.app import price_micros

def test_price_math():
    assert price_micros(1000000,1000000,100,200)==3000000
    assert price_micros(1,1,1,1)==1

def test_registry_and_demo(monkeypatch):
 async def seal(env,p,key):return 'encrypted-test-only'
 async def unseal(env,p,cipher):
    assert cipher=='encrypted-test-only';return 'fake-provider-key'
 async def catalog(env,p):return [{'id':'gpt-test','name':'GPT Test'}]
 async def paid(model,history,env):
    assert env.OPENAI_API_KEY=='fake-provider-key'
    model['_usage'].update(input_tokens=100,output_tokens=20)
    yield 'Provider test response.'
 monkeypatch.setattr(vault,'seal',seal);monkeypatch.setattr(vault,'unseal',unseal);monkeypatch.setattr(providers,'catalog',catalog);monkeypatch.setattr(providers,'chunks',paid)
 async def go():
    d=LocalD1();d.conn.executescript("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1),('v@example.org','volunteer',1);")
    def client(email):return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d,email,False)),base_url='http://test',headers={'Origin':'http://localhost:5173'})
    async with client('admin@example.org') as a,client('v@example.org') as v:
      assert (await v.get('/api/workspace/settings')).status_code==403
      assert (await v.put('/api/workspace/settings/providers/openai',json={'api_key':'fake-provider-key','enabled':True,'monthly_requests':2,'budget_cents':2500})).status_code==403
      r=await a.put('/api/workspace/settings/providers/openai',json={'api_key':'fake-provider-key','enabled':True,'monthly_requests':2,'budget_cents':2500});assert r.status_code==200,r.text
      assert 'fake-provider-key' not in str(d.conn.execute('SELECT * FROM api_providers').fetchall())
      r=await a.get('/api/workspace/settings');assert 'fake-provider-key' not in r.text and 'encrypted-test-only' not in r.text
      assert (await a.get('/api/workspace/settings/discover/openai')).json()['models'][0]['id']=='gpt-test'
      model={'provider':'openai','model_name':'gpt-test','label':'GPT Test','input_cents':100,'output_cents':200,'enabled':True}
      assert (await a.put('/api/workspace/settings/models',json=model)).status_code==200
      cat=(await a.get('/api/workspace/model-catalog')).json();assert next(x for x in cat if x['provider']=='openai')['models'][0]['id']=='gpt-test'
      async def create(provider,name):
        r=await a.post('/api/workspace/scenarios',json=dict(title='Registry',description='Synthetic only',audience='public',provider=provider,model_name=name,model_label='Test',no_limit=True));assert r.status_code==201,r.text
        s=r.json();detail=(await v.get('/api/workspace/scenarios/'+s['id'])).json()
        r=await v.post('/api/campaigns/'+s['campaign_id']+'/conversations',json={'scenario_id':s['id'],'model_id':detail['model_options'][0]['id']});assert r.status_code==201,r.text;return r.json()['id']
      async def send(cid):return await v.post('/api/conversations/'+cid+'/turns',json={'prompt':'Fictional','synthetic_only':True})
      c=await create('demo',demo.DEMO_ID);r=await send(c);assert r.status_code==200 and 'Synthetic demo response' in r.text
      assert (await a.get('/api/workspace/settings')).json()['cost']['total_micros']==0
      c=await create('openai','gpt-test');r=await send(c);assert r.status_code==200 and 'Provider test response' in r.text
      stats=(await a.get('/api/workspace/settings')).json();assert stats['cost']['total_micros']==140 and stats['cost']['reported_micros']==140
      assert stats['models'][0]['scenarios']==1
      assert (await a.put('/api/workspace/settings/budget',json={'budget_cents':1})).status_code==200
      r=await send(c);assert r.status_code==200
      assert (await send(c)).status_code==429
      assert (await a.put('/api/workspace/settings/models',json=dict(model,enabled=False))).status_code==200
      assert (await send(c)).status_code==503
      assert not next(x for x in (await a.get('/api/workspace/model-catalog')).json() if x['provider']=='openai')['models']
      assert (await a.put('/api/workspace/settings/providers/openai',json={'enabled':False,'monthly_requests':2,'budget_cents':2500,'remove_key':True})).status_code==200
      assert not next(x for x in (await a.get('/api/workspace/settings')).json()['providers'] if x['provider']=='openai')['configured']
 asyncio.run(go())
