"""Bounded four-segment production with pinned local models and a fictional reference."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

MODEL_ROOT = Path(r"D:\Codex-Verification\jiejing-evening-rework-20261009-owner01\offline-voice")
if "--output" not in sys.argv:
    raise SystemExit("Pass --output with a fresh directory outside the repository")
OUT = Path(sys.argv[sys.argv.index("--output")+1]).resolve()
if not str(OUT).lower().startswith("d:\\codex-verification\\jiejing-noon-v16-20261010\\"):
    raise SystemExit("Output must stay in this task media area on D:")
if "--worker" not in sys.argv:
    OUT.mkdir(parents=True, exist_ok=False)
REF = Path(r"D:\Codex-Verification\jiejing-v13-20261009-1111\assets\voice-design-male-trial-01.wav")
REF_SHA = "b26da2bcfa196ac2eb7b10e6a230a503e225f271340fb1cd221d9395dbcf45a4"
TEXTS = [
    "先问清实物和包装各多大，再要一张实测图。",
    "资料交给捷境整理草稿，没核实的尺寸先留空。",
    "核对后，再确认发布。",
    "把上架前的准备，一步步做清楚。",
]
for key, value in {
    "HF_HOME": str(MODEL_ROOT / "hf-cache"), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    "TMP": str(MODEL_ROOT / "tmp"), "TEMP": str(MODEL_ROOT / "tmp"), "OMP_NUM_THREADS": "2",
    "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "NUMBA_NUM_THREADS": "2",
}.items():
    os.environ[key] = value

def worker():
    import numpy as np
    import psutil
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    if hashlib.sha256(REF.read_bytes()).hexdigest() != REF_SHA:
        raise RuntimeError("Synthetic reference hash mismatch")
    if not torch.cuda.is_available() or torch.cuda.mem_get_info()[0] < 3200 * 1024**2:
        raise RuntimeError("Insufficient CUDA headroom; no driver or permission change")
    if psutil.virtual_memory().available < 1250 * 1024**2:
        raise RuntimeError("Insufficient RAM headroom")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.78, 0)
    torch.manual_seed(1010)
    print("Loading existing byte-verified weights with BF16, not overflowing FP16", flush=True)
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL_ROOT / "model-0.6B-Base-sharded-01"), device_map="cuda:0", dtype=torch.bfloat16,
        attn_implementation="eager", low_cpu_mem_usage=True, local_files_only=True, trust_remote_code=False,
    )
    model.model.speech_tokenizer.model.to(dtype=torch.bfloat16)
    torch.cuda.empty_cache()
    print("Model and codec BF16; allocation ceiling unchanged; generating short sentence", flush=True)
    for i, text in enumerate(TEXTS, start=2):
        torch.manual_seed(1008+i)
        torch.cuda.empty_cache()
        wavs, sr = model.generate_voice_clone(
            text=text, language="Chinese", ref_audio=str(REF),
            ref_text="商品图有了，接下来怎么上架？把资料交给捷境，标题、卖点、描述，接着往下做。",
            max_new_tokens=170, do_sample=True, subtalker_dosample=True,
        )
        wave = np.asarray(wavs[0], dtype=np.float32)
        duration = wave.size / sr
        if not np.isfinite(wave).all() or not 1.2 <= duration <= 12 or np.max(np.abs(wave)) < 1e-5:
            raise RuntimeError("Audio failed numeric/duration/signal checks")
        target = OUT / f"voice-{i:02d}.wav"
        with target.open("xb") as stream:
            sf.write(stream, wave, sr, format="WAV", subtype="PCM_16")
        with (OUT / f"VOICE_{i:02d}.safe.json").open("x", encoding="utf-8") as stream:
            json.dump({"text": text, "file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                       "sample_rate": sr, "duration_seconds": duration, "reference_sha256": REF_SHA,
                       "synthetic_reference_only": True, "dtype": "bfloat16", "codec_dtype": "bfloat16", "disk_weights_unchanged": True,
                       "cuda_peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2,
                       "listening_review_passed": False, "ready_for_film": False}, stream, ensure_ascii=False, indent=2)
        print(f"NEW_SEGMENT_{i:02d}_CREATED_REQUIRES_LISTENING_REVIEW", flush=True)

def supervise():
    import psutil
    receipt = OUT / "VOICE_PROCESS.safe.json"
    if receipt.exists() or (OUT / "voice-bf16-trial-01.wav").exists():
        raise SystemExit("Fresh outputs required; never overwrite prior evidence")
    if psutil.virtual_memory().available < 2000 * 1024**2:
        raise SystemExit("Not started: available RAM under 2000 MiB")
    started = time.monotonic()
    abort = None
    peak = 0
    minimum = psutil.virtual_memory().available
    with (OUT / "voice-trial.local.log").open("x", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-u", __file__, "--output", str(OUT), "--worker"], stdout=log, stderr=subprocess.STDOUT)
        process = psutil.Process(child.pid)
        while child.poll() is None:
            available = psutil.virtual_memory().available
            minimum = min(minimum, available)
            try:
                owned = list(reversed(process.children(recursive=True))) + [process]
                rss = sum(p.memory_info().rss for p in owned if p.is_running())
                peak = max(peak, rss)
            except psutil.NoSuchProcess:
                break
            if available < 1000 * 1024**2:
                abort = "available_ram_below_1000_mib"
            elif rss > 2300 * 1024**2:
                abort = "own_worker_rss_above_2300_mib"
            elif time.monotonic() - started > 600:
                abort = "four_segment_batch_exceeded_600_seconds"
            if abort:
                for p in owned:
                    try:
                        p.terminate()
                    except psutil.NoSuchProcess:
                        pass
                break
            time.sleep(0.5)
        code = child.wait(timeout=20)
    result = {"elapsed_seconds": round(time.monotonic()-started, 2), "exit_code": code,
              "aborted_reason": abort, "peak_worker_rss_mib": round(peak/1024**2, 1),
              "min_available_ram_mib": round(minimum/1024**2, 1), "gpu_allocator_fraction": 0.78,
              "precision": "bfloat16", "paid_calls": 0, "network_required": False,
              "listening_review_passed": False, "full_narration_created": False}
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result), flush=True)
    return code if not abort else 3

if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker()
    else:
        raise SystemExit(supervise())
