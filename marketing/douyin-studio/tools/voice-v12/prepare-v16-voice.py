"""Join verified new fictional-voice takes; no network, retiming or source overwrite."""
import argparse
import hashlib
import json
from pathlib import Path
import wave

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
if not args.root.is_absolute() or not args.output.is_absolute() or args.output.exists():
    raise SystemExit("Existing source root and fresh absolute output directory required")
sources = [
    ("codec-bf16-02/voice-bf16-trial-01.wav", "90f7a8abfd753bff8acfecba712fc08560d1a828b622fdebd0ea2f5db5237383", "这张写十一点五，那张写二十。这个尺寸，先别抄。"),
    ("voice-full-01/voice-02.wav", "1ef0421fb46fc92fdb20f64721d24adf6803e54cc5da8cb0ce8df2afe3658699", "先问清实物和包装各多大，再要一张实测图。"),
    ("voice-full-01/voice-03.wav", "50c92e004c747b0d31f8af4bef102385d5c0501ae4e6a2447163a2ecbd9f0de0", "资料交给捷境整理草稿，没核实的尺寸先留空。"),
    ("voice-full-01/voice-04.wav", "94a1923e6d4afd4dd57ead2cbb4888c6b679ad8b1f17b2110436a575887b6838", "核对后，再确认发布。"),
    ("voice-full-01/voice-05.wav", "d84355a80e8a8d61cef70559a54331c7b2be38b2e7179d94969e6ea5190657ce", "把上架前的准备，一步步做清楚。"),
]
audio = []
timeline = []
position = 0
rate = 24000
gap = int(.14 * rate)
for i, (relative, sha, text) in enumerate(sources):
    source = args.root / relative
    if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
        raise SystemExit(f"Source mismatch: {relative}")
    with wave.open(str(source), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != rate:
            raise SystemExit("Unexpected input encoding")
        frames = wav.getnframes()
        pcm = wav.readframes(frames)
    timeline.append({"start": position/rate, "end": (position+frames)/rate,
                     "text": text, "source": str(source), "sha256": sha})
    audio.append(pcm)
    position += frames
    if i < len(sources)-1:
        audio.append(b"\x00" * gap * 2)
        position += gap
args.output.mkdir(parents=True, exist_ok=False)
target = args.output / "v16-narration-raw.wav"
with wave.open(str(target), "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(rate)
    wav.writeframes(b"".join(audio))
receipt = {"file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
           "duration_seconds": position/rate, "rate": rate, "segments": timeline,
           "speed_changed": False, "pitch_changed": False, "source_trimmed": False,
           "natural_listening_passed": False, "paid_calls": 0}
with (args.output / "VOICE_JOIN.safe.json").open("x", encoding="utf-8") as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
print(json.dumps(receipt, ensure_ascii=False))
