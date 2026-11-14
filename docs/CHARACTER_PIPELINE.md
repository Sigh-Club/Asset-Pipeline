# Character pipeline standard

> Unit design method: `UNIT_KIT_METHODOLOGY.md` (derive-and-reshape kits, human-scale directive).
> This document is the rig, animation and certification standard that any kit must meet.

This is the authoritative standard for IoA unit assets: humans, near-human aliens, creatures and
monsters. It exists because the first base-mesh route (2026-11-13) passed every automated gate while
producing box hands, tube limbs and a statue-like rig. The gates measured pixels; they did not measure
anatomy. This document defines what "correct" means and how each stage is proven.

## Reference standard

Shipped games at comparable budgets, inspected from their own files:

| Asset | Tris | Bones | Hands | Weights | Animations | Textures |
|---|---|---|---|---|---|---|
| XCOM: EU generic soldier (`body_genericsoldier_sf.upk`) | 6,962 | 63 | 5×3 finger bones per hand, 5 mm inside the mesh | 7,921 weight records | full set | 512² DIF/NRM/SPC |
| DoW: DE Guardsman (`imperial_guard_guardsman.whm`) | ~2–5k | 32 | modelled hands, `finger0` bone | skinned | 41 clips | atlas |
| DoW: DE Space Marine | ~7k | 59 | modelled hands | 19 groups on the torso | 20+ clips | atlas |
| Boltgun | sprites only (80,145 animation assets in the pak) | — | — | — | — | 8-direction sprites with normal/AO/emission |

The standard is not polygon count. It is anatomical joint placement, modelled hands, real skin
weights, gear built to the skeleton, and real animation clips.

## Base and rig

- **Human base:** MakeHuman MPFB2 human (CC0), created in Blender. The standard rig is the MPFB
  standard rig: 137 bones including clavicles, two-segment upper arm and forearm, wrist, 5×3 finger
  bones per hand, two-segment legs, feet and toes.
- **Install (local, not committed):**
  `blender --command extension install-file -r user_default -e <mpfb-2.0.18.zip>`, then enable
  `bl_ext.user_default.mpfb`.
- **Prove the rig before anything else:** every finger bone must be inside its finger (nearest mesh
  vertex < 10 mm) and have weighted vertices; the hand chain must reach the grip targets with IK
  error < 5 mm. Measured on the MPFB proof: finger bones 5 mm from the nearest vertex, 20–87 weighted
  vertices per finger, both hands solved at 0.000 m.
- **Aliens:** morph the same human base (proportions, skull, limbs) and keep the same rig; use a
  dedicated creature base only where a humanoid skeleton cannot express the shape (titans, swarms).
- **Monsters:** a separate creature base with the same naming/retarget conventions; never force a
  titan onto the human rig.

## Topology and weights

- Keep the base topology. Decimate **after** rigging so weights and joint loops survive; never
  decimate before binding (this is what removed the elbow/knee/finger loops in the old route).
- Joint loops: circular edge loops through elbows and knees; fingers keep their own loops.
- Skin weights: the base's weights are the starting point; paint corrections at shoulders, elbows,
  hips, knees and hands. Add forearm twist bones when the arm twists (XCOM ships two per forearm).
- Budget: 8–15k tris for a unit; 60–140 bones; 512² DIF + NRM (+ AO). The 3070 Ti is not a
  constraint at this budget.

## Gear and weapons

- Model gear **in the rest pose on the body**, never at a posed position. Rigid pieces get one
  vertex group on their bone (DoW/XCOM pattern); cloth gets skin weights.
- Weapons attach to a hand socket (`wrist.R`) with the left hand solved by IK to the weapon's
  foregrip socket. Do not bake a single pose and copy it to every clip.
- The old route's pose-delta compensation is a workaround for gear authored at posed positions; it
  is removed once gear is authored in rest pose.

## Animation and export

- Real clips, retargeted from a compatible humanoid rig (Mixamo is free and adequate for humans).
  Minimum set: idle, walk, run, aim, fire, reload, hit, death, melee.
- Bake IK to bone keyframes only at export; keep the rig editable in the source scene.
- Export GLB with the skeleton, weights and clips; validate in-engine.

## Measured facts (Blender 5.1, 2026-11)

- The Decimate modifier **ignores its vertex group** in Blender 5.1: identical output at ratios
  0.20 and 0.42 with the same group, and the "protected" hands were still stripped. Do not rely on
  vertex-group protection; do not decimate at all for hero units.
- The "skirt" defect seen in GLB renders was a **misdiagnosis**. Geometrically the legs are separate
  (4 cm gap at the ankles, only 18 of 803 body vertices within 3 cm of x=0 at shin height). The
  apparent cone was flat dark shading on close-set legs, not fused geometry.
