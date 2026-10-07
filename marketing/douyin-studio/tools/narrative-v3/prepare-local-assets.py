"""Rebuild local font subsets and copy the saved audition. No external voice call."""
from pathlib import Path
import shutil
from fontTools import subset

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-narrative-rework-v3')
ASSETS = OUT / 'assets/narrative-v3'
ASSETS.mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / 'public/brand/jiejing-app-icon.svg', ASSETS / 'brand.svg')
shutil.copy2(OUT / 'voice-A-yunxi.mp3', ASSETS / 'voice-A-yunxi.mp3')
text = (ROOT / 'src/Douyin11NarrativeV3.tsx').read_text() + ''.join(chr(i) for i in range(32, 127))
options = subset.Options()
options.font_number = 2
options.layout_features = ['*']
options.notdef_glyph = True
for weight, name in [('Regular', 'narrative-sans.otf'), ('Bold', 'narrative-bold.otf')]:
    font = subset.load_font('/usr/share/fonts/opentype/noto/NotoSansCJK-' + weight + '.ttc', options)
    cutter = subset.Subsetter(options=options)
    cutter.populate(text=text)
    cutter.subset(font)
    subset.save_font(font, str(ASSETS / name), options)
print('LOCAL_ASSETS_OK')
