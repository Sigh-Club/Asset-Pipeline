# 3D asset production — tools, contract and workstation limits

Status: implemented 2026-11-09. This document is the operating manual for the **3D**
half of the asset pipeline (GLB units, materials, environments). The 2D sprite
path (8-direction renders, atlases, palette) is documented in
[`BLENDER_WORKFLOW.md`](BLENDER_WORKFLOW.md) and `PIPELINE_V2.md`.

**Unit strategy (2026-11-21, canonical).** For units we **overlay imported DoW2 models** and
apply **XCOM 2 animation layers where the DoW2 models are lacking**, to fit our style and engine.
Import gives anatomy, a named 93-bone Biped skeleton and gear bones; the overlay (IoA palette,
IoA silhouette parts, IoA materials) gives identity; the animation layer supplies the poses DoW2
has no clip for (lateral cover lean, peek, cover enter/exit, high-cover lean, flinch, panic).
The environment/prop path below is unchanged. Canonical statement, measured source inventory and
phased plan: `Imperium-of-Ash/docs/game-design/MODEL_PORT_AND_ANIMATION_PLAN.md`.

Authorities: `Imperium-of-Ash/docs/game-design/FACTION_IDENTITY.md` (art rules),
`UNIT_ROSTER.md` (what exists), `3D_COMBAT_MIGRATION.md` §4 (GLB contract),
`ASSET_PIPELINE_ROADMAP.md` (quality bar and programme state).

---

## 1. Tool inventory

| Path | Stage | Notes |
|---|---|---|
| `tools/img23d/img23d.py` | image → mesh | Hunyuan3D-2mini shape-only or TripoSR; preloads a CUDA VMM sysmem shim and waits for VRAM |
| `tools/blender/inspect_mesh.py` | decimate + inspect render | writes `mesh_report.json` |
| `tools/blender/uv_prepare.py` | weld, unwrap, origin | **required** before rigging or texturing |
| `tools/blender/rig_unit_proof.py` | 22-bone humanoid rig + idle/walk/aim | proof-grade clips |
| `tools/blender/preview_unit_materials.py` | material preview render | heuristic zones, review target |
| `tools/blender/tile_generator.py` | environment/prop kit | existing 2D tile source; GLB export path pending |
| `tools/pbr/build_material_manifest.py` | material demand plan + prompts | 79 items → 22 image generations |
| `tools/pbr/derive_maps.py` | sheet → seamless PBR set | albedo → normal/roughness/metallic |
| `tools/pbr/build_blender_library.py` | material `.blend` | box-projected PBR materials |
| `tools/glb_contract.py` | acceptance gate | exit code blocks a bad asset |
| `tools/gpu_policy.py` | workstation budget | VRAM/RAM policy, job parameter matrix |
| `tools/blender_run.sh` | safe Blender launcher | waits for VRAM, caps threads, sets profile |

Contract values and clip list: `tools/glb_contract.py` (`LIMITS`, `REQUIRED_CLIPS`)
mirrors `3D_COMBAT_MIGRATION.md` §4. Change the doc and the script together.

---

## 2. Stage sequence (one unit)

```bash
cd /run/media/talzanar/games/Projects/IoA/asset-pipeline
SLUG=<faction>_<unit>

# 1. concept + orthos (Gemini, 4-up sheets where possible)
gemini-img "$(cat prompts/$SLUG.txt)" --out output/img23d/$SLUG/concept

# 2. mesh
tools/img23d/.venv/bin/python tools/img23d/img23d.py \
  --front .../front.png --left .../left.png --right .../right.png --back .../back.png \
  --seed 7 --steps 20 --resolution 256 --out output/img23d/$SLUG

# 3. decimate to the LOD0 budget
tools/blender_run.sh --job decimate -- -P tools/blender/inspect_mesh.py -- \
  --glb <mesh>.glb --out output/img23d/$SLUG/inspect --tris 20000 --render

# 4. weld + unwrap + place origin
tools/blender_run.sh --job uv -- -P tools/blender/uv_prepare.py -- \
  --glb output/img23d/$SLUG/inspect/lod0.glb --out output/img23d/$SLUG/uv

# 5. rig + proof clips
tools/blender_run.sh --job render -- -P tools/blender/rig_unit_proof.py -- \
  --glb output/img23d/$SLUG/uv/lod0_uv.glb --out output/img23d/$SLUG/rig --render

# 6. material preview (review the PNG)
tools/blender_run.sh --job render -- -P tools/blender/preview_unit_materials.py -- \
  --glb output/img23d/$SLUG/uv/lod0_uv.glb --faction <faction> \
  --out output/img23d/$SLUG/preview

# 7. gate
python3 tools/glb_contract.py output/img23d/$SLUG/rig/unit_rigged.glb --kind unit
```

