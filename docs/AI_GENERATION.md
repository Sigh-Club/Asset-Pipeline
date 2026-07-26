# AI Generation Workflow

## Imperium of Ash Asset Pipeline — GLM-5.2 Integration

## Role of AI in This Pipeline

**GLM-5.2 is a pipeline architect and script writer, NOT a final asset generator.**
It generates unit configs, writes Blender Python scripts, analyzes render quality, and troubleshoots API issues. Final sprites come from the Blender render pipeline — deterministic, palette-locked, git-trackable.

**Why not AI direct-to-sprite?**
- Copyright risk: AI training data unclear, output not safely ownable
- Inconsistency: AI struggles with 8-direction consistency, palette-locking, exact frame sizes
- Control: Blender gives exact angles, exact colors, exact timing
- Scale: Re-rendering 5 animations x 8 directions for 18 units = ~3,700 frames. Blender scripting is deterministic; AI batch generation is not.
- Determinism: Same config + same scripts = identical output. AI varies between runs.
- Reproducibility: .blend files + JSON configs are git-trackable. AI-generated images are opaque binary blobs that can't be regenerated from source.

## What GLM-5.2 Does

### 1. Pipeline Architecture and Scripting

GLM-5.2 writes and maintains all pipeline scripts:
- `tools/pbr/gen_procedural_textures.py` — PBR texture generator
- `tools/blender/create_material_library.py` — Blender material library builder
- `tools/blender/parametric_unit_generator.py` — JSON config to rigged model
- `tools/blender/render_8dir_v2.py` — 8-direction render pipeline
- `tools/gimp/batch_pixelate.py` — Post-processing (downscale + palette quantize)
- `tools/packer/pack_sprites.py` — Atlas packer
- `tools/batch_pipeline.py` — Batch orchestration

This includes debugging Blender 5.1 API changes (layered Actions, NLA strip creation, ChannelBag fcurves) and writing workarounds.

### 2. Unit Config Generation

GLM-5.2 writes JSON configs for each unit based on faction lore and game design docs:
- Proportions (height, build, limb ratios)
- Material assignments (which PBR material on which body part)
- Weapon type and equipment flags
- Animation parameters

See `docs/PARAMETRIC_CONFIG.md` for the full schema.

### 3. Quality Analysis

GLM-5.2 runs the critic analysis (`tools/critic.py`) on rendered output and interprets results:
- Alpha coverage (model visibility)
- Mean brightness (lighting adequacy)
- Brightness std (contrast/detail)
- Unique color count (palette utilization)
- Direction variance (model consistency)

It then diagnoses failures (too dark = lighting, too small = ortho_scale, flat = wrong materials) and applies fixes.

### 4. Troubleshooting and Debugging

When the pipeline breaks, GLM-5.2:
- Reads error output from Blender
- Identifies API version mismatches (Blender 5.1 changed many APIs)
- Writes fixes (new API calls, workarounds)
- Tests fixes by re-running the pipeline
- Records issues and fixes in `development.md`

## What GLM-5.2 Does NOT Do

- Does NOT generate sprite images directly (no diffusion, no img2img)
- Does NOT generate 3D models via AI (no TripoSR, no image-to-mesh)
- Does NOT make artistic decisions without user approval
- Does NOT use paid APIs or external services

## Pipeline vs AI-Direct Comparison

| Approach | GLM-5.2 + Blender Pipeline | AI Direct-to-Sprite |
|----------|---------------------------|---------------------|
| Determinism | Same input = same output | Varies between runs |
| Reproducibility | .blend + JSON in git | Binary blobs, can't regenerate |
| 8-direction consistency | Exact (same 3D model rotated) | AI struggles |
| Palette lock | Enforced (64-color quantize) | AI ignores palettes |
| Cost | Free (Blender + Python) | Needs GPU + model downloads |
| Quality control | Critic metrics + visual inspection | Hope for the best |
| Copyright | Fully owned (procedural) | Unclear training data |
| Animation | Procedural NLA actions | AI can't do frame-by-frame |
| Scalability | JSON config per unit (~1 min) | Each unit needs prompt engineering |

## How to Use GLM-5.2 for Asset Work

### Generating a new unit

Tell GLM-5.2:
> "Create a config for a new Cinderborn unit called 'cinderborn_blood_priest'. It should be a lean caster with a pistol, chaos rust robes, no pauldrons, no backpack. Height 1.18, build 0.85."

GLM-5.2 will:
1. Write `configs/cinderborn/cinderborn_blood_priest.json`
2. Run the generator: `blender --background --python tools/blender/parametric_unit_generator.py -- --config configs/cinderborn/cinderborn_blood_priest.json`
3. Run the renderer
4. Run post-processing + packing
5. Sync to IoA

### Diagnosing a render problem

Tell GLM-5.2:
> "The cinder_wraith renders are too dark. What's wrong?"

GLM-5.2 will:
1. Run `critic.py` on the renders
2. Check brightness metrics
3. Inspect material assignments in the config
4. Check lighting setup in `render_8dir_v2.py`
5. Propose and apply a fix (adjust material, boost light energy, etc.)
6. Re-render and verify

### Adding a new material

Tell GLM-5.2:
> "Add a 'grimdark_bone' material — off-white, porous, for skeleton units."

GLM-5.2 will:
1. Add a `gen_grimdark_bone()` function to `gen_procedural_textures.py`
2. Regenerate textures
3. Add the material to `create_material_library.py`
4. Rebuild the material library .blend
5. It's now available in any unit config's `"materials"` section

## Model Information

**Current AI model**: `ollama-cloud/glm-5.2`
**Hardware**: AMD Ryzen 7 5700X3D, RTX 3070 Ti (8GB VRAM), 32GB RAM
**Role**: Pipeline architect, script writer, config generator, quality analyst, debugger
**Not used for**: Direct image generation, 3D mesh generation, diffusion-based sprite generation