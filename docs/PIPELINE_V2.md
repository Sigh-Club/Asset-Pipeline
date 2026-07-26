# Pipeline Architecture

## Imperium of Ash Asset Pipeline — v3: Multi-Asset-Type Parametric PBR Generation

## Overview

The v3 pipeline is a unified, multi-asset-type generation system for Imperium of Ash. It extends the v2 character pipeline with tile generation, UI element generation, 10 PBR materials (all 7 factions), bold combat-visible animations, enhanced geometry detail, and a unified CLI for all operations.

**Data flow:**

```
pipeline_cli.py (unified entry point)
    │
    ├── character/         JSON Config → Parametric Generator → .blend (rigged model)
    │                           → Render Pipeline → 384×512 raw frames
    │                           → Post-Processor → 96×128 palette-locked sprites
    │                           → Atlas Packer → Phaser-compatible atlas
    │
    ├── tile/              Tile Set Def → Blender Generator → .blend (tile model)
    │                           → Render Pipeline → tile textures
    │
    ├── ui/                Theme Config → Pillow Generator → PNG sprites
    │
    ├── materials/         Math Noise → PBR Texture Maps → Material Library
    │
    └── critic/            Rendered PNGs → Quality Analysis → JSON Report
```

## Why v3 Exists

v2 proved the parametric approach works — 18 units across 2 playable factions with PBR materials and NLA animations. v3 addresses the quality gaps identified during v2 development:

- **Animation intensity** was too subtle (1-9px frame diffs → now 15+px)
- **Materials** only covered 2 factions → now all 7 factions (10 materials)
- **No tile pipeline** → now procedural tile generation with 3 tile sets
- **No UI pipeline** → now Pillow-based grimdark UI elements
- **No unified entry point** → now `pipeline_cli.py` handles all operations
- **Geometry was too low-poly** → 822 vertices (was 630), subsurf level 3
- **Side-view coverage** → shoulders widened, codpiece/tabard added
- **No AI assistant guidance** → now pi skill auto-loaded in project directory

v3 replaces the old per-tool workflow with a unified CLI. Always use `pipeline_cli.py` — never run generators/renderers directly.

## Components

### 1. Procedural PBR Texture Generator

**File**: `tools/pbr/gen_procedural_textures.py`
**Input**: None (mathematical noise functions)
**Output**: `assets/pbr_textures/<material>/` (5 maps each)

Generates 10 PBR material sets using numpy/Pillow:

| Material | Use Case | Key Features |
|----------|----------|--------------|
| `grimdark_metal` | Iron Directorate armor, helmets, weapons | Gunmetal base, rust spots, broad scratches, pitting |
| `grimdark_leather` | Gloves, boots, weapon stocks | Brown base, creases, coarse grain |
| `grimdark_fabric` | Arms, thighs (fatigues) | Green weave, folds, wear |
| `imperial_gold` | Aquilas, crests, accents | Warm gold, tarnish spots |
| `chaos_rust` | Cinderborn armor, weapons | Heavy rust, blood stains, deep pitting |
| `bio_flesh` | Parasitic Bloom armor/flesh | Sickly green organic, vein networks, spore spots |
| `chrome_white` | Harmonic Collective armour | Bright white-chrome, panel lines, minimal wear |
| `cyan_bone` | Chrono Revenants | Cyan-tinted bone, porous, temporal crack glow |
| `red_rust` | Wreckstorm Clans armour | Hot red-orange rusted metal, heat scoring, burn marks |
| `black_silver` | Void Corsairs armour | Dark grey-black tactical, silver edge wear, matte finish |

Each material has 5 maps:
- `albedo.png` — base color (sRGB)
- `normal.png` — tangent-space normal map (Non-Color)
- `roughness.png` — grayscale roughness (Non-Color)
- `metallic.png` — grayscale metalness mask (Non-Color)
- `height.png` — grayscale height/displacement (Non-Color)