Never run two Blender or CUDA jobs concurrently. Each stage is its own process so
memory is released between stages — that is the batching strategy, not a
convenience.

### Hard-surface and environment assets

Image-to-3D is for organic one-piece forms only. Weapons, armour add-ons, crates
and vehicles are built parametrically in Blender (primitives + bevel + weighted
normal, exact dimensions), which also yields clean UVs. Environment kits come
from `tile_generator.py`; image-to-3D is reserved for organic clutter.

---

## 3. Material and pattern library

Spec: `configs/materials/families.json` — 7 faction kits × 5 slots, 17 shared
surfaces, 14 patterns, 13 decals, palettes and per-slot physical tile sizes.

```bash
python3 tools/pbr/build_material_manifest.py             # (re)write plan + prompts + generate.sh
tools/pbr/generate_batch.sh N                            # one sheet: generate -> derive, stops on failure
bash assets/materials/grimdark_scifi/generate.sh         # all sheets (mind the quota)
python3 tools/pbr/derive_maps.py --all                   # sheets -> PBR sets
tools/blender_run.sh --job script -- -P tools/pbr/build_blender_library.py
```

Output: `assets/materials/grimdark_scifi/<item>/{albedo,normal,roughness,metallic,emissive}.png`,
`meta.json`, and `grimdark_scifi.blend` with `IOA_<faction>__<slot>` materials on
box (triplanar) projection.

Rules:
- The image model supplies **albedo only**. Normal/roughness/metallic are derived.
- Tile size is physical (`slot_tile_m`); painted/enamelled armour is dielectric
  (metal ≤ 0.2), bare metal and gold 0.8–1.0.
- Generated sheets live in `assets/**/sheets/` (gitignored); the derived maps are
  the tracked deliverable.
- Decals have no alpha from the image model. Ask for a plain white card, then
  `derive_maps.py` keys it (local background estimate, bbox crop, square padding).
  Mark genuinely full-bleed art with `full_bleed: true` so it is not keyed.
  Pale-on-white art still needs a grey card — recorded in `TODO.md`.
- Generate one sheet per invocation. The wrapper intermittently returns error 1096;
  retry once before assuming quota.

---

## 4. Workstation budget and low-memory operation

Measured 2026-11-09 on the only machine that does this work:

| Resource | Value |
|---|---|
| GPU | RTX 3070 Ti, 8192 MB total, ~1400 MB held by the desktop, ~6488 MB free |
| Usable for a CUDA job | free − 1024 MB reserve − 900 MB desktop reserve |
| CPU | Ryzen 7 5700X3D, 8C/16T (Blender threads capped at 8) |
| RAM | 31 GB (≈20 GB available), 31 GB swap |
| Image-to-3D need | ~4.2 GB shape-only at 256 px / 16 steps; 320 px / 30 steps needs ~5.6 GB |

Policy, enforced by `tools/gpu_policy.py` and `tools/blender_run.sh`:

1. **One GPU job at a time.** No parallel Blender renders, no bake during an
   img23d run. The launcher waits for the required free VRAM (default 600 s) and
   falls back to the `low` profile rather than failing the task.
2. **Profiles, not judgement.** `low` = 960×720 / 8 samples / 1024 bake / 12k
   decimate / 256 px 16 steps. `balanced` = 1280×960 / 16 / 2048 / 20k / 256 px 20.
   `max` = 1920×1080 / 32 / 2048 / 25k / 320 px 30. `auto` chooses from live free
   VRAM. The resolved profile is printed and exported as `IOA_GPU_PROFILE`.
3. **Break work into stages.** One process per stage; a batch is a loop of
   separate invocations, never one long-lived Blender session accumulating scenes.
4. **Bound the bake.** 2048 max, CPU denoise, tile 1024, one map type per bake.
5. **Bound the render.** Textures ≤ 2K, no volumes, EEVEE for previews; Cycles only
   when a specific look needs it and then at the low profile.
