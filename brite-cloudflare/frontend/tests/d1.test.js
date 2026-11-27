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
 await db.prepare("INSERT INTO users(email,role) VALUES(?,?)").bind('ci@example.org','volunteer').run();
 assert.equal((await db.prepare('SELECT role FROM users WHERE email=?').bind('ci@example.org').first()).role,'volunteer');
 assert.equal(await db.prepare('SELECT email FROM users WHERE email=?').bind("' OR 1=1 --").first(),null);
 await assert.rejects(()=>db.batch([db.prepare("INSERT INTO campaigns(id,title,description) VALUES('rollback','Test','Test')"),db.prepare("INSERT INTO memberships(campaign_id,email) VALUES('missing','ci@example.org')")]));
 assert.equal(await db.prepare("SELECT id FROM campaigns WHERE id='rollback'").first(),null);
 assert.equal((await db.prepare('PRAGMA foreign_key_check').all()).results.length,0);
 }finally{await mf.dispose();}
});
