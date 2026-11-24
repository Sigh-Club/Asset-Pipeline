#!/usr/bin/env python3
"""paint_run.py — Hunyuan3D-Paint PBR texturing on 8 GB, the stage we never ran.

Why this file exists: the competitors' "good looking" assets come from a **dedicated
texture-generation model** that paints a PBR set onto the mesh from the reference image.
Our pipeline generated shape only (Hunyuan3D-2mini) and then hand-composited library
textures with tints — a collage, not generated art. That is why the materials looked wrong
no matter how the tint or roughness was tuned (docs/ASSEMBLY_MODEL.md §7.3c, §9).

Hunyuan3D-Paint is that model (PBR synthesis; its own report measures CLIP-FiD 24.78, better
than every baseline it compares against). It is documented at 21 GB VRAM, so this driver
scales the work down for an 8 GB card: smaller render/texture targets, fewer views, and an
OOM ladder that steps down once before giving up.

Usage:
  tools/img23d/paint_run.py <mesh.glb> <reference.png> <out.glb> [--texture 2048]
"""
from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from pathlib import Path

# expandable_segments fails to *map* on this card when the pool is nearly full
# ("memory mapping failed with OOM ... free: 142 MB"): it needs a contiguous VA range it
# cannot get, so a 20 MB allocation dies with 135 MB free. A split cap fragments less
# aggressively and does not need remapping.
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'max_split_size_mb:256,garbage_collection_threshold:0.8')

ORIG_CWD = Path.cwd()   # captured before chdir: argv paths are relative to here
ROOT = Path(__file__).resolve().parent
REPO = ROOT / 'Hunyuan3D-2.1'
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'hy3dpaint'))
os.chdir(REPO)

import torch  # noqa: E402


def _install_torchvision_shim() -> None:
    """basicsr (pulled in by realesrgan) imports torchvision.transforms.functional_tensor,
    which newer torchvision removed. Aliasing it is the documented workaround."""
    try:
        import torchvision.transforms.functional as _F
        sys.modules.setdefault('torchvision.transforms.functional_tensor', _F)
    except Exception as e:
        log(f'torchvision shim skipped: {type(e).__name__}')


def _patch_obj_to_glb() -> None:
    """Replace the Blender-based OBJ->GLB conversion with trimesh (bpy is shimmed)."""
    def convert_obj_to_glb(obj_path, glb_path, *a, **kw):
        import trimesh
        scene = trimesh.load(obj_path, force='scene')
        scene.export(glb_path)
        return True

    import DifferentiableRenderer.mesh_utils as mu
    mu.convert_obj_to_glb = convert_obj_to_glb
    import textureGenPipeline as tgp
    if hasattr(tgp, 'convert_obj_to_glb'):
        tgp.convert_obj_to_glb = convert_obj_to_glb


def _install_bpy_shim() -> None:
    """Stand-in for `bpy`, which has no cp312 wheel on PyPI.

    `DifferentiableRenderer.mesh_utils` imports bpy for mesh I/O, and the paint pipeline
    uses exactly one function from it (`convert_obj_to_glb`), which is monkeypatched to
    trimesh below — so bpy is never actually exercised.
    """
    import types
    if 'bpy' in sys.modules:
        return
    stub = types.ModuleType('bpy')
    stub.data = types.SimpleNamespace(scenes={}, objects={})
    stub.context = types.SimpleNamespace(window=None, scene=None, view_layer=None)
    stub.ops = types.SimpleNamespace()
    stub.app = types.SimpleNamespace(version_string='shim')
    sys.modules['bpy'] = stub


_install_bpy_shim()
_install_torchvision_shim()
_install_torchvision_shim()

NEED_MB = 2600   # with CPU offload only activations need VRAM   # paint is a 2B model + renderer; 'free' already excludes the desktop
DESKTOP_RESERVE_MB = int(os.environ.get('GPU_DESKTOP_RESERVE_MB', '1300'))


def log(m: str) -> None:
    print(f'[paint] {m}', flush=True)


def wait_for_vram(need_mb: int, tag: str, poll_s: int = 20, timeout_s: int = 0) -> bool:
    t0 = time.time()
    while True:
        free, _ = torch.cuda.mem_get_info()
        free_mb = free >> 20
        if free_mb >= need_mb:
            return True
        if timeout_s and time.time() - t0 > timeout_s:
            log(f'VRAM tight at {tag} ({free_mb} MB free, want {need_mb}); best effort')
            return False
        log(f'waiting for VRAM at {tag}: {free_mb} MB free, want {need_mb}')
        time.sleep(poll_s)


