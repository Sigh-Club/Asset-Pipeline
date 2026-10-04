# Asset-Pipeline for Imperium of Ash

**Multi-asset-type generation pipeline for grimdark tactical games.**

Built for **Imperium of Ash** (IoA), a Warhammer 40K-inspired tactical combat game. Generates characters, tiles, UI elements, and props — all deterministic, all in-house, zero budget.

## Project Zomboid Icon Forge (PZ — not IoA)

`tools/icon_forge.py` (+ `icon_forge.html` and its generated
`icon_forge_data.js`) is an in-house generator for **Project Zomboid** mod
icons (MTCDeathsExpanded). It lives in this pipeline's `tools/` for
convenience, but **nothing it produces belongs to IoA** — outputs go to the
PZ mod repo, never into `assets/`, `configs/` or `output/`.

```bash
# one icon per vanilla occupation (policeoff, fireoff, burgerflipper, ...)
python3 tools/icon_forge.py occupations --out ~/Downloads/mtcde_occupations.png

# contact sheet of random seeded variants
python3 tools/icon_forge.py sheet --count 12 --out ~/Downloads/forge_sheet.png

# refresh the HTML app's data, then open tools/icon_forge.html in a browser:
python3 tools/icon_forge.py --emit-js tools/icon_forge_data.js
```

Styles are parametric: palette, eyes, mouth, hair, headwear, service or
occupation uniform, prop, wound streak, seed. The HTML app exports 32x32 PNGs
(and 8x previews) straight from the browser.

## Quick Start

```bash
# === MATERIALS (one-time, or when adding new materials) ===
python3 tools/pipeline_cli.py materials generate

# === CHARACTER — full pipeline for a single unit ===
python3 tools/pipeline_cli.py character full --config configs/iron_directorate/iron_directorate_line_infantry.json

# === BATCH — generate + render + pack all units in a faction ===
python3 tools/pipeline_cli.py character batch --config-dir configs/iron_directorate/

# === UI — generate UI elements for a theme ===
python3 tools/pipeline_cli.py ui buttons --theme iron_directorate

# === TILES — generate a tile set ===
python3 tools/pipeline_cli.py tile generate --tile-set urban_concrete

# === CRITIC — quality check all rendered units ===
python3 tools/pipeline_cli.py critic batch

# === SYNC — copy atlases to the IoA game repo ===
python3 tools/pipeline_cli.py sync --target ../imperium-of-ash/frontend/public/assets/atlases/

# === QUEUE — manage and process render jobs ===
python3 tools/pipeline_cli.py queue add --unit iron_directorate_line_infantry
python3 tools/pipeline_cli.py queue list
python3 tools/pipeline_cli.py queue run --fast
python3 tools/pipeline_cli.py queue status

# === DASHBOARD — web UI for queue management ===
python3 tools/pipeline_cli.py dashboard

# === DOCTOR — verify tool dependencies ===
python3 tools/pipeline_cli.py doctor
```

## What This Pipeline Does

The pipeline is a unified orchestrator that routes commands to specialised sub-pipelines:

| Asset Type | Entry Point | Input → Output |
|------------|-------------|----------------|
| **Characters** | `pipeline_cli.py character` | JSON config → rigged .blend → 208 rendered frames → palette-locked atlas |
| **Tiles** | `pipeline_cli.py tile` | Tile set def → .blend model → rendered tile textures |
| **UI elements** | `pipeline_cli.py ui` | Theme config → Pillow-generated PNG sprites (buttons, panels, dividers, icons) |
| **PBR Materials** | `pipeline_cli.py materials` | Math noise → PBR texture maps → Blender material library |

All deterministic, all scriptable, all free. Use the unified CLI — never run generators/renderers directly.

## Repository Layout

