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

## 5. Tripwire

Re-check the bands if: the engine's asset contract changes, Nanite-style virtualised geometry becomes
the shipping target (which makes LOD0 budgets moot), or the project deliberately re-scopes to a
stylised tier. The cited band numbers are practitioner consensus, not a specification; they are
stable to roughly ±20 % and are not worth defending beyond that.
