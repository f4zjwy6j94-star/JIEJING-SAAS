from pathlib import Path
import json,subprocess,re,hashlib
import numpy as np
import soundfile as sf

OUT=Path('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6')
ASSETS=OUT/'assets/release-v6'
rate=48000

def command(args):
    r=subprocess.run(args,capture_output=True,text=True,timeout=90)
    if r.returncode:raise RuntimeError(f'Audio command exited {r.returncode}: {r.stderr[-1200:]}')
    return r

raw=OUT/'voice-qwen-serena-raw.wav'
assert raw.is_file()
command(['ffmpeg','-y','-v','error','-i',str(raw),'-af','highpass=f=70,loudnorm=I=-17:TP=-1.8:LRA=8','-ar',str(rate),'-ac','1',str(OUT/'voice-normalized.wav')])
voice,sr=sf.read(OUT/'voice-normalized.wav');assert sr==rate and voice.ndim==1
# Preserve all internal phrasing; add only a short ending hold.
duration=max(25.0,len(voice)/rate+.75)
assert duration<=30.0, f'Voice too long for requested film: {duration:.3f}s; shorten text instead of rushing it'
frames=int(np.ceil(duration*30));duration=frames/30
n=int(duration*rate);v=np.zeros(n,dtype=np.float64);v[:len(voice)]=voice
t=np.arange(n)/rate;music=np.zeros(n,dtype=np.float64)
beat=60/112
roots=[130.8128,87.3071,103.8262,116.5409]
for i,at in enumerate(np.arange(0,duration,beat/2)):
    start=int(at*rate);length=min(n-start,int(.48*rate));tt=np.arange(length)/rate
    root=roots[(i//8)%4]
    frequency=root*(2 if i%2 else 1)
    envelope=(1-np.exp(-tt*110))*np.exp(-tt*8)
    note=(np.sin(2*np.pi*frequency*tt)+.18*np.sin(2*np.pi*frequency*2*tt))*envelope
    music[start:start+length]+=.055*note
    if i%4==0:
        kick=np.sin(2*np.pi*(50*tt+14*(1-np.exp(-tt*24))))*np.exp(-tt*21)
        music[start:start+length]+=.065*kick
for bar in np.arange(0,duration,beat*8):
    start=int(bar*rate);length=min(n-start,int(beat*8*rate));tt=np.arange(length)/rate
    root=roots[int(bar/(beat*8))%4]
    pad=sum(np.sin(2*np.pi*root*r*tt) for r in [2,2.5,3])/3
    env=np.minimum(tt/.3,1)*np.minimum((len(tt)/rate-tt)/.65,1)
    music[start:start+length]+=.018*pad*env
# Gentle original musical bed; no third-party stock track or imitated melody.
fade=np.minimum(t/.45,1)*np.minimum((duration-t)/.85,1)
music*=fade
sf.write(OUT/'music-original.wav',music,rate,subtype='PCM_16')
sf.write(OUT/'voice-with-hold.wav',v,rate,subtype='PCM_16')
sf.write(OUT/'mix-before-master.wav',v+music,rate,subtype='PCM_16')
command(['ffmpeg','-y','-v','error','-i',str(OUT/'mix-before-master.wav'),'-af','loudnorm=I=-16.5:TP=-1.5:LRA=8','-ar',str(rate),'-ac','2',str(ASSETS/'soundtrack.wav')])
command(['ffmpeg','-y','-v','error','-i',str(OUT/'voice-normalized.wav'),'-c:a','libmp3lame','-b:a','192k',str(OUT/'jiejing-release-v6-narration.mp3')])
result={'exit_code':0,'seconds':duration,'frames':frames,'voice_seconds':len(voice)/rate,'sample_rate':rate,'music':'Original procedural composition for this film; no stock song','voice_generated_in_one_paragraph':True,'internal_silence_removed':False,'speed_or_pitch_changed':False,'soundtrack_sha256':hashlib.sha256((ASSETS/'soundtrack.wav').read_bytes()).hexdigest()}
(OUT/'SOUND_PREP.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
