# Parametric Unit Config Reference

> **Status 2026-11-09:** the parametric path is **retired for characters** (the
> output was a disconnected kitbash) and remains valid for **hard-surface props
> and vehicles**. Character units are now built from image-to-3D meshes — see
> [`3D_ASSETS.md`](3D_ASSETS.md). The JSON schema below still describes the prop
> and vehicle configs in `configs/`.

## Imperium of Ash Asset Pipeline — JSON Config Schema

## Overview

Each unit is defined by a JSON config file in `configs/<faction>/<unit_name>.json`. The parametric generator (`tools/blender/parametric_unit_generator.py`) reads this file and produces a complete rigged Blender model with PBR materials and procedural animations.

## Schema

```json
{
    "unit_name": "iron_directorate_line_infantry",
    "faction": "iron_directorate",
    "output_blend": "assets/units/iron_directorate_line_infantry/model/line_infantry_v2.blend",
    
    "proportions": {
        "height": 1.22,
        "build": 1.0,
        "leg_ratio": 0.42,
        "arm_ratio": 0.34,
        "head_ratio": 0.14
    },
    
    "materials": {
        "helmet": "MAT_GrimdarkMetal",
        "torso": "MAT_GrimdarkMetal",
        "shoulders": "MAT_GrimdarkMetal",
        "upper_arms": "MAT_GrimdarkFabric",
        "forearms": "MAT_GrimdarkLeather",
        "thighs": "MAT_GrimdarkFabric",
        "shins": "MAT_GrimdarkMetal",
        "boots": "MAT_GrimdarkLeather",
        "weapon_body": "MAT_GrimdarkMetal",
        "weapon_stock": "MAT_GrimdarkLeather",
        "accent": "MAT_ImperialGold"
    },
    
    "weapon": {
        "type": "rifle",
        "position": "right_hand"
    },
    
    "equipment": {
        "backpack": true,
        "pauldrons": true,
        "crest": true,
        "visor": true,
        "aquila": true
    },
    
    "animation_params": {
        "idle_intensity": 1.0,
        "walk_stride": 0.4,
        "attack_speed": 1.5
    }
}
```

## Field Reference

### `unit_name` (required)

The slug used for the unit across the pipeline. Must match the directory name in `assets/units/` and the atlas filename in IoA.

**Convention**: `{faction}_{unit_type}` (e.g., `iron_directorate_line_infantry`, `cinderborn_cinder_cultist`)

### `faction` (required)

Faction identifier. Used for organization only — does not affect model generation directly.

**Values**: `iron_directorate`, `cinderborn`

### `output_blend` (required)

Path where the generated .blend file is saved. Relative to project root.

**Convention**: `assets/units/{unit_name}/model/{unit_name}_v2.blend`

### `proportions` (required)

Controls the model's physical dimensions. All values are in Blender units.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `height` | float | 1.22 | Total height in Blender units. ~1.22 = standard human, ~1.40 = large hero |
| `build` | float | 1.0 | Body width multiplier. 0.85 = lean, 1.0 = standard, 1.35 = very bulky |
| `leg_ratio` | float | 0.42 | Legs as fraction of total height. 0.42 = standard, 0.38 = short-legged |
| `arm_ratio` | float | 0.34 | Arms as fraction of total height |
| `head_ratio` | float | 0.14 | Head as fraction of total height |

**Example presets**:
- Standard infantry: `height=1.22, build=1.0`
- Scout/light: `height=1.15, build=0.85`
- Heavy: `height=1.22, build=1.35`
- Hero/large: `height=1.40, build=1.20`

### `materials` (required)

Maps body parts to material names from the material library. Available materials:

