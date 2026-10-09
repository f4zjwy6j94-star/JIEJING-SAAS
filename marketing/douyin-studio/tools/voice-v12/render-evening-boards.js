import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";
import {bundle} from "@remotion/bundler";
import {selectComposition,renderStill} from "@remotion/renderer";

const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../..");
const [output]=process.argv.slice(2);
if(!output||!path.isAbsolute(output)||fs.existsSync(output)) throw new Error("Fresh absolute output required; no overwrite");
const browserExecutable=path.join(studio,"node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
if(!fs.existsSync(browserExecutable)) throw new Error("Existing render browser required");
fs.mkdirSync(output,{recursive:true});
const publicDir=path.join(output,"empty-public");fs.mkdirSync(publicDir);
const serveUrl=await bundle({entryPoint:path.join(studio,"src/index.ts"),outDir:path.join(output,"bundle"),publicDir,enableCaching:false,rspack:true,gitSource:null});
const results=[];
for(const id of ["EveningConflict","EveningSources","EveningSeparate","EveningAsk","EveningResolve","EveningClosing"]){
  const composition=await selectComposition({serveUrl,id,browserExecutable});
  const file=path.join(output,`${id}.png`);
  await renderStill({serveUrl,composition,browserExecutable,frame:65,output:file,imageFormat:"png",overwrite:false});
  results.push({composition:id,file,sha256:crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex"),width:composition.width,height:composition.height,frame:65});
  console.log(id);
}
fs.writeFileSync(path.join(output,"BOARDS.safe.json"),JSON.stringify({created_at:new Date().toISOString(),type:"six_storyboard_images_only",results,full_film_created:false,narration_present:false,full_av_review:false,ready_to_publish:false,reason:"New voice generation blocked by guest quota; no silent film fallback rendered."},null,2),{flag:"wx"});
