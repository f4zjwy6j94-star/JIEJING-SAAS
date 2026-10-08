"""Local free TTS audition, based on the official sherpa-onnx Kokoro API example.

This is a fallback for the unavailable keyed Speech API, not a quality approval.
No external request, custom voice clone, speed change or original overwrite.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import sherpa_onnx
import soundfile as sf

parser = argparse.ArgumentParser()
parser.add_argument("--model", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
if not args.model.is_absolute() or not args.out.is_absolute() or args.out.exists():
    raise SystemExit("Existing absolute model directory and new absolute output required")
required = ("model.onnx", "voices.bin", "tokens.txt", "espeak-ng-data",
            "lexicon-us-en.txt", "lexicon-zh.txt")
if any(not (args.model / name).exists() for name in required):
    raise SystemExit("Incomplete model")
config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(args.model / "model.onnx"), voices=str(args.model / "voices.bin"),
        tokens=str(args.model / "tokens.txt"), data_dir=str(args.model / "espeak-ng-data"),
        lexicon=",".join(str(args.model / p) for p in ("lexicon-us-en.txt", "lexicon-zh.txt"))),
    num_threads=2, provider="cpu"), max_num_sentences=1)
if not config.validate():
    raise SystemExit("Invalid model config")
args.out.mkdir(parents=True)
started = time.monotonic()
tts = sherpa_onnx.OfflineTts(config)
print(json.dumps({"model_load_seconds": round(time.monotonic() - started, 3)}), flush=True)
text = "货源图都有了，怎么还卡在上架前？一张图片，一份规格表，聊天里还有几句补充说明。先把资料理清，再开始写。"
rows = []
for sid, name in ((12, "zf_018"), (56, "zf_094"), (67, "zm_025")):
    target = args.out / f"audition-{name}.wav"
    if target.exists():
        raise SystemExit("Refusing existing audio")
    tick = time.monotonic()
    audio = tts.generate(text=text, sid=sid, speed=1.0)
    if not len(audio.samples):
        raise SystemExit("No audio samples")
    sf.write(str(target), audio.samples, samplerate=audio.sample_rate, subtype="PCM_16")
    row = {"speaker_id": sid, "speaker": name, "path": str(target),
           "sample_rate": audio.sample_rate, "duration_seconds": len(audio.samples) / audio.sample_rate,
           "generation_seconds": round(time.monotonic() - tick, 3),
           "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
           "synthetic_voice": True, "naturalness_review": "pending"}
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
with (args.out / "AUDITION.safe.json").open("x", encoding="utf-8") as out:
    json.dump({"input_text": text, "provider": "local-cpu", "paid_calls": 0,
               "voice_cloning": False, "rows": rows}, out, ensure_ascii=False, indent=2)
