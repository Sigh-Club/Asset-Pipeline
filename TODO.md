# Asset-pipeline — live work tracker

**Updated 2026-11-17.** This is the actionable list, and it is the honest one: it states what works,
what is partial, and what is blocked, with the measurement that decides each. Read it before touching
the DoW2 import.

Authority and detail:

- [`docs/DOW2_ANIMATION_DECODE.md`](docs/DOW2_ANIMATION_DECODE.md) — the clip format, the decoder, the
  validation, the action library, and the retarget rule.
- [`docs/HANDOFF_TURN_BASED.md`](docs/HANDOFF_TURN_BASED.md) — the self-contained handoff brief.
- [`docs/DOW2_STANCE_REFERENCE.md`](docs/DOW2_STANCE_REFERENCE.md) — how DoW2 units stand, the
  loadout rule, the part-assembly rule, and the four import rules (R1–R4) that make a build work.
- [`docs/BLENDER_MCP.md`](docs/BLENDER_MCP.md) — when to drive Blender interactively through MCP, and
  what not to use it for.
- [`docs/3D_ASSETS.md`](docs/3D_ASSETS.md) — the generated-art (img23d) path and the GLB contract.
- `PLANNING.md` — the sprite-era plan; superseded for 3D.

---

## 1. Current programme

**Copy DoW2 units 1:1 — geometry, materials, weapons, skeleton, animation — and drive them from a
turn-based combat system.**

DoW2 is an RTS; we are building a turn-based game. The deliverable is its **action library**: aim,
fire, reload, melee, grenade, ability-cast, hit, thrown and death — each with its timing and its
events, triggerable from our action system.

## 2. State, measured

| piece | state | evidence |
|---|---|---|
| body geometry | **working** | `tools/dow2/chunky_mesh.py` decodes positions, UVs and the shipped per-vertex bone indices/weights |
| unit assembly | **working** | `tools/dow2/parts.py` resolves `render_models` and de-duplicates quality tiers |
| skeleton | **working** | `tools/hkx/hkxread.py` decodes `hkSkeleton`: bones, parents, reference pose |
| rig + skinning | **working** | optimal one-to-one assignment of the shipped bone indices, source textures applied |
| **clip decode** | **working** | `hkDeltaCompressedSkeletalAnimation` decoded: frame 0 reproduces the file's own reference pose (max 5.5e-06 m / 3.4°); corpus 236/243 decoded, 0 structural failures |
| **action library** | **working** | `tools/dow2/action_library.py` + `--actions` in the builder: 6 units, 5–15 named actions each, with the shipped `.motiontree` events and times (fire burst cadence, reload foley, bodyfall) |
| materials | **diffuse only** | `_nrm`, `_spc`, `_ocl`, `_emi` and the team-colour masks are not wired |
| weapon hold | **approximate** | `WEAPON_HOLD` is authored; the 1:1 method is the shipped weapon model bound identity to `Bip01 R Weapon` |
| fidelity gate | **working** | `tools/rig_fidelity.py` measures tear / inversion / interpenetration / collapse, a displacement floor, and a rigid-plate reference; `tools/lab_fidelity.py` regenerates the lab report over every action |
| source assets for users | **working** | `tools/sources/pack_sources.py` + `fetch_sources.py`; release `source-v2` (295 files, 8.5 MB, hash-pinned) now carries each unit's `.motiontree` and `.marker`, so the event tables and attachment markers travel without the game |
| engine side (IoA repo) | **done for this work** | loadout-aware clip resolution, source-material passthrough, per-battle command log; 665 jest, Go suites green |

### What builds today

