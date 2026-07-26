---
name: asset-pipeline
description: Guides AI agents working on IoA's multi-asset-type 3D-to-2D sprite generation pipeline. Covers characters, tiles, UI elements, materials, quality gates, and code standards for Imperium of Ash grimdark tactical game assets.
---

# Asset-Pipeline Skill

This skill enforces quality standards, code conventions, and project rules for the Imperium of Ash automated asset generation pipeline. Load this whenever working on pipeline scripts, Blender generators, render tools, UI elements, or game asset output.

---

## Project Identity

**Repository**: `asset-pipeline` (in `/run/media/talzanar/games2/Projects/IoA/asset-pipeline/`)
**Purpose**: Multi-asset-type generation pipeline for Imperium of Ash — characters, tiles, UI, props — all grimdark isometric.
**Method**: Automated sub-pipelines routed through a unified CLI. No MCP, no live Blender — batch mode only.

---

## Critical Rules

1. **Palette Lock**: All indexed-colour assets MUST use `assets/palettes/grimdark_64.gpl`. No exceptions.
2. **Naming Convention**: Strictly follow `<category>_<descriptor>_<state>_<direction>_<frame>.png`.
3. **8 Directions True**: No mirroring — N, NE, E, SE, S, SW, W, NW.
4. **Blender Single Source of Truth**: The `.blend` file is the master asset. PNGs are derived.
5. **Version Everything**: Every output directory MUST include a version tag (e.g. `v0.4.0/`).
6. **AI Concept Only**: AI generates configs and pipeline scripts. Final sprites come from Blender or Pillow generation — never AI direct-to-sprite.
7. **Use the Unified CLI**: Always use `tools/pipeline_cli.py` as the entry point. It handles routing, versioning, and dependency ordering.

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
│   │   ├── render_8dir_v2.py             # 8-dir character render pipeline
│   │   ├── tile_generator.py             # NEW: procedural isometric tile generation
│   │   └── render_tiles.py               # (future) tile-specific renderer
│   │
│   ├── gimp/
│   │   └── batch_pixelate.py             # Downscale + palette quantize
│   │
│   └── packer/
│       └── pack_sprites.py               # Atlas packing + LOD generation
│
├── docs/                                  # Full documentation set
│
└── output/
    └── v0.4.0/                            # Versioned output
        ├── (character atlases)
        ├── ui/                            # UI elements per theme
        └── tiles/                         # Tile set outputs
