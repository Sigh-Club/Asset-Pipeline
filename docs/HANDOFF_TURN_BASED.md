# HANDOFF — turn-based action library from DoW2 source assets

Paste the block below into a fresh session. It is self-contained.

---

## PROMPT

You are continuing work in `/run/media/talzanar/games/Projects/IoA`. Read this whole prompt before
touching anything, then read `asset-pipeline/TODO.md` and the docs it links. Work in the direction set
here; do not restart the research.

### Goal

Turn **Dawn of War II's own models, rigs, materials, weapons and animations** into assets suitable for a
**turn-based** tactical game. DoW2 is an RTS, so we do **not** want its locomotion cycles: we want its
**action library** — aim, fire, reload, melee, grenade, leap, throw, ability-cast, hit, death — each with
its **timing and its events**, triggerable on demand from our action system. Copy from the shipped game
1:1 wherever the game ships something; invent only where it does not.

### Repos and sources of truth

| what | where |
|---|---|
| asset pipeline (this work) | `/run/media/talzanar/games/Projects/IoA/asset-pipeline` — remote `origin` = `Talzanar/Asset-pipeline`, `sighclub` = `Sigh-Club/Asset-Pipeline` (kept **byte-identical**; push both) |
| game repo | `/run/media/talzanar/games/Projects/IoA/Imperium-of-Ash` |
| DoW2 extracted data | `/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/` (`sga_art/`, `attrib-decoded/`, 126,860 decompiled functions) |
| **source assets without the game** | `python3 asset-pipeline/tools/sources/fetch_sources.py --out ~/dow2-sources` → release `source-v1` on Sigh-Club, 285 files, sha256 `5a5955df60fc25effbc8db2a36255bb67e32cd18b1e27c69a1f6d6e538a3bc3c` |
| live tracker | `asset-pipeline/TODO.md` (tracked in git; it is the honest status) |
| rules for this work | `asset-pipeline/docs/DOW2_STANCE_REFERENCE.md` §R1–R4, `docs/DOW2_ANIMATION_DECODE.md`, `docs/BLENDER_MCP.md`, `asset-pipeline/AGENTS.md` (G1–G7) |

Environment: `blender` 5.1 on PATH, `go` at `/usr/local/go/bin`. **Never** use `ollama_web_search` /
`ollama_web_fetch` (metered); use `websearch`, `webfetch`, `stealth-fetch`, or curl the primary source.

### What is already done — do not redo

- **Geometry, UVs, shipped skin weights**: `tools/dow2/chunky_mesh.py`.
- **Unit assembly**: `tools/dow2/parts.py` resolves the shipped `render_models` part list and
  de-duplicates quality tiers.
- **Skeleton**: `tools/hkx/hkxread.py` decodes `hkSkeleton` (bones, parents, reference pose).
- **Rig + skinning**: `tools/blender/dow2_build_unit.py`; skin indices resolved as an optimal
  one-to-one assignment, skeleton aligned to the mesh first.
- **Clip decode — SOLVED**: `hkDeltaCompressedSkeletalAnimation` is decoded from the file's own type
  table and fixups. Validation is self-checking: frame 0 reproduces that file's `referencePose`
  (measured max 5.5e-06 m / 3.4°). Corpus: 236/243 clips decoded, 0 structural failures. See
  `docs/DOW2_ANIMATION_DECODE.md`.
- **Action library**: `tools/dow2/action_library.py` emits named actions with the shipped timing and
  the shipped events from the unit's `.motiontree` (`DATAEVNT` clip→(time,event) + `DATAACTN`
  definitions). `tools/build_source_lab.sh` feeds it to the builder, which keys the real tracks as
  glTF actions and writes `<unit>.actions.json` beside the GLB.
- **Retarget rule**: motion must be relative to the clip's own reference pose
  (`W(frame) @ inv(W(reference of the same clip))`). Anchoring to the unit's rest bakes two clips' bind
  poses together and tears the mesh (12–19 % at frame 1).
- **Fidelity gate**: `tools/rig_fidelity.py` (tear / inversion / interpenetration / collapse /
  displacement floor / rigid-plate reference) and `tools/lab_fidelity.py` (worst keyframe of every
  action, regenerates `lab/fidelity.json`).
- **Source packaging**: `tools/sources/pack_sources.py` + `fetch_sources.py`; release `source-v2`
  (295 files, sha256 `d905e64d612f216a5c995f4f76fc42cf3a20f0cf3b8038dbb68fac017b3458aa`) carries the
  clips, textures, wargear lists, `.motiontree` and `.marker` files.
- **Engine side (IoA repo)**: loadout-aware clip resolution, source-material passthrough, per-battle
  command log; 665 jest, Go suites green.

### Ordered remaining work

1. **Weapon 1:1**: bind the shipped weapon model identity to `Bip01 R Weapon` and delete
   `WEAPON_HOLD`. Check the mirror once (lasgun at +x, the right hand at −x).
2. **Materials 1:1**: `_nrm`, `_spc`, `_ocl`, `_emi` and team-colour mask compositing.
3. **Interleaved clips**: `hkInterleavedSkeletalAnimation` for `fb_run`, `fb_sprint`,
   `fb_melee_attack_01..03`, `fb_reload_stand`, `ragdoll` (varies by unit).
