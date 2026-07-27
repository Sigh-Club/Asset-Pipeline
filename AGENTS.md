# Asset-Pipeline AGENTS.md
# Master Reference for All AI Assistants Working on IoA Sprite Assets

## Project Identity

**Repository**: asset-pipeline  
**Purpose**: Dedicated sprite and asset generation pipeline for Imperium of Ash (IoA), a grimdark tactical combat game set in the Warhammer 40K universe.  
**Method**: Pre-rendered 3D-to-2D isometric sprites, fully automated.  
**Philosophy**: 2008-era quality (Dawn of War 1/2 calibre). Full RGBA colour, smooth LANCZOS downscale, detailed PBR materials, no pixel-art restrictions. Every pixel serves the grimdark aesthetic. Automation over manual labour.

## Critical Rules

1. **Full Colour, No Palette Lock**: Assets use full RGBA colour. The `grimdark_64.gpl` palette is available as an optional retro/pixel-art variant but is NOT the default. PBR materials render with full colour fidelity.
2. **LANCZOS Downscale**: Raw renders are supersampled at 8× (768×1024) and downscaled with LANCZOS resampling for smooth anti-aliased edges — never nearest-neighbour.
3. **DEVELOPMENT.md MUST BE UPDATED BEFORE ANY NEW TASK**: `docs/DEVELOPMENT.md` is the master development tracking document. After completing any task (render fix, code change, pipeline improvement, asset generation), update it before starting the next task. Mark fixed items as ✅, add new open items, update the Last Updated date. This is NOT optional.
4. **Naming Convention**: Strict enforcement. Wrong names break the engine importer.
5. **8 Directions True**: No mirroring allowed. Each direction is a unique render. N, NE, E, SE, S, SW, W, NW.
6. **Blender Single Source of Truth**: The `.blend` file is the master asset. Sprites are derived products, not masters.
7. **Version Everything**: Every output directory MUST include a version tag (e.g., `v0.5.0/`).
8. **AI Concept Only**: AI assistants generate concepts, configs, and pipeline scripts. Final sprites come from Blender render pipeline, not AI direct-to-sprite (avoids copyright/quality issues).
9. **Sync to IoA**: The `sync_to_ioa.py` tool (or manual copy to `../imperium-of-ash/frontend/public/assets/atlases/`) is the approved method. Always copy to the **correct** IoA repo.

## AI-Assisted Workflow Architecture

To make the AI assistant produce real usable assets without human Blender expertise, we implement a **Visual Critic Loop** inspired by LL3M (UChicago) and production render pipelines.

### Phase Structure

1. **Plan**: Load kit JSON, resolve body + part paths, validate files exist
2. **Code**: Assemble scene, set camera/lights, render all 8 directions
3. **Critic** (automated, no human): Analyse rendered PNGs for quality metrics
4. **Fix** (automated): Adjust lighting energy, ortho_scale, or material brightness based on critic feedback
5. **Verify** (automated): Re-render and re-analyse. Up to 3 auto-retries.
6. **Human Gate**: Present renders + quality report to user. User approves or requests changes.

### Automated Quality Metrics (Critic)

The critic script analyses every rendered frame and assigns pass/fail:

| Metric | Fail Threshold | Meaning |
|--------|---------------|---------|
| Alpha Coverage | < 6% of frame | Model too small or invisible |
| Mean Brightness | < 40/255 | Too dark, lighting insufficient |
| Brightness StdDev | < 10/255 | Flat, no detail/contrast |
| Edge Density | < 1.5% edges | Too low-poly or blurry |
| Direction Variance | < 50% between dirs | Part detachment or asymmetric rig |
| Unique Colours | < 50 unique colours | Material detail too uniform |

If any metric fails, the Fix phase adjusts:
- **Too dark**: Boost light energy ×1.5, add ambient
- **Too small/invisible**: Reduce ortho_scale ×0.7
- **Too flat**: Increase light contrast (key vs fill ratio)
- **Low edges**: Increase resolution or check model detail

### Human-in-the-Loop Protocol

The AI assistant MUST follow this chat flow:

