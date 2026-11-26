import asyncio,base64,json
from types import SimpleNamespace
import pytest
from src.access import parse,verified_email
ISS='https://pilot.cloudflareaccess.com'; AUD='pilot-audience'
def encode(x): return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
def token(alg='RS256',**kw):
    return encode({'alg':alg,'kid':'test'})+'.'+encode(dict({'iss':ISS,'aud':[AUD],'exp':20000000000,'email':'User@example.org'},**kw))+'.c2ln'
def test_access_claims():
    assert parse(token(),ISS,AUD,now=1000)[3]=='user@example.org'
    for t in (token(alg='none'),token(aud=['other']),token(iss='https://evil.com'),token(exp=999),token(nbf=1001),token(email=''),token(exp=True),'invalid'):
        with pytest.raises(Exception): parse(t,ISS,AUD,now=1000)
def test_access_signature_required():
    env=SimpleNamespace(ACCESS_ISSUER=ISS,ACCESS_AUD=AUD)
    req=SimpleNamespace(headers={'Cf-Access-Jwt-Assertion':token(),'Cf-Access-Authenticated-User-Email':'forged@example.org'})
    async def valid(*args): return True
    async def invalid(*args): return False
    assert asyncio.run(verified_email(req,env,valid))=='user@example.org'
    assert asyncio.run(verified_email(req,env,invalid)) is None
    req.headers.pop('Cf-Access-Jwt-Assertion')
    assert asyncio.run(verified_email(req,env,valid)) is None
