# Style bands — published game-asset standards, and where our profiles sit

**Purpose.** Stop arguing about whether our assets look right and measure them against the
published bands instead. Every number below is either a cited external standard or a value read out
of `configs/styles/profiles.json`. The target band for this project is **AAA PC** — not the PSX/pixel
tier, which is a deliberate retro style and is *not* a defect.

Collected 2026-11-23. Sources are graded A (measured here) / B (primary document) / C (practitioner
reference with concrete numbers).

---

## 1. The bands

| band | LOD0 tris (character) | texture | texel density | normal/AO maps | shading | source |
|---|---|---|---|---|---|---|
| PS1/PSX retro | **≤ 1,000** | 64–512 px, nearest, lighting baked into texture | low | no | flat/affine | C — [3dAIStudio PS1 guide](https://www.3daistudio.com/blog/ps1-graphics-how-to-make-ps1-style-3d-models) |
| mobile / low-end | 2K–10K | 512–1K | ~256 px/m | optional | pbr-lite | C — [Tripo poly-count guide](https://www.tripo3d.ai/blog/poly-count-for-game-assets-how-to-prepare-ai-3d-models) (band table) |
| modern PC game-ready | 20K–50K | 1K–2K | 512–1024 px/m | yes, baked from high-poly | PBR | C — Tripo (20K-50K band), nastyrodent |
| **AAA PC hero (our target)** | **80K–120K** | 2K–4K | 1024–2048 px/m | **yes, required** | PBR | C — [nastyrodent LOD/polygon budget guide](https://nastyrodent.com/polygon-budget-guide/) ("High (reference: 80K–120K LOD0 on PC/console)") |
| source/sculpt input to bake from | 300K–2M | n/a | n/a | n/a (it is the source) | — | C — Tripo: "when you still build high poly (and bake it down)" |

Texel density anchors, C — [Beyond Extent, Texel Density](https://www.beyondextent.com/deep-dives/deepdive-texeldensity)
(last updated 2026-04-03): density is measured in px/cm or px/m; **256 px/m** is the unit's own worked
example; ~**20.48 px/cm ≈ 2048 px/m** is "more than enough" for high-end work; the doc's stated
failure mode is mismatched density *between* assets in one world.

## 2. Where our profiles sit (measured from `configs/styles/profiles.json`)

| profile | tris_max | shading | material | normal_map | falls in band |
|---|---|---|---|---|---|
| `lowpoly_3d` | 3,000 | cel | palette | false | mobile / stylised |
| `palette_3d` | 4,000 | flat | palette | **false** | mobile — **the "ancient console" look** |
| `palette_3d_hi` | 16,000 | flat | palette | **false** | mobile geometry, PSX shading |
| `stylised_3d` | 14,000 | pbr | pbr | true | mobile / low PC |
| `pbr_3d` | 25,000 | pbr | pbr | true | low end of modern PC |
| **`aaa_pc`** | **— does not exist —** | | | | **the target band is unrepresented** |

## 3. The measured contradiction

The generator already produces AAA-density geometry. Measured on this machine (2026-11-23):

| asset | triangles |
|---|---|
| `output/img23d/line_infantry_mv/front.glb` (raw Hunyuan3D shape) | **404,594** |
| `output/gen/unit8/line_infantry_pixel.glb` (shipping palette tier) | **4,160** |

That is a **97× reduction**, and the render comparison (`/tmp/ab/compare.png`, reproduced in the
session log) shows what it costs: the raw mesh is a smooth, plated, sculpted figure; the palette tier
is faceted and flat. The blockiness is introduced **by our output profile**, not by the generator.

Two further measured blockers:

- `tools/glb_contract.py` → `LIMITS["unit"]["max_tris"] = 25000`. The acceptance gate itself caps us
  below the AAA band; a 100K-tri unit fails the contract today.
- `tools/blender/bake_normal_maps.py` and `bake_ao_maps.py` exist but are **not wired into
  `tools/build_unit.sh`**, and `palette_3d` declares `"normal_map": false`. Normal/AO baking is the
  documented technique that lets a low-poly read as detailed ("build high poly and bake it down" —
  Tripo, above). We own the tools and do not run them.

## 4. What the target band requires, concretely

For an AAA PC unit the pipeline must produce:

1. **Geometry** 80K–120K tris at LOD0, quad-dominant, with a real LOD chain (120K → 60K → 25K → 10K).
2. **Topology built for the budget**, not decimated into it. Crushing a 400K organic sculpt to 4K
   destroys the curvature that made it read well; the 2000s solved this by modelling *for* the budget.
3. **Normal + AO baked from the high-poly** onto the game mesh — the industry technique, and the only
   way surface detail survives at game poly counts.
4. **PBR material set** (albedo/normal/roughness/metallic), 2K–4K, texel density 1024–2048 px/m,
   consistent across the roster.
5. **An acceptance gate that permits it** — `max_tris` raised for a declared `aaa_pc` kind, or LOD0
   allowed above the current 25K unit cap with the LOD chain enforced instead.

## 4b. Achieved, measured (2026-11-23) — `tools/blender/aaa_rebuild.py`

One command now produces the band, from the existing generative source, and refuses to
report success unless every gate passes:

```bash
tools/build_unit_aaa.sh line_infantry \
  output/img23d/line_infantry_mv/front.glb \
  output/img23d/line_infantry_mv/atlas/unit_textured.glb \
  iron_directorate
```

The underlying stage, if you need it directly:

```bash
tools/blender_run.sh --job bake -- -b -P tools/blender/aaa_rebuild.py -- \
    --high <source>.glb --slot-source <rigged reference>.glb \
    --out output/aaa/<id> --id <id> --tris 120000 --res 4096 \
    --min-texel-density 1024 --library assets/materials/grimdark_scifi/grimdark_scifi.blend \
    --faction <faction>
```

Gated end to end by `tools/build_unit_aaa.sh` (rebuild → contract → band report → profile check):

| measured | value | band requirement |
|---|---|---|
| LOD0 triangles | **120,000** | 80,000–120,000 ✓ |
| texel density | **1,366 px/m** at 4096 | 1024–2048 px/m ✓ |
| normal + AO | baked from the 404,594-tri source, 5.4 s / 9.3 s | required ✓ |
| material slots | 4, transferred by nearest surface | per-slot art ✓ |
| skin | weights transferred, 22 joints, 9 clips | rigged ✓ |
| contract | `glb_contract.py --kind aaa_pc` **PASS** | ✓ |
| file size | 15.4 MB | — |

Texel density is computed, not assumed: `px/m = sqrt(UV area) × res / sqrt(world area)`. The same
asset at **2048 measures 537 px/m and the tool refuses to export** — which is why the competitor tier
ships 4096-px textures (TRELLIS.2's own example export uses `decimation_target = 1000000` with 4096
textures). 2048 is not a choice on a 3.9 m² body; it is a failed floor.

## 4b2. Where we stand against the competition — measured 2026-11-23

| dimension | ours | competitor tier | verdict |
|---|---|---|---|
| LOD0 geometry | 120,000 tris, smooth, rigged, 9 clips | 80–120K, rigged | **level** — and it *is* the same generator family |
| silhouette readability | reads as an armoured human with a rifle at 1000 px | same | **level** |
| baked surface detail | 4K normal + AO from a 404,594-tri sculpt | 2K–4K baked | **level** |
| texel density | 1,685 px/m at 4096 | 1024–2048 | **level** |
| **albedo authoring** | the **pixel-tier 2048 atlas** — authored for the retro tier, stretched over a 120K mesh | full PBR set (albedo + normal + roughness + metallic) generated from the reference | **short** |
| material response | library roughness/metallic only where a slot maps | per-region PBR | **short** |

The remaining gap is **material authoring, not geometry**. The proof is the unlit render: the unit's identity
(navy torso, camo trousers, gold trim) survives, but it is painted in a retro-tier atlas, so it reads
soft and painterly where a competitor reads crisp. Geometry is no longer the bottleneck; the albedo set is.

Route to close it, in order of evidence: generate a 4K albedo matched to the concept (`gemini-img`, the
existing PBR manifest pipeline), or use the library's triplanar PBR set per slot with a per-region mask;
then author roughness/metallic per slot rather than one global value.

## 4c. Dead ends — do not chase (each measured, 2026-11-23)

| approach | why it failed |
|---|---|
| Bake a 2048 PBR normal into the palette tier's `texel_grid` UVs | thousands of tiny islands sized for a 256-px palette; produced mottled, patchy shading across the whole body. Proven by disconnecting the normal link: the same asset renders clean. **A texel-grid layout cannot carry a PBR normal map.** |
| 2 cm bake cage on a 1.9 m figure | rays reach the wrong surfaces; 2 mm is the working value |
| `smart_project` alone for a 100K mesh | does not produce a 0–1 packing at that face count (measured UV area 53.2 on a 0–1 layout); an explicit `pack_islands` with a 16 px margin is required |
| 2048 textures at PC tier | 537 px/m against a 1024 floor — refused by the tool |
| voxel remesh → decimate on a 404K source | minutes of CPU for a worse result; decimate-first is what Blender's manual and the practitioner guidance both recommend for a sound mesh |
| transferring albedo across `unit_textured.glb` → decimated `front.glb` | they are **different meshes**; a BVH nearest-surface lookup "hits" at any distance, so 100,000/100,000 hits proved nothing. The EMIT bake covered 0.06 % of the map (peak 0.89, mean 0.0006) | keep the textured mesh as the base and subdivide it — its UVs, atlas and rig stay valid |
| measuring UV area with a per-face Python loop | minutes on 100K faces, and the bmesh shoelace was 100× wrong; `foreach_get` + numpy is exact and instant |

## 5. Tripwire

Re-check the bands if: the engine's asset contract changes, Nanite-style virtualised geometry becomes
the shipping target (which makes LOD0 budgets moot), or the project deliberately re-scopes to a
stylised tier. The cited band numbers are practitioner consensus, not a specification; they are
stable to roughly ±20 % and are not worth defending beyond that.