1. **Generate**: Run full pipeline (Plan → Code → Critic → Fix → Verify)
2. **Inspect**: Read the rendered PNGs and display them inline to user
3. **Report**: State pass/fail for each metric. Do NOT say "rendered successfully" unless all metrics pass.
4. **Ask**: "Quality check: [X/5 metrics pass]. Renders attached. Approve, or adjust [lighting/materials/scale]?"
5. **Iterate**: If user requests changes, edit the creation script or render parameters and re-run.

### No MCP, No Live Blender

We run **batch mode only** (`--background`). No MCP server, no live socket.
This is intentional: MCP is unreliable for complex procedural generation and requires GUI Blender.
Our batch scripts are deterministic, version-controlled, and work on headless servers.

### Toolchain for AI Assistant

| Task | Tool | Why |
|------|------|-----|
| Concept / Style ref | AI assistant | Text prompts, config generation, pipeline scripting |
| 3D Generation | Blender 5.1 + Python scripts | Deterministic, repeatable, git-trackable |
| Visual Critique | Pillow + numpy (automated) | Fast histogram/edge analysis, no API cost |
| Post-Process | `tools/batch_process.py` | LANCZOS downscale, full RGBA, optional palette quantize |
| Pack | `tools/packer/pack_sprites.py` | Automated atlas generation with LANCZOS LOD |
| Preview | `tools/gallery_server.py` | Web-based sprite atlas browser |

## Visual Verification Mandate

**NEVER assume a render succeeded just because Blender exited without error.**
A missing light, wrong camera scale, transparent alpha, or a model smaller than a pixel will all produce "successful" renders that are blank or garbage.

**Rule: Every render MUST be visually inspected before it is declared done.**

Assessment criteria (compare to Warhammer 40K tabletop miniatures, Dawn of War 2):
1. **Silhouette readability**: At 384×512, can you identify the unit type and faction from outline alone?
2. **Material fidelity**: Do PBR materials read clearly? Can you distinguish ceramite armour from fabric under-layer from leather pouches?
3. **Proportions**: DoW2/tabletop miniature proportions are the benchmark. Armour plates should read as thick ceramite, not skin-tight cloth.
4. **Detail at full resolution**: At 384×512, can you distinguish weapon from body, helmet crest from visor, faction-specific trim and iconography?
5. **Direction consistency**: All 8 directions must look like the same unit from different angles, not 8 different models.
6. **Contrast separation**: High contrast between armour plates, under-armour, weapons, and faction accents. Miniature photography uses 10:1 key-to-fill ratios.
7. **Faction identity**: Iron Directorate = gold/blue/clean lines. Cinderborn = purple/orange/corrupted ritual markings. Each faction MUST be visually distinct even at reduced LOD levels.

If any criterion fails, the render is NOT done. Fix lighting, materials, scale, or model detail and re-render.

## IoA Integration Specs

When creating assets, reference these IoA requirements:

