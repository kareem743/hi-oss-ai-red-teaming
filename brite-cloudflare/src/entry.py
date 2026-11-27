"""Cloudflare single-host adapter. Identity is derived only from a validated Access JWT."""
from workers import WorkerEntrypoint,asgi
from src.app import app,reap
from src.access import verified_email

class Default(WorkerEntrypoint):
    async def fetch(self,request):
        env=self.env
        email=await verified_email(request,env)
        async def scoped(scope,receive,send):
            scope['brite_env']=env;scope['brite_email']=email
            await app(scope,receive,send)
        return await asgi.fetch(scoped,request,env)
    async def scheduled(self,controller,env,ctx):
        await reap(self.env)