```
asset-pipeline/
├── .pi/skills/asset-pipeline/SKILL.md  # AI assistant skill (loaded automatically by pi)
├── .pipeline_version                    # Current version tag
├── AGENTS.md                           # Master rules for AI assistants
├── README.md                           # This file
├── development.md                      # Dev log: issues, decisions, metrics
│
├── configs/                            # Unit JSON configs
│   ├── iron_directorate/               #   9 Iron Directorate unit configs
│   ├── cinderborn/                     #   9 Cinderborn unit configs
│   ├── parasitic_bloom/               #   2 configs
│   ├── harmonic_collective/           #   2 configs
│   ├── chrono_revenants/              #   2 configs
│   ├── wreckstorm_clans/              #   2 configs
│   ├── void_corsairs/                 #   2 configs
│   ├── vehicles/                      #   3 vehicle configs
│   ├── creatures/                     #   1 creature config
│   └── insectoids/                    #   2 insectoid configs
│
├── assets/
│   ├── pbr_textures/                   # 10 procedural PBR material sets
│   ├── materials/                      # Blender material library .blend
│   ├── palettes/                       # grimdark_64.gpl
│   └── units/                          # Per-asset model + render output
│
├── tools/
│   ├── pipeline_cli.py                 # UNIFIED CLI entry point (always use this)
│   ├── batch_pipeline.py               # Batch post-process + pack
│   ├── critic.py                       # Automated quality metrics
│   ├── render_queue.py                 # Render job queue manager
│   ├── queue_dashboard.py              # Web UI for queue management
│   ├── schedule_render.sh              # Cron/at scheduler script
│   ├── generate_status_icons.py        # 32×32 status effect icons
│   ├── generate_ui_elements.py         # UI button/panel/divider generation
│   ├── sync_to_ioa.py                  # Extract & copy to IoA repo
│   │
│   ├── blender/
│   │   ├── create_material_library.py  # Build grimdark_materials.blend
│   │   ├── parametric_unit_generator.py # JSON config → rigged .blend (humanoid)
│   │   ├── parametric_vehicle_generator.py # JSON config → rigged .blend (vehicle/creature/insectoid)
│   │   ├── render_8dir_v2.py           # 8-dir render with Cycles/Eevee + GPU fallback
│   │   └── tile_generator.py           # Procedural isometric tile generation
│   │
│   ├── gimp/
│   │   └── batch_pixelate.py           # Downscale + palette quantize
│   │
│   ├── pbr/
│   │   └── gen_procedural_textures.py  # PBR texture generator (10 materials)
│   │
│   └── packer/
│       └── pack_sprites.py             # Atlas packer + JSON metadata + LOD
├── docs/
│   ├── PIPELINE_V2.md                  # Pipeline architecture reference
│   ├── PARAMETRIC_CONFIG.md            # JSON config schema
│   ├── BLENDER_WORKFLOW.md             # Blender setup guide
│   ├── STYLE_GUIDE.md                  # Visual identity spec
│   └── AI_GENERATION.md                # AI prompting guide
│
└── output/
    └── v0.4.0/                         # Current output version
        ├── (character atlases)
        ├── ui/<theme>/                 # Generated UI elements
        └── tiles/<tile_set>/           # Generated tile textures
```

## Pipeline Architecture (v3)

The pipeline has evolved through three generations:

| Stage | v1 (Legacy) | v2 (Previous) | v3 (Current) |
|-------|-------------|---------------|--------------|
| **Entry** | Per-tool scripts | Per-tool scripts | **Unified CLI** (`pipeline_cli.py`) |
| **Characters** | Emission shaders | PBR + Eevee | **PBR + Cycles + GPU fallback** |
| **Animations** | Static poses | Subtle (1-9px) | **Bold (15+px frame diffs)** |
| **Materials** | 5 flat colours | 5 PBR sets | **10 PBR sets (5 NPC factions)** |
| **Tiles** | — | — | **Procedural tile pipeline** |
| **UI** | Ad-hoc script | — | **Theme-based UI pipeline** |
| **Geometry** | 630 vertices | — | **822 vertices, codpiece/tabard** |
| **Quality** | Manual check | Critic script | **Critic + visual checklist + batch** |
| **Non-humanoid** | — | — | **Vehicle, creature, insectoid body templates** |
| **Skill** | — | AGENTS.md only | **Pi skill + AGENTS.md** |

### Character Pipeline (v2 → v3 Improvements)

- **Animation intensity**: Rotation amplitudes increased 3-8× across idle/walk/attack/hurt/die. Frame diffs now 15+ pixels at 96×128.
- **Geometry detail**: Primitive segment counts increased (12→24), subsurf levels increased (1→3). 30% more vertices.
- **Side-profile**: Shoulders widened (0.26→0.30), legs spread (0.08→0.10), codpiece/tabard geometry added for E/W silhouette.
- **GPU fallback**: Auto-detects CUDA/OptiX devices, falls back to CPU if no GPU found.
- **Render modes**: `--fast` (16 samples) for iteration, `--samples N` for quality control.

