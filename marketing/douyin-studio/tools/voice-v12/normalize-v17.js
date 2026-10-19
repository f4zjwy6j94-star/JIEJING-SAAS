import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
const [source,out]=process.argv.slice(2);
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
if(!source||hash(source)!=='e9a84638fafb47565c30214f8a1e851a5a73d575ec58e70aa1486fcb501d0be7')throw new Error('Exact new V17 voice join required');
if(!out||!path.isAbsolute(out)||fs.existsSync(out))throw new Error('Fresh output directory required');
fs.mkdirSync(out,{recursive:true});
const linux=p=>`/mnt/${p[0].toLowerCase()}${p.slice(2).replaceAll('\\','/')}`;
const run=args=>{
  const p=spawnSync('wsl.exe',['-d','Ubuntu','--exec','/usr/bin/ffmpeg',...args],{encoding:'utf8',windowsHide:true,maxBuffer:4*1024*1024});
  if(p.status!==0)throw new Error(`Audio normalization failed: ${p.stderr.slice(-1000)}`);
  return p.stderr;
};
const analyze=file=>{
  const s=run(['-hide_banner','-i',linux(file),'-af','loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json','-f','null','-']);
  return JSON.parse(s.slice(s.lastIndexOf('{'),s.lastIndexOf('}')+1));
};
const m=analyze(source);
const filter=`loudnorm=I=-16:TP=-1.5:LRA=7:measured_I=${m.input_i}:measured_TP=${m.input_tp}:measured_LRA=${m.input_lra}:measured_thresh=${m.input_thresh}:offset=${m.target_offset}:linear=true:print_format=json,apad`;
const target=path.join(out,'v17-narration.wav');
run(['-v','error','-i',linux(source),'-af',filter,'-ar','48000','-ac','2','-c:a','pcm_s16le','-t','28','-n',linux(target)]);
const final=analyze(target);
const passed=Number(final.input_tp)<=-1&&Number(final.input_i)>=-18&&Number(final.input_i)<=-14;
const receipt={source,source_sha256:hash(source),output:target,sha256:hash(target),before:m,after:final,loudness_passed:passed,duration_seconds:28,speech_speed_or_pitch_changed:false,new_music_or_stock_audio:false,human_listening_passed:false};
fs.writeFileSync(path.join(out,'AUDIO_NORMALIZE.safe.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(receipt,null,2));
if(!passed)process.exitCode=1;
