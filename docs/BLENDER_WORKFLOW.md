# Blender-to-Sprite Pipeline Workflow (v2)

## Imperium of Ash Asset Pipeline — 3D-to-2D Automation

> **Scope:** this document covers the **2D sprite** path (8-direction renders,
> atlases, palette, supersampling). For the **3D GLB** path — units, materials,
> environments, the acceptance gate and the workstation memory policy — read
> [`3D_ASSETS.md`](3D_ASSETS.md) instead. The two paths share Blender and the
> material library but not their settings.

## Why Blender?

The Python scripts are the operators. You never touch Blender's UI for repetitive tasks. Your job is ONLY:
1. Write/edit a JSON config for the unit
2. Run the generator + render scripts
3. Inspect output

Blender gives us:
- **Accurate isometric projection**: Camera math is exact
- **8-direction automation**: Script rotates rig, renders all frames
- **PBR material response**: Principled BSDF + normal/roughness/metallic maps = real surface detail
- **Auto-rigging**: Armature + automatic bone weights
- **Procedural animation**: NLA actions with keyframed bone rotations
- **4× supersample**: Render at 384×512, downscale to 96×128 for crisp pixels
- **Reusability**: Change JSON config → regenerate model → re-render. No manual re-modeling.

## Prerequisites

- Blender 5.1 (free, download from blender.org)
- Python 3.14 with Pillow + numpy (for post-processing)
- Material library built: `blender --background --python tools/blender/create_material_library.py`
- PBR textures generated: `python3 tools/pbr/gen_procedural_textures.py`

## One-Time Setup

```bash
# 1. Generate PBR textures (deterministic, ~1 second)
python3 tools/pbr/gen_procedural_textures.py

# 2. Build material library .blend
blender --background --python tools/blender/create_material_library.py
```

These create 25 texture files + 5 Blender materials. Only re-run if textures or materials change.

## Generating a Unit Model

```bash
# Generate from JSON config (creates .blend with mesh + armature + 5 NLA actions)
blender --background --python tools/blender/parametric_unit_generator.py \
    --config configs/iron_directorate/iron_directorate_line_infantry.json
```

What the generator does:
1. Loads 5 PBR materials from `grimdark_materials.blend`
2. Builds head, torso, shoulders, arms, legs, weapon, backpack from config
3. Applies Subdivision Surface + Bevel modifiers + smooth shading
4. UV-unwraps each part for texture mapping
5. Joins all parts into one mesh
6. Creates humanoid armature (hips→spine→chest→neck→head + 2 arms + 2 legs)
7. Parents mesh to armature with automatic bone weights
8. Creates 5 NLA actions (idle/walk/attack/hurt/die) with keyframed bone rotations
9. Saves .blend file

## Rendering 8 Directions

```bash
# Render with Cycles (best PBR quality, ~5 min/unit)
blender --background assets/units/<unit>/model/<unit>_v2.blend \
    --python tools/blender/render_8dir_v2.py -- --engine CYCLES

# Or with Eevee (faster, ~2 min/unit, lower quality)
blender --background assets/units/<unit>/model/<unit>_v2.blend \
    --python tools/blender/render_8dir_v2.py -- --engine BLENDER_EEVEE
```

What the renderer does:
1. Computes model bounding box → auto-sets ortho_scale (fills 80% of frame)
2. Sets up 3-point PBR lighting (warm key 800W, cool fill 300W, gold rim 500W)
3. Enables Filmic color management + transparent film
4. For each animation (idle/walk/attack/hurt/die):
   a. Solos the NLA action (mutes all other strips)
   b. For each direction (N/NE/E/SE/S/SW/W/NW):
      i. Rotates camera rig to angle
      ii. For each frame in animation:
          - Renders 384×512 PNG with alpha
5. Writes manifest.json

## Post-Processing + Packing

```bash
# Process all units + pack into atlases (one command)
python3 tools/batch_pipeline.py
```

What this does per unit:
1. Downscale 384×512 → 96×128 (nearest-neighbor)
2. Crop to content bounding box
3. Quantize to grimdark_64 palette (64 colors)
4. Remove noise (stray single pixels)
5. Pad to uniform 96×128 canvas
6. Shelf-pack into atlas PNG
7. Generate JSON metadata (frame keys, positions, sizes, pivots)
8. Generate LOD1 (48×64) and LOD2 (24×32) atlases

## Syncing to IoA

```bash
cp output/v0.3.0/*.png output/v0.3.0/*.json \
    "../Imperium of Ash/frontend/public/assets/atlases/"
```

Then verify the unit is in the AtlasLoader registry (`frontend/src/phaser-game/utils/AtlasLoader.ts`).

## Material Setup (PBR, not Emission)

v2 uses **Principled BSDF** with PBR texture maps. This is the critical difference from v1.

| v1 (Emission) | v2 (Principled BSDF) |
|---------------|---------------------|
| Flat solid color | Albedo texture + lighting response |
| 5 unique colors per sprite | 33-41 unique palette colors |
| No normal/roughness/metallic | Normal maps + roughness + metallic = real surface detail |
| No lighting interaction | 3-point lighting creates highlights, shadows, rim light |
| Color management OFF | Filmic + Medium High Contrast |

The material library (`grimdark_materials.blend`) contains 5 pre-built Principled BSDF materials wired to PBR textures. The generator assigns these by name from the JSON config.

## Lighting (Script-Handled)

Three-point grimdark lighting tuned for PBR:
- **Key**: Warm rusty (1.0, 0.85, 0.65), 800W area light, upper-left
- **Fill**: Cool blue (0.6, 0.7, 1.0), 300W area light, lower-right
- **Rim**: Gold (1.0, 0.82, 0.3), 500W area light, behind subject

Area lights (not point lights) for soft shadows. Set automatically by the render script.

## Camera Rig (Script-Handled)

- Orthographic camera at 30° elevation
- `ortho_scale = bbox_height / 0.80` (auto-computed from model bounds)
- Parented to an empty that rotates for 8 directions
- Renders at 384×512 (4× supersample), downscaled to 96×128

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Model renders tiny (low coverage) | ortho_scale multiplied by supersample | Ensure ortho_scale is NOT × SUPER_SAMPLE (resolution handles supersampling) |
| Flat colors, no detail | Using Emission shaders | Ensure material library has Principled BSDF materials, not Emission |
| NLA actions blend together | No action isolation | render_8dir_v2.py solos each NLA strip and mutes others |
| Animation invisible (frames identical) | Bone rotation amplitudes too small | Increase `animation_params` in JSON config (idle_intensity, walk_stride) |
| Materials not found (KeyError) | Material library not built or not loaded | Run `create_material_library.py`, ensure `use_fake_user=True` on materials |
| E/W views too thin (low coverage) | Model thinner side-on | Increase `build` parameter in config proportions |
| Double "atlas" in filename | pack_unit already appends `_atlas` | Pass unit name without `_atlas` suffix to pack_unit |

## Best Practices

- **Test one direction first**: Render a single idle_S frame to verify scale, colors, and clarity before running the full 208-frame pipeline.
- **Use Cycles for final, Eevee for iteration**: Eevee is 2× faster but lacks true PBR reflections and normal map detail.
- **Keep configs in git**: The JSON configs are the source of truth for each unit. The .blend files are generated products.
- **Adjust animation params**: Default values produce subtle movement. Increase for visible animation at 96×128.
- **Re-render after config changes**: Changing proportions/materials requires regenerating the model AND re-rendering.