# DoW Asset Import — Dawn of War models → IoA pixel/render pipeline

Import authentic Relic Dawn of War assets (SGA v2 archives) as geometry and
material sources, render them through the IoA pipeline, and/or convert to
palette-locked pixel sprites (PZ sub-pipeline variant).

Proven 2026-10-05: ork Slugga Boy (`boyz.whm`) and Shoota Boy
(`boyz_shoota.whm`) extracted, imported, textured from the game's own atlases,
rendered front-facing, and pixelised. Scripts: `tools/dow/`.

## Source archives (SGA v2, magic `_ARCHIVE` v2)

| Archive | Contents |
|---|---|
| `W40kData-Whm-Definitive.sga` | Definitive Edition models: `art\...\races\orks\troops\*.whm` (boyz = Slugga, boyz_shoota = Shoota, nobz, nob_leader, warboss, big_mek, grots, stormboyz, mega_armoured_nobz, grotbomb, warboss_tgd) + `.whe` animations |
| `W40kData-SharedTextures-Full.sga` | material atlases: `art\ebps\races\orks\texture_share\*.rsh` (`boyz_unit_page` = boyz diffuse) |
| `W40kData-Whm-High.sga` | high-quality texture variants |
| `W40kData.sga` (NOT yet in hand) | unit selection icons (pre-rendered portraits), WTP team-colour patterns |

## Steps

### 1. Extract from SGA

```python
import fs
fsh = fs.open_fs('sga://' + archive_path)   # relic-tool-sga-v2 opener
data = fsh.openbin('art/art\\ebps/.../boyz.whm').read()
```

Uses the split PyPI packages (`relic-tool-sga-v2` + `relic-tool-sga-core` +
`relic-tool-core` 2.4). The old monolith `relic-tool-sga` 2.0.1 parses v2
structure but mis-reads DowI file data — do not use it. NOTE: Definitive
archives have doubled path components (`art/art\ebps/art\ebps\...`) — a
parser/pathing artefact, harmless for reading.

### 2. WHM → OBJ — `tools/dow/whm_v4_patch.py`

Definitive WHM = RSGM chunk **version 4**; the bundled v3 reader needs shims
(all in `whm_v4_patch.py`, import it before converting):
- `RsgmChunkFactory`: accept version 4 (v3 folder layout still matches)
- tolerant `convert_many`: skip unknown folder chunks (Definitive adds `STXT`
  texture-list folders — 6+ per model)
- `MslcChunk.convert`: v4 MSLC folders have >2 children
- `MslcDataChunk.convert`: v4 reserved header `rsv0_a` is non-zero (2
  observed; v3 asserts 0) — rest of v3 body verified: bones=5, verts=581,
  vsize_id=39 → 48-byte vertices (table `{37:32, 39:48}` already covers it)
- `RsgmChunkV3.convert` / `WhmChunky.convert`: child-count asserts relaxed
  (v4 adds STXT folders the v3 counter does not know)

```python
import whm_v4_patch; whm_v4_patch.patch()
from relic.chunky.serializer import read_chunky
from relic.chunky_formats.dow.whm.whm import WhmChunky
from relic.chunky_formats.dow.whm.obj_writer import write_whm
whm = WhmChunky.convert(read_chunky(open(model_whm, 'rb')))
write_whm(out_root, whm, write_textures=False)   # .obj + .mtl + -bones.json
```

OBJ contains the full load-out as separate objects (boyz_head, boyz_legs,
boyz_slugga, boyz_big_shoota, boyz_choppa_axe, boyz_burna, helmets, spiked
pauldrons, banner...) — load-outs are part sets inside one WHM.

### 3. Atlas decode — `tools/dow/rsh_extract.py`

RSH = "Relic Chunky" container: `FOLDSHRF → FOLDTXTR → DATAHEAD {fmt,w,h,
mips} + FOLDIMAG → DATAATTR + DATADATA` (raw DXT mip chain, no DDS header).
The parser wraps DATADATA in a synthetic DDS header (ATTR fmt 8 → DXT1, else
DXT5) and decodes with Pillow. Output PNGs are named `<rsh>__<tex>_mip0.png`;
the stem matches the MTL material name 1:1. Force 8-bit RGBA — 16-bit PNGs
break Blender GPU texture upload.

### 4. Blender render — `tools/dow/blender_ork_import.py`

```bash
DOW_ATLAS_DIR=<atlas png dir> blender -b -P tools/dow/blender_ork_import.py -- \
    --obj boyz.obj --out render.png --tint "0.55,0.10,0.08" --res 512
```

- `bpy.ops.wm.obj_import`, then per material load the matching atlas PNG
  (`Closest` interpolation, `alpha_mode="NONE"`, `blend_method="OPAQUE"` —
  DXT1 1-bit alpha otherwise blanks the render; 16-bit PNGs break GPU upload)
- ortho camera auto-framed from mesh bounds, dead front (facing us)
- key/fill/rim lights, `view_transform="Standard"` (AgX washes colour and the
  pixeliser quantises the wash faithfully)
