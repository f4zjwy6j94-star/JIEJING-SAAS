const fs=require('node:fs');
const path=require('node:path');
const project=path.resolve(__dirname,'../..');
const out=process.env.JIEJING_V8_OUTPUT||'/workspace/jiejing-deliverables/11.0/20261007-complete-v8';
const {bundle}=require(path.join(project,'node_modules/@remotion/bundler'));
const {openBrowser,selectComposition,renderStill,renderMedia}=require(path.join(project,'node_modules/@remotion/renderer'));
const stillOnly=process.argv.includes('--stills');
(async()=>{
 if(!stillOnly&&fs.existsSync(path.join(out,'render-source.mp4')))throw new Error('Preserve the earlier output; select a new output directory.');
 const story=JSON.parse(fs.readFileSync(path.join(out,'SCENES.safe.json'),'utf8'));
 for(const x of story.shots){const f=path.join(out,'assets/complete-v8',x.scene+(stillOnly?'-preview.png':'.mp4'));if(!fs.existsSync(f))throw new Error('Missing required shot '+x.scene);}
 for(const name of ['soundtrack.wav','sans.otf','bold.otf'])if(!fs.existsSync(path.join(out,'assets/complete-v8',name)))throw new Error('Missing '+name);
 const serveUrl=await bundle({entryPoint:path.join(project,'src/index.ts'),outDir:path.join(out,stillOnly?'bundle-still':'bundle-film'),publicDir:path.join(out,'assets'),enableCaching:true});
 const browser=await openBrowser('chrome',{browserExecutable:'/usr/bin/chromium',logLevel:'error'});
 try{
  const inputProps={stillMode:stillOnly,includeAudio:!stillOnly};
  const composition=await selectComposition({serveUrl,id:'Douyin11CompleteV8',puppeteerInstance:browser,inputProps});
  const prefix=stillOnly?'layout':'review';
  for(const frame of [36,120,210,295,402,470,560,638])await renderStill({serveUrl,composition,frame,output:path.join(out,`${prefix}-${frame}.png`),puppeteerInstance:browser,inputProps,logLevel:'error'});
  const cover=await selectComposition({serveUrl,id:'Douyin11CoverV8',puppeteerInstance:browser});
  await renderStill({serveUrl,composition:cover,frame:0,output:path.join(out,stillOnly?'cover-layout.png':'cover.png'),puppeteerInstance:browser,logLevel:'error'});
  if(!stillOnly){
   let old=-1;
   await renderMedia({serveUrl,composition,inputProps,outputLocation:path.join(out,'render-source.mp4'),codec:'h264',pixelFormat:'yuv420p',audioCodec:'aac',audioBitrate:'192k',crf:17,concurrency:2,imageFormat:'png',puppeteerInstance:browser,logLevel:'error',onProgress:p=>{const n=Math.floor(p.progress*10);if(n!==old){old=n;console.log('RENDER',n*10+'%');}}});
  }
  console.log(stillOnly?'LAYOUT_STILLS_READY':'FULL_FILM_RENDERED');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
