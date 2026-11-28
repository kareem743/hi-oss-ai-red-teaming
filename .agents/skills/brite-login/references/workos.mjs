// WorkOS AuthKit: PKCE, verified allowlist, fresh-auth evidence access, and safe failure codes.
import {digest,equal,randomToken} from './security.mjs';
import {adminEmail} from './access-control.mjs';

const flowCookie='__Host-brite-oidc';
const clearFlow=flowCookie+'=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0';
const baseHeaders={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'};
const failureCodes=new Set(['workos_callback_invalid','workos_unavailable','workos_identity_unverified','not_approved','reauth_failed','reauth_identity_changed','session_failed']);
function fail(code='workos_callback_invalid',status=null){
 const safe=failureCodes.has(code)?code:'workos_callback_invalid';
 console.warn(JSON.stringify({event:'workos_auth_failed',reason:safe,http_status:Number.isInteger(status)?status:null}));
 return new Response(null,{status:302,headers:{...baseHeaders,Location:'/?auth_error='+safe,'Set-Cookie':clearFlow}});
}
const isHttpsUrl=s=>{try{return new URL(s).protocol==='https:'}catch{return false}};
export function workosEnabled(env){
 return env.WORKOS_ENABLED==='true' &&
  typeof env.WORKOS_CLIENT_ID==='string' && /^client_[A-Za-z0-9]+$/.test(env.WORKOS_CLIENT_ID) &&
  typeof env.WORKOS_API_KEY==='string' && env.WORKOS_API_KEY.startsWith('sk_') &&
  typeof env.WORKOS_OWNER_EMAIL==='string' && env.WORKOS_OWNER_EMAIL.trim().includes('@') &&
  env.WORKOS_OWNER_EMAIL.trim().split('@')[1]?.includes('.') &&
  isHttpsUrl(env.WORKOS_REDIRECT_URI) && new URL(env.WORKOS_REDIRECT_URI).pathname==='/auth/workos/callback';
}
function readFlow(req){
 const cookie=(req.headers.get('cookie')||'').split(';').map(x=>x.trim()).find(x=>x.startsWith(flowCookie+'='));
 if(!cookie)return null;
 const [state,verifier,mode='login',...extra]=cookie.slice(flowCookie.length+1).split('.');
 if(extra.length || !/^[0-9a-f]{64}$/.test(state||'') || !/^[0-9a-f]{64}$/.test(verifier||'') || !['login','evidence'].includes(mode))return null;
 return {state,verifier,mode};
}
export async function startWorkOS(req,env,options={}){
 if(!workosEnabled(env))return new Response('WorkOS is not configured.',{status:503,headers:baseHeaders});
 if(new URL(req.url).origin!==new URL(env.WORKOS_REDIRECT_URI).origin)return new Response('Invalid origin.',{status:400,headers:baseHeaders});
 const state=randomToken(),verifier=randomToken();
 const bytes=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier)));
 const challenge=btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
 if(!/^[A-Za-z0-9_-]{43}$/.test(challenge))return new Response('Unable to generate a valid authentication challenge.',{status:500,headers:baseHeaders});
 const forceEvidence=options.forceEvidence===true;
 if(forceEvidence){
  if(!options.db||typeof options.workosUserId!=='string'||!/^user_[A-Za-z0-9]+$/.test(options.workosUserId))return new Response('An active WorkOS administrator session is required.',{status:403,headers:baseHeaders});
  await options.db.prepare('INSERT INTO workos_reauth_flows(state_hash,workos_user_id,expires_at) VALUES(?,?,?)')
    .bind(await digest(state),options.workosUserId,Date.now()+600000).run();
 }
 const url=new URL('https://api.workos.com/user_management/authorize');
 for(const [key,value] of Object.entries({
  response_type:'code',client_id:env.WORKOS_CLIENT_ID,redirect_uri:env.WORKOS_REDIRECT_URI,
  provider:'authkit',state,code_challenge:challenge,code_challenge_method:'S256'
 }))url.searchParams.set(key,value);
 if(forceEvidence)url.searchParams.set('max_age','0');
 return new Response(null,{status:302,headers:{...baseHeaders,Location:url.toString(),
  'Set-Cookie':flowCookie+'='+state+'.'+verifier+'.'+(forceEvidence?'evidence':'login')+'; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600'}});
}
// Claims are accepted only from a successful server-to-server WorkOS code exchange.
function tokenClaims(token){
 try{
  const part=token.split('.')[1];if(!part)return {sid:null,authAt:null};
  const decoded=JSON.parse(atob(part.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-part.length%4)%4)));
  return {
   sid:typeof decoded.sid==='string'&&/^session_[A-Za-z0-9]+$/.test(decoded.sid)?decoded.sid:null,
   authAt:Number.isSafeInteger(decoded.auth_time)&&decoded.auth_time>0?decoded.auth_time*1000:null
  };
 }catch{return {sid:null,authAt:null}}
}
export async function finishWorkOS(req,env,db,createSession){
 if(!workosEnabled(env))return fail('workos_unavailable');
 const url=new URL(req.url);
 if(url.origin!==new URL(env.WORKOS_REDIRECT_URI).origin||url.pathname!==new URL(env.WORKOS_REDIRECT_URI).pathname)return fail();
 const flow=readFlow(req);
 const state=url.searchParams.get('state'),code=url.searchParams.get('code');
 if(!flow||!state||!equal(flow.state,state)||!code||code.length>4096||url.searchParams.has('error'))return fail();
 let result;
 try{
  const response=await fetch('https://api.workos.com/user_management/authenticate',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({client_id:env.WORKOS_CLIENT_ID,client_secret:env.WORKOS_API_KEY,grant_type:'authorization_code',code,code_verifier:flow.verifier}),
   signal:AbortSignal.timeout(12000)
  });
  if(!response.ok)return fail('workos_unavailable',response.status);
  result=await response.json();
 }catch{return fail('workos_unavailable')}
 const workosUser=result?.user;
 const email=typeof workosUser?.email==='string'?workosUser.email.trim().toLowerCase():'';
 if(!email||workosUser.email_verified!==true||typeof workosUser.id!=='string')return fail('workos_identity_unverified');
 const owner=adminEmail(email);
 if(!owner){
  const invited=await db.prepare("SELECT email FROM invited_users WHERE email=? AND enabled=1 UNION SELECT email FROM approved_workos_users WHERE email=? AND enabled=1 LIMIT 1").bind(email,email).first();
  if(!invited)return fail('not_approved');
 }
 const {sid,authAt}=tokenClaims(result.access_token||'');
 if(flow.mode==='evidence'){
  const reauth=await db.prepare('DELETE FROM workos_reauth_flows WHERE state_hash=? AND expires_at>? RETURNING workos_user_id').bind(await digest(state),Date.now()).first();
  if(!reauth)return fail('reauth_failed');
  if(!owner||reauth.workos_user_id!==workosUser.id)return fail('reauth_identity_changed');
  if(!authAt||authAt<Date.now()-120000||authAt>Date.now()+30000)return fail('reauth_failed');
 }
 const primaryOwner=email===env.WORKOS_OWNER_EMAIL.trim().toLowerCase();
 let issued;
 try{issued=await createSession(db,primaryOwner?null:email,'workos',workosUser.id,sid,authAt);}
 catch{return fail('session_failed')}
 const location=url.origin+(flow.mode==='evidence'?'/?auth_notice=evidence_verified#reports':'/#reports');
 const response=new Response(null,{status:302,headers:{...baseHeaders,Location:location}});
 response.headers.append('Set-Cookie',issued.headers.get('Set-Cookie'));
 response.headers.append('Set-Cookie',clearFlow);
 return response;
}
export function workosLogoutUrl(sessionId){
 if(typeof sessionId!=='string'||!/^session_[A-Za-z0-9]+$/.test(sessionId))return null;
 const url=new URL('https://api.workos.com/user_management/sessions/logout');
 url.searchParams.set('session_id',sessionId);
 return url.toString();
}
