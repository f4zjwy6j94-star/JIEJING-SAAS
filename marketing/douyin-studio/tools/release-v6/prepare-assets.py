from pathlib import Path
from fontTools import subset
import shutil, json, hashlib

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6')
ASSETS = OUT / 'assets/release-v6'
ASSETS.mkdir(parents=True, exist_ok=True)
old = Path('/workspace/jiejing-deliverables/11.0/20261007-continuous-v4/assets/continuous-v4')
items=[]
for name in ['brand.svg','goal.mp4','workspace-goal.png']:
    source=old/name;target=ASSETS/name;shutil.copy2(source,target)
    items.append({'source':str(source),'destination':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
text=(ROOT/'src/Douyin11ReleaseV6.tsx').read_text()+(ROOT/'src/ReleaseV6Timing.ts').read_text()+''.join(chr(i) for i in range(32,127))
options=subset.Options();options.font_number=2;options.layout_features=['*'];options.notdef_glyph=True
for weight,name in [('Regular','sans.otf'),('Bold','bold.otf')]:
    font=subset.load_font('/usr/share/fonts/opentype/noto/NotoSansCJK-'+weight+'.ttc',options)
    sub=subset.Subsetter(options=options);sub.populate(text=text);sub.subset(font);subset.save_font(font,str(ASSETS/name),options)
(OUT/'licenses').mkdir(exist_ok=True)
shutil.copy2('/workspace/jiejing-deliverables/11.0/20261007-continuous-v4/licenses/Noto-CJK-copyright.txt',OUT/'licenses/Noto-CJK-copyright.txt')
(OUT/'EXISTING_ASSETS.safe.json').write_text(json.dumps({'files':items,'product_photos_used':False,'product_graphic':'Original generic SVG package','existing_input_clip_reused':True,'model_results_or_publishing_simulated_as_real':False},ensure_ascii=False,indent=2)+'\n')
print('ASSETS_READY')
