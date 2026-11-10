---
name: asset-pipeline
description: Guides AI agents working on IoA's multi-asset-type 3D-to-2D sprite generation pipeline. Covers characters, tiles, UI elements, materials, quality gates, and code standards for Imperium of Ash grimdark tactical game assets.
---

# Asset-Pipeline Skill

## 3D assets first (2026-11-09)

The combat loop moved to **Three.js with skinned GLB units**. If the task is 3D
art — unit models, materials, environments — read
`docs/3D_ASSETS.md` in this repo and load the global `ioa-3d-assets` skill. The
rules in the sections below (8 directions, LANCZOS, palette lock, atlas packing)
apply to the **2D sprite** path only.

Model training (optional, not yet active) is covered by
`docs/GENERATION_TRAINING_RESEARCH.md` and the global `generative-training` skill:
small Apache bases only, image/material LoRAs only, and a manufactured dataset.

New in this repo: `tools/glb_contract.py` (acceptance gate),
`tools/blender/uv_prepare.py`, `tools/blender/preview_unit_materials.py`,
`tools/pbr/build_material_manifest.py`, `tools/pbr/derive_maps.py`,
`tools/pbr/build_blender_library.py`, `tools/gpu_policy.py`,
`tools/blender_run.sh` (VRAM-guarded launcher), and the
`assets/materials/grimdark_scifi/` library.

This skill enforces quality standards, code conventions, and project rules for the Imperium of Ash automated asset generation pipeline. Load this whenever working on pipeline scripts, Blender generators, render tools, UI elements, or game asset output.

---

## Project Identity

**Repository**: `asset-pipeline` (in `/run/media/talzanar/games/Projects/IoA/asset-pipeline/`)
**Purpose**: Multi-asset-type generation pipeline for Imperium of Ash — characters, tiles, UI, props — all grimdark isometric.
**Method**: Automated sub-pipelines routed through a unified CLI. Batch-mode Blender (--background) for renders. MCP bridge planned for Phase 1 of engine roadmap.
**Target Quality**: Dawn of War 1/2 calibre — hard-surface modelling, heroic proportions, baked normal maps, team-colour masking.
**Master Tracking**: `docs/DEVELOPMENT.md` — MUST be updated before any new task.

---

## Critical Rules

1. **Full Colour, No Palette Lock**: Assets use full RGBA colour at 16-bit depth. The `grimdark_64.gpl` palette is optional for retro variants.
2. **LANCZOS Downscale**: Raw renders supersampled at 1152×1536 (3×), final output 384×512 via LANCZOS. All LOD downscales also use LANCZOS. NEVER use NEAREST.
3. **Hard-Surface Modelling, Not Subsurf**: Armour parts use `add_hard_surface()` (Edge Split + Bevel + Shade Flat). Subsurf is ONLY for cloth, flesh, organic parts. This is critical — subsurf on armour creates smooth blobs with ~1.5% edge density. Target is 15-30% edge density for DoW-quality hard surface.
4. **Miniature Lighting**: Small, bright lights (size=0.2-0.5, not 3.0). 4-point setup — key (3000W), fill (500W), rim (2000W), specular (800W). Hard shadows for edge definition, not soft studio lighting.
5. **8 Directions True**: No mirroring — N, NE, E, SE, S, SW, W, NW.
6. **Blender Single Source of Truth**: The `.blend` file is the master asset. PNGs are derived.
7. **Version Everything**: Every output directory MUST include a version tag (e.g. `v0.5.0/`).
8. **Kill Stale Blender Processes Before Render**: Always call `kill_blender_processes()` before spawning a render. Orphaned/crashed Blender processes consume GPU memory. Uses `pgrep -x blender` + `ps` to identify background renders, then `SIGKILL`. Fallback: `/proc` scanning. Implemented in `render_queue.py`, `pipeline_cli.py`, `batch_render.sh`.
9. **Gallery Uses External JS**: Gallery at `tools/gallery_server.py` serves `tools/static/gallery.js` externally. No inline JavaScript in Python triple-quoted strings — the `\'` → `''` bug crashes the UI. Use template literals (backticks) instead.
10. **Port Clearing at Boot**: Both `server.py` and `gallery_server.py` call `ensure_port()` which runs `fuser -k PORT/tcp` before binding. This prevents "port in use" errors from orphaned processes.
11. **Batch Overnight**: Each unit takes ~3h at 128 samples. Queue all units and batch overnight via the render queue system.

---

## Pipeline Architecture

```
pipeline_cli.py (unified entry point)
    │
    ├── character/        → sub-pipeline: JSON config → .blend → render → critic → pack → sync
    ├── tile/             → sub-pipeline: tile set def → .blend → render → pack
    ├── ui/               → sub-pipeline: Pillow-based UI element generation
    ├── materials/        → PBR texture generation + material library rebuild
    ├── critic/           → quality gate for any rendered output
    ├── pack/             → atlas packing for any processed sprites
    ├── sync/             → copy atlases to IoA game repo
    ├── info/             → pipeline configuration status
    └── doctor/           → dependency checker
```

