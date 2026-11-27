import asyncio,httpx
from tests.local_runtime import LocalD1,runtime
from src.app import app

def test_approval_revocation_and_blacklist():
 async def go():
    d=LocalD1();d.conn.execute("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1)");d.conn.commit()
    def client(email):return httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d,email)),base_url='http://test')
    async with client('admin@example.org') as a,client('new@example.org') as v,client(None) as n:
      assert (await n.post('/api/access/request',json={'email':'new@example.org'})).status_code==401
      assert (await v.get('/api/me')).status_code==403
      for _ in range(2):assert (await v.post('/api/access/request',json={'email':'spoof@example.org'})).json()['status']=='pending'
      records=(await a.get('/api/workspace/access-requests')).json()
      assert len(records)==1 and records[0]['email']=='new@example.org'
      assert (await v.get('/api/workspace/access-requests')).status_code==403
      async def decision(action,email='new@example.org'):
        return await a.post('/api/workspace/access-decision',json={'email':email,'action':action})
      assert (await decision('reject')).status_code==200
      assert (await v.post('/api/access/request',json={})).json()['status']=='rejected'
      assert (await decision('approve')).status_code==200
      assert (await v.get('/api/me')).json()['role']=='volunteer'
      assert (await decision('remove')).status_code==200
      assert (await v.get('/api/me')).status_code==403
      assert (await v.post('/api/access/request',json={})).json()['status']=='pending'
      assert (await decision('approve')).status_code==200
      assert (await decision('blacklist')).status_code==200
      assert (await v.get('/api/me')).status_code==403
      assert (await v.post('/api/access/request',json={})).json()['status']=='blacklisted'
      assert (await decision('approve')).status_code==409
      assert (await a.post('/api/workspace/volunteers',json={'email':'new@example.org'})).status_code==409
      assert (await a.put('/api/users',json={'email':'new@example.org','role':'volunteer','active':True})).status_code==409
      assert (await decision('blacklist','admin@example.org')).status_code==409
      assert (await decision('unblock')).status_code==200
      assert (await v.post('/api/access/request',json={})).json()['status']=='pending'
      assert (await decision('approve')).status_code==200
      assert (await v.get('/api/me')).status_code==200
      assert (await v.get('/api/workspace/scenarios')).status_code==200
 asyncio.run(go())

def test_oversize_body_without_content_length():
 async def go():
    d=LocalD1();d.conn.execute("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1)");d.conn.commit()
    async def content():
        yield b'x'*65000
        yield b'x'*65000
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime(d)),base_url='http://test') as a:
        r=await a.post('/api/workspace/volunteers',content=content(),headers={'Content-Type':'application/json'})
        assert r.status_code==413
 asyncio.run(go())
