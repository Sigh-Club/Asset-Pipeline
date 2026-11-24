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
  panel.py           spec sheet → per-view RGBA panels (system python, no GPU)
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

# spec sheet → multiview (see "Spec sheets" below)
tools/img23d/panel.py sheet.png --out /tmp/views --box front:X,Y,W,H --box side:X,Y,W,H \
    --mirror left=side
tools/img23d/img23d.py --front /tmp/views/front.png --left /tmp/views/left.png \
    --right /tmp/views/side.png --back /tmp/views/back.png --seed 7 --resolution 384
```

`--steps` and `--resolution` reach the pipeline as `num_inference_steps` / `octree_resolution`
(fixed 2026-11-24 — before that both were passed under the wrong names and silently ignored, so
every run did 50 steps at octree 384 whatever the flags said). Hunyuan defaults: 50 steps, octree
384. 20 steps at octree 320 halves the runtime (62 s vs 96 s measured) and loses fine detail —
use it for look-dev, not for the mesh you keep.

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

    img23d.py --front front.png --left left.png --right right.png --seed 7 --steps 50 --resolution 384

## Spec sheets → models (PROVEN 2026-11-24, helmet + rifle)

The Gemini concept sheets (`~/Pictures/IoA Gemini/Gemini_Generated_Image_*.png`, e.g. the ID-H9 helmet
and ID-90 plasma rifle spec sheets) are multiview already, and they convert. Measured on the shared
8 GB card, one job at a time:

| sheet | input | result |
|---|---|---|
| ID-H9 helmet | front/side/mirrored side/back, octree 384, 50 steps | 130.9 s, 690 550 verts, 1.38 M faces, 4 shells, bounds 1.90×1.98×2.00 — dome, brow trim, visor recess, comms box, both antennae, chin vent, rear louvre all present |
| ID-90 rifle | front (extent-cased) + side + mirrored side, octree 384, 50 steps | 122.3 s, 124 871 verts, watertight, 0.295×0.774×1.995 — receiver, scope, stock, grip, magazine well, muzzle present; handguard slots and cable bundle fused |

Both rows are the documented commands below, `panel.py` → `img23d.py`, seed 7, on the shared 8 GB card.
Wall time varies with desktop VRAM pressure (the same helmet job ran 96-131 s); the mesh differs
slightly run to run even at a fixed seed.

**The sheet must be split into per-view panels first.** Fed whole, the model fuses the leader lines,
dimension callouts, title block and grid into the geometry. `panel.py` crops a panel, deletes the 1–3 px
leader/dimension rules with a morphological opening, keeps the largest connected ink component, fills
it, and writes RGBA on true alpha (which the shape stage trusts, so rembg never runs):

```bash
tools/img23d/panel.py sheet.png --out /tmp/views \
    --box front:170,300,440,510 --box side:1120,310,580,560 \
    --box top:1900,300,540,560 --box back:160,890,530,540 --mirror left=side
