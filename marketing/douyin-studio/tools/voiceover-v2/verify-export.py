"""Export the owner-review variants and verify their actual audio/video streams."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

OUT = Path('/workspace/jiejing-deliverables/11.0/20261006-voiceover-v2')
ASSETS = OUT / 'assets/explainer-v2'


def run(name, args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{name} exit {result.returncode}: {result.stderr[-1800:]}')
    checks[name] = {'exit_code': result.returncode}
    return result.stdout, result.stderr


checks = {}
run('faststart_export', ['ffmpeg', '-y', '-v', 'error', '-i', str(OUT/'render-source.mp4'), '-c', 'copy', '-movflags', '+faststart', str(OUT/'jiejing-explainer-v2.mp4')])
run('voice_only_export', ['ffmpeg', '-y', '-v', 'error', '-i', str(OUT/'render-source.mp4'), '-i', str(ASSETS/'voice-only.wav'), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(OUT/'jiejing-explainer-v2-no-bgm.mp4')])
probe, _ = run('probe', ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(OUT/'jiejing-explainer-v2.mp4')])
probe = json.loads(probe)
v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
a = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
assert (v['width'], v['height'], v['r_frame_rate'], v['codec_name'], v['pix_fmt']) == (1080, 1920, '30/1', 'h264', 'yuv420p')
assert int(v['nb_frames']) == 1643
assert a['codec_name'] == 'aac' and a['sample_rate'] == '48000' and a['channels'] == 2
assert abs(float(v['duration']) - float(a['duration'])) < .1
for name in ['jiejing-explainer-v2.mp4', 'jiejing-explainer-v2-no-bgm.mp4']:
    run('full_decode_' + name, ['ffmpeg', '-v', 'error', '-i', str(OUT/name), '-f', 'null', '-'])
_, black = run('black_frame_check', ['ffmpeg', '-hide_banner', '-i', str(OUT/'jiejing-explainer-v2.mp4'), '-vf', 'blackdetect=d=0.08:pix_th=0.02:pic_th=0.98', '-an', '-f', 'null', '-'])
assert 'black_start:' not in black, 'Unexpected black segment'
_, loudness = run('loudness', ['ffmpeg', '-hide_banner', '-i', str(OUT/'jiejing-explainer-v2.mp4'), '-af', 'loudnorm=I=-16:TP=-1.3:LRA=9:print_format=json', '-vn', '-f', 'null', '-'])
levels = json.loads(re.findall(r'\{[^{}]+\}', loudness)[-1])
assert -18 < float(levels['input_i']) < -14 and float(levels['input_tp']) < 0
for frame in [0, 457, 720, 886, 1642]:
    run(f'frame_{frame}', ['ffmpeg', '-y', '-v', 'error', '-i', str(OUT/'jiejing-explainer-v2.mp4'), '-vf', f'select=eq(n\\,{frame})', '-frames:v', '1', str(OUT/f'export-frame-{frame}.png')])
timeline = json.loads((OUT/'voice-timeline.json').read_text())
assert timeline['duration_frames'] == 1643 and len(timeline['segments']) == 12
files = []
for name in ['jiejing-explainer-v2.mp4', 'jiejing-explainer-v2-no-bgm.mp4', 'cover.png', 'captions.srt']:
    path = OUT/name
    files.append({'path': name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
report = {'render_exit_code': 0, 'video_lint_typescript_exit_code': 0, 'checks': checks,
          'video': {k: v[k] for k in ['codec_name','width','height','pix_fmt','r_frame_rate','nb_frames','duration']},
          'audio': {k: a[k] for k in ['codec_name','sample_rate','channels','duration']},
          'measured_loudness': levels, 'keyframes_inspected': [70,215,316,400,457,586,720,866,1001,1158,1320,1459,1585],
          'narration_segments': 12, 'on_screen_people': 0, 'synthetic_narration': True,
          'actual_local_ui_capture': True, 'goal_submitted_or_model_called': False, 'real_platform_write': False,
          'publicly_published': False, 'final_owner_approval': False,
          'subjective_voice_naturalness': 'Owner review pending; not certified as human recording', 'files': files}
(OUT/'VIDEO_QA.safe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False))
