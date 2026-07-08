"""Hardware detection and local-AI model recommendations (Part 5 of spec)."""
from __future__ import annotations

import platform
import subprocess
from functools import lru_cache

import psutil

from backend.utils.logger import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def detect_hardware() -> dict:
    info: dict = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor() or "Unknown CPU",
        "cpu_cores": psutil.cpu_count(logical=False) or 1,
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "gpu": None,
        "vram_gb": 0.0,
        "cuda": False,
        "accelerator": "cpu",
    }
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,compute_cap",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            name, mem_mb, compute = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
            info["gpu"] = name
            info["vram_gb"] = round(float(mem_mb) / 1024, 1)
            # CTranslate2 CUDA kernels need compute capability >= 6.0 (Pascal+).
            info["cuda"] = float(compute) >= 6.0
            info["accelerator"] = "cuda" if info["cuda"] else "cpu"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        info["accelerator"] = "metal"
    log.info("Hardware: %s", info)
    return info


def recommend_local_models() -> dict:
    """Tiered Ollama model recommendations based on detected RAM/GPU."""
    hw = detect_hardware()
    ram, cuda, vram = hw["ram_gb"], hw["cuda"], hw["vram_gb"]

    if ram >= 32 and cuda and vram >= 8:
        tier, models = "high", ["gemma3:12b", "qwen3:14b", "llama3.3", "deepseek-r1:8b"]
        note = "Your workstation can run large local models with excellent quality."
    elif ram >= 16:
        tier, models = "mid", ["gemma3:4b", "llama3.2:3b", "qwen3:4b"]
        note = "Mid-size local models will give fast, high-quality cleanup."
    else:
        tier, models = "low", ["gemma3:1b", "qwen2.5:3b", "phi4-mini"]
        note = "Compact local models keep memory usage low with quick responses."

    return {
        "hardware": hw,
        "tier": tier,
        "recommended": models[0],
        "alternatives": models[1:],
        "note": note,
        "whisper_recommendation": (
            "medium" if (cuda and vram >= 5) else "small" if ram >= 8 else "base"),
    }
