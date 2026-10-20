"""Join immutable V18 takes at original speed, align scenes and create original UI Foley."""
import hashlib
import json
import math
from pathlib import Path
import sys
import wave
import numpy as np

ROOT = Path(r'D:\Codex-Verification\jiejing-v18-listing-20261010')
out = Path(sys.argv[1]).resolve()
if not out.is_relative_to(ROOT) or out == ROOT or out.exists():
    raise SystemExit('Fresh V18 output directory required')
RATE, FPS = 24000, 30
parts, timeline, total = [], [], 0
for number in range(1, 8):
    folder = ROOT / ('voice-01' if number <= 3 else 'voice-02')
    receipt = json.loads((folder / f'VOICE_{number:02d}.safe.json').read_text(encoding='utf-8'))
    source = folder / f'voice-{number:02d}.wav'
    if hashlib.sha256(source.read_bytes()).hexdigest() != receipt['sha256']:
        raise SystemExit('Take changed')
    with wave.open(str(source), 'rb') as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (RATE, 1, 2):
            raise SystemExit('Unexpected take format')
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
    lead = round(RATE*.05)
    frames = max(105 if number == 1 else 120, math.ceil((len(audio)/RATE+.23)*FPS))
    if number == 7:
        frames += 12
    count = frames * (RATE // FPS)
    scene = np.zeros(count, dtype=np.float32)
    scene[lead:lead+len(audio)] = audio
    timeline.append({'number':number,'text':receipt['text'],'scene_start_frame':total//(RATE//FPS),
                     'scene_frames':frames,'speech_start_seconds':(total+lead)/RATE,
                     'speech_end_seconds':(total+lead+len(audio))/RATE,'source':str(source),'source_sha256':receipt['sha256']})
    parts.append(scene)
    total += count
narration = np.concatenate(parts)
# Deterministic, quiet original sound effects; no stock music, samples or borrowed audio.
fx = np.zeros_like(narration)
for item in timeline[1:]:
    n = round(.15*RATE); t=np.arange(n)/RATE
    noise=np.random.default_rng(1800+item['number']).normal(size=n)
    smooth=np.convolve(noise,np.ones(12)/12,mode='same')
    whoosh=.019*smooth*np.sin(np.pi*np.arange(n)/n)**2
    offset=item['scene_start_frame']*(RATE//FPS)
    fx[offset:offset+n] += whoosh
for scene_number, frame in [(3,84),(5,25),(5,70),(5,84),(6,95)]:
    n=round(.045*RATE); t=np.arange(n)/RATE
    tick=.028*np.sin(2*np.pi*1050*t)*np.exp(-t*100)
    offset=(timeline[scene_number-1]['scene_start_frame']+frame)*(RATE//FPS)
    fx[offset:offset+n] += tick
mix=narration+fx
if np.max(np.abs(mix))>=.999:
    raise SystemExit('Mix would clip; originals preserved')
out.mkdir(parents=True,exist_ok=False)
target=out/'narration-with-original-foley.wav'
with wave.open(str(target),'wb') as stream:
    stream.setparams((1,2,RATE,0,'NONE','not compressed'))
    stream.writeframes((mix*32767).astype('<i2').tobytes())
result={'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'duration_seconds':len(mix)/RATE,'duration_frames':total//(RATE//FPS),'fps':FPS,
        'segments':timeline,'speed_changed':False,'pitch_changed':False,'music_used':False,
        'sound_design':'original quiet UI clicks and short noise swooshes','listening_review_passed':False}
with (out/'AUDIO_TIMELINE.safe.json').open('x',encoding='utf-8') as stream:
    json.dump(result,stream,ensure_ascii=False,indent=2)
print(json.dumps(result,ensure_ascii=False))