- klan tint = MULTIPLY mix node (factor 0.45) on cloth/banner parts by name
  (`boyz_legs`, `ork_flag`, `ork_flag_pole`) — full team-colour masks need
  WTP files (`relic.chunky_formats.dow.wtp` reader exists; WTP data is in
  `W40kData.sga`, pending)
- override the atlas directory with `DOW_ATLAS_DIR` (defaults to the
  Downloads review location)

### 5a. IoA full-colour render path

The OBJ imports into the standard IoA pipeline (Cycles, 384×512, PBR
materials, 8-direction renders) exactly like any parametric unit — the
authentic DoW atlases replace `paint_unit_diffuse.py` output, or keep IoA
procedural materials for the IoA art style (AGENTS.md rule 1: full colour).

### 5b. Pixel variant (PZ sub-pipeline) — `pz/pixel/`

`pz/pixel/pixelise.py --style rotbile --size 128` (box downsample, Oklab
fixed-palette quantisation, ink re-imposition, orphan merge) then
`pz/pixel/verify_pixel_asset.py` (alpha binarisation, palette compliance,
orphans, rim contrast). Style presets in `pz/pixel/styles.py`; palettes in
`pz/pixel/palette.py`.

## Gotchas

- SGA v2 DowI: use the split packages; the monolith 2.0.1 mis-reads file data.
- Definitive RSGM v4 needs the shims — without them: version-gate assertions,
  STXT KeyErrors, MSLC reserved-field assertions.
- RSH DATADATA = raw DXT mip chains without a DDS header.
- Blender `-b` output paths must be absolute when the cwd differs.
- 16-bit PNG atlases break Blender GPU texture upload.
- Slugga/Shoota/etc. are load-out part sets inside one WHM, not separate
  models — filter OBJ objects per load-out if a plain boy is wanted.

## 6. Skeleton, animation, markers (2026-10-08 decompile)

Full WHM chunk anatomy is documented in the docstring of
`tools/dow/whm_animdata.py` (RSGM → STXT/SHDR/SKEL/MSGR(MSLC)/MARK/CAMS/ANIM).
Headline facts:

- **Skeleton** (`SKEL`): per bone `name, parent idx, local pos(xyz),
  rot quat(xyzw)` — a standard 3ds Max Biped hierarchy (`bip01 pelvis …`),
  plus prop bones (`boyz_rokkit`, `ork_flag_pole`) and cloth bones
  (`bone_ork_plume_*`).
- **Animations** are embedded in the model WHM as named `ANIM` folders —
  122 clips on boyz.whm (`idle_1`, `run_1`, `melee_1`, `sync_kill_*`,
  `die_*`, per-weapon variants, and `vis_*` = mesh-visibility tracks that
  switch load-out parts). Each track: sparse keys `frame → pos(xyz)` /
  `frame → quat(xyzw)`, local to the parent bone, same convention as SKEL.
  Mesh visibility sub-tracks hide/show parts per frame.
- **Skinning**: MSLC verts are model-space bind pose; 48-byte vertex =
  `pos3f + weights3f + idx4B + normal3f + uv2f` (32-byte = no skinning).
  Weight indices are GLOBAL skeleton ids; `255` = unweighted padding.
- **Markers** (`MARK`): attachment points (muzzle, blade, sync-kill, icon)
  — `name`, optional parent-bone ref, 48-byte basis+pos transform.
- **Cameras** (`CAMS`): `army_painter_camera` etc., same 48B transform.
- **Materials** (`SHDR`): one shader per material; `CHAN` channels =
  `{index, flags, rgba tint, atlas path}` — tint `808080ff` = neutral.
  The RSH atlas is multi-page: page 0 diffuse, then glow / specular /
 normal (verified on `boyz_unit_page`); `rsh_extract.py` now suffixes
  pages _0.._3 and the Blender importer picks page 0.

### Bind-pose finding (important, empirical)

The SKEL rest pose is NOT the mesh bind in Definitive assets — skinning with
`M(f)·M(skel)⁻¹` tears limbs off. The bind that works: **the animation's own
frame 0** (`M(f)·M(f0)⁻¹`; frame 0 renders identical to the stored mesh,
later frames stay a coherent single unit). `pose_whm.py` implements this;
`--bind-rest` kept for debugging.

### Tools

```bash
# skeleton + all animations + markers + cams → JSON
python tools/dow/whm_animdata.py model.whm anims.json [name_filter …]

# skin any anim frame to OBJ (submesh names = atlas stems; feeds
# blender_ork_import.py unchanged) — the sprite-sheet workhorse:
python tools/dow/pose_whm.py model.whm anims.json run_1 20 posed.obj
#   [--bind-rest] for the (broken-on-Definitive) skel-rest bind
```

Verified: rest-pose skinning is exact to 1e-7; `run_1` frames render as a
coherent textured ork (see `output/` smoke runs). Frame rate: key frames are
integer indices; 30 fps is the working assumption for clip length.

