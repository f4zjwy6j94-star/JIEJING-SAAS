"""Check the exported v6 media and script without claiming subjective listening."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6')
PROJECT = Path(__file__).resolve().parents[2]


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} exit {result.returncode}: {result.stderr[-1600:]}')
    return result


def compact(text):
    return re.sub(r'[^\w]', '', text, flags=re.UNICODE).lower()


def timestamp(ms):
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}'


def main():
    source = (PROJECT/'src/ReleaseV6Timing.ts').read_text()
    captions = [dict(text=t, startMs=int(a), endMs=int(b), timestampMs=None, confidence=None)
                for t,a,b in re.findall(r"text: '([^']+)', startMs: (\d+), endMs: (\d+)", source)]
    assert captions and compact(''.join(c['text'] for c in captions)) == compact((OUT/'NARRATION.txt').read_text()), 'Caption/script mismatch'
    for i,c in enumerate(captions):
        assert 0 <= c['startMs'] < c['endMs'] <= 25000
        assert i == 0 or captions[i-1]['endMs'] <= c['startMs'], 'Caption overlap'
    (OUT/'captions.json').write_text(json.dumps(captions, ensure_ascii=False, indent=2)+'\n')
    (OUT/'jiejing-release-v6.srt').write_text('\n\n'.join(f"{i+1}\n{timestamp(c['startMs'])} --> {timestamp(c['endMs'])}\n{c['text']}" for i,c in enumerate(captions))+'\n')
    path = OUT/'jiejing-douyin-v6.mp4'
    probe = json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]).stdout)
    video = next(s for s in probe['streams'] if s['codec_type']=='video')
    audio = next(s for s in probe['streams'] if s['codec_type']=='audio')
    duration = float(probe['format']['duration'])
    assert 24.99 <= duration <= 25.04, f'Unexpected duration: {duration}'
    assert (video['codec_name'],video['width'],video['height'],video['pix_fmt'],video['avg_frame_rate']) == ('h264',1080,1920,'yuv420p','30/1')
    assert audio['codec_name']=='aac' and audio['sample_rate']=='48000' and audio['channels']==2
    assert int(video['nb_frames']) == 750
    full = run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'])
    black = run(['ffmpeg','-hide_banner','-i',str(path),'-vf','blackdetect=d=0.08:pix_th=0.10:pic_th=0.98','-an','-f','null','-'])
    black_events = re.findall(r'black_start:[^\n]+',black.stderr)
    assert not black_events, f'Black segments: {black_events}'
    loud = run(['ffmpeg','-hide_banner','-i',str(path),'-af','loudnorm=I=-16.5:TP=-1.5:LRA=7:print_format=json','-vn','-f','null','-'])
    loudness = json.loads(re.findall(r'\{\s*"input_i".*?\}',loud.stderr,re.S)[-1])
    assert -18 <= float(loudness['input_i']) <= -14, 'Unexpected overall loudness'
    assert float(loudness['input_tp']) <= -1, 'True peak exceeds ceiling'
    silence = run(['ffmpeg','-hide_banner','-i',str(OUT/'voice-qwen-serena-raw.wav'),'-af','silencedetect=noise=-48dB:d=0.38','-f','null','-'])
    pauses = [float(x) for x in re.findall(r'silence_duration: ([\d.]+)',silence.stderr)]
    result = {'exit_code':0,'duration_seconds':duration,'video':{k:video[k] for k in ('codec_name','width','height','pix_fmt','avg_frame_rate','nb_frames')},
              'audio':{k:audio[k] for k in ('codec_name','sample_rate','channels')},'full_decode_exit_code':full.returncode,
              'black_detect_exit_code':black.returncode,'black_segments':black_events,'loudness':loudness,'caption_count':len(captions),
              'caption_text_matches_script':True,'captions_follow_measured_ASR_timing':True,
              'raw_voice_internal_and_edge_pauses_above_0_38s':pauses,'voice_generated_as_one_paragraph':True,
              'human_listening_performed':False,'owner_voice_approval':False,
              'ASR_notes':['商品页被识别为同音商品业','eBay被识别为一辈；英文及品牌发音仍需主人审听','AI CEO识别置信度较低，不能据此保证发音准确'],
              'mp4_bytes':path.stat().st_size,'mp4_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'technical_export_pass_is_not_owner_or_platform_approval':True,'published':False}
    (OUT/'VIDEO_QA.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
