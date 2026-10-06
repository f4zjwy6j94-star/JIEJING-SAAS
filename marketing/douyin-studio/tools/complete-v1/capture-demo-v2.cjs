const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('/workspace/JIEJING-SAAS/output/codex-playwright-deps/node_modules/playwright-core');
const root='/workspace/JIEJING-SAAS';
const out='/workspace/jiejing-deliverables/11.0/20261006-complete-v1';
const base='http://127.0.0.1:8796';
async function api(route, body, token) {
  const r=await fetch(base+route,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
  if(!r.ok)throw new Error(route+' HTTP '+r.status);
  return r.json();
}
(async()=>{
  const health=await api('/health');
  if(health.environment!=='local_dev'||health.real_platform_writes_enabled!==false)throw Error('Unsafe backend');
  const suffix=Date.now();
  const user=await api('/auth/register',{email:`video-demo-${suffix}@local.invalid`,password:crypto.randomBytes(24).toString('hex'),company_name:'演示工作室'});
  const store=(await api('/stores',{platform:'ebay',store_name:'示例店铺',marketplace:'EBAY_US'},user.token)).store;
  const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1280,height:1000},deviceScaleFactor:1});
    await context.addCookies([{name:'jiejing_saas_session',value:user.token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
    await context.addInitScript(({base,uid,sid})=>{
      localStorage.setItem('jiejing_saas_api_base',base);
      localStorage.setItem('jiejing_saas_backend_session_hint','1');
      localStorage.setItem('jiejing_saas_session_hint','1');
      localStorage.setItem('jiejing_saas_last_account',uid);
      localStorage.setItem('jiejing_saas_backend_store_id',sid);
      localStorage.setItem('jiejing_saas_onboarding_done:'+uid,'1');
      window.__JIEJING_FORCE_PUBLIC_MVP__=true;
    },{base,uid:String(user.user.user_id).toLowerCase(),sid:store.store_id});
    const requests=[];
    await context.route('**/*',async route=>{
      const req=route.request(),u=new URL(req.url());
      if(u.origin!==base)return route.abort();
      if(req.method()!=='GET'&&/oauth|publish|checkout|refund|media-asset-jobs|listing-drafts\/generate/i.test(u.pathname))return route.abort();
      requests.push({method:req.method(),path:u.pathname});
      if(req.method()==='GET'&&(/^\/(app\.html|app\.js|styles\.css)$/.test(u.pathname)||u.pathname.startsWith('/assets/'))){
        const p=path.resolve(root,'.'+u.pathname);
        if(!p.startsWith(root+'/'))throw Error('Unsafe path');
        if(fs.existsSync(p)){const ext=path.extname(p),ct={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg'}[ext]||'application/octet-stream';return route.fulfill({status:200,contentType:ct,body:fs.readFileSync(p)});}
      }
      return route.continue();
    });
    const page=await context.newPage();
    await page.goto(base+'/app.html?start=app&view=product',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>typeof state!=='undefined'&&state.saasProtectedStateReady&&!state.saasLoading,null,{timeout:30000});
    await page.evaluate(async()=>{await refreshSaasState({silent:true});setView('product',{listingMode:'single'});});
    await page.evaluate(()=>document.fonts.ready);
    const framesDir=path.join(out,'capture-frames-v2');fs.mkdirSync(framesDir,{recursive:true});
    const cdp=await context.newCDPSession(page);const frames=[],events=[];const t0=performance.now();
    cdp.on('Page.screencastFrame',async e=>{const f=path.join(framesDir,String(frames.length).padStart(5,'0')+'.jpg');fs.writeFileSync(f,Buffer.from(e.data,'base64'));frames.push({file:f,time:(performance.now()-t0)/1000});await cdp.send('Page.screencastFrameAck',{sessionId:e.sessionId});});
    await cdp.send('Page.startScreencast',{format:'jpeg',quality:96,maxWidth:1280,maxHeight:1000,everyNthFrame:1});
    const wait=ms=>new Promise(r=>setTimeout(r,ms));
    async function point(selector){const el=page.locator(selector).first();await el.scrollIntoViewIfNeeded();const r=await el.boundingBox();const x=r.x+r.width/2,y=r.y+r.height/2;await page.mouse.move(x,y,{steps:18});events.push({type:'pointer',time:(performance.now()-t0)/1000,x,y});return el;}
    await wait(700);
    const name=await point('[data-source-manual-field="product_name"]');await name.click();events.push({type:'click',time:(performance.now()-t0)/1000});await name.pressSequentially('咖啡量勺（示例资料）',{delay:110});await wait(700);
    const button=await point('[data-saas-action="save-new-product-facts"]');await wait(450);
    const saved=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/product-facts')&&r.status()===201);
    events.push({type:'click',time:(performance.now()-t0)/1000});await button.click();await saved;
    await wait(1700);
    await page.screenshot({path:out+'/ui-after-save.png'});
    fs.writeFileSync(out+'/ui-after-save.txt',await page.locator('body').innerText());
    const visibleButtons=await page.locator('[data-saas-action]').evaluateAll(xs=>xs.filter(x=>x.getBoundingClientRect().height>0).map(x=>({action:x.dataset.saasAction,text:x.textContent.trim()})));
    console.log(JSON.stringify({after_save_actions:visibleButtons}));
    const title=await point('[data-saas-listing-draft-field="title"]');
    await title.click();events.push({type:'click',time:(performance.now()-t0)/1000});await title.fill('');await title.pressSequentially('Coffee Measuring Scoop',{delay:75});await title.press('Tab');await wait(1900);

    await page.screenshot({path:out+'/ui-draft.png'});
    fs.writeFileSync(out+'/ui-draft.txt',await page.locator('body').innerText());
    await wait(1400);const duration=(performance.now()-t0)/1000;await cdp.send('Page.stopScreencast');
    fs.writeFileSync(out+'/capture-events-v2.safe.json',JSON.stringify({duration,frames,events,requests,source:'Actual checkout app.html/app.js and real isolated local backend; own example account; no mocked API success; no model call or eBay write'},null,2));
    console.log(JSON.stringify({duration,frames:frames.length,events}));
    await page.screenshot({path:out+'/ui-inspect.png'});
    fs.writeFileSync(out+'/ui-inspect.txt',await page.locator('body').innerText());
    console.log(JSON.stringify({screenshot:out+'/ui-inspect.png',inputs:await page.locator('[data-source-manual-field]').evaluateAll(xs=>xs.map(x=>({field:x.dataset.sourceManualField,type:x.type,box:(()=>{const r=x.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()}))),buttons:await page.locator('[data-saas-action]').evaluateAll(xs=>xs.filter(x=>x.getBoundingClientRect().height>0).map(x=>({action:x.dataset.saasAction,text:x.textContent.trim()})).slice(0,40))}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1)});
