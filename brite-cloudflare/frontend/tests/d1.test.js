import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
test('actual local D1 binding: migrations, parameter binding, rollback, constraints',async()=>{
 const mf=new Miniflare({modules:true,script:'export default {fetch(){return new Response("CI")}}',compatibilityDate:'2025-01-01',d1Databases:['DB']});
 try{
 const db=await mf.getD1Database('DB');
 const files=(await readdir('../migrations')).filter(x=>x.endsWith('.sql')).sort();
 for(const file of files){
  const sql=await readFile('../migrations/'+file,'utf8');
  const statements=sql.split(';').map(x=>x.trim()).filter(x=>x&&!x.startsWith('PRAGMA foreign_keys'));
  await db.batch(statements.map(x=>db.prepare(x)));
 }
 await db.prepare("INSERT INTO campaigns(id,title,description) VALUES('limits','Test','Test')").run();
 await db.prepare("INSERT INTO scenarios(id,campaign_id,title,instructions) VALUES('s','limits','Test','Test')").run();
 const limits=await db.prepare("SELECT max_turns,max_context_chars FROM scenarios WHERE id='s'").first();
 assert.equal(limits.max_turns,25);assert.equal(limits.max_context_chars,80000);
 await assert.rejects(()=>db.prepare("UPDATE scenarios SET max_turns=26 WHERE id='s'").run());
 await db.prepare("INSERT INTO users(email,role) VALUES(?,?)").bind('ci@example.org','volunteer').run();
 assert.equal((await db.prepare('SELECT role FROM users WHERE email=?').bind('ci@example.org').first()).role,'volunteer');
 assert.equal(await db.prepare('SELECT email FROM users WHERE email=?').bind("' OR 1=1 --").first(),null);
 await assert.rejects(()=>db.batch([db.prepare("INSERT INTO campaigns(id,title,description) VALUES('rollback','Test','Test')"),db.prepare("INSERT INTO memberships(campaign_id,email) VALUES('missing','ci@example.org')")]));
 assert.equal(await db.prepare("SELECT id FROM campaigns WHERE id='rollback'").first(),null);
 assert.equal((await db.prepare('PRAGMA foreign_key_check').all()).results.length,0);
 }finally{await mf.dispose();}
});
