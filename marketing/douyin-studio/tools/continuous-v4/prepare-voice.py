"""Tighten only verified long quiet intervals, then time visuals from the complete voice."""
from pathlib import Path
import json
import math
import re
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-continuous-v4')
ASSETS = OUT / 'assets/continuous-v4'
ASSETS.mkdir(parents=True, exist_ok=True)


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f'Audio command exit {p.returncode}: {p.stderr[-1200:]}')
    return p


def silence(path):
    p = run(['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'silencedetect=noise=-48dB:d=0.38', '-f', 'null', '-'])
    pairs = re.findall(r'silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)', p.stderr)
    return [(float(a), float(b)) for a, b in pairs]


run(['ffmpeg', '-y', '-v', 'error', '-i', str(OUT / 'voice-raw.mp3'), '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', str(OUT / 'voice-raw.wav')])
with wave.open(str(OUT / 'voice-raw.wav'), 'rb') as wav:
    rate = wav.getframerate()
    assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
    samples = wav.readframes(wav.getnframes())
raw_seconds = len(samples) / 2 / rate
quiet = silence(OUT / 'voice-raw.wav')
cuts = []
for start, end in quiet:
    if end >= raw_seconds - .02:
        # Keep a short tail after the last word, with no repeated scene padding.
        a, b = start + .26, end
    elif start <= .02:
        a, b = start, end - .10
    else:
        # Preserve both quiet margins; no time stretch or voiced samples are removed.
        a, b = start + .13, end - .13
    if b > a:
        cuts.append((int(a * rate), int(b * rate)))
pieces = []
cursor = 0
for a, b in cuts:
    assert a >= cursor and b > a
    pieces.append(samples[cursor * 2:a * 2])
    cursor = b
pieces.append(samples[cursor * 2:])
edited = b''.join(pieces)
with wave.open(str(OUT / 'voice-continuous-unmixed.wav'), 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(rate)
    wav.writeframes(edited)
run(['ffmpeg', '-y', '-v', 'error', '-i', str(OUT / 'voice-continuous-unmixed.wav'), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=7', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(ASSETS / 'voice-continuous.wav')])
run(['ffmpeg', '-y', '-v', 'error', '-i', str(ASSETS / 'voice-continuous.wav'), '-c:a', 'libmp3lame', '-b:a', '192k', str(OUT / 'jiejing-continuous-narration-v4.mp3')])


def shifted(seconds):
    n = seconds * rate
    removed = sum(max(0, min(n, b) - a) for a, b in cuts if n > a)
    return max(0, (n - removed) / rate)


def norm(text):
    return ''.join(c.lower() for c in text if c.isalnum())


spoken = (OUT / 'narration-spoken.txt').read_text().strip()
metadata = [json.loads(line) for line in (OUT / 'voice-raw.jsonl').read_text().splitlines()]
words = [w for w in metadata if w['type'] == 'WordBoundary']
assert ''.join(norm(w['text']) for w in words) == norm(spoken), 'Voice word metadata does not cover the complete narration'
cursor = 0
timed = []
for word in words:
    count = len(norm(word['text']))
    timed.append({'text': word['text'], 'char_start': cursor, 'char_end': cursor + count,
        'start': shifted(word['offset'] / 1e7), 'end': shifted((word['offset'] + word['duration']) / 1e7)})
    cursor += count


def word_at(char):
    return next(w for w in timed if w['char_start'] <= char < w['char_end'])


captions = []
cursor = 0
for phrase in re.findall(r'[^，。！？；]+[，。！？；]?', spoken):
    count = len(norm(phrase))
    first = word_at(cursor)
    last = word_at(cursor + count - 1)
    captions.append({'text': phrase.replace('易贝', 'eBay'), 'from': round(first['start'] * 30), 'to': round(last['end'] * 30) + 5})
    cursor += count
for current, nxt in zip(captions, captions[1:]):
    current['to'] = nxt['from']
anchors = {}
for key, phrase in {'workspace':'所以捷境', 'goal':'比如你想', 'prepare':'捷境会围绕', 'revise':'你可以接着',
    'confirm':'准备好以后', 'assist':'后续的客服', 'roadmap':'现在先支持', 'planned':'后续计划', 'cta':'想试试'}.items():
    start = spoken.index(phrase)
    anchors[key] = round(word_at(len(norm(spoken[:start])))['start'] * 30)
final_seconds = len(edited) / 2 / rate
frames = math.ceil((final_seconds + .65) * 30)
timeline = {'fps':30, 'duration_frames':frames, 'voice_seconds':final_seconds, 'captions':captions, 'anchors':anchors, 'word_count':len(timed)}
(OUT / 'voice-timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + '\n')
(ROOT / 'src/ContinuousV4Timing.ts').write_text('export const continuousTiming = ' + json.dumps(timeline, ensure_ascii=False, indent=2) + ' as const;\n')
post = silence(ASSETS / 'voice-continuous.wav')
internal_post = [(a, b) for a, b in post if a > .02 and b < final_seconds - .02]
assert not internal_post, f'Long internal quiet intervals remain: {internal_post}'
report = {'exit_code':0, 'raw_seconds':raw_seconds, 'continuous_seconds':final_seconds, 'video_frames':frames,
    'quiet_threshold_db':-48, 'long_quiet_threshold_seconds':.38, 'retained_internal_pause_seconds':.26,
    'raw_long_quiet_intervals':quiet, 'removed_only_quiet_sample_intervals':cuts, 'removed_seconds':raw_seconds-final_seconds,
    'remaining_long_internal_quiet_intervals':internal_post, 'metadata_covers_full_text':True,
    'speech_speedup_or_pitch_change_in_edit':False, 'scene_padding_added':False,
    'single_global_audio_track':True, 'subjective_fluency_certified':False}
(OUT / 'VOICE_CONTINUITY.safe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'exit_code':0,'raw_seconds':raw_seconds,'continuous_seconds':final_seconds,'cut_count':len(cuts),'remaining_long_internal_gaps':len(internal_post),'anchors':anchors,'frames':frames},ensure_ascii=False))
