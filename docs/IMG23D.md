# Image-to-3D stage (`tools/img23d/`)

Generated concept art → printable/renderable mesh. Sits **before** the Blender
pipeline: its output is a master mesh that feeds either the sprite render
pipeline (import → rig/pose → 8-dir render) or direct 3D printing.

## Engines

| engine | repo | licence | VRAM | note |
|---|---|---|---|---|
| `hunyuan` (default) | `vendor/Hunyuan3D-2`, model `tencent/Hunyuan3D-2mini` | Tencent Hunyuan Community (see NOTICE) | ~6 GB shape-only | best geometry; 87 s on RTX 3070 Ti @ 20 steps |
| `triposr` | `vendor/TripoSR`, `stabilityai/TripoSR` | MIT | ~6 GB | fast fallback; blobbier on fine relief |

Weights auto-download from Hugging Face on first run to `~/.cache/hy3dgen`
(HF reachable; Civitai is region-blocked from this network — irrelevant here).

## Layout

```
tools/img23d/
  img23d.py          CLI wrapper (re-execs itself under .venv)
  .venv/             python3.12 env (gitignored) — torch cu126, hy3dgen deps
  Hunyuan3D-2/       shallow clone (gitignored)
  TripoSR/           shallow clone (gitignored)
output/img23d/<stem>-<engine>/   glb + obj + stl
```

## Usage

```bash
tools/img23d/img23d.py concept.png                     # hunyuan, seedless
tools/img23d/img23d.py a.png b.png --seed 7 --steps 20 # batch, reproducible
tools/img23d/img23d.py x.png --engine triposr --resolution 320
tools/img23d/img23d.py x.png --formats stl --quiet     # print-only
```

The wrapper prints per-mesh QC (verts/faces/watertight/components/bounds).
Non-watertight output is normal — repair before printing:

```bash
blender -b model.glb --python <(echo "…3D-Print Toolbox: make manifold, export STL")
```
or interactively: Blender → Edit → Preferences → 3D Print Toolbox →
*Make Manifold* → check wall thickness → export STL.

## Input rules (same as concept art elsewhere)

Single object, plain/absent background, even lighting. Images with real alpha
skip rembg entirely (`--no-rembg` trusts alpha); RGB images go through rembg
(onnprocruntime CPU) with a white-composite fallback.

## Certified state (2026-10-16, RTX 3070 Ti 8 GB)

- hunyuan mini-turbo, 20 steps, seed 7: 87 s shape, 418k verts / 836k faces,
  **watertight**, 1 component — `output/img23d/test_tome-hunyuan/`
- triposr, mc-res 256: 100k verts / 201k faces, not watertight, 8 components
  (floating shells — prune in Blender) — `output/img23d/test_tome-triposr/`

## Gotchas (all hit and resolved 2026-10-16)

- **Pin the AI stack**: `transformers==4.46.3` + `diffusers==0.35.1` +
  `huggingface_hub==0.36.2`. transformers ≥4.48 renamed Dinov2 attention keys
  (`q_proj`) and Hunyuan's bundled ckpt uses the old naming
  (`attention.attention.*`) → state_dict load crash. Latest diffusers wants
  hub 2.x which conflicts — the triple above is the known-good set.
- **torchmcubes** (TripoSR isosurface) must be built `--no-build-isolation`
  against the venv torch, and needs a system CUDA toolkit
  (`sudo pacman -S cuda`; `/opt/cuda`, set `CUDA_HOME`). CUDA 13 + the
  vendored `helper_math.h` trips a `lerp` redeclaration — patch guarded by
  `#if CUDA_VERSION < 13000` around the `float lerp` overload (upstream
  unpached as of 2026-10). It currently builds the CPU variant — works, adds
  seconds; revisit if TripoSR becomes the primary engine.
- System python is 3.14 (no torch wheels) — the venv is deliberately 3.12.
- Hunyuan `from_pretrained` needs an explicit `subfolder` per repo
  (`hunyuan3d-dit-v2-mini-turbo` / `hunyuan3d-dit-v2-0-turbo`) — the wrapper
  derives it; override with `--hunyuan-subfolder`.
- Texture stage (Hunyuan3D-Paint) needs 16 GB → skipped; sprites get
  materials from the Blender PBR library instead, per pipeline philosophy.

## Licence note

Hunyuan weights: Tencent Hunyuan Community License — check
`Hunyuan3D-2/LICENSE` before shipping game assets built from it commercially;
TripoSR is MIT. For IoA-internal sprites either is fine.
