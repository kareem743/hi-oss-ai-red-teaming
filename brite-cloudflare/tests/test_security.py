import asyncio,httpx,pytest
from tests.local_runtime import LocalD1,runtime

def test_security_and_rate_limit():
 async def go():
    d=LocalD1();d.conn.executescript("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1),('v@example.org','volunteer',1),('inactive@example.org','volunteer',1);UPDATE users SET active=0 WHERE email='inactive@example.org';")
    def client(email,mock=True):return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d,email,mock)),base_url='http://test')
    async with client('admin@example.org') as a,client('v@example.org') as v,client('inactive@example.org') as i,client(None) as anon,client('admin@example.org',False) as live:
      assert (await i.get('/api/workspace/scenarios')).status_code==403
      assert (await anon.get('/api/users',headers={'Cf-Access-Authenticated-User-Email':'admin@example.org'})).status_code==401
      assert (await v.get('/api/audit')).status_code==403
      assert (await v.put('/api/users',json={'email':'v@example.org','role':'admin'})).status_code==403
      assert (await live.post('/api/workspace/volunteers',json={'email':'x@example.org'})).status_code==403
      assert (await live.post('/api/workspace/volunteers',headers={'Origin':'http://localhost:5173','Sec-Fetch-Site':'cross-site'},json={'email':'x@example.org'})).status_code==403
      assert (await live.post('/api/workspace/volunteers',headers={'Origin':'http://localhost:5173'},json={'email':'x@example.org'})).status_code==200
      assert (await a.put('/api/users',json={'email':'admin@example.org','role':'volunteer'})).status_code==409
      s=(await a.post('/api/workspace/scenarios',json=dict(title='Test',description='Synthetic only',audience='public',provider='openai',model_name='gpt',model_label='GPT'))).json()
      detail=(await v.get('/api/workspace/scenarios/'+s['id'])).json()
      cv=(await v.post('/api/campaigns/'+s['campaign_id']+'/conversations',json={'scenario_id':s['id'],'model_id':detail['model_options'][0]['id']})).json()['id']
      d.conn.execute("INSERT INTO model_daily_usage VALUES('v@example.org',date('now'),50)");d.conn.commit()
      resp=await v.post('/api/conversations/'+cv+'/turns',json={'prompt':'Fictional','synthetic_only':True})
      assert resp.status_code==429
      assert d.conn.execute('SELECT COUNT(*) FROM turns').fetchone()[0]==0
      assert (await v.get('/api/campaigns/'+s['campaign_id']+'/export')).status_code==403
      assert (await a.get('/api/me')).headers['cache-control']=='no-store'
 asyncio.run(go())
