"""Build v10 from the measured narration timeline and hash-checked private inputs."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess

OUT = Path(os.environ.get('JIEJING_V10_OUTPUT', '/workspace/jiejing-deliverables/11.0/20261007-ai-commerce-v10'))
PRIOR = OUT.parent / '20261007-product-rework-v9'
SOURCE = Path(__file__).resolve().parents[2] / 'hyperframes/commerce-v10'
FILM = OUT / 'film'
ASSETS = FILM / 'assets'
ASSETS.mkdir(parents=True, exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)

receipt = json.loads((PRIOR / 'ASSET_RECEIPT.safe.json').read_text())
records = receipt['files']
if isinstance(records, dict):
    records = [dict(value, path=key) for key, value in records.items()]
prior_hashes = {r.get('path', r.get('relative_path')): r['sha256'] for r in records}
for name in ['gsap.min.js', 'brand.svg', 'original-product.jpg', 'workspace.png', 'title-after.png']:
    rel = 'film/assets/' + name
    p = PRIOR / rel
    assert sha(p) == prior_hashes[rel], f'Prior verified asset changed: {p}'
    shutil.copy2(p, ASSETS / name)

timing = json.loads((OUT / 'TIMING.json').read_text())
duration = timing['duration']
assert timing['source'] == 'measured_local_voice_asr_with_disclosed_text_alignment'
assert timing['scenes'][0]['start'] == 0 and timing['scenes'][-1]['end'] == duration
template = (SOURCE / 'index.template.html').read_text()
html = template.replace('__DURATION__', str(duration)).replace('__TIMING_DATA__', json.dumps(timing, ensure_ascii=False))
(FILM / 'index.html').write_text(html)
shutil.copy2(SOURCE / 'DESIGN.md', FILM / 'DESIGN.md')
shutil.copy2(PRIOR / 'film/hyperframes.json', FILM / 'hyperframes.json')

from fontTools.ttLib import TTCollection
from fontTools import subset
text = html + (OUT / 'NARRATION.txt').read_text()
fonts = []
for filename, source in [('serif-bold.otf','NotoSerifCJK-Bold.ttc'),('sans.otf','NotoSansCJK-Regular.ttc'),('bold.otf','NotoSansCJK-Bold.ttc')]:
    original = Path('/usr/share/fonts/opentype/noto') / source
    collection = TTCollection(original)
    font = collection.fonts[2]
    name = font['name'].getDebugName(1)
    assert 'SC' in name, name
    options = subset.Options()
    options.name_IDs = ['*']
    worker = subset.Subsetter(options=options)
    worker.populate(text=text)
    worker.subset(font)
    font.save(ASSETS / filename)
    fonts.append({'source':str(original),'source_sha256':sha(original),'family':name,'subset':filename,'sha256':sha(ASSETS / filename)})
    collection.close()

voice = OUT / 'voice-qwen-serena-raw.wav'
generation = json.loads((OUT / 'QWEN_LOCAL_GENERATION.safe.json').read_text())
assert sha(voice) == generation['sha256']
assert generation['seconds'] + .3 <= duration
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(voice),'-af',f'loudnorm=I=-17:TP=-2:LRA=7,aresample=48000,adelay=300,apad,atrim=duration={duration}','-ac','2',str(ASSETS / 'voice.wav')])
music = OUT.parent / '20261007-release-film-v6/music-original.wav'
assert music.is_file()
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ASSETS / 'voice.wav'),'-stream_loop','-1','-i',str(music),'-filter_complex',f'[1:a]volume=0.11,afade=t=in:d=0.8,afade=t=out:st={duration-2.7}:d=2.7,atrim=duration={duration}[m];[0:a][m]amix=inputs=2:normalize=0,loudnorm=I=-16.5:TP=-1.5:LRA=8,aresample=48000[a]','-map','[a]','-t',str(duration),'-ac','2',str(ASSETS / 'mix.wav')])
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ASSETS / 'voice.wav'),'-c:a','libmp3lame','-b:a','192k',str(OUT / 'jiejing-v10-voice.mp3')])
def stamp(t):
    n=round(t*1000)
    return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'
(OUT / 'jiejing-v10.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(timing['captions']))+'\n')
data = {'exit_code':0,'voice_source_sha256':sha(voice),'voice_raw_seconds':generation['seconds'],'voice_lead_seconds':.3,'film_seconds':duration,'whole_paragraph':True,'voice_per_scene_cuts':False,'voice_speed_changed':False,'human_recording':False,'fonts':fonts,'music_source':str(music),'music_sha256':sha(music),'prior_assets_hash_verified':True,'network_used':False}
(OUT / 'AUDIO_PREPARATION.safe.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'exit_code':0,'film_seconds':duration,'captions':len(timing['captions']),'scenes':len(timing['scenes'])}))
