"""Verify the Access JWT even when the static-assets router removes ctx.access."""
import base64,json,re,time,math

def decode(s):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',s): raise ValueError("Invalid encoding")
    return base64.urlsafe_b64decode(s+'='*(-len(s)%4))

def parse(token,issuer,aud,now=None):
    if not issuer or not aud or not re.fullmatch(r'https://[a-z0-9-]+\.cloudflareaccess\.com',issuer):
        raise ValueError("Access not configured")
    if not token or len(token)>16384: raise ValueError("Missing or oversized token")
    a,b,c=token.split('.')
    h,p=json.loads(decode(a)),json.loads(decode(b))
    if h.get('alg')!='RS256' or not isinstance(h.get('kid'),str): raise ValueError("Invalid algorithm")
    audiences=p.get('aud')
    if isinstance(audiences,str): audiences=[audiences]
    if p.get('iss')!=issuer or not isinstance(audiences,list) or aud not in audiences: raise ValueError("Wrong issuer or audience")
    now=time.time() if now is None else now
    def numeric(v): return type(v) in (int,float) and math.isfinite(v)
    exp=p.get('exp'); nbf=p.get('nbf',0)
    if not numeric(exp) or exp<=now or not numeric(nbf) or nbf>now: raise ValueError("Expired or not yet valid")
    email=p.get('email')
    if not isinstance(email,str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise ValueError("No user email")
    return h['kid'],(a+'.'+b).encode(),decode(c),email.lower()

async def verify_signature(issuer,kid,message,signature):
    from js import crypto,fetch,Object,Uint8Array
    from pyodide.ffi import to_js
    def obj(d): return to_js(d,dict_converter=Object.fromEntries)
    def buf(b): return Uint8Array.new(to_js(list(b)))
    response=await fetch(issuer+'/cdn-cgi/access/certs')
    if not response.ok: return False
    data=(await response.json()).to_py()
    jwk=next((k for k in data.get('keys',[]) if k.get('kid')==kid and k.get('kty')=='RSA'),None)
    if not jwk: return False
    key=await crypto.subtle.importKey('jwk',obj(jwk),obj({'name':'RSASSA-PKCS1-v1_5','hash':'SHA-256'}),False,to_js(['verify']))
    return bool(await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,buf(signature),buf(message)))

async def verified_email(request,env,verifier=verify_signature):
    try:
        issuer=str(env.ACCESS_ISSUER); aud=str(env.ACCESS_AUD)
        kid,message,sig,email=parse(request.headers.get('Cf-Access-Jwt-Assertion'),issuer,aud)
        return email if await verifier(issuer,kid,message,sig) else None
    except Exception:
        return None
