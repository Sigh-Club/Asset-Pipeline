# Asset-Pipeline AGENTS.md
# Master Reference for All AI Assistants Working on IoA Sprite Assets

## Project Identity

**Repository**: asset-pipeline  
**Purpose**: Dedicated sprite and asset generation pipeline for Imperium of Ash (IoA), a grimdark tactical combat game set in the Warhammer 40K universe.  
**Method**: Pre-rendered 3D-to-2D isometric sprites, fully automated.  
**Philosophy**: Every pixel serves the grimdark aesthetic. No bright anime colors. No hand-waving. Automation over manual labor.

## Critical Rules

1. **Palette Lock**: All indexed-color assets MUST use the `grimdark_64.gpl` palette. No exceptions. Deviation breaks visual consistency.
2. **Naming Convention**: Strict enforcement. Wrong names break the engine importer.
3. **8 Directions True**: No mirroring allowed. Each direction is a unique render. N, NE, E, SE, S, SW, W, NW.
4. **Blender Single Source of Truth**: The `.blend` file is the master asset. Sprites are derived products, not masters.
5. **Version Everything**: Every output directory MUST include a version tag (e.g., `v0.1.0/`).
6. **AI Concept Only**: Gemini Pro generates concepts and references. Final sprites come from Blender render pipeline, not AI direct-to-sprite (avoids copyright/quality issues).
7. **Sync to IoA**: The `sync_to_ioa.py` tool is the ONLY approved method for copying assets into the IoA repo. No manual copying.

## IoA Integration Specs

When creating assets, reference these IoA requirements:

- **Game Engine**: React frontend (Phaser-ready if needed)
- **Grid System**: Isometric, 2:1 ratio tiles
- **Tile Footprint**: 96×48 px (width × depth)
- **Tile Canvas**: 96×128 px (allows elevation, walls, overhangs)
- **Character Frame Size**: 96×128 px
- **UI Scale**: Designed for 1080p target, scales with CSS
- **Color Theme**: Grimdark industrial — gunmetal, bone, rust, Imperial gold, hazard yellow, bruised purple, soot black, off-white, blood red
- **Animation Frame Rate Target**: 12 FPS for characters (retro tactical feel)
- **Transparency**: Alpha channel for all sprites. Black (#000000) is NOT a background color — it is a valid grimdark color. Use true alpha.

### Unit Roster Priority (IoA Phase One)
1. Imperial Guardsman (base infantry)
2. Imperial Scout (recon phase)
3. Chaos Cultist (enemy fodder)
4. Chaos Marine (heavy enemy)
5. Imperial Officer (command unit)

## File Naming Convention

```
<category>_<descriptor>_<state>_<direction?>_<frame?>.<ext>

Examples:
ui_button_attack_default.png
ui_button_attack_hover.png
ui_button_attack_active.png
ui_button_attack_disabled.png
ui_panel_frame_corner.png
tiles_ground_concrete_01.png
tiles_wall_metal_straight_N.png
tiles_wall_metal_corner_NE.png
units_imperial_guardsman_idle_N_01.png
units_imperial_guardsman_idle_N_02.png
units_imperial_guardsman_walk_NE_01.png
units_imperial_guardsman_attack_S_01.png
units_imperial_guardsman_die_SW_01.png
```

Direction suffixes (always 2-letter):
- N, NE, E, SE, S, SW, W, NW

Animation suffixes:
- idle, walk, attack, hurt, die

State suffixes (UI only):
- default, hover, active, disabled

## Blender Accuracy Guarantee

User concern: Blender experience was "terrible."  
Answer: The pipeline removes Blender's UI pain. You never manually click through render settings. The Python script (`render_8dir.py`) handles:
- Camera rig positioning (isometric angles, locked)
- Lighting setup (3-point grimdark: key = warm rusty, fill = cool blue, rim = gold)
- Render output paths (auto-organized)
- Animation sampling (frame N per direction)
- Export naming (matches convention above)
- Pixelation via compositor nodes (optional) OR raw export for GIMP refinement

Your job: Model the asset, rig if animated, save `.blend` file. Run script. Done.

## Toolchain (All Free)

| Purpose | Tool | File Type |
|---------|------|-----------|
| Concept/Reference | Gemini Pro API (user key in opencode config) | PNG/JPEG refs |
| 3D Model/Render | Blender 3.6+ | .blend |
| Sprite Cleanup | LibreSprite | .ase / .aseprite |
| Batch Processing | GIMP 2.10+ + Python-Fu | Script |
| Atlas Packing | Custom Python/Pillow | Script |
| Normal/Depth | Blender compositor or Laigter | .png |
| Palette | Shared GIMP palette | .gpl |
| Sync | Custom Python | sync_to_ioa.py |

## LOD Support

Per-unit, per-tile:
- **LOD0**: Full resolution (96×128 chars, 96×128 tiles) — default view
- **LOD1**: 50% scale (48×64) — zoomed out, many units
- **LOD2**: 25% scale (24×32) — tactical overview, minimap

Blender script generates all three in one pass. The packer assembles separate atlases per LOD.

## Documentation Mandate

Every tool, every script, every pipeline stage MUST have:
- Inline comments
- A matching doc section in `docs/`
- Usage examples in `README.md`

No undocumented code. No "I'll remember how this works."

## Git Workflow

- Main branch: `main`
- Feature branches: `feature/<thing>`
- All `.blend` source files tracked in git (they are not large if models are low-poly)
- Exported renders (PNG) tracked ONLY if they are final outputs in `output/<version>/`
- Raw render outputs (per-frame PNGs) in `assets/<unit>/render/` — add to `.gitignore` (regenerable from .blend)
- Never commit AI-generated concept art (temporary refs, keep outside repo or in `refs/`)
