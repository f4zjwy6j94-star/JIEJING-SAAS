const path=require('node:path');
const fs=require('node:fs');
const project=path.resolve(__dirname,'../..');
const out='/workspace/jiejing-deliverables/11.0/20261007-release-film-v6';
const {bundle}=require(path.join(project,'node_modules/@remotion/bundler'));
const {openBrowser,selectComposition,renderStill,renderMedia}=require(path.join(project,'node_modules/@remotion/renderer'));
(async()=>{
 const serveUrl=await bundle({entryPoint:path.join(project,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir:path.join(out,'assets'),enableCaching:true});
 const browser=await openBrowser('chrome',{browserExecutable:'/usr/bin/chromium',logLevel:'error'});
 try {
  const composition=await selectComposition({serveUrl,id:'Douyin11ReleaseV6',puppeteerInstance:browser});
  fs.mkdirSync(path.join(out,'frames'),{recursive:true});
  const frames=[1,55,120,195,260,380,490,570,650,715,780,composition.durationInFrames-10].filter(f=>f<composition.durationInFrames);
  if(!process.argv.includes('--video-only'))for(const frame of frames){
   await renderStill({serveUrl,composition,output:path.join(out,'frames',`frame-${frame}.png`),puppeteerInstance:browser,frame,inputProps:{includeAudio:false},logLevel:'error'});
   console.log('FRAME',frame);
  }
  const cover=await selectComposition({serveUrl,id:'Douyin11ReleaseCover',puppeteerInstance:browser});
  await renderStill({serveUrl,composition:cover,output:path.join(out,'cover.png'),puppeteerInstance:browser,frame:0,logLevel:'error'});
  if(process.argv.includes('--video')||process.argv.includes('--video-only')){
   if(!fs.existsSync(path.join(out,'assets/release-v6/soundtrack.wav')))throw new Error('Verified final audio is missing');
   let last=-1;
   await renderMedia({serveUrl,composition,outputLocation:path.join(out,'render-source.mp4'),codec:'h264',pixelFormat:'yuv420p',audioCodec:'aac',audioBitrate:'192k',crf:17,imageFormat:'png',concurrency:2,puppeteerInstance:browser,logLevel:'error',inputProps:{includeAudio:true},onProgress:p=>{const n=Math.floor(p.progress*10);if(n!==last){last=n;console.log('RENDER',n*10+'%');}}});
   console.log('RENDER_OK');
  }
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
