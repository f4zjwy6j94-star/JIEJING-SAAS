"""Export and verify the continuous private-review film, with measured AV evidence."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-continuous-v4')
checks = []


def run(name, args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    checks.append({'check': name, 'exit_code': result.returncode})
    if result.returncode:
        raise RuntimeError(f'{name}: exit {result.returncode}: {result.stderr[-2000:]}')
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(frame, fps):
    ms = round(frame / fps * 1000)
    hours, rest = divmod(ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, rest = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{rest:03}'


def main():
    timeline = json.loads((OUT / 'voice-timeline.json').read_text())
    voice = json.loads((OUT / 'VOICE_CONTINUITY.safe.json').read_text())
    target = OUT / 'jiejing-continuous-v4.mp4'
    run('faststart_export', ['ffmpeg', '-hide_banner', '-y', '-i', str(OUT / 'render-source.mp4'),
        '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-movflags', '+faststart', str(target)])
    probe = json.loads(run('ffprobe', ['ffprobe', '-v', 'error', '-show_streams', '-show_format',
        '-of', 'json', str(target)]).stdout)
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    assert len(probe['streams']) == 2
    assert (video['width'], video['height']) == (1080, 1920)
    assert video['codec_name'] == 'h264' and video['pix_fmt'] == 'yuv420p'
    assert video['r_frame_rate'] == '30/1' and int(video['nb_frames']) == timeline['duration_frames']
    assert audio['codec_name'] == 'aac' and int(audio['sample_rate']) == 48000
    assert abs(float(probe['format']['duration']) - timeline['duration_frames'] / timeline['fps']) < .05
    checks.append({'check': 'stream_and_duration_contract', 'exit_code': 0})
    run('full_video_and_audio_decode', ['ffmpeg', '-v', 'error', '-xerror', '-i', str(target),
        '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
    run('standalone_voice_decode', ['ffmpeg', '-v', 'error', '-xerror', '-i',
        str(OUT / 'jiejing-continuous-narration-v4.mp3'), '-f', 'null', '-'])
    black = run('black_screen_detection', ['ffmpeg', '-hide_banner', '-i', str(target),
        '-an', '-vf', 'blackdetect=d=0.1:pix_th=0.05:pic_th=0.98', '-f', 'null', '-'])
    black_segments = re.findall(r'black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)', black.stderr)
    assert not black_segments, f'Black-screen intervals: {black_segments}'
    silence = run('exported_voice_silence_detection', ['ffmpeg', '-hide_banner', '-i', str(target),
        '-vn', '-af', 'silencedetect=noise=-48dB:d=0.38', '-f', 'null', '-'])
    intervals = []
    start = None
    for line in silence.stderr.splitlines():
        match = re.search(r'silence_start: ([\d.]+)', line)
        if match:
            start = float(match.group(1))
        match = re.search(r'silence_end: ([\d.]+)', line)
        if match and start is not None:
            intervals.append([start, float(match.group(1))])
            start = None
    # The final hold after the completed narration is distinct from an internal speech gap.
    internal = [p for p in intervals if p[0] > .2 and p[1] < timeline['voice_seconds'] - .3]
    assert not internal, f'Long internal audio gaps: {internal}'
    assert voice['metadata_covers_full_text'] and not voice['scene_padding_added']
    loudness = run('exported_loudness_measurement', ['ffmpeg', '-hide_banner', '-i', str(target),
        '-vn', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json', '-f', 'null', '-'])
    # FFmpeg can append progress text after the meter's JSON object.
    meter, _ = json.JSONDecoder().raw_decode(loudness.stderr[loudness.stderr.rfind('{'):])
    assert -18 <= float(meter['input_i']) <= -14 and float(meter['input_tp']) <= 0
    captions = timeline['captions']
    assert all(0 <= c['from'] < c['to'] <= timeline['duration_frames'] for c in captions)
    assert all(a['to'] == b['from'] for a, b in zip(captions, captions[1:]))
    assert ''.join(c['text'] for c in captions) == (OUT / 'narration-display.txt').read_text().strip()
    srt = []
    for i, cap in enumerate(captions, 1):
        text = cap['text'].replace('亚马逊、TikTok Shop', '亚马逊、\nTikTok Shop')
        srt.append(f"{i}\n{timestamp(cap['from'], timeline['fps'])} --> {timestamp(cap['to'], timeline['fps'])}\n{text}\n")
    (OUT / 'captions.srt').write_text('\n'.join(srt))
    checks.append({'check': 'full_script_caption_coverage', 'exit_code': 0})
    final_frames = OUT / 'final-frames'
    final_frames.mkdir(exist_ok=True)
    for frame in [220, 332, 430, 782, 1085, 1405, 1570]:
        run(f'export_frame_{frame}', ['ffmpeg', '-v', 'error', '-y', '-i', str(target),
            '-vf', f'select=eq(n\\,{frame})', '-frames:v', '1', str(final_frames / f'frame-{frame}.png')])
    return {'exit_code': 0, 'checks': checks, 'video': {'path': target.name,
        'bytes': target.stat().st_size, 'sha256': sha(target), 'width': video['width'], 'height': video['height'],
        'fps': 30, 'frames': int(video['nb_frames']), 'seconds': float(probe['format']['duration']),
        'codec': 'h264', 'pixel_format': 'yuv420p', 'audio_codec': 'aac', 'audio_sample_rate': 48000},
        'voice_seconds': timeline['voice_seconds'], 'internal_silence_at_least_0_38_seconds': internal,
        'all_detected_silences_including_ending_hold': intervals, 'black_intervals': black_segments,
        'integrated_lufs': float(meter['input_i']), 'true_peak_dbtp': float(meter['input_tp']),
        'caption_count': len(captions), 'metadata_covers_full_narration': True,
        'one_continuous_narration_with_no_scene_padding': True, 'synthetic_voice': True,
        'human_voice_claimed': False, 'subjective_fluency_certified': False,
        'current_supported_platform': 'eBay', 'future_plans_not_current': ['Amazon', 'TikTok Shop', '抖音', '更多电商平台'],
        'owner_full_film_approval': False, 'public_posting': False, 'production_access': False,
        'full_274_gate_rerun': False}


if __name__ == '__main__':
    try:
        result = main()
    except (OSError, ValueError, KeyError, RuntimeError, AssertionError, subprocess.SubprocessError) as exc:
        result = {'exit_code': 1, 'checks': checks, 'error': str(exc)}
    (OUT / 'VIDEO_QA.safe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result['exit_code'])