4. **Engine side**: read `<unit>.actions.json` to schedule an action's effect and its events.
5. **Four blocked units** (data hunts): ork warboss (add the boy body), necron overlord (not Havok
   packfiles; borrows the guardsman rig), eldar farseer (no skeleton), tyranid lictor (carnifex
   loadout).
6. **Lab page check**: `/units` → RIG LAB reads the regenerated `fidelity.json` and drives the named
   actions.

### Commands (all verified this session)

```bash
cd /run/media/talzanar/games/Projects/IoA/asset-pipeline
python3 tools/sources/fetch_sources.py --out ~/dow2-sources
export DOW2_RETRIB=~/dow2-sources
IG=$DOW2_RETRIB/sga_art/000_data/DATA/art/race_ig

tools/build_source_lab.sh dow_ig_guardsman \
  "$DOW2_RETRIB/attrib-decoded/wargear/wargear/core/race_imperial_guard/armor/flak_common.txt" \
  "$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx" \
  "$IG/troops/gaurdsman/animations/range_burst" \
  ../Imperium-of-Ash/frontend/public/assets/models/weapons/lasgun.glb 1.85

tools/build_source_lab_all.sh          # six units, each with its own action library
python3 tools/rig_fidelity.py output/source_lab/work/dow_ig_guardsman/dow_ig_guardsman.glb \
  --clip idle --frame 1                 # PASS; per-action gate, every keyframe

python3 -c "import sys; sys.path.insert(0,'tools/hkx'); from hkxread import validate_animation; \
print(validate_animation('$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx'))"

python3 tools/dow2/action_library.py --loadout "$IG/troops/gaurdsman/animations/range_burst" \
  --motiontree "$IG/troops/gaurdsman/guardsman.motiontree" --unit dow_ig_guardsman \
  --out output/source_lab/actions/dow_ig_guardsman.json

python3 tools/lab_fidelity.py --lab ../Imperium-of-Ash/frontend/public/assets/models/units/lab

# game-side gates after any engine change
cd ../Imperium-of-Ash/backend && go build ./... && go vet ./... && go test ./...
cd ../frontend && npx tsc --noEmit && npm test -- --runInBand && npm run build
cd .. && npm run guard:glb && npm run guard:assets
```

### Blender MCP — investigation only

Installed and wired: addon `~/.config/blender/5.1/scripts/addons/blender_mcp.py` (v1.30.0), server
registered in `~/.pi/agent/mcp-servers.json` as `blender`, bridge self-test
`node ~/.pi/agent/extensions/mcp-bridge/selftest.mjs --server blender` lists 10 tools including
`get_scene_info`, `execute_blender_code` and **`look`** (scene → image).

**Use it to find causes, not to produce assets.** It refuses `blender -b` (no event loop → commands
never execute), so the host is GUI-mode under a virtual display:

```bash
# /tmp/mcp_serve.py: enable the addon, start the server, then RETURN (never block) and let a timer quit
setsid xvfb-run -a blender --python /tmp/mcp_serve.py -- --secs 1800 </dev/null >/tmp/blender_mcp.log 2>&1 &
```

Traps, all hit this session: a `while True: sleep()` host deadlocks every call; the addon's socket can
stop after a command raises (restart the host, do not retry); `bpy.ops.import_scene.gltf` fails under
MCP with `'Context' object has no attribute 'object'` unless an object is created and made active
first; stdout is buffered, so write state to a file; an unrelated `blender_dow`/PIL `libtiff` ImportError
appears in every log and is harmless. Details: `asset-pipeline/docs/BLENDER_MCP.md`.

### Rules (each one is a failure we paid for)

1. **Copy from the shipped game; never invent.** Invented values — a T-pose template, distance weights,
   authored weapon angles, procedural clips — each produced a defect that took days to trace.
2. **Rig a unit with the skeleton from the same file its clips come from.** Mixing files gives a
   constant ~180° frame difference and tears the mesh.
3. **Assemble from the shipped wargear part list**, de-duplicating quality tiers only.
4. **Gate with `rig_fidelity.py` and then look at a render.** A rigid mesh measures 0 % tearing, and a
   mis-scaled Carnifex passed a green audit. `look` is the tool for this.
5. **Judge poses against the shipped game**, not from imagination: `docs/evidence/dow2-stance/`
   (DoW2 units idle hunched, wide-legged, weapon low in one hand; two-handed aim at chest with bent
   elbows).
6. **Verify the source before asserting a cause.** Cite the file and the command. Several confident
   diagnoses this session were wrong and one measurement each time showed it.
7. **Never take a shortcut for context-window reasons.** Finish and certify the current task; the user
   decides when a session ends.
8. **Push to both remotes** (`origin` and `sighclub`) and keep them byte-identical; the Sigh-Club copy is
   what gets shared with a human. `TODO.md` is tracked and must state the real status.

### The one-line summary

The tracks decode and the action library exists: the shipped clips play on one rig, with the shipped
timings and events, which is the difference between "idle works" and "the full DoW2 action set, 1:1,
driven by our turn-based action system".