**Frequency tuning**: All textures use low-frequency noise (octaves 3-5, base_scale 48-128) so features survive 4× downscale + 64-color quantization. High-frequency detail vanishes at 96×128 — only broad features (panel lines, pitting, rust patches) remain visible.

**Deterministic**: Same seed = same output. Fully git-trackable.

### 2. Material Library Builder

**File**: `tools/blender/create_material_library.py`
**Input**: PBR textures from step 1
**Output**: `assets/materials/grimdark_materials.blend`

Creates 5 Blender materials using Principled BSDF shader nodes:
- Albedo → Base Color
- Normal map → Normal (via Normal Map node)
- Roughness → Roughness
- Metallic → Metallic
- UV mapping with trilinear repeat

Materials are saved with `use_fake_user = True` to prevent Blender from purging them on save (no objects reference them until models are generated).

Material names: `MAT_GrimdarkMetal`, `MAT_GrimdarkLeather`, `MAT_GrimdarkFabric`, `MAT_ImperialGold`, `MAT_ChaosRust`

### 3. Parametric Unit Generator

**File**: `tools/blender/parametric_unit_generator.py`
**Input**: JSON config file
**Output**: `.blend` file with mesh + armature + 5 NLA actions

The core of the v2 pipeline. Reads a JSON config describing a unit's proportions, materials, weapon, and equipment, then:

1. **Loads materials** from the material library .blend (via `bpy.ops.wm.append`)
2. **Builds body parts** parametrically:
   - Head/helmet (sphere, scaled, with optional visor + crest)
   - Torso (tapered box with Subsurf + Bevel, optional aquila)
   - Shoulders (pauldron spheres, flattened)
   - Arms (upper arm + forearm cylinders, different materials)
   - Legs (thigh + shin cylinders + boot box)
   - Weapon (rifle/pistol/melee/heavy/none, positioned at right hand)
   - Backpack (optional, behind torso)
3. **Joins all parts** into a single mesh object
4. **Creates armature** with standard humanoid bone hierarchy:
   - Hips → Chest → Neck → Head
   - Thigh_L/R → Shin_L/R → Foot_L/R
   - UpperArm_L/R → Forearm_L/R → Hand_L/R
5. **Parents mesh to armature** with automatic bone weights (`bpy.ops.object.parent_set(type='ARMATURE_AUTO')`)
6. **Creates 5 procedural NLA actions** using Blender 5.1's layered Action API:
   - Action → Layer → Strip → ChannelBag → FCurves → Keyframes
   - Each action is added as an NLA track/strip for isolation at render time
7. **Saves .blend** to the path specified in the config

**Animation details**:
- `idle` (frames 1-4): Breathing, subtle arm sway, head bob
- `walk` (frames 10-16): Alternating leg/arm swings, torso bob
- `attack` (frames 20-24): Wind-up, strike, recover (right arm thrust)
- `hurt` (frames 30-32): Recoil backward, head snap
- `die` (frames 40-46): Collapse forward, go limp

**Note**: Animation intensity is currently subtle (1-9 pixel frame diffs). Adjust `animation_params` in the JSON config to increase intensity. The bone rotation amplitudes need to be larger for visible movement at 96×128.

### 4. Render Pipeline v2

**File**: `tools/blender/render_8dir_v2.py`
**Input**: .blend file (from step 3)
**Output**: 208 PNG frames at 384×512 + manifest.json

Key features:
- **4× supersample**: Renders at 384×512 (4× the 96×128 target), downscales with nearest-neighbor. This preserves hard edges from PBR material detail before palette quantization.
- **Cycles or Eevee**: Cycles for true PBR (reflections, normal maps, displacement). Eevee for speed (~2s/frame vs ~1.5s/frame, but lower quality).
- **Filmic color management**: `view_transform = Filmic`, `look = Medium High Contrast`. Required for proper PBR material response.
- **3-point PBR lighting**:
  - Key: warm (1.0, 0.85, 0.65), 800W area light, upper-left
  - Fill: cool (0.6, 0.7, 1.0), 300W area light, lower-right
  - Rim: gold (1.0, 0.82, 0.3), 500W area light, behind
