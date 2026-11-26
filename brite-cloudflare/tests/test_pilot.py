import asyncio
import httpx
from tests.local_runtime import LocalD1,runtime
from src.app import reap
from types import SimpleNamespace

def test_end_to_end():
 async def go():
    db=LocalD1();db.conn.execute("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1)");db.conn.commit()
    def client(email):return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(db,email)),base_url='http://test')
    async with client('admin@example.org') as a,client('volunteer@example.org') as v,client('reviewer@example.org') as r,client('outside@example.org') as o,client(None) as anon:
      async def call(cl,method,path,p=None,code=200):
        kw={'json':p} if p is not None else {};res=await cl.request(method,path,**kw);assert res.status_code==code,(path,res.status_code,res.text);return res
      assert (await call(anon,'GET','/api/me',code=401)).status_code==401
      await call(o,'GET','/api/me',code=403)
      for email,role in [('volunteer@example.org','volunteer'),('reviewer@example.org','reviewer'),('outside@example.org','volunteer')]:await call(a,'PUT','/api/users',{'email':email,'role':role})
      c=(await call(a,'POST','/api/campaigns',{'title':'Medication safety','description':'Synthetic test only'},201)).json()['id']
      await call(a,'PATCH',f'/api/campaigns/{c}',{'status':'active'},409)
      s=(await call(a,'POST',f'/api/campaigns/{c}/scenarios',{'title':'Overconfidence','instructions':'Use fictional patients'},201)).json()['id']
      t=(await call(a,'POST',f'/api/scenarios/{s}/tasks',{'title':'Record behavior','instructions':'Check response'},201)).json()['id']
      m=(await call(a,'POST',f'/api/campaigns/{c}/models',{'label':'Demo GPT','provider':'openai','model_name':'gpt-4.1-mini'},201)).json()['id']
      for email in ['volunteer@example.org','reviewer@example.org']:await call(a,'POST',f'/api/campaigns/{c}/members',{'email':email})
      await call(a,'PATCH',f'/api/campaigns/{c}',{'status':'active'})
      await call(o,'GET',f'/api/campaigns/{c}',code=404)
      await call(v,'POST','/api/campaigns',{'title':'Unauthorized','description':'x'},403)
      await call(v,'POST',f'/api/campaigns/{c}/conversations',{'scenario_id':s,'model_id':m},403)
      await call(v,'POST','/api/training/acknowledge',{'synthetic_only':True,'evidence_rule':True,'urgent_rule':True})
      cv=(await call(v,'POST',f'/api/campaigns/{c}/conversations',{'scenario_id':s,'model_id':m},201)).json()['id']
      await call(o,'GET',f'/api/conversations/{cv}',code=404)
      await call(v,'POST',f'/api/conversations/{cv}/turns',{'prompt':'Fictional patient question','synthetic_only':False},422)
      res=await call(v,'POST',f'/api/conversations/{cv}/turns',{'prompt':'Fictional patient question','synthetic_only':True});assert 'Synthetic demo response' in res.text and '"type": "done"' in res.text
      detail=(await call(v,'GET',f'/api/conversations/{cv}')).json();assert 'model_snapshot' not in detail and detail['turns'][0]['status']=='complete';turn=detail['turns'][0]['id']
      await call(v,'POST',f'/api/conversations/{cv}/submit',code=409)
      await call(v,'PUT',f'/api/conversations/{cv}/tasks/{t}')
      f=(await call(v,'POST',f'/api/conversations/{cv}/findings',{'turn_id':turn,'category':'overconfidence','severity':'urgent','explanation':'Demo evidence explanation','expected':'Expected safe and cautious answer'},201)).json()['id']
      assert len((await call(r,'GET',f'/api/campaigns/{c}/findings')).json())==1
      await call(v,'POST',f'/api/findings/{f}/review',{'verdict':'confirmed','feedback':'Unauthorized feedback'},403)
      await call(v,'POST',f'/api/conversations/{cv}/submit')
      await call(r,'POST',f'/api/findings/{f}/review',{'verdict':'confirmed','feedback':'Verified synthetic test'})
      await call(r,'POST',f'/api/findings/{f}/review',{'verdict':'confirmed','feedback':'Duplicate review test'},409)
      assert (await call(v,'GET',f'/api/conversations/{cv}')).json()['findings'][0]['verdict']=='confirmed'
      assert (await call(a,'GET',f'/api/campaigns/{c}/metrics')).json()['reviewed']==1
      data=(await call(a,'GET',f'/api/campaigns/{c}/export')).json();assert data['turns'][0]['prompt']=='Fictional patient question' and data['reviews'][0]['verdict']=='confirmed'
      await call(v,'GET',f'/api/campaigns/{c}/export',code=403)
      assert len((await call(a,'GET','/api/audit')).json())>5
      await call(v,'POST',f'/api/conversations/{cv}/turns',{'prompt':'after submit','synthetic_only':True},409)
      db.conn.execute("INSERT INTO turns(id,conversation_id,seq,prompt,status,created_at) VALUES('stale',?,2,'test','pending','2000-01-01 00:00:00')",(cv,));db.conn.commit()
      assert await reap(SimpleNamespace(DB=db))==1
      assert db.conn.execute("SELECT status FROM turns WHERE id='stale'").fetchone()[0]=='failed'
      await call(a,'DELETE',f'/api/campaigns/{c}/members/volunteer@example.org')
      await call(v,'GET',f'/api/conversations/{cv}',code=404)
 asyncio.run(go())
