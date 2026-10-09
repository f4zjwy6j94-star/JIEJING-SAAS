import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const [out,mode='frames',voice,expectedSha]=process.argv.slice(2);
if(!out||!path.isAbsolute(out)||fs.existsSync(out))throw new Error('A fresh absolute output directory is required');
if(!['frames','sample','film'].includes(mode))throw new Error('Unknown rendering mode');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
if(mode!=='frames'&&(!voice||!expectedSha||hash(voice)!==expectedSha))throw new Error('A reviewed new narration path and exact SHA are required; no silent fallback');
const chrome=path.join(studio,'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
if(!fs.existsSync(chrome))throw new Error('Existing renderer is required; no download');
fs.mkdirSync(out,{recursive:true});
const publicDir=path.join(out,'public');fs.mkdirSync(publicDir);
if(voice)fs.copyFileSync(voice,path.join(publicDir,'v16-narration.wav'),fs.constants.COPYFILE_EXCL);
const serveUrl=await bundle({entryPoint:path.join(studio,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir,enableCaching:false,rspack:true,gitSource:null});
const inputProps={withAudio:mode!=='frames'};
const composition=await selectComposition({serveUrl,id:'JiejingV16',browserExecutable:chrome,inputProps});
const frames=[];
for(const frame of [0,145,232,306,378,452,518,621]){
  const file=path.join(out,`frame-${String(frame).padStart(4,'0')}.png`);
  await renderStill({serveUrl,composition,browserExecutable:chrome,inputProps,frame,output:file,imageFormat:'png',overwrite:false});
  frames.push({frame,file,sha256:hash(file)});console.log(`Frame ${frame}`);
}
let film=null;
if(mode!=='frames'){
  const file=path.join(out,mode==='sample'?'jiejing-v16-first12s-review.mp4':'jiejing-v16-full-review.mp4');
  await renderMedia({serveUrl,composition,browserExecutable:chrome,inputProps,codec:'h264',audioCodec:'aac',pixelFormat:'yuv420p',colorSpace:'bt709',crf:18,concurrency:1,outputLocation:file,overwrite:false,...(mode==='sample'?{frameRange:[0,359]}:{})});
  film={file,sha256:hash(file),bytes:fs.statSync(file).size};
}
fs.writeFileSync(path.join(out,'RENDER.safe.json'),JSON.stringify({created_at:new Date().toISOString(),mode,composition:composition.id,duration_frames:composition.durationInFrames,fps:composition.fps,width:composition.width,height:composition.height,voice_sha256:voice?hash(voice):null,frames,film,full_av_review_passed:false,ready_to_publish:false},null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({out,film}));
