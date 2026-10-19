"""V18 review narration. Existing offline model and fictional reference only."""
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(r"D:\Codex-Verification\jiejing-evening-rework-20261009-owner01\offline-voice")
AREA = Path(r"D:\Codex-Verification\jiejing-v18-listing-20261010")
REF = Path(r"D:\Codex-Verification\jiejing-v13-20261009-1111\assets\voice-design-male-trial-01.wav")
REF_SHA = "b26da2bcfa196ac2eb7b10e6a230a503e225f271340fb1cd221d9395dbcf45a4"
TEXTS = [
    "货都备好了，上架还卡在写文案？",
    "图片、参数，到英文介绍，又得从头整理。",
    "在捷境，把商品资料交给商品内容模块。",
    "标题、卖点、描述，先得到一份可编辑草稿。",
    "哪句不合适，直接改。规格再核对一遍。",
    "从零散资料，到完整的上架准备。发布前，由你确认。",
    "捷境，当前支持易贝。带一个商品，来试试。",
]
OUT = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
START = int(sys.argv[sys.argv.index("--start") + 1]) if "--start" in sys.argv else 1
if not OUT.is_relative_to(AREA.resolve()) or OUT == AREA.resolve():
    raise SystemExit("Fresh V18 output subdirectory required")
for key, value in {
    "HF_HOME": str(ROOT / "hf-cache"), "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    "TMP": str(ROOT / "tmp"), "TEMP": str(ROOT / "tmp"),
    "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
    "NUMBA_NUM_THREADS": "2",
    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
}.items():
    os.environ[key] = value


def worker():
    import numpy as np
    import psutil
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    if hashlib.sha256(REF.read_bytes()).hexdigest() != REF_SHA:
        raise RuntimeError("Fictional reference changed")
    if not torch.cuda.is_available() or torch.cuda.mem_get_info()[0] < 3200 * 1024**2:
        raise RuntimeError("Insufficient GPU headroom; no other process will be stopped")
    if psutil.virtual_memory().available < 1250 * 1024**2:
        raise RuntimeError("Insufficient memory")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.78, 0)
    model = Qwen3TTSModel.from_pretrained(
        str(ROOT / "model-0.6B-Base-sharded-01"), device_map="cuda:0",
        dtype=torch.bfloat16, attn_implementation="eager",
        low_cpu_mem_usage=True, local_files_only=True, trust_remote_code=False,
    )
    model.model.speech_tokenizer.model.to(dtype=torch.bfloat16)
    for number, text in enumerate(TEXTS, 1):
        if number < START:
            continue
        chunks = {
            4: ["标题、卖点、描述，", "先得到一份可编辑草稿。"],
            5: ["哪句不合适，直接改。", "规格再核对一遍。"],
            6: ["从零散资料，到完整的上架准备。", "发布前，由你确认。"],
            7: ["捷境，当前支持易贝。", "带一个商品，来试试。"],
        }.get(number, [text])
        pieces = []
        for part, chunk in enumerate(chunks):
            torch.manual_seed(1800 + number * 10 + part)
            torch.cuda.empty_cache()
            wavs, rate = model.generate_voice_clone(
                text=chunk, language="Chinese", ref_audio=str(REF),
                ref_text="商品图有了，接下来怎么上架？把资料交给捷境，标题、卖点、描述，接着往下做。",
                max_new_tokens=100, do_sample=True, subtalker_dosample=True,
            )
            portion = np.asarray(wavs[0], dtype=np.float32)
            part_target = OUT / f"part-{number:02d}-{part+1}.wav"
            with part_target.open("xb") as stream:
                sf.write(stream, portion, rate, format="WAV", subtype="PCM_16")
            pieces.append(portion.copy())
            if part < len(chunks)-1:
                pieces.append(np.zeros(round(rate*.09), dtype=np.float32))
            del wavs, portion
            gc.collect()
            torch.cuda.empty_cache()
        wave = np.concatenate(pieces)
        duration = wave.size / rate
        if not np.isfinite(wave).all() or not 1.2 <= duration <= 13 or np.max(np.abs(wave)) < 1e-5:
            raise RuntimeError("Invalid generated waveform")
        target = OUT / f"voice-{number:02d}.wav"
        with target.open("xb") as stream:
            sf.write(stream, wave, rate, format="WAV", subtype="PCM_16")
        receipt = {"number": number, "text": text, "file": str(target),
                   "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                   "sample_rate": rate, "duration_seconds": duration,
                   "reference_sha256": REF_SHA, "synthetic_reference_only": True,
                   "precision": "bfloat16", "listening_review_passed": False}
        with (OUT / f"VOICE_{number:02d}.safe.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
        print(f"V18_SEGMENT_{number:02d}_CREATED {duration:.2f}s", flush=True)
        del pieces, wave
        gc.collect()
        torch.cuda.empty_cache()


def supervise():
    import psutil
    if psutil.virtual_memory().available < 2000 * 1024**2:
        raise SystemExit("Available RAM below 2000 MiB guard")
    OUT.mkdir(parents=True, exist_ok=False)
    start, peak, abort = time.monotonic(), 0, None
    with (OUT / "voice.local.log").open("x", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-u", __file__, "--output", str(OUT), "--start", str(START), "--worker"], stdout=log, stderr=subprocess.STDOUT)
        process = psutil.Process(child.pid)
        while child.poll() is None:
            try:
                owned = list(reversed(process.children(recursive=True))) + [process]
                rss = sum(p.memory_info().rss for p in owned if p.is_running())
                peak = max(peak, rss)
            except psutil.NoSuchProcess:
                break
            if psutil.virtual_memory().available < 1000 * 1024**2:
                abort = "available_ram_below_1000_mib"
            elif rss > 2300 * 1024**2:
                abort = "own_worker_rss_above_2300_mib"
            elif time.monotonic() - start > 1200:
                abort = "batch_exceeded_1200_seconds"
            if abort:
                for p in owned:
                    try:
                        p.terminate()
                    except psutil.NoSuchProcess:
                        pass
                break
            time.sleep(0.5)
        code = child.wait(timeout=20)
    result = {"exit_code": code, "aborted_reason": abort, "elapsed_seconds": round(time.monotonic()-start, 2),
              "peak_worker_rss_mib": round(peak / 1024**2, 1), "paid_calls": 0,
              "network_required": False, "created_segments": len(list(OUT.glob("voice-*.wav"))),
              "natural_listening_passed": False}
    with (OUT / "VOICE_PROCESS.safe.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result), flush=True)
    return code if not abort else 3


if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker()
    else:
        raise SystemExit(supervise())