6. **Do not kill the user's desktop apps.** They hold the VRAM; wait your turn.
   `img23d` already waits and has a sysmem spill shim (`CUDA_VMM_*`).

```bash
python3 tools/gpu_policy.py status
python3 tools/gpu_policy.py plan --job img23d
tools/blender_run.sh --job bake --profile low -- -P ...
```

---

## 5. Acceptance

A 3D asset is done when: `glb_contract.py` passes, the preview renders were
reviewed at 720p and 1080p, an in-engine screenshot and a short motion clip exist,
the manifest and `ASSET_INVENTORY.md` are updated, the faction palette is
respected, and the unit/track names match `UNIT_ROSTER.md` code keys.

Tests prove plumbing. Renders and in-engine footage prove quality.

---

## 5a. Generative models and training

Nothing in the shipping pipeline is trained today: concepts and albedo come from the
hosted image model, geometry from img23d, and everything else from Blender. The
decision on what is worth training, the VRAM/RAM tables, dataset recipes, Gemini
shortcuts and the eval gates live in
[`GENERATION_TRAINING_RESEARCH.md`](GENERATION_TRAINING_RESEARCH.md); the procedure
an agent should follow is the `generative-training` skill.

Short version: train image/material LoRAs on small Apache-2.0 bases only
(FLUX.2 klein 4B, Z-Image-Turbo); do **not** train 3D shape or motion at this scale;
the real training constraint is 31 GB of system RAM, not the 8 GB of VRAM.

## 6. Known limitations (recorded, not hidden)

1. No retopology stage yet — decimated image-to-3D geometry has fused parts and
   poor deformation loops. Highest-value next improvement.
2. Clip set is 3 of 9; `run fire reload hit death melee` are missing everywhere.
3. Material zones are assigned by a height/normal heuristic; trim does not follow
   armour edges yet.
4. `uv_prepare.py` produces coarse islands (3 for a humanoid, 12.7 % UV coverage);
   adequate for box-projected materials, not for hand-painted atlases.
5. glTF export currently relies on Blender defaults for bone influences; limit to 4
   and normalise before shipping skinned units to other engines.

## 7. Retopo, slots and texture bake (2026-11-09, later session)

The stage sequence in §2 stops at a rigged, untextured proof. Three tools close the
gap to a contract-passing unit:

| Tool | Does | Gate |
|---|---|---|
| `tools/blender/retopo_unit.py` | welds the soup, drops debris, voxel-remeshes to one watertight shell, decimates to 20k tris, unwraps (measured texel density), assigns authored semantic zones (`helmet`, `torso`, `pauldron`, `arm`, `leg`, `boot`, `belt`, `backpack`, `weapon`) to slot materials and vertex groups; `--debug-zones` renders the split flat-shaded for review | `retopo_report.json` (tris, UV density, region counts) |
| `tools/blender/rig_unit_proof.py --clips all` | shared 22-bone humanoid rig, ≤4 distance weights normalised, the full 9-clip contract set (`idle walk run aim fire reload hit death melee`), NLA export | pose diag + clip list |
| `tools/blender/bake_unit_atlas.py` | bakes the box-projected library slot materials into a 2K atlas on the unit's UVs (Cycles diffuse/colour, lights off), then rebuilds slot materials from the atlas + derived maps and exports a textured GLB including the armature and clips | `glb_contract.py` PASS |

Measured on `line_infantry` (2026-11-09): 20,000 tris, 22 joints, 1 skin, UVs,
2K albedo + derived normal, 4 slot materials, 9 clips, 4.84 MB — **contract PASS**.
This is the first unit that passes; the game baseline is now empty and
`npm run guard:glb` enforces the contract on every shipped model.

Known limits, recorded:

- The remesh is automated topology, not artist retopology: uniform triangles and a
  softened silhouette (helmet and plate edges lose sharpness). Hero close-ups still
  need an artist pass.
- Zone→slot mapping is authored data in `REGION_SLOT`. The gunmetal legs/boots read
  very dark under a single area light; that is the material choice, not a bake bug.
  Tune per faction before the next unit.
- Atlas UV utilisation is ~25 % (Smart UV Project on a remeshed shell). A proper
  pack would allow 4K detail; 2K is sufficient at the isometric camera distance.

## 8. Style profiles, asset requests and the pixel gate (2026-11-09)

