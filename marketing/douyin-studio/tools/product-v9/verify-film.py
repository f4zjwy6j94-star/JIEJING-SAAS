"""Verify the encoded v9 movie and audio; does not approve style or publication."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

OUT = Path(os.environ.get('JIEJING_V9_OUTPUT', '/workspace/jiejing-deliverables/11.0/20261007-product-rework-v9'))

def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f'{args[0]} exited {p.returncode}: {p.stderr[-1800:]}')
    return p

def main():
    movie = OUT / 'jiejing-douyin-v9.mp4'
    info = json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(movie)]).stdout)
    v = next(x for x in info['streams'] if x['codec_type']=='video')
    a = next(x for x in info['streams'] if x['codec_type']=='audio')
    assert (v['codec_name'],v['width'],v['height'],v['avg_frame_rate'],v['pix_fmt'],int(v['nb_frames'])) == ('h264',1080,1920,'30/1','yuv420p',870)
    assert abs(float(info['format']['duration'])-29)<.04
    assert a['codec_name']=='aac' and int(a['sample_rate'])==48000 and a['channels']==2
    run(['ffmpeg','-v','error','-xerror','-i',str(movie),'-f','null','-'])
    b = run(['ffmpeg','-hide_banner','-i',str(movie),'-vf','blackdetect=d=.08:pix_th=.05:pic_th=.98','-an','-f','null','-'])
    black = re.findall(r'black_start:[^\n]+',b.stderr)
    assert not black, black
    sound = run(['ffmpeg','-hide_banner','-i',str(movie),'-af','loudnorm=I=-16.5:TP=-1.5:LRA=8:print_format=json','-vn','-f','null','-'])
    levels = json.loads(re.findall(r'\{\s*"input_i".*?\}',sound.stderr,re.S)[-1])
    assert -19<=float(levels['input_i'])<=-14 and float(levels['input_tp'])<=-1
    raw = OUT/'voice-qwen-serena-raw.wav'
    assert hashlib.sha256(raw.read_bytes()).hexdigest()=='bac5fb118f852b029f49a1538ba5d568bc1023edd1497f6fc3bcd0a867b91e1e'
    srt=(OUT/'jiejing-v9.srt').read_text()
    assert srt.count(' --> ')==14
    normalize=lambda s:re.sub(r'[^\u4e00-\u9fffA-Za-z]','',s).replace('eBay','易贝')
    spoken=''.join(re.findall(r'\n([^\n]+)(?=\n\n|\n?$)',srt))
    assert normalize(spoken)==normalize((OUT/'NARRATION.txt').read_text()), (spoken,'subtitle/script mismatch')
    (OUT/'encoded-frames').mkdir(exist_ok=True)
    sample_times=[0,1.5,5.2,8.58,8.84,9.1,9.65,11.86,12.11,12.4,15.7,17.93,18.2,18.47,19.75,20.44,20.7,20.99,23.4,24.1,24.36,24.64,28.5,28.966]
    for t in sample_times:
        run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(movie),'-frames:v','1',str(OUT/'encoded-frames'/f'{t:.3f}.png')])
    result={'exit_code':0,'duration_seconds':float(info['format']['duration']),'width':1080,'height':1920,'fps':30,'frames':870,
            'video_codec':'h264','audio':'AAC48kHz stereo','full_decode_exit_code':0,'black_segments':black,'loudness':levels,
            'narration_whole_paragraph':True,'voice_speed_changed':False,'subtitle_script_match':True,
            'encoded_review_times':sample_times,'human_audio_listening_claimed':False,'creative_approval':False,'public_posting':False,
            'mp4_bytes':movie.stat().st_size,'mp4_sha256':hashlib.sha256(movie.read_bytes()).hexdigest()}
    (OUT/'VIDEO_QA.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
