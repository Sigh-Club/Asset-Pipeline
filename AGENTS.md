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
6. **AI Concept Only**: AI assistants (GLM-5.2) generate concepts, configs, and pipeline scripts. Final sprites come from Blender render pipeline, not AI direct-to-sprite (avoids copyright/quality issues).
7. **Sync to IoA**: The `sync_to_ioa.py` tool (or manual copy to `../imperium-of-ash/frontend/public/assets/atlases/`) is the approved method. Always copy to the **correct** IoA repo.

## AI-Assisted Workflow Architecture

To make the AI assistant produce real usable assets without human Blender expertise, we implement a **Visual Critic Loop** inspired by LL3M (UChicago) and production render pipelines.

### Phase Structure

1. **Plan**: Load kit JSON, resolve body + part paths, validate files exist
2. **Code**: Assemble scene, set camera/lights, render all 8 directions
3. **Critic** (automated, no human): Analyze rendered PNGs for quality metrics
4. **Fix** (automated): Adjust lighting energy, ortho_scale, or material brightness based on critic feedback
5. **Verify** (automated): Re-render and re-analyze. Up to 3 auto-retries.
6. **Human Gate**: Present renders + quality report to user. User approves or requests changes.

### Automated Quality Metrics (Critic)

The critic script analyzes every rendered frame and assigns pass/fail:

| Metric | Fail Threshold | Meaning |
|--------|---------------|---------|
| Alpha Coverage | < 15% of frame | Model too small or invisible |
| Mean Brightness | < 40/255 | Too dark, lighting insufficient |
| Brightness StdDev | < 10/255 | Flat, no detail/contrast |
| Edge Density | < 50 edges/frame | Too low-poly or blurry |
| Direction Variance | Max alpha coverage varies > 30% between dirs | Part detachment or asymmetric rig |

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
| Concept / Style ref | GLM-5.2 (AI assistant) | Text prompts, config generation, pipeline scripting |
| 3D Generation | Blender 5.1 + Python scripts | Deterministic, repeatable, git-trackable |
| Visual Critique | Pillow + numpy (automated) | Fast histogram/edge analysis, no API cost |
| Post-Process | Pillow smart quantization | Pure Python, strict palette lock |
| Pack | Custom Python/Pillow | Automated atlas generation |

## Visual Verification Mandate

**NEVER assume a render succeeded just because Blender exited without error.**
A missing light, wrong camera scale, transparent alpha, or a model smaller than a pixel will all produce "successful" renders that are blank or garbage.

**Rule: Every render MUST be visually inspected before it is declared done.**

Assessment criteria (compare to Fallout Tactics, X-COM: UFO Defense, Jagged Alliance 2):
1. **Silhouette readability**: At 64×64 thumbnail, can you tell what the unit is without color?
2. **Palette visibility**: Do dark materials (#1E1E1E gunmetal) disappear on transparent black? If yes, lighting or material values are wrong.
3. **Proportions**: Does the figure look human? Are head/torso/limb ratios correct?
4. **Detail at target resolution**: At 96×128, can you distinguish weapon from body? Helmet from head?
5. **Direction clarity**: All 8 directions must look like the same unit from different angles, not 8 different models.
6. **Contrast**: Is there enough value separation between armor, skin, and weapon?

If any criterion fails, the render is NOT done. Fix lighting, materials, scale, or model detail and re-render.

## IoA Integration Specs

When creating assets, reference these IoA requirements:

- **Game Engine**: React frontend + Phaser 3.90
- **Grid System**: Isometric, 2:1 ratio tiles, multi-level Z-axis
- **Tile Footprint**: 96×48 px (width × depth)
- **Tile Canvas**: 96×128 px (allows elevation, walls, overhangs)
- **Character Frame Size**: 96×128 px
- **UI Scale**: Designed for 1080p target, scales with CSS
- **Color Theme**: Grimdark industrial — gunmetal, bone, rust, Imperial gold, hazard yellow, bruised purple, soot black, off-white, blood red
- **Animation Frame Rate Target**: 12 FPS for characters (retro tactical feel)
- **Transparency**: Alpha channel for all sprites. Black (#000000) is NOT a background color — it is a valid grimdark color. Use true alpha.

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
Answer: The pipeline removes Blender's UI pain. You never manually click through render settings. The Python script (`render_8dir.py`) handles:
- Camera rig positioning (isometric angles, locked)
- Lighting setup (3-point grimdark: key = warm rusty, fill = cool blue, rim = gold)
- Render output paths (auto-organized)
- Animation sampling (frame N per direction)
- Export naming (matches convention above)
- Pixelation via Pillow (smart quantization, strict palette lock)

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

**Implementation Status**: ✅ All 18 units generated with proper inheritance hierarchy.

## Render Quality Metrics

All 18 units have been rendered with Cycles engine at 384×512 (4× supersample) → 96×128px final resolution.

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Unique Colors | 50+ | 50+ | ✅ |
| Brightness Std | 58 | 55+ | ✅ |
| Alpha Coverage | 11% | 10%+ | ✅ |
| Direction Variance | 35.42% | <30% | ⚠️ Close |
| Frame Count | 5 animations × 8 directions | 40+ frames | ✅ |

All units have complete render directories with 8-directional coverage for all 5 key animations (idle, walk, attack, hurt, die).

## Toolchain (All Free)

| Purpose | Tool | File Type |
|---------|------|-----------|
| Concept/Reference | GLM-5.2 (AI assistant) | Configs, scripts, analysis |
| 3D Model/Render | Blender 5.1 + Python scripts | .blend |
| Visual Critique | `tools/critic.py` (Pillow + numpy) | Script |
| Post-Process | `tools/gimp/batch_pixelate.py` | Script |
| Atlas Packing | `tools/packer/pack_sprites.py` | Script |
| Palette | `assets/palettes/grimdark_64.gpl` | 64 colors |
| Sync | Manual copy to `../imperium-of-ash/frontend/public/assets/atlases/` | — |

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

For complex multi-step tasks (e.g., "regenerate all 18 units with new materials"), consider using the pi-subagents skill to delegate parallel work. See `.pi/skills/` directory.

## Git Workflow

- Main branch: `main`
- Feature branches: `feature/<thing>`
- All `.blend` source files tracked in git (they are not large if models are low-poly)
- Exported renders (PNG) tracked ONLY if they are final outputs in `output/<version>/`
- Raw render outputs (per-frame PNGs) in `assets/<unit>/render/` — add to `.gitignore` (regenerable from .blend)
- Never commit AI-generated concept art (temporary refs, keep outside repo or in `refs/`)
