# HANDOFF — turn-based action library from DoW2 source assets

Paste the block below into a fresh session. It is self-contained.

---

## PROMPT

You are continuing work in `/run/media/talzanar/games/Projects/IoA`. Read this whole prompt before
touching anything, then read `asset-pipeline/TODO.md`,
`asset-pipeline/docs/DOW2_COMMUNITY_TOOLCHAIN.md` and `asset-pipeline/docs/DOW2_ANIMATION_DECODE.md`.
Work in the direction set here; do not restart the research.

### Goal

Turn **Dawn of War II's own models, rigs, materials, weapons and animations** into assets for a
**turn-based** tactical game. DoW2 is an RTS, so we do not want its locomotion cycles: we want its
**action library** — aim, fire, reload, melee, grenade, leap, throw, ability-cast, hit, death — each
with its timing and its events, triggerable from our action system. Copy from the shipped game 1:1
wherever it ships something; invent only where it does not.

### Repos and sources of truth

| what | where |
|---|---|
| asset pipeline (this work) | `/run/media/talzanar/games/Projects/IoA/asset-pipeline` — `origin` = `Talzanar/Asset-pipeline`, `sighclub` = `Sigh-Club/Asset-Pipeline` (byte-identical; push both) |
| game repo | `/run/media/talzanar/games/Projects/IoA/Imperium-of-Ash` |
| DoW2 extracted data | `/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/` |
| source assets without the game | `python3 asset-pipeline/tools/sources/fetch_sources.py --out ~/dow2-sources` → release `source-v3`, 297 files |
| community tool | `~/.config/blender/5.1/scripts/addons/dow2_tools` (dow2-blender v0.3.3, Santos Tools 2 lineage, the Elite mod tooling) |
| live tracker | `asset-pipeline/TODO.md` |

Environment: `blender` 5.1 on PATH, `go` at `/usr/local/go/bin`. Never use `ollama_web_search` /
`ollama_web_fetch`; use `websearch`, `webfetch`, `stealth-fetch` (ModDB is Cloudflare-protected) or
curl the primary source.

### What is already done — do not redo

- **Assembly** uses the community importer (`tools/blender/dow2_import_community.py`): the add-on
  builds the armature from the model's own `FOLDSKEL`, applies its bone-axis adapter, binds the
  shipped weights and resolves materials. Body, head (`ebps animator_attachments`) and shipped weapon
  are merged onto one armature.