Style is selectable, not hard-coded. `configs/styles/profiles.json` defines
`pbr_3d`, `lowpoly_3d`, `palette_3d`, `palette_sprite` and `hd_sprite`, each
with geometry/texture/render/animation budgets and the gate set that accepts the
asset. `tools/style/profiles.py` validates them (unknown keys, cycles, palette
ids, budgets); `docs/STYLE_PROFILES.md` is the schema reference.

Assets are requested, not improvised: `configs/assets/examples.json` holds one
request per asset with a **route**:

| Route | Used for | Tool |
|---|---|---|
| `parametric_hard_surface` | weapons, barrels, crates, machinery | `tools/blender/parametric_prop.py` |
| `parametric_modular` | buildings, base modules, tiles | same, recipes `block`/`tile` |
| `procedural_organic` | foliage, simple organics | branch generator (Phase 5) |
| `image_to_3d` | units and creatures | `tools/img23d` + retopo |
| `pixel_ui` | icons, portraits, panels | `pz/pixel` |

Proof run (2026-11-09): `iron_directorate_barrel_a`, `iron_directorate_lasrifle`
and `tile_floor_industrial_a` built from requests at `palette_3d`, rendered 256²
without antialiasing, palette-checked (`tools/style/check_palette_asset.py`: drift
0.022–0.034, one component, fill in range). Outputs under `output/props/<id>/`.

The pixel gate measures palette drift in Oklab and silhouette integrity (component
count, bounding-box fill per asset kind). It is the pixel-tier counterpart to
`glb_contract.py`: PBR seam/flatness gates are meaningless for a palette-locked
asset. Human readability review is still required.

### 8a. The pixel-master route (2026-11-10) — `palette_3d` end to end

The 2026-11-09 proof produced *smooth-shaded* masters with palette drift 0.02–0.04:
correct geometry, wrong tier. The pixel look needs a texel grid, a band-limited
material source and a palette lock, and those are now stages with gates rather
than intentions. Two drivers run the whole route:

```bash
tools/build_asset.sh <out-name> <request-id> <prop|weapon|tile>
tools/build_unit.sh  <out-name> <unit-id> <textured-unit.glb> [faction]
```

| Stage | Tool | What it enforces |
|---|---|---|
| texel grid | `tools/blender/palette_uv.py` (via `bake_palette_atlas.py --stage texel`) | uniform `texel_world_m` density per island, UVs snapped to the atlas texel lattice, density contract ±25 % |
| material source | `tools/pbr/build_palette_variants.py` → `build_blender_library.py --pixel` | albedo band-limited to `2 × tile_m / texel_m` px so one texel samples an averaged texel, not a random sub-texel value |
| bake | `bake_palette_atlas.py --stage albedo` | albedo via a base-colour→emission reroute (a metallic material has no diffuse component, so `DIFFUSE` bakes black), plus an emission atlas |
| palette lock | `tools/style/palette_lock.py` | Oklab nearest-palette with ordered dither, binary alpha, despeckle; every opaque pixel must be an exact palette entry |
| final GLB | `bake_palette_atlas.py --stage final` | one palette material, `Closest` filtering, no PBR maps, flat shading |
| master | `tools/blender/render_master.py` + `master_render.py` | 8 directions at the profile canvas, no AA, one constant scale across the set, pose chosen explicitly, normal/AO/emission masks in Raw |
| gates | `check_texel_grid.py`, `check_palette_asset.py`, `check_master.py`, `glb_contract.py` | see below |

Certified 2026-11-10 (all four green, negative controls recorded in §8b):

| Asset | `<out>` | tris | density vs profile | atlas | off-palette | masks |
|---|---|---|---|---|---|---|
| line infantry (aim pose) | `output/gen/unit8` | 4,080 | +0.26 % | 256² | 0 | 8×3 |
| lasrifle | `output/gen/weapon8` | 460 | +7.5 % | 256² | 0 | 8×3 |
| deck tile | `output/gen/tile8` | 380 | +1.7 % | 256² | 0 | 8×3 |
| barrel | `output/gen/barrel8` | 460 | −0.27 % | 256² | 0 | 8×3 |

`glb_contract.py` PASS on all four; the unit keeps 22 joints, one skin and the
9-clip set (the pixel tier re-authors mesh budget, texel grid and material model,
not the rig).

