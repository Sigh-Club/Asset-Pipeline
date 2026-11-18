# Asset-pipeline — live work tracker

**Updated 2026-11-18.** This is the actionable list, and it is the honest one: it states what works,
what is partial, and what is broken, with the measurement that decides each. Read it before touching
the DoW2 import.

Authority and detail:

- [`docs/DOW2_COMMUNITY_TOOLCHAIN.md`](docs/DOW2_COMMUNITY_TOOLCHAIN.md) — **the build method**:
  the community importer, its constants, the pose sequence, the export flags, the traps.
- [`docs/DOW2_ANIMATION_DECODE.md`](docs/DOW2_ANIMATION_DECODE.md) — the clip format and our decoder.
- [`docs/HANDOFF_TURN_BASED.md`](docs/HANDOFF_TURN_BASED.md) — the self-contained handoff prompt.
- [`docs/DOW2_STANCE_REFERENCE.md`](docs/DOW2_STANCE_REFERENCE.md) — how DoW2 units stand and the
  import rules.
- `docs/KNOWN-ISSUES.md` — recorded defects, not masked.

---

## 1. Current programme

Copy DoW2 units 1:1 — geometry, rig, weights, materials, weapons, clips — and drive them from a
turn-based action system. DoW2 is an RTS, so the deliverable is its **action library**, not its
locomotion cycles.

## 2. State, measured (2026-11-18)

| piece | state | evidence |
|---|---|---|
| assembly | **working, community toolchain** | `tools/blender/dow2_import_community.py` uses the DoW2 Tools add-on (dow2-blender v0.3.3) for body, head, weapon, weights and materials |
| rig | **working** | the add-on builds the armature from the model's own `FOLDSKEL` with its bone-axis adapter |
| clips | **working for 7 units** | the add-on's pose sequence (DirectX→Blender, rest delta, adapter) with our decoder; export with `export_optimize_animation_size=False` |
| heads | **working** | imported from the ebps `animator_attachments` (`cadian_trooper`, `warboss_head_01`) |
| weapons | **partial** | guardsman lasgun, necron tachyon arrow, tau burst cannon are the shipped models; chaos, eldar, warboss and lictor carry no weapon yet |
| materials | **imported** | the add-on resolves `_dif`/`_nrm`/`_spc`/`_emi`; the farseer's face submesh uses a shared material and renders near-black (open) |
| action coverage | **7 units, 5–14 actions each** | walk present on all seven with real leg motion (chaos 0.07 m, eldar 0.13 m, necron 1.59 m) |
| interleaved clips | **not decoded** | `fb_run`, `fb_sprint`, `fb_melee_attack_01..03`, `fb_reload_stand`, `ragdoll` — the action library falls back to a delta clip |
| layering | **not baked** | `.hkanim` composes base + upper-body layers at runtime; we export one clip per action |
| lab page | **7 units live** | `fidelity.json` regenerated, `UNIT_ASSET_REV 20261143`, served bytes verified |

## 3. Ordered next work

1. **Interleaved clip decoder** (`hkInterleavedSkeletalAnimation`). It costs chaos and necron their
   true run and melee attacks 1–3, and every unit its `fb_reload_stand`. This is the last format gap.
2. **Tau `aim` and `fire` are static** (aim is a 2-pose clip whose poses are identical; fire has 91
   keys but 0.003 m of motion). Diagnose the pose application for those two clips.
3. **Eldar face renders near-black.** The head is textured (`farseer_head_dif` is embedded); the face
   submesh uses the shared material `standard_15`. Check its UVs against the atlas and its
   metalness/base colour.
4. **Weapons 1:1 for the remaining units**: chaos (bolt pistol / force stave), eldar (witchblade /
   spear), warboss (big shoota / choppa), lictor (its talons are part of the armour). The shipped
   weapon model is imported the same way as a head (`merge=True`).
5. **Layered animation**: decode the `.hkanim` state machine and bake the composed pose (base +
   upper-body), which is what the game actually shows.
6. **More units**: the remaining Tau troops (drones) and the other factions' loadouts, all with the
   same table-driven build.

## 4. Testing — the gate is visual

The numeric gate measures deformation from each mesh's own bind; it passed shard piles. The gate that
catches a wrong bind, a missing part or a broken animation is **looking at renders**.

```bash
# per unit: idle, fire, walk, death, and a close-up of the head and the weapon
blender -b -P tools/render_lab.py -- <lab dir> <png dir> idle:1 fire:30 walk:10 death:30
python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>
python3 tools/lab_fidelity.py --lab <lab dir>
```

Required review for every build:
1. render each unit's idle, fire, walk and death at two frames each, plus a head close-up and a weapon
   close-up;
2. **read the PNGs** and compare against `docs/evidence/dow2-stance/` — a pose that disagrees with the
   shipped game passes every numeric gate and is still wrong;
3. flag any action whose bone motion is below 2 cm (static), and any action whose motion exceeds the
   body height (exploded);
4. record the verdict in this file, not just in the report.

## 5. Commands

```bash
export DOW2_RETRIB=~/dow2-sources          # release source-v3, hash-pinned
R=$DOW2_RETRIB/sga_art

# one unit (example: guardsman, body + head + shipped weapon)
python3 tools/dow2/action_library.py \
  --loadout "$R/000_data/DATA/art/race_ig/troops/gaurdsman/animations/range_burst" \
  --motiontree "$R/000_data/DATA/art/race_ig/troops/gaurdsman/guardsman.motiontree" \
  --unit dow_ig_guardsman --out output/source_lab/actions/dow_ig_guardsman.json
blender -b -P tools/blender/dow2_import_community.py -- --id dow_ig_guardsman \
  --out output/source_lab/community --manifest output/source_lab/actions/dow_ig_guardsman.json \
  --part "$R/000_data/DATA/art/race_ig/troops_wargear/armour/ig_armour/ig_armour.model" \
  --part "$R/000_data/DATA/art/race_ig/troops_wargear/heads/cadian_trooper/cadian_trooper.model" \
  --weapon "$R/000_data/DATA/art/race_ig/troops_wargear/weapons_ranged/lasgun/lasgun.model"
```

## 6. Standing rules (learned, do not relearn)

- **Use the community importer for assembly.** Do not rebuild bone construction or pose conversion by
  hand; the recipe is in `docs/DOW2_COMMUNITY_TOOLCHAIN.md`.
- **Match bones by name against the armature's own names**, case-insensitively.
- **Never trust a numeric gate without a render.** A rigid mesh measures 0 % tearing.
- **Judge poses against the shipped game**, not from imagination.
- **A build that does not print `EXPORTED` is a failure**, whatever Blender's exit code says.
