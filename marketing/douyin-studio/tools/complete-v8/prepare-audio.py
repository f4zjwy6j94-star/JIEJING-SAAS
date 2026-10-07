"""Reuse one continuous narrated paragraph and create quiet original event sounds."""
from pathlib import Path
import array
import json
import math
import os
import random
import shutil
import subprocess
import wave

OUT=Path(os.environ.get('JIEJING_V8_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-complete-v8'))
OLD=Path('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6')
A=OUT/'assets/complete-v8';A.mkdir(parents=True,exist_ok=True)
for name in ['sans.otf','bold.otf','workspace-goal.png']:shutil.copy2(OLD/'assets/release-v6'/name,A/name)
for shot in json.loads((OUT/'SCENES.safe.json').read_text())['shots']:
    name=shot['scene']+'-preview.png';source=OUT/name
    if not source.is_file():source=OUT/'preview-attempt1'/name
    if not source.is_file():raise FileNotFoundError(str(source))
    shutil.copy2(source,A/name)
rate=48000;data=array.array('h',[0])*(28*rate);rng=random.Random(20261007)
for start,duration,amp,kind in [(3.20,.27,.020,'paper'),(7.0,.22,.015,'paper'),(10.5,.24,.017,'paper'),(14.33,.27,.018,'paper'),(16.22,.12,.036,'tap'),(17.6,.28,.013,'paper'),(21.0,.30,.018,'paper')]:
    previous=0.0
    for n in range(int(duration*rate)):
        t=n/rate;env=math.sin(math.pi*t/duration)**2
        if kind=='tap':value=amp*math.exp(-65*t)*(math.sin(2*math.pi*620*t)+.3*math.sin(2*math.pi*1270*t))
        else:
            previous=.76*previous+.24*rng.uniform(-1,1);value=amp*env*previous
        index=int(start*rate)+n;data[index]=int(max(-.95,min(.95,data[index]/32768+value))*32767)
foley=OUT/'foley-original.wav'
if foley.exists():raise FileExistsError(str(foley))
with wave.open(str(foley),'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(data.tobytes())
shutil.copy2(OLD/'voice-normalized.wav',OUT/'narration-continuous.wav')
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-n','-i',str(OUT/'narration-continuous.wav'),'-stream_loop','-1','-i',str(OLD/'music-original.wav'),'-i',str(foley),'-filter_complex','[0:a]apad,atrim=0:28,asetpts=PTS-STARTPTS[v];[1:a]atrim=0:28,asetpts=PTS-STARTPTS,volume=0.42,afade=t=in:st=0:d=0.3,afade=t=out:st=26.5:d=1.5[m];[2:a]apad,atrim=0:28[s];[v][m][s]amix=inputs=3:normalize=0,loudnorm=I=-16.5:TP=-1.5:LRA=7[out]','-map','[out]','-ar','48000','-ac','2','-c:a','pcm_s16le',str(A/'soundtrack.wav')],check=True)
(OUT/'AUDIO.safe.json').write_text(json.dumps({'exit_code':0,'duration':28,'voice_source':str(OLD/'voice-normalized.wav'),'voice_generated_this_turn':False,'one_continuous_paragraph':True,'voice_speed_changed':False,'voice_owner_approved':False,'music':'Retained original v6 score, extended underneath ending','foley':'Original deterministic synthesis in this script','paid_service_calls':False},indent=2)+'\n')
print('AUDIO_AND_PREVIEW_ASSETS_READY')
