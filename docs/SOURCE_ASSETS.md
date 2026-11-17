# Source assets — what the pipeline reads from Dawn of War II, and how to get it without the game

> Audience: a developer picking this repo up. Read this before running any `tools/build_source_lab*`
> command.

The DoW2 import reads the **shipped game's own files**. That is the whole point of the approach: a DoW2
body is authored geometry with a shipped rig, skin weights, materials and animation, so importing it
beats generating an approximation of it. It also means the tools need those files.

You do **not** need Dawn of War II installed. The exact subset the pipeline reads is packaged and
published as a release asset, and this repo can build every unit in the lab from it.

## Get the sources

```bash
python3 tools/sources/fetch_sources.py --out ~/dow2-sources
export DOW2_RETRIB=~/dow2-sources
tools/build_source_lab_all.sh
```

The fetcher verifies the archive's sha256 before unpacking and prints the `DOW2_RETRIB` to export. To
point at your own copy of the game's extracted data instead, set `DOW2_RETRIB` (and optionally
`DOW2_ART`) to that tree and skip the fetcher.

## What the package contains

`dow2-unit-sources-v1` — **285 files, 19.2 MB uncompressed, 8.4 MB compressed**, one archive per
release tag (`source-v1`). Contents, exactly:

| kind | what it is | why the pipeline needs it |
|---|---|---|
| `attrib-decoded/wargear/.../*.txt` | the wargear blueprints | they carry `render_models`, the authoritative list of a unit's parts (armour + head + accessories) |
| `sga_art/.../troops_wargear/**/*.model` | body, head and accessory geometry | decoded by `tools/dow2/chunky_mesh.py` — positions, UVs and the per-vertex bone indices/weights |
| `sga_art/.../troops_wargear/**/*_dif.dds` | the shipped diffuse textures | converted to PNG by `tools/dow2/dds_to_png.py` and applied as the unit's material |
| `sga_art/.../troops/*/animations/<loadout>/*.hkx` | the shipped clip files | the skeleton (`hkSkeleton`) and, once the decoder lands, the animation tracks |
| `MANIFEST.json` | path, size and sha256 for every file | verify a download and reproduce the pack |

Units covered: `dow_ig_guardsman`, `dow_chaos_sorcerer`, `dow_eldar_farseer`, `dow_ork_warboss`,
`dow_tyranid_lictor`, `dow_necron_overlord` — one per faction, the same table as
`tools/build_source_lab_all.sh`.

## Rebuilding the package

If you add a unit, add its row to `DEFAULT_UNITS` in `tools/sources/pack_sources.py` and re-pack:

```bash
python3 tools/sources/pack_sources.py --out output/source_pack
# prints the archive and its sha256; publish it as a new release tag and update
# DEFAULT_URL / DEFAULT_SHA in tools/sources/fetch_sources.py
```

The packer collects only what the build reads — it resolves each unit's `render_models` list, its
textures, and its loadout's clips — so the archive stays small instead of copying the whole 6 GB art
tree.

## Licensing and provenance — read this

The packaged files are **Relic's**, not ours:

- they are used as **source data for import**, not as our authored art;
- the pipeline re-authors what ships — palette, materials, part selection, silhouette amendments — so
  a shipped unit is derived, not copied wholesale;
- the provenance of every asset is recorded, and a clip keeps its shipped name (`fb_idle_stand_01`,
  never renamed to `idle`) so it can always be traced back to the file it came from.

This is the same posture already recorded in the game repo's known-issues for the DoW2 prop and body
imports. If the project ever needs to ship without Relic's files, the archived inputs make that a
re-export question rather than a re-authoring one.

## Why the archive is in a release, not in git

The repo already carries a large history; an 8.4 MB binary that changes whenever the unit table changes
belongs to a release, not to every clone. `fetch_sources.py` pins the hash, so the download is
verifiable and reproducible.