- Full-anatomy body cost: 19,158 verts / ~19.5k tris; joined with the gear kit ~26.5k tris. The
  final pixel GLB measures 19,943 tris after the atlas/final stage.
- The MPFB distal phalanx bone heads sit up to 8 cm from the nearest body vertex in the rest pose
  (the fingers are curled, the bones are straight). The rejected centroid-rig route measured
  20-26 cm, which is the failure class the gate has to catch.
- A GLB exported while IK constraints are live writes the **constrained pose** as the node
  transforms; every bone-to-mesh measurement is then meaningless. Bake the IK result into the
  action, clear the constraints, clear the pose and export with `export_rest_position_armature`.

## Rig classes: humanoid, alien, monster (measured references)

Bone budgets are taken from shipped games, not invented. Measured from the installed DoW
Definitive Edition archives (`DXP2Data-Whm-Definitive.sga`) with `tools/dow/whm_animdata.py`:

| Reference | Class | Bones |
|---|---|---|
| `kroot_hounds.whm` | quadruped beast | 30 |
| `krootox.whm` | large quadruped | 82 |
| `daemonprince.whm` | large monster | 33 |
| `kroot_warrior.whm` | humanoid alien | 43 |
| `kroot_shaper.whm` | humanoid alien | 49 |
| DoW DE `imperial_guard_guardsman.whm` | human | 32 |
| DoW DE space marine | human | 59 |
| XCOM EU `body_genericsoldier_sf.upk` | human | 63 |
| MPFB2 standard rig | human | 137 (incl. facial) |

DoW2 Retribution is already decompiled and extracted at
`Projects/Decompilor/work/dow2-retribution` (SGA v5 via `relic.sga`, Chunky v3 via
`chunky_dump.py`, art pulled with `extract_sga.py --all --match`). Measured Tyranid composition
(parts / materials / mesh payload): carnifex 14 / 23 / 1.8 MB, hive_tyrant 12 / 22 / 2.1 MB,
lictor 4 / 16 / 2.2 MB, ravener 4 / 16 / 1.1 MB, warrior_brood 4 / 12 / 0.9 MB,
termagaunt 5 / 10 / 0.9 MB, hormagaunt 4 / 4 / 0.6 MB. Two facts follow for our pipeline:
DoW2 units are **part assemblies with one material per draw call**, and their skeletons are
separate Havok/`FOLDSKEL` assets, not embedded in the mesh models. Our shipped units (single
mesh, 8 materials, ~3.5 MB incl. textures and clips) sit inside that envelope; the gaps are LODs
(DoW2 ships a state/LOD tree) and material splitting.

### How a non-human rig is built

1. `configs/rigs/<class>.json` — declarative template: bone names, hierarchy, rest head/tail,
   deform flag, skin radius, IK chains, and the measured reference it targets.
   Shipped: `quadruped.json` (31 bones), `monster.json` (28 bones).
2. `tools/blender/creature_base.py` — builds an organic base mesh from the template with the Skin
   modifier (per-bone radii), subdivision and smoothing, then decimates to budget. No primitive kit.
3. `tools/blender/rig_template.py` — builds the armature from the same template, fits it to the
   mesh height, binds with heat weights and falls back to envelope weights using the template radii
   when heat weighting fails (measured: skin-modifier shells are non-manifold and heat weighting
   returns empty groups).
4. `tools/audit_rig.py` — certifies the result. Humanoid-only checks (finger distance, limb ratios,
   hands on weapon) are conditional; creature rigs get deform-bone coverage and bone-to-mesh
   distance instead.

Measured proof: `output/units/beast` (quadruped, 31 bones, 12k-poly base) and
`output/units/brute` (monster, 28 bones) both PASS the anatomy gate with zero orphan deform bones.

**Decision:** humanoids keep the MPFB2 standard rig (137 bones, fingers, morphs). Creatures and
monsters use rig templates plus a generated or authored base mesh. **Rejected:** hand-written rig
code per creature; **rejected:** Rigify metarig fitting (the centroid fit was the original defect).
**Revisit when:** a creature needs facial rigging or more than ~90 bones (krootox-class).

## Using shipped-game meshes as bases (DoW2)

DoW2 art is already extracted at `Projects/Decompilor/work/dow2-retribution/sga`; art is pulled with
`extract_sga.py --all --match '<race regex>'` (the default run skips art, which is why the models
appeared to be missing). Geometry decodes: DoW2 stores it in `DATADATA v7` chunks with an attribute
table, vertex count, stride, vertex stream and a submesh/index table.

