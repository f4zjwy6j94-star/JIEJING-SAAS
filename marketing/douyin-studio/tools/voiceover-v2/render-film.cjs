const path=require('node:path');
const fs=require('node:fs');
const project='/workspace/JIEJING-SAAS/marketing/douyin-studio';
const out='/workspace/jiejing-deliverables/11.0/20261006-voiceover-v2';
const {bundle}=require(path.join(project,'node_modules/@remotion/bundler'));
const {openBrowser,selectComposition,renderStill,renderMedia}=require(path.join(project,'node_modules/@remotion/renderer'));
(async()=>{
  const final=process.argv.includes('--video');
  const serveUrl=await bundle({entryPoint:path.join(project,'src/index.ts'),outDir:path.join(out,final?'bundle-final':'bundle-review'),publicDir:path.join(out,'assets'),enableCaching:true});
  const browser=await openBrowser('chrome',{browserExecutable:'/usr/bin/chromium',logLevel:'error'});
  try{
    const composition=await selectComposition({serveUrl,id:'Douyin11VoiceoverV2',puppeteerInstance:browser});
    const dir=path.join(out,final?'frames-final':'frames-review');fs.mkdirSync(dir,{recursive:true});
    for(const frame of [70,215,316,400,457,586,720,866,1001,1158,1320,1459,1585]){
      await renderStill({serveUrl,composition,output:path.join(dir,`frame-${frame}.png`),puppeteerInstance:browser,frame,logLevel:'error'});
      console.log('FRAME',frame);
    }
    const cover=await selectComposition({serveUrl,id:'Douyin11VoiceoverCover',puppeteerInstance:browser});
    await renderStill({serveUrl,composition:cover,output:path.join(out,'cover.png'),puppeteerInstance:browser,frame:0,logLevel:'error'});
    if(final){
      let last=-1;
      await renderMedia({serveUrl,composition,outputLocation:path.join(out,'render-source.mp4'),codec:'h264',audioCodec:'aac',audioBitrate:'192k',pixelFormat:'yuv420p',imageFormat:'png',crf:18,concurrency:3,puppeteerInstance:browser,logLevel:'error',onProgress:p=>{const n=Math.floor(p.progress*10);if(n!==last){last=n;console.log('RENDER',n*10+'%');}}});
      console.log('RENDER_OK');
    }
  }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
