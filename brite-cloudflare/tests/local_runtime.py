"""SQLite test double for D1 bindings; not the Cloudflare runtime."""
import sqlite3,types,os
from pathlib import Path
from src.app import app
class Statement:
    def __init__(self,db,sql,args=()):self.db,self.sql,self.args=db,sql,args
    def bind(self,*args):return Statement(self.db,self.sql,args)
    async def first(self):
        r=self.db.conn.execute(self.sql,self.args).fetchone();return dict(r) if r else None
    async def all(self):return types.SimpleNamespace(results=[dict(x) for x in self.db.conn.execute(self.sql,self.args).fetchall()])
    async def run(self):
        c=self.db.conn.execute(self.sql,self.args);self.db.conn.commit();return types.SimpleNamespace(meta=types.SimpleNamespace(changes=c.rowcount))
class LocalD1:
    def __init__(self,path=':memory:'):
        self.conn=sqlite3.connect(path,check_same_thread=False);self.conn.row_factory=sqlite3.Row;self.conn.execute('PRAGMA foreign_keys=ON')
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():self.conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0001_pilot.sql').read_text())
        if 'is_public' not in [r[1] for r in self.conn.execute('PRAGMA table_info(campaigns)')]:self.conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0002_scenario_audience.sql').read_text())
        self.conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0003_model_limits.sql').read_text())
        if 'max_turns' not in [r[1] for r in self.conn.execute('PRAGMA table_info(scenarios)')]:self.conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0004_scenario_limits.sql').read_text())
        if 'no_limit' not in [r[1] for r in self.conn.execute('PRAGMA table_info(scenarios)')]:self.conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0005_optional_limits.sql').read_text())
        self.conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0006_access_security.sql').read_text())
    def prepare(self,sql):return Statement(self,sql)
    async def batch(self,stmts):
        with self.conn:
            for s in stmts:self.conn.execute(s.sql,s.args)
        return []
async def fake_provider(model,history,env):
    yield 'Synthetic demo response. ';yield 'This is not a live model result.'
def runtime(binding,identity='admin@example.org',mock=True):
    env=types.SimpleNamespace(DB=binding,APP_ORIGIN='http://localhost:5173',OPENAI_API_KEY='',ANTHROPIC_API_KEY='')
    async def local(scope,receive,send):
        scope['brite_env']=env;scope['brite_email']=identity
        if mock:scope['brite_test_provider']=fake_provider
        await app(scope,receive,send)
    return local