Tooling in this repo:
- `tools/dow2/chunky_mesh.py` — decodes one or more `.model` parts to OBJ (positions + submeshes).
  Measured: `space_marine_base` 16,838 verts / 9,720 tris, carnifex armour 11,034 tris,
  hive tyrant 8,549, hormagaunt 3,800, warrior brood 4,206, genestealer 4,546.
- `tools/blender/dow2_base.py` — imports the OBJ, welds, fixes the up-axis (DoW2 vertex data is
  Y-up), scales to the unit height, grounds it and decimates to budget.
- `tools/blender/rig_template.py` — fits one of our rig templates to that base (per-axis bbox fit),
  binds with distance-based weights and exports a bind-pose GLB.
- `configs/rigs/humanoid.json` (27 bones), `quadruped.json` (31), `monster.json` (28) — all inside
  the measured shipped-game bands.

Verified end to end: `space_marine_base` -> humanoid template -> `output/units/space_marine`
(PASS), `carnifex` (4 parts merged) -> quadruped template -> `output/units/carnifex` (PASS).

Known limits, measured: the bbox fit is crude for T-posed meshes (bones 20-68 cm from the surface on
the marine), and a part assembly can legitimately leave head/weapon bones unweighted (the gate
reports those as warnings for creature-class rigs, hard failures for humanoids). Per-creature fit
overrides are the next refinement; the MPFB human remains the human base where a production
skeleton is wanted.

## Animation clips (all frames)

`tools/blender/animate_frames.py` authors the required clip set on any frame:
`aim, idle, walk, run, fire, reload, hit, death, melee` at 24 fps. The clips are generated from
shared helpers (arms-down base, gait, recoil, collapse), so a gait change improves every frame.
Measured travel on `ig_human` to prove the clips are real, not static keys: walk foot 0.42 m,
run foot 0.65 m, melee hand 0.59 m, death head drop 0.87 m.

The frames ship with those nine clips and pass `tools/audit_rig.py`.

## Visual-truth gate (added after a shipped jumble)

Contract, silhouette and palette gates passed a completely broken mesh: a jumble of triangles still
renders as one silhouette blob, still has valid UVs and still sits in the tri budget. Two failures
slipped through that way:

1. **Wrong source model.** `ig_base` and `space_marine_base` are the Imperial Guard and Space Marine
   *base buildings*, not troopers. The frames were rigged scenery.
2. **Broken index decode.** `chunky_mesh.py` offset every face by the model base but not by the
   payload's own vertex block, so models with more than one geometry payload referenced the wrong
   vertices and produced 1.9 m edges.

`tools/audit_rig.py` now measures geometry directly: an edge longer than 35% of the model span fails
the asset. Measured after the fix: ig_human 0.21, super_human 0.17, eldar 0.19, carnifex 0.13.

Body sources (verified by bbox proportions, not by filename): human `commissar_armour`,
super-human `power_armour_ultramarines_commander`, eldar `farseer_armour_common`, monster carnifex
(4 parts merged). Do not use `*_base.model` — those are scenery.

## Base frames shipped (human, super-human, eldar, monster)

`tools/build_base_frames.sh` rebuilds all four from the extracted DoW2 art and audits each one.
Each frame carries attachment sockets (`socket_weapon_L/R`, `socket_shoulder_L/R`, `socket_backpack`,
`socket_head`, `socket_hip_L/R`) exported as nodes, so gear is parented in the game rather than
welded into the mesh.

| Frame | Class | Source mesh | Tris | Joints | Sockets | Audit |
|---|---|---|---|---|---|---|
| `ig_human` | human | DoW2 `ig_base` | 7,825 | 35 (26 deform) | 8 | PASS |
| `super_human` | super-human (Space Marine / Chaos Marine) | DoW2 `space_marine_base` | 8,497 | 35 (26 deform) | 8 | PASS |
| `eldar` | slim athletic | DoW2 `farseer_armour_common` | 4,706 | 35 (26 deform) | 8 | PASS |
| `carnifex` | monster | DoW2 carnifex (4 parts merged) | 10,671 | 35 (30 deform) | 4 | PASS |

Chaos Marines share the `super_human` frame: the shipped game reuses the marine armour and varies
material, palette and spike/horn gear, which is also how our palette tier works.

Frame construction, measured and automated:
- `tools/dow2/chunky_mesh.py` decodes the shipped geometry; `tools/blender/dow2_base.py` welds,
  fixes the Y-up axis, scales to the class height, grounds and decimates.
- `tools/blender/rig_template.py` fits the frame: uniform height fit, then **limb fitting** to the
  mesh's own extremities (the bases are A/T-posed, so a bbox fit stretches depth up to 6x).
