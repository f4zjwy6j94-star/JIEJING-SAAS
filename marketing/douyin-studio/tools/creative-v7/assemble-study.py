"""Assemble sampled physical renders per shot, preserving cut boundaries and narration."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import time

OUT=Path(os.environ.get('JIEJING_V7_OUTPUT', '/workspace/jiejing-deliverables/11.0/20261007-creative-reset-v7'))
OLD=Path('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6')
BLENDER=Path('/workspace/toolchains/blender-4.3.2-portable/blender-4.3.2-linux-x64/blender')
ASSETS=OUT/'assets/creative-v7'
ASSETS.mkdir(parents=True,exist_ok=True)


def run(args):
    subprocess.run(args,check=True)


def main():
    state=json.loads((OUT/'RENDER_FRAMES.safe.json').read_text())
    assert state['exit_code']==0
    for frame in [82,172,255]:
        target=OUT/'frames'/f'frame-{frame:04d}.png'
        if not target.is_file():
            code=f"import bpy; s=bpy.context.scene;s.cycles.samples=4;s.render.threads=4;s.frame_set({frame});s.render.filepath={str(target)!r};bpy.ops.render.render(write_still=True)"
            run([str(BLENDER),'-b',str(OUT/'jiejing-tactile-v7.blend'),'-t','4','--python-expr',code])
            state['frames'].append(frame)
    state['frames']=sorted(set(state['frames']))
    state['exact_cut_boundary_frames_verified']=[81,82,171,172,254,255]
    (OUT/'RENDER_FRAMES.safe.json').write_text(json.dumps(state,indent=2)+'\n')
    shot_defs=[(1,81),(82,171),(172,254),(255,342)]
    shots=[]
    for index,(start,end) in enumerate(shot_defs):
        frames=[f for f in state['frames'] if start<=f<=end]
        assert frames[0]==start and frames[-1]==end
        concat=OUT/f'shot-{index+1}.ffconcat'
        lines=['ffconcat version 1.0']
        for i,f in enumerate(frames):
            path=OUT/'frames'/f'frame-{f:04d}.png';assert path.is_file()
            duration=(frames[i+1]-f)/24 if i+1<len(frames) else 1/24
            lines += [f"file '{path}'",f'duration {duration:.9f}']
        lines.append(f"file '{OUT/'frames'/f'frame-{frames[-1]:04d}.png'}'")
        concat.write_text('\n'.join(lines)+'\n')
        output=OUT/f'shot-{index+1}.mp4'
        run(['ffmpeg','-hide_banner','-loglevel','error','-n','-safe','0','-f','concat','-i',str(concat),'-vf','tpad=stop_mode=clone:stop_duration=0.5,minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1','-t',f'{(end-start+1)/24:.9f}','-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p','-threads','3',str(output)])
        shots.append(output)
    concat=OUT/'shots.ffconcat';concat.write_text('ffconcat version 1.0\n'+'\n'.join(f"file '{p}'" for p in shots)+'\n')
    run(['ffmpeg','-hide_banner','-loglevel','error','-n','-safe','0','-f','concat','-i',str(concat),'-c','copy','-movflags','+faststart',str(ASSETS/'footage.mp4')])
    # Same paragraph excerpt to compare visual direction; no new voice approval implied.
    run(['ffmpeg','-hide_banner','-loglevel','error','-n','-i',str(OLD/'voice-normalized.wav'),'-i',str(OLD/'music-original.wav'),'-filter_complex','[0:a]atrim=0:14.25,asetpts=PTS-STARTPTS,afade=t=out:st=13.8:d=0.45[v];[1:a]atrim=0:14.25,asetpts=PTS-STARTPTS,volume=0.35,afade=t=out:st=13.5:d=0.75[m];[v][m]amix=inputs=2:normalize=0,loudnorm=I=-16.5:TP=-1.5:LRA=7[out]','-map','[out]','-ar','48000','-ac','2','-c:a','pcm_s16le',str(ASSETS/'soundtrack.wav')])
    for name in ['sans.otf','bold.otf']:
        shutil.copy2(OLD/'assets/release-v6'/name,ASSETS/name)
    shutil.copy2(OLD/'assets/release-v6/workspace-goal.png',ASSETS/'workspace-goal.png')
    result={'exit_code':0,'frames_physically_rendered':len(state['frames']),'native_render_resolution':[720,1280],'nominal_render_sampling_fps':4,'output_fps':24,'motion_interpolation':'FFmpeg mci per shot, never across cut boundaries','full_24fps_native_render':False,'seconds':14.25,'narration':'Existing unapproved v6 Serena voice, first complete section; no new generation','old_reference_movies_used_in_footage':False}
    (OUT/'ASSEMBLY.safe.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
