from pathlib import Path
import json, shutil, subprocess, wave, numpy as np
out=Path('/workspace/jiejing-deliverables/11.0/20261006-voiceover-v2');assets=out/'assets'/'explainer-v2'
shutil.copy2('/workspace/jiejing-continuity/10.0/media/coffee-scoop/09.jpg',assets/'product-original.jpg')
shutil.copy2('/workspace/JIEJING-SAAS/marketing/douyin-studio/public/brand/jiejing-app-icon.svg',assets/'brand.svg')
capture=json.loads((out/'capture.safe.json').read_text());frames=capture['frames'];lines=[]
for i,r in enumerate(frames):
 duration=(frames[i+1]['time']-r['time']) if i+1<len(frames) else capture['duration']-r['time']
 if i==0:duration+=r['time']
 lines += ["file '"+r['file']+"'",f'duration {max(.001,duration):.6f}']
lines.append("file '"+frames[-1]['file']+"'")
(out/'capture.ffconcat').write_text('\n'.join(lines)+'\n')
subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(out/'capture.ffconcat'),'-vf','fps=30,format=yuv420p','-t',str(capture['duration']),'-c:v','libx264','-crf','17','-preset','fast','-an','-movflags','+faststart',str(assets/'goal.mp4')],check=True)
timeline=json.loads((out/'voice-timeline.json').read_text());rate=48000;duration=timeline['duration_frames']/30;n=int(round(duration*rate));music=np.zeros((n,2));rng=np.random.default_rng(101006)
def add(at,x,pan=0):
 start=int(at*rate);end=min(n,start+len(x));x=x[:end-start]
 if len(x)>0:music[start:end,0]+=x*np.sqrt((1-pan)/2);music[start:end,1]+=x*np.sqrt((1+pan)/2)
def tone(freq,seconds,amp):
 t=np.arange(int(seconds*rate))/rate
 env=(1-np.exp(-t*60))*np.exp(-t*2.3)
 return amp*env*(np.sin(2*np.pi*freq*t)+.24*np.sin(2*np.pi*freq*2*t)+.06*np.sin(2*np.pi*freq*3*t))
beat=.6;chords=[[146.832,220,293.665,349.228],[116.541,174.614,233.082,293.665],[130.813,196,261.626,329.628],[130.813,196,261.626,391.995]]
for b in range(int(duration/beat)+1):
 at=b*beat;chord=chords[(b//8)%4]
 # Soft original electric-piano pattern, bass and restrained percussion.
 add(at,tone(chord[(b*3)%4]*(2 if b%4==3 else 1),1.8,.031),(-.35 if b%2 else .35))
 if b%4==0:add(at,tone(chord[0]/2,2.1,.03),0)
 if b%2==0:
  t=np.arange(int(.15*rate))/rate;kick=.025*np.sin(2*np.pi*(50*t+1.8*(1-np.exp(-t*35))))*np.exp(-t*30);add(at,kick)
 t=np.arange(int(.065*rate))/rate;noise=rng.standard_normal(len(t));hi=noise-np.convolve(noise,np.ones(21)/21,mode='same');add(at+.3,hi*np.exp(-t*85)*.0015,.35)
for seg in timeline['segments'][1:]:
 at=seg['from_frame']/30;t=np.arange(int(.22*rate))/rate;noise=rng.standard_normal(len(t));smooth=np.convolve(noise,np.ones(31)/31,mode='same');add(max(0,at-.14),smooth*np.sin(np.pi*t/.22)**2*.045,0)
with wave.open(str(assets/'voice.wav'),'rb') as f:
 v=np.frombuffer(f.readframes(f.getnframes()),'<i2').astype(float)/32768;vr=f.getframerate()
voice=np.interp(np.arange(n)/rate,np.arange(len(v))/vr,v,left=0,right=0)
kernel=np.ones(int(rate*.08))/(rate*.08);level=np.convolve(np.abs(voice),kernel,mode='same')
duck=1-.55*np.clip(level/.04,0,1);music*=duck[:,None]
fade=np.minimum(np.arange(n)/rate/.6,(n-1-np.arange(n))/rate/.75);music*=np.clip(fade,0,1)[:,None]
def write(name,y):
 with wave.open(str(assets/name),'wb') as f:f.setnchannels(y.shape[1]);f.setsampwidth(2);f.setframerate(rate);f.writeframes((np.clip(y,-1,1)*32767).astype('<i2').tobytes())
write('music-original.wav',music)
mix=voice[:,None]*np.ones((1,2))+music;write('mix-raw.wav',mix)
subprocess.run(['ffmpeg','-y','-v','error','-i',str(assets/'mix-raw.wav'),'-af','loudnorm=I=-16:TP=-1.3:LRA=9','-ar','48000','-ac','2',str(assets/'soundtrack.wav')],check=True)
subprocess.run(['ffmpeg','-y','-v','error','-i',str(assets/'voice.wav'),'-af','loudnorm=I=-16:TP=-1.3:LRA=9','-ar','48000','-ac','2',str(assets/'voice-only.wav')],check=True)
def tc(f):
 ms=round(f/30*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
(out/'captions.srt').write_text('\n\n'.join(f"{i+1}\n{tc(s['voice_start_frame'])} --> {tc(s['voice_end_frame']+6)}\n{s['text']}" for i,s in enumerate(timeline['segments']))+'\n')
(assets/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'duration_seconds':duration,'raw_capture_seconds':capture['duration'],'music':'original procedural score and transition sounds','audio':'local Chinese TTS, preset voice; no voice cloning'},ensure_ascii=False))