Mask passes zero the scene view transform **and the exposure**: a −0.65 EV studio
grade is applied even under Raw, and it decayed every normal mask to a 0.64×
multiply (decoded lengths 0.58–0.75) until `pass_materials.py` reset it. That is
the third instance of the same class of bug; the module now owns the discipline for
every renderer.

`build_unit.sh` takes the faction as its 4th argument (default
`iron_directorate`): the bake maps bare slot names to `<faction>__<slot>`, so
shipping a non-Directorate unit without it silently bakes Directorate materials.
`decimate_unit.py` also cleans before decimating now (weld, delete loose/degenerate,
drop loose parts under 2 % of the body at full resolution). Image-to-3D shells
arrive with coincident faces and debris — the Cinderborn cultist came in with 8
components and its pixel master broke into 2–64 alpha components until that
cleanup ran.

**Material-source changes made to reach that bar** (recorded, not silent):
`iron_directorate__metal_trim` retuned to neutral gunmetal (chroma 26.6 → 14.0)
and `gunmetal_worn` value-stretched (luma std 6.46 → 59.3) by
`tools/pbr/retune_material.py` with the reason attached in
`configs/materials/retune.json`; two sheets were generated to fill real gaps
(`deck_plate_industrial`, `gunmetal_polished`); the pixel variants apply a
0.5 contrast retention so micro-wear does not read as noise after
box-projection onto a coarse mesh.

### 8a.1 Cover kit masters (2026-11-10) — the gameplay cover set

The combat map needs a shape per cover tier, not one crate. A new `cover` recipe in
`tools/blender/parametric_prop.py` builds six silhouettes from one request schema
(`shape` = crate_stack / sandbag_row / barricade / machine_block / shield_wall /
column) and the deck module was re-cut at the engine's 2.4 m cell:

| Asset | `<out>` | tris | density vs profile | atlas | off-palette | tier / height |
|---|---|---|---|---|---|---|
| crate stack | `output/gen/cover8_crate` | 228 | +0.12 % | 256² | 0 | partial 0.95 m |
| sandbag row | `output/gen/cover8_sandbag` | 364 | +0.62 % | 256² | 0 | partial 0.82 m |
| barricade | `output/gen/cover8_barricade` | 108 | +0.02 % | 256² | 0 | partial 1.08 m |
| machine block | `output/gen/cover8_machine` | 120 | −0.11 % | 256² | 0 | hardened 1.90 m |
| shield wall | `output/gen/cover8_shield` | 108 | +0.73 % | 256² | 0 | hardened 1.85 m |
| column | `output/gen/cover8_column` | 312 | +0.37 % | 256² | 0 | hardened 2.30 m |
| deck module 2.4 m | `output/gen/tile8_24` | 380 | +0.36 % | 256² | 0 | tile |

All seven pass `glb_contract.py` (prop/tile), `check_texel_grid.py` (0 % off-lattice,
0 off-palette), `check_palette_asset.py` and `check_master.py` (8 directions, distinct).

**Two tool defects the kit exposed, fixed here:**

1. **`palette_uv.py` left every UV off the texel lattice whenever island packing
   translated an island.** The snap ran *before* `pack_islands`, which then
   translated islands by arbitrary (fractional-texel) offsets — the column came out
   100 % off-lattice with a filtered atlas while its own report claimed
   `uv_lattice_snapped: true`. Fixed by re-latticeing after packing (per-island
   translation by the mean fractional offset, which preserves island shape) and
   recording `islands_relattices` in the stage report. Negative control: the
   unpatched column fails `check_texel_grid.py`, the patched one passes.
2. **`check_palette_asset.py` rejected correct boxy cover.** Its `prop` bbox-fill
   range (0.25–0.95) assumes a rounded prop; a crate or wall seen edge-on
   legitimately fills 0.96–1.00 of its bounding box. A separate `cover` kind
   (0.20–1.00) was added instead of loosening `prop` for every prop.

Surface area is the real budget on this tier: at 2 cm texels a 256² atlas holds
~26 m², and the texel stage refuses anything needing >75 % of the atlas. The
machine block and shield wall were dimensioned down to fit rather than raising the
atlas (recorded in their request params).

### 8b. Gate negative controls (evidence, not claims)

