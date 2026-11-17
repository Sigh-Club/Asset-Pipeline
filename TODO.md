# Asset-pipeline — live work tracker

**Updated 2026-11-17.** This is the actionable list, and it is the honest one: it states what works,
what is partial, and what is blocked, with the measurement that decides each. Read it before touching
the DoW2 import.

Authority and detail:

- [`docs/DOW2_STANCE_REFERENCE.md`](docs/DOW2_STANCE_REFERENCE.md) — how DoW2 units stand, the
  loadout rule, the part-assembly rule, and the four import rules (R1–R4) that make a build work.
- [`docs/DOW2_ANIMATION_DECODE.md`](docs/DOW2_ANIMATION_DECODE.md) — the clip format, the located
  animation header, and the exact next steps for the decoder.
- [`docs/BLENDER_MCP.md`](docs/BLENDER_MCP.md) — when to drive Blender interactively through MCP, and
  what not to use it for.
- [`docs/3D_ASSETS.md`](docs/3D_ASSETS.md) — the generated-art (img23d) path and the GLB contract.
- `PLANNING.md` — the sprite-era plan; superseded for 3D.

---

## 1. Current programme

**Copy DoW2 units 1:1 — geometry, materials, weapons, skeleton, animation — and drive them from a
turn-based combat system.**

DoW2 is an RTS; we are building a turn-based game. So the deliverable is not DoW2's locomotion cycles
but its **action library**: aim, fire, reload, melee, grenade, leap, throw, ability-cast, hit and
death — each with its timing and its events, triggerable from our action system.

## 2. State, measured

| piece | state | evidence |
|---|---|---|
| body geometry | **working** | `tools/dow2/chunky_mesh.py` decodes positions, UVs and the shipped per-vertex bone indices/weights |
| unit assembly | **working** | `tools/dow2/parts.py` resolves `render_models` (armour + head + accessories) and de-duplicates quality tiers (`ig_armour`/`ig_armour_epic` are one body; `_common_a/b/c` are not) |
| skeleton | **working** | `tools/hkx/hkxread.py` decodes `hkSkeleton`: bones, parents, reference pose |
| rig + skinning | **working** | optimal one-to-one assignment of the shipped bone indices (`resolve_skin_indices`), source textures applied |
| materials | **diffuse only** | `tools/dow2/dds_to_png.py` + material-name resolution; `_nrm`, `_spc`, `_ocl`, `_emi` and the team-colour masks are not wired |
| clips | **partial — the real gap** | see §3 |
| weapon hold | **approximate** | `WEAPON_HOLD` is authored; the 1:1 method is the shipped weapon model bound identity to `Bip01 R Weapon` (its geometry is authored in character space at the hand) |
| fidelity gate | **working** | `tools/rig_fidelity.py` measures tear / inversion / interpenetration / collapse **and fails a mesh that does not move** |
| engine side (IoA repo) | **done for this work** | loadout-aware clip resolution, source-material passthrough, per-battle command log; 665 jest, Go suites green |

### What builds correctly today

`tools/build_source_lab_all.sh` builds one unit per faction from the shipped data. Two are complete
and correct, and are the reference for what "done" looks like:

- `dow_ig_guardsman` — Imperial Guard body, shipped skeleton, shipped clips, shipped texture.
  `rig_fidelity.py --clip fb_idle_stand_01` → **PASS, 0.000 torn / 0.000 inverted**, and it renders as
  a complete, textured guardsman holding a lasgun.
- `dow_chaos_sorcerer` — Chaos body + head + backpack, same construction, same result.

The other four build but are wrong for known, data-side reasons (§4).

## 3. The clip gap — why only the rig's own clip is exact

Each shipped clip file carries a skeleton whose **reference pose is that clip's pose**, plus
delta-compressed animation tracks. We currently use the reference pose, so a unit is exact for the
clip it was rigged from and approximate for the rest of its loadout.

Measured, on the same body:

| construction | result |
|---|---|
| rig on `guardsman.hkx`, apply `fb_idle_stand_01` | every bone shows a **~180° delta** — a frame difference, not a pose — **23 % torn edges**, mesh shatters |
| rig on `fb_idle_stand_01.hkx` itself | **0.000 torn / 0.000 inverted**, correct render |

**The fix is the track decoder**, not another rig attempt. Established so far (see
`docs/DOW2_ANIMATION_DECODE.md`):

- the file declares `hkAnimationBinding` and `hkDeltaCompressedSkeletalAnimation` — i.e. **one
  skeleton plus track→bone bindings**, which is why one rig *should* play every clip;
- the animation header is located: `fb_idle_stand_01` at data offset 5320 — type 2
  (`HK_DELTA_COMPRESSED_ANIMATION`), duration 7.333 s, 46 tracks, `numberOfPoses` 221,
  `blockSize` 8 (implied 30.1 fps — self-consistent);
