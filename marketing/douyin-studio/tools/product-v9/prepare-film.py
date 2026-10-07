"""Prepare v9 from verified private inputs; no product services or credentials."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

OUT = Path(os.environ.get('JIEJING_V9_OUTPUT', '/workspace/jiejing-deliverables/11.0/20261007-product-rework-v9'))
SOURCE = Path(__file__).resolve().parents[2] / 'hyperframes/product-v9'
FILM = OUT / 'film'
ASSETS = FILM / 'assets'
ASSETS.mkdir(parents=True, exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def run(args):
    subprocess.run(args, check=True, capture_output=True, text=True)

voice = OUT / 'voice-qwen-serena-raw.wav'
assert sha(voice) == 'bac5fb118f852b029f49a1538ba5d568bc1023edd1497f6fc3bcd0a867b91e1e'
shutil.copy2(SOURCE / 'index.html', FILM / 'index.html')
for name, src in {
    'workspace.png': OUT / 'actual-ui/03-input.png',
    'title-after.png': OUT / 'actual-ui/06-title-after.png',
}.items():
    if not src.is_file():
        raise FileNotFoundError(src)
    shutil.copy2(src, ASSETS / name)

gsap = ASSETS / 'gsap.min.js'
gsap_url = 'https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js'
if not gsap.exists():
    with urllib.request.urlopen(gsap_url, timeout=30) as response:
        gsap.write_bytes(response.read())
assert '3.14.2' in gsap.read_text()[:500]

run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(voice),
     '-af','loudnorm=I=-17:TP=-2:LRA=7,aresample=48000,adelay=300,apad,atrim=duration=29',
     '-ac','2',str(ASSETS / 'voice.wav')])
music = OUT.parent / '20261007-release-film-v6/music-original.wav'
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ASSETS / 'voice.wav'),
     '-stream_loop','-1','-i',str(music),'-filter_complex',
     '[1:a]volume=0.14,afade=t=in:d=0.8,afade=t=out:st=26.4:d=2.6,atrim=duration=29[m];'
     '[0:a][m]amix=inputs=2:normalize=0,loudnorm=I=-16.5:TP=-1.5:LRA=8,aresample=48000[a]',
     '-map','[a]','-t','29','-ac','2',str(ASSETS / 'mix.wav')])
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ASSETS / 'voice.wav'),
     '-c:a','libmp3lame','-b:a','192k',str(OUT / 'jiejing-v9-voice.mp3')])

captions = [(.3,1.85,'做跨境电商'),(1.94,4.75,'麻烦的往往是上架前那一堆事'),
(4.98,5.98,'查资料'),(6.08,6.98,'写商品页'),(7.2,8.6,'还要准备图片'),
(8.96,11.84,'捷境把这些工作放在一个网站里'),(12.3,13.85,'用中文说清需求'),
(14.08,15.97,'给它真实的图片和参数'),(16.18,18.35,'它协助你调研、准备内容'),
(18.54,20.7,'哪里不合适，接着改'),(20.88,21.72,'你核对'),(21.86,22.8,'检查通过'),
(22.92,24.18,'再确认发布'),(24.54,26.8,'目前先支持 eBay')]
def stamp(t):
    ms = round(t*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
(OUT / 'jiejing-v9.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{c}' for i,(a,b,c) in enumerate(captions))+'\n')
(OUT / 'AUDIO_PREPARATION.safe.json').write_text(json.dumps({
    'exit_code':0,'voice_source_sha256':sha(voice),'voice_raw_seconds':25.92,
    'voice_lead_seconds':.3,'film_seconds':29,'voice_whole_paragraph':True,
    'voice_per_scene_cuts':False,'voice_speed_changed':False,'human_recording':False,
    'model':'Qwen3-TTS 0.6B CustomVoice / Serena','music':'Original existing v6 procedural bed',
    'gsap':{'version':'3.14.2','source':gsap_url,'sha256':sha(gsap)},
    'asr_limitations':['品牌被转写为同音近似词；以正式品牌捷境校正字幕','易贝低置信度；字幕使用eBay','ASR未转写它，不能单凭此证明漏读'],
    'assets':[{ 'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(ASSETS.iterdir()) if p.is_file()],
},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'exit_code':0,'film':str(FILM),'audio_seconds':29,'captions':len(captions)}))
