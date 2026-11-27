// Pure, independently testable browser logic. Never render user/model content as HTML.
export const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const eligibleVolunteers=(users,excluded=[])=>users.filter(u=>u.role==='volunteer'&&u.active&&!excluded.includes(u.email));
export function filterSessions(sessions,flagged,search=''){
 const q=search.trim().toLowerCase();
 return sessions.filter(x=>(!flagged||x.flags>0)&&(!q||((x.owner||'')+' '+(x.model||'')).toLowerCase().includes(q)));
}
export function toggleSelection(previous,id,checked){
 const next=new Set(previous);
 if(checked){if(!next.has(id)&&next.size>=20)throw Error('Select at most 20 volunteers per scenario.');next.add(id);}
 else next.delete(id);
 return next;
}
export class SSEParser {
 constructor(onEvent){this.onEvent=onEvent;this.decoder=new TextDecoder();this.buffer='';this.done=false;this.started=false;}
 push(bytes){this.buffer+=this.decoder.decode(bytes,{stream:true});this.drain();}
 drain(){let match;while((match=/\r?\n\r?\n/.exec(this.buffer))!==null){
   const event=this.buffer.slice(0,match.index);this.buffer=this.buffer.slice(match.index+match[0].length);
   const data=event.split(/\r?\n/).filter(x=>x.startsWith('data:')).map(x=>x.slice(5).replace(/^ /,'')).join('\n');
   if(!data)continue;
   let p;try{p=JSON.parse(data)}catch{throw Error('Invalid model stream');}
   if(!p||typeof p!=='object'||this.done)throw Error('Invalid model stream');
   if(p.type==='error')throw Error(typeof p.message==='string'?p.message:'Model error');
   if(p.type==='start'){if(this.started)throw Error('Invalid model stream');this.started=true;}
   if(p.type==='delta'&&(!this.started||typeof p.text!=='string'))throw Error('Invalid model stream');
   if(p.type==='done'){if(!this.started)throw Error('Invalid model stream');this.done=true;}
   this.onEvent(p);
 }}
 finish(){this.buffer+=this.decoder.decode();this.drain();if(!this.done||this.buffer.trim())throw Error('Response interrupted. Refresh to inspect the saved conversation.');}
}

export function conversationAllowance(l){
 if(!l)return {blocked:true,reason:'Conversation limits unavailable. Reload to continue.',maxPrompt:0};
 if(l.no_limit)return {blocked:false,reason:'',maxPrompt:8000};
 if(l.turns_remaining<=0)return {blocked:true,reason:'Conversation turn limit reached.',maxPrompt:0};
 if(l.context_chars_remaining<=0)return {blocked:true,reason:'Conversation context limit reached.',maxPrompt:0};
 return {blocked:false,reason:'',maxPrompt:Math.min(8000,l.context_chars_remaining)};
}
