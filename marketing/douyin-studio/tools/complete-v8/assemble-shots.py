"""Interpolate verified native frames within each shot, never through a scene cut."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

OUT=Path(os.environ.get('JIEJING_V8_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-complete-v8'))
A=OUT/'assets/complete-v8'
state=json.loads((OUT/'RENDER.safe.json').read_text());assert state['exit_code']==0
saved=json.loads((OUT/'FRAME_PROGRESS.safe.json').read_text());receipts=[]
for shot in state['shots']:
    frames=shot['frames'];assert frames[0]==1 and frames[-1]==shot['timeline_frames']
    lines=['ffconcat version 1.0']
    for i,f in enumerate(frames):
        p=OUT/'frames'/shot['scene']/f'{f:04d}.png';relative=str(p.relative_to(OUT));expected=saved['completed'][relative]
        assert p.stat().st_size==expected['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==expected['sha256']
        duration=(frames[i+1]-f)/24 if i+1<len(frames) else 1/24
        lines.extend([f"file '{p}'",f'duration {duration:.9f}'])
    lines.append(f"file '{p}'");concat=OUT/(shot['scene']+'.ffconcat');concat.write_text('\n'.join(lines)+'\n')
    target=A/(shot['scene']+'.mp4')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-n','-safe','0','-f','concat','-i',str(concat),'-vf','tpad=stop_mode=clone:stop_duration=0.6,minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1','-t',str(shot['timeline_frames']/24),'-c:v','libx264','-crf','15','-preset','fast','-pix_fmt','yuv420p','-threads','3',str(target)],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_streams','-of','json',str(target)],text=True))['streams'][0]
    assert int(probe['nb_frames'])==shot['timeline_frames'] and probe['avg_frame_rate']=='24/1'
    receipts.append({'scene':shot['scene'],'frames':int(probe['nb_frames']),'native_frames':len(frames),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    print('ASSEMBLED',shot['scene'],flush=True)
(OUT/'ASSEMBLY.safe.json').write_text(json.dumps({'exit_code':0,'shots':receipts,'output_fps':24,'native_3D_resolution':[720,1280],'motion_interpolation':'Per shot, no cross-cut interpolation','final_text_composition_resolution':[1080,1920],'full_native_1080p24_3D_claimed':False},indent=2)+'\n')