- **Game Engine**: React frontend + Phaser 3.90
- **Grid System**: Isometric, 2:1 ratio tiles, multi-level Z-axis
- **Tile Footprint**: 96×48 px (width × depth)
- **Tile Canvas**: 96×128 px (allows elevation, walls, overhangs)
- **Character Frame Size**: 96×128 px
- **UI Scale**: Designed for 1080p target, scales with CSS
- **Colour Theme**: Grimdark industrial — gunmetal, bone, rust, Imperial gold, hazard yellow, bruised purple, soot black, off-white, blood red
- **Animation Frame Rate Target**: 12 FPS for characters (retro tactical feel)
- **Transparency**: Alpha channel for all sprites. Black (#000000) is NOT a background colour — it is a valid grimdark colour. Use true alpha.

### Unit Roster Priority (IoA Phase One)
1. ✅ Line Infantry (T1) — Iron Directorate
2. ✅ Scout (T1) — Iron Directorate
3. ✅ Cinder Cultist (T1) — Cinderborn
4. ✅ Cinderborn Legionnaire (T3) — Cinderborn
5. ✅ Officer (T2) — Iron Directorate
6. ✅ Storm Talon (T3) — Iron Directorate
7. ✅ Cinder Wraith (T2) — Cinderborn

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
Answer: The pipeline removes Blender's UI pain. You never manually click through render settings. The Python scripts handle:
- Camera rig positioning (isometric angles, locked)
- Lighting setup (3-point grimdark: key = warm rusty, fill = cool blue, rim = gold)
- Render output paths (auto-organised)
- Animation sampling (frame N per direction)
- Export naming (matches convention above)
- Post-processing via `batch_process.py` (LANCZOS downscale, full RGBA)

Your job: Model the asset, rig if animated, save `.blend` file. Run script. Done.

## Inheritance Hierarchy

Each unit inherits from a base model, with unique headgear/armor/accessories as separate objects on top. The `promoted_from` field in the JSON config links promoted units to their base unit, enabling clean visual progression from base → promoted → highest level.

**Iron Directorate Hierarchy:**
- **Base**: `iron_directorate_line_infantry` — standard infantry
- **Promoted**: `iron_directorate_command_officer` — cape, vox_caster, pistol
- **Highest**: `iron_directorate_ironclad_high_command` — full armor, heavy weapon

**Cinderborn Hierarchy:**
- **Base**: `cinderborn_cinder_cultist` — cultist
- **Promoted**: `cinderborn_soul_weaver` — cape, vox_caster
- **Highest**: `cinderborn_warlord` — unique headgear, weapons

Each body part is a separate object with its own material, allowing independent visual treatment. The `promoted_from` field in the JSON config triggers automatic inheritance of materials, equipment, and proportions from the base unit.

**Implementation Status**: ✅ All 34 units generated with proper inheritance hierarchy.

## Render Quality Spec (v0.5.0+)

Target: miniature-level detail comparable to Warhammer 40K tabletop miniatures at isometric scale.

| Setting | v0.4.0 (old) | v0.5.0 (current) |
|---------|-------------|-------------------|
| Render engine | Cycles | Cycles |
| Final frame size | 96×128 | **384×512** (16× pixel area) |
| Render supersample (raw buffer) | 4× (384×512) | **3× (1152×1536)** |
| Cycles samples | 32 | **128 (64 fast, 256 max)** |
| Pixel count per frame | 12,288 | **196,608** |
| Colour depth | 8-bit | **16-bit** |
| Downscale method | NEAREST (pixelated) | **LANCZOS (smooth)** |
| Palette | grimdark_64 forced | **Full RGBA (palette optional)** |
| Cylinder vertices | 12 | **24** |
| Sphere segments | 12–24 | **24–32** |
| Subsurf levels | 1–3 | **3–4** |
| Bevel segments | 1–2 | **3** |
| Average vertex count | ~822 | **~2,500+** |
| Atlas max size | 4096 | **8192** |
| Post-process | batch_pixelate.py | **batch_process.py** |
| Noise removal | Yes (washes detail) | **Removed** |
| LOD downscale | NEAREST | **LANCZOS** |

All 34 units have complete render directories with 8-directional coverage for all 5 key animations (idle, walk, attack, hurt, die).

## IoA Integration Specs

When creating assets, reference these IoA requirements:

- **Game Engine**: React frontend + Phaser 3.90
- **Grid System**: Isometric, 2:1 ratio tiles, multi-level Z-axis
- **Tile Footprint**: 96×48 px (width × depth)
- **Character Frame Size**: **384×512 px** (was 96×128 — game engine must be updated to support larger sprite dimensions)
- **Tile Canvas**: 96×128 px (allows elevation, walls, overhangs)
- **Display Scale**: Sprites are displayed at native resolution (384×512). At 1080p, ~5 characters visible vertically.
- **LOD System**: LOD1 (192×256) for zoomed-out view, LOD2 (96×128) for tactical overview. All LOD downscales use LANCZOS.
- **UI Scale**: Designed for 1080p target, scales with CSS
- **Colour Theme**: Grimdark industrial — gunmetal, bone, rust, Imperial gold, hazard yellow, bruised purple, soot black, off-white, blood red
- **Animation Frame Rate Target**: 12 FPS for characters (retro tactical feel)
- **Transparency**: Alpha channel for all sprites. Black (#000000) is NOT a background colour — it is a valid grimdark colour. Use true alpha.

## Batch Render Time Estimates

Based on Cycles GPU rendering with OptiX denoising:
| Render quality | Render res | Samples | Time/frame | Time/unit (248 frames) | All 34 units |
|---------------|-----------|---------|-----------|----------------------|-------------|
| Fast iteration | 384×512 | 64 | ~5s | ~20 min | ~11 h |
| Standard quality | 1152×1536 | 64 | ~22s | ~1.5 h | ~51 h (5 nights) |
| **High quality (default)** | **1152×1536** | **128** | **~43s** | **~3 h** | **~101 h (10 nights)** |
| Ultra quality | 1152×1536 | 256 | ~86s | ~6 h | ~202 h (20 nights) |

Use the render queue for overnight batching: `pipeline_cli.py queue add --unit <name>` → `pipeline_cli.py queue run`.

## Toolchain

| Purpose | Tool | File Type |
|---------|------|-----------|
| Concept/Reference | AI assistant | Configs, scripts, analysis |
| 3D Model/Render | Blender 5.1 + Python scripts | .blend |
| Visual Critique | `tools/critic.py` (Pillow + numpy) | Script |
| Post-Process | `tools/batch_process.py` | Script (LANCZOS downscale, 16-bit RGBA) |
| Atlas Packing | `tools/packer/pack_sprites.py` | Script (8192 max atlas, LANCZOS LOD) |
| 3D Model Preview | `tools/blender/preview_model.py` | Blender script |
| Gallery Browser | `tools/gallery_server.py` (web UI) | — |
| Palette (optional) | `assets/palettes/grimdark_64.gpl` | 64 colours for retro variants |
| Sync | `pipeline_cli.py sync` | — |

## LOD Support

Per-unit, per-tile:
- **LOD0**: Full resolution (384×512 chars) — default detailed view
- **LOD1**: 50% scale (192×256) — zoomed out, many units
- **LOD2**: 25% scale (96×128) — tactical overview, minimap

All LOD downscales use LANCZOS. The packer generates all three LOD levels in one pass.

## Geometry Detail Spec

Target: miniature-level geometry density. Comparable to detailed plastic miniatures at isometric sprite scale.

| Body Part | v0.4.0 segments | v0.5.0 segments | Notes |
|-----------|----------------|----------------|-------|
| Head sphere | 24×16 | **32×24** | Smooth helmet curves, visible crest detail |
| Pauldron sphere | 12×8 | **24×16** | Visible trim, chapter/legion markings |
| All cylinders (limbs, torso) | 12 | **24** | Smooth arm/leg profiles, no faceting |
| Subsurf (head/torso) | levels 2–3 | **levels 3–4** | High-quality mesh subdivision |
| Subsurf (limbs/accessories) | levels 1–2 | **levels 2–3** | Balance detail vs generation time |
| Bevel segments | 1–2 | **3** | Smooth edge highlights on armour |
| Average vertex count | ~822 | **~2,500+** | Proper geometry density for miniature look |

## Documentation Mandate

Every tool, every script, every pipeline stage MUST have:
- Inline comments
- A matching doc section in `docs/`
- Usage examples in `README.md`
- Task tracking in `docs/DEVELOPMENT.md` (✅ for complete, OPEN for pending)

**`docs/DEVELOPMENT.md` is the master tracking document.** After every task completion, update it before moving on. This is the single source of truth for:
- Current pipeline status and known issues
- Technical decisions and their rationale
- Quality metrics and improvement targets
- Open technical debt items

No undocumented code. No "I'll remember how this works."

## AI Assistant Skill

A comprehensive pi skill is available at `.pi/skills/asset-pipeline/SKILL.md`. This skill is auto-loaded by the pi agent when working in this directory. It contains:
- Full pipeline architecture reference
- Code standards for all asset types
- Per-tool rules and common pitfalls
- Visual verification checklist
- Faction coding reference
- New unit workflow
- Known technical debt

**The skill supersedes this AGENTS.md for code-level guidance.** This file remains the master project reference for high-level rules and conventions.

## Sub-Agent Usage

For complex multi-step tasks (e.g., "regenerate all 34 units with new geometry"), consider using the pi-subagents skill to delegate parallel work. See `.pi/skills/` directory.

## Git Workflow

- Main branch: `main`
- Feature branches: `feature/<thing>`
- All `.blend` source files tracked in git
- Exported renders (PNG) tracked ONLY if they are final outputs in `output/<version>/`
- Raw render outputs (per-frame PNGs) in `assets/<unit>/render/` — add to `.gitignore` (regenerable from .blend)
- Never commit AI-generated concept art (temporary refs, keep outside repo or in `refs/`)