`tools/build_source_lab_all.sh` rebuilds all six lab units through the fixed chain. Each one gets its
action library from its own loadout and `.motiontree`; the guardsman and the necron (which borrows the
guardsman's clips) resolve 14–15 actions, the others 5–11 depending on what their loadout ships.

The guardsman's action set, measured: idle 7.333 s, aim 7.333 s, fire 2.000 s with 8 shots at 0.209 s,
reload 7.333 s with 6 foley events, melee 1.000 s, grenade 1.333 s, hit 0.667 s, thrown_getup 1.533 s,
death 1.067 s with a bodyfall at 0.587 s, walk/run 0.800/0.600 s with footfall markers, pinned 4.667 s.

`lab/fidelity.json` is regenerated over every action of every unit: 6 units, 15 named actions, no unit
fails. Extreme action frames are exempted from the tear band only where the shipped rigid plates
separate just as much (`reference_*` in the report); the guardsman's worst is 0.160 at a death/thrown
pose, against a rigid reference of the same order.

## 3. Ordered next work

1. **Weapon 1:1** — bind the shipped weapon model identity to `Bip01 R Weapon` and delete
   `WEAPON_HOLD`. One check first: the lasgun geometry sits at +x while the guardsman's right hand is at
   −x, so verify the mirror once.
2. **Materials 1:1** — wire `_nrm`, `_spc`, `_ocl`, `_emi` and the team-colour mask compositing.
3. **Interleaved clip decode** — `hkInterleavedSkeletalAnimation` for `fb_run`, `fb_sprint`,
   `fb_melee_attack_01..03`, `fb_reload_stand`, `ragdoll`, so the action set can use the shipped clip
   rather than an alternative.
4. **Engine consumption of the action sidecar** — the GLB carries the actions; the timing/events travel
   in `<unit>.actions.json`. The action system should read it to schedule effects and sounds.
5. **The four blocked units** — `dow_ork_warboss` (wargear lists armour plates only — add the boy
   body), `dow_necron_overlord` (not Havok packfiles; borrows the guardsman rig and clips),
   `dow_eldar_farseer` (ships no skeleton), `dow_tyranid_lictor` (borrows the carnifex loadout).
6. **Lab page check** — verify the `/units` → RIG LAB tab reads the regenerated `fidelity.json` and
   drives the named actions.

## 4. Blocked on shipped data (not code)

| unit | blocker | fix |
|---|---|---|
| `dow_ork_warboss` | its wargear lists armour **plates only**; the boy body is not in the list | add the boy body part to the assembly |
| `dow_necron_overlord` | its clips are not Havok packfiles (`magic 0x0003da78`) and its `.model` has no `FOLDSKEL` | locate its real skeleton (its markers name `rig_rleg_calf`-style bones) |
| `dow_eldar_farseer` | the farseer ships no skeleton; the build borrows the banshee's | find the farseer rig |
| `dow_tyranid_lictor` | built on the carnifex loadout | use the lictor's own loadout |

## 5. Commands (verified 2026-11-17)

```bash
# source assets: no DoW2 install needed — hash-pinned release download
python3 tools/sources/fetch_sources.py --out ~/dow2-sources
export DOW2_RETRIB=~/dow2-sources
IG=$DOW2_RETRIB/sga_art/000_data/DATA/art/race_ig

# one unit from the shipped data (parts + skeleton + textures + action library)
tools/build_source_lab.sh dow_ig_guardsman \
  "$DOW2_RETRIB/attrib-decoded/wargear/wargear/core/race_imperial_guard/armor/flak_common.txt" \
  "$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx" \
  "$IG/troops/gaurdsman/animations/range_burst" \
  ../Imperium-of-Ash/frontend/public/assets/models/weapons/lasgun.glb 1.85

# the whole lab set
tools/build_source_lab_all.sh

# the action library alone (named actions, timing, shipped events)
python3 tools/dow2/action_library.py \
  --loadout "$IG/troops/gaurdsman/animations/range_burst" \
  --motiontree "$IG/troops/gaurdsman/guardsman.motiontree" \
  --unit dow_ig_guardsman --out output/source_lab/actions/dow_ig_guardsman.json

# the decoder's self-check: frame 0 must reproduce the file's own reference pose
python3 -c "import sys; sys.path.insert(0,'tools/hkx'); from hkxread import validate_animation; \
print(validate_animation('$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx'))"

# the gate, per action and over the whole lab
python3 tools/rig_fidelity.py output/source_lab/work/dow_ig_guardsman/dow_ig_guardsman.glb \
  --clip death --frame 33
python3 tools/lab_fidelity.py --lab ../Imperium-of-Ash/frontend/public/assets/models/units/lab

# game-side gates after any engine change
cd ../Imperium-of-Ash/backend && go build ./... && go vet ./... && go test ./...
cd ../frontend && npx tsc --noEmit && npm test -- --runInBand && npm run build
cd .. && npm run guard:glb && npm run guard:assets
```

## 6. Standing rules (learned, do not relearn)

- **Transfer motion relative to the clip's own reference pose.** Each clip file carries its own bind
  pose; anchoring the retarget to the unit's rest bakes two clips' bind differences into the animation
  (measured: 12–19 % torn edges at frame 1).
- **Never trust a numeric gate without a render.** A rigid mesh measures 0 % tearing, and a metric can
  be tripped by its own sampling (assuming 24 fps on a 30 fps clip reported 4–9 % tears on an intact
  mesh).
- **Judge poses against the shipped game**, not from imagination: `docs/evidence/dow2-stance/`.
- **Assemble from the shipped wargear part list**, de-duplicating quality tiers.
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
