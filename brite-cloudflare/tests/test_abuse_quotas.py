import asyncio,httpx,time
from tests.local_runtime import LocalD1,runtime

def test_atomic_quota_safety_and_prompt():
 async def go():
    d=LocalD1();d.conn.executescript("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1),('v@example.org','volunteer',1);")
    def client(email):return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d,email)),base_url='http://test')
    async with client('admin@example.org') as a,client('v@example.org') as v:
      base=dict(title='Safety',description='Synthetic only',audience='public',provider='openai',model_name='gpt-test',model_label='GPT',no_limit=True,system_prompt='Synthetic test system message')
      s=(await a.post('/api/workspace/scenarios',json=base)).json()
      detail=(await v.get('/api/workspace/scenarios/'+s['id'])).json()
      assert 'system_prompt' not in detail['model_options'][0]
      assert (await a.get('/api/workspace/scenarios/'+s['id'])).json()['model_options'][0]['system_prompt']==base['system_prompt']
      async def start():
        r=await v.post('/api/campaigns/'+s['campaign_id']+'/conversations',json={'scenario_id':s['id'],'model_id':detail['model_options'][0]['id']});assert r.status_code==201,r.text;return r.json()['id']
      c=await start();c2=await start()
      async def send(cid):return await v.post('/api/conversations/'+cid+'/turns',json={'prompt':'Fictional question','synthetic_only':True})
      assert (await v.put('/api/workspace/safety',json={'enabled':False})).status_code==403
      assert (await a.put('/api/workspace/safety',json={'enabled':False})).status_code==200
      assert (await send(c)).status_code==429
      assert (await a.put('/api/workspace/safety',json={'enabled':True})).status_code==200
      assert (await send(c)).status_code==200
      chat=(await v.get('/api/conversations/'+c)).json()
      assert 'model_snapshot' not in chat
      assert chat['limits']['context_chars_used']>len(base['system_prompt'])
      month=time.strftime('%Y-%m',time.gmtime());minute=str(int(time.time())//60)
      assert d.conn.execute('SELECT COUNT(*) FROM model_usage').fetchone()[0]==1
      assert d.conn.execute('SELECT requests FROM model_monthly_usage').fetchone()[0]==1
      d.conn.execute("UPDATE abuse_windows SET requests=5 WHERE kind='user'");d.conn.commit()
      assert (await send(c)).status_code==429
      d.conn.execute("DELETE FROM abuse_windows");d.conn.commit()
      d.conn.execute("INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES('pending',?,2,'test','pending')",(c,));d.conn.commit()
      assert (await send(c2)).status_code==429
      d.conn.execute("UPDATE turns SET status='failed' WHERE id='pending'");d.conn.commit()
      d.conn.execute("UPDATE model_monthly_usage SET reserved_input_bytes=2000000");d.conn.commit()
      assert (await send(c2)).status_code==429
      d.conn.execute("UPDATE model_monthly_usage SET reserved_input_bytes=0,output_token_allowance=512000");d.conn.commit()
      assert (await send(c2)).status_code==429
      d.conn.execute("UPDATE model_monthly_usage SET output_token_allowance=0,requests=1000");d.conn.commit()
      assert (await send(c2)).status_code==429
      assert d.conn.execute('SELECT COUNT(*) FROM model_usage').fetchone()[0]==1
      assert d.conn.execute('SELECT requests FROM model_daily_usage').fetchone()[0]==1
 asyncio.run(go())
