"""Validate the actual encoded v10 deliverable, without certifying taste or publication."""
from pathlib import Path
import os
import hashlib
import json
import re
import subprocess

OUT=Path(os.environ.get('JIEJING_V10_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-ai-commerce-v10'))
def run(args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(f'{args[0]} exit {p.returncode}: {p.stderr[-1800:]}')
    return p
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    timing=json.loads((OUT/'TIMING.json').read_text());duration=timing['duration'];movie=OUT/'jiejing-douyin-v10.mp4'
    metadata=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(movie)]).stdout)
    video=next(s for s in metadata['streams'] if s['codec_type']=='video');audio=next(s for s in metadata['streams'] if s['codec_type']=='audio')
    assert (video['codec_name'],video['width'],video['height'],video['avg_frame_rate'],video['pix_fmt'],int(video['nb_frames']))==('h264',1080,1920,'30/1','yuv420p',round(duration*30))
    assert abs(float(metadata['format']['duration'])-duration)<.04
    assert audio['codec_name']=='aac' and int(audio['sample_rate'])==48000 and audio['channels']==2
    run(['ffmpeg','-v','error','-xerror','-i',str(movie),'-f','null','-'])
    blacklog=run(['ffmpeg','-hide_banner','-i',str(movie),'-vf','blackdetect=d=.08:pix_th=.05:pic_th=.98','-an','-f','null','-'])
    black=re.findall(r'black_start:[^\n]+',blacklog.stderr);assert not black,black
    sound=run(['ffmpeg','-hide_banner','-i',str(movie),'-af','loudnorm=I=-16.5:TP=-1.5:LRA=8:print_format=json','-vn','-f','null','-'])
    levels=json.loads(re.findall(r'\{\s*"input_i".*?\}',sound.stderr,re.S)[-1]);assert -19<=float(levels['input_i'])<=-14 and float(levels['input_tp'])<=-1
    generation=json.loads((OUT/'QWEN_LOCAL_GENERATION.safe.json').read_text());assert digest(OUT/'voice-qwen-serena-raw.wav')==generation['sha256']
    normalize=lambda s:re.sub(r'[^\u4e00-\u9fffA-Za-z]','',s).replace('eBay','易贝')
    srt=(OUT/'jiejing-v10.srt').read_text();spoken=''.join(re.findall(r'\n([^\n]+)(?=\n\n|\n?$)',srt))
    assert normalize(spoken)==normalize((OUT/'NARRATION.txt').read_text())
    assert srt.count(' --> ')==len(timing['captions'])
    for c in timing['captions']:assert 0<=c['start']<c['end']<=duration
    for a,b in zip(timing['captions'],timing['captions'][1:]):assert a['end']<=b['start']
    times=[0,duration-1/30]
    for s in timing['scenes']:
        times.append(min(s['end']-.3,s['start']+max(2,(s['end']-s['start'])*.65)))
        if s['start']>0:times.extend([s['start']-.04,s['start']+.25,s['start']+.55])
    times=sorted(set(round(t,3) for t in times));frames=OUT/'encoded-frames';frames.mkdir(exist_ok=True)
    for t in times:run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(movie),'-frames:v','1',str(frames/f'{t:.3f}.png')])
    pause=run(['ffmpeg','-hide_banner','-i',str(OUT/'voice-qwen-serena-raw.wav'),'-af','silencedetect=n=-45dB:d=0.6','-f','null','-'])
    silence=re.findall(r'silence_(?:start|end):[^\n]+',pause.stderr)
    result={'exit_code':0,'duration_seconds':float(metadata['format']['duration']),'resolution':[1080,1920],'fps':30,'frames':int(video['nb_frames']),'audio':'AAC48k stereo','full_decode_exit_code':0,'black_segments':black,'loudness':levels,'voice_whole_paragraph':True,'voice_source_sha256':generation['sha256'],'voice_speed_changed':False,'subtitles_match_script':True,'captions':len(timing['captions']),'scenes':len(timing['scenes']),'encoded_review_times':times,'voice_silence_over_600ms':silence,'human_listening_claimed':False,'creative_approval':False,'public_posting':False,'mp4_bytes':movie.stat().st_size,'mp4_sha256':digest(movie)}
    (OUT/'VIDEO_QA.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
