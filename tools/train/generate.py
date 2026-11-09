#!/usr/bin/env python3
"""generate.py — run a trained adapter through the production sampling path.

This is the only script that turns an adapter into assets. It exists so that the
evaluation grid and the material build use exactly the same sampling path: base
model, adapter, sampler settings, seamless handling and repair.

Usage:
    # one prompt, four seeds, exact tiling attempt + repair
    python3 tools/train/generate.py --adapter output/train/materials_v2/checkpoint-750 \
        --prompt "worn gunmetal steel, fine scratches, oil sheen" \
        --seeds 1,2,3,4 --out output/gen/gunmetal

    # a fixed prompt set (used by the eval gate)
    python3 tools/train/generate.py --adapter <dir> --prompts tools/train/prompts/eval_materials.json \
        --out output/gen/grid --seeds 11,22,33,44

Output per image: <slug>_s<seed>.png plus meta.jsonl carrying the prompt, seed,
adapter hash, base model, sampler settings and measured seam before/after repair.
The manifest is the provenance record; nothing is generated without it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BASE_MODEL = "black-forest-labs/FLUX.2-klein-base-4B"
DEFAULT_STEPS = 16
DEFAULT_GUIDANCE = 4.0
SEAM_LIMIT = 0.02


# ---------------------------------------------------------------- geometry ---

def seam_score(arr: np.ndarray) -> float:
    a = arr.astype(np.float32)
    lr = np.abs(a[:, 0] - a[:, -1]).mean()
    tb = np.abs(a[0] - a[-1]).mean()
    return float((lr + tb) / 2.0 / 255.0)


def seam_ratio(arr: np.ndarray) -> float:
    """Wrap-edge roughness / interior-edge roughness. This is the metric the
    adoption gate uses; absolute border difference is not a seam measurement."""
    a = arr.astype(np.float32)
    border = (np.abs(a[:, 0] - a[:, -1]).mean() + np.abs(a[0] - a[-1]).mean()) / 2 / 255
    interior = (np.abs(a[:, 1:] - a[:, :-1]).mean() + np.abs(a[1:] - a[:-1]).mean()) / 2 / 255
    return float(border / max(interior, 1e-6))


_DM = None


def _derive_maps():
    global _DM
    if _DM is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "derive_maps", ROOT / "tools" / "pbr" / "derive_maps.py")
        _DM = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_DM)
    return _DM


def repair(arr: np.ndarray) -> np.ndarray:
    """The production treatment, in the same order as the material pipeline:
    flatten baked lighting, then repair the seam only if it is broken."""
    dm = _derive_maps()
    before = seam_score(arr)
    out = dm.flatten_lighting(arr.astype(np.float32))
    if before > SEAM_LIMIT:
        out = dm.seamless(out)
    return out.clip(0, 255).astype(np.uint8)


def _blend_border(packed: "object", band_frac: float = 0.08) -> "object":
    """Constrain the latent to be periodic at every denoising step.

    FLUX.2 packs the latent into a token sequence (B, H*W, C); this unpacks the
    square grid, cross-fades a border band with the wrapped interior, then
    repacks. A texture model has no reason to make one border equal to the
    opposite border; giving the sampler a periodic boundary each step does. This
    is the latent-space analogue of circular-pad convolution used by the
    ComfyUI/A1111 seamless modes. Measure the result, never assume it.
    """
    import math
    import torch
    b, s, c = packed.shape
    hw = int(round(math.sqrt(s)))
    if hw * hw != s:
        return packed
    lat = packed.view(b, hw, hw, c).permute(0, 3, 1, 2).contiguous()
    by = max(1, int(hw * band_frac))
    # mask 1 at the outer edge, 0 at the inner edge of the band
    my = torch.linspace(1.0, 0.0, by, device=lat.device, dtype=lat.dtype)[None, None, :, None]
    mx = torch.linspace(1.0, 0.0, by, device=lat.device, dtype=lat.dtype)[None, None, None, :]

    top = lat[..., :by, :].clone()
    bot = lat[..., -by:, :].clone()
    lat[..., :by, :] = top * (1 - my) + bot.flip(-2) * my
    lat[..., -by:, :] = bot * (1 - my.flip(-2)) + top.flip(-2) * my.flip(-2)

    left = lat[..., :, :by].clone()
    right = lat[..., :, -by:].clone()
    lat[..., :, :by] = left * (1 - mx) + right.flip(-1) * mx
    lat[..., :, -by:] = right * (1 - mx.flip(-1)) + left.flip(-1) * mx.flip(-1)
    return lat.permute(0, 2, 3, 1).reshape(b, s, c)


# ------------------------------------------------------------------ models ---

def adapter_hash(path: Path) -> str:
    if path.is_dir():
        p = path / "pytorch_lora_weights.safetensors"
        path = p if p.exists() else next(iter(path.glob("*.safetensors")))
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_pipe(adapter: Path | None, dtype: str = "bfloat16", offload: str = "sequential"):
    import os
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from diffusers import Flux2KleinPipeline

    td = {"bfloat16": torch.bfloat16, "float16": torch.float16,
          "float32": torch.float32}[dtype]
    pipe = Flux2KleinPipeline.from_pretrained(BASE_MODEL, torch_dtype=td)
    if adapter is not None:
        pipe.load_lora_weights(str(adapter))
    # 4B at bf16 is 8 GB. The desktop (browser compositor) holds ~3 GB of the
    # 8 GB card on this box, so model-level offload is not always enough;
    # sequential offload streams the blocks and fits in ~2 GB.
    if offload == "sequential":
        pipe.enable_sequential_cpu_offload()
    elif offload == "model":
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    return pipe


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def generate(pipe, prompt: str, seed: int, size: int, steps: int,
             guidance: float, seamless: str, do_repair: bool):
    import torch

    callback = None
    kwargs = {}
    if seamless == "blend":
        callback = lambda p, i, t, k: {"latents": _blend_border(k["latents"])}  # noqa: E731
        kwargs["callback_on_step_end"] = callback
        kwargs["callback_on_step_end_tensor_inputs"] = ["latents"]

    gen = torch.Generator("cpu").manual_seed(seed)
    image = pipe(prompt=prompt, height=size, width=size, num_inference_steps=steps,
                 guidance_scale=guidance, generator=gen, **kwargs).images[0]
    arr = np.asarray(image.convert("RGB"))
    before = seam_score(arr)
    if do_repair:
        arr = repair(arr)
    after = seam_score(arr)
    return Image.fromarray(arr), before, after, seam_ratio(arr)


# -------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", help="checkpoint dir or .safetensors; omit for base model")
    ap.add_argument("--prompt")
    ap.add_argument("--prompts", help="JSON list of {id, prompt, kind} or a plain list")
    ap.add_argument("--seeds", default="1,2,3,4")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    ap.add_argument("--guidance", type=float, default=DEFAULT_GUIDANCE)
    ap.add_argument("--seamless", choices=("off", "blend"), default="blend")
    ap.add_argument("--no-repair", action="store_true")
    ap.add_argument("--dtype", default="bfloat16", choices=("bfloat16", "float16", "float32"))
    ap.add_argument("--offload", default="sequential", choices=("sequential", "model", "none"))
    args = ap.parse_args()

    if not args.prompt and not args.prompts:
        raise SystemExit("need --prompt or --prompts")

    if args.prompts:
        data = json.loads(Path(args.prompts).read_text())
        prompts = [(p.get("id") or slugify(p["prompt"]), p["prompt"], p.get("kind", "in_domain"))
                   for p in data]
    else:
        prompts = [(slugify(args.prompt), args.prompt, "in_domain")]

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    adapter = Path(args.adapter).resolve() if args.adapter else None
    ahash = adapter_hash(adapter) if adapter else None
    pipe = load_pipe(adapter, args.dtype, args.offload)

    meta_path = out / "meta.jsonl"
    rows = []
    for pid, prompt, kind in prompts:
        for seed in seeds:
            img, before, after, ratio = generate(pipe, prompt, seed, args.size, args.steps,
                                                 args.guidance, args.seamless, not args.no_repair)
            name = f"{pid}_s{seed}.png"
            img.save(out / name)
            row = {
                "file": name, "id": pid, "prompt": prompt, "kind": kind, "seed": seed,
                "size": args.size, "steps": args.steps, "guidance": args.guidance,
                "seamless": args.seamless, "repaired": not args.no_repair,
                "base_model": BASE_MODEL, "adapter": str(adapter) if adapter else None,
                "adapter_sha256_16": ahash,
                "seam_raw": round(before, 4), "seam_repaired": round(after, 4),
                "seam_ratio": round(ratio, 3),
            }
            rows.append(row)
            with meta_path.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"{name}: seam {before:.3f} -> {after:.3f}, ratio {ratio:.2f}")

    gate_pass = sum(1 for r in rows if r["seam_ratio"] <= 1.5 or r["seam_repaired"] <= SEAM_LIMIT)
    print(f"{gate_pass}/{len(rows)} tiles seam-correct (ratio <= 1.5 or absolute <= {SEAM_LIMIT}) -> {out}")


if __name__ == "__main__":
    sys.exit(main())
