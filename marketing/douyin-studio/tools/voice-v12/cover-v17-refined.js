import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderStill,selectComposition} from '@remotion/renderer';
const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const [out]=process.argv.slice(2);
if(!out||!path.isAbsolute(out)||fs.existsSync(out))throw new Error('Fresh absolute output required');
const chrome=path.join(studio,'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
if(!fs.existsSync(chrome))throw new Error('Existing renderer required');
fs.mkdirSync(out,{recursive:true});const publicDir=path.join(out,'public');fs.mkdirSync(publicDir);
const serveUrl=await bundle({entryPoint:path.join(studio,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir,enableCaching:false,rspack:true,gitSource:null});
const results=[];
for(const [id,name] of [['V17RefinedCover','cover-vertical.png'],['V17RefinedCoverHorizontal','cover-horizontal.png']]){
 const composition=await selectComposition({serveUrl,id,browserExecutable:chrome});const file=path.join(out,name);
 await renderStill({serveUrl,composition,browserExecutable:chrome,frame:0,output:file,imageFormat:'png',overwrite:false});
 results.push({id,file,sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
}
fs.writeFileSync(path.join(out,'COVERS.safe.json'),JSON.stringify(results,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(results));
