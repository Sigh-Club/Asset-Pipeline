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

- **Geometry, UVs, shipped skin weights**: `tools/dow2/chunky_mesh.py` decodes positions, UVs and the
  per-vertex bone indices/weights from `.model` files.
- **Unit assembly**: `tools/dow2/parts.py` resolves the shipped `render_models` part list (armour + head
  + accessories) and de-duplicates quality tiers (`ig_armour`/`ig_armour_epic` are one body;
  `ig_armour_common_a/b/c` are distinct).
- **Skeleton**: `tools/hkx/hkxread.py` decodes `hkSkeleton` (bones, parents, reference pose).
- **Rig + skinning**: `tools/blender/dow2_build_unit.py` builds a unit from the shipped data. The skin
  indices are resolved as an **optimal one-to-one assignment** (Hungarian) because the stream is a
  bijection onto bones; the skeleton is **aligned to the mesh** before matching (they are in different
  spaces: armour 2.39 m vs skeleton 2.54 m).
- **Materials**: `tools/dow2/dds_to_png.py` converts the shipped `_dif.dds`; the material name resolves
  to the shipped texture (`relic.material.<stem>` → `<stem>_dif`). Diffuse only so far.
- **Fidelity gate**: `tools/rig_fidelity.py` measures tear / inverted triangles / real
  triangle-triangle interpenetration / collapse **and fails a mesh that does not move**. Use it on
  every build.
- **Source packaging**: `tools/sources/pack_sources.py` + `fetch_sources.py`; the pipeline runs with no
  DoW2 install.
- **Engine side (IoA repo)**: loadout-aware clip resolution (`frontend/src/three/unitLoadouts.ts`),
  source-material passthrough (`UnitModelEntry.sourceMaterials`), per-battle command log
  (`GameState.CommandLog`). 665 jest tests, Go suites green.

### What is working, measured

`tools/build_source_lab_all.sh` builds six source units, one per faction. Two are **correct** and are
the reference for "done": `dow_ig_guardsman` and `dow_chaos_sorcerer` — complete, textured, in a real
DoW2 idle, `rig_fidelity.py` → PASS at 0.000 on every metric.

### The critical path — decode the animation tracks

**This is the whole remaining problem.** Each shipped clip file carries a skeleton whose *reference
pose is that clip's pose*, plus delta-compressed animation tracks. We currently use the reference pose,
so a unit is exact only for the clip it was rigged from.

Measured, same body: rigging on `guardsman.hkx` and applying `fb_idle_stand_01` gives **every bone a
~180° delta** — a frame difference, not a pose — and **23 % torn edges**; rigging on
`fb_idle_stand_01.hkx` itself gives **0.000 torn / 0.000 inverted**.

The files declare the answer themselves (`__classnames__` / `__types__` of
`race_ig/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx`):

```
hkSkeletalAnimation            type, duration, numberOfTracks, extractedMotion, annotationTracks
hkAnimationBinding             (track -> bone map; present in __classnames__)
hkDeltaCompressedSkeletalAnimation
                               numberOfPoses, blockSize, qFormat, quantizedDataIdx/Size,
                               staticMaskIdx/Size, staticDOFsIdx/Size, totalBlockSize,
                               lastBlockSize, dataBuffer
hkDeltaCompressedSkeletalAnimationQuantizationFormat
                               maxBitWidth, preserved, numD, offsetIdx, scaleIdx, bitWidthIdx
```

Located so far: the animation header sits at **`__data__` offset 5320** in that file — type `2`
(`HK_DELTA_COMPRESSED_ANIMATION`), duration `7.333` s, `numberOfTracks` 46 (= the skeleton's bone
count). The delta fields begin **24 bytes after the header** (`numberOfPoses` 221, `blockSize` 8 →
implied 30.1 fps, self-consistent); `qFormat` reads 264, which is an **offset into the data section**,
not an object index. The last four fields (`totalBlockSize`, `lastBlockSize`, `dataBuffer`) read
plausibly only if the struct tail holds pointers/`hkArray`s, so the widths there still need pinning.

Two known blockers:

1. `hkxread.type_table()` is **misaligned by 2 bytes** — it returns names like `ationBinding` for
   `hkAnimationBinding` and only 4 bogus types. In `__types__` the first type name `hkxEnvironment`
   begins at payload offset **48**, so the per-type record header is 48 bytes; fix the reader and the
   member offsets come from the file instead of from guesswork.
2. Then decode one block and **validate frame 0 against the file's own `hkSkeleton.referencePose`** —
   a self-checking target a wrong quantisation layout cannot fake.

### Ordered remaining work

1. **Track decoder** (`tools/hkx/hkxread.py`): fix the type table, pin the struct tail, decode a block,
   validate frame 0 == `referencePose`, then all frames for all 46 bones. Test file:
   `fb_idle_stand_01.hkx`; then a moving clip (`fb_run`, `fb_fire_stand`).
2. **Action library**: for each action clip, sample the frames an action needs (the fire frame from the
   `hkAnnotationTrack` events, reload midpoint, leap apex) and export **named actions with their events**
   on the one canonical rig. Turn-based combat needs a pose/frames + timing + event per action, not a
   state machine.
3. **Weapon 1:1**: the shipped weapon geometry is authored **in character space at the hand** (lasgun
   bbox x 0.48–1.06, y −0.21–1.67). Bind the shipped weapon model **identity** to `Bip01 R Weapon` and
   delete the authored `WEAPON_HOLD` table. One check first: the lasgun sits at **+x** while the
   guardsman's right hand is at **−x**, so verify the mirror once before trusting it.
4. **Materials 1:1**: wire `_nrm`, `_spc`, `_ocl`, `_emi` and the team-colour mask compositing.
5. **Four blocked units** (data hunts, not rig work): `dow_ork_warboss` (wargear lists armour plates
   only — add the boy body), `dow_necron_overlord` (its clips are not Havok packfiles, `magic
   0x0003da78`, and its `.model` has no `FOLDSKEL`; its markers name `rig_rleg_calf`-style bones),
   `dow_eldar_farseer` (ships no skeleton), `dow_tyranid_lictor` (borrows the carnifex loadout).
6. **Rebuild the lab** (`Imperium-of-Ash/frontend/public/assets/models/units/lab/`) through the fixed
   chain, regenerate `lab/fidelity.json`, and verify the `/units` → RIG LAB tab.

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

tools/build_source_lab_all.sh          # six units; table inside names each unit's gaps
python3 tools/rig_fidelity.py output/source_lab/work/dow_ig_guardsman/dow_ig_guardsman.glb \
  --clip fb_idle_stand_01               # PASS at 0.000 on every metric today

python3 -c "import sys; sys.path.insert(0,'tools/hkx'); from hkxread import decode_report; \
decode_report('$IG/troops/gaurdsman/animations/range_burst/fb_idle_stand_01.hkx')"

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

The models were never the problem and neither was Blender: we have been reading the **reference pose**
out of files that carry **animation tracks**, and decoding those tracks is the difference between
"idle works" and "the full DoW2 action set, 1:1, driven by our turn-based action system".