- **remaining:** map the last four field offsets (the tail of the struct holds pointers), read the
  quantisation format, decode one block. The validation is self-checking and cannot be faked:
  **frame 0 must reproduce the file's own `referencePose`**.

## 4. Blocked on shipped data (not code)

| unit | blocker | fix |
|---|---|---|
| `dow_ork_warboss` | its wargear lists armour **plates only**; the boy body is not in the list | add the boy body part to the assembly |
| `dow_necron_overlord` | its clips are not Havok packfiles (`magic 0x0003da78`) and its `.model` has no `FOLDSKEL` | locate its real skeleton (its markers name `rig_rleg_calf`-style bones) |
| `dow_eldar_farseer` | the farseer ships no skeleton; the build borrows the banshee's, whose robes are authored for a different rig | find the farseer rig |
| `dow_tyranid_lictor` | built on the carnifex loadout | use the lictor's own loadout |

## 5. Ordered next work

1. **Decode the animation tracks** (`tools/hkx/hkxread.py`): finish the field offsets, decode the
   quantisation/block payload, validate frame 0 against `referencePose`. This unblocks everything
   else and removes the per-clip rig entirely.
2. **Extract the action library**: for each clip, sample the frames an action needs (fire frame from
   the `hkAnnotationTrack` events, reload midpoint, leap apex) and export named actions with events on
   the one canonical rig.
3. **Weapon 1:1**: bind the shipped weapon model identity to `Bip01 R Weapon` after one mirror check
   (the lasgun geometry sits at +x while the guardsman's right hand is at −x), then delete
   `WEAPON_HOLD`.
4. **Materials 1:1**: wire the full channel set (`_dif`, `_nrm`, `_spc`, `_ocl`, `_emi`) and the
   team-colour mask compositing.
5. **The four blocked units** in §4 — data hunts, not rig work.
6. **Rebuild the lab** (`models/units/lab/`) through the fixed chain and re-run
   `tools/rig_fidelity.py` over it; the page reads `lab/fidelity.json`.

## 6. Commands (dry-run verified 2026-11-17)

```bash
export DOW2_RETRIB=/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution
IG=$DOW2_RETRIB/sga_art/000_data/DATA/art/race_ig

# one unit from the shipped data
tools/build_source_lab.sh dow_ig_guardsman \
  "$DOW2_RETRIB/attrib-decoded/wargear/wargear/core/race_imperial_guard/armor/flak_common.txt" \
  "$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx" \
  "$IG/troops/gaurdsman/animations/range_burst" \
  ../Imperium-of-Ash/frontend/public/assets/models/weapons/lasgun.glb 1.85

# the whole lab set (table + documented gaps inside the script)
tools/build_source_lab_all.sh

# the gate: tear / inversion / interpenetration / collapse, and a displacement floor
python3 tools/rig_fidelity.py output/source_lab/work/dow_ig_guardsman/dow_ig_guardsman.glb \
  --clip fb_idle_stand_01

# the animation-header report
python3 -c "import sys; sys.path.insert(0,'tools/hkx'); from hkxread import decode_report; \
decode_report('$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx')"
```

All four were executed against the current tree on 2026-11-17: the unit builds, the gate returns
`PASS` with `0.000` on every metric, and the header report prints the values quoted in §3.

## 7. Standing rules (learned, do not relearn)

- **Rig the unit with the skeleton from the same file its clips come from.** Mixing a unit `.hkx` with
  a loadout's clips gives a constant frame difference and tears the mesh.
- **Assemble from the shipped wargear part list**, de-duplicating quality tiers; a wargear that lists
  only armour overlays will build a pile of plates.
- **Never trust a numeric gate without a render** — a rigid mesh measures 0 % tearing. The gate now
  fails a mesh that does not move, and the render is still the acceptance.
- **Judge poses against the shipped game**, not from imagination: `docs/evidence/dow2-stance/`.
- **MCP is for investigation only.** The pipeline and the gates are scripts.

---

## Historical state (superseded, kept for context)

### Generated-art (img23d) path — 2026-11-09

| Area | State |
|---|---|
| 3D stage tools | working end to end: img23d → retopo → rig → bake → contract |
| GLB contract | PASS on line-infantry (20k tris, 22 joints, UVs, 2K atlas, 4 slots, 9 clips) |
| Material/pattern library | 79/79 built |
| Model training | `materials_v2_800` + `materials_v3_800` adopted |
| Clip set | 9/9 on the shipped unit; quality pass pending |
| Pixel tiers | pixeliser/registry exist; Boltgun-grade master/masks/ramps not yet |

The DoW2 source import supersedes this path for the roster: a DoW2 body is real authored geometry with
a shipped rig, which no generated mesh can match for silhouette or deformation.
