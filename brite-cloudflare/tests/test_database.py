import asyncio,sqlite3
from pathlib import Path
import pytest
from src.db import DB,native
from tests.local_runtime import LocalD1
MIGRATIONS=Path(__file__).resolve().parents[1]/'migrations'

def test_fresh_and_incremental_migrations():
    c=sqlite3.connect(':memory:')
    c.execute('PRAGMA foreign_keys=ON')
    files=sorted(MIGRATIONS.glob('*.sql'))
    assert len(files)>=3
    c.executescript(files[0].read_text())
    c.execute("INSERT INTO campaigns(id,title,description) VALUES('old','Old','Original')")
    for f in files[1:]:c.executescript(f.read_text())
    assert c.execute("SELECT title,is_public FROM campaigns WHERE id='old'").fetchone()==('Old',0)
    assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not c.execute('PRAGMA foreign_key_check').fetchall()

@pytest.fixture
def d():
    d=LocalD1()
    d.conn.executescript("""
    INSERT INTO users(email,role) VALUES('a@example.org','volunteer');
    INSERT INTO campaigns(id,title,description) VALUES('c','C','Test');
    INSERT INTO scenarios(id,campaign_id,title,instructions) VALUES('s','c','S','Test');
    INSERT INTO models(id,campaign_id,label,provider,model_name) VALUES('m','c','M','openai','gpt');
    INSERT INTO conversations(id,campaign_id,scenario_id,model_id,owner,model_snapshot) VALUES('v','c','s','m','a@example.org','{}');
    """)
    yield d
    d.conn.close()

@pytest.mark.parametrize('sql',[
 "INSERT INTO users(email,role) VALUES('b@example.org','superadmin')",
 "INSERT INTO memberships(campaign_id,email) VALUES('missing','a@example.org')",
 "INSERT INTO models(id,campaign_id,label,provider,model_name) VALUES('x','c','M','unknown','x')",
 "UPDATE campaigns SET is_public=2 WHERE id='c'",
 "INSERT INTO model_daily_usage(email,day,requests) VALUES('a@example.org','2026-01-01',-1)",
 "INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES('x','missing',1,'test','pending')",
])
def test_database_constraints(d,sql):
    with pytest.raises(sqlite3.IntegrityError):d.conn.execute(sql)
    d.conn.rollback()

def test_only_one_pending_and_unique_sequence(d):
    d.conn.execute("INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES('x','v',1,'test','pending')")
    d.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):d.conn.execute("INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES('y','v',2,'test','pending')")
    d.conn.rollback()
    d.conn.execute("UPDATE turns SET status='complete' WHERE id='x'")
    d.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):d.conn.execute("INSERT INTO turns(id,conversation_id,seq,prompt,status) VALUES('y','v',1,'test','complete')")
    d.conn.rollback()
    assert d.conn.execute('SELECT COUNT(*) FROM turns').fetchone()[0]==1

def test_adapter_parameter_binding_and_rollback(d):
    async def go():
        db=DB(d)
        assert (await db.one('SELECT email FROM users WHERE email=?','a@example.org'))['email']=='a@example.org'
        assert await db.one('SELECT email FROM users WHERE email=?',"' OR 1=1 --") is None
        assert len(await db.all('SELECT * FROM users'))==1
        with pytest.raises(sqlite3.IntegrityError):
            await db.batch([('INSERT INTO memberships VALUES(?,?)',('c','a@example.org')),('INSERT INTO memberships VALUES(?,?)',('missing','a@example.org'))])
        assert not await db.all('SELECT * FROM memberships')
        assert await db.run('UPDATE users SET trained=1 WHERE email=?','a@example.org')==1
    asyncio.run(go())

def test_native_conversion():
    class Proxy:
        def to_py(self):return {'converted':True}
    assert native(Proxy())=={'converted':True}
    assert native(None) is None
