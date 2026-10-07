"""Export and verify the 16-second private direction study; no subjective approval."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-narrative-rework-v3')
checks = {}


def run(label, args):
    result = subprocess.run(args, capture_output=True, text=True)
    checks[label] = {'exit_code': result.returncode}
    if result.returncode:
        raise RuntimeError(f'{label} exited {result.returncode}: {result.stderr[-1500:]}')
    return result


target = OUT / 'jiejing-narrative-v3-opening.mp4'
run('final_export', ['ffmpeg', '-y', '-v', 'error', '-i', str(OUT / 'render-source.mp4'),
    '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=7',
    '-ar', '48000', '-ac', '2', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(target)])
probe = json.loads(run('probe', ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(target)]).stdout)
video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
assert (video['width'], video['height'], video['r_frame_rate'], video['nb_frames']) == (1080, 1920, '30/1', '480')
assert video['codec_name'] == 'h264' and video['pix_fmt'] == 'yuv420p'
assert audio['codec_name'] == 'aac' and audio['sample_rate'] == '48000'
run('complete_audio_video_decode', ['ffmpeg', '-v', 'error', '-i', str(target), '-f', 'null', '-'])
black = run('black_frame_check', ['ffmpeg', '-hide_banner', '-i', str(target), '-vf', 'blackdetect=d=0.08:pix_th=0.02:pic_th=0.98', '-an', '-f', 'null', '-'])
assert 'black_start:' not in black.stderr
loud = run('loudness', ['ffmpeg', '-hide_banner', '-i', str(target), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json', '-vn', '-f', 'null', '-'])
measure = json.loads(re.findall(r'\{[\s\S]*?\}', loud.stderr)[-1])
assert float(measure['input_tp']) <= -0.5
for frame in [0, 85, 180, 337, 458, 479]:
    run(f'export_frame_{frame}', ['ffmpeg', '-y', '-v', 'error', '-i', str(target), '-vf', f'select=eq(n\\,{frame})', '-frames:v', '1', str(OUT / f'export-frame-{frame}.png')])
report = {'checks': checks, 'video': {k: video[k] for k in ['codec_name', 'width', 'height', 'r_frame_rate', 'nb_frames', 'duration']},
    'measured_loudness': measure, 'file': {'path': target.name, 'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()},
    'same_product_continuous_scene': True, 'web_screenshot_count': 0, 'real_product_execution_recording': False,
    'synthetic_voice': True, 'human_voice_or_naturalness_certified': False, 'complete_v3_film': False,
    'owner_creative_approval': False, 'public_release': False}
(OUT / 'REWORK_QA.safe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
