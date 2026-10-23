# Rendering Standards — the research record for the IoA sprite bake (2026-10-23)

> **Purpose**: the researched state of the art for 3D→2D isometric sprite production,
> the golden-standard rules, and an audit of OUR pipeline (`tools/blender/render_8dir_v2.py`,
> the batch queue, and the defringe/pack post chain) against each. Every rule cites its
> source class (manual / postmortem / studio guide / community consensus). The delta list
> at the end is what changes before the combat-animation bake fires.
>
> Sources consulted 2026-10-23: Blender manual (colour management, denoising, Freestyle),
> FrameSprite orthographic contract guide, 3dtexel hand-painted look, salivity colour
> management + OIDN pieces, Rivals Workshop anticipation/action/recovery, pixel-art frame
> count surveys, AUTeddy 8-Directions plugin, polycount/CGDirector alpha threads.

---

## 1. Camera & framing contract

1. **Orthographic, always.** Perspective cameras break sprite scale consistency across
   frames and directions. One camera, one orthographic scale, fixed for the entire
   production — verified against the weapon's full extent *before* the first frame.
2. **The 45° ring**: eight views at 0/45/…/315; 360 duplicates 0. The direction→game-map
   naming must be explicit and verified with a marker pass (model-forward is not
   screen-down by accident).
3. **One pivot.** Foot/attachment reference stable across every angle and frame; per-view
   auto-zoom is forbidden (breaks the sheet).
4. **Canvas contract**: fixed output canvas; our pipeline's 64×64 canvas with the 64×32
   footprint in the bottom half and headroom above is correct and matches the field
   convention (headroom for raised props, footprint anchoring the cell).
5. **Per-action directories + frame-number patterns**; never overwrite across
   action/camera combinations.

**Audit**: our renderer fixes camera + canvas;✅ no per-view zoom observed;✅ the
frame-numbering per action exists.⚠️ The explicit zero-direction marker pass is not
recorded in the repo — add a one-off verification render to the bake checklist.

## 2. Colour management (the silent quality killer)

1. Blender ≥4.0 defaults **AgX**; Filmic before that. AgX handles saturated colours
   differently (highlights desaturate toward white) — **for palette-locked sprite work
   the safer transform is `Standard`** or a locked custom look: the house GPL palette and
   the front's hex kits are display-referred values; any tone-mapping curve shifts hues
   and breaks palette discipline (§8.5 closed-palette rule).
2. Whatever is chosen: **lock it in the .blend and never change between units** — a
   mixed-transform atlas is unfixable in post.
3. Exposure/gamma grading belongs in the compositor as a recorded node group, not
   ad-hoc per-render tweaks.

**Audit**: our configs do not record a view transform.⚠️ **Delta: pin `Standard` (or a
locked custom LUT) explicitly in the render template + verify the existing idle/walk
frames' transform matches before baking new states, or the old and new frames won't match.**

## 3. Stylized material language (the look)

From the hand-painted discipline (3dtexel; Sea of Thieves/Fortnite/WoW lineage):

1. **Shape hierarchy**: one big read, few medium cuts, sparse accents. Realistic noise is
   the enemy — detail that doesn't help the silhouette is painted out.
2. **Hue-shifted ramps, not saturation**: shadows lean purple/blue, highlights warm. This
   is what makes stylised albedo alive at sprite scale.
3. **Painted light is allowed but consistent**: one implied light direction for the whole
   kit, never mixed.
4. **Normals carry the chunky forms; roughness stays broad** (two-zone, not noise).
5. Slight emission-from-albedo lifts shadows the way painted miniatures read.

**Audit**: our materials are library-based (`grimdark_materials.blend`) — the palette rule
is enforced, but there is no recorded hue-shift ramp policy.⚠️ **Delta: add the
hue-shifted shadow/highlight ramp as a shared node group; audit the 3 material libraries
against the shape-hierarchy rule before the bake.**

## 4. Lighting for 8-direction sheets — the classic trap

1. **Rotate the model, never the light rig** (or equivalently: parent the rig to the
   camera). Camera-space lighting gives every direction an identical read — the sprite
   sheet looks like one character photographed eight ways. World-anchored suns produce
   directions that read inconsistently (a rim from the east disappears facing west).
2. The known community standard for sprites: **single dominant key from the front-high**,
   fill low, **strong rim for silhouette separation** (the camera reads silhouette before
   detail at 64 px), plus a dedicated ground-contact shadow catcher.
3. Our renderer already bakes AO — keep AO subtle; painted-AI look wants the shadow
   implied in the diffuse, not a heavy baked pass.

**Audit**: need to verify in `render_8dir_v2.py` whether the rig rotates with the
subject.⚠️ **Delta: assert rig-parenting in code + a 8-up contact sheet review per unit
before batch (silhouette consistency gate).**

## 5. Animation: the combat-beat contract (the H1 bake's soul)

From the fighting-game/animation literature (Rivals Workshop; the 12 principles; sprite
frame-count surveys):

