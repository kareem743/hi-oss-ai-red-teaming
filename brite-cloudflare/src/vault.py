"""AES-256-GCM vault using the Workers Web Crypto runtime. No credentials in API responses."""
import base64
def _decode(value):
    return base64.b64decode(value,validate=True)
async def _key(env):
    from js import crypto,Object,Uint8Array
    from pyodide.ffi import to_js
    raw=_decode(str(env.BRITE_VAULT_KEY))
    if len(raw)!=32:raise RuntimeError('Invalid vault configuration')
    return await crypto.subtle.importKey('raw',Uint8Array.new(to_js(list(raw))),'AES-GCM',False,to_js(['encrypt','decrypt']))
async def seal(env,provider,secret):
    from js import crypto,Object,Uint8Array
    from pyodide.ffi import to_js
    nonce=crypto.getRandomValues(Uint8Array.new(12))
    aad=Uint8Array.new(to_js(list(('brite-vault-v1:'+provider).encode())))
    buf=Uint8Array.new(to_js(list(secret.encode())))
    algorithm=to_js({'name':'AES-GCM','iv':nonce,'additionalData':aad},dict_converter=Object.fromEntries)
    cipher=await crypto.subtle.encrypt(algorithm,await _key(env),buf)
    return 'v1.'+base64.b64encode(bytes(nonce.to_py())+bytes(Uint8Array.new(cipher).to_py())).decode()
async def unseal(env,provider,record):
    from js import crypto,Object,Uint8Array
    from pyodide.ffi import to_js
    if not record.startswith('v1.'):raise RuntimeError('Invalid vault record')
    raw=_decode(record[3:])
    if len(raw)<28:raise RuntimeError('Invalid vault record')
    def buf(x):return Uint8Array.new(to_js(list(x)))
    algorithm=to_js({'name':'AES-GCM','iv':buf(raw[:12]),'additionalData':buf(('brite-vault-v1:'+provider).encode())},dict_converter=Object.fromEntries)
    plain=await crypto.subtle.decrypt(algorithm,await _key(env),buf(raw[12:]))
    return bytes(Uint8Array.new(plain).to_py()).decode()
