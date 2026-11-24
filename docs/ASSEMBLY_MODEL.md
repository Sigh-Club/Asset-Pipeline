# How game characters are actually built — and why our "one big mesh" route is wrong

**Researched 2026-11-23.** This corrects the approach in `tools/blender/aaa_rebuild.py`: the AAA tier was
being produced as a single monolithic mesh with one atlas and one bake. That is not how characters are
built in modern game development, and it is the reason every material decision in this pipeline is a
global compromise instead of a per-part one.

---

## 1. What the industry actually does

### Modular characters are multiple skeletal meshes

Epic's own documentation for Unreal Engine, "Modular Characters in Unreal Engine":

> "Describes the different methods you can use to create modular characters comprised of **multiple
> Skeletal Meshes**." — [dev.epicgames.com, Modular Characters](https://dev.epicgames.com/documentation/en-us/unreal-engine/modular-characters-in-unreal-engine) (retrieved 2026-11-23; the page is
> client-rendered, so the statement is taken from Epic's own document summary)

The methods it covers exist precisely because a character is assembled, not sculpted as one object: a
body mesh plus separate meshes for helmet, torso armour, arms, legs, and gear, all bound to one
skeleton and combined at runtime.

### Gear attaches to sockets, not to the mesh

Epic, "Skeletal Mesh Sockets":