### Materials Expansion

10 procedural PBR material sets covering all 7 IoA factions:

| Faction | Materials | Status |
|---------|-----------|--------|
| Iron Directorate | grimdark_metal, grimdark_leather, grimdark_fabric, imperial_gold | ✅ v2 |
| Cinderborn | chaos_rust, grimdark_metal, grimdark_leather | ✅ v2 |
| Parasitic Bloom | **bio_flesh**, grimdark_leather | ✅ v3 |
| Harmonic Collective | **chrome_white**, grimdark_metal | ✅ v3 |
| Chrono Revenants | **cyan_bone**, grimdark_metal | ✅ v3 |
| Wreckstorm Clans | **red_rust**, grimdark_metal, grimdark_leather | ✅ v3 |
| Void Corsairs | **black_silver**, grimdark_leather | ✅ v3 |

## Design Philosophy

1. **Pre-rendered 3D to 2D**: The Fallout/Diablo 2 method. Models exist in 3D, sprites are derived.
2. **True 8 Directions**: No mirroring. All 8 compass points individually rendered.
3. **Palette-Locked**: All sprites use the `grimdark_64` palette. Visual consistency is mandatory.
4. **Fully Automated**: Single CLI command → complete asset set. Zero manual Blender clicking.
5. **Deterministic**: Same config + same scripts = identical output. Git-trackable, reproducible.
6. **10 Materials**: Each faction has distinct PBR material sets. Faction coding through materials, not geometry.
7. **Quality Gates**: Every render passes automated critic analysis before being declared done.

## Render Queue & Dashboard

The render queue system allows you to queue units for rendering during the day and process them when the machine is idle (night, lunch break, etc.).

### Web Dashboard

```
http://localhost:8082    # (port auto-increments from 8080)
```

Launch with:
```bash
python3 tools/queue_dashboard.py                # default port (8080+)
python3 tools/pipeline_cli.py dashboard          # same, via CLI
python3 tools/queue_dashboard.py --port 9090     # custom port
python3 tools/queue_dashboard.py --host 0.0.0.0  # accessible from LAN
```

**Dashboard features:**
- Live render progress bar with frame count and percentage
- Queue status: queued/running/done/failed counts
- Job list with status badges and remove buttons
- **Render Now** — start processing immediately
- **Pause / Resume** — pause after current job finishes; resume later
- **Stop** — kill current render process
- Schedule time input (default 00:00) with **Install Cron** button
- Add unit to queue via text input
- Live log tail expander

### CLI Queue Management

```bash
# Add units to the queue
python3 tools/pipeline_cli.py queue add --unit iron_directorate_line_infantry
python3 tools/pipeline_cli.py queue add --unit cinderborn_cinder_cultist --priority 1

# List / status
python3 tools/pipeline_cli.py queue list
python3 tools/pipeline_cli.py queue status

# Process all queued renders (run when machine is idle)
python3 tools/pipeline_cli.py queue run --fast

# Pause (finishes current job, then stops)
python3 tools/pipeline_cli.py queue pause

# Resume (removes pause, starts processing again)
python3 tools/pipeline_cli.py queue resume

# Clean stale jobs (reset "running" → "queued" after crash)
python3 tools/pipeline_cli.py queue clean

# Clear completed/failed jobs
python3 tools/pipeline_cli.py queue clear --status done failed

# Remove a specific job
python3 tools/pipeline_cli.py queue remove --id 3
```

### Scheduler / Nightly Automation

```bash
# One-off: schedule for 2am
at 02:00 -f tools/schedule_render.sh

# Via cron (set via dashboard or manually):
crontab -e
# 0 0 * * * /path/to/tools/schedule_render.sh --fast >> /path/to/output/nightly_render.log 2>&1
```

The scheduler script handles:
- Lock files (prevents overlapping runs)
- `systemd-inhibit` (prevents sleep during renders)
- `nice` priority (yields CPU to interactive tasks)
- Per-job logging to `output/render_logs/`

### Crash Recovery

