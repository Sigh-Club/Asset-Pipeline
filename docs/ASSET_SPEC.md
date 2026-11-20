# Asset specification — the contract, independent of the source

> Audience: whoever produces art for this project, and whoever maintains the pipeline.
>
> **Why this file exists.** The pipeline was built by reverse engineering Dawn of War II. The *art*
> in that game is Relic's; the *method* is not. US Copyright Office Circular 31, quoting 17 U.S.C.
> §102(b): "In no case does copyright protection for an original work of authorship extend to any
> idea, procedure, process, system, method of operation, concept, principle, or discovery". So the
> numbers, formats, limits and techniques below are ours to keep and build on. What we must replace
> is the expression: the meshes, the textures, the audio, the names. See
> `docs/METHOD_PORTABILITY.md` for the boundary and the adapter that lets a different source feed
> this pipeline.
>
> **How to read the labels.** Every statement is one of:
> * **[M] measured** — read out of shipped game data, with the file and command named.
> * **[E] engine** — required by the shipped engine, as encoded in the community exporter's own
>   validation (an exporter is the engine's requirements written as code).
> * **[C] our choice** — a decision of this project, with the reason. Changeable, but not silently.
>
> The machine-readable form of the enforceable parts is `docs/asset_spec.json`, checked by
> `tools/spec/validate_assets.py`. Where this document and that file disagree, the file wins and the
> document is the bug.

## 1. Space, scale and orientation

| fact | label | source |
|---|---|---|
| Combat grid cell is **2.0 m** | [M] | `Imperium-of-Ash/frontend/src/three/gridMath.ts` (`TILE_SIZE`) |
| Elevation step is **0.35 m** | [M] | same (`ELEVATION_STEP`) |
| +Y up, forward −Z, right-handed | [C] | same; the engine's own space is +Z up (see §3) |
| Shipped DoW2 maps use **8–32 m** ground tiles | [M] | `output/source_lab/maps/*.json` `terrain.tile_world_scale` |
| A DoW2 1v1 map's playable area is **512×320 nav cells** with 5 layers | [M] | `PRMP` decode, e.g. `1v1typhonlowlands` |

The 2 m / 0.35 m pair is what every other budget in this document is expressed against. An asset
authored at another scale is not "close enough": a 1.8 m door reads as a hatch and a 0.5 m step
becomes unclimbable.

## 2. Mesh contract

| requirement | value | label | evidence |
|---|---|---|---|
| Vertex attributes | position, bone indices, weights, normal, **binormal**, **tangent**, UV0, UV1 | [E] | `model/exporter_meshes.py:753` `write_vertex_elements` |
| Bone influences per vertex | **4 maximum** (strongest 4 kept) | [E] | `model/exporter_meshes.py:325` |
| Influencing bones per mesh | **54 maximum** (split the mesh if exceeded) | [E] | `model/exporter_mesh_plan.py:9` |
| Sub-mesh granularity | one sub-mesh per material | [E] | `_collect_triangles_by_material`, `exporter_meshes.py:398` |
| LOD chain | per mesh group, LoD0 first | [E] | `export_mesh_group`, `exporter_meshes.py:658` |
| Bounding volumes | per sub-mesh, and per bone for skinned meshes | [E] | `export_bounding_volumes`, `exporter_meshes.py:850` |
| Tangents | computed, not supplied, when absent | [E] | `compute_tangent_space`, `exporter_meshes.py:518` |
| Degenerate material names | rejected | [C] | `tools/glb_contract.py` `PLACEHOLDER_MATERIALS` |

**glTF translation** (our output format, [C]): `POSITION`, `JOINTS_0`, `WEIGHTS_0`, `NORMAL`,
`TANGENT` (with the w sign carrying the binormal orientation — glTF has no separate binormal),
`TEXCOORD_0`, `TEXCOORD_1`. The engine's explicit binormal is reconstructed from
`cross(normal, tangent) * tangent.w`, which is why the sign must be authored correctly rather than
left at 0.

**Budgets we ship at** [M, measured over the current kit]: environment props 8–4052 triangles,
median 320. The gate's class limits (`tools/glb_contract.py` `LIMITS`) are the enforcement, and the
spec's copy of them is checked against it so the two cannot drift.

## 3. Rig and skeleton contract

| requirement | label | evidence |
|---|---|---|
| Skeleton space conversion is a **−90° Z rotation** plus a DX mirror (`BLENDER_TO_DX`) | [M] | `docs/DOW2_COMMUNITY_TOOLCHAIN.md`, constants verified against shipped files |
| Clip space and model space are **different skeletons** with the same bone names — only 5 of 39 local rests match on the guardsman | [M] | same, measured |
| Bone names are the join key: clips address bones by name, and a renamed bone silently drops the track | [M] | `tools/dow2/action_motion.py` track→bone binding |
| Per-part health states: `healthy`, `light_damage`, `heavy_damage`, `wreck` | [E] | `collision/utils.py:12` `COLLISION_STATE_DEFINITIONS` |
| Aim is layered by direction (`aim_left/right/up/down`), not one blended clip | [M] | `action_library.json`, 542 actions |

**Our rig requirement** [C]: a humanoid must provide the same named bone set the clips address,
because our action library is keyed by bone name. A source that cannot name its bones cannot play
our clips — that is the first thing an adapter must satisfy.

## 4. Animation contract

| requirement | value | label | evidence |
|---|---|---|---|
| Data form | per-frame absolute **local** bone transforms, all bones, every frame | [E] | `animation/export_core.py:161` `gather_animation_data` |
| Space | DX (the mirror applies) | [E] | `blender_to_dx_matrix`, same file |
| Quaternion continuity | sign flipped when `dot(prev, cur) < 0` | [E] | `export_core.py:150` |
| Duration | `(frames − 1) / fps` — a 30-frame clip at 30 fps is 0.967 s | [E] | `export_core.py:163` |
| Layering | base + upper-body additive, driven by `.hkanim` state | [M] | documented, **not implemented by us** — recorded gap |
| Motion trees | `.motiontree` state machines select clips | [M] | **not implemented by us** — recorded gap |

**Our rule** [C]: an action bakes at its true duration, never a re-timed approximation, and the
timing gate (`action_motion.py --timing-only`) fails the build if a clip's duration drifts. That
rule exists because a re-timed clip reads as sliding feet and no numeric check caught it.

## 5. Material contract

The engine's material interface is a fixed slot table, not free-form PBR. Measured from the
community exporter, which reconstructs it faithfully enough to round-trip shipped materials:

| element | detail | label | evidence |
|---|---|---|---|
| Texture slots | **28** named slots: `diffuseTex`, `normalMap`, `specularTex`, `glossTex`, `emissiveTex`, `occlusionTex`, `teamTex`, `badge1Tex`, `badge2Tex`, `damageDiffuseTex`, `damageNormalTex`, `damageSpecTex`, `dirtTex`, `overlayTex`, `scarTexture`, `dualScar*`, `normalMapCoarseTex`, `normalMapFineTex`, `normalMapFoamTex`, `cliffTex1`, `cliffNormalTex1`, `grassTex1`, `grassNormalTex1`, `waterColourTex`, `waterTurbulenceTex`, `waterTurbulenceMaskTex` | [E] | `material/definitions.py:12` `TEXTURE_SLOT_NAMES` |
| Specular convention | `specularTex` **RGB is specular colour, A is gloss** | [E] | `material/shaders/node_passes.py:31` |
| Metalness conversion | `metal = clamp((max(r,g,b) − 0.04) / 0.96)` | [E] | same, `apply_legacy_specular_metalness` |
| Roughness conversion | `rough = 1 − a` (legacy), or `0.65 − a` (reflective path) | [E] | same, both passes |
| Team colour | `teamTex` is a mask; the tint comes from one of **4 palettes** | [E] | `material/definitions.py:88` |
| Float parameters | `brightness`, `damageTexTilingFactor`, `dirtVisibility`, `emissiveMultiplier`, `glossValue`, `uOffset`, `vOffset` | [E] | `material/definitions.py:56` |
| Bool parameters | `alphaTest`, `bHighlight`, `enableScarring`, `useDepthTest`, `useLighting` | [E] | same |
| Damage states carry their own diffuse/normal/spec set | `damage*Tex`, `dualScar*Tex` | [E] | same |

**What this means for our own art** [C]: we author **albedo, normal, and a packed
specular/gloss map in exactly this convention** (RGB specular, A gloss), because the conversion to
metallic/roughness is then exact and reversible. This is the single most useful thing taken from
the engine's material model, and it is why the environment kit's earlier "metal 0, rough 0.8" was
wrong: it discarded the shipped specular map and flattened every surface to dielectric.

Recorded failure, for the record: forcing albedo-only material made every metal prop render black,
because the *building* shader graph exported a black combined base colour and a 1.04 metallic
factor. Fix: albedo from `_dif`, and derive metalness from the packed specular channel per the
formula above.

## 6. Collision, physics and cover

| element | contract | label | evidence |
|---|---|---|---|
| `.collision` | one mesh **per damage state** (healthy, light, heavy, wreck) | [E] | `collision/utils.py:12` |
| Simple collision | walkable surfaces only: faces whose world normal is within N° of up | [E] | `_filter_walkable_faces`, `collision/utils.py:249` |
| Complex collision | projectile and unit nav, for garrisonable structures | [E] | `readme.md:91` |
| `.simbox` | Havok rigid-body properties: mass, allowed penetration depth, friction, restitution, quality type, contact-callback delay, deactivation class/counter, damping, max linear/angular velocity, filters, centre-of-mass mode | [M] | `physics/hull_properties.py` header, corpus-derived |
| `.coverbox` | cover volumes, read and used by our kit (`cover` + footprint per prop) | [M] | `env_kit.json` |
| `.markers` | named attachment/effect points, transformed with bones | [E] | `readme.md:87`, **not adopted by us** |

Corpus-measured physics values worth reusing [M]: static building bodies use mass 0,
`HK_REAL_MAX` penetration, friction 0.5, restitution 0.4, quality type 1 (fixed), deactivation class
1 (never); dynamic rubble uses mass ~2–20, penetration ~0.1, quality type 4 (moving), deactivation
class 2 (at rest).

**Our requirement** [C]: every prop that a unit can stand on, shoot through, or take cover behind
must declare a cover volume and a footprint, because the map forge and the combat grid both consume
them. A prop without them is decoration, and must be labelled as such.

## 7. Terrain contract

The terrain model is fully recoverable and is the most valuable single finding of this review:

| element | contract | label | evidence |
|---|---|---|---|
| Layers | **8**, each a `(surface, cliff)` path pair | [E] | `map_io/terrain_material_nodes.py`, verified against `RCTI/LAYR` in shipped maps |
| Per-layer textures | diffuse, normal, specular — for both surface and cliff | [E] | `TerrainTextureSet`, `map_io/terrain_material_types.py` |
| Layer weights | **2 RGBA masks**; layer `i` weight = `mask[i // 4]` channel `i % 4` | [E] | `create_layer_weight_socket`, `terrain_material_nodes.py:96` |
| Layer activity | a per-chunk usage grid, same RGBA packing: layer `i` active = `usage[i // 4]` channel `i % 4` | [E] | `create_layer_activity_socket`, `:114` |
| Blend | weighted accumulation normalised by total weight, epsilon 1e-5 | [E] | `build_layer_stack`, `:161` |
| Mask sampling | `Closest`, `EXTEND` (not filtered) | [E] | `build_mask_nodes`, `:132` |
| Heightmap | u32 width/height + zlib float grid | [M] | `SCEN/GEWD/TERR/HMAN/HITE/HVAL/HEAD` + `VALS` |
| Nav grid | width, height, layers, byte grid | [M] | `WRLD/WLDI/PFDR/PRMP` (bytes **not yet decoded** — recorded gap) |
| Image samplers | 28 maximum in the terrain shader | [E] | `map_io/terrain_material_images.py:10` |

**Our terrain spec** [C]: adopt the 8-layer / 2-RGBA-mask / usage-grid structure as-is, because it
is cheap (8 weights fit in two textures), it is what the art was authored against, and it gives a
map author a vocabulary that matches how the ground actually varies. Our forge currently renders a
single ground texture per biome; closing that gap is a recorded task, not a silent simplification.

## 8. Map and placement format

| element | contract | label | evidence |
|---|---|---|---|
| Map container | chunk tree with 4-byte tags, sizes and offsets | [M] | `SCEN` root, decoded by `tools/dow2/scenario_decode.py` |
| Placements | blueprint index into a path table + 4×3 transform | [M] | `SMEG/EBPT` + `ENTL/ENTY/ENTI` |
| Blueprint naming | `ebps/...` entity blueprints, `art/...` model paths | [M] | decode output |
| Blockers | `move_blockers` / `move_shot_blockers` are **invisible shape blockers**, the most-placed entries in the corpus (6612 / 756) | [M] | corpus frequency count |

**Our decision** [C]: blockers are *not* props. The map forge's paint layer is their equivalent, so
importing a shipped map must convert blockers into paint rather than into geometry.

## 9. Whose limit is it — ours, or the source engine's

This distinction is the difference between a spec and a cargo cult. A limit belongs in our contract
only if it is a limit of **our** target engine or of the vertex format. A limit of DoW2's D3D9
renderer must be *recorded*, not imposed: building our own art to it throws away headroom for no
reason, and failing imported art against it reports a defect that is not one.

| limit | value | whose | do we enforce it |
|---|---|---|---|
| bone influences per vertex | **4** | universal — the vertex attribute format, and the target engine's own hard limit | **yes**, hard failure |
| bones per skinned mesh | 54 | DoW2 / D3D9 shader constant budget | **no** — recorded |
| bones per skinned mesh | **256** | WebGL2: guaranteed `GL_MAX_UNIFORM_BLOCK_SIZE` 16 KB ÷ 64 bytes per bone matrix | **yes**, hard failure |
| terrain image samplers | 28 | DoW2 / D3D9 sampler slots | **no** — recorded |
| texture units in practice | 16 | WebGL2 guaranteed minimum | reference only |

Evidence for the 4-influence limit: the shipped exporter truncates to the strongest four
(`model/exporter_meshes.py:325`), and the target engine enforces the same ceiling
(three.js issue 26137: "Currently ThreeJS limits how many bones to skin a vertex to at most 4"; forum
thread 47457 confirms it is unchanged). So 4 is not a DoW2 quirk — it is the format.

Evidence for 256: the WebGL2 backend stores `skeleton.boneMatrices` in a uniform block and fails to
link beyond `GL_MAX_UNIFORM_BLOCK_SIZE / 64`, i.e. 256 at the 16 KB the specification guarantees
(three.js issue 34196).

Measured consequence, which is why this section exists: **19 converted units exceed DoW2's 54-bone
limit**, the largest at 110 joints, and they render correctly in our engine. Enforcing 54 would have
rejected a third of the roster as broken. The validator reports them under "over the source engine's
54-bone limit — legal in our engine" rather than hiding them.

## 10. Recorded gaps

Honest list of what is documented here but not yet implemented. Each is a task, not a disclaimer:

1. `.hkanim` additive layering and `.motiontree` state machines.
2. `.collision` simple/complex meshes — we use cover volumes only.
3. `.simbox` physics hulls — we ship static props with no body.
4. `.markers` attachment points.
5. Terrain layer blending in the forge (single texture today).
6. `PRMP` nav grid bytes (dimensions only).
7. `RSH` atlas composition — we read `_dif.dds` directly and ignore channel packing.
8. Specular/gloss maps are not yet authored for our own art; the kit uses shipped maps.

## 11. Enforcement

```bash
python3 tools/spec/validate_assets.py --spec docs/asset_spec.json \
    --assets ../Imperium-of-Ash/frontend/public/assets --report /tmp/spec_report.json
python3 tools/glb_contract.py --dir ../Imperium-of-Ash/frontend/public/assets/models/env --kind env

# from the game repo, as a gate
npm run guard:spec
```

The validator checks the parts of this document that are checkable on our current output: attribute
presence, influence and joint limits against the *target* engine, per-class budgets, animation
duration sanity, and sidecar declarations. It reports recorded source properties separately from
failures, so a regression in our own art cannot hide behind an import exception.

Current state, measured: `env=151, prop=38, tile=1, unit=200, weapon=8` checked, **PASS**, with 28
flat-colour imports recorded (shipped weapon shells and two necron units ship no texture, so there is
no UV set to carry) and 19 units over the source engine's 54-bone limit. It also cross-checks `docs/asset_spec.json` against
`tools/glb_contract.py`'s `LIMITS`, so the prose, the spec and the gate cannot drift apart.