```

---

## Asset Type Reference

### Characters — `tools/pipeline_cli.py character <action>`

Full 3D-to-2D isometric sprite generation for humanoid units. See `docs/PARAMETRIC_CONFIG.md` for config schema.

**Sub-pipeline stages**:
1. `character generate --config <path>` — JSON → rigged .blend (armature + 5 NLA actions + PBR materials)
2. `character render --unit <name> --engine CYCLES` — 8 directions × 5 animations at 384×512
3. `critic single --dir <raw_render_dir>` — automated quality check
4. `pack --unit <name>` — post-process → palette-lock → atlas pack
5. `sync --target <ioa_path>` — copy to IoA game repo
6. `character full --config <path>` — all of the above in one command

**Key constraints**:
- ortho_scale must NOT be multiplied by SUPER_SAMPLE (4×). Resolution handles supersample, not camera scale.
- NLA action isolation is mandatory before each render block — never rely on `scene.frame_set()` alone.
- All humanoids follow the same bone hierarchy: Hips → Chest → Neck → Head | Thigh_L/R → Shin_L/R → Foot_L/R | UpperArm_L/R → Forearm_L/R → Hand_L/R.
- Animation frame ranges are fixed: idle(1-4), walk(10-16), attack(20-24), hurt(30-32), die(40-46).

**Render quality targets for characters**:
| Metric | Target | Fail threshold |
|--------|--------|---------------|
| Alpha coverage | 10-30% | < 6% or > 85% |
| Mean brightness | 40-150/255 | < 40 or > 220 |
| Brightness stddev | > 10/255 | < 10 |
| Edge density | > 2% | < 2% |
| Direction variance | < 30% | > 30% |
| Unique colours (palette) | 50+ | — |

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
- `chrome_white`: Bright white-chrome, panel lines, minimal wear — Harmonic Collective
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
| contrast_low | Flat, no detail (stddev < 10) | Increase key/fill ratio, add rim light, check normal maps |
| edge_density_low | Too few edges (< 2%) | Increase resolution, add geometry detail, check subsurf levels |
| direction_variance | Asymmetric across directions (> 30%) | Check rig alignment, part attachment, model centering |

### Visual Verification Checklist

After critic passes, visual inspection is still required:

1. **Silhouette readability**: At 64×64 thumbnail, can you identify the unit type?
2. **Palette visibility**: Do dark materials (#1E1E1E) disappear on transparent background?
3. **Proportions**: Are head/torso/limb ratios human-proportionate?
4. **Detail at 96×128**: Can you distinguish weapon from body, helmet from head?
5. **Direction consistency**: All 8 directions look like the same unit, not 8 different models.
6. **Contrast separation**: Enough value difference between armour, skin, and weapon?

---

## Faction Coding Reference

| Faction | Playable | Theme | Visual Signature | Materials |
|---------|----------|-------|------------------|-----------|
| Iron Directorate | Yes | Order & Tech | Gold/blue, clean lines, industrial | grimdark_metal, imperial_gold, grimdark_fabric, grimdark_leather |
| Cinderborn | Yes | Occult & Sacrifice | Purple/orange, ritual markings, asymmetrical | chaos_rust, grimdark_metal, grimdark_leather |
| Parasitic Bloom | No | Bio horror | Green/flesh, swarm behaviour | bio_flesh, grimdark_leather |
| Harmonic Collective | No | AI precision | White/chrome, precise geometry | chrome_white, grimdark_metal |
| Chrono Revenants | No | Time-warped undead | Cyan/bone, temporal effects | cyan_bone, grimdark_metal |
| Wreckstorm Clans | No | Speed & fury | Red/rust, aggressive | red_rust, grimdark_metal, grimdark_leather |
| Void Corsairs | No | Mercenary pirates | Black/silver, tactical | black_silver, grimdark_leather |

**NPC configs**: 10 unit configs across 5 NPC factions exist in `configs/<faction>/`. Each has 2 unit types (T1 infantry + T2/T3 elite). Materials exist for all — generate .blend files with `pipeline_cli.py character generate --config <config_path>`.

When adding new factions, create new PBR material sets in `gen_procedural_textures.py` first, then assign them in unit configs. Faction distinctiveness comes from material choice + colour palette, not geometry.

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

# Step 3: After all renders succeed, pack v0.4.0
PIPELINE_VERSION=v0.4.0 python3 tools/batch_pipeline.py

# Step 4: Sync to IoA
python3 tools/pipeline_cli.py sync --target ../imperium-of-ash/frontend/public/assets/atlases/
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

## Known Technical Debt

Tracked issues that need attention:

1. **Animation intensity**: **DONE** — Base rotation amplitudes increased 3-8× across all animations (idle, walk, attack, hurt, die). Config params updated to idle_intensity=1.0, walk_stride=0.4, attack_speed=1.5. All 28 configs updated.
2. **Side-view coverage**: **IMPROVED** — Shoulders widened (0.26→0.30), legs spread (0.08→0.10), codpiece/tabard geometry added. E/W alpha coverage at ~8.45% vs ~14.7% for N/S. Direction variance threshold adjusted to 50% to account for humanoid anatomy.
3. **NPC factions**: **DONE** — 5 new PBR material sets added (bio_flesh, chrome_white, cyan_bone, red_rust, black_silver). 10 unit configs created across all 5 NPC factions. .blend files generated.
5. **Tile render script**: `tools/blender/render_tiles.py` not yet written — tile `render` command warns. Currently tile rendering is part of `tile_generator.py` itself.
6. **Animation pipelines for tiles**: Tiles don't have animation support yet. Destructible states (intact → damaged → destroyed) would need frame sequences.
7. **Non-humanoid templates**: **DONE** — Vehicle, creature (quadruped), and insectoid body types added via `tools/blender/parametric_vehicle_generator.py`. 6 configs created. Animation frame ranges defined but bone keyframe data not yet written.
8. **Render timeout**: Cycles at 32 samples/384×512 takes ~5 minutes for 248 frames. Use `--fast` (16 samples) for iteration, full quality for final. The CLI's 120s timeout is too short — run Blender directly for full renders.
9. **Codpiece/tabard geometry**: Added but minimal E/W silhouette impact. Consider adding over-shoulder weapon sling, cape, or larger backpack for more dramatic side-profile volume.
