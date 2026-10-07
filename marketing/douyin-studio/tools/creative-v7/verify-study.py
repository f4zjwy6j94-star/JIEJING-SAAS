"""Technical checks of the visual prototype, separate from creative approval."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

OUT=Path(os.environ.get('JIEJING_V7_OUTPUT', '/workspace/jiejing-deliverables/11.0/20261007-creative-reset-v7'))


def run(args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(f'{args[0]} exit {p.returncode}: {p.stderr[-1600:]}')
    return p


def main():
    path=OUT/'jiejing-v7-visual-study.mp4'
    if not path.exists():
        run(['ffmpeg','-hide_banner','-loglevel','error','-n','-i',str(OUT/'study-render-source.mp4'),'-c:v','copy','-c:a','aac','-b:a','192k','-af','atrim=duration=14.25,asetpts=PTS-STARTPTS','-t','14.25','-movflags','+faststart',str(path)])
    probe=json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]).stdout)
    video=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert (video['codec_name'],video['width'],video['height'],video['pix_fmt'],video['avg_frame_rate'],int(video['nb_frames']))==('h264',720,1280,'yuv420p','24/1',342)
    assert abs(float(probe['format']['duration'])-14.25)<.025
    assert audio['codec_name']=='aac' and audio['sample_rate']=='48000' and audio['channels']==2
    decode=run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'])
    black=run(['ffmpeg','-hide_banner','-i',str(path),'-vf','blackdetect=d=0.08:pix_th=0.10:pic_th=0.98','-an','-f','null','-'])
    black_events=re.findall(r'black_start:[^\n]+',black.stderr);assert not black_events
    loud=run(['ffmpeg','-hide_banner','-i',str(path),'-af','loudnorm=I=-16.5:TP=-1.5:LRA=7:print_format=json','-vn','-f','null','-'])
    loudness=json.loads(re.findall(r'\{\s*"input_i".*?\}',loud.stderr,re.S)[-1]);assert -19<=float(loudness['input_i'])<=-14 and float(loudness['input_tp'])<=-1
    state=json.loads((OUT/'RENDER_FRAMES.safe.json').read_text())
    for f in state['frames']:
        p=OUT/'frames'/f'frame-{f:04d}.png';assert p.is_file() and p.stat().st_size>10000
    assert {81,82,171,172,254,255,342}.issubset(state['frames'])
    assert (OUT/'jiejing-tactile-v7.blend').stat().st_size>100000
    for f in [1,43,85,121,175,211,259,307]:assert (OUT/f'review-{f}.png').is_file()
    result={'exit_code':0,'duration_seconds':float(probe['format']['duration']),'width':720,'height':1280,'output_fps':24,'video_frames':342,'frames_physically_rendered':len(state['frames']),'motion_interpolation_used':True,'native_24fps_render_claimed':False,'full_decode_exit_code':decode.returncode,'black_segments':black_events,'loudness':loudness,'mp4_bytes':path.stat().st_size,'mp4_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'full_advertisement':False,'technical_pass_does_not_certify_visual_approval':True,'owner_visual_approval':False,'voice_approval':False,'published':False,'no_human_listening_claimed':True}
    (OUT/'VIDEO_QA.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