- **NLA action isolation**: Before rendering each animation, the script:
  - Sets `armature.animation_data.action = action` (for standalone actions)
  - Mutes all NLA strips except the target strip (for NLA-based actions)
  - Disables NLA evaluation when using active action mode
- **Ortho camera**: Auto-computed `ortho_scale = bbox_height / 0.80` (fills 80% of frame height). NOT multiplied by supersample factor — resolution handles that.
- **8 directions**: N(0°), NE(45°), E(90°), SE(135°), S(180°), SW(225°), W(270°), NW(315°)

**Important**: `ortho_scale` must NOT be multiplied by `SUPER_SAMPLE`. The supersample is handled by render resolution (384×512), not camera scale. This was a bug in early v2 that made models render at 0.7% coverage.

### 5. Post-Processor

**File**: `tools/gimp/batch_pixelate.py` (updated for v2)
**Input**: 384×512 raw renders
**Output**: 96×128 palette-locked sprites

Process per frame:
1. **Downscale** 384×512 → 96×128 with `Image.NEAREST` (preserves hard edges)
2. **Crop** to content bounding box (remove excess transparency)
3. **Quantize** to grimdark_64 palette (nearest-color matching)
4. **Noise removal** (remove stray single pixels)
5. **Pad** to uniform 96×128 canvas (bottom-center origin)

The v2 update added step 1 (downscale) — the v1 `process_frame` assumed input was already at target size.

### 6. Atlas Packer

**File**: `tools/packer/pack_sprites.py`
**Input**: 96×128 processed frames
**Output**: Atlas PNG + JSON + LOD1/LOD2

- Shelf-packing algorithm
- Frame keys: `{animation}_{direction}_frame_{N}` (e.g., `idle_S_frame_01`)
- JSON format: Phaser multi-atlas compatible (RGBA8888, sourceSize 96×128, pivot 0.5/1.0)
- LOD1: 50% scale (48×64), LOD2: 25% scale (24×32)

### 7. Batch Pipeline

**File**: `tools/batch_pipeline.py`
**Input**: All unit render directories
**Output**: All atlases in `output/v0.3.0/`

Orchestrates post-processing + packing for all 18 units in one pass. Scans `assets/units/*/model/render/raw/` for units with renders, processes each, and packs into atlases.

## IoA Integration

### AtlasLoader Registry

**File**: `frontend/src/phaser-game/utils/AtlasLoader.ts` (in IoA repo)

The AtlasLoader has a registry mapping unit slugs to atlas file paths. Updated in v2 to include all 18 units:

```typescript
const ATLAS_REGISTRY: AtlasConfig[] = [
  // Iron Directorate (9 units)
  { slug: 'iron_directorate_line_infantry', path: 'assets/atlases/iron_directorate_line_infantry_atlas' },
  { slug: 'iron_directorate_command_officer', path: 'assets/atlases/iron_directorate_command_officer_atlas' },
  // ... etc
  // Cinderborn (9 units)
  { slug: 'cinderborn_cinder_cultist', path: 'assets/atlases/cinderborn_cinder_cultist_atlas' },
  // ... etc
];
```

### AssetMapper

**File**: `frontend/src/phaser-game/utils/AssetMapper.ts` (in IoA repo)

Maps backend unit type strings to sprite slugs. The `resolveAtlasKey` method checks the AtlasLoader registry to determine if an atlas exists for a given unit.

### Sync

Copy atlases to IoA:
```bash
cp output/v0.3.0/*.png output/v0.3.0/*.json \
    "../Imperium of Ash/frontend/public/assets/atlases/"
```

## Quality Metrics

Measured on v2 output (Eevee render, 64-color palette quantization):

