#!/usr/bin/env python3
"""gpu_policy.py — the workstation's memory budget, in one place.

This box is the only machine that does the work: RTX 3070 Ti (8 GB, shared with
a desktop session), 31 GB RAM, 8C/16T. Nothing here is allowed to assume more
than that, and nothing may run two GPU jobs at once.

Usage:
    python3 tools/gpu_policy.py status
    python3 tools/gpu_policy.py plan --job img23d
    python3 tools/gpu_policy.py plan --job blender_render --profile auto
    python3 tools/gpu_policy.py require 4500 --timeout 300

Import it from other tools:

    from gpu_policy import plan, wait_for_vram, live_gpu
    p = plan("img23d")           # dict of safe parameters for current headroom
    wait_for_vram(p["require_mb"])
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RESERVE_MB = 1024          # never allocate into the last GB: desktop + driver
DESKTOP_RESERVE_MB = 900   # observed chrome/discord/compositor floor
JOBS = ("img23d", "blender_render", "blender_bake", "uv", "decimate", "script", "train")

# Parameter sets keyed by (job, profile). Values are the measured-safe ceiling on
# a 3070 Ti 8 GB; "low" exists for when the desktop is loaded or a 2K bake is
# already resident.
MATRIX = {
    "img23d": {
        "low":      {"resolution": 256, "steps": 16, "require_mb": 4200, "engine": "hunyuan"},
        "balanced": {"resolution": 256, "steps": 20, "require_mb": 4800, "engine": "hunyuan"},
        "max":      {"resolution": 320, "steps": 30, "require_mb": 5600, "engine": "hunyuan"},
    },
    "blender_render": {
        "low":      {"width": 960, "height": 720, "samples": 8, "require_mb": 1200, "engine": "BLENDER_EEVEE"},
        "balanced": {"width": 1280, "height": 960, "samples": 16, "require_mb": 1600, "engine": "BLENDER_EEVEE"},
        "max":      {"width": 1920, "height": 1080, "samples": 32, "require_mb": 2200, "engine": "BLENDER_EEVEE"},
    },
    "blender_bake": {
        "low":      {"size": 1024, "margin": 4, "require_mb": 2200, "denoise": "cpu"},
        "balanced": {"size": 2048, "margin": 8, "require_mb": 3000, "denoise": "cpu"},
        "max":      {"size": 2048, "margin": 8, "require_mb": 3600, "denoise": "cpu"},
    },
    "uv": {
        "low":      {"weld": 0.0001, "angle": 66, "margin": 0.02, "require_mb": 600},
        "balanced": {"weld": 0.0001, "angle": 66, "margin": 0.02, "require_mb": 800},
        "max":      {"weld": 0.0001, "angle": 60, "margin": 0.03, "require_mb": 1000},
    },
    "decimate": {
        "low":      {"tris": 12000, "require_mb": 800},
        "balanced": {"tris": 20000, "require_mb": 1000},
        "max":      {"tris": 25000, "require_mb": 1200},
    },
    "train": {    # LoRA fine-tune: hours of GPU, not minutes. free-memory only.
        "low":      {"require_mb": 4800, "note": "small Apache bases only (klein 4B / Z-Image)"},
        "balanced": {"require_mb": 5300, "note": "klein 4B, 512-768px"},
        "max":      {"require_mb": 5700, "note": "nothing larger than 10GB floor classes"},
    },
    "script": {   # generic Blender python stage: materials, export, inspection
        "low":      {"require_mb": 1000},
        "balanced": {"require_mb": 1400},
        "max":      {"require_mb": 1800},
    },
}


def live_gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        name, total, used, free, util = [x.strip() for x in out.split(",")]
        return {"name": name, "total_mb": int(total), "used_mb": int(used),
                "free_mb": int(free), "util": int(util)}
    except Exception:
        return None


def live_ram():
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) // 1024
        return {"total_mb": info.get("MemTotal"), "available_mb": info.get("MemAvailable"),
                "swap_free_mb": info.get("SwapFree")}
    except Exception:
        return None


def _load():
    try:
        import psutil  # noqa: F401
        return psutil.cpu_percent(interval=0.2)
    except Exception:
        return None


def choose_profile(free_mb: int) -> str:
    usable = free_mb - RESERVE_MB - DESKTOP_RESERVE_MB
    if usable < 1800:
        return "low"
    if usable < 3600:
        return "balanced"
    return "max"


def plan(job: str, profile: str = "auto", free_mb: int | None = None):
    if job not in MATRIX:
        raise ValueError(f"unknown job {job!r}; choose from {', '.join(JOBS)}")
    gpu = live_gpu() if free_mb is None else {"free_mb": free_mb}
    free = gpu.get("free_mb") or 0
    profile = choose_profile(free) if profile == "auto" else profile
    if profile not in ("low", "balanced", "max"):
        raise ValueError("profile must be auto, low, balanced or max")
    params = dict(MATRIX[job][profile])
    params.update({"job": job, "profile": profile,
                   "gpu_free_mb": free,
                   "ok": free >= params["require_mb"],
                   "note": "one GPU job at a time; free VRAM first with gpu-wait"})
    return params


def wait_for_vram(need_mb: int, timeout_s: float = 600, poll_s: float = 5):
    deadline = time.time() + timeout_s
    while True:
        gpu = live_gpu()
        if gpu is None:
            return None
        if gpu["free_mb"] >= need_mb:
            return gpu
        if time.time() > deadline:
            return gpu
        time.sleep(poll_s)


def cmd_status():
    print(json.dumps({"gpu": live_gpu(), "ram": live_ram(),
                      "cpu_load": _load(), "policy": {
                          "reserve_mb": RESERVE_MB,
                          "desktop_reserve_mb": DESKTOP_RESERVE_MB,
                          "max_concurrent_gpu_jobs": 1}}, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("plan")
    p.add_argument("--job", required=True, choices=JOBS)
    p.add_argument("--profile", default="auto")
    p.add_argument("--json", action="store_true")
    r = sub.add_parser("require")
    r.add_argument("mb", type=int)
    r.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args(argv)

    if args.cmd == "status":
        cmd_status()
        return 0
    if args.cmd == "plan":
        p = plan(args.job, args.profile)
        if args.json:
            print(json.dumps(p))
        else:
            print(f"{p['job']}: profile={p['profile']} free={p['gpu_free_mb']}MB "
                  f"needs={p['require_mb']}MB ok={p['ok']}")
            for k, v in p.items():
                if k not in ("job", "profile", "gpu_free_mb", "require_mb", "ok", "note"):
                    print(f"  {k}={v}")
        return 0 if p["ok"] else 1
    if args.cmd == "require":
        gpu = wait_for_vram(args.mb, timeout_s=args.timeout)
        if gpu is None:
            print(f"no NVIDIA GPU visible; assuming {args.mb} MB available")
            return 0
        ok = gpu["free_mb"] >= args.mb
        print(f"{'ok' if ok else 'insufficient'}: {gpu['free_mb']}MB free, need {args.mb}MB")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