```

Boxes are `x,y,w,h` in sheet pixels — find them by cropping and looking. `--mirror NEW=SRC` writes the
opposite side by flipping one view (2mv needs both); `panels.json` records boxes, sizes and extents.

### Trap: each view is rescaled independently

`MVImageProcessorV2.recenter` (`Hunyuan3D-2/hy3dgen/shapegen/preprocessors.py:36`) normalises **every
view's silhouette to fill the frame on its own**. Relative scale between views is destroyed, so an
elongated object seen muzzle-on gets its cross-section inflated to the object's length. Measured on the
rifle: 0.412×0.863 cross-section against a 1.993 length (thickness/length 0.207). `--extent VIEW=W:H`
re-cases that view on a canvas of its true projected bounding box (white, alpha=1 padding — invisible in
the composite but inside the mask bbox, which is what `recenter` scales by). Same job after the fix:
0.295-0.307 × 0.764-0.774, thickness/length **0.148-0.154**, which matches the sheet's own 1:1 panels —
the fix is the padding, not a guess.

### Trap: the sheets are not scale-consistent between panels

The helmet sheet draws the same object at 395×485 px (front panel) and 527×522 px (side panel, labelled
SCALE 1:1), so panels disagree by ~30 %. Shape comes out right; **absolute dimensions do not** — the
reconstruction made the helmet 1.90 wide against 1.63 implied by the front panel's own aspect. Take the
real numbers from the printed dimension callouts and correct the mesh in Blender, or reconcile panel
scales before the run. Do not trust the reconstruction's units.

### What a reconstruction is, and is not

Shape only. No colour (the texture stage needs 16 GB), no part separation (the helmet is one blob in 4
shells — visor, antennae and trim have to be split in Blender to take separate materials), no
hard-surface crispness (handguard slots, muzzle-brake fins and cable bundles fuse).
`tools/glb_contract.py` fails both as shipped — helmet against `--kind prop` (1.38 M tris / 23.7 MB,
cap 12 000 / 4.0), rifle against `--kind weapon` (250 k tris / 4.29 MB, cap 8 000 / 4.0), both with no
UVs, no normals and no texture. So the mesh is a **master**, and the prop route is decimate →
`tools/blender/uv_prepare.py` → PBR from the library → up-axis and origin → the gate. (A rigged
*unit* has a better route: `tools/build_unit_aaa.sh` takes an img23d mesh to the 120 k AAA-PC band with
baked normal/AO, but it wants a rig and clips, which a helmet or rifle does not have yet.) Judge the
result against the sheet (G5), not against the numbers.

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

## Normal-bridge carve (PROVEN 2026-10-21, crow-panel v2) — the detail tier upgrade

Adopted from bytedance/Hi3DGen (MIT, arXiv 2503.22236): detail must come from a
PREDICTED NORMAL MAP, never from photo luminance.

1. `MarigoldNormalsPipeline` (diffusers, prs-eth/marigold-normals-v1-1, fp16 ~3GB)
   on each view, square-padded, ensemble 3, res 768 -> normals [-1,1].
2. Relight the normal map under 3 fixed raking lights, multiply the shadings,
   normalise -> grain-free detail image; mask background to neutral 128.
3. Feed as the carve reference (sculpt_detail --smooth 0 --strength 0.02;
   side_carve --strength 0.012; detail_loop target 70).

Results vs photo-carve (same mesh): front audit capture 36.2% -> 69.9%,
side 53/72 -> 57/78, spurious 22.5 (guarded). Registration is bbox-stretch:
crop the relight to the panel bbox of the PADDED canvas and flatten bg, or the
plate gets embossed with background noise.

Helper: /tmp/normals.py pattern (normalise, 3-light product). VRAM: unload
pipe (del + empty_cache) before the next stage.

### Multi-scale carve (PROVEN 2026-10-21 crow-panel v3) — default for relief plates

Single-pass carve (one blur) cannot carry both the ~20mm inter-bird grooves AND
2mm barbs. Cumulative passes on the DC mesh, smooth 0, strongest first:

    sculpt_detail s0 blur 30 str 0.025   # macro separation grooves
    sculpt_detail s1 blur 12 str 0.020   # feather layer
    sculpt_detail s2 blur 5  str 0.012   # barbs
    side_carve str 0.012 (audit; v3: L 55->66, R 83->89)

Then finalise. Total added relief up to ~10mm on a 696mm panel; raise/lower
strengths proportionally with panel scale. NEVER rely on hy3d raw relief: the
mv latent decoder flattens; the carve IS the detail.

Blender glb import rotates axes (Y-up->Z-up): after import, recompute extents
and sort axes [widest,second,thinnest] before any scale-by-height, else the
scale factor uses the depth axis and the print is 3x oversize (hit twice).

---

## Game-asset use (2026-11-09)

The stage now feeds the **3D combat pipeline** as well as printing:

    concept/orthos -> img23d -> inspect_mesh.py (decimate) -> uv_prepare.py (weld+UV)
                   -> rig_unit_proof.py -> glb_contract.py

Two consequences for this stage:

- Output is used as a **base mesh**, not an asset. It arrives as triangle soup
  (every triangle carries its own vertices) with no UVs and no PBR separation; the
  weld in `uv_prepare.py` reduces a 20K-tri unit from ~60K verts to ~10K before
  unwrapping. Never skip that step.
- This is the most VRAM-hungry stage in the repo. It waits for free VRAM and loads
  a CUDA sysmem-spill shim by default. Budgets, profiles and the one-job-at-a-time
  rule are in [`3D_ASSETS.md`](3D_ASSETS.md) §4; check headroom with
  `python3 tools/gpu_policy.py status` before a batch.
