"""Local CI browser harness only; no deployment or real credentials."""
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from tests.local_runtime import LocalD1,runtime
import uvicorn
if os.environ.get('BRITE_CI_BROWSER')!='1':raise RuntimeError('CI harness only')
d=LocalD1()
d.conn.executescript("INSERT INTO users(email,role,trained) VALUES('admin@example.org','admin',1),('other@example.org','volunteer',0);")
# Cookie identity exists only in this test harness, never in production.
from src.app import app
from http.cookies import SimpleCookie
from starlette.responses import Response
from tests.local_runtime import fake_provider
from types import SimpleNamespace
env=SimpleNamespace(DB=d,APP_ORIGIN='http://127.0.0.1:8765',OPENAI_API_KEY='',ANTHROPIC_API_KEY='')
static=StaticFiles(directory=Path(__file__).resolve().parents[1]/'frontend'/'dist',html=True)
async def serve(scope,receive,send):
    if scope['type']=='lifespan':
        await app(scope,receive,send);return
    if not scope['path'].startswith('/api/'):
        await static(scope,receive,send);return
    cookie=SimpleCookie(dict(scope['headers']).get(b'cookie',b'').decode())
    scope['brite_email']=cookie['ci_email'].value if 'ci_email' in cookie else None
    scope['brite_env']=env
    scope['brite_test_provider']=fake_provider
    await app(scope,receive,send)
if __name__=='__main__':uvicorn.run(serve,host='127.0.0.1',port=8765)