- Binding is distance-based with a distance-resolved coverage fallback; Blender's heat and envelope
  binds both return empty groups on these meshes.
- `tools/audit_rig.py` certifies each frame (deform coverage, limb ratios for humanoids, bone-to-mesh
  distance, sockets allowed to be unweighted).
- Texel density tolerance: the hi class allows ±65% (was ±25%). Shipped part assemblies have
  overlapping shells and pack at ~32% atlas utilisation, so the 2 cm grid cannot be held exactly
  (measured +31% to +56%). The standard class keeps ±25%.

Not yet done: the frames ship in bind pose with no clips. The required clip set (idle/walk/run/fire/
reload/hit/death/melee) still has to be retargeted onto these skeletons; the humanoid frames are
27 bones and the monster 31, which is inside the measured DoW/XCOM bands and compatible with the
usual retarget sources.

## Certification gates (all required)

0. Visual: `blender -b -P tools/visual_check.py -- --glb <glb> [--source <base>] --out <dir>` must
   PASS and the contact sheet must be reviewed by a human. Numeric gates cannot see a jumble: it
   still has valid UVs, a plausible tri count and one silhouette blob.
0b. Automated: `python3 tools/audit_rig.py <glb>` must PASS (bone-to-skin <= 9 cm, human limb
   ratios, no unweighted vertices, no orphan body bones, hands near the weapon) and
   `python3 tools/glb_contract.py <glb> --kind unit` must PASS (<= 35,000 tris LOD0).

1. Rig anatomy: every finger bone inside the mesh and weighted; hand IK error < 5 mm; elbow/knee
   bend test passes without collapse.
2. Proportions: upper-arm/forearm/hand ratios within human range (forearm ≈ 0.8–0.9 × upper arm).
3. Topology: no decimation before binding; joint loops present.
4. Gear: authored in rest pose; rigid groups correct; weapon socket alignment.
5. Animation: the required clip set present and distinct.
6. Visual: 8-direction master, one connected silhouette, palette compliance.
7. In-engine: the unit loads and animates in the combat renderer.

## Decisions

- **Choice:** MPFB2 human + standard rig as the humanoid base. **Rejected:** centroid-fitted Rigify
  metarig on the CC0 sculpt; decimate-before-rig; box fists. **Because:** the MPFB base ships
  anatomical joints, fingers, weights and morphs for humans/aliens, is free/CC0 and runs in Blender
  5.1. **Revisit when:** MPFB breaks on a Blender upgrade, or a creature base is required.
- **Choice:** ship the anatomical body **undecimated** and raise the hi LOD0 budget to 35,000 tris.
  **Rejected:** decimating the body to fit a 16k/25k budget. **Because:** decimation is what stripped
  the hands (6-8 cm bone-to-mesh) and welded the legs; the anatomical body is only 19.5k tris and a
  26.5k rigged unit is normal for a modern hero character. **Check:** `tools/glb_contract.py` and
  `scripts/guard_pixel.py` hi class both pass; audit_rig passes. **Revisit when:** the combat scene
  exceeds the frame budget with 10+ units on screen.
- **Choice:** gear in rest pose, rigid one-bone binding for hard pieces. **Rejected:** posed-position
  gear with inverse-delta compensation. **Because:** compensation only holds for the baked pose and
  displaced the primitives when the rig changed.

## Current status (2026-11-17)

**Shipped and certified:** 61 pixel assets pass `guard:glb` and `guard:pixel`; Jest 624/624;
pixel-tier and full-loop-demo E2E 3/3. Of those, 26 units are built on the frames below; the rest are
the earlier authored primitive kit and the props.

| Asset | Body class | Source | Tris | Joints | Clips |
|---|---|---|---|---|---|
| `iron_directorate_ig_human_pixel.glb` | human | DoW2 `commissar_armour` | 4,114 | 35 | 9 |
| `iron_directorate_super_human_pixel.glb` | elite | DoW2 `power_armour_ultramarines_commander` | 5,479 | 35 | 9 |
| `void_corsairs_eldar_pixel.glb` | corsair | DoW2 `farseer_armour_common` | 7,463 | 35 | 9 |
| `parasitic_bloom_carnifex_pixel.glb` | bloom | DoW2 carnifex (4 parts) | 9,423 | 35 | 9 |
| `cinderborn_chaos_heretic_pixel.glb` | human | DoW2 `heretic_wordbearers` | 4,471 | 35 | 9 |
| `cinderborn_chaos_marine_pixel.glb` | elite | DoW2 `wordbearers_marine` | 4,264 | 35 | 9 |

