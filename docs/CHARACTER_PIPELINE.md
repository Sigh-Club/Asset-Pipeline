# Character pipeline standard

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

## Certification gates (all required)

0. Automated: `python3 tools/audit_rig.py <glb>` must PASS (bone-to-skin <= 9 cm, human limb
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

## Migration status

- Done: MPFB2 installed and proven in Blender 5.1; `tools/blender/mpfb_unit_build.py` creates the
  human, adds the 137-bone rig, derives landmarks from the skeleton, decimates after rigging, solves
  the two-handed pose (0.000 m error) and curls the real finger bones.
- Done: male morph, rest-pose bind export, anatomy gate (`tools/audit_rig.py`), contract budget for
  full-anatomy units, mirrored feet and degenerate lames fixed, one unit certified end-to-end
  (`output/gen/unit_mpfb`, 19,943 tris, 137 joints, 9 clips, 0 off-palette).
- Next: batch the 20 humanoid units, add normal/AO to the pixel material, retarget real clips, then
  rebuild the gear kit tighter to the MPFB proportions (upper arms and face are still exposed).