**Rule**: All pipeline entry goes through `python3 tools/pipeline_cli.py <command>`. Never run generator/renderer/packer scripts directly unless debugging a specific stage. The CLI handles versioning, path resolution, and execution ordering.

---

## Repository Layout

```
asset-pipeline/
├── .pi/skills/asset-pipeline/SKILL.md   # This skill
├── .pipeline_version                     # Current version tag (set by CLI)
├── AGENTS.md                             # Legacy master rules
├── README.md
├── PLANNING.md
├── development.md
│
├── configs/
│   ├── iron_directorate/      # 9 unit JSON configs
│   └── cinderborn/            # 9 unit JSON configs
│
├── assets/
│   ├── pbr_textures/          # Procedural PBR texture sets (per material)
│   ├── materials/             # Blender material library .blend
│   ├── palettes/              # grimdark_64.gpl + Python helper
│   └── units/                 # Per-unit model dirs (characters, tiles, props)
│
├── tools/
│   ├── pipeline_cli.py                   # UNIFIED CLI entry point
│   ├── batch_pipeline.py                 # Batch post-process + pack (legacy)
│   ├── critic.py                         # Automated quality metrics
│   ├── render_queue.py                   # Render job queue manager
│   ├── queue_dashboard.py                # Web UI dashboard for queue management
│   ├── schedule_render.sh               # Cron/at scheduler script
│   ├── generate_status_icons.py          # 32×32 status effect icons
│   ├── generate_ui_elements.py           # NEW: UI button/panel/divider generation
│   ├── sync_to_ioa.py                    # Extract & copy to IoA repo
│   │
│   ├── pbr/
│   │   └── gen_procedural_textures.py    # PBR texture generator (numpy/Pillow)
│   │
│   ├── blender/
│   │   ├── create_material_library.py    # Build grimdark_materials.blend
│   │   ├── parametric_unit_generator.py  # JSON config → rigged .blend (characters)
│   │   ├── render_8dir_v2.py             # 8-dir render pipeline (8× supersample, Cycles)
│   │   ├── preview_model.py              # Interactive 3D model viewer
│   │   ├── tile_generator.py             # Procedural isometric tile generation
│   │   └── render_tiles.py               # (future) tile-specific renderer
│   │
│   ├── batch_process.py                  # LANCZOS downscale + optional palette (v0.5.0+)
│   ├── batch_pipeline.py                 # Legacy pixel-art pipeline (v0.4.0)
│   │
│   └── packer/
│       └── pack_sprites.py               # Atlas packing + LOD generation (LANCZOS)
│
├── docs/                                  # Full documentation set
│
├── output/
│   ├── v0.5.0/                            # Current versioned output
│   │   ├── (character atlases — full RGBA)
│   │   ├── ui/                            # UI elements per theme
│   │   └── tiles/                         # Tile set outputs
│   ├── releases/                          # Timestamped release snapshots
│   │   └── latest/ -> v0.5.0-2026-...     # Symlink to latest release
│   └── v0.4.0/                            # Previous version (pixel-art)
```

---

## Asset Type Reference

### Characters — `tools/pipeline_cli.py character <action>`

Full 3D-to-2D isometric sprite generation for humanoid units. See `docs/PARAMETRIC_CONFIG.md` for config schema.

**Sub-pipeline stages**:
1. `character generate --config <path>` — JSON → rigged .blend (armature + 5 NLA actions + PBR materials)
2. `character render --unit <name> --engine CYCLES` — 8 directions × 5 animations at 1152×1536 supersample
3. `critic single --dir <raw_render_dir>` — automated quality check
4. `pack --unit <name>` — post-process (LANCZOS 1152×1536→384×512) → atlas pack
5. `sync --target <ioa_path>` — copy to IoA game repo
6. `character full --config <path>` — all of the above in one command

**Key constraints**:
- ortho_scale must NOT be multiplied by SUPER_SAMPLE. Resolution handles supersample, not camera scale. Current render buffer is 1152×1536 (3× supersample), final output is 384×512 via LANCZOS.
- NLA action isolation is mandatory before each render block — never rely on `scene.frame_set()` alone.
- All humanoids follow the same bone hierarchy: Hips → Chest → Neck → Head | Thigh_L/R → Shin_L/R → Foot_L/R | UpperArm_L/R → Forearm_L/R → Hand_L/R.
- Animation frame ranges are fixed: idle(1-4), walk(10-16), attack(20-24), hurt(30-32), die(40-46).

**Render quality targets for characters** (v0.5.0+ full RGBA, 384×512 final, 16-bit colour):
| Metric | Target | Fail threshold |
|--------|--------|---------------|
| Alpha coverage | 8-25% | < 4% or > 80% |
| Mean brightness | 60-150/255 | < 40 or > 220 |
| Brightness stddev | > 10/255 | < 10 |
| Edge density (hard surface target) | > 5% at 384×512 | < 1.5% |
| Edge density (DoW target) | 15-30% | — |
| Direction variance | < 50% | > 50% |
| Unique colours | 200+ | — |

