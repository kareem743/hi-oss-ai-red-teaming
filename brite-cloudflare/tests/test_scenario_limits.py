import asyncio,httpx,pytest
from tests.local_runtime import LocalD1,runtime

def test_scenario_limits_enforced_before_billing():
 async def go():
    d=LocalD1()
    d.conn.executescript("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1),('v@example.org','volunteer',1);")
    def client(email):return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d,email)),base_url='http://test')
    async with client('admin@example.org') as a,client('v@example.org') as v:
      base=dict(title='Limits test',description='Synthetic only',audience='public',provider='openai',model_name='gpt-test',model_label='GPT')
      for field,value in [('max_turns',0),('max_turns',26),('max_turns','3'),('max_context_chars',999),('max_context_chars',80001)]:
        assert (await a.post('/api/workspace/scenarios',json=dict(base,**{field:value}))).status_code==422
      async def create(**kw):
        r=await a.post('/api/workspace/scenarios',json=dict(base,**kw));assert r.status_code==201,r.text
        s=r.json();detail=(await v.get('/api/workspace/scenarios/'+s['id'])).json()
        r=await v.post('/api/campaigns/'+s['campaign_id']+'/conversations',json={'scenario_id':s['id'],'model_id':detail['model_options'][0]['id']});assert r.status_code==201,r.text
        return detail,r.json()['id']
      default,_=await create(max_turns=None,max_context_chars=None)
      assert default['max_turns']==25 and default['max_context_chars']==80000
      detail,c=await create(max_turns=1,max_context_chars=2000)
      assert detail['max_turns']==1 and detail['max_context_chars']==2000
      async def send(c,p):return await v.post('/api/conversations/'+c+'/turns',json={'prompt':p,'synthetic_only':True})
      r=await send(c,'Fictional question');assert r.status_code==200 and '"type": "done"' in r.text
      r=await send(c,'Another question');assert r.status_code==409 and 'turn limit' in r.text
      chat=(await v.get('/api/conversations/'+c)).json()
      assert chat['limits']['turns_remaining']==0 and len(chat['turns'])==1
      assert (await v.post('/api/workspace/conversations/'+c+'/flag',json={'turn_id':chat['turns'][0]['id'],'reason':'Test'})).status_code==200
      assert (await v.post('/api/conversations/'+c+'/submit')).status_code==200
      assert d.conn.execute('SELECT requests FROM model_daily_usage').fetchone()[0]==1
      _,c=await create(max_turns=5,max_context_chars=1000)
      assert (await send(c,'x'*1001)).status_code==409
      assert d.conn.execute('SELECT requests FROM model_daily_usage').fetchone()[0]==1
      r=await send(c,'x'*950);assert r.status_code==200 and '"type": "done"' in r.text
      chat=(await v.get('/api/conversations/'+c)).json()
      assert chat['limits']['context_chars_used']>1000 and chat['limits']['context_chars_remaining']==0
      assert (await send(c,'x')).status_code==409
      assert d.conn.execute('SELECT requests FROM model_daily_usage').fetchone()[0]==2
      assert len(chat['turns'])==1
      # A failed reserved attempt also counts toward the turn cap.
      _,c=await create(max_turns=1,max_context_chars=2000)
      d.conn.execute("INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES('failed-test',?,1,'failed','failed')",(c,));d.conn.commit()
      assert (await send(c,'retry')).status_code==409
 asyncio.run(go())