| Material | Appearance | Use For |
|----------|-----------|---------|
| `MAT_GrimdarkMetal` | Dark gunmetal, rust spots, pitting | Iron Directorate armor, helmets, weapons |
| `MAT_GrimdarkLeather` | Worn brown leather, creases | Gloves, boots, weapon stocks |
| `MAT_GrimdarkFabric` | Military green fabric, weave | Fatigues (arms, thighs) |
| `MAT_ImperialGold` | Warm gold, tarnish | Aquilas, crests, officer accents |
| `MAT_ChaosRust` | Heavy rust, blood stains, deep pitting | Cinderborn armor, weapons |
| `MAT_BioFlesh` | Sickly green organic, veins, spores | Parasitic Bloom armor/flesh |
| `MAT_ChromeWhite` | Bright white-chrome, panel lines | Harmonic Collective armour |
| `MAT_CyanBone` | Cyan-tinted bone, porous, temporal cracks | Chrono Revenants |
| `MAT_RedRust` | Hot red-orange rusted metal, battle wear | Wreckstorm Clans armour |
| `MAT_BlackSilver` | Dark grey-black tactical, silver edge wear | Void Corsairs armour |

**Material slots** (each maps to a body part):

| Slot | Body Part |
|------|----------|
| `helmet` | Head/helmet sphere |
| `torso` | Chest armor box |
| `shoulders` | Pauldron spheres |
| `upper_arms` | Upper arm cylinders |
| `forearms` | Forearm cylinders (gloves) |
| `thighs` | Thigh cylinders |
| `shins` | Shin cylinders (armor) |
| `boots` | Boot boxes |
| `weapon_body` | Weapon main body |
| `weapon_stock` | Weapon stock/grip |
| `accent` | Small decorative elements (aquila, crest) |

### `weapon` (required)

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `type` | string | `rifle`, `pistol`, `melee`, `heavy`, `none` | Weapon shape |
| `position` | string | `right_hand` | Where weapon is held (currently only right_hand) |

**Weapon types**:
- `rifle`: Long body + barrel + stock (lasgun, pulse rifle)
- `pistol`: Short body (bolt pistol, plasma pistol)
- `melee`: Long blade/cylinder (chainsword, power sword)
- `heavy`: Large body + ammo drum (heavy bolter, autocannon)
- `none`: No weapon

### `equipment` (required)

Boolean flags for optional body parts:

| Field | Default | Adds |
|-------|---------|------|
| `backpack` | true | Backpack box behind torso |
| `pauldrons` | true | Shoulder armor spheres |
| `crest` | true | Small ridge on top of helmet |
| `visor` | true | Thin slit on front of helmet |
| `aquila` | true | Small gold emblem on chest front |

**Design guide**: Reduce equipment for stealth units (scouts: no pauldrons, no crest). Add more for heavy units (wardens: large pauldrons, backpack, visor, crest).

### `animation_params` (required)

Controls procedural animation intensity:

| Field | Default | Effect |
|-------|---------|--------|
| `idle_intensity` | 1.0 | Breathing amplitude + arm/weapon sway. At 1.0, chest rises ~8px at 96×128 |
| `walk_stride` | 0.4 | Step length. At 0.4, legs swing ~30px. Arms counter-swing naturally |
| `attack_speed` | 1.5 | Attack speed multiplier. Higher = faster strike/recover cycle |

**Note**: The base animation code was rewritten in v3 for bold, combat-visible movement. At current defaults, frame diffs are 15+ pixels at 96×128. Reduce values for subtle animations (e.g., civilian NPCs: `idle_intensity: 0.3, walk_stride: 0.15, attack_speed: 1.0`).

## Current Configs

### Iron Directorate (9 units)

| Unit | Build | Height | Weapon | Key Equipment |
|------|-------|--------|--------|---------------|
| line_infantry | 1.0 | 1.22 | rifle | Full (backpack, pauldrons, crest, visor, aquila) |
| command_officer | 1.1 | 1.28 | pistol | Full + larger pauldrons |
| pathfinder_scout | 0.85 | 1.15 | rifle | Minimal (no pauldrons, no crest, small backpack) |
| storm_talons | 1.3 | 1.22 | heavy | Full + large pauldrons |
| ashrim_raiders | 1.0 | 1.22 | rifle | Pauldrons, no crest |
| suppression_team | 1.15 | 1.22 | heavy | Full |
| ironclad_warden | 1.35 | 1.22 | melee | Full metal, large pauldrons, no backpack |
| logistics_engineer | 1.0 | 1.22 | pistol | No pauldrons, no crest, backpack |
| ironclad_high_command | 1.2 | 1.35 | pistol | Full + gold heavy, large everything |