### Team colour (WTP) — `tools/dow/wtp_tint.py`

- `<atlas>_default.wtp` lives beside the RSH in
  `W40kData-SharedTextures-Definitive.sga` under
  `art\ebps\<race>\texture_share\`. TPAT = INFO dims + IMAG (default atlas) +
  PTLD per-layer masks + PTBD badge uv-rect.
- PTLD mask = raw W×H **single-byte soft blend weight** per pixel
  (Primary/Secondary/Trim/Weapon/Eyes/Dirt), UV-aligned to the atlas, not
  row-flipped. Values are soft (anti-aliased edges), not binary.
- `.teamcolour` lua files (W40kData.sga `art\team_colours\<race>\`) give
  per-layer RGB + badge/banner names; `teamcolourdefaults.lua` maps race →
  default scheme (orks = Evil Sunz).
- Blend: `out = diff·(1−m) + diff·colour·m` (multiplicative tint inside the
  mask — the classic DoW team shader).
- Badge/banner: PTBD/PTBN give the uv rect on the atlas where the race badge
  PNG (also in W40kData.sga) is stamped.

### Replication recipe (our own assets, DoW conventions)

1. One skinned mesh per body, 3ds-Max-Biped-style bone set; rest pose stored
   in SKEL, all animation clips embedded in the model file as named tracks
   (pos+quat, sparse keys, local space).
2. Vertex format 48B with 3 weights + 4 indices; static props 32B no skin.
3. Texture: one diffuse atlas per material + glow/spec/normal pages; team
   areas tinted via soft grayscale masks + per-layer RGB; badge uv-rect.
4. Attachments via named markers bound to bones; load-outs switched by
   visibility tracks (`vis_*`) — no separate meshes per variant.

### GOG installer extraction (full source archives)

`innoextract` on the setup exe: the `-I '*.sga'` glob does NOT match (its
path matcher is per-component) — extract everything
(`innoextract -s -m -d OUT setup*.exe`, ~20 GB) and take the `W40k/ DX?P2/
DX?P3/ WXP/` SGA trees. The `.bin` data slices must sit next to the exe.
Full set now at `/run/media/talzanar/games/dow-definitive/` (W40kData.sga
included → unit selection icons in `art\ui\...ingame\*_icons`, WTPs, badges).

### Blender addon PIL breakage (system-upgrade collateral)

`~/.config/blender/5.1/scripts/addons/modules/PIL` needs its bundled
`PIL.libs/*` beside it; if missing, copy from
`~/.local/lib/python3.13/site-packages/pillow.libs/`. Symptom:
`ImportError: libtiff-….so` inside blender, which kills `import os` in
scripts that import PIL first.

## 7. Retarget bridge — our assets playing DoW animations (2026-10-08)

The pipeline for original characters at DoW motion quality:

1. **Bind to `bip01` names.** Author/parametrically-build the mesh bound to
   the DoW bone set (rigid per part is authentic — DoW props are single-bone;
   add weights later for cloth). `mannequin.py` generates the proof rig
   (parts JSON: name/bone/verts/tris) directly from a whm_animdata skeleton.
2. **`pose_rig.py parts.json rig.json ANIM FRAME out.obj`** — skins our parts
   with any clip: `v' = Σ w M(f) M(bind)⁻¹ v`, bind = rig rest. Same math as
   pose_whm, generalised to arbitrary bound meshes (per-part "weights" list
   for smooth skinning).
3. **Keys are NORMALISED 0..1** (N = the ANIM frames field, float keys
   1/N apart). `pose_whm.sample(anim, frame)` wraps/interpolates: pos lerp,
 quat slerp, and `pose_overrides(anim, u)` takes u∈[0,1] directly. Frame
   N-1 = end; loops via modulo. Earlier int-truncation of keys collapsed
   49-key runs to 2 — always sample, never truncate.
4. Result: the whole 122-clip library (incl. sync-kills, per-weapon aim
   overlays) plays on any conforming mesh; render posed OBJs through
   `blender_ork_import.py` → 8-dir/style post (`pz/pixel/`, `hd` preset for
   high-detail pixel).

Exemplars: `tools/dow/mannequin.py` (capsule mannequin, rigid-bound) — its
run cycle renders coherent; `output/dow_decompile_smoke/`.

### Pose-fidelity resolution (same session, later)

The arm-detachment quirk is the **stale flag**: ~24/31 bones per clip are
marked stale and their keys are placeholders — applying them detaches limbs.
`--respect-stale` (pose_whm/pose_rig) skips stale bones to rest: aim/idle
render PERFECTLY (verified textured). Run cycles: legs are stale-flagged in
run clips, so respect-stable keeps them neutral — the stride likely lives in
the engine's locomotion layering; open question for sprite-quality runs
(candidates: per-clip layering, DXP shared anims, or stale semantics
variation). Evidence trail in git; next session starts here.
