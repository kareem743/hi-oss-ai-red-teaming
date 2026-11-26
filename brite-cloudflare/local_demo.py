"""Local-only demo: synthetic model response and explicit fixed persona. NEVER deploy."""
import os
from tests.local_runtime import LocalD1,runtime
import uvicorn
p=LocalD1('demo.sqlite');p.conn.execute("INSERT OR IGNORE INTO users(email,role,trained) VALUES('admin@example.org','admin',1)");p.conn.commit()
identity=os.environ.get('DEMO_USER','admin@example.org')
if __name__=='__main__':uvicorn.run(runtime(p,identity),host='127.0.0.1',port=8000)
