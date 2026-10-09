import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {bundle} from "@remotion/bundler";
import {selectComposition, renderStill, renderMedia} from "@remotion/renderer";

const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../..");
const [assets,output,mode="stills"]=process.argv.slice(2);
if(!assets||!output||!path.isAbsolute(assets)||!path.isAbsolute(output)||!["stills","sample","film"].includes(mode)) throw new Error("Expected absolute assets/new output and stills|sample|film");
if(fs.existsSync(output)) throw new Error("Refusing existing output");
for(const name of ["v13-product.png","serena-flow-original.wav"]) if(!fs.existsSync(path.join(assets,name))) throw new Error(`Missing ${name}`);
const browserExecutable=path.join(studio,"node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
fs.mkdirSync(output,{recursive:true});
const serveUrl=await bundle({entryPoint:path.join(studio,"src/index.ts"),outDir:path.join(output,"bundle"),publicDir:assets,enableCaching:false,rspack:true,gitSource:null});
const composition=await selectComposition({serveUrl,id:"DouyinFlowV13",browserExecutable});
if(composition.durationInFrames!==720||composition.fps!==30) throw new Error("Unexpected metadata");
const frames=[30,100,164,208,256,320,380,442,492,540,584,618,671];
if(mode==="stills") {
 for(const frame of frames){await renderStill({serveUrl,composition,browserExecutable,frame,output:path.join(output,`frame-${frame}.png`),imageFormat:"png",overwrite:false});console.log(`frame ${frame}`);}
}else{
 let last=-1;
 await renderMedia({serveUrl,composition,browserExecutable,outputLocation:path.join(output,`v13-${mode}-raw.mp4`),codec:"h264",audioCodec:"aac",crf:18,pixelFormat:"yuv420p",colorSpace:"bt709",imageFormat:"png",concurrency:2,overwrite:false,frameRange:mode==="sample"?[0,269]:undefined,onProgress:({progress})=>{const step=Math.floor(progress*10);if(step>last){last=step;console.log(`${mode} ${step*10}%`);}}});
}
fs.writeFileSync(path.join(output,"RENDER.safe.json"),JSON.stringify({version:"V13 action-flow",mode,frames:mode==="sample"?270:720,fps:30,reviewFrames:frames,contains_owner_rejected_serena_voice:true,publication_prohibited:true,full_visual_review:false,natural_voice_listening_review:false,ready_to_publish:false},null,2),{flag:"wx"});