**Note on edge density**: At 1.5% the models are smooth blobs (1990s quality). At 5%+ the hard-surface armour edges become visible. Target of 15-30% equals DoW1/2 miniature-level detail. The hard-surface modelling changes (`add_hard_surface()`) aim to raise edge density from ~1.5% to 5%+. Normal map baking will push it to the 15-30% target.

### Tiles — `tools/pipeline_cli.py tile <action>`

Procedural isometric tile generation via Blender. See `tools/blender/tile_generator.py` for tile set definitions.

**Tile types**:
- `ground`: Floor tiles (concrete, dirt, metal grating, etc.) at TILE_FOOTPRINT_W × TILE_FOOTPRINT_D (96×48 px in game)
- `walls`: Vertical walls at WALL_HEIGHT (96 px tall)
- `props`: Crates, barrels, barricades, cover objects
- `elevation`: Raised platforms (+24 px per elevation level)
- `decoration`: Vents, cables, signs (future)

**Tile sets** (defined in `tools/blender/tile_generator.py:TILE_SETS`):
- `urban_concrete`: Cracked pavement, manholes, barricades, barrels
- `industrial_metal`: Metal plates, grating, crates, drums
- `cinderborn_ruin`: Blasted stone, ash, ritual circles, pillars

**Adding a new tile set**: Add a new dict entry to `TILE_SETS` in `tile_generator.py` following existing structure. Each entry defines ground tiles, walls, and props with material assignments.

**Tile render**: Uses a dedicated isometric camera (30° elevation) and SUN lighting (not 3-point area lights). Tile renders are 384×384 with top-down isometric perspective.

### UI Elements — `tools/pipeline_cli.py ui <action>`

Pillow-based 2D UI element generation. No Blender required. See `tools/generate_ui_elements.py`.

**Available actions**:
- `ui icons` — Generate 32×32 status effect icons (wraps `generate_status_icons.py`)
- `ui buttons --theme <theme>` — Generate button sets (small/medium/large × default/hover/active/disabled)

**UI element types**:
- Buttons: 3 sizes (48×24, 96×32, 160×40) × 4 states (default, hover, active, disabled)
- Panels: Modular 16×16 grid pieces (bg, corner, border_h, border_v) — assemble any size via tiling
- Dividers: Horizontal (96×2), vertical (2×96), section headers (96×4)
- Icon frames: Themed 32×32 borders for status effect icons

**Themes** (defined in `tools/generate_ui_elements.py:THEMES`):
- `default`: Grimdark industrial — gunmetal, hazard yellow accents
- `iron_directorate`: Gold/blue, clean lines, ordered
- `cinderborn`: Purple/orange, asymmetrical, chaotic

**Adding a new theme**: Add a new dict entry to `THEMES` with all colour fields populated. Each field controls a specific UI element colour (panel_bg, button_default, text, etc.)

### Materials — `tools/pipeline_cli.py materials <action>`

Procedural PBR texture generation + Blender material library management.

- `materials generate` — Generate all PBR textures (numpy noise → albedo/normal/roughness/metallic/height maps), then rebuild Blender material library .blend
- `materials list` — Show available material sets

**Current materials** (10):
- `grimdark_metal`: Dark gunmetal, rust spots, scratches, pitting — Iron Directorate
- `grimdark_leather`: Worn brown leather, creases, grain — All factions
- `grimdark_fabric`: Military green fabric, weave, folds — Iron Directorate
- `imperial_gold`: Warm gold, tarnish, engraved detail — Iron Directorate officers
- `chaos_rust`: Heavy corrosion, blood stains, deep pitting — Cinderborn
- `bio_flesh`: Sickly green organic, vein network, spore spots — Parasitic Bloom
- `chrome_white`: Bright white-chrome, panel lines, minimal wear — Radiant Concord
- `cyan_bone`: Cyan-tinted bone, porous, temporal cracks — Chrono Revenants
- `red_rust`: Hot red-orange rusted metal, heat scoring, battle wear — Wreckstorm Clans
- `black_silver`: Dark grey-black tactical, silver edge wear, matte — Void Corsairs

**Adding a new material**:
1. Add `gen_<name>()` function to `tools/pbr/gen_procedural_textures.py` following existing pattern
2. Add to `materials` dict in `tools/blender/create_material_library.py`
3. Run `pipeline materials generate` to rebuild
4. Material is now available in any JSON config's `"materials"` section

---

## Code Standards

### General