| Metric | v1 (Emission) | v2 (PBR + Cycles) | Threshold |
|--------|:---:|:---:|:---:|
| Unique colors (avg) | 5 | 30-41 | — |
| Brightness std | 32 | 44-50 | >10 |
| Alpha coverage | 15% | 8-16% | >6% |
| Frame size | 96×128 | 96×128 | 96×128 |
| Atlas format | RGBA8888 | RGBA8888 | RGBA8888 |
| Pivot | (0.5, 1.0) | (0.5, 1.0) | (0.5, 1.0) |

## Known Issues

1. **Animation intensity**: Frame diffs are 1-9 pixels (near-invisible). Need to increase bone rotation amplitudes in the `animate_*` functions or `animation_params` in JSON configs.
2. **Side-view coverage**: E/W directions have ~8% alpha coverage vs ~13% for front/back. Models are thinner side-on. Fix by widening stance or shoulder breadth.
3. **Geometry Nodes rivets**: The Blender 5.1 API for `DistributePointsOnFaces` changed. Rivets on armor surfaces are disabled pending API fix.
4. **Eevee vs Cycles**: All 18 units rendered with Eevee for speed. Cycles re-render would add real PBR reflections and better normal map response.

## What's NOT Covered (Future Work)

| Category | Status | What's Needed |
|----------|--------|---------------|
| Non-humanoid NPC factions | Not started | New body-type templates (insectoid, skeletal, mecha, vehicle) |
| Tiles | Not started | Separate Blender template for isometric tiles |
| UI elements | Not started | 2D asset generation or separate template |
| VFX/particles | Not started | Separate pipeline |
| NPC factions (humanoid) | **All 10 configs + .blend files created** | 10 unit configs across 5 factions. Renders pending. |

## v3 Changes Over v2

### Animation Rewrite

The `animate_*` functions in `parametric_unit_generator.py` were completely rewritten with 3-8× larger rotation amplitudes:

| Animation | v2 (subtle) | v3 (bold) | Pixel effect at 96×128 |
|-----------|-------------|-----------|----------------------|
| idle chest | 0.003 BU | 0.10 BU | ~8px breathing |
| idle arm sway | 0.006 rad | 0.25 rad | ~15px weapon drift |
| walk stride | 0.15 rad | 0.60 rad | ~30px leg swing |
| walk torso bob | 0.01 BU | 0.05 BU | ~4px bounce |
| attack swing | 0.9 rad max | 2.7 rad max | ~70px strike arc |
| hurt recoil | 0.3 rad | 0.8 rad | ~25px flinch |
| die collapse | 1.2 rad | 1.8 rad | ~45px fall |

### Geometry Enhancement

- All primitive segment counts increased (spheres 16→24 ring, cylinders 12→16 verts)
- Subsurf render levels increased to 3 for all body parts
- Bevel segments increased to 2 for sharper edge highlights
- Side-profile geometry: codpiece (Iron Directorate) / tabard (Cinderborn)
- Total vertex count: ~630 → ~822 (+30%)

### GPU Fallback

The render script now auto-detects GPU compute devices (CUDA/OptiX) and falls back to CPU rendering if none are available. No more crashes on headless systems or misconfigured Blender installs.

### Render Modes

- `--fast` flag: 16 Cycles samples for quick iteration (~2.5 min per unit)
- `--samples N`: Override samples for quality control (default: 32)
- Default: 32 Cycles samples with OpenImageDenoise

### Unified CLI

All operations go through `pipeline_cli.py`:

```
python3 tools/pipeline_cli.py character full --config <path>   # Full end-to-end
python3 tools/pipeline_cli.py character fast --config <path>   # Quick iteration
python3 tools/pipeline_cli.py tile generate --tile-set <name>  # Tiles
python3 tools/pipeline_cli.py ui buttons --theme <name>         # UI
python3 tools/pipeline_cli.py materials generate               # Rebuild materials
python3 tools/pipeline_cli.py critic batch                     # Quality check all
python3 tools/pipeline_cli.py sync --target <path>             # Sync to IoA
```