import test from 'node:test';
import assert from 'node:assert/strict';
import {escapeHTML,eligibleVolunteers,filterSessions,toggleSelection,SSEParser,conversationAllowance} from '../src/helpers.js';
test('escape all HTML attribute and text metacharacters',()=>{
 assert.equal(escapeHTML('<img src=x onerror="alert(1)"> & \'x\''),'&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;x&#39;');
 assert.equal(escapeHTML(null),'');
});
test('only active approved volunteers are selectable; exclude assigned users',()=>{
 const u=[{email:'a',role:'volunteer',active:1},{email:'b',role:'volunteer',active:0},{email:'c',role:'admin',active:1},{email:'d',role:'volunteer',active:1}];
 assert.deepEqual(eligibleVolunteers(u,['a']).map(x=>x.email),['d']);
});
test('flagged and search filters combine without mutation',()=>{
 const rows=[{owner:'Alice@example.org',model:'GPT',flags:2},{owner:'Bob',model:'Claude',flags:0},{owner:'C',model:'GPT',flags:1}];
 assert.equal(filterSessions(rows,true,' ALICE ').length,1);
 assert.equal(filterSessions(rows,true,'Claude').length,0);
 assert.equal(filterSessions(rows,false,'gpt').length,2);
 assert.equal(rows.length,3);
});
test('selection is immutable, deduplicated and capped',()=>{
 const a=new Set(Array.from({length:20},(_,i)=>String(i)));
 assert.equal(toggleSelection(a,'0',true).size,20);
 assert.throws(()=>toggleSelection(a,'21',true),/at most 20/);
 assert.equal(toggleSelection(a,'0',false).size,19);assert.equal(a.size,20);
});
const enc=new TextEncoder();
test('SSE handles split UTF8, CRLF, multiple events and completion',()=>{
 const events=[];const p=new SSEParser(x=>events.push(x));
 const b=enc.encode('data: {"type":"start"}\r\n\r\ndata: {"type":"delta","text":"café"}\n\ndata: {"type":"done"}\n\n');
 for(const byte of b)p.push(Uint8Array.of(byte));
 p.finish();assert.equal(events[1].text,'café');
});
test('SSE rejects incomplete, malformed, duplicate completion and provider error',()=>{
 for(const [raw,pattern] of [['data: {"type":"start"}\n\n',/interrupted/],['data: broken\n\n',/Invalid/],['data: {"type":"done"}\n\n',/Invalid/],['data: {"type":"error","message":"Provider failed"}\n\n',/Provider failed/]]){
  const p=new SSEParser(()=>{});assert.throws(()=>{p.push(enc.encode(raw));p.finish();},pattern);
 }
});

test('conversation allowance stops at either limit and caps the next prompt',()=>{
 assert.equal(conversationAllowance({turns_remaining:0,context_chars_remaining:1000}).blocked,true);
 assert.equal(conversationAllowance({turns_remaining:2,context_chars_remaining:0}).blocked,true);
 assert.equal(conversationAllowance({turns_remaining:2,context_chars_remaining:120}).maxPrompt,120);
 assert.equal(conversationAllowance({turns_remaining:2,context_chars_remaining:20000}).maxPrompt,8000);
 assert.equal(conversationAllowance(null).blocked,true);
});