- **DRY**: Extract repeated logic (path resolution, palette loading, noise generation) into shared functions.
- **Lean & Simple**: Prefer the simplest correct solution. A 20-line function that works is better than a 200-line abstraction that almost works.
- **Indentation**: 4-space Python. Never introduce tabs.
- **Sorting**: Sort imports, config keys, material definitions, and class members alphabetically unless order is semantically significant.
- **Docstrings**: Every module and public function MUST have a docstring. Follow existing style.
- **Path Resolution**: Always anchor to `SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))`. Never hardcode absolute paths.
- **Exit Codes**: Scripts that can fail MUST return non-zero exit codes on failure and zero on success. Use `sys.exit()`.

### Python

- Use `pathlib.Path` for path operations.
- Use `argparse` for CLI argument parsing. Never use raw `sys.argv`.
- Type hints encouraged but not mandatory.
- f-strings for string formatting, never `%` or `.format()`.
- Import order: standard library → third-party → local. Groups separated by blank lines.
- Context managers for file I/O.
- Module-level constants in `UPPER_CASE`.

### Blender Python Scripts

- Run in `--background` mode — no UI dependency.
- Always call `bpy.context.view_layer.update()` after moving objects.
- Set `use_fake_user = True` on materials with no object users (prevents Blender purge on save).
- Blender 5.1 uses layered Actions (`Action → Layer → Strip → ChannelBag → FCurves`). Never use `action.fcurves`.
- Use `bpy.ops.wm.append()` for loading from other `.blend` files.
- Set `bpy.context.view_layer.objects.active` before any `bpy.ops.object.*`.

---

## Quality Gates

**Never declare a render done without running the critic.**

1. `python3 tools/pipeline_cli.py critic single --dir <render/raw/dir>`
2. Check `critic_report.json` in the render directory
3. ALL metrics must pass (`overall_pass: true`)
4. If any metric fails, diagnose from common failures table below, fix, re-render (up to 3 retries)
5. After batch operations, run `pipeline critic batch` for full coverage

### Common Failures & Fixes

| Failure | Symptom | Fix |
|---------|---------|-----|
| alpha_coverage_low | Model invisible (< 6% coverage) | Reduce ortho_scale (×0.7), scale up model, or increase render res |
| alpha_coverage_high | Model fills > 85% frame | Increase ortho_scale or check framing |
| brightness_low | Too dark (< 40/255) | Boost light energy (×1.5), add ambient light, brighten materials |
| brightness_high | Blown out (> 220/255) | Reduce light energy or darken materials |
| contrast_low | Flat, no detail (stddev < 10) | Increase key/fill ratio (6:1 target), add rim light, check normal maps. Ensure light size is small (0.2-0.5) for hard shadows |
| edge_density_low | Too few edges (< 2%) | Check that `add_hard_surface()` is used instead of `add_subsurf()` on armour parts. Verify Edge Split modifier angle limit (30°). Increase base geometry segments (cylinder 48, sphere 48×32). Flat shade, not smooth shade. |
| edge_density_very_low | Blobby (< 1.5%) | Subsurf is still on armour parts. Replace with `add_hard_surface()`. The `parametric_unit_generator.py` should use `shade_flat()` + `add_hard_surface()` for all non-cloth parts. |
| direction_variance | Asymmetric across directions (> 30%) | Check rig alignment, part attachment, model centering |

### Visual Verification Checklist (miniature-level detail standard)

After critic passes, visual inspection is still required. Compare against tabletop miniatures and Dawn of War 2 quality:

1. **Silhouette readability**: At 384×512, can you identify the unit type and faction from outline alone?
2. **Material fidelity**: Do PBR materials read clearly? Can you distinguish ceramite armour from fabric under-layer?
3. **Proportions**: DoW2/tabletop miniature proportions are the benchmark. Armour should read as thick ceramite. Heroic scale: hands +30%, weapons +25%, pauldrons +30%, boots +20%.
4. **Hard-surface definition**: Can you see individual armour plates with sharp edges, or is the model a smooth blob? Look for edge highlights, panel lines, armour plate separation.
5. **Detail at full resolution**: At 384×512, can you distinguish weapon from body, helmet crest from visor, faction-specific trim?
6. **Direction consistency**: All 8 directions look like the same unit from different angles.
7. **Contrast separation**: High contrast between armour plates, under-armour, weapons, and faction accents. Miniature photography uses 10:1 key-to-fill ratio.
8. **Faction identity**: Each faction MUST be visually distinct — gold/blue + cool key light for Iron Directorate, purple/orange + magenta key for Cinderborn.

---

## Faction Coding Reference

