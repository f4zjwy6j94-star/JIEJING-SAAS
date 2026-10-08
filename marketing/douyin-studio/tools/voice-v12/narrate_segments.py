"""Generate a frame-aligned spoken trial locally; quality approval is separate."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import sherpa_onnx
import soundfile as sf

parser = argparse.ArgumentParser()
parser.add_argument("--model", type=Path, required=True)
parser.add_argument("--script", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
if not args.model.is_absolute() or not args.out.is_absolute() or args.out.exists():
    raise SystemExit("Use an existing absolute model and a new absolute output directory")
script = json.loads(args.script.read_text(encoding="utf-8"))
fps = script["fps"]
config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(args.model / "model.onnx"), voices=str(args.model / "voices.bin"),
        tokens=str(args.model / "tokens.txt"), data_dir=str(args.model / "espeak-ng-data"),
        lexicon=",".join(str(args.model / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt"))),
    num_threads=2, provider="cpu"), max_num_sentences=1)
if not config.validate():
    raise SystemExit("Invalid model config")
tts = sherpa_onnx.OfflineTts(config)
args.out.mkdir(parents=True)
cursor = 8
rate = 24000
parts = [np.zeros(int(rate * cursor / fps), dtype=np.float32)]
captions = []
for index, line in enumerate(script["lines"]):
    tick = time.monotonic()
    audio = tts.generate(text=line, sid=script["speaker_id"], speed=1.0)
    samples = np.asarray(audio.samples, dtype=np.float32)
    if audio.sample_rate != rate or samples.size == 0 or not np.isfinite(samples).all():
        raise SystemExit("Unexpected or invalid audio")
    frames = math.ceil(len(samples) / rate * fps)
    padded = np.pad(samples, (0, int(frames * rate / fps) - len(samples)))
    target = args.out / f"line-{index + 1:02}.wav"
    sf.write(str(target), samples, rate, subtype="PCM_16")
    captions.append({"text": line, "startMs": cursor / fps * 1000,
                     "endMs": (cursor + frames) / fps * 1000,
                     "timestampMs": None, "confidence": None,
                     "from": cursor, "frames": frames, "file": target.name})
    parts.extend((padded, np.zeros(4 * rate // fps, dtype=np.float32)))
    cursor += frames + 4
    print(json.dumps({"line": index + 1, "frames": frames,
                      "generation_seconds": round(time.monotonic() - tick, 3)}), flush=True)
parts.append(np.zeros(10 * rate // fps, dtype=np.float32))
cursor += 10
target = args.out / "narration.wav"
sf.write(str(target), np.concatenate(parts), rate, subtype="PCM_16")
report = {"captions": captions, "fps": fps, "frames": cursor,
          "speaker": script["speaker_name"], "synthetic_voice": True,
          "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
          "sample_rate": rate, "naturalness_review": "pending", "paid_calls": 0}
with (args.out / "TIMING.safe.json").open("x", encoding="utf-8") as file:
    json.dump(report, file, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False), flush=True)
