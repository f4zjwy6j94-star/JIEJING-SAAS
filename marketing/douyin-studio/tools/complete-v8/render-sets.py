"""Render the saved seven-set Blender file; validate cached frames before resume."""
import bpy
import hashlib
import json
import os
import sys
import time
from pathlib import Path

OUT=Path(os.environ.get('JIEJING_V8_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-complete-v8'))
args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
story=json.loads((OUT/'SCENES.safe.json').read_text())
scene_hash=hashlib.sha256((OUT/'jiejing-v8-seven-sets.blend').read_bytes()).hexdigest()
if '--preview' in args:
    for name in ['01_materials','03_input']:
        s=bpy.data.scenes[name];bpy.context.window.scene=s;s.frame_set(round(s.frame_end*.55))
        target=OUT/(name+'-preview.png')
        if target.exists():raise FileExistsError(str(target))
        s.render.filepath=str(target);bpy.ops.render.render(write_still=True)
else:
    record=OUT/'FRAME_PROGRESS.safe.json'
    data=json.loads(record.read_text()) if record.exists() else {'scene_sha256':scene_hash,'completed':{}}
    assert data['scene_sha256']==scene_hash,'Saved scene changed; do not reuse old frames'
    result=[];start=time.monotonic()
    for shot in story['shots']:
        s=bpy.data.scenes[shot['scene']];bpy.context.window.scene=s;assert s.frame_end==shot['frames']
        step=4 if shot['scene'] in ['04_editorial','05_confirm','06_world'] else 6
        frames=sorted(set(range(1,s.frame_end+1,step))|{s.frame_end})
        folder=OUT/'frames'/s.name;folder.mkdir(parents=True,exist_ok=True)
        for f in frames:
            dest=folder/f'{f:04d}.png';relative=str(dest.relative_to(OUT))
            if dest.exists():
                assert relative in data['completed'],'Unrecorded frame exists; preserve and investigate'
                assert hashlib.sha256(dest.read_bytes()).hexdigest()==data['completed'][relative]['sha256']
            else:
                assert relative not in data['completed'],'Previously verified frame missing'
                s.frame_set(f);s.render.filepath=str(dest);bpy.ops.render.render(write_still=True)
                data['completed'][relative]={'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'bytes':dest.stat().st_size}
                record.write_text(json.dumps(data,indent=2)+'\n')
        result.append({'scene':s.name,'frames':frames,'timeline_frames':s.frame_end,'sample_every_nth_frame':step})
        print('SHOT_FINISHED',s.name,len(frames),flush=True)
    (OUT/'RENDER.safe.json').write_text(json.dumps({'exit_code':0,'shots':result,'scene_sha256':scene_hash,'frames_physically_rendered':sum(len(s['frames']) for s in result),'samples':6,'cpu_threads':4,'native_resolution':[720,1280],'timeline_fps':24,'full_native24fps':False,'elapsed_seconds':time.monotonic()-start},indent=2)+'\n')
    print('V8_RENDER_COMPLETE',flush=True)
