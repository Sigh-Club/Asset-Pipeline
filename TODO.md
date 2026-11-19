# Asset-pipeline — live work tracker

**Updated 2026-11-18 (session 3).** This is the actionable list, and it is the honest one: it states
what works, what is partial, and what is broken, with the measurement that decides each. Read it
before touching the DoW2 import.

Authority and detail:

- [`docs/DOW2_COMMUNITY_TOOLCHAIN.md`](docs/DOW2_COMMUNITY_TOOLCHAIN.md) — **the build method**:
  the community importer, its constants, the pose sequence, the pruning rules, the export flags, the
  traps.
- [`docs/DOW2_ANIMATION_DECODE.md`](docs/DOW2_ANIMATION_DECODE.md) — the clip formats (delta-compressed
  **and** interleaved) and our decoder.
- [`docs/HANDOFF_TURN_BASED.md`](docs/HANDOFF_TURN_BASED.md) — the self-contained handoff prompt.
- [`docs/DOW2_STANCE_REFERENCE.md`](docs/DOW2_STANCE_REFERENCE.md) — how DoW2 units stand and the
  import rules.
- `docs/KNOWN-ISSUES.md` — recorded defects, not masked.

---

## 1. Current programme

Copy DoW2 units 1:1 — geometry, rig, weights, materials, weapons, clips — and drive them from a
turn-based action system. DoW2 is an RTS, so the deliverable is its **action library**, not its
locomotion cycles.

## 2. State, measured (2026-11-18, session 2)

