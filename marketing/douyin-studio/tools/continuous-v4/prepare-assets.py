"""Prepare approved existing assets and local fonts for the continuous explainer."""
from pathlib import Path
import hashlib
import json
import shutil
from fontTools import subset

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-continuous-v4')
ASSETS = OUT / 'assets/continuous-v4'
ASSETS.mkdir(parents=True, exist_ok=True)
old = Path('/workspace/jiejing-deliverables/11.0/20261006-voiceover-v2')
sources = {'brand.svg': ROOT / 'public/brand/jiejing-app-icon.svg',
    'goal.mp4': old / 'assets/explainer-v2/goal.mp4',
    'workspace-goal.png': old / 'assets/explainer-v2/workspace-goal.png'}
receipt = []
for name, source in sources.items():
    target = ASSETS / name
    shutil.copy2(source, target)
    receipt.append({'source': str(source), 'destination': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
text = (ROOT / 'src/Douyin11ContinuousV4.tsx').read_text() + (ROOT / 'src/ContinuousV4Timing.ts').read_text() + ''.join(chr(i) for i in range(32, 127))
options = subset.Options()
options.font_number = 2
options.layout_features = ['*']
options.notdef_glyph = True
for weight, name in [('Regular', 'sans.otf'), ('Bold', 'bold.otf')]:
    font = subset.load_font('/usr/share/fonts/opentype/noto/NotoSansCJK-' + weight + '.ttc', options)
    sub = subset.Subsetter(options=options)
    sub.populate(text=text)
    sub.subset(font)
    subset.save_font(font, str(ASSETS / name), options)
(OUT / 'licenses').mkdir(exist_ok=True)
shutil.copy2(old / 'licenses/Noto-CJK-copyright.txt', OUT / 'licenses/Noto-CJK-copyright.txt')
(OUT / 'EXISTING_ASSETS.safe.json').write_text(json.dumps({'files': receipt, 'new_product_flow_run': False,
    'actual_input_recording_reused': True, 'recorded_goal_was_submitted': False}, ensure_ascii=False, indent=2) + '\n')
print('ASSETS_OK')