- **Pose application** is the add-on's own sequence: `dx_to_blender(track local)` → world → `rest^-1 @
  (parent^-1 @ world)` → adapter conjugation → keyframe. Export uses
  `export_optimize_animation_size=False`.
- **Clip decode** (`tools/hkx/hkxread.py`): packfile, type table, fixups, delta-compressed tracks,
  annotation events; frame 0 reproduces each file's own reference pose to 1e-5 m.
- **Action library** (`tools/dow2/action_library.py`): named actions with the shipped timed events
  from the unit's `.motiontree`.
- **Seven lab units build and animate**: guardsman (14 actions), chaos sorcerer (10), eldar farseer
  (11), ork warboss (11), tyranid lictor (10), necron overlord (7), tau battlesuit (11). All have a
  walk with real leg motion.
- **Gates**: `tools/rig_fidelity.py`, `tools/lab_fidelity.py` (regenerates `lab/fidelity.json`),
  `tools/render_lab.py` (renders every unit).
- **Source packaging**: `tools/sources/pack_sources.py` + `fetch_sources.py`, release `source-v3`.

### Ordered remaining work

1. **Interleaved clip decoder** (`hkInterleavedSkeletalAnimation`): `fb_run`, `fb_sprint`,
   `fb_melee_attack_01..03`, `fb_reload_stand`, `ragdoll` are not decoded, which costs chaos and
   necron their true run and melee attacks 1–3. The last format gap.
2. **Tau `aim` and `fire` are static**: aim is a 2-pose clip whose poses are identical; fire has 91
   keys but 0.003 m of motion. Diagnose the pose application for those clips.
3. **Eldar face renders near-black**: the head is textured (`farseer_head_dif` is embedded) and the
   face submesh uses the shared material `standard_15`. Check its UVs against the atlas and its
   metalness/base colour.
4. **Weapons 1:1 for chaos, eldar, warboss** (bolt pistol/stave, witchblade/spear, big shoota/choppa).
   Import the shipped weapon model as an extra `--part`, exactly like a head.
5. **Layered animation**: decode the `.hkanim` state machine and bake the composed pose (base +
   upper-body layers), which is what the game actually shows.
6. **More units**: the remaining Tau troops (drones) and other factions' loadouts, same table-driven
   build.

### Testing — visual first, numeric second

The numeric gate measures deformation from each mesh's own bind and has passed shard piles; it cannot
catch a wrong bind, a missing part or a broken animation. **Renders are the gate.**

For every build:
1. render each unit's **idle, fire, walk and death at two frames each**, plus a **head close-up** and
   a **weapon close-up**;
2. **read the PNGs** (the `read` tool renders them) and compare against
   `asset-pipeline/docs/evidence/dow2-stance/` — a pose that disagrees with the shipped game passes
   every numeric gate and is still wrong;
3. flag any action whose bone motion is under 2 cm (static) or over the body height (exploded);
4. record the verdict in `TODO.md`, not only in the report.

Useful screening command (motion per action, per unit):

```bash
python3 - <<'EOF'
import sys, numpy as np
sys.path.insert(0,'tools')
import rig_fidelity as R
from pathlib import Path
for g in sorted(Path('<lab dir>').glob('*.glb')):
    js,binc=R.load_glb(g); j=js['skins'][0]['joints']
    out=[]
    for a in js['animations']:
        t=R.accessor(js,binc,a['samplers'][0]['input']).ravel()
        base=R.node_worlds(js,R.sample_clip(js,binc,a['name'],t[0]))
        w=R.node_worlds(js,R.sample_clip(js,binc,a['name'],t[int((len(t)-1)*0.75)]))
        out.append((a['name'], round(float(max(np.linalg.norm(base[k][:3,3]-w[k][:3,3]) for k in j)),3)))
    print(g.stem, dict(out))
EOF
```

### Commands

```bash
cd /run/media/talzanar/games/Projects/IoA/asset-pipeline
export DOW2_RETRIB=~/dow2-sources
R=$DOW2_RETRIB/sga_art

# action manifest for a unit
python3 tools/dow2/action_library.py --loadout "<loadout dir>" \
  --motiontree "<unit>.motiontree" --unit <unit> --out output/source_lab/actions/<unit>.json

# build it (body, head, weapon)
blender -b -P tools/blender/dow2_import_community.py -- --id <unit> \
  --out output/source_lab/community --manifest output/source_lab/actions/<unit>.json \
  --part <body.model> [--part <head.model>] [--weapon <weapon.model>]

# visual gate
blender -b -P tools/render_lab.py -- output/source_lab/community /tmp/renders idle:1 fire:30 walk:10 death:30

# deformation gate + lab report
python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>
python3 tools/lab_fidelity.py --lab ../Imperium-of-Ash/frontend/public/assets/models/units/lab

# game-side gates after any engine change
cd ../Imperium-of-Ash/backend && go build ./... && go vet ./... && go test ./...
cd ../frontend && npx tsc --noEmit && npm test -- --runInBand && npm run build
cd .. && npm run guard:glb && npm run guard:assets
```

### Rules (each one is a failure we paid for)

1. **Copy from the shipped game; never invent.** Use the community importer for assembly and its
   pose sequence for animation; do not rebuild either by hand.
2. **Match bones by name against the armature's own names**, case-insensitively — mapping through our
   canonical vocabulary finds nothing and exports a constant pose.
3. **Judge poses against the shipped game**, not from imagination: `docs/evidence/dow2-stance/`.
4. **Never trust a numeric gate without a render.**
5. **A build that does not print `EXPORTED` is a failure**, whatever Blender's exit code says.
6. **Verify the source before asserting a cause.** Cite the file and the command.
7. **Never take a shortcut for context-window reasons.** Finish and certify the current task; the user
   decides when a session ends.
8. **Push to both remotes** and keep them byte-identical; `TODO.md` must state the real status.

### The one-line summary

The models, rigs, weights, materials, heads, weapons and clips are imported 1:1 with the community
toolchain and verified by rendering; what remains is the interleaved clip format, two broken Tau
actions, one dark eldar material, four missing weapons, and the game's layered animation.
