"""Deploy a packaged BRITE pilot with Cloudflare's official multipart upload API.
Token is read only from environment or an interactive hidden prompt.
This command does not modify Access policies or create databases.
"""
import base64,getpass,hashlib,json,mimetypes,os,sys,zipfile
from pathlib import Path
import httpx

def required(k):
    v=os.environ.get(k)
    if not v: raise SystemExit('Missing configuration: '+k)
    return v

def run():
    account=required('CLOUDFLARE_ACCOUNT_ID')
    db=required('BRITE_D1_ID')
    issuer=required('BRITE_ACCESS_ISSUER')
    aud=required('BRITE_ACCESS_AUD')
    origin=required('BRITE_ORIGIN')
    if not origin.startswith('https://brite-redteam-api.') or not origin.endswith('.workers.dev'):
        raise SystemExit('This command targets the dedicated pilot only.')
    token=os.environ.get('CLOUDFLARE_API_TOKEN') or getpass.getpass('Scoped Cloudflare API token: ')
    root=Path(__file__).resolve().parent
    package=Path(sys.argv[1]) if len(sys.argv)>1 else None
    if package is None: raise SystemExit('Usage: python deploy.py PACKAGE.zip')
    with zipfile.ZipFile(package) as z:
        names=[n for n in z.namelist() if not n.endswith('/')]
        assets={n.removeprefix('frontend/dist/'):z.read(n) for n in names if n.startswith('frontend/dist/')}
        vendor={n:z.read(n) for n in names if n.startswith('python_modules/')}
    if not assets.get('index.html') or not vendor: raise SystemExit('Build artifact missing frontend or Python modules')
    source={f'src/{p.name}':p.read_bytes() for p in (root/'src').glob('*.py')}
    if 'src/access.py' not in source or 'src/entry.py' not in source: raise SystemExit('Missing updated source')
    base=f'https://api.cloudflare.com/client/v4/accounts/{account}'
    script='/workers/scripts/brite-redteam-api'
    with httpx.Client(timeout=120) as client:
        def call(method,path,auth=token,**kw):
            resp=client.request(method,base+path,headers={'Authorization':'Bearer '+auth},**kw)
            try: body=resp.json()
            except Exception: raise RuntimeError(f'Cloudflare HTTP {resp.status_code} for {method} {path}')
            if resp.is_error or not body.get('success'):
                # Do not print response data that could contain credentials.
                codes=[e.get('code') for e in body.get('errors',[]) if isinstance(e,dict)]
                raise RuntimeError(f'Cloudflare HTTP {resp.status_code} for {method} {path}; codes {codes}')
            return body['result']
        # Fail before uploads if existing Access application is absent.
        apps=call('GET','/access/apps')
        host=origin.removeprefix('https://')
        if not any(a.get('domain')==host and a.get('aud')==aud for a in apps):
            raise SystemExit('Expected Access application not found; refusing to deploy.')
        manifest={}; hashed={}
        for name,data in assets.items():
            encoded=base64.b64encode(data)
            digest=hashlib.sha256(encoded+Path(name).suffix.lstrip('.').encode()).hexdigest()[:32]
            manifest['/'+name]={'hash':digest,'size':len(data)}
            hashed[digest]=(None,encoded,mimetypes.guess_type(name)[0] or 'application/octet-stream')
        session=call('POST',script+'/assets-upload-session',json={'manifest':manifest})
        completion=session['jwt']
        for bucket in session.get('buckets',[]):
            result=call('POST','/workers/assets/upload?base64=true',auth=session['jwt'],files={h:hashed[h] for h in bucket})
            if result and result.get('jwt'): completion=result['jwt']
        bindings=[{'name':'DB','type':'d1','id':db}]
        bindings.extend({'name':name,'type':'plain_text','text':val} for name,val in {'APP_ORIGIN':origin,'ACCESS_ISSUER':issuer,'ACCESS_AUD':aud}.items())
        meta={'main_module':'src/entry.py','compatibility_date':'2026-11-26','compatibility_flags':['python_workers'],'bindings':bindings,'keep_bindings':['secret_text'],'assets':{'jwt':completion,'config':{'not_found_handling':'single-page-application','run_worker_first':['/api/*']}}}
        parts=[('metadata',(None,json.dumps(meta),'application/json'))]
        for name,data in source.items(): parts.append((name,(name,data,'text/x-python')))
        for name,data in vendor.items():
            mime='application/javascript+module' if name.startswith('python_modules/workers/') and Path(name).suffix in ('.js','.mjs') else 'application/octet-stream'
            parts.append((name,(name,data,mime)))
        call('PUT',script,files=parts)
        call('POST',script+'/subdomain',json={'enabled':True,'previews_enabled':False})
        call('PUT',script+'/schedules',json=[{'cron':'*/15 * * * *'}])
        print('Upload complete. Verify Access login, /api/me, campaign CRUD and synthetic model calls at '+origin)

if __name__=='__main__': run()
