"""BRITE WorkOS AuthKit adapter, ported from Medical Tool src/workos.mjs (96d38a4).
The local D1 account/approval system is the authorization boundary. WorkOS verifies identity only.
"""
import base64,hashlib,hmac,json,re,secrets,time
from urllib.parse import urlencode,urlsplit
import httpx
from fastapi.responses import RedirectResponse,JSONResponse
from .db import DB

FLOW='__Host-brite-oidc'
SESSION='__Host-brite-session'
COOKIE_FLAGS=dict(secure=True,httponly=True,samesite='lax',path='/')
HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}
def mode(env):
    value=str(getattr(env,'BRITE_AUTH_MODE','access') or 'access')
    return value if value in ('access','workos-preview','workos') else 'invalid'
def ready(env):
    try:
        origin=str(env.APP_ORIGIN);redirect=str(env.WORKOS_REDIRECT_URI)
        return (urlsplit(origin).scheme=='https' and urlsplit(origin).netloc!='' and
                redirect==origin+'/auth/workos/callback' and
                bool(re.fullmatch(r'client_[A-Za-z0-9]+',str(env.WORKOS_CLIENT_ID))) and
                str(env.WORKOS_API_KEY).startswith('sk_'))
    except Exception:return False
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def challenge(verifier):return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
def token():return secrets.token_hex(32)
def valid_token(s):return isinstance(s,str) and re.fullmatch(r'[0-9a-f]{64}',s) is not None
def fail(code='workos_callback_invalid'):
    r=RedirectResponse('/?auth_error='+code,status_code=302,headers=HEADERS)
    r.delete_cookie(FLOW,**COOKIE_FLAGS)
    return r
def error(message,status):return JSONResponse({'detail':message},status_code=status,headers=HEADERS)
def sid_from_exchange(token):
    try:
        p=token.split('.')[1];claims=json.loads(base64.urlsafe_b64decode(p+'='*(-len(p)%4)))
        sid=claims.get('sid')
        return sid if isinstance(sid,str) and re.fullmatch(r'session_[A-Za-z0-9]+',sid) else None
    except Exception:return None
async def identity(req,env):
    if not ready(env):return None
    t=req.cookies.get(SESSION)
    if not valid_token(t):return None
    row=await DB(env.DB).one('SELECT email FROM brite_workos_sessions WHERE token_hash=? AND expires_at>?',digest(t),int(time.time()))
    return row['email'] if row else None
def valid_origin(req,env):
    return str(req.url).split('/auth/workos/',1)[0]==str(env.APP_ORIGIN)

async def start(req,env):
    m=mode(env)
    if m not in ('workos-preview','workos') or not ready(env):return error('WorkOS is not configured.',503)
    if not valid_origin(req,env):return error('Invalid origin.',400)
    if m=='workos-preview' and not req.scope.get('brite_edge_email'):return error('Cloudflare Access sign-in required during preview.',401)
    d=DB(env.DB);now=int(time.time());window=now//60
    subject=digest('brite-workos-ip:'+req.headers.get('cf-connecting-ip','unknown'))
    allowance=await d.one("""INSERT INTO brite_workos_rate(subject,window,requests) VALUES(?,?,1)
      ON CONFLICT(subject,window) DO UPDATE SET requests=requests+1 WHERE requests<10 RETURNING requests""",subject,window)
    if not allowance:return error('Too many sign-in attempts. Try again later.',429)
    state,verifier=token(),token()
    await d.run('INSERT INTO brite_workos_flows(state_hash,verifier_hash,expires_at) VALUES(?,?,?)',digest(state),digest(verifier),now+600)
    url='https://api.workos.com/user_management/authorize?'+urlencode(dict(response_type='code',client_id=str(env.WORKOS_CLIENT_ID),redirect_uri=str(env.WORKOS_REDIRECT_URI),provider='authkit',state=state,code_challenge=challenge(verifier),code_challenge_method='S256'))
    r=RedirectResponse(url,status_code=302,headers=HEADERS)
    r.set_cookie(FLOW,state+'.'+verifier,max_age=600,**COOKIE_FLAGS)
    return r

