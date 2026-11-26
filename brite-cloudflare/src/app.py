import asyncio,csv,io,json,uuid
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel,Field
from .db import DB
from . import providers
app=FastAPI(title='BRITE | Red Teaming',version='0.2.0',docs_url=None,redoc_url=None,openapi_url=None)

def uid(): return str(uuid.uuid4())
def fail(code,msg): raise HTTPException(code,msg)
def db(req): return DB(req.scope['brite_env'].DB)
async def current(req:Request):
    email=req.scope.get('brite_email')
    if not email: fail(401,'Sign in through Cloudflare Access.')
    user=await db(req).one('SELECT email,role,trained FROM users WHERE email=? AND active=1',email.lower())
    if not user: fail(403,'Your account has not been approved.')
    return user

def role(user,*roles):
    if user['role'] not in roles: fail(403,'Insufficient permissions.')
async def campaign(d,u,c):
    row=await d.one('SELECT * FROM campaigns WHERE id=?',c)
    if not row: fail(404,'Campaign not found.')
    if u['role']!='admin' and not await d.one('SELECT 1 FROM memberships WHERE campaign_id=? AND email=?',c,u['email']): fail(404,'Campaign not found.')
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
        if origin and origin!=expected: return Response('Origin not allowed',403)
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
async def health(): return {'ok':True}
@app.get('/api/me')
async def me(u=Depends(current)): return u
@app.get('/api/users')
async def users(req:Request,u=Depends(current)):
    role(u,'admin'); return await db(req).all('SELECT * FROM users ORDER BY email LIMIT 500')
@app.put('/api/users')
async def put_user(req:Request,p:UserInput,u=Depends(current)):
    role(u,'admin'); email=p.email.lower()
    if email==u['email'] and (p.role!='admin' or not p.active): fail(409,'Cannot remove your own administrator access.')
    await write(db(req),u,'user.upsert',email,'INSERT INTO users(email,role,active,trained) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET role=excluded.role,active=excluded.active,trained=excluded.trained',email,p.role,int(p.active),int(p.trained));return {'email':email}
@app.post('/api/training/acknowledge')
async def training(req:Request,p:TrainingInput,u=Depends(current)):
    role(u,'volunteer'); await write(db(req),u,'training.acknowledge',u['email'],'UPDATE users SET trained=1 WHERE email=?',u['email']);return {'trained':True}
@app.get('/api/campaigns')
async def campaigns(req:Request,u=Depends(current)):
    d=db(req)
    if u['role']=='admin': return await d.all('SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 200')
    return await d.all('SELECT c.* FROM campaigns c JOIN memberships m ON c.id=m.campaign_id WHERE m.email=? ORDER BY c.created_at DESC LIMIT 200',u['email'])
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
@app.get('/api/conversations/{c}')
async def read_conversation(req:Request,c:str,u=Depends(current)):
    d=db(req);row=await conversation(d,u,c);row.pop('model_snapshot',None)
    row['turns']=await d.all('SELECT * FROM turns WHERE conversation_id=? ORDER BY seq',c)
    row['tasks']=await d.all('SELECT t.*, CASE WHEN x.task_id IS NULL THEN 0 ELSE 1 END AS completed FROM tasks t LEFT JOIN completions x ON x.task_id=t.id AND x.conversation_id=? WHERE t.scenario_id=?',c,row['scenario_id'])
    row['findings']=await d.all('SELECT f.*,r.verdict,r.feedback FROM findings f LEFT JOIN reviews r ON r.finding_id=f.id WHERE f.conversation_id=? ORDER BY f.created_at',c)
    return row
@app.post('/api/conversations/{c}/turns')
async def send(req:Request,c:str,p:PromptInput,u=Depends(current)):
    d=db(req);row=await own_open(d,u,c);model=json.loads(row['model_snapshot']);env=req.scope['brite_env']
    if not getattr(env,'OPENAI_API_KEY' if model['provider']=='openai' else 'ANTHROPIC_API_KEY','') and not req.scope.get('brite_test_provider'):fail(503,'AI provider is not configured.')
    rows=await d.all('SELECT seq,prompt,response,status FROM turns WHERE conversation_id=? ORDER BY seq',c)
    if len(rows)>=25:fail(409,'Pilot limit: 25 turns per conversation.')
    if any(r['status']=='pending' for r in rows):fail(409,'A response is already in progress.')
    history=[]
    for r in rows:
        if r['status']=='complete':history.extend([{'role':'user','content':r['prompt']},{'role':'assistant','content':r['response']}])
    history.append({'role':'user','content':p.prompt})
    id=uid();seq=rows[-1]['seq']+1 if rows else 1
    # Atomic reservation: simultaneous sends cannot reserve the same sequence or another pending turn.
    try:
        await d.run('INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES(?,?,?,?,?)',id,c,seq,p.prompt,'pending')
    except Exception:fail(409,'Unable to reserve turn; refresh and retry.')
    def event(kind,**data):return 'data: '+json.dumps({'type':kind,**data})+'\n\n'
    source=req.scope.get('brite_test_provider') or providers.chunks
    async def stream():
        text='';yield event('start',turn_id=id)
        try:
            async for piece in source(model,history,env):
                text+=piece
                if len(text)>100000: raise RuntimeError('Response too large')
                yield event('delta',text=piece)
            changed=await d.run("UPDATE turns SET response=?,status='complete' WHERE id=? AND status='pending'",text,id)
            if changed!=1:raise RuntimeError('Turn expired')
            yield event('done',turn_id=id)
        except (Exception,asyncio.CancelledError) as exc:
            try:await d.run("UPDATE turns SET response=?,status='failed',error='Stream interrupted or provider failed' WHERE id=? AND status='pending'",text,id)
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
    return await DB(env.DB).run("UPDATE turns SET status='failed',error='Interrupted response (timeout)' WHERE status='pending' AND created_at < datetime('now','-10 minutes')")
