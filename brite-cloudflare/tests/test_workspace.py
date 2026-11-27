import asyncio,httpx
from tests.local_runtime import LocalD1,runtime

def test_scenario_workspace():
    async def go():
        d=LocalD1()
        d.conn.execute("INSERT INTO users(email,role,active,trained) VALUES('admin@example.org','admin',1,1)")
        d.conn.commit()
        def client(email):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d,email)),base_url='http://test')
        async with client('admin@example.org') as a,client('one@example.org') as v,client('two@example.org') as w,client('unknown@example.org') as x:
            def data(title,audience,emails): return dict(title=title,description='Act as a fictional patient',audience=audience,emails=emails,provider='openai',model_name='gpt-4.1-mini',model_label='GPT')
            async def ok(c,method,path,**kwargs):
                r=await c.request(method,path,**kwargs)
                assert r.is_success,r.text
                return r.json()
            assert (await a.post('/api/workspace/scenarios',json=data('Unapproved','private',['unknown@example.org']))).status_code==409
            await ok(a,'POST','/api/workspace/volunteers',json={'email':'one@example.org'})
            assert (await v.get('/api/workspace/model-catalog')).status_code==403
            assert all(p['status']=='not_configured' for p in await ok(a,'GET','/api/workspace/model-catalog'))
            assert (await a.post('/api/workspace/volunteers',headers={'Origin':'https://evil.example'},json={'email':'blocked@example.org'})).status_code==403
            private=await ok(a,'POST','/api/workspace/scenarios',json=data('Private','private',['one@example.org']))
            public=await ok(a,'POST','/api/workspace/scenarios',json=data('Public','public',[]))
            await ok(a,'POST','/api/workspace/volunteers',json={'email':'two@example.org'})
            assert {s['id'] for s in await ok(v,'GET','/api/workspace/scenarios')}=={private['id'],public['id']}
            assert {s['id'] for s in await ok(w,'GET','/api/workspace/scenarios')}=={public['id']}
            assert (await w.get('/api/workspace/scenarios/'+private['id'])).status_code==404
            assert (await x.get('/api/workspace/scenarios')).status_code==403
            assert (await v.post('/api/workspace/scenarios',json=data('Forbidden','public',[]))).status_code==403
            s=await ok(v,'GET','/api/workspace/scenarios/'+public['id'])
            assert 'emails' not in s
            await ok(v,'POST','/api/training/acknowledge',json={'synthetic_only':True,'evidence_rule':True,'urgent_rule':True})
            conv=await ok(v,'POST','/api/campaigns/'+public['campaign_id']+'/conversations',json={'scenario_id':s['id'],'model_id':s['model_options'][0]['id']})
            r=await v.post('/api/conversations/'+conv['id']+'/turns',json={'prompt':'Fictional question','synthetic_only':True})
            assert r.is_success and '"type": "done"' in r.text
            transcript=await ok(v,'GET','/api/conversations/'+conv['id'])
            turn=transcript['turns'][0]['id']
            await ok(v,'POST','/api/workspace/conversations/'+conv['id']+'/flag',json={'turn_id':turn,'reason':'A concern'})
            await ok(v,'POST','/api/workspace/conversations/'+conv['id']+'/flag',json={'turn_id':turn,'reason':'Duplicate'})
            assert (await w.get('/api/conversations/'+conv['id'])).status_code==404
            assert not (await ok(w,'GET','/api/workspace/scenarios/'+public['id']))['sessions']
            detail=await ok(a,'GET','/api/workspace/scenarios/'+public['id'])
            assert detail['sessions'][0]['flags']==1
            assert detail['sessions'][0]['owner']=='one@example.org'
            assert len((await ok(a,'GET','/api/conversations/'+conv['id']))['findings'])==1
            assert next(s for s in await ok(a,'GET','/api/workspace/scenarios') if s['id']==public['id'])['flagged']==1
    asyncio.run(go())
