#!/usr/bin/env python3
"""trellis_run.py — TRELLIS.2 (4B) image-to-mesh on 8GB, desktop-friendly.

Runs the ComfyUI-Trellis2 pipeline standalone (no server). Guard rails, per
the standing policy: never kills desktop apps; waits for free VRAM with a
desktop reserve (youtube headroom); on OOM steps 1024 -> 512 and retries.

Geometry-only (generate_texture_slat=False): the user paints the print.

Setup (one-time, already done):
  uv venv ~/ComfyUI-trellis/.venv --python 3.12
  torch 2.9.1 cu126 + ComfyUI reqs + ComfyUI-Trellis2 reqs
  + wheels/Linux/Torch291/*.whl (--no-deps for o_voxel)
  models: microsoft/TRELLIS.2-4B, facebook/dinov3..., TRELLIS-image-large ss_dec

Usage:
  trellis_run.py image.png [out.glb] [seed]
"""
import gc
import os
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["ATTN_BACKEND"] = "sdpa"  # dense attn: sdpa (no flash-attn build needed)

HOME = os.path.expanduser("~")
MODELS = os.path.join(HOME, "ComfyUI-trellis", "models")
NODES = os.path.join(HOME, "ComfyUI", "custom_nodes", "ComfyUI-Trellis2")

import torch  # noqa: E402

DESKTOP_RESERVE_MB = int(os.environ.get("GPU_DESKTOP_RESERVE_MB", "1300"))


def gpu_free_mb():
    free, _ = torch.cuda.mem_get_info()
    return free >> 20


def wait_for_free(need_mb, tag, poll_s=20, timeout_s=0):
    t0 = time.time()
    while True:
        held = torch.cuda.memory_reserved() >> 20
        if need_mb - held + 400 <= gpu_free_mb():  # 400 context margin
            return
        if timeout_s and time.time() - t0 > timeout_s:
            print(f"[wait] budget tight at {tag}; best effort", flush=True)
            return
        print(f"[wait] {tag}: held {held} free {gpu_free_mb()} need {need_mb}; "
              f"retry {poll_s}s", flush=True)
        time.sleep(poll_s)


def main():
    import argparse
    a = argparse.ArgumentParser()
    a.add_argument("image", type=str)
    a.add_argument("out", nargs="?", default=None)
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--pipeline-type", default="1024")
    a.add_argument("--texture", action="store_true")
    a.add_argument("--sparse-backend", default="xformers")
    a.add_argument("--attn-backend", default=None)
    a = a.parse_args()
    out = a.out or "/tmp/trellis_out.glb"

    sys.path.insert(0, NODES)
    sys.path.insert(0, os.path.join(HOME, "ComfyUI"))
    from PIL import Image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    model_dir = os.path.join(MODELS, "microsoft", "TRELLIS.2-4B")
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(
        model_dir, keep_models_loaded=False, use_fp8=False)
    # node-equivalent path patching
    pa = pipeline._pretrained_args
    pa["models"]["sparse_structure_decoder"] = os.path.join(
        MODELS, "microsoft", "TRELLIS-image-large", "ckpts", "ss_dec_conv3d_16l8_fp16")
    fb = os.path.join(MODELS, "facebook", "dinov3-vitl16-pretrain-lvd1689m")
    pa["image_cond_model"]["args"]["model_name"] = fb
    for k in ("ss", "shape_512", "shape_1024"):
        if k in getattr(pipeline, "PIXAL3D_IMAGE_COND_CONFIGS", {}):
            pipeline.PIXAL3D_IMAGE_COND_CONFIGS[k]["model_name"] = fb

    from trellis2.modules.sparse import config as sparseconfig
    sparseconfig.set_attn_backend(a.sparse_backend)
    sparseconfig.set_conv_backend("flex_gemm")

    pipeline.low_vram = True
    pipeline.cuda()

    img = Image.open(a.image).convert("RGBA")
    has_alpha = img.mode == "RGBA" and img.getextrema()[3][0] < 250
    if not has_alpha:
        from rembg import remove
        img = remove(img)

    ladder = [("1024", 49152), ("512", 49152)] if a.pipeline_type == "auto" \
        else [(a.pipeline_type, 49152)]
    for ptype, tokens in ladder:
        for attempt in (1, 2):
            try:
                wait_for_free(7000, f"trellis {ptype} try{attempt}", timeout_s=600)
                t0 = time.time()
                kw = dict(
                    image=img, seed=a.seed, pipeline_type=ptype,
                    sparse_structure_sampler_params={"steps": 12},
                    shape_slat_sampler_params={"steps": 12},
                    tex_slat_sampler_params={"steps": 12},
                    max_num_tokens=tokens,
                    sparse_structure_resolution=32,
                    max_views=1,
                    generate_texture_slat=a.texture,
                    use_tiled=True,
                    sampler="euler",
                    fill_holes=True, hole_iterations=1,
                    hole_fill_algorithm="flood_fill", keep_only_shell=True,
                )
                if not a.texture:
                    kw["pbar"] = None
                ret = pipeline.run(**kw)
                mesh = ret[0]
                print(f"[t] {ptype} gen {time.time()-t0:.0f}s verts "
                      f"{len(mesh.vertices)} faces {len(mesh.faces)}", flush=True)
                o = out.replace(".glb", f"_{ptype}.glb")
                mesh.export(o)
                print("OK", o, flush=True)
                return 0
            except torch.OutOfMemoryError as e:
                print(f"[oom] {ptype} try{attempt}: {str(e)[:200]}", flush=True)
                gc.collect()
                torch.cuda.empty_cache()
                time.sleep(20)
    print("[fail] ladder exhausted", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
