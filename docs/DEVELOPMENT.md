# IoA Asset Pipeline — Development Master Document

> **Status**: Active Development (v0.5.0)
> **Target**: Warhammer 40,000: Dawn of War 1/2 quality — 2.5D isometric tactical game
> **This document must be updated when any task is completed. Priority: HIGH.**
> **Last Updated**: 2026-07-27 — Full restructure: added sections 3, 9-13. DoW asset budgets, MCP arch, WebGPU engine spec, KTX2 optimisation pipeline, roadmap — Added DoW asset budgets, MCP architecture, WebGPU engine spec, optimisation pipeline, roadmap

---

## Table of Contents

1. [Rendering Quality Standard](#1-rendering-quality-standard)
2. [3D Model Quality — Dawn of War 1 Standard](#2-3d-model-quality--dawn-of-war-1-standard)
3. [Asset Budget Specifications](#3-asset-budget-specifications)
4. [Lighting & Materials](#4-lighting--materials)
5. [2.5D Isometric Camera Setup](#5-25d-isometric-camera-setup)
6. [Fog of War & Line of Sight System](#6-fog-of-war--line-of-sight-system)
7. [Animation & Rigging](#7-animation--rigging)
8. [Faction Visual Identity](#8-faction-visual-identity)
9. [AI Agent Orchestration — Blender MCP Architecture](#9-ai-agent-orchestration--blender-mcp-architecture)
10. [Web-Ready Asset Optimisation Pipeline](#10-web-ready-asset-optimisation-pipeline)
11. [WebGPU RTS Engine Architecture](#11-webgpu-rts-engine-architecture)
12. [Technical Risk Mitigation](#12-technical-risk-mitigation)
13. [Strategic Implementation Roadmap](#13-strategic-implementation-roadmap)
14. [Pipeline Technical Debt](#14-pipeline-technical-debt)
15. [Build & Deploy](#15-build--deploy)

---

## 1. Rendering Quality Standard

### Target: Dawn of War 1/2 Calibre (2004-2009 RTS)

| Metric | Current (v0.5.0) | Target | Notes |
|--------|-------------------|--------|-------|
| Strong edge density | ~1.5% | **15-30%** | Model lacks geometric detail |
| Distinct colour regions | ~85 | **500+** | Need material detail + surface variation |
| Mean brightness | 56/255 | **80-120/255** | Renders too dark |
| Alpha coverage | 14% | **15-25%** | Character frame fill acceptable |
| Polygon count | ~2,500 tris | **1,500-3,500 tris** | DoW1 budget is appropriate |
| Frame size | 384×512 | 384×512 | ✅ Correct |
| Downsample filter | LANCZOS | LANCZOS | ✅ Now using LANCZOS (was NEAREST) |

### Why Renders Look Primitive (Root Causes)

1. **Subsurf modifier on everything** — `add_subsurf(levels=3, render_levels=4)` on cylinders, cubes, and spheres creates smooth blobs with no hard surface definition. Armour should have FACETS and EDGES, not smooth gradients.
2. **Lighting too soft** — `light.size = 3.0` creates broad, diffused area lights. Miniature photography requires small, bright lights (`size = 0.2-0.5`) for hard shadow lines and specular edge highlights.
3. **No geometric detail** — Body parts are primitives (cylinder arms, cube torso, sphere head) with no panel lines, no armour trim rings, no greebles, no belt/webbing detail, no weapon detailing.
4. **NEAREST downscale** (FIXED) — Was using `Image.NEAREST` at render time, creating blocky pixelation. Now using `Image.LANCZOS`.

### Required Render Settings

```
Resolution:         1152×1536 (3× supersample) → LANCZOS → 384×512
Engine:             Cycles
Samples:            128 (64 fast, 256 max)
Denoising:          OpenImageDenoise
Colour depth:       16-bit RGBA
View transform:     Filmic
Look:               Medium High Contrast
```

---

## 2. 3D Model Quality — Dawn of War 1 Standard

DoW1 assets have very specific constraints that our generator must match:

### Heroic Scale Proportions

Standard real-world proportions look flimsy from isometric RTS camera height. Instruct the generator to scale up key features:

| Body Part | Scale Factor | Rationale |
|-----------|-------------|-----------|
| Hands/gauntlets | +30% | Must read at game resolution |
| Weapons | +25% | Silhouette identification |
| Shoulder pauldrons | +30% | Faction identity marker |
| Boots | +20% | Grounded stance weight |
| Backpack | +25% | Silhouette variety |
| Head/helmet | +10% | Faction identity |

### Polygon Budget

```
Units:            1,500-3,500 triangles
Buildings:        4,000-8,000 triangles  
Terrain tiles:    200-500 triangles
Vehicles:         3,000-6,000 triangles
```

### Geometry Requirements for Armour (DoW1-style)

DoW1 armour is NOT smooth. It has distinct, hard-edged armour plates separated by visible gaps or trim:

```
Required detail elements per armoured body part:
  ┌──────────────────────────────────────────────┐
  │ Helmet:   Visor slit, crest/ridge, ear-pieces,  │
  │           neck guard ring, brow ridge           │
  ├──────────────────────────────────────────────┤
  │ Torso:    Chest plate (separate from back),      │
  │           abdominal plates, belt/webbing,        │
  │           collar ring, power pack connections    │
  ├──────────────────────────────────────────────┤
  │ Shoulders: Trim ring around pauldron edge,       │
  │           faction symbol/icon, layered plates    │
  ├──────────────────────────────────────────────┤
  │ Arms:     Elbow guard, wrist guard,               │
  │           segmented vambrace, gauntlet detail    │
  ├──────────────────────────────────────────────┤
  │ Legs:     Knee guard (separate geometry),         │
  │           greave plates, thigh plate strips,     │
  │           boot armour/trim                       │
  └──────────────────────────────────────────────┘
```

### Modelling Technique: Hard Surface, Not Subsurf

For armour/mechanical parts:

```
✗ BAD:  Subsurf(levels=3) + Shade Smooth  
        → turns everything into organic blobs

✓ GOOD: Edge Split(angle=30°) + Bevel(angle=30°, width=0.005) + Shade Flat  
        → creates faceted hard-surface armour with crisp edges

✓ GOOD: Higher segment counts on base primitives
        → Cylinder(vertices=48), Sphere(segments=48, rings=32)
        → smoother curves WITHOUT subsurf smoothing
```

Keep Subsurf ONLY for:
- Cloth/tabard (levels=1-2)
- Organic flesh/creature parts (levels=2-3)
- Capes and fabric accessories

### Normal Maps & Surface Detail

For fabricated detail without geometry:

```
Process:
1. Render a high-poly version (Subsurf level 4+) of the model  
2. Bake Normal Map from high-poly to low-poly  
3. Bake Ambient Occlusion  
4. Combine with diffuse colour texture  
5. Apply normal map in the material shader  

This gives the ILLUSION of:
  - Panel lines
  - Rivets  
  - Armour plate edges
  - Surface wear/scratches
```

---

## 3. Asset Budget Specifications

### DoW-Class Visual Asset Budgets

Target triangle counts and texture budgets for WebGPU deployment:

| Asset Category | Target Triangles | Texture Budget | Material Config | Draw Strategy |
|---------------|-----------------|---------------|-----------------|---------------|
| Standard Infantry | 1,200 – 2,500 | 512 × 512 | PBR / Baked Diffuse + Normal + Roughness | Hardware GPU Instancing |
| Elite / Heavy Units | 2,500 – 5,000 | 1024 × 1024 | PBR with Masked Faction-Colour Channels | Hardware GPU Instancing |
| Vehicles & Armour | 4,000 – 8,000 | 1024 × 1024 | PBR Metallic/Roughness + Emissive | Dynamic Instancing / Batched |
| Environmental Props | 200 – 1,500 | 256 × 256 – 512 × 512 | Static Lit / Baked AO | Static Geometry Batching |
| Terrain / Grass | 20 – 150 | 128 × 128 | Alpha-Tested Cutout | Indirect GPU Instancing |

### Surface Detail Strategy

Surface detail is carried by baked normal maps and team-colour masks — NOT heavy geometric density:
- Low-poly geometry with triangulated quads optimised for rendering hardware
- Visual illusion of armour bevels, rivets, and mechanical wear via high-to-low poly normal map baking
- Faction-colour masking via alpha channel (tintable by player colour at runtime)

### Current v0.5.0 Gap Analysis

| Metric | DoW Target | Current | Action Required |
|--------|-----------|---------|----------------|
| Infantry triangles | 1,200-2,500 | ~2,500 | ✅ In range (upper bound) |
| Texture resolution | 512×512 | 384×512 atlas | ⚠ Atlas contains 248 frames; individual frame texturing not yet implemented |
| Normal maps | Required | Not used | ❌ Must add normal map baking pipeline |
| Team-colour mask | Required | Not generated | ❌ Must add mask channel to material shaders |
| Hardware instancing | Required | N/A (sprites) | ❌ Engine-side; sprites use atlas batching |

---

## 4. Lighting & Materials

### Miniature Photography Lighting (Warhammer 40K Style)

For grimdark tactical miniatures, DO NOT use soft diffuse lighting. Use small, intense lights with hard shadows:

| Light | Colour Temp | Energy | Size | Position | Purpose |
|-------|-------------|--------|------|----------|---------|
| Key | Warm 3500K (#FFD9A6) | 3000W | 0.5 | (-4, -3, 6) | Main sculpt lighting |
| Fill | Cool 7500K (#99B3FF) | 500W | 1.0 | (3, 2, 2) | Shadow detail |
| Rim | Gold (#FFD14C) | 2000W | 0.3 | (1, 6, 3) | Armour edge definition |
| Specular | White (#FFF2E6) | 800W | 0.2 | (0, 0, 8) | Helmet/armour highlights |

Key-to-fill ratio: 6:1 (for dramatic miniature contrast, NOT 2:1 like studio photography)

### Material Palette (PBR)

Materials must have clear visual differentiation at 384×512 and MUST NOT look the same when lit:

| Material | Roughness | Metallic | Base Colour | Specular | Used On |
|----------|-----------|----------|-------------|----------|---------|
| Armour plate | 0.3 | 0.8 | Dark steel | High | Torso, helm, pauldrons |
| Trim/Gold | 0.2 | 1.0 | Gold/brass | Very high | Faction accents |
| Fabric underlayer | 0.8 | 0.0 | Dark grey | None | Arms, thighs |
| Leather | 0.6 | 0.1 | Brown | Low | Boots, pouches, gloves |
| Ceramite | 0.4 | 0.6 | Faction colour | Medium | Power armour plates |
| Flesh | 0.7 | 0.0 | Flesh tone | Low (skin) | Creature faces |

### Team-Colour Masking (Critical for Faction Identity)

Each unit must have an alpha-channel-based team colour mask that allows the game engine to tint specific areas:

```
Layer 1: Base diffuse texture (full colour)
Layer 2: Team colour alpha mask
  - Black (alpha=0) = Main armour (tinted by player colour)  
  - White (alpha=255) = Trim/accents (always gold/brass)
  - Grey (alpha=128) = Secondary armour (darker tint)

Implementation: Blender Shader Node group that:
  Diffuse × TeamColour(lerp with mask) + Trim(Gold fixed)
```

---

## 5. 2.5D Isometric Camera Setup

### True Isometric Orthographic Camera

For 2:1 pixel-ratio isometric projection (standard tactical game perspective):

```python
import bpy, math

def set_true_isometric_camera():
    cam = bpy.data.cameras.new("Isometric_Camera")
    cam.type = 'ORTHO'
    cam.ortho_scale = 14.0
    
    obj = bpy.data.objects.new("Isometric_Camera", cam)
    obj.location = (15.0, -15.0, 15.0)
    obj.rotation_euler = (
        math.radians(54.736),  # X: arctan(1/sqrt(2))
        math.radians(0),       # Y: 0
        math.radians(45)       # Z: 45 degrees
    )
    bpy.context.scene.camera = obj
```

### Why This Matters

Perspective cameras (even with long focal lengths) create converging parallel lines that break the tactical grid illusion. Orthographic cameras at exact isometric angles:
- Ensure square/hex grid tiles fit perfectly
- Prevent parallel lines from converging
- Maintain consistent scale across the entire viewport
- Match the rendering style of XCOM, Silent Storm, and classic tactical games

### Current v0.5.0 Camera (Needs Review)

The current `render_8dir_v2.py` uses a custom isometric rig with `ISO_ELEVATION_DEG = 30` and `rotation_euler = (90 - ISO_ELEVATION_DEG, 0, 0)`. This needs verification against true isometric angles.

---

## 6. Fog of War & Line of Sight System

### Three-State Visibility Model

Per XCOM/Silent Storm standard:

| State | Visual Treatment | Description |
|-------|-----------------|-------------|
| Unexplored | Black (#000) | Player has never seen this area |
| Explored (Out of LoS) | Darkened/Greyscale | Seen before, no active unit watching |
| Active LoS | Fully lit | Actively visible by a player unit |

### Implementation Approaches

#### Option A: Global Mask Texture (Recommended for Real-Time)

Apply a world-space fog texture across all environment shaders:

```python
# 2D fog grid texture: 64×64 pixels for a 64×64 tile map
# Each pixel maps to tile coordinates:
#   RGB(0,0,0)       = Unexplored
#   RGB(0.3,0.3,0.3) = Explored / Out of LoS
#   RGB(1.0,1.0,1.0) = Active Line of Sight

# In Blender shader nodes for every material:
# 1. ShaderNodeTexCoord (World)
# 2. ShaderNodeMapping 
#    → Scale: (1/map_width, 1/map_height, 1)
#    → Location: (0.5, 0.5, 0)
# 3. ShaderNodeTexImage (FoW grid texture, interpolation = Closest)
# 4. MixRGB (Multiply) — multiply base colour by fog colour
```

#### Option B: Raycast LoS Check (For Pre-Rendered Sequences)

For rendered turn animations or sprite sheet generation:

```python
def check_line_of_sight(viewer_pos, target_pos, max_distance=15.0):
    """Raycast between two points — returns True if LoS is clear."""
    direction = (target_pos - viewer_pos).normalized()
    distance = (target_pos - viewer_pos).length
    if distance > max_distance:
        return False
    depsgraph = bpy.context.evaluated_depsgraph_get()
    result, location, normal, index, hit_obj, matrix = \
        bpy.context.scene.ray_cast(depsgraph, viewer_pos, direction, distance=distance)
    if result and hit_obj.name != "TargetUnit":
        return False  # Blocked by terrain/cover
    return True  # Clear line of sight
```

### Height & Cover System

LoS must respect:
- **High ground**: Units at higher elevation see further and over low cover
- **Full cover**: Walls, buildings — completely blocks LoS
- **Half cover**: Railings, crates — provides cover bonus but doesn't block LoS
- **Smoke**: Temporary LoS blocker

### Secrets of Sol Divisive / XCOM Approach

For each unit, per-turn:
1. Calculate all tiles within视线 range
2. Raycast from unit position to each tile centre
3. Check for cover objects along the ray
4. Update fog texture: tile → Fully Lit (if visible) or Explored (if previously seen)
5. AOEs and reactions: only trigger if the acting unit has LoS to target

---

## 7. Animation & Rigging

### Auto-Rigging Pipeline

For animated units, the pipeline should:

```python
# 1. Export low-poly .obj
# 2. Send to auto-rigging service (Mixamo API or Rigify)
# 3. Import rigged model back
# 4. Adjust vertex weights for armour pieces
# 5. Set up NLA tracks for animations
```

### Vertex Weighting Rules

Armour pieces must not deform like cloth:
- **Pauldrons**: Weighted to spine/shoulder bone only — NO twist deformation
- **Boots**: Weighted to foot bone — NO ankle bending
- **Torso plate**: Weighted to spine — NO stretch on arm movement
- **Helmet**: Weighted to head — NO clipping into torso on look-down

### Animation Style (DoW2 Tactical)

| Animation | Style | Frame Count | Notes |
|-----------|-------|-------------|-------|
| Idle | Minimal breathing | 4 | Weapon held ready |
| Walk | Tactical advance | 7 | Weapon up, scanning |
| Attack | Weighted strike | 5 | Wind-up, hit, recovery |
| Hurt | Stagger back | 3 | Armour absorbs impact |
| Die | Collapse | 7 | Weapon drops, falls |

---

## 8. Faction Visual Identity

Each faction must be DISTINCTLY recognisable at 384×512 from silhouette alone.

### Colour Palettes & Lighting Per Faction

| Faction | Primary | Secondary | Trim | Key Light | Fill Light | Mood |
|---------|---------|-----------|------|-----------|------------|------|
| **Iron Directorate** | Blue-grey steel | Bone white | Imperial gold | Cool (5500K) | Neutral | Ordered, militaristic |
| **Cinderborn** | Deep purple | Orange | Brass | Warm magenta | Purple | Corrupted, ritualistic |
| **Parasitic Bloom** | Sickly green | Rotting pink | Bone | Green-white | Pinkish | Flesh horror |
| **Wreckstorm Clans** | Rust red | Scrap brown | Yellow | Orange-red | Minimal | Ork-like scrap |
| **Harmonic Collective** | Clean white | Bright blue | Silver | Cool blue | White | Sleek machine |
| **Chrono Revenants** | Aged bronze | Teal | Gold-green | Warm gold | Teal | Temporal decay |
| **Void Corsairs** | Dark purple | Deep blue | Silver | Purple-blue | Cool white | Stealth/void |

### Silhouette Design Language

```
Iron Directorate:  Broad, rectangular, heavy. Blocky armour plates, 
                   straight lines, Imperial Gothic architecture.

Cinderborn:        Angular, spiky, asymmetric. Corruption spikes, 
                   jagged edges, ritual scarring.

Parasitic Bloom:   Bulbous, organic, irregular. Swollen sacs, 
                   tendrils, multiple limbs.

Wreckstorm Clans:  Chunky, asymmetrical scrap. Mismatched armour, 
                   visible rivets, crude construction.

Harmonic Collective: Sleek, curved, symmetrical. Clean lines, 
                   glowing elements, minimal silhouette.

Chrono Revenants:  Streamlined, ancient. Worn but elegant curves, 
                   bronze patina, flowing lines.

Void Corsairs:     Lithe, pointed, aggressive. Narrow waist, 
                   wide shoulders, elongated limbs.
```

---

## 9. AI Agent Orchestration — Blender MCP Architecture

### Problem: Raw bpy Script Synthesis Fails

Directly prompting LLMs to generate raw Blender Python (bpy) scripts fails in production due to:
- API version drift across Blender updates
- Context mismatches (invoking operators in incorrect selection mode)
- No deterministic verification feedback loops

### Solution: Model Context Protocol (MCP) Bridge

```
AI Agent (MCP Client) ⇄ MCP Bridge Server (ASGI) ⇄ WebSocket ⇄ Blender Addon (Main Thread) ⇄ Live Scene
```

The MCP bridge abstracts Blender's internal state behind validated, goal-first macro tools and deterministic inspection RPCs.

### Multi-Stage Procedural Workflow

**1. Geometry Generation & Mesh Cleaning**
- Import draft 3D mesh from diffusion-based 2D→3D pipelines or programmatic primitives
- Inspect for non-manifold edges, duplicate vertices, excessive polygon counts

**2. Mesh Decimation**
```
bpy.ops.object.modifier_add(type='DECIMATE')
```
Quadric Error Metrics reduction to match unit budget (1,200-2,500 tris for infantry)

**3. Automated UV Unwrapping**
```
bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
```

**4. Automated Rigging & Weighting**
- Invoke Rigify or RigNet ML-based rigging
- Align metarig to mesh bounding volume
- Parent mesh with automatic vertex weighting:
```
bpy.ops.object.parent_set(type='ARMATURE_AUTOMATIC')
```

**5. Truth-First Verification**
- `get_viewport_screenshot` — confirm visual consistency
- `get_object_info` — verify vertex count, material assignments, bounding dimensions
- Reject and retry before moving to export

### Pipeline Integration

For our current pipeline, MCP would replace the need for manual `blender --background --python` invocation by providing a live Blender session that the agent can inspect and iterate on. This is a Phase 1 goal.

---

## 10. Web-Ready Asset Optimisation Pipeline

### Why Raw Blender Exports Fail on Web

Raw 3D assets from Blender cause:
- Network overhead from uncompressed meshes
- VRAM exhaustion from PNG/JPEG textures decompressing to raw RGBA (5-10× expansion)
- Browser tab crashes, frame stutter

### Compression Pipeline

| Layer | Technology | Method | Benefit |
|-------|-----------|--------|---------|
| Container | glTF 2.0 / GLB | Binary JSON layout, contiguous buffers | Zero-copy parsing into GPU memory |
| Geometry | Google Draco | Attribute quantisation (14-bit pos, 10-bit normal, 12-bit UV) | 75-90% mesh file size reduction |
| Textures (diffuse) | KTX2 / Basis Universal (ETC1S) | Endpoint-vector quantisation | Up to 90% smaller than PNG |
| Textures (normal/PBR) | KTX2 / Basis Universal (UASTC) | High-quality block compression | Preserves surface detail fidelity |

### Critical Advantage: KTX2 Stays Compressed in VRAM

Standard web image formats (PNG/JPEG) must be fully decompressed into raw RGBA bytes upon load → 5-10× VRAM expansion. KTX2 textures are **transcoded directly into native GPU block-compressed format** (BC7 desktop, ASTC mobile, ETC2 Android):

- Minimises GPU memory consumption
- Eliminates frame stutter during dynamic streaming
- Increases GPU upload speeds

### Toolchain

```
Raw export from Blender (.glb)
    ↓
glTF-Transform (automated processing script)
    ├── Google Draco compression (geometry)
    ├── toktx / Basis Universal encoding (textures)
    │   ├── ETC1S → diffuse maps (smallest size)
    │   └── UASTC → normal/roughness/metallic maps (detail preservation)
    └── KTX2 container packaging
        ↓
Final optimised asset for WebGPU/WebGL deployment
```

---

## 11. WebGPU RTS Engine Architecture

### Multi-Language Architecture

Single-threaded JavaScript cannot handle hundreds of concurrent units (GC pauses, main-thread blocking). The engine separates high-level logic from performance-critical subsystems:

| Language | Subsystem | Runtime | Responsibilities |
|----------|-----------|---------|-----------------|
| Rust / C++ | Core Engine & Simulation | WebAssembly (Wasm) | ECS, pathfinding, spatial partitioning, memory management |
| TypeScript | Application Shell & UI | Browser main thread | Events, UI/HUD, WebAudio, network sync |
| WGSL / GLSL | Graphics Shaders | GPU pipelines | Vertex transform, PBR shading, instancing, terrain |

### Engine Pipeline Topology

```
Application Shell (TypeScript / DOM)
    ↓
Simulation Engine (Rust/C++ → Wasm) ⇄ Contiguous Memory Heap (SharedArrayBuffer)
    ↓
Graphics Layer (WebGPU API / WGSL Shaders) ⇄ Hardware GPU VRAM
```

### Entity Component System (ECS)

- Thousands of unit instances managed without GC overhead
- Entity data stored in contiguous arrays within Wasm linear memory
- Maximises cache locality
- Flowfield or Hierarchical A* pathfinding across pre-computed navmeshes

### Rendering: Hardware Geometry Instancing

Instead of submitting separate draw calls per character:
1. Single base mesh uploaded to GPU VRAM once
2. Per-instance data (position, rotation, animation frame, faction colour) passed via instance buffer
3. Hundreds of units rendered in a single draw call

### Spatial Indexing & Culling

- Quadtree spatial index maintained inside the Wasm runtime
- View frustum culling against spatial tree each frame
- Off-screen units discarded before GPU command buffer construction
- Preserves rendering bandwidth during wide tactical views

---

## 12. Technical Risk Mitigation

| Risk | Cause | Impact | Mitigation |
|------|-------|--------|------------|
| Camera zoom perf drop | Expanding view increases visible unit count | Frame rate drops | Strict zoom limits, dynamic LOD swapping, flowfield pathfinding |
| Wasm 32-bit memory ceiling | 4 GB max heap | Crashes if data exceeds bounds | Stream KTX2 textures directly to GPU VRAM — no raw buffers in Wasm memory |
| Generative mesh artifacts | AI models produce non-manifold geometry | Broken shading, rigging failures | Automated cleanup, normal recalculation, decimation passes before rigging |
| Visual style inconsistency | No unified material pipeline | Assets mismatch | Enforce standardised palettes, material templates, poly-count budgets across all agent prompts |

---

## 13. Strategic Implementation Roadmap

### Phase 1: AI Agent & Blender Automation Infrastructure
- Configure headless Blender with MCP server bridge
- Register tool schemas: decimation, UV projection, Rigify skeleton binding, GLB export
- Implement verification routines (viewport screenshot, object metadata inspection)
- Ensure assets meet triangle budgets before pipeline progression

### Phase 2: Automated Asset Optimisation Pipeline
- Deploy glTF-Transform post-processing script
- Google Draco geometry compression with attribute quantisation
- toktx / Basis Universal texture encoding:
  - ETC1S → diffuse maps (minimal download size)
  - UASTC → normal / PBR maps (detail preservation)
- KTX2 container packaging

### Phase 3: WebAssembly Simulation & WebGPU Rendering Engine
- Build ECS core in Rust, compile to Wasm
- Implement spatial Quadtree for frustum culling + collision detection
- WebGPU rendering layer with hardware instancing
- WebGL2 fallback for older hardware
- Custom WGSL shaders for PBR, instanced transforms, faction colour masking

### Phase 4: Integration, Profiling & Performance Tuning
- Stress test: 500+ active animated characters on screen
- Profile frame rates, memory consumption, draw calls
- Tune: camera zoom constraints, dynamic LOD transition distances, spatial hashing boundaries
- Target: stable 60 FPS across desktop and laptop browsers

---

### Render Issues (FIXED)
- ~~NEAREST downscale → LANCZOS~~ ✅ Fixed in `render_8dir_v2.py` line 475
- ~~Overly soft lighting~~ ✅ Fixed: light size 3.0 → 0.2-1.0, energies increased, 4th specular light added
- ~~Subsurf on all armour parts~~ ✅ Fixed: `add_hard_surface()` (Edge Split + Bevel + Shade Flat) replaces subsurf on helmet, torso, pauldrons, arms, legs, codpiece — only cloth/flesh retains subsurf
- ~~Double `_atlas` filename suffix~~ ✅ Fixed in `batch_pipeline.py`
- ~~Inline JS escaping bug in gallery~~ ✅ Fixed: external `tools/static/gallery.js`, no inline scripts
- ~~No port cleanup at server boot~~ ✅ Fixed: `ensure_port()` uses `fuser -k PORT/tcp` before binding
- ~~No Blender crash cleanup~~ ✅ Fixed: `kill_blender_processes()` in render_queue, pipeline_cli, batch_render.sh

### Render Issues (OPEN)
- [ ] Mean brightness below 60/255 — need higher light energy or exposure compensation
- [ ] Faction-specific lighting profiles not implemented — all factions use same lighting
- [ ] No normal map baking — surface detail is purely geometric (low detail)
- [ ] Ortho_scale not optimised — character fills only 14% of frame area
- [ ] No team-colour mask generation
- [ ] Hard-surface modelling changes need re-render test to verify edge density improvement

### Generator Issues (OPEN)
- [ ] No knee pad geometry
- [ ] No belt/webbing detail
- [ ] No elbow/wrist armour guards
- [ ] No backpack detail (vents, cables, power packs)
- [ ] No weapon detail (scope, barrel, magazine, grip)
- [ ] Creature/monster templates not using hard-surface modelling
- [ ] Vehicle generator needs review for hard-surface approach

### Gallery Issues (FIXED)
- ~~Inline JS `\'` escaping bug~~ ✅ Fixed — external JS file `tools/static/gallery.js`, no inline scripts
- ~~NEAREST downscale artifacts~~ ✅ Fixed — LANCZOS in render_8dir_v2.py + batch_process.py

### Gallery Issues (OPEN)
- [ ] Gallery needs per-faction filter/sort
- [ ] Gallery should show LOD comparison view
- [ ] Gallery should show metric scores alongside previews

---

## 14. Pipeline Technical Debt

### Render Issues (FIXED)
- ~~NEAREST downscale → LANCZOS~~ ✅ Fixed in `render_8dir_v2.py` line 475
- ~~Overly soft lighting~~ ✅ Fixed: light size 3.0 → 0.2-1.0, energies increased, 4th specular light added
- ~~Subsurf on all armour parts~~ ✅ Fixed: `add_hard_surface()` (Edge Split + Bevel + Shade Flat) replaces subsurf on helmet, torso, pauldrons, arms, legs, codpiece — only cloth/flesh retains subsurf
- ~~Double `_atlas` filename suffix~~ ✅ Fixed in `batch_pipeline.py`
- ~~Inline JS escaping bug in gallery~~ ✅ Fixed: external `tools/static/gallery.js`, no inline scripts
- ~~No port cleanup at server boot~~ ✅ Fixed: `ensure_port()` uses `fuser -k PORT/tcp` before binding
- ~~No Blender crash cleanup~~ ✅ Fixed: `kill_blender_processes()` in render_queue, pipeline_cli, batch_render.sh

### Render Issues (OPEN)
- [ ] Mean brightness below 60/255 — need higher light energy or exposure compensation
- [ ] Faction-specific lighting profiles not implemented — all factions use same lighting
- [ ] No normal map baking — surface detail is purely geometric (low detail)
- [ ] Ortho_scale not optimised — character fills only 14% of frame area
- [ ] No team-colour mask generation
- [ ] Hard-surface modelling changes need re-render test to verify edge density improvement

### Generator Issues (OPEN)
- [ ] No knee pad geometry
- [ ] No belt/webbing detail
- [ ] No elbow/wrist armour guards
- [ ] No backpack detail (vents, cables, power packs)
- [ ] No weapon detail (scope, barrel, magazine, grip)
- [ ] Creature/monster templates not using hard-surface modelling
- [ ] Vehicle generator needs review for hard-surface approach

### Gallery Issues (FIXED)
- ~~Inline JS `\'` escaping bug~~ ✅ Fixed — external JS file `tools/static/gallery.js`, no inline scripts
- ~~NEAREST downscale artifacts~~ ✅ Fixed — LANCZOS in render_8dir_v2.py + batch_process.py

### Gallery Issues (OPEN)
- [ ] Gallery needs per-faction filter/sort
- [ ] Gallery should show LOD comparison view
- [ ] Gallery should show metric scores alongside previews

---

## 15. Build & Deploy

### Render Queue (Overnight Batch)

```bash
# Add all units to queue
python3 tools/pipeline_cli.py queue add --unit iron_directorate_line_infantry
# ... (add all units)

# Process overnight
python3 tools/pipeline_cli.py queue run

# Post-process and pack
PIPELINE_VERSION=v0.5.0 python3 tools/batch_pipeline.py

# Sync to game repo
python3 tools/pipeline_cli.py sync --target ../imperium-of-ash/frontend/public/assets/atlases/
```

### Development Loop

```bash
# 1. Edit generator or render script
# 2. Test with single unit
python3 tools/pipeline_cli.py character render --unit iron_directorate_line_infantry --engine CYCLES --fast

# 3. Run quality check
python3 tools/pipeline_cli.py critic single --dir assets/units/iron_directorate_line_infantry/model/render/raw/

# 4. Visual inspection via gallery
python3 tools/gallery_server.py

# 5. Update this document with findings
# ← ALWAYS DO THIS BEFORE STARTING NEXT TASK
```

---

> **Document Maintainer**: AI Assistant + Human Review
> **Last Updated**: 2026-07-27
> **Next Review**: After next render batch — verify hard-surface modelling output, measure edge density improvement
