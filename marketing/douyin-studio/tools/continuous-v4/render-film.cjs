const path=require('node:path');
const fs=require('node:fs');
const project=path.resolve(__dirname,'../..');
const out='/workspace/jiejing-deliverables/11.0/20261007-continuous-v4';
const {bundle}=require(path.join(project,'node_modules/@remotion/bundler'));
const {openBrowser,selectComposition,renderStill,renderMedia}=require(path.join(project,'node_modules/@remotion/renderer'));
(async()=>{
 const serveUrl=await bundle({entryPoint:path.join(project,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir:path.join(out,'assets'),enableCaching:true});
 const browser=await openBrowser('chrome',{browserExecutable:'/usr/bin/chromium',logLevel:'error'});
 try {
  const composition=await selectComposition({serveUrl,id:'Douyin11ContinuousV4',puppeteerInstance:browser});
  fs.mkdirSync(path.join(out,'frames'),{recursive:true});
  for(const frame of [25,95,220,332,430,542,661,782,892,1085,1210,1288,1405,1470,1570,1640]){
   await renderStill({serveUrl,composition,output:path.join(out,'frames',`frame-${frame}.png`),puppeteerInstance:browser,frame,logLevel:'error'});
   console.log('FRAME',frame);
  }
  if(process.argv.includes('--video')){
   let last=-1;
   await renderMedia({serveUrl,composition,outputLocation:path.join(out,'render-source.mp4'),codec:'h264',pixelFormat:'yuv420p',audioCodec:'aac',audioBitrate:'192k',crf:18,imageFormat:'png',concurrency:4,puppeteerInstance:browser,logLevel:'error',onProgress:p=>{const n=Math.floor(p.progress*10);if(n!==last){last=n;console.log('RENDER',n*10+'%');}}});
   console.log('RENDER_OK');
  }
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
