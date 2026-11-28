import asyncio,csv,io,json,uuid,hashlib,time
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel,Field
from .db import DB
from . import providers, vault, demo, workos
from types import SimpleNamespace
app=FastAPI(title='BRITE | Red Teaming',version='0.2.0',docs_url=None,redoc_url=None,openapi_url=None)

@app.exception_handler(RequestValidationError)
async def validation_error(req:Request,exc:RequestValidationError):
    if req.url.path.startswith('/api/workspace/settings/providers/'):
        return JSONResponse({'detail':'Invalid provider configuration.'},status_code=422)
    return JSONResponse({'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]},status_code=422)

def uid(): return str(uuid.uuid4())
def fail(code,msg): raise HTTPException(code,msg)
def db(req): return DB(req.scope['brite_env'].DB)
async def current(req:Request):
    email=req.scope.get('brite_email')
    if not email: fail(401,'Sign in to BRITE.')
    user=await db(req).one('SELECT email,role,trained FROM users WHERE email=? AND active=1',email.lower())
    if not user or await db(req).one("SELECT 1 FROM volunteer_access WHERE email=? AND status IN ('pending','rejected','removed','blacklisted')",email.lower()): fail(403,'Your account has not been approved.')
    return user

def role(user,*roles):
    if user['role'] not in roles: fail(403,'Insufficient permissions.')
async def campaign(d,u,c):
    row=await d.one('SELECT * FROM campaigns WHERE id=?',c)
    if not row: fail(404,'Campaign not found.')
    if u['role']!='admin' and not (u['role']=='volunteer' and row.get('is_public',0)) and not await d.one('SELECT 1 FROM memberships WHERE campaign_id=? AND email=?',c,u['email']): fail(404,'Campaign not found.')
    return row
async def conversation(d,u,c):
    row=await d.one('SELECT * FROM conversations WHERE id=?',c)
    if not row: fail(404,'Conversation not found.')
    await campaign(d,u,row['campaign_id'])
    if u['role']=='volunteer' and row['owner']!=u['email']: fail(404,'Conversation not found.')
    return row
async def own_open(d,u,c):
    role(u,'volunteer'); row=await conversation(d,u,c)
    if not u['trained']: fail(403,'Complete training first.')
    if row['state']!='open' or (await campaign(d,u,row['campaign_id']))['status']!='active': fail(409,'Conversation or campaign is closed.')
    return row

def audit(u,action,target): return ('INSERT INTO audit(id,actor,action,target) VALUES(?,?,?,?)',(uid(),u['email'],action,target))
async def write(d,u,action,target,sql,*args): await d.batch([(sql,args),audit(u,action,target)])

@app.middleware('http')
async def security(req:Request,call_next):
    # Same-origin-only mutations; Access authentication is independent of this check.
    if req.method not in ('GET','HEAD','OPTIONS'):
        origin=req.headers.get('origin'); expected=getattr(req.scope.get('brite_env'),'APP_ORIGIN','')
        if not expected or (origin!=expected and not (origin is None and req.scope.get('brite_test_provider'))): return Response('Origin not allowed',403)
        if req.headers.get('sec-fetch-site') in ('cross-site','same-site'): return Response('Origin not allowed',403)
        length=req.headers.get('content-length')
        if length and (not length.isdigit() or int(length)>128000): return Response('Request too large',413)
        # Bound actual bytes, even when Content-Length is absent.
        received=bytearray()
        async for chunk in req.stream():
            if len(received)+len(chunk)>128000:return Response('Request too large',413)
            received.extend(chunk)
        req._body=bytes(received)
    env=req.scope.get('brite_env')
    if env is not None:
        auth_mode=workos.mode(env)
        req.scope['brite_edge_email']=req.scope.get('brite_email')
        if auth_mode=='workos':req.scope['brite_email']=await workos.identity(req,env)
        elif auth_mode=='invalid':req.scope['brite_email']=None
    res=await call_next(req); res.headers['Cache-Control']='no-store';res.headers['X-Content-Type-Options']='nosniff';return res

class UserInput(BaseModel):
    email:str=Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    role:Literal['admin','volunteer','reviewer']
    active:bool=True
    trained:bool=False
class CampaignInput(BaseModel):
    title:str=Field(min_length=1,max_length=150); description:str=Field(min_length=1,max_length=4000)
class StatusInput(BaseModel): status:Literal['draft','active','closed']
class TextInput(BaseModel):
    title:str=Field(min_length=1,max_length=150); instructions:str=Field(min_length=1,max_length=4000)
class ModelInput(BaseModel):
    label:str=Field(min_length=1,max_length=100);provider:Literal['openai','anthropic'];model_name:str=Field(min_length=1,max_length=150);system_prompt:str=Field(default='',max_length=6000);max_tokens:int=Field(default=512,ge=64,le=2048)
class MembershipInput(BaseModel): email:str=Field(min_length=3,max_length=254)
class ConversationInput(BaseModel): scenario_id:str;model_id:str
class PromptInput(BaseModel): prompt:str=Field(min_length=1,max_length=8000); synthetic_only:Literal[True]
class FindingInput(BaseModel):
    turn_id:str;category:Literal['medical_accuracy','overconfidence','missed_warning','harmful_advice','other'];severity:Literal['low','moderate','high','urgent'];explanation:str=Field(min_length=10,max_length=5000);expected:str=Field(min_length=10,max_length=5000)
class ReviewInput(BaseModel):
    verdict:Literal['confirmed','not_confirmed','needs_more_evidence'];feedback:str=Field(min_length=10,max_length=5000)
class TrainingInput(BaseModel): synthetic_only:Literal[True]; evidence_rule:Literal[True]; urgent_rule:Literal[True]

@app.get('/api/health')
async def health(u=Depends(current)): return {'ok':True}
@app.get('/api/me')
async def me(u=Depends(current)): return u
@app.get('/api/users')
async def users(req:Request,u=Depends(current)):
    role(u,'admin'); return await db(req).all('SELECT * FROM users ORDER BY email LIMIT 500')
@app.put('/api/users')
async def put_user(req:Request,p:UserInput,u=Depends(current)):
    role(u,'admin'); email=p.email.lower()
    if await db(req).one("SELECT 1 FROM volunteer_access WHERE email=? AND status IN ('pending','rejected','removed','blacklisted')",email):fail(409,'Manage volunteer access through the Volunteers tab.')
    if email==u['email'] and (p.role!='admin' or not p.active): fail(409,'Cannot remove your own administrator access.')
    await write(db(req),u,'user.upsert',email,'INSERT INTO users(email,role,active,trained) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET role=excluded.role,active=excluded.active,trained=excluded.trained',email,p.role,int(p.active),int(p.trained));return {'email':email}
@app.post('/api/training/acknowledge')
async def training(req:Request,p:TrainingInput,u=Depends(current)):
    role(u,'volunteer'); await write(db(req),u,'training.acknowledge',u['email'],'UPDATE users SET trained=1 WHERE email=?',u['email']);return {'trained':True}
@app.get('/api/campaigns')
async def campaigns(req:Request,u=Depends(current)):
    d=db(req)
    if u['role']=='admin': return await d.all('SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 200')
    return await d.all("SELECT c.* FROM campaigns c WHERE (EXISTS(SELECT 1 FROM memberships m WHERE m.campaign_id=c.id AND m.email=?) OR (?='volunteer' AND c.is_public=1)) AND (?!='volunteer' OR c.status='active') ORDER BY c.created_at DESC LIMIT 200",u['email'],u['role'],u['role'])
@app.post('/api/campaigns',status_code=201)
async def create_campaign(req:Request,p:CampaignInput,u=Depends(current)):
    role(u,'admin'); id=uid();await write(db(req),u,'campaign.create',id,'INSERT INTO campaigns(id,title,description) VALUES(?,?,?)',id,p.title,p.description);return {'id':id}
@app.patch('/api/campaigns/{c}')
async def set_status(req:Request,c:str,p:StatusInput,u=Depends(current)):
    role(u,'admin');d=db(req);await campaign(d,u,c)
    if p.status=='active' and (not await d.one('SELECT 1 FROM scenarios WHERE campaign_id=?',c) or not await d.one('SELECT 1 FROM models WHERE campaign_id=? AND enabled=1',c)): fail(409,'Add a scenario and model before activating.')
    await write(d,u,'campaign.status',c,'UPDATE campaigns SET status=? WHERE id=?',p.status,c);return {'status':p.status}
@app.get('/api/campaigns/{c}')
async def detail(req:Request,c:str,u=Depends(current)):
    d=db(req); row=await campaign(d,u,c)
    row['scenarios']=await d.all('SELECT * FROM scenarios WHERE campaign_id=? LIMIT 200',c)
    row['tasks']=await d.all('SELECT t.* FROM tasks t JOIN scenarios s ON t.scenario_id=s.id WHERE s.campaign_id=? LIMIT 1000',c)
    cols='id,label' if u['role']=='volunteer' else 'id,label,provider,model_name,system_prompt,max_tokens,enabled'
    row['models']=await d.all('SELECT '+cols+' FROM models WHERE campaign_id=? AND enabled=1 LIMIT 50',c)
    if u['role']=='admin': row['members']=await d.all('SELECT u.email,u.role,u.trained,u.active FROM memberships m JOIN users u ON u.email=m.email WHERE m.campaign_id=? LIMIT 500',c)
    return row
@app.post('/api/campaigns/{c}/members')
async def add_member(req:Request,c:str,p:MembershipInput,u=Depends(current)):
    role(u,'admin');d=db(req);await campaign(d,u,c);email=p.email.lower()
    if not await d.one('SELECT 1 FROM users WHERE email=? AND active=1',email):fail(404,'Create an approved user first.')
    await write(d,u,'member.add',c,'INSERT OR IGNORE INTO memberships(campaign_id,email) VALUES(?,?)',c,email);return {'ok':True}
@app.delete('/api/campaigns/{c}/members/{email}')
async def remove_member(req:Request,c:str,email:str,u=Depends(current)):
    role(u,'admin');d=db(req);await campaign(d,u,c);await write(d,u,'member.remove',c,'DELETE FROM memberships WHERE campaign_id=? AND email=?',c,email.lower());return {'ok':True}
@app.post('/api/campaigns/{c}/scenarios',status_code=201)
async def add_scenario(req:Request,c:str,p:TextInput,u=Depends(current)):
    role(u,'admin');d=db(req);await campaign(d,u,c);id=uid();await write(d,u,'scenario.create',id,'INSERT INTO scenarios(id,campaign_id,title,instructions) VALUES(?,?,?,?)',id,c,p.title,p.instructions);return {'id':id}
@app.post('/api/scenarios/{s}/tasks',status_code=201)
async def add_task(req:Request,s:str,p:TextInput,u=Depends(current)):
    role(u,'admin');d=db(req);row=await d.one('SELECT campaign_id FROM scenarios WHERE id=?',s)
    if not row:fail(404,'Scenario not found.')
    id=uid();await write(d,u,'task.create',id,'INSERT INTO tasks(id,scenario_id,title,instructions) VALUES(?,?,?,?)',id,s,p.title,p.instructions);return {'id':id}
@app.post('/api/campaigns/{c}/models',status_code=201)
async def add_model(req:Request,c:str,p:ModelInput,u=Depends(current)):
    role(u,'admin');d=db(req);await campaign(d,u,c);id=uid();await write(d,u,'model.create',id,'INSERT INTO models(id,campaign_id,label,provider,model_name,system_prompt,max_tokens) VALUES(?,?,?,?,?,?,?)',id,c,p.label,p.provider,p.model_name,p.system_prompt,p.max_tokens);return {'id':id}
@app.get('/api/campaigns/{c}/conversations')
async def conversations(req:Request,c:str,u=Depends(current)):
    d=db(req);await campaign(d,u,c);args=[c];where=''
    if u['role']=='volunteer': where=' AND v.owner=?';args.append(u['email'])
    return await d.all('SELECT v.id,v.owner,v.state,v.created_at,s.title AS scenario,m.label AS model FROM conversations v JOIN scenarios s ON s.id=v.scenario_id JOIN models m ON m.id=v.model_id WHERE v.campaign_id=?'+where+' ORDER BY v.created_at DESC LIMIT 500',*args)
@app.post('/api/campaigns/{c}/conversations',status_code=201)
async def start(req:Request,c:str,p:ConversationInput,u=Depends(current)):
    role(u,'volunteer');d=db(req);row=await campaign(d,u,c)
    if not u['trained']:fail(403,'Complete training first.')
    if row['status']!='active':fail(409,'Campaign is not active.')
    s=await d.one('SELECT id FROM scenarios WHERE id=? AND campaign_id=?',p.scenario_id,c);m=await d.one('SELECT * FROM models WHERE id=? AND campaign_id=? AND enabled=1',p.model_id,c)
    if not s or not m:fail(422,'Choose a scenario and model from this campaign.')
    id=uid();await write(d,u,'conversation.create',id,'INSERT INTO conversations(id,campaign_id,scenario_id,model_id,owner,model_snapshot) VALUES(?,?,?,?,?,?)',id,c,p.scenario_id,p.model_id,u['email'],json.dumps(m));return {'id':id}
async def conversation_limits(d,row,turns,model):
    scenario=await d.one('SELECT max_turns,max_context_chars,no_limit FROM scenarios WHERE id=?',row['scenario_id'])
    if not scenario: fail(404,'Scenario not found.')
    # Count all reserved attempts, even failed ones, to prevent repeated billed retries.
    # Context is the actual text included in the next provider request, excluding protocol framing.
    chars=len(model.get('system_prompt') or '')+sum(len(t['prompt'])+len(t['response']) for t in turns if t['status']=='complete')
    maximum=scenario['max_context_chars']
    return {'no_limit':bool(scenario['no_limit']),'max_turns':None if scenario['no_limit'] else scenario['max_turns'],'turns_used':len(turns),'turns_remaining':None if scenario['no_limit'] else max(0,scenario['max_turns']-len(turns)),
            'max_context_chars':None if scenario['no_limit'] else maximum,'context_chars_used':chars,'context_chars_remaining':None if scenario['no_limit'] else max(0,maximum-chars)}

@app.get('/api/conversations/{c}')
async def read_conversation(req:Request,c:str,u=Depends(current)):
    d=db(req);row=await conversation(d,u,c);model=json.loads(row.pop('model_snapshot'))
    row['turns']=await d.all('SELECT * FROM turns WHERE conversation_id=? ORDER BY seq',c)
    row['limits']=await conversation_limits(d,row,row['turns'],model)
    row['tasks']=await d.all('SELECT t.*, CASE WHEN x.task_id IS NULL THEN 0 ELSE 1 END AS completed FROM tasks t LEFT JOIN completions x ON x.task_id=t.id AND x.conversation_id=? WHERE t.scenario_id=?',c,row['scenario_id'])
    row['findings']=await d.all('SELECT f.*,r.verdict,r.feedback FROM findings f LEFT JOIN reviews r ON r.finding_id=f.id WHERE f.conversation_id=? ORDER BY f.created_at',c)
    return row
@app.post('/api/conversations/{c}/turns')
async def send(req:Request,c:str,p:PromptInput,u=Depends(current)):
    d=db(req);row=await own_open(d,u,c);model=json.loads(row['model_snapshot']);env=req.scope['brite_env']
    is_demo=model['model_name']==demo.DEMO_ID
    mock=req.scope.get('brite_test_provider')
    paid=not is_demo and not mock
    config=None;provider_env=env
    if paid:
        config=await registered_model(d,model['provider'],model['model_name'])
        if not config:fail(503,'API model is not registered or enabled in Settings.')
        try:
            key=await vault.unseal(env,model['provider'],config['cipher'])
        except Exception:fail(503,'API credential is unavailable.')
        provider_env=SimpleNamespace(**{('OPENAI_API_KEY' if model['provider']=='openai' else 'ANTHROPIC_API_KEY'):key})
    rows=await d.all('SELECT seq,prompt,response,status FROM turns WHERE conversation_id=? ORDER BY seq',c)
    limits=await conversation_limits(d,row,rows,model)
    if not limits['no_limit'] and limits['turns_remaining']==0:fail(409,f"Conversation turn limit reached ({limits['max_turns']}).")
    if any(r['status']=='pending' for r in rows):fail(409,'A response is already in progress.')
    history=[]
    for r in rows:
        if r['status']=='complete':history.extend([{'role':'user','content':r['prompt']},{'role':'assistant','content':r['response']}])
    history.append({'role':'user','content':p.prompt})
    if limits['context_chars_used']+len(p.prompt)>80000:fail(409,'Platform context safety limit reached. Start a new chat.')
    if not limits['no_limit'] and len(p.prompt)>limits['context_chars_remaining']: fail(409,f"Conversation context limit reached ({limits['max_context_chars']} characters). Shorten the message or finish the chat.")
    id=uid();seq=rows[-1]['seq']+1 if rows else 1
    # Atomic D1 batch. Reserve only when all limits and account checks pass.
    now=int(time.time()); minute=str(now//60); month=time.strftime('%Y-%m',time.gmtime(now)); day=time.strftime('%Y-%m-%d',time.gmtime(now))
    ip=req.headers.get('CF-Connecting-IP','unknown')
    ip_key=hashlib.sha256(('brite-ip-v1:'+ip).encode()).hexdigest()
    size=limits['context_chars_used']+len(p.prompt)
    input_bytes=len((model.get('system_prompt') or '').encode('utf-8'))+sum(len(x['content'].encode('utf-8')) for x in history)
    if input_bytes>320000:fail(409,'Platform context safety limit reached.')
    rate_in=config['input_cents'] if paid else 0;rate_out=config['output_cents'] if paid else 0
    # Conservative estimate: UTF-8 bytes plus message framing allowance, full output allowance.
    reserved=price_micros(input_bytes+64*len(history)+1024,model['max_tokens'],rate_in,rate_out) if paid else 0
    provider=model['provider'];name=model['model_name'];pr=config['provider_revision'] if paid else -1;mr=config['model_revision'] if paid else -1
    try:
        await d.batch([
          ("""INSERT INTO turns(id,conversation_id,seq,prompt,status)
          SELECT ?,?,?,?,'pending' WHERE EXISTS(SELECT 1 FROM users WHERE email=? AND active=1 AND role='volunteer')
          AND NOT EXISTS(SELECT 1 FROM volunteer_access WHERE email=? AND status!='approved')
          AND EXISTS(SELECT 1 FROM safety_settings WHERE id=1 AND enabled=1)
          AND COALESCE((SELECT requests FROM model_daily_usage WHERE email=? AND day=?),0)<50
          AND COALESCE((SELECT requests FROM abuse_windows WHERE kind='user' AND subject=? AND window=?),0)<5
          AND COALESCE((SELECT requests FROM abuse_windows WHERE kind='ip' AND subject=? AND window=?),0)<20
          AND COALESCE((SELECT requests FROM model_monthly_usage WHERE month=?),0)<1000
          AND COALESCE((SELECT reserved_input_bytes FROM model_monthly_usage WHERE month=?),0)+?<=2000000
          AND COALESCE((SELECT output_token_allowance FROM model_monthly_usage WHERE month=?),0)+?<=512000
          AND NOT EXISTS(SELECT 1 FROM turns t JOIN conversations v ON v.id=t.conversation_id WHERE v.owner=? AND t.status='pending')
          AND (?=0 OR (EXISTS(SELECT 1 FROM api_providers p JOIN api_models m ON m.provider=p.provider WHERE p.provider=? AND m.model_name=? AND p.enabled=1 AND m.enabled=1 AND p.cipher!='' AND p.revision=? AND m.revision=?)
           AND (SELECT COUNT(*) FROM api_cost WHERE month=? AND provider=?)<(SELECT monthly_requests FROM api_providers WHERE provider=?)
           AND COALESCE((SELECT SUM(cost_micros) FROM api_cost WHERE month=? AND provider=?),0)+?<=(SELECT budget_micros FROM api_providers WHERE provider=?)
           AND COALESCE((SELECT SUM(cost_micros) FROM api_cost WHERE month=?),0)+?<=(SELECT budget_micros FROM api_budget WHERE id=1)))""",(id,c,seq,p.prompt,u['email'],u['email'],u['email'],day,u['email'],minute,ip_key,minute,month,month,input_bytes,month,model['max_tokens'],u['email'],int(paid),provider,name,pr,mr,month,provider,provider,month,provider,reserved,provider,month,reserved)),
          ("""INSERT INTO model_daily_usage(email,day,requests) SELECT ?,?,1 WHERE EXISTS(SELECT 1 FROM turns WHERE id=?)
            ON CONFLICT(email,day) DO UPDATE SET requests=requests+1""",(u['email'],day,id)),
          ("""INSERT INTO abuse_windows(kind,subject,window,requests) SELECT 'user',?,?,1 WHERE EXISTS(SELECT 1 FROM turns WHERE id=?)
            ON CONFLICT(kind,subject,window) DO UPDATE SET requests=requests+1""",(u['email'],minute,id)),
          ("""INSERT INTO abuse_windows(kind,subject,window,requests) SELECT 'ip',?,?,1 WHERE EXISTS(SELECT 1 FROM turns WHERE id=?)
            ON CONFLICT(kind,subject,window) DO UPDATE SET requests=requests+1""",(ip_key,minute,id)),
          ("""INSERT INTO model_monthly_usage(month,requests,input_chars,output_token_allowance,reserved_input_bytes) SELECT ?,1,?,?,? WHERE EXISTS(SELECT 1 FROM turns WHERE id=?)
            ON CONFLICT(month) DO UPDATE SET requests=requests+1,input_chars=input_chars+excluded.input_chars,output_token_allowance=output_token_allowance+excluded.output_token_allowance,reserved_input_bytes=reserved_input_bytes+excluded.reserved_input_bytes""",(month,size,model['max_tokens'],input_bytes,id)),
          ("""INSERT INTO model_usage(turn_id,email,scenario_id,model_id,input_chars,output_token_allowance) SELECT ?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM turns WHERE id=?)""",(id,u['email'],row['scenario_id'],row['model_id'],size,model['max_tokens'],id)),
          ("""INSERT INTO api_cost(turn_id,provider,model_name,month,cost_micros,reserved_micros,input_cents,output_cents,status) SELECT ?,?,?,?,?,?,?,?,'reserved' WHERE ?=1 AND EXISTS(SELECT 1 FROM turns WHERE id=?)""",(id,provider,name,month,reserved,reserved,rate_in,rate_out,int(paid),id))
        ])
    except Exception:fail(409,'Unable to reserve turn; refresh and retry.')
    if not await d.one('SELECT id FROM turns WHERE id=?',id):
        await d.batch([audit(u,'model.request_blocked',c)])
        fail(429,'Model request blocked by usage limits, concurrent request, or administrator pause.')
    def event(kind,**data):return 'data: '+json.dumps({'type':kind,**data})+'\n\n'
    source=demo.chunks if is_demo else (mock or providers.chunks)
    model['_usage']={}
    async def stream():
        text='';yield event('start',turn_id=id)
        try:
            async for piece in source(model,history,provider_env):
                text+=piece
                if len(text)>100000: raise RuntimeError('Response too large')
                yield event('delta',text=piece)
            changed=await d.run("UPDATE turns SET response=?,status='complete' WHERE id=? AND status='pending'",text,id)
            await d.run('UPDATE model_usage SET output_chars=? WHERE turn_id=?',len(text),id)
            if changed!=1:raise RuntimeError('Turn expired')
            if paid:
                usage=model['_usage'];it=usage.get('input_tokens');ot=usage.get('output_tokens')
                if type(it)==int and type(ot)==int and it>=0 and ot>=0:
                    actual=price_micros(it,ot,rate_in,rate_out)
                    await d.run("UPDATE api_cost SET cost_micros=?,input_tokens=?,output_tokens=?,status='reported' WHERE turn_id=?",actual,it,ot,id)
                else:await d.run("UPDATE api_cost SET status='estimated' WHERE turn_id=?",id)
            yield event('done',turn_id=id)
        except (Exception,asyncio.CancelledError) as exc:
            try:await d.run("UPDATE turns SET response=?,status='failed',error='Stream interrupted or provider failed' WHERE id=? AND status='pending'",text,id)
            except Exception:pass
            if paid:
                try:await d.run("UPDATE api_cost SET status='estimated' WHERE turn_id=? AND status='reserved'",id)
                except Exception:pass
            if isinstance(exc,asyncio.CancelledError):raise
            yield event('error',message='Model response could not be completed. Refresh to inspect the saved turn.')
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
@app.put('/api/conversations/{c}/tasks/{t}')
async def complete_task(req:Request,c:str,t:str,u=Depends(current)):
    d=db(req);row=await own_open(d,u,c)
    if not await d.one('SELECT 1 FROM tasks WHERE id=? AND scenario_id=?',t,row['scenario_id']):fail(404,'Task not found.')
    await write(d,u,'task.complete',t,'INSERT OR IGNORE INTO completions(conversation_id,task_id) VALUES(?,?)',c,t);return {'ok':True}
@app.post('/api/conversations/{c}/findings',status_code=201)
async def flag(req:Request,c:str,p:FindingInput,u=Depends(current)):
    d=db(req);await own_open(d,u,c)
    if not await d.one("SELECT 1 FROM turns WHERE id=? AND conversation_id=? AND status='complete'",p.turn_id,c):fail(422,'Flag a completed response from this conversation.')
    id=uid();await write(d,u,'finding.create',id,'INSERT INTO findings(id,conversation_id,turn_id,author,category,severity,explanation,expected) VALUES(?,?,?,?,?,?,?,?)',id,c,p.turn_id,u['email'],p.category,p.severity,p.explanation,p.expected);return {'id':id}
@app.post('/api/conversations/{c}/submit')
async def submit(req:Request,c:str,u=Depends(current)):
    d=db(req);row=await own_open(d,u,c)
    if await d.one("SELECT 1 FROM turns WHERE conversation_id=? AND status='pending'",c):fail(409,'Wait for response completion.')
    if not await d.one("SELECT 1 FROM turns WHERE conversation_id=? AND status='complete'",c):fail(409,'Complete at least one turn.')
    if await d.one('SELECT 1 FROM tasks t WHERE t.scenario_id=? AND NOT EXISTS(SELECT 1 FROM completions x WHERE x.task_id=t.id AND x.conversation_id=?)',row['scenario_id'],c):fail(409,'Complete all scenario tasks.')
    await write(d,u,'conversation.submit',c,"UPDATE conversations SET state='submitted' WHERE id=?",c);return {'state':'submitted'}
@app.get('/api/campaigns/{c}/findings')
async def queue(req:Request,c:str,u=Depends(current)):
    role(u,'admin','reviewer');d=db(req);await campaign(d,u,c)
    return await d.all("SELECT f.*,v.state,r.verdict,r.feedback,r.reviewer FROM findings f JOIN conversations v ON v.id=f.conversation_id LEFT JOIN reviews r ON r.finding_id=f.id WHERE v.campaign_id=? AND (v.state='submitted' OR f.severity='urgent') ORDER BY CASE f.severity WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,f.created_at LIMIT 500",c)
@app.post('/api/findings/{f}/review')
async def review(req:Request,f:str,p:ReviewInput,u=Depends(current)):
    role(u,'reviewer','admin');d=db(req);r=await d.one('SELECT f.*,v.state FROM findings f JOIN conversations v ON v.id=f.conversation_id WHERE f.id=?',f)
    if not r:fail(404,'Finding not found.')
    await conversation(d,u,r['conversation_id'])
    if r['state']!='submitted' and r['severity']!='urgent':fail(409,'Await submission.')
    if r['author']==u['email']:fail(403,'Independent review required.')
    if await d.one('SELECT 1 FROM reviews WHERE finding_id=?',f):fail(409,'Already reviewed.')
    try:await write(d,u,'finding.review',f,'INSERT INTO reviews(finding_id,reviewer,verdict,feedback) VALUES(?,?,?,?)',f,u['email'],p.verdict,p.feedback)
    except Exception:fail(409,'Review could not be recorded; refresh.')
    return {'verdict':p.verdict}
@app.get('/api/campaigns/{c}/metrics')
async def metrics(req:Request,c:str,u=Depends(current)):
    role(u,'admin','reviewer');d=db(req);await campaign(d,u,c)
    return await d.one("SELECT (SELECT COUNT(*) FROM memberships WHERE campaign_id=?) AS members,(SELECT COUNT(*) FROM conversations WHERE campaign_id=?) AS conversations,(SELECT COUNT(*) FROM conversations WHERE campaign_id=? AND state='submitted') AS submitted,(SELECT COUNT(*) FROM findings f JOIN conversations v ON v.id=f.conversation_id WHERE v.campaign_id=?) AS findings,(SELECT COUNT(*) FROM reviews r JOIN findings f ON r.finding_id=f.id JOIN conversations v ON v.id=f.conversation_id WHERE v.campaign_id=?) AS reviewed",c,c,c,c,c)
@app.get('/api/campaigns/{c}/export')
async def export(req:Request,c:str,u=Depends(current)):
    role(u,'admin');d=db(req);await campaign(d,u,c)
    # Bounded pilot export: no silent truncation or spreadsheet formula injection.
    convs=await d.all('SELECT * FROM conversations WHERE campaign_id=? LIMIT 201',c)
    if len(convs)>200:fail(413,'Pilot export exceeds 200 conversations; use a queued export implementation.')
    data={'campaign':await campaign(d,u,c),'conversations':convs,'scenarios':await d.all('SELECT * FROM scenarios WHERE campaign_id=?',c),'tasks':await d.all('SELECT t.* FROM tasks t JOIN scenarios s ON s.id=t.scenario_id WHERE s.campaign_id=?',c)}
    for name,sql in [('turns','SELECT t.* FROM turns t JOIN conversations v ON v.id=t.conversation_id WHERE v.campaign_id=? LIMIT 5001'),('findings','SELECT f.* FROM findings f JOIN conversations v ON v.id=f.conversation_id WHERE v.campaign_id=? LIMIT 5001'),('reviews','SELECT r.* FROM reviews r JOIN findings f ON r.finding_id=f.id JOIN conversations v ON v.id=f.conversation_id WHERE v.campaign_id=? LIMIT 5001'),('completions','SELECT x.* FROM completions x JOIN conversations v ON v.id=x.conversation_id WHERE v.campaign_id=? LIMIT 5001')]:
        data[name]=await d.all(sql,c)
        if len(data[name])>5000:fail(413,'Pilot export exceeds 5,000 rows; use a queued export.')
    payload=json.dumps(data,ensure_ascii=False)
    if len(payload.encode())>8_000_000:fail(413,'Export exceeds 8 MB.')
    await d.batch([audit(u,'campaign.export',c)])
    return Response(payload,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="brite-{c}.json"'})
@app.get('/api/audit')
async def audit_log(req:Request,u=Depends(current)):
    role(u,'admin');return await db(req).all('SELECT * FROM audit ORDER BY created_at DESC LIMIT 500')

async def reap(env):
    d=DB(env.DB)
    result=await d.run("UPDATE turns SET status='failed',error='Interrupted response (timeout)' WHERE status='pending' AND created_at < datetime('now','-10 minutes')")
    await d.run('DELETE FROM abuse_windows WHERE CAST(window AS INTEGER)<?',int(time.time())//60-1440)
    await workos.cleanup(d)
    return result


# Scenario-first workspace. Campaigns remain the internal authorization boundary.
from pydantic import BaseModel, Field
from typing import Literal

class WorkspaceScenario(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(min_length=1,max_length=12000)
    audience: Literal['public','private']
    emails: list[str] = Field(default_factory=list,max_length=20)
    provider: Literal['openai','anthropic','demo']
    model_name: str = Field(min_length=1,max_length=200)
    model_label: str = Field(min_length=1,max_length=200)
    system_prompt: str = Field(default='',max_length=6000)
    no_limit: bool = Field(default=False,strict=True)
    max_turns: int | None = Field(default=None,ge=1,le=25,strict=True)
    max_context_chars: int | None = Field(default=None,ge=1000,le=80000,strict=True)

class WorkspaceEmail(BaseModel):
    email: str = Field(min_length=3,max_length=254)

class WorkspaceFlag(BaseModel):
    turn_id: str
    reason: str = Field(default='',max_length=4000)

def normalize_email(value):
    import re
    v=value.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v) or len(v)>254: fail(422,'Enter a valid email address.')
    return v

async def workspace_assignment(d,u,c,emails):
    result=[]
    for e in dict.fromkeys(normalize_email(x) for x in emails):
        existing=await d.one('SELECT role,active FROM users WHERE email=?',e)
        if not existing or existing['role']!='volunteer' or not existing['active']: fail(409,'Select an approved, active volunteer.')
        result.append(('INSERT OR IGNORE INTO memberships(campaign_id,email) VALUES(?,?)',(c,e)))
    return result

@app.get('/api/workspace/scenarios')
async def workspace_scenarios(req:Request,u=Depends(current)):
    d=db(req)
    sql="""SELECT s.id,s.campaign_id,s.title,s.instructions AS description,s.max_turns,s.max_context_chars,s.no_limit,c.status,c.is_public,c.created_at,
        (SELECT GROUP_CONCAT(m.label,', ') FROM models m WHERE m.campaign_id=c.id AND m.enabled=1) AS models,
        (SELECT COUNT(*) FROM conversations v WHERE v.scenario_id=s.id) AS conversations,
        (SELECT COUNT(DISTINCT v.id) FROM conversations v JOIN findings f ON f.conversation_id=v.id WHERE v.scenario_id=s.id) AS flagged,
        (SELECT COUNT(*) FROM memberships m JOIN users a ON a.email=m.email WHERE m.campaign_id=c.id AND a.role='volunteer') AS assigned
        FROM scenarios s JOIN campaigns c ON c.id=s.campaign_id"""
    if u['role']=='admin':
        return await d.all(sql+' ORDER BY c.created_at DESC,s.id LIMIT 200')
    if u['role']=='reviewer':
        return await d.all(sql+" WHERE EXISTS(SELECT 1 FROM memberships m WHERE m.campaign_id=c.id AND m.email=?) ORDER BY c.created_at DESC,s.id LIMIT 200",u['email'])
    # Never disclose other volunteers' counts, assignments, or evidence.
    return await d.all("""SELECT s.id,s.campaign_id,s.title,s.instructions AS description,s.max_turns,s.max_context_chars,s.no_limit,c.status,c.is_public,
        (SELECT GROUP_CONCAT(m.label,', ') FROM models m WHERE m.campaign_id=c.id AND m.enabled=1) AS models,
        (SELECT COUNT(*) FROM conversations v WHERE v.scenario_id=s.id AND v.owner=?) AS conversations
        FROM scenarios s JOIN campaigns c ON c.id=s.campaign_id WHERE c.status='active' AND (c.is_public=1 OR EXISTS(SELECT 1 FROM memberships m WHERE m.campaign_id=c.id AND m.email=?))
        ORDER BY c.created_at DESC,s.id LIMIT 200""",u['email'],u['email'])

@app.post('/api/workspace/scenarios',status_code=201)
async def workspace_create(req:Request,p:WorkspaceScenario,u=Depends(current)):
    role(u,'admin');d=db(req)
    if not p.title.strip() or not p.description.strip() or not p.model_name.strip() or not p.model_label.strip(): fail(422,'Complete all required fields.')
    if p.audience=='private' and not p.emails: fail(422,'Assign at least one volunteer email.')
    if p.provider=='demo':
        if p.model_name!=demo.DEMO_ID:fail(422,'Invalid demo model.')
    elif p.model_name==demo.DEMO_ID:fail(422,'Reserved demo model ID.')
    elif not req.scope.get('brite_test_provider') and not await registered_model(d,p.provider,p.model_name):fail(409,'Register and enable this API model in Settings first.')
    c,s,m=uid(),uid(),uid()
    assignments=await workspace_assignment(d,u,c,p.emails)
    await d.batch([
        ("INSERT INTO campaigns(id,title,description,status,is_public) VALUES(?,?,?,'active',?)",(c,p.title.strip(),p.description.strip(),int(p.audience=='public'))),
        ('INSERT INTO scenarios(id,campaign_id,title,instructions,max_turns,max_context_chars,no_limit) VALUES(?,?,?,?,?,?,?)',(s,c,p.title.strip(),p.description.strip(),p.max_turns if p.max_turns is not None else 25,p.max_context_chars if p.max_context_chars is not None else 80000,int(p.no_limit))),
        ('INSERT INTO models(id,campaign_id,label,provider,model_name,system_prompt) VALUES(?,?,?,?,?,?)',(m,c,('Demo' if p.provider=='demo' else p.model_label.strip()),('openai' if p.provider=='demo' else p.provider),p.model_name.strip(),p.system_prompt)),
        *assignments,audit(u,'scenario.create',s)
    ])
    return {'id':s,'campaign_id':c}

async def workspace_scenario(d,u,s):
    row=await d.one('SELECT s.id,s.campaign_id,s.title,s.instructions AS description,s.max_turns,s.max_context_chars,s.no_limit,c.status,c.is_public FROM scenarios s JOIN campaigns c ON c.id=s.campaign_id WHERE s.id=?',s)
    if not row: fail(404,'Scenario not found.')
    await campaign(d,u,row['campaign_id'])
    return row

@app.get('/api/workspace/scenarios/{s}')
async def workspace_detail(req:Request,s:str,u=Depends(current)):
    d=db(req);row=await workspace_scenario(d,u,s);c=row['campaign_id']
    cols='id,label,provider,model_name,system_prompt' if u['role']=='admin' else 'id,label,provider,model_name'
    row['model_options']=await d.all('SELECT '+cols+' FROM models WHERE campaign_id=? AND enabled=1 ORDER BY label',c)
    args=[s];where=''
    if u['role']=='volunteer': where=' AND v.owner=?';args.append(u['email'])
    row['sessions']=await d.all("""SELECT v.id,v.owner,v.state,v.created_at,m.label AS model,
        (SELECT COUNT(*) FROM turns t WHERE t.conversation_id=v.id) AS turns,
        (SELECT COUNT(*) FROM findings f WHERE f.conversation_id=v.id) AS flags
        FROM conversations v JOIN models m ON m.id=v.model_id WHERE v.scenario_id=?"""+where+' ORDER BY v.created_at DESC LIMIT 500',*args)
    if u['role']!='volunteer':
        row['emails']=await d.all("SELECT a.email FROM memberships m JOIN users a ON a.email=m.email WHERE m.campaign_id=? AND a.role='volunteer' ORDER BY a.email",c)
    return row

@app.post('/api/workspace/scenarios/{s}/assign')
async def workspace_assign(req:Request,s:str,p:WorkspaceEmail,u=Depends(current)):
    role(u,'admin');d=db(req);row=await workspace_scenario(d,u,s)
    items=await workspace_assignment(d,u,row['campaign_id'],[p.email])
    await d.batch([*items,audit(u,'scenario.assign',s)])
    return {'ok':True}

@app.post('/api/workspace/volunteers')
async def workspace_add_volunteer(req:Request,p:WorkspaceEmail,u=Depends(current)):
    role(u,'admin');d=db(req);e=normalize_email(p.email)
    existing=await d.one('SELECT role,active FROM users WHERE email=?',e)
    if existing and existing['role']!='volunteer': fail(409,'Email belongs to a different account role.')
    if await d.one("SELECT 1 FROM volunteer_access WHERE email=? AND status='blacklisted'",e):fail(409,'Unblock the email before approval.')
    await approve_volunteer(d,u,e)
    return {'ok':True}

@app.post('/api/workspace/conversations/{c}/flag')
async def workspace_flag(req:Request,c:str,p:WorkspaceFlag,u=Depends(current)):
    role(u,'volunteer');d=db(req);v=await conversation(d,u,c)
    turn=await d.one('SELECT id FROM turns WHERE id=? AND conversation_id=? AND status=\'complete\'',p.turn_id,c)
    if not turn: fail(404,'Response not found.')
    existing=await d.one('SELECT id FROM findings WHERE conversation_id=? AND turn_id=? AND author=?',c,p.turn_id,u['email'])
    if existing: return {'id':existing['id']}
    id=uid()
    await d.batch([("INSERT INTO findings(id,conversation_id,turn_id,author,category,severity,explanation,expected) SELECT ?,?,?,?,'other','moderate',?,'' WHERE NOT EXISTS(SELECT 1 FROM findings WHERE conversation_id=? AND turn_id=? AND author=?)",(id,c,p.turn_id,u['email'],p.reason.strip() or 'Flagged for reviewer attention.',c,p.turn_id,u['email'])),audit(u,'response.flag',id)])
    return {'ok':True}


@app.get('/api/workspace/model-catalog')
async def workspace_catalog(req:Request,u=Depends(current)):
    role(u,'admin')
    d=db(req)
    rows=await d.all("SELECT provider,enabled,cipher!='' AS configured FROM api_providers ORDER BY provider")
    result=[{'provider':'demo','status':'connected','models':[{'id':demo.DEMO_ID,'name':'Demo (local, free)'}]}]
    for r in rows:
        models=await d.all("SELECT model_name AS id,label AS name FROM api_models WHERE provider=? AND enabled=1 ORDER BY label",r['provider'])
        active=bool(r['enabled'] and r['configured'])
        result.append({'provider':r['provider'],'status':'connected' if active else 'not_configured','models':models if active else []})
    return result


# Verified identity is not authorization. Only this narrow route accepts unapproved identities.
@app.post('/api/access/request')
async def request_access(req:Request):
    email=req.scope.get('brite_email')
    if not email:fail(401,'Verify your email first.')
    e=normalize_email(email);d=db(req)
    user=await d.one('SELECT role,active FROM users WHERE email=?',e)
    record=await d.one('SELECT status FROM volunteer_access WHERE email=?',e)
    if user and user['active'] and (not record or record['status']=='approved'):return {'status':'approved'}
    if record and record['status'] in ('blacklisted','rejected'):return {'status':record['status']}
    await d.run("""INSERT INTO volunteer_access(email,status) VALUES(?,'pending')
       ON CONFLICT(email) DO UPDATE SET status='pending',updated_at=CURRENT_TIMESTAMP WHERE status='removed'""",e)
    record=await d.one('SELECT status FROM volunteer_access WHERE email=?',e)
    return {'status':record['status']}

async def approve_volunteer(d,u,e):
    # Conditional SQL prevents a concurrent blacklist being silently overwritten.
    await d.batch([
      ("""INSERT INTO volunteer_access(email,status,decided_by) VALUES(?,'approved',?)
        ON CONFLICT(email) DO UPDATE SET status='approved',decided_by=excluded.decided_by,updated_at=CURRENT_TIMESTAMP WHERE status!='blacklisted'""",(e,u['email'])),
      ("""INSERT INTO users(email,role,active,trained) SELECT ?,'volunteer',1,0 WHERE EXISTS(SELECT 1 FROM volunteer_access WHERE email=? AND status='approved')
        ON CONFLICT(email) DO UPDATE SET active=1 WHERE role='volunteer'""",(e,e)),
      audit(u,'volunteer.approve',e)
    ])

class AccessDecision(BaseModel):
    email: str = Field(min_length=3,max_length=254)
    action: Literal['approve','reject','remove','blacklist','unblock']

@app.get('/api/workspace/access-requests')
async def access_requests(req:Request,u=Depends(current)):
    role(u,'admin')
    return await db(req).all('SELECT * FROM volunteer_access ORDER BY updated_at DESC LIMIT 500')

@app.post('/api/workspace/access-decision')
async def access_decision(req:Request,p:AccessDecision,u=Depends(current)):
    role(u,'admin');d=db(req);e=normalize_email(p.email)
    user=await d.one('SELECT role,active FROM users WHERE email=?',e)
    if user and user['role']!='volunteer':fail(409,'Administrator and reviewer accounts are managed separately.')
    record=await d.one('SELECT status FROM volunteer_access WHERE email=?',e)
    if p.action=='approve':
        if record and record['status']=='blacklisted':fail(409,'Unblock before approving.')
        await approve_volunteer(d,u,e)
    elif p.action=='unblock':
        if not record or record['status']!='blacklisted':fail(409,'Email is not blacklisted.')
        await write(d,u,'volunteer.unblock',e,"UPDATE volunteer_access SET status='removed',updated_at=CURRENT_TIMESTAMP,decided_by=? WHERE email=? AND status='blacklisted'",u['email'],e)
    else:
        status={'reject':'rejected','remove':'removed','blacklist':'blacklisted'}[p.action]
        if record and record['status']=='blacklisted' and p.action!='blacklist':fail(409,'Unblock first.')
        await d.batch([
          ("UPDATE users SET active=0 WHERE email=? AND role='volunteer'",(e,)),
          ("DELETE FROM memberships WHERE email=?",(e,)),
          ("""INSERT INTO volunteer_access(email,status,decided_by) VALUES(?,?,?)
            ON CONFLICT(email) DO UPDATE SET status=excluded.status,decided_by=excluded.decided_by,updated_at=CURRENT_TIMESTAMP WHERE status!='blacklisted' OR excluded.status='blacklisted'""",(e,status,u['email'])),
          audit(u,'volunteer.'+p.action,e)
        ])
    return {'ok':True}

class SafetyInput(BaseModel):
    enabled: bool = Field(strict=True)

@app.get('/api/workspace/safety')
async def safety_status(req:Request,u=Depends(current)):
    role(u,'admin');d=db(req)
    settings=await d.one('SELECT enabled FROM safety_settings WHERE id=1')
    usage=await d.one("SELECT * FROM model_monthly_usage WHERE month=strftime('%Y-%m','now')")
    return {'enabled':bool(settings['enabled']),'monthly_requests':usage['requests'] if usage else 0,'monthly_request_limit':1000,'input_chars':usage['input_chars'] if usage else 0,'reserved_output_tokens':usage['output_token_allowance'] if usage else 0,'reserved_input_bytes':usage['reserved_input_bytes'] if usage else 0,'monthly_input_byte_limit':2000000,'monthly_output_token_limit':512000}

@app.put('/api/workspace/safety')
async def safety_update(req:Request,p:SafetyInput,u=Depends(current)):
    role(u,'admin')
    await write(db(req),u,'model.safety_toggle','global','UPDATE safety_settings SET enabled=? WHERE id=1',int(p.enabled))
    return {'enabled':p.enabled}


# Shared provider registry, server-only credentials and model pricing.
def price_micros(input_tokens,output_tokens,input_cents,output_cents):
    return (input_tokens*input_cents+output_tokens*output_cents+99)//100

async def registered_model(d,provider,name):
    return await d.one("""SELECT p.cipher,p.revision AS provider_revision,m.revision AS model_revision,m.input_cents,m.output_cents
      FROM api_providers p JOIN api_models m ON m.provider=p.provider
      WHERE p.provider=? AND m.model_name=? AND p.enabled=1 AND m.enabled=1 AND p.cipher!=''""",provider,name)

class ProviderConfig(BaseModel):
    api_key: str | None = Field(default=None,min_length=8,max_length=500)
    enabled: bool = Field(strict=True)
    monthly_requests: int = Field(ge=1,le=1000,strict=True)
    budget_cents: int = Field(ge=1,le=100000,strict=True)
    remove_key: bool = Field(default=False,strict=True)

class RegisteredModel(BaseModel):
    provider: Literal['openai','anthropic']
    model_name: str = Field(min_length=1,max_length=200,pattern=r'^[A-Za-z0-9._:/-]+$')
    label: str = Field(min_length=1,max_length=200)
    input_cents: int = Field(ge=1,le=100000,strict=True)
    output_cents: int = Field(ge=1,le=100000,strict=True)
    enabled: bool = Field(default=True,strict=True)

class BudgetInput(BaseModel):
    budget_cents: int = Field(ge=1,le=100000,strict=True)

@app.get('/api/workspace/settings')
async def registry_settings(req:Request,u=Depends(current)):
    role(u,'admin');d=db(req)
    providers_rows=await d.all("""SELECT p.provider,p.enabled,p.cipher!='' AS configured,p.monthly_requests,p.budget_micros,
       (SELECT COUNT(*) FROM api_cost c WHERE c.provider=p.provider AND c.month=strftime('%Y-%m','now')) AS used_requests,
       COALESCE((SELECT SUM(c.cost_micros) FROM api_cost c WHERE c.provider=p.provider AND c.month=strftime('%Y-%m','now')),0) AS used_micros FROM api_providers p ORDER BY p.provider""")
    models=await d.all("""SELECT a.provider,a.model_name,a.label,a.input_cents,a.output_cents,a.enabled,
       (SELECT COUNT(*) FROM models m WHERE m.provider=a.provider AND m.model_name=a.model_name) AS scenarios,
       COALESCE((SELECT SUM(c.cost_micros) FROM api_cost c WHERE c.provider=a.provider AND c.model_name=a.model_name),0) AS cost_micros
       FROM api_models a ORDER BY provider,label""")
    total=await d.one("""SELECT COALESCE(SUM(cost_micros),0) AS total_micros,
       COALESCE(SUM(CASE WHEN status='reported' THEN cost_micros ELSE 0 END),0) AS reported_micros,
       COALESCE(SUM(CASE WHEN status!='reported' THEN cost_micros ELSE 0 END),0) AS estimated_micros,
       COALESCE(SUM(CASE WHEN month=strftime('%Y-%m','now') THEN cost_micros ELSE 0 END),0) AS monthly_micros,
       COUNT(*) AS requests FROM api_cost""")
    budget=await d.one('SELECT budget_micros FROM api_budget WHERE id=1')
    return {'providers':providers_rows,'models':models,'cost':total,'budget_micros':budget['budget_micros'],'vault_ready':bool(getattr(req.scope['brite_env'],'BRITE_VAULT_KEY',''))}

@app.put('/api/workspace/settings/providers/{provider}')
async def provider_update(req:Request,provider:Literal['openai','anthropic'],p:ProviderConfig,u=Depends(current)):
    role(u,'admin');d=db(req);env=req.scope['brite_env']
    if p.remove_key and p.api_key:fail(422,'Choose key replacement or removal, not both.')
    old=await d.one('SELECT cipher FROM api_providers WHERE provider=?',provider)
    cipher=old['cipher']
    if p.remove_key:cipher=''
    elif p.api_key:
        if not p.api_key.strip() or p.api_key!=p.api_key.strip():fail(422,'Enter a valid API key without surrounding whitespace.')
        try:cipher=await vault.seal(env,provider,p.api_key)
        except Exception:fail(503,'Secure credential storage unavailable.')
    if p.enabled and not cipher:fail(422,'Add an API key before enabling this provider.')
    await write(d,u,'api.provider_update',provider,'UPDATE api_providers SET cipher=?,enabled=?,monthly_requests=?,budget_micros=?,revision=revision+1 WHERE provider=?',cipher,int(p.enabled and not p.remove_key),p.monthly_requests,p.budget_cents*10000,provider)
    return {'ok':True}

@app.get('/api/workspace/settings/discover/{provider}')
async def registry_discover(req:Request,provider:Literal['openai','anthropic'],u=Depends(current)):
    role(u,'admin');d=db(req);r=await d.one('SELECT cipher FROM api_providers WHERE provider=?',provider)
    if not r['cipher']:fail(409,'Add an API key first.')
    try:
        key=await vault.unseal(req.scope['brite_env'],provider,r['cipher'])
        env=SimpleNamespace(**{('OPENAI_API_KEY' if provider=='openai' else 'ANTHROPIC_API_KEY'):key})
        return {'models':await providers.catalog(env,provider)}
    except Exception:fail(503,'Provider discovery failed. Check key and model-list permission.')

@app.put('/api/workspace/settings/models')
async def model_register(req:Request,p:RegisteredModel,u=Depends(current)):
    role(u,'admin');d=db(req)
    if p.model_name==demo.DEMO_ID:fail(422,'Reserved demo model ID.')
    if not p.label.strip():fail(422,'Enter a model label.')
    if not await d.one("SELECT 1 FROM api_providers WHERE provider=? AND cipher!=''",p.provider):fail(409,'Add the provider API key first.')
    await write(d,u,'api.model_register',p.provider+':'+p.model_name,"""INSERT INTO api_models(provider,model_name,label,input_cents,output_cents,enabled) VALUES(?,?,?,?,?,?)
    ON CONFLICT(provider,model_name) DO UPDATE SET label=excluded.label,input_cents=excluded.input_cents,output_cents=excluded.output_cents,enabled=excluded.enabled,revision=revision+1""",p.provider,p.model_name,p.label.strip(),p.input_cents,p.output_cents,int(p.enabled))
    return {'ok':True}

@app.put('/api/workspace/settings/budget')
async def budget_update(req:Request,p:BudgetInput,u=Depends(current)):
    role(u,'admin');await write(db(req),u,'api.budget_update','global','UPDATE api_budget SET budget_micros=? WHERE id=1',p.budget_cents*10000)
    return {'ok':True}


@app.get('/api/auth-config')
async def auth_config(req:Request):
    env=req.scope['brite_env']
    return {'mode':workos.mode(env),'ready':workos.ready(env),'signed_in':bool(req.scope.get('brite_email'))}

@app.get('/auth/workos/start')
async def workos_start(req:Request):
    return await workos.start(req,req.scope['brite_env'])

@app.get('/auth/workos/callback')
async def workos_callback(req:Request):
    return await workos.finish(req,req.scope['brite_env'])

@app.post('/api/auth/logout')
async def workos_logout(req:Request):
    return await workos.logout(req,req.scope['brite_env'])
