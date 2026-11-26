"""Cloudflare adapter. Trusted identity is provided by Access, never a header."""
import asgi
from workers import WorkerEntrypoint
from src.app import app,reap

class Default(WorkerEntrypoint):
    async def fetch(self,request):
        access=getattr(self.ctx,'access',None)
        identity=await access.getIdentity() if access is not None else None
        email=str(identity.email).lower() if identity is not None and getattr(identity,'email',None) else None
        env=self.env
        async def scoped(scope,receive,send):
            scope['brite_env']=env;scope['brite_email']=email
            await app(scope,receive,send)
        return await asgi.fetch(scoped,request,self.env)
    async def scheduled(self,controller,env,ctx):
        await reap(env)