def build_pipeline(texture_size: int, render_size: int, views: int):
    _patch_obj_to_glb()
    from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
    cfg = Hunyuan3DPaintConfig(max_num_view=views, resolution=512)
    # Load weights into system RAM first: the 2B diffusion model alone OOMs the card during
    # loading (measured: 12 MB allocation failing with 6.2 GB free), so accelerate's
    # cpu_offload never got a chance to run. Load on CPU, then swap in per forward pass.
    cfg.device = 'cpu'
    cfg.render_size = render_size
    cfg.texture_size = texture_size
    # Do NOT truncate candidate_camera_azims/elevs: bake_view_selection indexes them with
    # indices produced against the full set, so a shortened list raises IndexError
    # (measured 2026-11-24). View count is controlled by max_num_view above.
    pipe = Hunyuan3DPaintPipeline(cfg)
    return pipe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('mesh')
    ap.add_argument('image')
    ap.add_argument('out')
    ap.add_argument('--texture', type=int, default=2048)
    ap.add_argument('--render', type=int, default=384)
    ap.add_argument('--views', type=int, default=3)
    a = ap.parse_args()

    a.mesh = str((ORIG_CWD / a.mesh).resolve())
    a.image = str((ORIG_CWD / a.image).resolve())
    a.out = str((ORIG_CWD / a.out).resolve())
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    for p in (a.mesh, a.image):
        if not Path(p).exists():
            log(f'missing input: {p}')
            return 1

    ladder = [(a.texture, a.render, a.views)]
    if a.texture > 1024:
        ladder.append((1024, 384, 3))
    if len(ladder) == 2:
        ladder.append((1024, 256, 3))
    ladder.append((1024, 192, 3))

    for attempt, (tex, rend, views) in enumerate(ladder, start=1):
        log(f'attempt {attempt}: texture={tex} render={rend} views={views}')
        gc.collect()
        torch.cuda.empty_cache()
        # 'free' already excludes the desktop, so the reserve must NOT be added again
        wait_for_vram(NEED_MB, 'paint')
        t0 = time.time()
        pipe = None
        try:
            pipe = build_pipeline(tex, rend, views)
            # The 2B diffusion weights alone exceed this card. accelerate's cpu_offload keeps
            # them in system RAM and swaps them in per forward pass — the same pattern
            # run21_offload.py uses for the shape model. Slow, but it fits.
            # The wrapper classes hold a diffusers pipeline; accelerate's cpu_offload cannot
            # see through them (no state_dict), but diffusers' own model offload is built for
            # exactly this and keeps GPU compute. This is the documented low-VRAM path.
            # Offload is opt-in: diffusers' model offload works for the diffusion net but
            # this custom pipeline then mixes devices (measured: "weight is on cuda:0,
            # different from other tensors on cpu"). CPU-resident is slow but correct, and
            # slow is acceptable for a batch texture bake.
            offloaded = 0 if not os.environ.get('PAINT_OFFLOAD') else 0
            for name in ('multiview_model', 'super_model'):
                m = pipe.models.get(name)
                inner = getattr(m, 'pipeline', None) or m
                fn = getattr(inner, 'enable_model_cpu_offload', None) if os.environ.get('PAINT_OFFLOAD') else None
                if fn is None:
                    continue
                try:
                    fn(device='cuda')
                    offloaded += 1
                    log(f'diffusers model offload enabled: {name}')
                except Exception as e:
                    log(f'offload failed for {name}: {type(e).__name__}: {str(e)[:80]}')
            if not offloaded:
                log('no diffusers offload available; running CPU-resident (slow)')
            torch.cuda.empty_cache()
            gc.collect()
            log('pipeline loaded, painting …')
            pipe(str(a.mesh), str(a.image), str(a.out), use_remesh=True, save_glb=True)
            size = Path(a.out).stat().st_size / 1e6
            log(f'OK in {time.time() - t0:.0f}s -> {a.out} ({size:.1f} MB)')
            return 0
        except torch.cuda.OutOfMemoryError as e:
            log(f'OOM at texture={tex}: {str(e)[:120]}')
            if pipe is not None:
                del pipe
            gc.collect()
            torch.cuda.empty_cache()
        except Exception as e:
            log(f'FAILED at texture={tex}: {type(e).__name__}: {str(e)[:200]}')
            import traceback
            traceback.print_exc()
            return 1
    log('all attempts OOM — the paint stage needs more than this card can give')
    return 1


sys.exit(main())
