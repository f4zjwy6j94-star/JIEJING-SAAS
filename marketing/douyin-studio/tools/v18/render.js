import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const area='D:/Codex-Verification/jiejing-v18-listing-20261010';
const [out,mode='frames']=process.argv.slice(2);
if(!out||!path.isAbsolute(out)||fs.existsSync(out))throw new Error('Fresh absolute output directory required');
if(!['frames','sample','film'].includes(mode))throw new Error('Unknown mode');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const chrome=path.join(studio,'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
if(!fs.existsSync(chrome))throw new Error('Existing renderer required; no download');
fs.mkdirSync(out,{recursive:true});
const serveUrl=await bundle({entryPoint:path.join(studio,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir:path.join(area,'assets'),enableCaching:false,rspack:true,gitSource:null});
const inputProps={withAudio:mode!=='frames'};
const composition=await selectComposition({serveUrl,id:'JiejingV18',browserExecutable:chrome,inputProps});
const frames=[];
if(mode==='frames'){
 for(const [id,frame] of [['V18Hook',60],['V18Scattered',90],['V18Collect',108],['V18Draft',120],['V18Edit',95],['V18Result',90],['V18Close',95]]){
  const c=await selectComposition({serveUrl,id,browserExecutable:chrome});
  const file=path.join(out,`${id}.png`);
  await renderStill({serveUrl,composition:c,browserExecutable:chrome,frame:Math.min(frame,c.durationInFrames-1),output:file,imageFormat:'png',overwrite:false});
  frames.push({id,frame,file,sha256:hash(file)}); console.log(`Frame ${id}`);
 }
}
let film=null;
if(mode!=='frames'){
 const file=path.join(out,mode==='sample'?'jiejing-v18-narrated-sample.mp4':'jiejing-v18-review.mp4');
 let last=-1;
 await renderMedia({serveUrl,composition,browserExecutable:chrome,inputProps,codec:'h264',pixelFormat:'yuv420p',colorSpace:'bt709',crf:18,concurrency:2,outputLocation:file,overwrite:false,
  ...(mode==='sample'?{frameRange:[0,Math.min(449,composition.durationInFrames-1)]}:{}),
  onProgress:p=>{const n=Math.floor(p.renderedFrames/150);if(n!==last){last=n;console.log(`Rendered ${p.renderedFrames}/${composition.durationInFrames}`);}}});
 film={file,sha256:hash(file),bytes:fs.statSync(file).size};
}
const receipt={created_at:new Date().toISOString(),mode,composition:composition.id,duration_frames:composition.durationInFrames,fps:composition.fps,width:composition.width,height:composition.height,frames,film,ready_to_publish:false,external_uploads:0};
fs.writeFileSync(path.join(out,'RENDER.safe.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({out,film}));