async def exchange(env,code,verifier):
    # Same AuthKit authorization-code exchange as the Medical Tool. Never log secrets or response bodies.
    async with httpx.AsyncClient(timeout=httpx.Timeout(12,connect=5),follow_redirects=False) as client:
        r=await client.post('https://api.workos.com/user_management/authenticate',json=dict(client_id=str(env.WORKOS_CLIENT_ID),client_secret=str(env.WORKOS_API_KEY),grant_type='authorization_code',code=code,code_verifier=verifier))
        r.raise_for_status()
        return r.json()

async def finish(req,env):
    m=mode(env)
    if m not in ('workos-preview','workos') or not ready(env):return fail('workos_unavailable')
    if not valid_origin(req,env) or req.url.path!='/auth/workos/callback':return fail()
    flow=req.cookies.get(FLOW,'').split('.')
    state=req.query_params.get('state');code=req.query_params.get('code')
    if len(flow)!=2 or not all(valid_token(x) for x in flow) or not valid_token(state) or not hmac.compare_digest(flow[0],state) or not code or len(code)>4096 or 'error' in req.query_params:return fail()
    d=DB(env.DB);now=int(time.time())
    # One-use database reservation: a callback cannot be replayed, even with an old flow cookie.
    used=await d.one('DELETE FROM brite_workos_flows WHERE state_hash=? AND verifier_hash=? AND expires_at>? RETURNING state_hash',digest(state),digest(flow[1]),now)
    if not used:return fail()
    try:result=await exchange(env,code,flow[1])
    except Exception:return fail('workos_unavailable')
    user=result.get('user') if isinstance(result,dict) else None
    if not isinstance(user,dict):return fail('workos_identity_unverified')
    email=user.get('email');wid=user.get('id')
    if not isinstance(email,str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email.strip()) or user.get('email_verified') is not True or not isinstance(wid,str) or not re.fullmatch(r'user_[A-Za-z0-9]+',wid):return fail('workos_identity_unverified')
    email=email.strip().lower()
    if m=='workos-preview':
        if not req.scope.get('brite_edge_email') or email!=req.scope['brite_edge_email'].lower():return fail('workos_identity_changed')
    # Identity alone never grants authorization. The existing D1 approval/blacklist checks still run on every API.
    t=token();sid=sid_from_exchange(result.get('access_token',''))
    old=req.cookies.get(SESSION)
    if valid_token(old):await d.run('DELETE FROM brite_workos_sessions WHERE token_hash=?',digest(old))
    await d.run('INSERT INTO brite_workos_sessions(token_hash,email,workos_user_id,workos_sid,expires_at) VALUES(?,?,?,?,?)',digest(t),email,wid,sid,now+86400)
    r=RedirectResponse('/?auth_notice=workos_verified' if m=='workos-preview' else '/',status_code=302,headers=HEADERS)
    r.set_cookie(SESSION,t,max_age=86400,**COOKIE_FLAGS)
    r.delete_cookie(FLOW,**COOKIE_FLAGS)
    return r

async def logout(req,env):
    d=DB(env.DB);t=req.cookies.get(SESSION);row=None
    if valid_token(t):row=await d.one('DELETE FROM brite_workos_sessions WHERE token_hash=? RETURNING workos_sid',digest(t))
    sid=row.get('workos_sid') if row else None
    url='https://api.workos.com/user_management/sessions/logout?'+urlencode({'session_id':sid}) if sid and re.fullmatch(r'session_[A-Za-z0-9]+',sid) else '/'
    r=JSONResponse({'logout_url':url},headers=HEADERS)
    r.delete_cookie(SESSION,**COOKIE_FLAGS);r.delete_cookie(FLOW,**COOKIE_FLAGS)
    return r

async def cleanup(d):
    now=int(time.time())
    await d.batch([('DELETE FROM brite_workos_flows WHERE expires_at<=?',(now,)),('DELETE FROM brite_workos_sessions WHERE expires_at<=?',(now,)),('DELETE FROM brite_workos_rate WHERE window<?',(now//60-1440,))])