### Cinderborn (9 units)

| Unit | Build | Height | Weapon | Key Materials |
|------|-------|--------|--------|---------------|
| cinder_cultist | 0.9 | 1.18 | pistol | ChaosRust torso, no pauldrons |
| voidtouched_legionnaire | 1.0 | 1.22 | rifle | ChaosRust armor, pauldrons |
| cinder_wraith | 0.75 | 1.15 | melee | All ChaosRust, no pauldrons, no backpack |
| soul_weaver | 0.85 | 1.18 | pistol | ChaosRust + leather, no pauldrons |
| ashbound_artificer | 1.0 | 1.22 | heavy | Metal + ChaosRust, pauldrons |
| zealot_captain | 1.1 | 1.25 | melee | ChaosRust + gold, large pauldrons, crest |
| son_of_ciner | 1.2 | 1.40 | heavy | All ChaosRust, large pauldrons, no backpack |
| ash_stalker | 0.85 | 1.15 | rifle | Fabric + leather (stealthy), no pauldrons |
| warlord | 1.25 | 1.30 | melee | ChaosRust + gold, large pauldrons, crest |

### NPC Factions (10 units)

| Faction | Unit | Build | Height | Weapon | Key Materials |
|---------|------|-------|--------|--------|---------------|
| Parasitic Bloom | bloated_swarm | 1.15 | 1.18 | melee | bio_flesh all, no backpack |
| Parasitic Bloom | toxic_reaver | 1.0 | 1.22 | rifle | bio_flesh + leather, backpack |
| Harmonic Collective | precision_drone | 0.90 | 1.20 | rifle | chrome_white all, pauldrons |
| Harmonic Collective | logic_weaver | 1.0 | 1.25 | heavy | chrome_white + gold, backpack |
| Chrono Revenants | time_soldier | 0.95 | 1.20 | rifle | cyan_bone + metal, backpack |
| Chrono Revenants | chrono_guardian | 1.2 | 1.30 | melee | cyan_bone all, no backpack |
| Wreckstorm Clans | wreck_raider | 1.05 | 1.22 | rifle | red_rust + metal, backpack |
| Wreckstorm Clans | scrap_boss | 1.3 | 1.35 | heavy | red_rust all, large everything |
| Void Corsairs | void_raider | 1.0 | 1.22 | rifle | black_silver + leather, backpack |
| Void Corsairs | shadow_blade | 0.85 | 1.18 | pistol | black_silver + leather, stealth |

## Adding a New Unit

1. Create a JSON config in `configs/<faction>/<unit_name>.json`
2. Generate the model (via pipeline CLI):
   ```bash
   python3 tools/pipeline_cli.py character generate --config configs/<faction>/<unit_name>.json
   ```
3. Render (use --fast for iteration, full quality for final):
   ```bash
   blender --background assets/units/<unit_name>/model/<unit_name>_v2.blend \
       --python tools/blender/render_8dir_v2.py -- --engine CYCLES --fast
   ```
4. Quality check:
   ```bash
   python3 tools/critic.py assets/units/<unit_name>/model/render/raw/
   ```
5. Post-process + pack (set version via env var):
   ```bash
   PIPELINE_VERSION=v0.4.0 python3 tools/batch_pipeline.py
   ```
6. Sync to IoA:
   ```bash
   cp output/v0.4.0/<unit_name>_atlas*.png output/v0.4.0/<unit_name>_atlas*.json \
       "../Imperium of Ash/frontend/public/assets/atlases/"
   ```
7. Add to AtlasLoader registry in `frontend/src/phaser-game/utils/AtlasLoader.ts`