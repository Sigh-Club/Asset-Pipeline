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
