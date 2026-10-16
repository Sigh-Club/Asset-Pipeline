#!/usr/bin/env python3
"""run21_offload.py — Hunyuan3D-2.1 (2.5B) on 8GB cards, desktop-friendly.

Guard rails (user policy: chrome/discord stay open, GPU sharing fine, slow is OK):
  - never kills or throttles desktop processes
  - waits for free VRAM before the GPU-heavy stages (poll; unbounded — slow OK)
  - on CUDA OOM: empty caches, wait for room, retry same res once, then step
    the octree down (ladder res -> ... -> 192)

Staging (manual; accelerate hooks leave meta params / resident conditioner):
  cpu load -> dit resident cuda; conditioner cuda for encode, dropped to cpu at
  first dit call; at vae decode the idle dit drops to cpu. pipe.device pinned
  to cuda so latents spawn on the right device while conditioner/vae sit low.

Usage:
  run21_offload.py [octree] [out.glb]
"""
import gc
import os
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Hunyuan3D-2.1")
sys.path.insert(0, os.path.join(R, "hy3dshape"))
sys.path.insert(0, R)
os.chdir(R)

from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline

OOM_LADDER = (384, 320, 256, 192)
NEED_MB = 6300  # dit + context + activations headroom


def gpu_free_mb() -> int:
    free, _total = torch.cuda.mem_get_info()
    return free >> 20


def wait_for_free(need_mb: int, tag: str, poll_s: int = 20, timeout_s: int = 0) -> None:
    """Block until free >= need minus what this process already holds.

    The desktop is never touched; need_mb is the stage's TOTAL footprint and
    our own cuda reservation is subtracted, else we'd wait on ourselves.
    """
    t0 = time.time()
    while True:
        held = torch.cuda.memory_reserved() >> 20
        short = need_mb - held - gpu_free_mb()
        if short <= 0:
            return
        if timeout_s and time.time() - t0 > timeout_s:
            print(f"[wait] timeout waiting for {need_mb}MiB at {tag}; best effort",
                  flush=True)
            return
        print(f"[wait] {tag}: need {need_mb}MiB, held {held}MiB, "
              f"free {gpu_free_mb()}MiB; retry in {poll_s}s (desktop untouched)",
              flush=True)
        time.sleep(poll_s)


class StageProxy:
    """Moves the wrapped module to cuda on __call__.

    on_first_call: optional callable run once before the first forward
    (used to drop the previous stage's weights).
    re_cuda: if the module was moved away after an OOM retry, bring it back.
    """

    def __init__(self, mod, on_first_call=None):
        self.__dict__["_mod"] = mod
        self.__dict__["_on_first_call"] = on_first_call
        self.__dict__["_done"] = False

    def __call__(self, *a, **k):
        if self._on_first_call is not None and not self._done:
            self._on_first_call()
            self._done = True
        if next(self._mod.parameters()).device.type != "cuda":
            self._mod.cuda()
        return self._mod(*a, **k)

    def __getattr__(self, k):
        return getattr(self.__dict__["_mod"], k)


IMG_PATH = os.path.expanduser(
    "~/Downloads/Gemini_Generated_Image_494afl494afl494a.jpeg")


def cpu_fallback(res, out):
    """Last tier: whole pipeline on CPU. Slow (hours) but certain; fp32."""
    print("[cpu] falling back to full-CPU pipeline (fp32, slow)", flush=True)
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2.1", use_safetensors=False, device="cpu",
        dtype=torch.float32)
    from PIL import Image
    from hy3dshape.rembg import BackgroundRemover
    img = Image.open(IMG_PATH).convert("RGB")
    img = BackgroundRemover()(img)
    t0 = time.time()
    mesh = pipe(image=img, seed=7, num_inference_steps=50, octree_resolution=res)[0]
    print(f"[cpu] done in {(time.time()-t0)/60:.0f}min", flush=True)
    out = out or f"/tmp/full21_cpu_{res}.glb"
    mesh.export(out)
    print("OK", out, flush=True)


def main():
    res = int(sys.argv[1]) if len(sys.argv) > 1 else 384
    out = sys.argv[2] if len(sys.argv) > 2 else None
    img_path = IMG_PATH

    t0 = time.time()
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2.1", use_safetensors=False, device="cpu")
    print(f"[t] cpu load {time.time()-t0:.0f}s", flush=True)

    # conditioner: cuda during encode; dropped at first dit forward
    cond_holder = []
    cond = StageProxy(pipe.conditioner)
    cond_holder.append(cond._mod)
    pipe.conditioner = cond

    def _drop_cond():
        if cond_holder:
            cond_holder.pop().cpu()
            torch.cuda.empty_cache()
            print("[mem] conditioner -> cpu at first dit call", flush=True)

    dit = StageProxy(pipe.model, on_first_call=_drop_cond)
    pipe.model = dit
    dit._mod.cuda()

    def _drop_dit():
        dit._mod.cpu()
        torch.cuda.empty_cache()
        print("[mem] dit -> cpu at vae decode", flush=True)

    vae = StageProxy(pipe.vae, on_first_call=_drop_dit)
    pipe.vae = vae

    # latents must spawn on cuda while conditioner/vae sit low
    pipe.device = torch.device("cuda")

    def generate(res):
        from PIL import Image
        from hy3dshape.rembg import BackgroundRemover
        img = Image.open(img_path).convert("RGB")
        img = BackgroundRemover()(img)
        return pipe(image=img, seed=7, num_inference_steps=50,
                    octree_resolution=res)[0]

    ladder = [r for r in OOM_LADDER if r <= res] or [res]
    for attempt_res in ladder:
        for attempt in (1, 2):
            try:
                wait_for_free(NEED_MB, f"gen res{attempt_res} try{attempt}",
                              timeout_s=1800)
                t0 = time.time()
                mesh = generate(attempt_res)
                print(f"[t] res{attempt_res} gen {time.time()-t0:.0f}s "
                      f"verts {len(mesh.vertices)} faces {len(mesh.faces)}",
                      flush=True)
                out = out or f"/tmp/full21_{attempt_res}.glb"
                mesh.export(out)
                print("OK", out, flush=True)
                return 0
            except torch.OutOfMemoryError as e:
                print(f"[oom] res{attempt_res} try{attempt}: {e}", flush=True)
                torch.cuda.empty_cache()
                gc.collect()
                time.sleep(30)
    cpu_fallback(min(ladder), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
