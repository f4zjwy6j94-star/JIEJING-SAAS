"""Verify the actual export, soundtrack, shot receipts and subtitles; never approve aesthetics."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

OUT=Path(os.environ.get('JIEJING_V8_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-complete-v8'))


def run(args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(f'{args[0]} exited{p.returncode}: {p.stderr[-2000:]}')
    return p


def main():
    movie=OUT/'jiejing-douyin-v8.mp4'
    if not movie.exists():
        run(['ffmpeg','-hide_banner','-loglevel','error','-n','-i',str(OUT/'render-source.mp4'),'-c:v','copy','-c:a','aac','-b:a','192k','-af','atrim=duration=28,asetpts=PTS-STARTPTS','-t','28','-movflags','+faststart',str(movie)])
    info=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(movie)]).stdout)
    video=next(s for s in info['streams'] if s['codec_type']=='video');audio=next(s for s in info['streams'] if s['codec_type']=='audio')
    assert (video['codec_name'],video['width'],video['height'],video['pix_fmt'],video['avg_frame_rate'],int(video['nb_frames']))==('h264',1080,1920,'yuv420p','24/1',672)
    assert abs(float(info['format']['duration'])-28)<.025
    assert audio['codec_name']=='aac' and audio['sample_rate']=='48000' and audio['channels']==2
    run(['ffmpeg','-v','error','-xerror','-i',str(movie),'-f','null','-'])
    black=run(['ffmpeg','-hide_banner','-i',str(movie),'-vf','blackdetect=d=.10:pix_th=.06:pic_th=.98','-an','-f','null','-'])
    events=re.findall(r'black_start:[^\n]+',black.stderr);assert not events
    loud=run(['ffmpeg','-hide_banner','-i',str(movie),'-af','loudnorm=I=-16.5:TP=-1.5:LRA=7:print_format=json','-vn','-f','null','-'])
    levels=json.loads(re.findall(r'\{\s*"input_i".*?\}',loud.stderr,re.S)[-1]);assert -19<=float(levels['input_i'])<=-14 and float(levels['input_tp'])<=-1
    a=json.loads((OUT/'ASSEMBLY.safe.json').read_text());assert a['exit_code']==0 and len(a['shots'])==7
    assert sum(s['frames'] for s in a['shots'])==672
    for s in a['shots']:
        p=OUT/'assets/complete-v8'/(s['scene']+'.mp4');assert hashlib.sha256(p.read_bytes()).hexdigest()==s['sha256']
    assert (OUT/'jiejing-v8-seven-sets.blend').is_file()
    for f in [36,120,210,295,402,470,560,638]:assert (OUT/f'review-{f}.png').is_file()
    source=Path('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6/voice-normalized.wav')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==hashlib.sha256((OUT/'narration-continuous.wav').read_bytes()).hexdigest()
    text=(OUT/'captions.srt').read_text();assert len(re.findall(r' --> ',text))==9
    result={'exit_code':0,'duration_seconds':float(info['format']['duration']),'video_codec':'h264','width':1080,'height':1920,'fps':24,'frames':672,'audio':'AAC48kHz stereo','full_decode_exit_code':0,'black_segments':events,'loudness':levels,'shots':7,'native_3D_resolution':[720,1280],'3D_motion_interpolation_used':True,'full_native1080p24_3D_claimed':False,'voice_source_hash_preserved':True,'voice_speed_changed':False,'full_film_exported':True,'owner_creative_approval':False,'voice_owner_approval':False,'human_audio_listening_claimed':False,'platform_publication':False,'mp4_bytes':movie.stat().st_size,'mp4_sha256':hashlib.sha256(movie.read_bytes()).hexdigest()}
    (OUT/'VIDEO_QA.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
