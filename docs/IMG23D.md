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

## Printer prep — Creality CR-200B (200³ enclosed)

`tiles.py` cuts any reconstruction/plate into bed-sized watertight tiles
(heightfield-level cut → relief continuous across seams; butt-glue + optional
6 mm dowels, `dowel_6x8.stl`). Machine limits, verified faults and fixes, and
the slicer profile live in the agent skill `~/.pi/agent/skills/cr200b/SKILL.md`
(CR-200B: 200³, 0.4 nozzle, PTFE hotend ≤250 °C, poor stock adhesion — glue
stick mandatory, bowden extruder — ≤60 mm/s, 0.12 mm layers for detail).

```bash
tools/img23d/.venv/bin/python tools/img23d/tiles.py <mesh.glb> --width 628 --bed 190
# → <name>_tiles/: 16 × ~157 mm tiles + manifest + dowels, all pre-checked
#   watertight/single-component; reject any tile the slicer flags
```
Detail floor: heightfield must come from ≥384 MC resolution + ≥960 grid
(`--resolution 384` on img23d.py); below that, 2 mm features print as blobs on
the 0.4 nozzle.

## Multiview capture — prompt templates (the 100%-3D path)

Hunyuan3D-2mv wants front/left/right/back, camera level, object 70–80% of frame,
identical light, plain background. Generate as EDITS of the approved front
render (upload it with each prompt) — never fresh generations, or identity
drifts and the fusion smears.

Template (swap the bracketed view; run once per view):

    Using the attached image as the exact reference: the identical object —
    every book, same colours, same damage, same positions — photographed
    rotated to show its [LEFT SIDE 90° | RIGHT SIDE 90° | BACK], as if the
    object turned on a turntable. Camera at the same height and distance as the
    reference, straight-on orthographic view, no perspective. Same soft even
    lighting, same plain light-grey seamless background, object centred and
    filling the same fraction of frame. Nothing else in frame.

Notes:
- left/right are the money views: page blocks, overhang depths, how far the
  dragon stands off the wall — the geometry a relief cannot encode.
- back is optional (plain surfaces reconstruct fine from front+2 sides).
- one view per generation; verify each against the front (same books, same
  order) before running the batch:

    img23d.py --front front.png --left left.png --right right.png --seed 7 --steps 30 --resolution 384

## Low-VRAM operation (shared-GPU desktop, 8 GB card)

The GPU is shared with chrome/discord by policy — they are never killed. Four
defence layers, all wired into `img23d.py` (2026-10-21):

1. **Allocator defrag**: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` set
   by the wrapper before torch imports. Kills fragmentation OOMs.
2. **VRAM wait**: `wait_for_vram()` polls `nvidia-smi` and holds until ≥4.5 GB
   free (600 s cap) before loading the model.
3. **OOM retry with step-down**: on `CUDA out of memory` — empty cache, gc,
   wait, then `-64` resolution / `-10` steps, up to 3 attempts.
4. **Sysmem fallback shim** (`~/.local/lib/libcuda_vmm_fallback.so`, MIT, from
   `AmeerJ97/cuda-vmm-sysmem-fallback`): LD_PRELOAD'd automatically by the
   wrapper. Linux has no Windows-style VRAM→RAM spill; the shim intercepts
   driver-level allocs on OOM and splits them VRAM+RAM via CUDA VMM. Verified:
   7.2 GB alloc on 6.2 GB-free card → 5.7 VRAM + 1.0 RAM. Cap spill with
   `CUDA_VMM_FALLBACK_MAX_SYSMEM` (default 50 % RAM); disable with
   `CUDA_VMM_FALLBACK_DISABLE=1` (per-process) or `CUDA_VMM_DISABLE=1`
   (wrapper).

Ad-hoc blocking from scripts: `gpu-wait [min_free_mb] [timeout_s]`
(`~/.pi/agent/bin/gpu-wait`).

Desktop-side the two big cheap wins: Discord → Settings → Advanced →
Hardware Acceleration **off** (frees 0.5–1 GB permanently), and Chrome →
Settings → System → "Use graphics acceleration when available" **off** if
browser VRAM pressure is chronic (pages render on CPU; fine for browsing).

## Anti-grain / detail-retention chain (PROVEN 2026-10-21, crow-panel)

Order matters. Smooth-last melts detail; smooth-first via DC is lossless:

1. mv shape (`img23d.py --front/--left/--right --seed 7 --steps 50 --resolution 384`)
2. **printprep DC remesh FIRST** (`printprep.py in.glb out.stl --dc-res 1024`)
   — dual contouring re-positions vertices on the true iso-surface: kills MC
   staircase/voxel-sand with **zero vertex relaxation** (Warren DMC paper: thin
   features without MC's smoothing). This replaces heavy smoothing, not
   complements it.
3. `sculpt_detail.py dc.stl artwork.jpg --strength 0.025 --smooth 6` — token
   smooth only. **Do NOT use the default smooth=30**: Humphrey
   (alpha .1/beta .6) at 30 iters rounds feather-scale edges faster than the
   carve restores them (Garland smoothing notes; Laplacian-family shrinks,
   Taubin λ/μ is the near-lossless variant if smoothing must be heavier —
   `trimesh.smoothing.filter_taubin(lamb=.5,nu=-.53)`).
4. `side_carve.py --left l --right r --strength 0.012` (audit-gated)
5. `detail_loop.py --target 60 --max-iters 2` — keep only capture-positive passes
6. hole boolean / float purge / boundary fill / centre + ×1000 mm last.

Empirically (crow-panel): Humphrey-30-first chain → visible detail erosion;
DC-first chain → crisp feather relief, capture 67% sides / 36% front
(render-edge ceiling ~43% per quality ladder).

## Blender 5.1 headless — verified API traps (all hit 2026-10-21)

- `bpy.ops.wm.stl_import` / `wm.stl_export` (NOT import_mesh/export_mesh).
  GLB: `bpy.ops.export_scene.gltf(export_format='GLB')`; there is NO
  `bpy.ops.wm.export`.
- `mesh.vertices` prop arrays are NOT sliceable (`vs[::step]` TypeError) —
  use `foreach_get('co', np.empty(n*3))`.
- `bpy.ops.object.voxel_remesh` takes NO kwargs in 5.1 and `object.remesh_mode`
  doesn't exist; mesh-level attrs also absent — plain `bpy.ops.object.voxel_remesh()`
  after setting nothing works (defaults), else avoid voxel entirely.
- After `bpy.data.objects.remove()`, re-set `view_layer.objects.active` before
  any mode_set, else "Context missing active object".
- Edit-mode bmesh needs an explicit `mode_set('EDIT')` first (poll fails
  silently otherwise in background).
- User addons break background runs when their PIL is broken:
  `LD_LIBRARY_PATH=~/.config/blender/5.1/scripts/addons/modules/PIL.libs`.
- hy3d/Blender mesh is a FLAT SLAB: thickness on Z, front +z, up +y. Any camera
  on ±Y sees an edge-on sliver unless you rotX ±90 first. Blank grey renders =
  this, every time.
- f3d 3.5: comma-separated option values (`--resolution 900x920` warns; still
  renders 300² default), `--camera-view-up 0,1,0` comma-form; HUD/grid show
  even in "background" renders — fine for QC, never for deliverables.
- Reliable artifact QC without any renderer: matplotlib PolyCollection of
  subsampled faces, shaded by `n·light` (see session/proven in crow-panel).
- STL units are silent: decide the convention (1 unit = 1 mm) and apply
  `apply_scale(1000)` from model-space before export, then re-verify extents.