> Identity authority: `Imperium-of-Ash/docs/game-design/FACTION_IDENTITY.md` — 40K-role lineage
> (Iron Directorate=Guard, Sons of Cinder=`cinderborn`=Chaos, Parasitic Bloom=Tyranid,
> Harmonic=T'au, Revenants=Necron, Wreckstorm=Ork, Corsairs=Eldar) with our own silhouettes,
> weapon language and palettes. One silhouette idea per faction; muted world, saturated units.\n
| Faction | Playable | Theme | Visual Signature | Materials | Lighting Profile |
|---------|----------|-------|------------------|-----------|-----------------|
| Iron Directorate | Yes | Order & Tech | Gold/blue, clean lines, industrial | grimdark_metal, imperial_gold, grimdark_fabric, grimdark_leather | Cool key (5500K), neutral fill — ordered militaristic |
| Cinderborn | Yes | Occult & Sacrifice | Purple/orange, ritual markings, asymmetrical | chaos_rust, grimdark_metal, grimdark_leather | Warm magenta key, purple fill — corrupted ritual |
| Parasitic Bloom | No | Bio horror | Green/flesh, swarm behaviour | bio_flesh, grimdark_leather | Sickly green key, pink fill — fleshy horror |
| Radiant Concord | No | AI precision | White/chrome, precise geometry | chrome_white, grimdark_metal | Cool blue key, white rim — sleek machine |
| Chrono Revenants | No | Time-warped undead | Cyan/bone, temporal effects | cyan_bone, grimdark_metal | Warm gold/bronze key, teal fill — aged temporal |
| Wreckstorm Clans | No | Speed & fury | Red/rust, aggressive | red_rust, grimdark_metal, grimdark_leather | Rusty orange key, minimal fill — scrap heat |
| Void Corsairs | No | Mercenary pirates | Black/silver, tactical | black_silver, grimdark_leather | Cool purple key, deep shadows — stealth |

**TODO**: Faction-specific lighting profiles are NOT yet implemented in `render_8dir_v2.py`. All factions currently use the same 4-point miniature lighting. Each needs its own key light colour temperature and intensity to establish distinct visual identity.

**NPC configs**: 10 unit configs across 5 NPC factions exist in `configs/<faction>/`. Each has 2 unit types (T1 infantry + T2/T3 elite). Materials exist for all — generate .blend files with `pipeline_cli.py character generate --config <config_path>`.

When adding new factions, create new PBR material sets in `gen_procedural_textures.py` first, then assign them in unit configs. Faction distinctiveness comes from material choice + colour palette + lighting profile, not geometry alone.

---

## Working with the Unified CLI

### Common workflows

```bash
# Full end-to-end for a single character unit
python3 tools/pipeline_cli.py character full --config configs/iron_directorate/line_infantry.json

# Batch all units in a faction (with quality summary)
python3 tools/pipeline_cli.py character batch --config-dir configs/iron_directorate/
python3 tools/pipeline_cli.py critic batch

# Quick iteration: generate materials, test one unit
python3 tools/pipeline_cli.py materials generate
python3 tools/pipeline_cli.py character generate --config configs/cinderborn/cinder_cultist.json
python3 tools/pipeline_cli.py character render --unit cinderborn_cinder_cultist --engine BLENDER_EEVEE
python3 tools/pipeline_cli.py critic single --dir assets/units/cinderborn_cinder_cultist/model/render/raw/

# Generate UI elements
python3 tools/pipeline_cli.py ui buttons --theme iron_directorate
python3 tools/pipeline_cli.py ui icons

# Generate a tile set
python3 tools/pipeline_cli.py tile generate --tile-set urban_concrete

# Check pipeline health
python3 tools/pipeline_cli.py doctor
python3 tools/pipeline_cli.py info

# Sync latest output to IoA
python3 tools/pipeline_cli.py sync --target ../imperium-of-ash/frontend/public/assets/atlases/
```

### Render Queue (offline processing)

Use the queue to defer renders to when the machine is idle:

```bash
# During the day: queue up units to render
python3 tools/pipeline_cli.py queue add --unit iron_directorate_line_infantry
python3 tools/pipeline_cli.py queue add --unit cinderborn_cinder_cultist

# Quick batch add: queue all units that haven't been rendered
for cfg in configs/iron_directorate/*.json; do
    name=$(basename "$cfg" .json)
    python3 tools/pipeline_cli.py queue add --unit "$name"
done

# Check what's queued
python3 tools/pipeline_cli.py queue list
python3 tools/pipeline_cli.py queue status

# At night / lunch break: process everything
python3 tools/pipeline_cli.py queue run --fast

# Or use the scheduler script (handles locking, logging, sleep prevention):
bash tools/schedule_render.sh --fast

# Schedule for 2am (requires `at` command):
at 02:00 -f tools/schedule_render.sh

# Or via cron (editing crontab):
# 0 2 * * * /path/to/asset-pipeline/tools/schedule_render.sh --fast
```

**Queue workflow**: Add during day → process when idle → pack atlases after all done:
```bash
# Step 1: Queue everything
python3 tools/pipeline_cli.py queue add --unit all_units...

# Step 2: Process when machine is free
bash tools/schedule_render.sh --fast

# Step 3: After all renders succeed, pack (full RGBA, LANCZOS downscale)
PIPELINE_VERSION=v0.5.0 python3 tools/batch_pipeline.py

# Step 4: Create timestamped release snapshot
python3 tools/pipeline_cli.py release

# Step 5: Sync to IoA
python3 tools/pipeline_cli.py sync --target ../imperium-of-ash/frontend/public/assets/atlases/
```

To use the optional palette quantisation (retro pixel-art look):
```bash
PIPELINE_VERSION=v0.5.0 python3 tools/batch_pipeline.py --palette assets/palettes/grimdark_64.gpl
```

### Render Queue & Dashboard

The web dashboard provides a visual interface for the render queue.

```bash
# Launch dashboard
python3 tools/queue_dashboard.py
# Opens: http://localhost:8081 (port auto-increments)

# Or via CLI
python3 tools/pipeline_cli.py dashboard
```

**Dashboard features**:
- Live progress bar (frame count, percentage, animation/direction tracking)
- Queue overview (queued/running/done/failed counts, job list with status badges)
- **Render Now** / **Pause** / **Resume** / **Stop** buttons
- Schedule time input with **Install Cron** button (cron entry for nightly automation)
- Add unit to queue via text input
- Live render log tail

**Pause / Resume flow**:
```
queue add --unit iron_directorate_line_infantry    # Add units during day
queue run --fast                                    # Start processing
queue pause                                         # Pause after current job
# (PC goes to sleep)
queue resume                                        # Resume processing next day
```

The queue is crash-safe — all state is on disk. If a render is interrupted:
- `queue run` auto-resets stale "running" jobs and detects already-rendered units
- `queue clean` manually resets stuck jobs

### Version Management

- Current version is tracked in `.pipeline_version` (auto-created by CLI).
- Read with: `python3 tools/pipeline_cli.py info`
- Override for a single command: `PIPELINE_VERSION=v0.5.0 python3 tools/pipeline_cli.py pack --unit line_infantry`
- When creating a new version: update `.pipeline_version`, then regenerate all assets.

---

## DoW Asset Import (external game assets)

Authentic Relic Dawn of War assets (SGA v2 archives, Definitive Edition)
import as geometry + material sources — proven with the ork roster (Slugga/
Shoota Boyz rendered textured + klan-tinted + pixelised 2026-10-05).

- Tools: `tools/dow/` — `whm_v4_patch.py` (Definitive RSGM v4 shims over the
  v3 WHM reader: version gate, STXT tolerance, MSLC v4 reserved fields),
  `rsh_extract.py` (RSH atlas decoder: raw DXT mip chains wrapped in synthetic
  DDS), `blender_ork_import.py` (OBJ import + atlas texturing + klan tint +
  ortho front render; `DOW_ATLAS_DIR` overrides the atlas dir).
- Pixel variant: `pz/pixel/` — `pixelise.py`/`verify_pixel_asset.py`/
  `styles.py`/`palette.py` (Oklab fixed-palette quantisation, QC gates).
- Full reference: `docs/DOW_IMPORT.md`; replication guide (with all gotchas:
  split relic packages not the 2.0.1 monolith, 8-bit RGBA atlases only,
  `Standard` view transform not AgX, DXT1 alpha blanks renders):
  `~/Downloads/mtcde_masters/PIPELINE_GUIDE.md`.
- Sources: Definitive archives have doubled path components; unit models at
  `art\...\races\orks\troops\*.whm`, atlases at
  `art\ebps\races\orks\texture_share\*.rsh`; W40kData.sga (unit icons +
  WTP team patterns) pending. Slugga/Shoota are load-out part sets inside one
  WHM — filter OBJ objects per load-out if a plain boy is wanted.

## XCOM: Enemy Unknown reference (environment & prop grammar)

XCOM:EU is the readability benchmark our tile/prop work emulates (IoA side:
`Imperium-of-Ash/docs/skills/xcomcombatskill.md` — combat rules; here: what it means for
assets). Non-negotiables for generators, keyed to the game's actual env rules:

1. **One tile = one decision.** Every tile must read as one of: open / half-cover /
   full-cover / blocked / elevated. Props are cover-shaped (waist-high half pieces,
   shoulder-high full pieces) — bake this into `tile_generator.py` prop vocabulary.
2. **Damage states are mandatory, not decorative.** XCOM destructibles carry HP and every
   shot deals `environmentDamage` (pistol 10 → grenades 250). Any cover prop we ship needs
   intact → damaged → destroyed frames or a shatter-to-rubble variant. (See Known Technical
   Debt #9 — tile animation/destructible states.) Prioritise cover props, walls, vehicles.
3. **Silhouette over detail. XCOM mutes the world, saturates the units** — the level is
   grey/brown/blue-grey; the most saturated object on screen must always be a unit. Our
   faction palettes already do this; enforce it in tile material albedo (low-chroma base,
   accent only on interactables).
4. **Elevation is geometry, not texture.** Distinct walkable strata (ground/roof) with
   readable edges and drop shadows; props that enable climbing read differently.
5. **Diorama lighting.** Fixed 45° iso, key from upper-left, unit-contrast priority —
   matches our existing 4-point miniature rig; keep tile lighting quieter than unit lighting.
6. **Sound stingers per outcome, not per weapon** (hit/crit/miss/death + UI confirm) —
   audio layer is outcome-classed (see xcomcombatskill §11).


### Surface quality & the printer band-pass (researched 2026-10-17, panel project)

**The governing principle: the pipeline is a band-pass filter tuned to the
printer.** FDM at 0.12mm layers / 0.4mm nozzle reproduces: lateral features
>=~0.8mm, relief >=~0.25mm (2 layers). Everything below is invisible or paint:

- **Geometry band**: keep form + features 0.8mm and coarser, relief >=0.3mm.
- **Sub-floor detail** (photo grain, paper texture, jpeg mush, mc shimmer):
  SMOOTH AWAY, never carve. The carve must be band-limited (>=2mm wavelength)
  and >=0.3mm amplitude -- sub-layer displacement is invisible but reads as
  sand under print lighting.
- **Texture (wood grain, leather, text)**: paint, not geometry. Geometry only
  carries the raised bands/borders. The user paints the print.

Measured root causes of grain (panel project):
1. stacked carve passes at 6-15mm amplitude -> scribble (fixed: detail_loop
   per-cell deficit weighting, single-band, <=1.6mm)
2. marching-cubes staircase + mc noise: the dc remesh (cumesh
   remesh_narrow_band_dc_quad, the ComfyUI node chain's "Voxel to Mesh")
   removes staircase by construction but only -4% roughness -- it inherits
   the mc surface noise through the SDF.
3. The principled fix (IMPLEMENTED NEXT): **bilateral normal filtering**
   (Zheng et al., TVCG 2010; feature-preserving: filter normals with
   spatial+normal-distance weights, then refit vertices) -- the standard for
   exactly this. Fallback: trimesh filter_taubin (lambda|mu, no shrinkage) --
   NEVER plain Laplacian (shrinks features).
4. Roughness metric for gates: mean angle between adjacent-face normals
   (printprep.py::roughness). Track it per loop iteration; the loop's
   spurious guard plus a roughness-nonincrease guard = the balance the
   95%-loop needs.

Pipeline order (printer-band): generate -> dc remesh -> bilateral smooth ->
band-limited carve -> detail_loop -> printprep (floater/simplify/holes) ->
tiles3d -> slicer. Never carve before smoothing.

Multi-image endgame: the loop + band-pass are input-agnostic; mv variants
(Pixal3D-MV in ComfyUI-Trellis2) slot in at step 1 for 3-4-image runs.


## Known Technical Debt

Tracked issues that need attention. See `docs/DEVELOPMENT.md` section 14 for full tracking.

1. **Hard-surface modelling implemented but untested**: `add_hard_surface()` replaces subsurf on all armour parts. Needs a re-render to verify edge density improvement from ~1.5% to target 5%+.
2. **Faction-specific lighting not implemented**: All factions use the identical 4-point miniature lighting. Needs per-faction key light colour temperature and energy profiles.
3. **Normal map baking**: No normal map pipeline exists. This is required to push edge density from 5% (hard-surface geometry only) to 15-30% (DoW target with baked detail).
4. **Team-colour mask generation**: No alpha-channel team colour mask on materials. Required for game engine faction tinting.
5. **Animation intensity**: **DONE** — Base rotation amplitudes increased 3-8× across all animations (idle, walk, attack, hurt, die). Config params updated to idle_intensity=1.0, walk_stride=0.4, attack_speed=1.5. All 28 configs updated.
6. **Side-view coverage**: **IMPROVED** — Shoulders widened (0.26→0.30), legs spread (0.08→0.10), codpiece/tabard geometry added. E/W alpha coverage at ~8.45% vs ~14.7% for N/S. Direction variance threshold adjusted to 50% to account for humanoid anatomy.
7. **NPC factions**: **DONE** — 5 new PBR material sets added (bio_flesh, chrome_white, cyan_bone, red_rust, black_silver). 10 unit configs created across all 5 NPC factions. .blend files generated.
8. **Tile render script**: `tools/blender/render_tiles.py` not yet written — tile `render` command warns. Currently tile rendering is part of `tile_generator.py` itself.
9. **Animation pipelines for tiles**: Tiles don't have animation support yet. Destructible states (intact → damaged → destroyed) would need frame sequences.
10. **Non-humanoid templates**: **DONE** — Vehicle, creature (quadruped), and insectoid body types added via `tools/blender/parametric_vehicle_generator.py`. 6 configs created. Animation frame ranges defined but bone keyframe data not yet written.
11. **Render timeout**: Cycles at 128 samples/1152×1536 takes ~3 hours for 248 frames (full unit). Use `--fast` (64 samples at 1152×1536) for iteration, full quality for final. The CLI's 120s timeout is too short — run Blender directly for full renders. The render queue handles this automatically in background mode.
12. **Codpiece/tabard geometry**: Added but minimal E/W silhouette impact. Consider adding over-shoulder weapon sling, cape, or larger backpack for more dramatic side-profile volume.


## Image-to-3D detail standard & multi-pass loop (mandatory for panel/prop meshes)

**The standard (user-set, gate on every delivery):** the mesh must survive a
side-by-side against the reference artwork at PRINT SCALE (one tile, 157mm
zoom) — forms, proportions, mid-relief crisp; no visible sand/stipple; and the
render-edge audit ≥85% capture on the final pass, judged per-region via the
residual map (red=lost/green=spurious overlay, code pattern in session logs
and `tools/img23d/verify.py`). "Structurally right" is NOT passing; surface
fidelity is the deliverable.

**The loop (one-to-one is reached by passes, never one-shot):**
1. reconstruct (best model that fits VRAM — see quality ladder in
   `~/.pi/skills/cr200b/SKILL.md`; full Hunyuan3D-2 ≥ octree 384 minimum)
2. smooth (Humphrey ~30 it) → carve artwork high-pass (multi-band 24/12/6/3)
3. render-audit vs artwork → residual miss-map → carve ONLY the missing
   regions/bands (pass 3 pattern)
4. pose-registered side-view carving (homography from silhouette) for
   vertical walls; hero-element anatomy is Blender sculpt work against the
   reference render — no pipeline pass substitutes
5. iterate 3→4 until capture plateaus AND visual sign-off at tile zoom;
   then plate/tiles via `plate.py`/`tiles.py`, verify, print-prep per cr200b

Full state, pass ledger, blockers: `HANDOFF_IMG23D.md` (repo root). Multiview
capture prompts: `docs/IMG23D.md`. Never ship a mesh whose verify <85 or
whose sand pass was skipped.

## Gemini web image generation — agent-driven (gemini-img, LIVE 2026-10-23 pending first cookie auth)

Consumer Gemini Pro (Nano Banana) driven programmatically — no API key, no AI Studio.
Wrapper: `~/.pi/agent/bin/gemini-img` (venv `~/.venvs/gemini`, pkg `gemini_webapi`,
reverse-engineered web client, 3.6★ repo HanaokaYuzu/Gemini-API).

- **One-time auth (owner)**: fresh PRIVATE browser window → gemini.google.com → F12 →
  Network → any request → copy `__Secure-1PSID` + `__Secure-1PSIDTS` → then EITHER
  `gemini-img --set-cookie <PSID> <PSIDTS>` OR fill `~/.config/gemini/cookies.env`
  (template beside it). Close the private window after. The lib auto-refreshes the TS
  cookie while the process runs.
- **Generate**: `gemini-img "<prompt from IoA Imperium-of-Ash
  docs/game-design/UI_ART_PROMPTS.md>" --out ~/Downloads/gemini --name <asset>` →
  JSON `{text, images[], out}` on stdout; images land on disk for agent review
  (agent reads the PNGs and iterates).
- **Edit chain (identity preservation — the entire game)**: `gemini-img "same object
  rotated 90 degrees, keep everything identical except ..." --edit <winner.png>`.
  The wrapper prefixes "Using the attached image:" automatically. NEVER reroll a
  winner from scratch; derive.
- **Agent loop**: prompt (from the art contract) → run → READ the saved PNG →
  compare against the contract/prior winner → next edit prompt → repeat until
  sign-off → post (`rembg`, nearest-neighbour downscale) → repo `assets/`/mod dir
  per the destination rules at the top of this skill.
- **Governing queue**: before ANY generation, read
`Imperium-of-Ash/docs/game-design/ASSET_LEDGER.md` (phases, per-asset status
NEED→SHIPPED, approval law, quota burn log) and the art contract
`Imperium-of-Ash/docs/game-design/UI_ART_PROMPTS.md` + `ASSET_DIRECTION.md §8`
(faction hex/silhouette law). Never generate an asset the ledger does not list.

**Status: CONFIRMED LIVE 2026-10-23.** Auth installed (`~/.config/gemini/cookies.env`, PSID+PSIDTS pair; PSIDTS is REQUIRED — PSID alone authenticates-unverified). Proven end-to-end: text turn (`AUTH OK`) and a 2048px portrait generation from the IoA UI art contract saved via the wrapper (`~/Downloads/ioa-ui/line_infantry/line_infantry_v1_0.png`). Iterate via `--edit <winner>`; the wrapper's auto 'Using the attached image:' prefix matches the edit-chain discipline above. If auth expires: re-copy BOTH cookies from a fresh logged-in window (Chromium TS cookies rot fast; Firefox alternative per lib README).


## Style profiles (2026-11-09)

Pixel tiers are selected by profile, not by editing the pixeliser:
`configs/styles/profiles.json` + `tools/style/profiles.py` (see
`docs/STYLE_PROFILES.md`). The 2D pixel path is the `pixel_sprite` /
`hd_pixel_sprite` profile; assets are requested from `configs/assets/*.json` with
a route, and the pixel gate is `tools/style/check_pixel_asset.py`.
