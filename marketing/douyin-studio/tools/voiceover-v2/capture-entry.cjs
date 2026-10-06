const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('/workspace/JIEJING-SAAS/output/codex-playwright-deps/node_modules/playwright-core');
const root='/workspace/JIEJING-SAAS',out='/workspace/jiejing-deliverables/11.0/20261006-voiceover-v2',asset=out+'/assets/explainer-v2',base='http://127.0.0.1:8797';
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function api(route,body,token){const r=await fetch(base+route,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error(route+' HTTP'+r.status);return r.json();}
(async()=>{
 const health=await api('/health');if(health.environment!=='local_dev'||health.real_platform_writes_enabled!==false)throw Error('Unexpected live backend');
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true});
 const calls=[];
 try{
  const ctx=await browser.newContext({viewport:{width:1180,height:1000},deviceScaleFactor:1});
  await ctx.addInitScript(base=>{localStorage.setItem('jiejing_saas_api_base',base);window.__JIEJING_FORCE_PUBLIC_MVP__=true;},base);
  await ctx.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url());if(u.origin!==base)return route.abort();
   if(req.method()!=='GET'&&/oauth|publish|checkout|refund|commands|listing-drafts\/generate/i.test(u.pathname))return route.abort();
   calls.push({method:req.method(),path:u.pathname});
   const file=path.resolve(root,'.'+u.pathname);
   if(req.method()==='GET'&&file.startsWith(root+'/')&&fs.existsSync(file)&&fs.statSync(file).isFile()){
    const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2'};
    return route.fulfill({status:200,contentType:types[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
   }return route.continue();
  });
  const page=await ctx.newPage();await page.goto(base+'/index.html',{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);await wait(800);
  await page.screenshot({path:asset+'/home.png'});
  await page.locator('#heroWorkbenchLogin').click();await wait(450);await page.screenshot({path:asset+'/login.png'});
  const u=await api('/auth/register',{email:`explainer-${Date.now()}@local.invalid`,password:crypto.randomBytes(24).toString('hex'),company_name:'视频示例工作室'});
  const s=(await api('/stores',{platform:'ebay',store_name:'讲解示例店铺',marketplace:'EBAY_US'},u.token)).store;
  await ctx.addCookies([{name:'jiejing_saas_session',value:u.token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
  await ctx.addInitScript(({uid,sid})=>{localStorage.setItem('jiejing_saas_backend_session_hint','1');localStorage.setItem('jiejing_saas_session_hint','1');localStorage.setItem('jiejing_saas_last_account',uid);localStorage.setItem('jiejing_saas_backend_store_id',sid);localStorage.setItem('jiejing_saas_onboarding_done:'+uid,'1');},{uid:String(u.user.user_id).toLowerCase(),sid:s.store_id});
  await page.goto(base+'/app.html?start=app&view=cockpit',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>typeof state!=='undefined'&&state.saasProtectedStateReady&&!state.saasLoading,null,{timeout:30000});
  await page.evaluate(async()=>{await refreshSaasState({silent:true});setView('cockpit');});await page.evaluate(()=>document.fonts.ready);await wait(500);
  const input=page.locator('#ceoInput');await input.scrollIntoViewIfNeeded();const rect=await input.boundingBox();
  await page.screenshot({path:asset+'/workspace-start.png'});
  const frameDir=out+'/goal-frames';fs.mkdirSync(frameDir,{recursive:true});const frames=[];const cdp=await ctx.newCDPSession(page);const t0=performance.now();
  cdp.on('Page.screencastFrame',async e=>{const file=frameDir+'/'+String(frames.length).padStart(5,'0')+'.jpg';fs.writeFileSync(file,Buffer.from(e.data,'base64'));frames.push({file,time:(performance.now()-t0)/1000});await cdp.send('Page.screencastFrameAck',{sessionId:e.sessionId});});
  await cdp.send('Page.startScreencast',{format:'jpeg',quality:97,maxWidth:1180,maxHeight:1000,everyNthFrame:1});
  await wait(350);await input.click();await input.pressSequentially('帮我准备这款咖啡量勺的商品页。',{delay:145});await wait(1200);
  const duration=(performance.now()-t0)/1000;await cdp.send('Page.stopScreencast');
  await page.screenshot({path:asset+'/workspace-goal.png'});
  const panel=await page.locator('.saas-ai-ceo-chatgpt-shell').boundingBox();
  fs.writeFileSync(out+'/capture.safe.json',JSON.stringify({duration,frames,input_rect:rect,panel_rect:panel,requests:calls,action:'Actual local input typed, not submitted; no model response or external platform call',source_head:'5e30c8b81e880baade28f655505c635d2bbc8f50'},null,2));
  console.log(JSON.stringify({duration,frames:frames.length,input:rect,panel,assets:['home.png','login.png','workspace-start.png','workspace-goal.png']}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