| piece | state | evidence |
|---|---|---|
| assembly | **working, community toolchain, table-driven** | `tools/dow2/build_community_units.py` builds all seven units from a table of shipped files; damage states and extra LoDs are pruned per part |
| rig | **working** | the add-on builds the armature from the model's own `FOLDSKEL` with its bone-axis adapter |
| clips | **working, both formats** | delta-compressed **and** `hkInterleavedSkeletalAnimation` (151 of 182 interleaved clips validate against their own reference pose; the 31 others are partial-track clips) |
| heads | **working** | from the ebps `animator_attachments`, chapter variants skipped |
| weapons | **working for all seven** | each unit's `default_wargear` resolved to shipped models: guardsman lasgun, necron tachyon arrow, tau plasma rifle, chaos power sword + bolt pistol, eldar witchblade + shuriken pistol, warboss kustom shoota + huge choppa, lictor talons (part of its armour) |
| materials | **working, opaque** | every unit material exports `OPAQUE` + single-sided (the add-on's alpha wiring made every material `BLEND`, which is why units were see-through and lost parts at an angle); `dow2_alphaTest` honoured as MASK where a source declares a cutout |
| action coverage | **7–21 actions per unit** | see the scorecard below; the four aim directions are new, and the Tau's aim set is static by design (its stance clip is two identical frames) |
| layering | **aim directions baked, fire/idle layers not** | the shipped single-track upper-body layers are composed onto the stance for `aim_left`/`aim_right`/`aim_up`/`aim_down` (5 units; the necron uses its shipped aim-pivot clips). The `.hkanim` is a clip container (227 embedded packfiles), so the state machine's *other* layer uses (fire over run, idle additive) are still exported as base clips |
| lab page | **10 units live** | `fidelity.json` regenerated (10 units, 132 actions, 0 FAIL), `UNIT_ASSET_REV 20261150`, dist rebuilt byte-identical to `public/` |
| playback speed | **1:1 with the shipped clip** | every action baked at its own duration on one 30 fps timeline; measured 0.000x deviation across 132 actions (`action_motion --timing-only`) |

### Per-unit scorecard

Rubric (110 points): assembly 20 · rig/weights 20 · materials 15 · weapons 15 · action coverage 20
(resolved/20, capped) · visual gate 10 · layered animation 10 (5 = aim directions composed from the
shipped layers, 3 = shipped aim-pivot clips only, 0 = no composition). A component is only scored when
it is measured — the visual gate means the renders were read against `docs/evidence/dow2-stance/`.

| unit | assembly | rig | materials | weapons | actions | visual | layering | total |
|---|---|---|---|---|---|---|---|---|
| dow_ig_guardsman | 20 | 20 | 15 | 15 | 20 | 10 | 5 | **95 %** |
| dow_eldar_farseer | 20 | 20 | 15 | 15 | 18 | 10 | 5 | **94 %** |
| dow_ork_warboss | 20 | 20 | 15 | 15 | 18 | 10 | 5 | **94 %** |
| dow_chaos_sorcerer | 20 | 20 | 15 | 15 | 17 | 10 | 5 | **93 %** |
| dow_tau_battlesuit | 20 | 20 | 15 | 15 | 15 | 10 | 5 | **91 %** |
| dow_tyranid_lictor | 20 | 20 | 15 | 15 | 13 | 10 | 5 | **89 %** |
| dow_necron_overlord | 20 | 20 | 15 | 15 | 11 | 10 | 3 | **85 %** |
| dow_tau_gun_drone | 20 | 20 | 15 | 15 | 7 | 10 | 5 | **84 %** |
| dow_tau_marker_drone | 20 | 20 | 15 | 15 | 7 | 10 | 5 | **84 %** |
| dow_tau_shield_drone | 20 | 20 | 15 | 15 | 5 | 10 | 5 | **82 %** |

Action coverage per unit (of the 20-name action set plus the four aim directions; missing names are
loadouts that ship no clip for them, which the manifest records as `not shipped`):

- guardsman 21 — 17 named actions + 4 aim directions; missing ability, leap, death_sync
- eldar 18 — missing idle_crouch, reload, ability, thrown_getup, death_sync, pinned
- warboss 18 — missing idle_crouch, reload, ability, leap, death_sync, pinned
- chaos 17 — missing idle_combat, idle_crouch, reload, grenade, leap, death_sync, pinned
- tau 15 — missing idle_combat, idle_crouch, reload, melee_01..03, ability, death_sync, pinned
- lictor 13 — missing idle_combat, aim, fire, reload, grenade, death_sync, pinned (a melee creature:
  its loadout ships no ranged clips, so it has no aim layers either)
- necron 11 — missing idle_combat, idle_crouch, reload, melee_03, grenade, ability, hit, thrown_getup,
  leap, death_sync, pinned
- tau_gun_drone 7 / tau_marker_drone 7 — turret rigs whose loadouts ship 12 clips each (`dhg_*`/`dm_*`):
  idle, fire, move, two deaths and two aim layers. No aim stance clip (the layers rotate the gun mount
  onto the idle), no melee, no reload, no crouch
- tau_shield_drone 5 — idle, ability (`sd_ability_field`), death, move. It ships no fire clip: its
  loadout is a support field

The gap to 100 % is the same two things for every unit: the game's layered animation (10 points) and
the actions their loadout genuinely does not ship.

## 3. Ordered next work

1. **The rest of the layering**: the aim directions are composed from the shipped layers now, but the
   game also layers fire over locomotion (`ub_fire_run*` over `fb_run`) and adds idle sway. Those are
   still exported as base clips. The layers and their bindings are decoded; what is missing is the
   *rule* that says which layer applies in which state, which lives in the `.motiontree` state
   machine (we read it only for event timing today).
2. **More units**: the whole Tau drone family is in (gun, marker, shield); next are other factions'
   loadouts, all through the same table (`tools/dow2/build_community_units.py`) — a drone needed only
   a table row plus its clip stems in the action library.
3. **More actions per loadout where the game ships them**: the necron (9) and tau (11) are the thin
   ones; their loadouts ship fewer clips, so this is a unit-choice question rather than a decoder gap.
4. **Ground contact per action**: measure and, where a turn-based consumer needs it, normalise the
   root height per clip. Deaths, getups and leaps legitimately go below the origin (measured: lictor
   leap 1.34 m, guardsman getup 1.42 m) because the shipped clip carries the fall.

## 4. Testing — the gate is visual

The numeric gate measures deformation from each mesh's own bind; it passed shard piles. The gate that
catches a wrong bind, a missing part or a broken animation is **looking at renders**.

```bash
# per unit: idle, fire, walk, death, and a close-up of the head and the weapon
blender -b -P tools/render_lab.py -- <lab dir> <png dir> --unit=<id> \
  idle:1 idle:60 fire:30 fire:45 walk:10 walk:20 run:10 run:20 melee:10 melee:30 death:30 death:60 \
  idle:1:head idle:1:weapon
python3 tools/dow2/action_motion.py --lab <lab dir> --static-only
python3 tools/dow2/action_motion.py --lab <lab dir> --timing-only   # playback speed vs the shipped clip
python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>
python3 tools/lab_fidelity.py --lab <lab dir>
```

Required review for every build:
1. render each unit's idle, fire, walk and death at two frames each, plus a head close-up and a weapon
   close-up;
2. **read the PNGs** and compare against `docs/evidence/dow2-stance/` — a pose that disagrees with the
   shipped game passes every numeric gate and is still wrong;
3. flag any action whose bone motion is below 2 cm (static), and any action whose motion exceeds the
   body height (usually a fall or a leap, not an explosion);
4. record the verdict in this file, not just in the report.

## 5. Commands

```bash
export DOW2_RETRIB=<unpacked DoW2 data>    # needs sga_art/ and attrib-decoded/
python3 tools/dow2/build_community_units.py --list
python3 tools/dow2/build_community_units.py --only dow_ig_guardsman
python3 tools/dow2/build_community_units.py
```

## 6. Standing rules (learned, do not relearn)

- **Use the community importer for assembly.** Do not rebuild bone construction or pose conversion by
  hand; the recipe is in `docs/DOW2_COMMUNITY_TOOLCHAIN.md`.
- **Prune states and LoDs per part** to `healthy` + the lowest LoD that part ships.
- **Materials are opaque unless `dow2_alphaTest` says otherwise.** A `BLEND` material is drawn without
  depth writes and sorts per object: that is the see-through unit and the part that vanishes at an
  angle.
- **Skip `chapter_*` blocks** — they are DLC swaps for the same slot, not extra parts.
- **Match bones by name against the armature's own names**, case-insensitively.
- **Never trust a numeric gate without a render.** A rigid mesh measures 0 % tearing.
- **Judge poses against the shipped game**, not from imagination.
- **A build that does not print `EXPORTED` is a failure**, whatever Blender's exit code says.
