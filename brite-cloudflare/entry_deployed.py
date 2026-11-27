"""Same-host pilot entrypoint serving packaged React build files."""
import base64
import gzip
from urllib.parse import urlsplit
from workers import WorkerEntrypoint, Response, asgi
from src.app import app, reap
from src.access import verified_email
from src.ui_assets import ASSETS

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlsplit(request.url).path
        if not path.startswith('/api/'):
            if request.method not in ('GET', 'HEAD'):
                return Response('Method not allowed', status=405, headers={'Allow': 'GET, HEAD'})
            asset = ASSETS.get('/index.html' if path == '/' else path)
            if asset is None:
                return Response('Not found', status=404)
            mime, encoded = asset
            body = gzip.decompress(base64.b64decode(encoded)).decode('utf-8')
            headers = {'Content-Type': mime, 'Cache-Control': 'no-store',
                       'X-Content-Type-Options': 'nosniff', 'Vary': 'Accept-Encoding',
                       'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}
            return Response(None if request.method == 'HEAD' else body, headers=headers)
        env = self.env
        email = await verified_email(request, env)
        async def scoped(scope, receive, send):
            scope['brite_env'] = env
            scope['brite_email'] = email
            await app(scope, receive, send)
        return await asgi.fetch(scoped, request, env)

    async def scheduled(self, controller, env, ctx):
        await reap(self.env)
