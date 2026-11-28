import asyncio,base64,json,time
from urllib.parse import urlsplit,parse_qs
from types import SimpleNamespace
import httpx
from src.app import app
from src import workos
from tests.local_runtime import LocalD1

def test_workos_pkce_and_verified_identity(monkeypatch):
 async def go():
    d=LocalD1();d.conn.execute("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1)");d.conn.commit()
    origin='https://redteam.example.org'
    env=SimpleNamespace(DB=d,APP_ORIGIN=origin,BRITE_AUTH_MODE='workos',WORKOS_CLIENT_ID='client_test',WORKOS_API_KEY='sk_test',WORKOS_REDIRECT_URI=origin+'/auth/workos/callback')
    calls=[]
    async def fake_exchange(env,code,verifier):
        calls.append((code,verifier))
        return {'user':{'email':'new@example.org','email_verified':True,'id':'user_test'}}
    monkeypatch.setattr(workos,'exchange',fake_exchange)
    async def scoped(scope,receive,send):
        scope['brite_env']=env;scope['brite_email']='admin@example.org' # forged/fallback edge identity must not authorize WorkOS mode
        await app(scope,receive,send)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scoped),base_url=origin,headers={'Origin':origin},follow_redirects=False) as c:
        assert (await c.get('/api/me')).status_code==401
        assert (await c.post('/api/access/request',json={})).status_code==401
        r=await c.get('/auth/workos/start');assert r.status_code==302
        q=parse_qs(urlsplit(r.headers['location']).query);assert q['code_challenge_method']==['S256'] and len(q['code_challenge'][0])==43
        assert q['redirect_uri']==[env.WORKOS_REDIRECT_URI]
        cookie=c.cookies.get(workos.FLOW);assert cookie and 'HttpOnly' in r.headers['set-cookie'] and 'Secure' in r.headers['set-cookie']
        state,verifier=cookie.split('.');assert q['state']==[state] and q['code_challenge']==[workos.challenge(verifier)]
        r=await c.get('/auth/workos/callback',params={'state':'f'*64,'code':'bad'});assert 'auth_error=' in r.headers['location'] and not calls
        c.cookies.set(workos.FLOW,cookie,domain='redteam.example.org',path='/')
        r=await c.get('/auth/workos/callback',params={'state':state,'code':'valid'});assert r.headers['location']=='/' and calls==[('valid',verifier)]
        assert c.cookies.get(workos.SESSION)
        assert (await c.get('/api/me')).status_code==403
        assert (await c.post('/api/access/request',json={})).json()['status']=='pending'
        d.conn.execute("INSERT INTO users(email,role,trained) VALUES('new@example.org','volunteer',1)")
        d.conn.execute("UPDATE volunteer_access SET status='approved' WHERE email='new@example.org'");d.conn.commit()
        assert (await c.get('/api/me')).json()['email']=='new@example.org'
        assert (await c.get('/api/workspace/settings')).status_code==403
        d.conn.execute("UPDATE volunteer_access SET status='blacklisted' WHERE email='new@example.org'");d.conn.commit()
        assert (await c.get('/api/me')).status_code==403
        c.cookies.set(workos.FLOW,cookie,domain='redteam.example.org',path='/')
        r=await c.get('/auth/workos/callback',params={'state':state,'code':'replay'});assert 'auth_error=' in r.headers['location'] and len(calls)==1
        assert (await c.post('/api/auth/logout',json={},headers={'Origin':'https://evil.example'})).status_code==403
        assert (await c.post('/api/auth/logout',json={})).status_code==200
        assert (await c.get('/api/me')).status_code==401
        env.WORKOS_API_KEY=''
        assert (await c.get('/api/me')).status_code==401
        assert (await c.get('/auth/workos/start')).status_code==503
 asyncio.run(go())

def test_workos_preview_does_not_replace_cloudflare(monkeypatch):
 async def go():
    d=LocalD1();d.conn.execute("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1)");d.conn.commit()
    origin='https://redteam.example.org'
    env=SimpleNamespace(DB=d,APP_ORIGIN=origin,BRITE_AUTH_MODE='workos-preview',WORKOS_CLIENT_ID='client_test',WORKOS_API_KEY='sk_test',WORKOS_REDIRECT_URI=origin+'/auth/workos/callback')
    async def fake_exchange(env,code,verifier):return {'user':{'email':'other@example.org','email_verified':True,'id':'user_test'}}
    monkeypatch.setattr(workos,'exchange',fake_exchange)
    async def scoped(scope,receive,send):
        scope['brite_env']=env;scope['brite_email']='admin@example.org';await app(scope,receive,send)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scoped),base_url=origin,headers={'Origin':origin},follow_redirects=False) as c:
        assert (await c.get('/api/me')).json()['role']=='admin'
        r=await c.get('/auth/workos/start');state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
        r=await c.get('/auth/workos/callback',params={'state':state,'code':'test'})
        assert 'workos_identity_changed' in r.headers['location']
        assert not c.cookies.get(workos.SESSION)
        assert (await c.get('/api/me')).json()['role']=='admin'
 asyncio.run(go())
