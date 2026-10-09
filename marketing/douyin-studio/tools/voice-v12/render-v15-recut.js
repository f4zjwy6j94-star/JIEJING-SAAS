import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const studio=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const [out,voice,product,mode='frames']=process.argv.slice(2);
if(!out||!path.isAbsolute(out)||fs.existsSync(out)) throw new Error('Fresh absolute output only');
if(!['frames','film'].includes(mode)) throw new Error('Unknown render mode');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
if(!voice||hash(voice)!=='321e641b1595f0aa3421d782b5da02e8b7d5587a39bf97d5cba6a4a99f0dec12') throw new Error('Expected approved-source audio recut; no silent or old-voice fallback');
if(!product||!fs.statSync(product).isFile()) throw new Error('Existing product PNG required');
const chrome=path.join(studio,'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
if(!fs.existsSync(chrome)) throw new Error('Existing renderer required; do not download');
const linux=p=>`/mnt/${p[0].toLowerCase()}${p.slice(2).replaceAll('\\','/')}`;
const run=(bin,args)=>{
 const r=spawnSync('wsl.exe',['-d','Ubuntu','--exec',bin,...args],{encoding:'utf8',windowsHide:true,maxBuffer:8*1024*1024});
 if(r.status!==0) throw new Error(`${bin} failed: ${(r.stderr||'').slice(-1200)}`);
 return r;
};
fs.mkdirSync(out,{recursive:true});
const publicDir=path.join(out,'public');fs.mkdirSync(publicDir);
fs.copyFileSync(voice,path.join(publicDir,'v15-recut.wav'),fs.constants.COPYFILE_EXCL);
fs.copyFileSync(product,path.join(publicDir,'v15-product.png'),fs.constants.COPYFILE_EXCL);
const serveUrl=await bundle({entryPoint:path.join(studio,'src/index.ts'),outDir:path.join(out,'bundle'),publicDir,enableCaching:false,rspack:true,gitSource:null});
const composition=await selectComposition({serveUrl,id:'JiejingV15Recut',browserExecutable:chrome});
const frames=[];
for(const frame of [0,35,70,139,246,344,430,520,620,704]) {
 const file=path.join(out,`frame-${String(frame).padStart(4,'0')}.png`);
 await renderStill({serveUrl,composition,browserExecutable:chrome,frame,output:file,imageFormat:'png',overwrite:false});
 frames.push({frame,file,sha256:hash(file)});console.log(`Frame ${frame}`);
}
let film=null;
if(mode==='film'){
 const raw=path.join(out,'v15-raw-with-narration.mp4');
 await renderMedia({serveUrl,composition,browserExecutable:chrome,codec:'h264',audioCodec:'aac',pixelFormat:'yuv420p',colorSpace:'bt709',crf:18,concurrency:2,outputLocation:raw,overwrite:false});
 const final=path.join(out,'jiejing-v15-23.6s-approved-voice-review.mp4');
 run('/usr/bin/ffmpeg',['-v','error','-i',linux(raw),'-i',linux(voice),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-af','apad','-t','23.6','-movflags','+faststart','-n',linux(final)]);
 const meta=JSON.parse(run('/usr/bin/ffprobe',['-v','error','-show_entries','format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels','-of','json',linux(final)]).stdout);
 run('/usr/bin/ffmpeg',['-v','error','-xerror','-i',linux(final),'-map','0:v:0','-map','0:a:0','-f','null','-']);
 const l=run('/usr/bin/ffmpeg',['-hide_banner','-i',linux(final),'-af','loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json','-f','null','-']).stderr;
 const metrics=JSON.parse(l.slice(l.lastIndexOf('{'),l.lastIndexOf('}')+1));
 const v=meta.streams.find(s=>s.codec_name==='h264'),a=meta.streams.find(s=>s.codec_name==='aac');
 const pass=v?.width===1080&&v?.height===1920&&v?.nb_frames==='708'&&v?.r_frame_rate==='30/1'&&a?.channels===2&&a?.sample_rate==='48000'&&Math.abs(Number(meta.format.duration)-23.6)<0.05&&Number(metrics.input_tp)<=-1&&Number(metrics.input_i)>=-18&&Number(metrics.input_i)<=-14;
 film={file:final,sha256:hash(final),meta,loudness:metrics,full_decode_exit:0,technical_check_passed:pass};
 if(!pass)console.log('Technical gate failed; preserve and inspect output.');
}
const result={created_at:new Date().toISOString(),composition:composition.id,width:1080,height:1920,frames:708,fps:30,duration_seconds:23.6,voice_sha256:hash(voice),product_sha256:hash(product),sampled_frames:frames,film,full_speed_av_review_passed:false,ready_to_publish:false,uploaded:false,published:false,source_voice_reused:true,new_voice_generated:false};
fs.writeFileSync(path.join(out,'RENDER.safe.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({output:out,film},null,2));
if(film&&!film.technical_check_passed)process.exitCode=1;