| Gate | Negative controls exercised |
|---|---|
| `check_master.py --selftest` | flat normals, antialiased alpha, identical views, wrong resolution, uniform AO → each rejected; correct set accepted |
| `check_texel_grid.py --selftest` | wrong density, off-lattice UVs, off-palette atlas, wrong atlas size → each rejected; correct GLB accepted |
| `palette_lock.py --selftest` | off-palette input flagged, single hand-edited pixel flagged after locking, soft alpha rejected; locked output is exact |
| `check_palette_asset.py --selftest` | off-palette render, two-component silhouette, stringy silhouette, empty canvas → each rejected; palette-locked single shape accepted |

Run them all before trusting a green run:

```bash
python3 tools/style/check_master.py --selftest
python3 tools/style/check_texel_grid.py --selftest
python3 tools/style/palette_lock.py --selftest
python3 tools/style/check_palette_asset.py --selftest
```

Known limits of this tier, recorded in `docs/KNOWN-ISSUES.md`: the automated
retopo silhouette is still soft, the unit's emissive mask is empty (no emissive
slot is authored on the unit), and atlas utilisation is 1.8–49 % because the
islands come from smart projection rather than an artist pack.

### 8c. Reference-art gap fill (2026-11-10)

The unit's declared references were dangling on disk: `output/img23d/line_infantry_mv/`
held no orthos and there was no faction style sheet. Three Gemini generations
closed the gap (consumer web app via `~/.pi/agent/bin/gemini-img`; the whole
session used 3 of the 5-hour budget):

| Output | Command shape | Use |
|---|---|---|
| `output/gen/sheets/deck_plate_industrial_0.png` | text → 2K square, seamless | ingested as `deck_plate_industrial` (1 m plate module) |
| `output/gen/sheets/gunmetal_polished_0.png` | text → 2K square, seamless | ingested as `gunmetal_polished` (barrel body, rifle trim) |
| `output/gen/sheets/line_infantry_turnaround_0.png` | `--edit` the pixel master → 16:9 four-view turnaround | cropped locally into `output/img23d/line_infantry_mv/{front,left,right,back}.png`, the paths the asset request declares |
| `assets/units/iron_directorate_line_infantry/concept.png` | text → 2K square style sheet | **review target only**, not a source |

Rules applied: flat uniform studio light for anything destined for 3D, pure white
background (never a request for transparency), 2K then local downscale, and no
edit chains. Two verified flaws showed up and are recorded rather than worked
around silently: the style sheet **replaced the injected hex labels with its own
palette** (`#800000`, `#151515`, … instead of the `grimdark_3d` values), and its
trooper is more ornate than the line-infantry model. It is therefore a density /
value-ramp reference, not a colour authority — the palette authority stays
`assets/palettes/grimdark_3d.gpl`.

---

## 8. Authored unit kit (2026-11-11)

The roster-scale unit route is authored, not image-to-3D. It is deterministic, needs no Gemini
quota or GPU generation, and carries role gear as real geometry.

```bash
# mesh + authored-weight rig + texel/atlas/palette/master/gates
BUILD_RIG=1 tools/build_authored_unit.sh unit_<id> <unit-id> <faction>
```

- `configs/units/<faction>.json` — unit configs (body preset, helm, shoulders, back, weapon,
  shield/robe/cloak, crest/horns).
- `tools/blender/parametric_unit.py` — modular part generator. Primary forms are chamfered/tapered
  prisms and wedges, not axis-aligned cubes; parts are named `<bone>__<slot>__<tag>` for authored
  binding.
- `tools/blender/unit_pose.py` — the shared arm poses. `ranged` puts the right hand on the pistol
  grip and the left hand on the foregrip; the weapon is built around those two points and weighted
  to `RightHand`. `melee` grows the blade from the right-hand socket.
- `tools/blender/rig_unit_proof.py --bind authored --hold <pose>` — binds the authored vertex
  groups (no distance weights) and builds the same 22-bone/9-clip rig.
- `tools/pbr/tint_faction_pixel.py` — rebuilds a faction kit's pixel albedo on its identity ramp
  when the generated sheet is ash-toned and the hue is lost at the pixel-variant size
  (`configs/materials/faction_pixel_ramps.json`).

Art rules applied: silhouette first, exaggerated role proportions, chamfered planes, no surface
greebles outside the 4,000–4,800 tri budget. The engine floor is filled with hidden interior
structure, never floating surface studs (those split the silhouette at side angles).
