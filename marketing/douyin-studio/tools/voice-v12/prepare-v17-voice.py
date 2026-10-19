"""Join verified, newly generated V17 takes without retiming or source edits."""
import hashlib
import json
from pathlib import Path
import sys
import wave

ROOT = Path(r"D:\Codex-Verification\jiejing-v17-common-pain-20261010")
out = Path(sys.argv[1]).resolve()
if not out.is_relative_to(ROOT) or out == ROOT or out.exists():
    raise SystemExit("Fresh V17 output directory required")
pieces, timeline, samples = [], [], 0
for number in range(1, 7):
    folder = ROOT / ("voice-01" if number <= 3 else "voice-03")
    receipt = json.loads((folder / f"VOICE_{number:02d}.safe.json").read_text(encoding="utf-8"))
    source = folder / f"voice-{number:02d}.wav"
    if hashlib.sha256(source.read_bytes()).hexdigest() != receipt["sha256"]:
        raise SystemExit("Take hash mismatch")
    with wave.open(str(source), "rb") as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (24000, 1, 2):
            raise SystemExit("Unexpected take encoding")
        count = stream.getnframes()
        pieces.append(stream.readframes(count))
    timeline.append({"number": number, "start": samples / 24000, "end": (samples + count) / 24000,
                     "text": receipt["text"], "source_sha256": receipt["sha256"]})
    samples += count
    if number < 6:
        pieces.append(b"\0" * 6720)
        samples += 3360  # 0.14 second sentence break; voices stay at original speed.
out.mkdir(parents=True, exist_ok=False)
target = out / "v17-narration.wav"
with wave.open(str(target), "wb") as stream:
    stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
    stream.writeframes(b"".join(pieces))
result = {"file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
          "duration_seconds": samples / 24000, "segments": timeline,
          "speed_changed": False, "listening_review_passed": False, "paid_calls": 0}
with (out / "VOICE_JOIN.safe.json").open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False))