> "Once set up, you can attach your objects, weapons, and other actors to the Socket."
> — [dev.epicgames.com, Skeletal Mesh Sockets](https://dev.epicgames.com/documentation/unreal-engine/skeletal-mesh-sockets-in-unreal-engine)

Sockets live on the **skeleton**, so any asset sharing that skeleton can carry any weapon, backpack,
pauldron or VFX emitter at a known transform. A practitioner summary states the engineering reason
plainly: without sockets, "attaching a prop to a moving character means writing fragile offset code that
breaks every time an animator tweaks the rig."

### The consequences for asset production

| practice | why it exists |
|---|---|
| one shared skeleton, many meshes | every unit, variant and DLC piece animates from the same clip set |
| per-part meshes | each part gets its own triangle budget, UV layout, material and LOD |
| per-part materials | cloth, ceramite, brass and leather each get correct roughness/metallic instead of one averaged value |
| sockets for gear | weapons and equipment are swappable without re-authoring the character |
| LOD per part | a pauldron can drop to 200 tris while the torso stays high — you cannot do that inside one mesh |
| kitbash / modular kits | new variants come from recomposing existing parts, not re-modelling |

## 2. What we do instead — measured

`tools/blender/aaa_rebuild.py` (reference-base route) produces:

- **one** mesh: subdivide the whole body to 120,000 tris;
- **one** atlas: a single 4K normal/AO baked across the entire figure;
- **one** material decision per slot name, applied globally (`SLOT_SURFACE`);
- **one** LOD chain for the whole body;
- gear fused into the body, positioned by the sculpt rather than by a socket.

That is why the material work kept failing: with the whole figure in one bake and one atlas, the
trousers, the pauldron and the rifle share one texel budget and one normal map, and every per-slot
tuning is a compromise against the other three.

## 3. Our own repo already proves the modular route wins

`TODO.md` scores the DoW2 import — which is *modular assembly* — at **85–95 % per unit**, and
`AGENTS.md` G3 states the rule explicitly:

> "**Assemble from the shipped wargear `render_models` list**, de-duplicating quality tiers."

The DoW2 units are body + wargear armour + weapon, assembled from shipped parts, each with its own
mesh, material and (where shipped) clips. That path scores 85–95 %. The monolithic AAA route is the
one that needed six iterations to stop looking wrong.

The competition does the same thing from the other direction: Tripo and Meshy both sell **segmentation**
as the step *before* rigging — "separate rigid parts before rigging for cleaner deformation" and
"break characters into modular equipment pieces" (`docs/AGENTIC_3D_RESEARCH.md` §2.3).

## 4. The change this implies

Produce a **part set**, not a single GLB:

```
<unit>/
  skeleton.glb            one shared rig; sockets named (hand_r, head, back, hips)
  body.glb                base body, own UV/material/LOD chain
  gear/pauldron_l.glb     attached at socket, own budget + material
  gear/pauldron_r.glb
  gear/helmet.glb
  gear/weapon.glb         at hand_r socket
  unit.manifest.json      parts, sockets, per-part budgets, materials, LODs
```

Rules that follow from the research:

1. **Per-part budgets.** A pauldron is not 1/6 of a hero character's 120,000 tris; it is 3,000–8,000
   with its own LODs.
2. **Per-part materials.** Ceramite, brass, cloth and leather get their own roughness/metallic ranges,
   not a global `SLOT_SURFACE` table applied to one atlas.
3. **Sockets on the skeleton.** Gear position comes from a named bone socket, so a new pauldron needs no
   re-bake of the body.
4. **Per-part bakes.** The normal bake is per part against that part's high-poly source, which is also
   what makes a 4K map affordable: a pauldron at 4K is far denser in texels than a whole body at 4K.
5. **Assembly is data.** The manifest is what the engine reads; recomposing a variant is editing the
   manifest, not rebuilding a mesh.

## 4b. Implemented and verified (2026-11-23)

`tools/blender/aaa_assemble.py` is now a stage in `tools/build_unit_aaa.sh` (step 2/5). It produces,
and then **re-loads every file it wrote to verify** bones, sockets, skin and clips survived:

```
skeleton.glb                       22 bones, 9 clips, 5 SOCKET_* nodes parented to their joints
  SOCKET_weapon_r -> RightHand     SOCKET_weapon_l -> LeftHand     SOCKET_head -> Head
  SOCKET_back -> Spine2            SOCKET_hips -> Hips
parts/line_infantry_<slot>.glb     4 parts, 120,000 tris total, each skinned to the 22-bone rig
parts/line_infantry_<slot>_lodN.glb per-part LOD chain at 50 / 25 / 10 %
unit.manifest.json                 parts, budgets, LODs, sockets, skeleton, provenance
```

Measured on line infantry: parts at 43,008 / 31,266 / 29,724 / 16,002 tris, each with LOD1–LOD3
(21,503 / 10,752 / 4,300 …), every part verified `skinned=True bones=22 clips=9`. Re-importing the
skeleton plus the four parts renders the identical figure — the assembly reconstructs the whole, which
is the test that a modular set is actually complete.

**Honest limitations, recorded not hidden:**

1. The parts are derived by splitting the built LOD0 on material boundaries. The *structure* is
   industry-shaped; the *provenance* is a split, not separately authored gear. `unit.manifest.json`
   states this in `provenance`.
2. Every part carries the whole-body 4K bake. Per-part bakes are the next step and are where the
   texture budget actually gets spent properly.
3. Sockets are declared and exported, but gear is still fused geometry — nothing is *attached* at a
   socket yet. The socket nodes exist so that the first separately-authored gear piece can be.

## 5. What this does not change

The band numbers in `docs/STYLE_BANDS.md` still apply — they now apply **per part** rather than per
figure. The gates still apply: contract, texel floor, baked normal, vision review. The generator is
still the geometry source. What changes is the unit of production.

## 6. Tripwire

Re-check if the engine side adopts a virtualised-geometry pipeline (Nanite) for characters, which
removes the per-part LOD incentive but not the per-part material and socket ones.

## 7. Closing the three limitations — plan, evidence and falsifier

### 7.1 Parts derived by material split → real authored or segmented parts

**Two routes, in order of fidelity:**

**(a) Source the gear from the shipped wargear.** `AGENTS.md` G3 already mandates it: *"Assemble from the
shipped wargear `render_models` list."* DoW2 ships body, armour overlays and weapons as **separate
models with their own meshes and materials**, already posed and already bound to a 93-bone skeleton.
`tools/dow2/discover_units.py` + `build_community_units.py` already resolve `default_wargear` to shipped
files per unit (see `TODO.md` §2: "each unit's `default_wargear` resolved to shipped models"). The work
is to feed those gear meshes into the AAA assemble stage instead of splitting a generated body.
This is the only route that gives **authored** parts rather than inferred ones.

**(b) Semantic segmentation of the generated mesh.** `tencent/Hunyuan3D-Part` (open weights) provides
P3-SAM, a native 3D part-segmentation model — its card states *"P3-SAM can handle any input mesh"* — and
returns part masks plus bounding boxes. That converts a generated monolith into head / limbs / gear
regions without inventing geometry. This is also exactly what Tripo and Meshy sell as "segmentation
before rigging" (`docs/AGENTIC_3D_RESEARCH.md` §2.3).

**Falsifier:** if the segmented parts cannot be re-posed independently (a pauldron that deforms when the
shoulder rotates is not a part), the segmentation is cosmetic and route (a) is the only real answer.

### 7.2 Shared 4K bake → per-part bakes at per-part texel density

Per part: fresh 0–1 UV layout with a 32 px margin at 2K (1/128 of resolution), a resolution chosen from
that part's surface area against the 1024–2048 px/m band, and its own normal/AO bake from the high-poly.

The arithmetic is the whole argument: a pauldron occupying ~1/6 of a shared 4K atlas receives ~1/6 of
the texels; the same pauldron with its **own** 1K layout receives ~4–8× the texel density, because it no
longer shares with the torso, trousers and rifle. This is standard practice — modular UV layouts and
per-piece texture sets are AAA UV practice (nastyrodent, *UV Unwrapping for Games*; Tripo, *Smart Mesh UV
Strategy for Modular Kits*), and the atlas-packing guidance is explicit that texel density must be
preserved per packed region (CraftPBR, *Texture Atlas Guide*).

**Falsifier:** measure px/m per part with the existing formula; if a part's density does not exceed what
it had in the shared atlas, the re-layout is not worth the extra draw call.

### 7.3 Sockets declared but gear fused → rigid gear parented to the socket

Classify each part:
- **rigid** (helmet, pauldron, backpack, weapon) → compute the offset from the socket bone's rest matrix,
  parent the part to the `SOCKET_*` node, drop its skin weights. Practitioner consensus: *"you can parent
  hard objects directly to a bone"*; Epic's sockets exist for exactly this.
- **deforming** (underlayer, cloth) → keep skinning to the same bones, as shipped characters do
  (*"each hair, armor, and clothing is essentially another skin using the same bones"*).

Once rigid gear is socket-parented, a variant is a **part swap in the manifest**, not a re-bake of the
body — which is the entire commercial reason for modular characters.

**Falsifier:** play a clip and measure the attached part's transform relative to the socket bone across
frames. If it drifts, the offset was computed in the wrong space.

### 7.2b Implemented: per-part bakes (2026-11-23)

`aaa_assemble.py` now gives every part its own layout, its own resolution from its own
surface area, and its own bakes. Measured on line infantry:

| part | LOD0 tris | res | px/m | albedo | normal | AO |
|---|---|---|---|---|---|---|
| armour_primary | 43,008 | 4096 | 1339 | True | True | False |
| metal_trim | 31,266 | 2048 | 1053 | True | True | True |
| armour_secondary | 29,724 | 2048 | 1081 | True | True | True |
| underlayer | 16,002 | 2048 | 1691 | True | True | False |

All four parts meet the 1024 px/m PC floor (they previously shared one 4K atlas at
1,366 px/m for the *whole* figure, so the smallest part received a fraction of that).
Re-importing skeleton + parts renders the identical figure, so the set still composes.

Two failures found and fixed on the way, both recorded because they will recur:

* A ray-cast albedo transfer between two layouts of the *same* mesh is unreliable —
  with a positive cage extrusion the ray starts outside the coincident source, and on
  open shells it misses. Replaced with a UV-space rasteriser (`bake_utils.
  transfer_uv_texture`), which is exact and needs no rays.
* Layer names are not trustworthy: `smart_project` can write into the layer that was
  meant to be preserved, which produced 99.7 % black albedo maps. The source layout is
  now captured to an array *before* unwrapping.

AO failed on two parts (open shells where the occlusion ray escapes). Recorded as
`ao=false` in the manifest and not multiplied in — not masked.

### 7.3b Implemented: rigid gear on sockets (2026-11-23)

`tools/blender/aaa_socket_gear.py` (stage 3/6 of the build) classifies rigid pieces by a
measured rule — a face whose every vertex is weighted >=0.95 to one bone moves rigidly with
that bone — then parents each piece to its socket and drops its skin. Skeleton now carries
**12 sockets**.

| bone | socket | faces | follows bone | drift |
|---|---|---|---|---|
| Head | SOCKET_head | 4,026 | True | 0.0 |
| RightUpLeg | SOCKET_thigh_r | 3,706 | True | 0.0 |
| LeftFoot | SOCKET_boot_l | 3,330 | True | 0.0 |
| RightFoot | SOCKET_boot_r | 2,736 | True | 0.0 |
| RightToeBase | SOCKET_toe_r | 1,020 | True | 0.0 |
| LeftUpLeg | SOCKET_thigh_l | 691 | True | 0.0 |
| RightLeg | SOCKET_knee_r | 606 | True | 0.0 |
| LeftToeBase | SOCKET_toe_l | 462 | True | 0.0 |

The falsifier from §7.3 passes on every piece: posing the rig from a clip and comparing the
part's transform in the *pose* bone's space gives drift 0.0. (The first version of that check
compared against the bone's *rest* matrix and reported false drift — the check was wrong, not
the attachment.)

The body is exported with those faces removed (`103,423`
faces), so the assembly is body + gear rather than body-with-gear + gear.

**What this cannot do, measured rather than assumed:** there is **no rigid cluster at the
hands**, because the rifle was skinned into the body rather than attached. The weapon is
therefore not separable by this rule, and it stays in the body until step 3 brings in the
shipped wargear. This is recorded in the manifest (`rigid_gear_note`).

**Residual:** removing the rigid faces leaves an open boundary on the body where the gear was
cut away; at grazing angles the seam can show. Mitigation when it matters: keep a low-poly
under-layer of those faces, or cap the boundary.

### 7.3c Albedo: what was actually wrong, and what fixed it (2026-11-23)

Three attempts failed before the cause was measured:

1. Multiplying the atlas albedo by a library detail map at 0.55 — no visible change, because
   the atlas measures **0.10-0.25 in RGB**; multiplying a dark base by a mid-grey detail
   changes nothing a viewer can see.
2. The reason nothing reached the render at all: **the body/gear stage ran on the pre-part
   mesh**, so the per-part bakes and materials were built into `parts/` and then never used by
   `line_infantry_body.glb`. An ordering bug, not a material bug.
3. The join in that stage picked an 80-tri `Icosphere` reference mesh as its active object,
   because the reference mesh was being exported inside **every** part GLB.

Fixed: the reference mesh is removed at import; gear extraction runs on the per-part set
(`--from-parts`), so body and gear carry the per-part UVs, bakes and materials; and the albedo
is built the right way round — **library PBR albedo as the base** (authored detail and value)
with the unit's colour identity as a **constant per-part tint**, derived by keeping the atlas
hue and restoring its value (`--tint-value`, default 0.8). Measured tints: armour_primary
(0.33, 0.45, 0.80), metal_trim (0.44, 0.53, 0.80), armour_secondary (0.53, 0.59, 0.80),
underlayer (0.79, 0.79, 0.80).

The result reads as the intended unit for the first time: camo trousers, gold shoulder trim,
plated armour and a detailed rifle.

**Attempted and parked: projection texturing from the reference views.** `bake_utils.
project_reference_texture` projects front/back/left/right onto the mesh by orthographic bbox
mapping, which is what a reference-driven pipeline should do. Measured outcome: the concept's
upper body and arm bands land correctly, but the legs come out unfilled/black, because an
orthographic bbox projection cannot align a *generated* mesh to a *flat drawing* — the drawing's
proportions and the mesh's differ, and there is no camera to solve against. It is available as
`--views <dir>` and needs a camera solve (or per-region alignment) before it can replace the
composite. Four failed variants were tried before the cause was clear: vertical flip, axis swap,
part-vs-character bounds, and library multiply on top — each produced a pixel-identical render,
which is what proved the source image was not reaching the output.

**Still not competitor tier, and the reason is specific:** the albedo is a *composite* of a 1K
tiling library and a flat tint, not an authored 2K-4K albedo set matched to the concept. That is
the remaining art gap, and it cannot be closed by compositing existing assets — it needs a real
albedo source (generated PBR from the reference, or an authored set).

### 7.4 Order and cost

| step | gain | cost | risk |
|---|---|---|---|
| 1. per-part bakes (§7.2) | **largest visible quality gain**; no new data needed | mechanical: loop the existing bake per part with its own layout | low — the bake and texel machinery already exist and are gated |
| 2. socket-parent rigid gear (§7.3) | unlocks variants and equipment swapping | needs a rigid/deforming classification per part | medium — offsets must be verified per bone |
| 3. real gear sourcing (§7.1a) | authored parts instead of inferred; the structural fix | wiring DoW2 wargear into the AAA stage | medium — the wargear resolution already exists, the assembly path does not |
| 4. P3-SAM segmentation (§7.1b) | semantic parts for *generated* units with no shipped gear | model download + VRAM (8 GB card, one job at a time) | medium — new dependency, unproven on our meshes |

Do them in that order. Step 1 is pure gain with the machinery already built; step 3 is the one that makes
the structure genuinely authored, and it should not be attempted before the per-part pipeline exists,
or the gear will be authored and then baked into one atlas anyway.

## 8. Vision gate: certified, and what it found (2026-11-23)

`tools/review/certify.py` passes all six checks — the gate separates a good render from a detached-part
render and a flattened render, names the injected defect, and scores the good one higher (7.0 vs 4.0):

```
[PASS] good render is not stopped        decision=continue
[PASS] detached part is rejected         decision=refine-code
[PASS] detached defect is named          "[critical] head and upper shoulder detached..."
[PASS] flat render is rejected           decision=refine-code
[PASS] flat defect lands on detail/contrast
[PASS] good outscores both broken        7.0 vs 4.0 vs 4.0
CERTIFIED
```

Getting it certified required three fixes, each a real failure: the format demand had to lead the prompt
(the model answered in prose when it trailed), the critic had to tolerate a plausible variant schema
(`{verdict, pass, issues:[{type,severity,description}]}`) and record what it derived, and `pkill -f
certify.py` had to stop killing its own shell.

**What the gate then found in the asset, and what it fixed.** Its first certified review named
"excessively glossy and metallic across the camo pants, boots and weapon" as the top defect. Chasing that
found a real bug: the part materials had metallic/roughness **linked to a texture**, so every
`default_value` the script set was ignored — confirmed by reading the exported GLB, which carried
`metallicRoughnessTexture` with `metallicFactor=None`. Unlinking before authoring produced the intended
factors in the GLB (`armour 0.1/0.55`, `metal_trim 0.55/0.50`, `underlayer 0.0/0.92`, `mrTex=False`), and
the gate now returns `continue` at 7.0 across all five features.

**The residual defect the gate keeps naming is albedo contrast, not material response**: the library
albedo carries bright patches that read as highlights under review lighting. That is the same gap as
§7.3c — a composite albedo, not an authored set — and it is the one thing left that compositing cannot
fix.

## 9. Final material state and the trade-off that was resolved (2026-11-23)

Two albedo fixes were measured against the gate, and one was rejected:

| change | gate result | decision |
|---|---|---|
| luminance-only flatten of the library albedo (removes baked lighting) | `continue`, 7.0; the "specular/metallic sheen" defect drops | **kept** |
| per-slot desaturation of the library (tint as sole colour authority) | `continue`, 7.0, but the render goes flat grey | **rejected** |

The desaturation removed the "unintended yellow/tan bands" defect but also removed the concept's
**gold shoulder trim** and the cloth's camo variation — colour identity is the more important property, so
desaturation is off (`SLOT_DESAT` all 0.0) and the flatten does the work alone. That is a recorded
trade-off, not an oversight: the defect it leaves behind is cosmetic, the one it fixes is identity.

Authoring values now in the build: `armour 0.10/0.55`, `armour_secondary 0.10/0.60`,
`metal_trim 0.55/0.50`, `underlayer 0.00/0.92` (metallic/roughness), exported as material factors with no
metallicRoughness texture, verified by reading the GLB.

**What remains, and what it would take:**

| gap | cause | fix |
|---|---|---|
| helmet reads bulbous, groin plate thin, proportions stockier | the *generated mesh's* shape, not the material pipeline | better source geometry or a reference-matched generator; not fixable downstream |
| albedo is a composite, not authored | no authored 2K-4K set exists for this unit | the shipped DoW2 wargear textures (128-512 px, too small) or a working image-generation route |
| weapon not separable | no rigid cluster at the hands; the rifle was skinned into the body | step 3: assemble from shipped wargear meshes |

The first row is the honest answer to "are we at competitor tier": the material and structure work is
there; the *shape* is the generator's, and it is the shape the gate keeps naming.
