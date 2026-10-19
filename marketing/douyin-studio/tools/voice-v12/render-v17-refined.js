import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia,renderStill,selectComposition} from '@remotion/renderer';

const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const [out,mode='frames']=process.argv.slice(2);
if(!out||!path.isAbsolute(out)||fs.existsSync(out))throw new Error('Fresh absolute output directory required');
if(!['frames','film'].includes(mode))throw new Error('Unknown mode');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const chrome=path.join(studio,'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
if(!fs.existsSync(chrome))throw new Error('Existing renderer required; no download');
fs.mkdirSync(out,{recursive:true});
const publicDir=path.join(out,'public');fs.mkdirSync(publicDir);
const serveUrl=await bundle({entryPoint:path.join(studio,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir,enableCaching:false,rspack:true,gitSource:null});
const inputProps={withAudio:false};
const composition=await selectComposition({serveUrl,id:'JiejingV17Refined',browserExecutable:chrome,inputProps});
const frames=[];
for(const frame of [18,100,215,345,468,535,628,740,791]){
 const file=path.join(out,`frame-${String(frame).padStart(4,'0')}.png`);
 await renderStill({serveUrl,composition,browserExecutable:chrome,inputProps,frame,output:file,imageFormat:'png',overwrite:false});
 frames.push({frame,file,sha256:hash(file)});console.log(`Frame ${frame}`);
}
let film=null;
if(mode==='film'){
 const file=path.join(out,'jiejing-v17-refined-visual-intermediate.mp4');
 await renderMedia({serveUrl,composition,browserExecutable:chrome,inputProps,codec:'h264',pixelFormat:'yuv420p',colorSpace:'bt709',crf:18,concurrency:2,outputLocation:file,overwrite:false,onProgress:p=>{if(p.renderedFrames%150===0)console.log(`Rendered ${p.renderedFrames}/${composition.durationInFrames}`);}});
 film={file,sha256:hash(file),bytes:fs.statSync(file).size};
}
const receipt={created_at:new Date().toISOString(),mode,composition:composition.id,duration_frames:840,fps:30,width:1080,height:1920,frames,film,intermediate_visual_only:true,requires_original_accepted_audio:true,ready_to_publish:false};
fs.writeFileSync(path.join(out,'RENDER.safe.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({out,film}));
