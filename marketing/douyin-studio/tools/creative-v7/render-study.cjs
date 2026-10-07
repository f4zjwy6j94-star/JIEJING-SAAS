const fs=require('node:fs');
const path=require('node:path');
const project=path.resolve(__dirname,'../..');
const out=process.env.JIEJING_V7_OUTPUT||'/workspace/jiejing-deliverables/11.0/20261007-creative-reset-v7';
const {bundle}=require(path.join(project,'node_modules/@remotion/bundler'));
const {openBrowser,selectComposition,renderStill,renderMedia}=require(path.join(project,'node_modules/@remotion/renderer'));
(async()=>{
 if(fs.existsSync(path.join(out,'study-render-source.mp4')))throw new Error('Preserve the prior render; choose a new JIEJING_V7_OUTPUT directory.');
 for(const name of ['footage.mp4','soundtrack.wav','sans.otf','bold.otf','workspace-goal.png'])if(!fs.existsSync(path.join(out,'assets/creative-v7',name)))throw new Error('Missing required v7 asset: '+name);
 const serveUrl=await bundle({entryPoint:path.join(project,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir:path.join(out,'assets'),enableCaching:true});
 const browser=await openBrowser('chrome',{browserExecutable:'/usr/bin/chromium',logLevel:'error'});
 try{
  const composition=await selectComposition({serveUrl,id:'Douyin11TactileV7',puppeteerInstance:browser});
  for(const frame of [1,43,85,121,175,211,259,307])await renderStill({serveUrl,composition,frame,output:path.join(out,`review-${frame}.png`),puppeteerInstance:browser,inputProps:{includeAudio:false},logLevel:'error'});
  let prior=-1;
  await renderMedia({serveUrl,composition,outputLocation:path.join(out,'study-render-source.mp4'),codec:'h264',pixelFormat:'yuv420p',audioCodec:'aac',audioBitrate:'192k',crf:17,concurrency:2,imageFormat:'png',puppeteerInstance:browser,logLevel:'error',onProgress:p=>{const n=Math.floor(p.progress*10);if(n!==prior){prior=n;console.log('RENDER',n*10+'%');}}});
  console.log('STUDY_RENDER_OK');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