1. **Every combat animation is Anticipation → Action → Recovery**, with
   **distinct, exaggerated silhouettes** per phase. The anticipation pose must differ
   clearly from idle and show the *direction* of the incoming hit.
2. **Power = fewer transition frames, harder poses.** Long smooth blends read weak. Our
   budget: attack 5f ≈ 2 anticipation / 1 strike (smear) / 2 recovery.
3. **The recovery→idle transition must be fast and unambiguous** — the last recovery
   frame must not resemble idle, or the read of "when can I act" breaks.
4. **Hit reactions**: 2–3f, offset from the pose, head-recoil secondary motion; death:
   5–7f with follow-through and a long final rest (our `die 7f` is correct; `hurt 3f` ✓).
5. **Timing on twos where possible** at our 64 px scale — but combat strikes land on
   singles for snap.
6. **Frame counts are a floor, not a law**: the field survey (Hollow Knight ~6f attack,
   Celeste 8f dash…) says readability beats count; our 5f attack matches the fighting
   convention (2-1-2).

**Audit**: the parametric generator's `attack_speed 1.5` etc. are global multipliers —
there is no per-pose silhouette review step.⚠️ **Delta: the bake QC gate must include a
per-unit 3-pose contact sheet (anticipation/strike/recover) signed before batch; silence
in the strip = re-pose, not ship.**

## 6. Render tech

1. **Engine**: stylised matte surfaces render cleaner in **EEVEE** (or EEVEE Next) with
   high sample counts + AO/bloom off-by-default; CYCLES only where GI truth matters. For
   64 px-downscaled sprites either passes; EEVEE is 5–10× faster across 49 units.
2. **Denoise**: OIDN — but in the **compositor** (enable denoising data pass), so noise
   rejection is tunable per unit without re-rendering.
3. **Passes**: beauty + AO + object/index (for defringing and team masks — our
   `teammask` pass ✓) + cryptomatter if per-part recolouring is planned.
4. **Alpha**: straight vs premultiplied — export PNG **straight alpha with colour bled to
   the edge** (fill edges with the adjacent colour before keying) to avoid dark fringing;
   the defringe pass exists in our chain ✅ — keep it *after* resize, not before.
5. **Supersampling**: render 2–3×, downscale LANCZOS (house rule ✓ — 3× 1152→384
   convention matches the field's 2–3× guidance).
6. **Outlines**: prefer post (backface-hull or inverted-hull pass, or defringe-based
   darkened rim) over Freestyle for sprite-scale control; Freestyle lines are
   view-layer-global and thicken inconsistently at our scale. A 1px darkened-silhouette
   pass, opacity ~60%, sells the painted look and separates units from the floor.

**Audit**: our chain has defringe ✅, depth/normal passes optional ✅.⚠️ Deltas: pin the
engine choice per unit class (EEVEE default), move OIDN to compositor, add the outline
pass, and record the alpha convention in the packer.

## 7. Palette discipline & atlas hygiene

1. Quantize final sprites to the house palette **after** downscale (the 64 px LANCZOS
   output is where colour is locked) — never before (resampling needs the headroom).
2. UV/padding: 2 px minimum island padding at final res to survive mip generation; our
   atlas packer must enforce it (verify).
3. Texel consistency: one texel-density target across all 49 units so a heavy and a scout
   read at the same fidelity on the board — audit per-unit sprite heights
   (the proportions schema drives this; verify in the QC sheet).

## 8. Pipeline hygiene (house + field)

1. Versioned output trees ✅ (v0.5.x convention).
2. Kill stale Blender processes before launches ✅ (render_queue).
3. Per-unit manifests recording: engine, samples, view transform, seed, denoise settings,
   pass list — **the reproducibility contract**.⚠️ Not present; add to `render_8dir_v2`
   manifest writer.
4. Overnight batches: progress dashboard exists ✅; add per-unit QC gate between render
   and pack (the critic exists — wire the 3-pose sheet into it).

---

## The delta list (do before/with the H1 bake)

| # | Delta | Blocks |
|---|---|---|
| D1 | Pin view transform (`Standard`) in template + verify old frames' transform | H1 consistency |
| D2 | Camera-space light rig assertion + 8-up silhouette contact-sheet QC gate | H1 |
| D3 | Hue-shift ramp node group in the shared material library | look |
| D4 | Per-unit manifest (engine/samples/transform/seed/passes) | reproducibility |
| D5 | OIDN to compositor; record denoise strength | quality/time |
| D6 | Outline pass (inverted hull, 60% darkened rim) as a render layer | readability |
| D7 | Attack strip = 2 anticipation / 1 strike / 2 recovery, per-pose QC sheet | H1 drama |
| D8 | Post-downscale palette quantisation + 2px atlas padding audit | atlas |

None of these change the pipeline's shape; all are template/config/code edits in
`render_8dir_v2.py` + the QC gate. **Do them BEFORE the overnight batch** — a 49-unit
re-render because the transform mismatched is the expensive way to learn D1.