The queue system is resilient:
- **Queue file on disk** (`output/render_queue.json`) — survives reboot
- **Progress file** (`output/render_progress.json`) — real-time frame tracking
- **Auto-recovery** — `queue run` resets stale "running" jobs
- **Already-rendered detection** — skips units with existing output on disk
- **Per-job logging** — every render has its own log in `output/render_logs/`

## IoA Integration

- **Game Engine**: React frontend + Phaser 3.90
- **Grid System**: Isometric, 2:1 ratio tiles, multi-level Z-axis
- **Character Frame Size**: 96×128 px
- **Animation Frame Rate**: 12 FPS (retro tactical feel)
- **Atlas Format**: Phaser multi-atlas (PNG + JSON, RGBA8888, pivot at bottom-center)
- **Sync Command**: `python3 tools/pipeline_cli.py sync --target <ioa_atlases_path>`

## Current Output (v0.4.0)

**34 units** across 7 factions (2 playable + 5 NPC), including 28 humanoid + 6 non-humanoid (vehicles, creatures, insectoids). Each unit has 8 directions × 5 animations:

| Faction | Playable | Units | Status |
|---------|----------|-------|--------|
| Iron Directorate | ✅ Playable | line_infantry, command_officer, pathfinder_scout, storm_talons, ashrim_raiders, suppression_team, ironclad_warden, logistics_engineer, ironclad_high_command, **predator_tank** (10) | ✅ Generated, .blend, partial render |
| Cinderborn | ✅ Playable | cinder_cultist, voidtouched_legionnaire, cinder_wraith, soul_weaver, ashbound_artificer, zealot_captain, son_of_ciner, ash_stalker, warlord (9) | ✅ Generated, .blend, partial render |
| Parasitic Bloom | ❌ NPC | bloated_swarm, toxic_reaver, **swarm_beast** (3) | ✅ Configs + .blend, render pending |
| Harmonic Collective | ❌ NPC | precision_drone, logic_weaver, **gun_drone** (3) | ✅ Configs + .blend, render pending |
| Chrono Revenants | ❌ NPC | time_soldier, chrono_guardian, **chrono_scarab** (3) | ✅ Configs + .blend, render pending |
| Wreckstorm Clans | ❌ NPC | wreck_raider, scrap_boss, **battle_wagon** (3) | ✅ Configs + .blend, render pending |
| Void Corsairs | ❌ NPC | void_raider, shadow_blade, **shade_swarm** (3) | ✅ Configs + .blend, render pending |

**Body type breakdown:** 28 humanoid, 3 vehicle (predator_tank, battle_wagon, gun_drone), 1 creature (swarm_beast), 2 insectoid (chrono_scarab, shade_swarm)

**Quality metrics** (line_infantry baseline, v0.4.0):
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Frames passing critic | 234/234 | 100% | ✅ |
| Alpha coverage (N/S) | 14-15% | 10%+ | ✅ |
| Alpha coverage (E/W) | 8.4% | 6%+ | ✅ |
| Edge density | 1.7-2.9% | 1.5%+ | ✅ |
| Materials available | 10 sets | — | ✅ |
| Animation frame diffs | 15+ px | 15+ px | ✅ |

## Documentation

| Document | Purpose |
|----------|---------|
| `.pi/skills/asset-pipeline/SKILL.md` | **Pi skill** — auto-loaded when working in this directory. Full standards, architecture, and workflow reference. |
| `AGENTS.md` | Legacy master rules for AI assistants |
| `docs/PIPELINE_V2.md` | Pipeline architecture, component reference, data flow |
| `docs/BLENDER_WORKFLOW.md` | Blender setup, camera rig, PBR materials, render workflow |
| `docs/PARAMETRIC_CONFIG.md` | JSON config schema, all fields, example configs |
| `docs/STYLE_GUIDE.md` | Visual identity, resolution tables, palette specs |
| `docs/AI_GENERATION.md` | AI prompting guide |
| `development.md` | Development log: issues, decisions, metrics, session notes |

## Tool Dependencies

All free, all open-source:
- **Blender 5.1** (3D modeling + Cycles rendering)
- **Python 3.14** with **Pillow** + **numpy** (textures, post-processing, UI generation)
- No GIMP, no Aseprite, no ComfyUI, no paid services required

## License

MIT — Tools and scripts are open. Game assets belong to Imperium of Ash project.
