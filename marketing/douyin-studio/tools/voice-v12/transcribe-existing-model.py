"""Transcribe a new review voice locally using the already installed tiny model.

No model download, network call, source overwrite, or publication action.
"""
import argparse
import audioop
import hashlib
import json
from pathlib import Path
import wave

import numpy as np
from faster_whisper import WhisperModel

parser = argparse.ArgumentParser()
parser.add_argument("input", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("model", type=Path)
args = parser.parse_args()
assert args.input.is_file() and args.model.is_dir()
assert not args.output.exists(), "Refusing overwrite"
with wave.open(str(args.input), "rb") as wav:
    assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
    duration = wav.getnframes() / wav.getframerate()
    pcm, _ = audioop.ratecv(wav.readframes(wav.getnframes()), 2, 1, wav.getframerate(), 16000, None)
model = WhisperModel(str(args.model), device="cpu", compute_type="int8", cpu_threads=2,
                     num_workers=1, local_files_only=True)
segments, _ = model.transcribe(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768,
    language="zh", beam_size=5, word_timestamps=True, condition_on_previous_text=False,
    vad_filter=False, initial_prompt="捷境，eBay，商品图，标题，卖点，描述，官网。")
result = {"input": str(args.input), "sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
    "duration": duration, "audio_uploaded": False, "human_listening": False,
    "segments": [{"start": s.start, "end": s.end, "text": s.text,
        "words": [{"word": w.word, "start": w.start, "end": w.end} for w in s.words or []]}
        for s in segments]}
with args.output.open("x", encoding="utf-8") as output:
    json.dump(result, output, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False))
