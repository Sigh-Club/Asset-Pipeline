#!/usr/bin/env trellis-venv-python
"""refine_run.py — Trellis.2 mesh refinement: re-imprint source detail.

refine_mesh = encode our mesh's structure as sparse latent, re-sample the
surface shape-slat from scratch on those coords conditioned on the source
image at high res, decode. Geometry layout preserved, detail re-derived from
the image -- the one-to-one rescue pass (RefineMesh_MeshOnly workflow).

Memory: 1024 refine fits the 8GB budget incl desktop (same peaks as gen);
1536 needs headroom -- try after. Guard rails per policy: no kills, wait
for free VRAM, OOM ladder 1536->1024.

Usage:
  refine_run.py mesh.glb source_image.png [out.glb] [--resolution 1024] [--seed 7]
"""
import argparse
import gc
import os
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "ComfyUI"))
sys.path.insert(0, os.path.join(HOME, "ComfyUI", "custom_nodes", "ComfyUI-Trellis2"))
os.chdir(os.path.join(HOME, "ComfyUI", "custom_nodes", "ComfyUI-Trellis2"))

import numpy as np
import torch  # noqa: E402

NEED_MB = 6600


def wait_for_free(need_mb, tag, poll_s=20, timeout_s=300):
    import time
    t0 = time.time()
    while True:
        free, _ = torch.cuda.mem_get_info()
        if (free >> 20) >= need_mb:
            return
        if timeout_s and time.time() - t0 > timeout_s:
            print(f"[wait] budget tight at {tag}; best effort", flush=True)
            return
        print(f"[wait] {tag}: free {free >> 20} need {need_mb}; retry", flush=True)
        time.sleep(poll_s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mesh", type=str)
    p.add_argument("image", type=str)
    p.add_argument("out", nargs="?", default=None)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--resolution", type=int, default=1024, choices=[512, 1024, 1536])
    p.add_argument("--steps", type=int, default=12)
    p.add_argument("--guidance", type=float, default=7.5)
    p.add_argument("--max-tokens", type=int, default=150000)
    a = p.parse_args()
    out = a.out or f"/tmp/refined_{a.resolution}.glb"

    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    from trellis2.modules.sparse import config as sparseconfig
    sparseconfig.set_attn_backend("xformers")
    sparseconfig.set_conv_backend("flex_gemm")

    model_dir = os.path.join(HOME, "ComfyUI-trellis", "models", "microsoft", "TRELLIS.2-4B")
    pipe = Trellis2ImageTo3DPipeline.from_pretrained(
        model_dir, keep_models_loaded=False, use_fp8=False)
    pa = pipe._pretrained_args
    pa["models"]["sparse_structure_decoder"] = os.path.join(
        HOME, "ComfyUI-trellis", "models", "microsoft", "TRELLIS-image-large",
        "ckpts", "ss_dec_conv3d_16l8_fp16")
    fb = os.path.join(HOME, "ComfyUI-trellis", "models", "facebook",
                      "dinov3-vitl16-pretrain-lvd1689m")
    pa["image_cond_model"]["args"]["model_name"] = fb
    for k in ("ss", "shape_512", "shape_1024"):
        if k in getattr(pipe, "PIXAL3D_IMAGE_COND_CONFIGS", {}):
            pipe.PIXAL3D_IMAGE_COND_CONFIGS[k]["model_name"] = fb

    pipe.low_vram = True
    pipe.cuda()

    import trimesh
    from PIL import Image
    mesh = trimesh.load(a.mesh, force="mesh", process=True)
    mesh.update_faces(mesh.nondegenerate_faces(height=1e-8))
    mesh.merge_vertices()
    if len(mesh.faces) > 600_000:  # encode neighbour cache scales with density
        import open3d as o3d
        o = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(mesh.vertices),
            o3d.utility.Vector3iVector(mesh.faces))
        o = o.simplify_quadric_decimation(500_000)
        mesh = trimesh.Trimesh(np.asarray(o.vertices), np.asarray(o.triangles), process=False)
        print(f"[refine] input decimated to {len(mesh.faces)} faces", flush=True)
    # normalise to the unit aabb the pipeline expects, keep transform to undo
    lo, hi = mesh.bounds
    c = (lo + hi) / 2
    s = 1.0 / (hi - lo).max()
    mesh.apply_translation(-c)
    mesh.apply_scale(s)

    img = Image.open(a.image).convert("RGBA")
    if not (img.mode == "RGBA" and img.getextrema()[3][0] < 250):
        from rembg import remove
        img = remove(img)

    from PIL import Image as _PILImage
    for res_try, tokens in [(a.resolution, a.max_tokens), (512, 100_000)]:
        try:
            wait_for_free(NEED_MB, f"refine {res_try}", timeout_s=600)
            t0 = time.time()
            params = {"steps": a.steps, "guidance_strength": a.guidance,
                      "guidance_rescale": 0.05, "rescale_t": 4.0}
            res = pipe.refine_mesh(
                mesh=mesh, image=img, seed=a.seed,
                shape_slat_sampler_params=dict(params),
                tex_slat_sampler_params=dict(params),
                resolution=res_try, max_num_tokens=tokens,
                generate_texture_slat=False, use_tiled=True,
                sampler="heun", verbose=True,
            )[0]
            break
        except torch.OutOfMemoryError as e:
            print(f"[oom] res{res_try}: {str(e)[:150]}", flush=True)
            gc.collect()
            torch.cuda.empty_cache()
            time.sleep(20)
    else:
        print("[fail] refine ladder exhausted", flush=True)
        return 1
    print(f"[t] refine done: {time.time()-t0:.0}s "
          f"verts {len(res.vertices)} faces {len(res.faces)}", flush=True)

    # undo normalisation
    r = trimesh.Trimesh(res.vertices.cpu().numpy(), res.faces.cpu().numpy())
    r.apply_scale(1 / s)
    r.apply_translation(c)
    r.export(out)
    print("OK", out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
