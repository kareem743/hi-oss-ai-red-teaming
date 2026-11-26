"""Generate the compressed static build module used for the pilot's same-host upload."""
import base64
import gzip
import json
import mimetypes
import pathlib
import sys
dist, out = map(pathlib.Path, sys.argv[1:3])
assets = {}
for file in sorted(dist.rglob('*')):
    if file.is_file():
        path = '/' + file.relative_to(dist).as_posix()
        mime = ('application/javascript' if file.suffix == '.js' else
                mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        if file.suffix in ('.js', '.css', '.html'):
            mime += '; charset=utf-8'
        assets[path] = [mime, base64.b64encode(gzip.compress(file.read_bytes(), mtime=0)).decode()]
assert '/index.html' in assets
out.write_text('ASSETS = ' + json.dumps(assets) + '\n')
