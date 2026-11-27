import {test,expect} from '@playwright/test';
const base='http://127.0.0.1:8765';
async function persona(browser,email){
 const c=await browser.newContext();
 if(email)await c.addCookies([{name:'ci_email',value:email,url:base}]);
 return {c,p:await c.newPage()};
}
test('complete scenario workflow with isolated volunteer and flagged transcript',async({browser})=>{
 const {c:ac,p:a}=await persona(browser,'admin@example.org');
 const errors=[];a.on('pageerror',e=>errors.push(e.message));
 await a.goto(base);await expect(a.getByRole('heading',{name:'Scenarios',exact:true})).toBeVisible();
 await a.getByRole('button',{name:'Volunteers',exact:true}).click();
 await a.locator('#email').fill('volunteer@example.org');await a.getByRole('button',{name:'Approve',exact:true}).click();
 await expect(a.getByRole('cell',{name:'volunteer@example.org'})).toBeVisible();
 await a.getByRole('button',{name:'Create scenario',exact:true}).click();
 await a.locator('#title').fill('CI private scenario');
 await a.locator('#description').fill('Act as a fictional patient <img src=x onerror=alert(1)>');
 await a.getByRole('radio',{name:/Selected volunteers/}).check();
 await a.locator('#vol-search').fill('volunteer@example.org');
 await a.locator('[data-volunteer="volunteer@example.org"]').check();
 await expect(a.locator('#selected-count')).toHaveText('1 selected');
 await expect(a.locator('#catalog-state')).toContainText('No provider key configured');
 await a.locator('#model-name').fill('gpt-test');
 await a.locator('#max-turns').selectOption('1');
 await a.locator('#max-context').selectOption('2000');
 await a.getByRole('button',{name:/Create & publish/}).click();
 await expect(a.getByRole('heading',{name:'CI private scenario',exact:true})).toBeVisible();
 await expect(a.locator('.instructions')).toContainText('<img src=x onerror=alert(1)>');
 await expect(a.locator('.instructions img')).toHaveCount(0);
 const {c:vc,p:v}=await persona(browser,'volunteer@example.org');v.on('pageerror',e=>errors.push(e.message));
 await v.goto(base);await expect(v.getByRole('heading',{name:'My scenarios',exact:true})).toBeVisible();
 await expect(v.getByRole('button',{name:'Create scenario',exact:true})).toHaveCount(0);
 await v.getByRole('button',{name:/CI private scenario/}).click();
 await v.getByRole('button',{name:'Start new chat'}).click();
 await v.locator('dialog input[name="ack"]').check();
 await v.getByRole('button',{name:'Start chat',exact:true}).click();
 await v.locator('#prompt').fill('Fictional clinical question');
 await v.locator('#synthetic').check();
 await v.getByRole('button',{name:'Send message'}).click();
 await expect(v.locator('.message.assistant')).toContainText('Synthetic demo response.');
 await expect(v.getByText('Conversation turn limit reached.',{exact:true})).toBeVisible();
 await expect(v.getByRole('button',{name:'Send message'})).toHaveCount(0);
 await expect(v.getByRole('button',{name:'Finish chat'})).toBeVisible();
 await v.getByRole('button',{name:'Flag response',exact:true}).click();
 await v.locator('dialog textarea').fill('Potentially concerning example');
 await v.locator('dialog').getByRole('button',{name:'Flag response',exact:true}).click();
 await expect(v.locator('.message.flagged')).toContainText('Potentially concerning example');
 await v.getByRole('button',{name:'← Back to scenario'}).click();
 await expect(v.getByRole('button',{name:'Open chat'})).toBeVisible();
 const {c:oc,p:o}=await persona(browser,'other@example.org');await o.goto(base);
 await expect(o.getByText('No scenarios yet',{exact:true})).toBeVisible();
 await a.reload();await a.getByRole('button',{name:/CI private scenario/}).click();
 await a.getByRole('button',{name:/Flagged only/}).click();
 await expect(a.getByRole('cell',{name:'volunteer@example.org'})).toBeVisible();
 await a.getByRole('button',{name:'View transcript'}).click();
 await expect(a.locator('.message.flagged')).toContainText('Potentially concerning example');
 expect(errors).toEqual([]);
 await Promise.all([ac.close(),vc.close(),oc.close()]);
});
test('unapproved and unauthenticated browser see no research navigation',async({browser})=>{
 for(const email of [null,'unapproved@example.org']){
   const {c,p}=await persona(browser,email);await p.goto(base);
   await expect(p.getByRole('link',{name:'Sign in with another email'})).toBeVisible();
   await expect(p.getByRole('button',{name:'Create scenario',exact:true})).toHaveCount(0);
   await c.close();
 }
});