Every one of these is a **derived whole mesh**: the anatomy and animation are sound, but the
silhouette is still the source's. They are placeholders until the kit method in
`UNIT_KIT_METHODOLOGY.md` replaces them with assembled parts.

## Lessons learned (each cost a shipped defect)

1. **Verify the source is the body, not scenery.** `ig_base.model` and `space_marine_base.model` are
   the Imperial Guard and Space Marine *base buildings*. Two frames were rigged architecture before
   anyone looked at a render. Check by bbox proportions (tall/narrow), never by filename.
2. **A jumble passes every pixel gate.** Contract, silhouette and palette checks measure tris, UVs
   and colour; a mesh exploded into 1.9 m triangles is still one blob with valid UVs. Geometry is
   now measured directly: `audit_rig.py` fails any edge longer than 35% of the model span.
3. **Multi-payload models need per-payload vertex offsets.** `chunky_mesh.py` offset faces by the
   model base only, so every payload after the first referenced the wrong vertices.
4. **Do not trust Blender's automatic binding on shipped meshes.** Heat weighting and envelope
   binding both return empty groups; distance-plus-radius weighting works, and a distance-resolved
   coverage fallback prevents dead joints.
5. **Small bones out-compete large ones under distance-only weighting.** The jaw captured 66% of the
   commissar mesh (hat and shoulders) until weighting was scaled by the template's bone radius.
6. **Decimation protection is inert in Blender 5.1.** The Decimate modifier ignores its vertex group,
   and separating hands before decimating also fights the ratio. Plain uniform decimation behaves.
7. **Export with live IK writes the constrained pose as the rest pose.** Bake the result, clear the
   constraints, clear the pose, then export with `export_rest_position_armature`.
8. **The OBJ importer creates one object per material group.** Deleting the extras silently dropped
   up to 44% of a mesh. Join them.
9. **Texel density and readability need real thresholds.** Shipped part assemblies pack at ~32% atlas
   utilisation (hi tolerance 65%); a character legitimately renders as body + gear, so readability
   requires a dominant body (largest piece ≥90%), not one blob.
10. **The catalogue and the cache are part of shipping.** A replaced model that the catalogue does
    not reference is invisible; without a cache revision the browser keeps the old master.
11. **The backend is a compiled binary.** Go changes do not reach the test server until
    `backend_server` is rebuilt and restarted.
12. **Facing must be populated.** `ComponentBasedUnit.facing` was never set, so every unit defaulted
    to yaw 0 and both sides faced the same way.
13. **Spacing is a squad property.** Spacing each hostile from its paired player left the second
    hostile adjacent to another squad member; the stand-off is measured against the whole squad.
15. **A gate can be wrong too.** The geometry check indexed all primitives' vertices with
    primitive-local indices, producing a false 1.48 m edge, and a duplicate copy of the check
    overwrote the corrected result. A gate that fails a known-good asset is a gate bug, not an asset
    bug — investigate before changing the asset.
16. **Joining a derived part duplicates the material datablock** (`armour_primary.001`) and the bake
    cannot map it. Reuse the body's existing slot.
14. **Whole-mesh import is copy-paste.** The models animate and certify, but the part vocabulary,
    tier ladder and silhouette belong to the source. That is what `UNIT_KIT_METHODOLOGY.md` fixes.

## Test-mode parity (MANDATORY — no exceptions)

**Every change to game assets, models, animations, materials or runtime code must be passed to
test mode in the same change.** A change that exists only in source is not done.

Definition of test mode for this project:

1. `frontend/public/assets/...` — the source of truth for assets.
2. `frontend/dist` — rebuilt with `cd frontend && npm run build`. This is what the nginx test
   server (`http://localhost:8080`, root `frontend/dist`) and the offline demo serve.
3. `UNIT_ASSET_REV` in `frontend/src/three/unitModels.ts` — bumped whenever a model file is
   replaced, otherwise the browser keeps serving the previous master from cache and the test
   version looks unchanged.
4. The catalogue (`unitModels.ts`) must point at the shipped file names. A model on disk that the
   catalogue does not reference is invisible in game and in test mode.

Required verification before a change is called complete:

```
npm run guard:glb && npm run guard:pixel && npm run guard:assets
cd frontend && npm test --silent
npx playwright test -c playwright.combat.config.ts --grep "pixel-tier|full-loop-demo"
curl -sI http://localhost:8080/assets/models/units/<file>.glb   # served bytes match disk
```

If the served bytes differ from the file on disk, the change has not reached test mode. If the
catalogue still points at an older file, the change has not reached test mode. Both are failures,
not warnings.
