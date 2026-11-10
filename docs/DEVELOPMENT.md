# IoA Asset Pipeline — Development Master Document

> **Status**: Active Development (v0.5.0)
> **Scope (2026-11-09)**: this master document tracks the **2D sprite** programme.
> The combat loop moved to skinned 3D GLB in Three.js — its tools, contract and
> workstation policy live in [`3D_ASSETS.md`](3D_ASSETS.md). Both paths share
> Blender, the material library and the GPU, not their settings.
> **Target**: Dawn of War 1/2 presentation quality, achieved with our own assets
> **This document must be updated when any task is completed. Priority: HIGH.**
> **Last Updated**: 2026-11-09 — scoped this document to the 2D sprite programme; 3D GLB path moved to `3D_ASSETS.md`; MCP section marked as proposal (batch-only is the implemented method).
> **2026-08-02 PIVOT**: Switched primary target from DoW2 (normal-map sculpt/bake) to DoW1 (painted diffuse + team-colour mask on lean geometry). See section 16.

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
| Strong edge density | ~3.9% (lighting improved) | **15-30%** | Model lacks geometric detail; normal map baking will push further |
| Distinct colour regions | ~266 | **500+** | Need material detail + surface variation |
| Mean brightness | **96.3/255** ✅ | **80-120/255** | Now within target range (faction lighting fix) |
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

> DoW1 is a **reference measurement**, not a source of geometry. The DoW import
> path is retired; the style and budgets below still inform the 2D sprite bake.

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

> **Status 2026-11-09: proposal, not implemented.** The shipping decision is the
> opposite (see `AGENTS.md` §"No MCP, No Live Blender" and the 3D pipeline): batch
> `blender -b -P` stages with render-to-PNG review. Read this section for the
> reasoning, not as a description of the current system.

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
Quadric Error Metrics reduction to match the **2D sprite** budget (1,200-2,500 tris). The 3D GLB path uses a 10,000-25,000 tri LOD0 budget instead — do not apply the sprite figure to GLB work

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

MCP would replace manual `blender --background --python` invocation with a live session the agent can inspect and iterate on. **Not adopted** (2026-11-09): batch stages plus render-to-PNG review proved sufficient and more reproducible. MCP remains an option if interactive scene work becomes necessary.

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
- ~~Mean brightness below 60/255~~ ✅ Fixed in `render_8dir_v2.py`: faction-specific key light energy 3500W (was 3000W) raised mean brightness to 96.3/255, within 80-120 target. See `FACTION_LIGHTING` dict.
- ~~Faction-specific lighting profiles not implemented~~ ✅ Implemented in `render_8dir_v2.py`: `FACTION_LIGHTING` dict with 7 factions (iron_directorate, cinderborn, parasitic_bloom, wreckstorm_clans, harmonic_collective, chrono_revenants, void_corsairs). Each has per-faction key/fill/rim/specular colour temperatures and energies. CLI `--faction` argument added to `pipeline_cli.py character render`.
- ~~Hard-surface modelling re-render test~~ ✅ Tested with iron_directorate_line_infantry using faction lighting + fast mode (16 samples). Edge density at 384×512 LANCZOS improved from 2.41% → 3.88% (lighting-only improvement of +61%). Mean brightness 59.7 → 96.3, stddev 48.4 → 70.7. All critic metrics pass at processed resolution.

### Render Issues (OPEN)
- [ ] Normal map baking script created (`tools/blender/bake_normal_maps.py`) but not yet run on any unit. Run `blender --background --python bake_normal_maps.py -- --blend path/to/unit.blend` to apply.
- [ ] Normal map baking needs integration with pipeline_cli.py (add `pipeline normal-bake` subcommand)
- [ ] Ortho_scale not optimised — character fills only 14% of frame area
- [ ] No team-colour mask generation
- [ ] Edge density at 3.88% still far below 15-30% DoW target. Need: (a) higher segment counts on primitives (cylinder 48, sphere 48×32), (b) actual panel line/trim ring/greeble geometry, (c) normal map baking to push past 5%+

### Generator Issues (FIXED in this pass)
- ~~No knee pad geometry~~ ✅ DONE
- ~~No belt/webbing detail~~ ✅ DONE
- ~~No elbow/wrist armour guards~~ ✅ DONE
- ~~No backpack detail (vents, cables, power packs)~~ ✅ DONE
- ~~No weapon detail (scope, barrel, magazine, grip, muzzle)~~ ✅ DONE
- ~~Creature/monster templates not using hard-surface modelling~~ ✅ DONE
- ~~Vehicle generator needs review for hard-surface approach~~ ✅ DONE

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
- ~~Mean brightness below 60/255~~ ✅ Fixed in `render_8dir_v2.py`: faction-specific key light 3500W raised brightness to 96.3/255
- ~~Faction-specific lighting profiles not implemented~~ ✅ Implemented in `render_8dir_v2.py`: `FACTION_LIGHTING` dict for 7 factions, CLI `--faction` argument
- ~~Hard-surface modelling re-render test~~ ✅ Tested: edge density 5.68% at 384×512 LANCZOS (136% improvement over 2.41% baseline)
- ~~No normal map baking script~~ ✅ Created `tools/blender/bake_normal_maps.py` — two-phase bake (avoids circular dependency), tested on iron_directorate_line_infantry
- ~~Low primitive segment counts~~ ✅ Cylinder 24→48, sphere 32×24→48×32 across all body parts
- ~~Leg hard-surface~~ ✅ Thighs/shin/boots converted from subsurf+smooth to `add_hard_surface()`+`shade_flat`
- ~~No geometry detail~~ ✅ Added: pauldron trim rings (gold torus), kneepads with gold trim, belt ring with buckle+pouches, weapon scope+lens+magazine+foregrip
- ~~Normal map black/circular dependency~~ ✅ Fixed: two-phase bake (target only → save → connect). Valid normal map: avg (130,134,217) with 116K unique colours.

### Render Issues (OPEN)
- [ ] Edge density at 5.68% still below 15-30% DoW target. **Next levers after current detail pass: (a) ~7 new detail functions added — panel lines on torso/helmet, outer chest plate, rivets on pauldrons+chest, vent greebles on backpack, elbow guards, muzzle detail — re-render needed to verify new density. (b) higher subsurf levels on high-poly for normal map bake, (c) more aggressive bevel/hard-surface parameters**
- [ ] Unique colours at 405/500 — needs more material variation (wear, weathering, faction markings)
- [ ] Ortho_scale not optimised — character fills 15.5% of frame area
- [ ] No team-colour mask generation
- [ ] Normal map bake needs integration with pipeline_cli.py (add `pipeline normal-bake` subcommand)
- [ ] Batch normal-map bake needed for all 34 units
- [ ] Render queue dashboard shows nothing because renders ran via `character render` (direct) instead of `queue add` + `queue run`

### Generator Issues (FIXED in this pass)
- ~~No knee pad geometry~~ ✅ DONE
- ~~No belt/webbing detail~~ ✅ DONE
- ~~No elbow/wrist armour guards~~ ✅ DONE — `create_elbow_guards()` added with hard-surface plates + gold trim
- ~~No backpack detail (vents, cables, power packs)~~ ✅ DONE — `create_vent_greebles()` adds 4 slat vents per side/back with dark interiors
- ~~No weapon detail (scope, barrel, magazine, grip)~~ ✅ DONE (scope, lens, magazine, foregrip, barrel tip ring, sight post)
- ~~No muzzle detail (barrel tip ring + sight post)~~ ✅ DONE — added to `create_weapon` rifle section
- ~~Creature/monster templates not using hard-surface modelling~~ ✅ DONE — `generate_creature` and `generate_insectoid` now use `add_hard_surface()`+`shade_flat()` on body segments, head, legs, horns, mandibles, tail, feet/claws. Subsurf retained only on wings (membrane) and eyes (organic).
- ~~Vehicle generator needs review for hard-surface approach~~ ✅ DONE — parametric_vehicle_generator.py updated with `add_hard_surface()` and `shade_flat()` helpers. Creature/insectoid templates converted.

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
> **Last Updated**: 2026-08-03 — Phase 3.5/3.6/3.7 DONE. Iron Directorate line infantry hits DoW1 calibre: critic 40/40 PASS, edge density 14.02% alpha-normalised (DoW1 band 12-16%). Fixes: manual cylinder unwrap (fills tile), high-contrast AO remap, Bilinear+UnsharpMask downscale (replaces LANCZOS), alpha-normalised critic metric. Open: bolder markings readability, visor/lens material (Issue 5).
> **Prior (2026-08-02)**: DoW1 texture-driven pipeline pivot. Evidence: fresh render of iron_directorate_line_infantry with current generator → edge density 1.71% (DoW floor 5%, target 15%), 25% pass rate. Visual: camo-painted mannequin, no readable pauldrons/helmet, camo-blot PBR albedo textures. Root causes: (1) PBR albedo textures are camo/mud blots not surface detail; (2) ~7,400 verts of greeble geometry blurs to nothing after LANCZOS downscale — detail-from-geometry fails at sprite scale; (3) normal-map bake subsurfs the same primitives so bakes no real detail. DoW2 research: ~2000-2600 tris geometry, all detail in per-unit _dif/_nrm/_tem/_drt/_spec textures. Pivot to DoW1 (no normal maps — skips expensive high-poly sculpt/bake).
> **Next Review**: Phase 3.5 implementation on iron_directorate_line_infantry — coherent painted diffuse across all 8 directions.

---

## 17. PIVOT (2026-08-03): Real mesh foundation — retire primitive assembly

### 17.1 The ceiling of primitive assembly

Phase 3.5-3.7 hit a hard ceiling: `parametric_unit_generator.py` builds units from
54 `primitive_*_add` calls (cylinders/spheres/cubes); even `assets/bodies/.../body.blend`
was 8-vertex cubes per limb. No UV/atlas/AO/downscale tuning turns a cylinder into a
Dawn of War 1 space marine. The critic edge-density metric (14%) was passing on a
primitive mannequin — metric-gaming, not the visual goal. The texture/render pipeline
is sound and reusable; the GEOMETRY was the flaw.

### 17.2 New foundation: CC0 humanoid base + manual armour

- **Body**: CC0 MakeHuman-retopology base mesh (`assets/bodies/imperial_male/model/body_base_cc0.blend`,
  ~2,332 tris, 84-bone rig, UV-mapped, 512 diffuse + normal). See `CREDIT_cc0_base.txt`.
  Validated through the existing pipeline: renders as a real humanoid (correct
  proportions, anatomical silhouette) — clear step up from the cylinder mannequin.
- **Armour**: modelled manually in Blender on top of the base (pauldrons, helmet,
  chest/back plates, greaves, backpack, faction iconography). This is the IoA-original,
  IP-clean layer — NO Warhammer 40K fan-art assets (GW IP risk; the project is already
  40K-adjacent by rename, armour must be ours).
- **Pipeline reused**: UV/atlas/AO/downscale/critic infrastructure runs on any mesh.
  `parametric_unit_generator.py` primitive assembly retired for humanoids (kept only
  for non-humanoid body types if useful).

### 17.3 Pipeline fixes flagged by the base-mesh validation (before armour)

1. **Camera framing inconsistency**: front view has margins, side view fills ~90% —
   orthographic bounds not locked across the 8 directions → scale jumps. Lock the
   camera bbox to the unit's bounding box across all directions.
2. **Lighting too flat**: grimdark 3-point lighting underlit; tonal range compressed;
   form/volume barely reads. Push key/fill contrast ~15-20% within the grimdark range.
3. **Isometric angle verification**: side view reads as true 90° profile, not isometric
   3/4 (should be 30°/35.264°). Verify the projection matrix in `render_8dir_v2.py`.
4. **Baseline pose**: base is akimbo (hands on hips) — occludes hip/belt. Consider an
   A-pose for the armour-modelling baseline so belt/codpiece seams are accessible.

### 17.4 Phase status

- [x] Phase 5.1: Source + stage CC0 humanoid base — DONE (2026-08-03). male.blend staged,
  inspected (1147v/2332tris/84-bone rig/UVs/512 diff), rendered through pipeline.
- [x] Phase 5.2: Pipeline fixes — DONE (2026-08-03). Camera framing lock, scale-invariant
  SUN lighting, AgX colour management, ortho_scale clamp fix. Validated on the CC0 base.
- [ ] Phase 5.3: Model Iron Directorate armour kit on the base (manual Blender) — line
      infantry first, then reuse across roster. NOT DONE. **PIVOT**: user is not an artist;
      armour must come from a mesh source, not manual modelling (see §17.5).
- [ ] Phase 5.4: Re-run full texture pipeline (atlas/AO/downscale/critic) on the
      armoured mesh; gate = critic 40/40 + visual DoW1 read. NOT DONE.

### 17.5 Sourced-mesh test (2026-08-03) — the bar is stylistic, not technical

Tested a free IP-clean sci-fi soldier mesh (~3k tris, textured, 4096² maps) through the
full pipeline. Result: the **pipeline is proven sound on a real armoured mesh** (correct
scale, framing, lighting, 8-direction). But it is **NOT DoW1 calibre** — because DoW1
calibre is a *stylistic* bar, not a technical one:

- The mesh is the wrong style: generic sci-fi (smooth astronaut helmet, modest pauldrons,
  no weapon, T-pose, no chapter heraldry/purity seals/rivets). A DoW1 marine has an angular
  Mark-VII helmet with vents/aquila, enormous exaggerated pauldrons, a weapon in hand, a
  combat pose, and dense painted iconography.
- The existing 4096 PBR texture reads "modern clean PBR", not the DoW1 *painted* look
  (hand-painted edge highlights, weathering, hard baked contrast). Our painted-diffuse
  pipeline (atlas paint + AO + edge highlights) is what produces the DoW1 painted look —
  it must be applied to the marine mesh, not the mesh's stock PBR texture.

**Conclusion**: hitting DoW1 calibre needs (a) a 40K-marine-STYLED mesh and (b) our
painted-diffuse pipeline applied to it. IP-clean direct-download meshes are generic sci-fi,
not marine-styled; marine-styled meshes are 40K fan art (IP risk for shipping) or behind
account logins. The user's end goal is *original* models at DoW1 standard, so the marine is
a proof-of-concept target, not a shipped asset.

**Path forward (decision pending)**: use a 40K fan-art marine as a TEST-ONLY input to
prove the pipeline hits DoW1 calibre on a real marine (never ships), then build original
generation; OR have the user download a better mesh from an account-gated source.

---

## 16. DoW1 Texture-Driven Pipeline Pivot

### 16.1 Evidence (2026-08-02 review)

Fresh regenerate + render of `iron_directorate_line_infantry` with the **current** generator + `critic.py`:

| Metric | Fresh render | DoW target |
|--------|-------------|------------|
| Edge density | **1.71%** avg (min 1.13, max 2.06) | 5% floor / 15% target / 30% ideal |
| Pass rate | 10/40 (25%) | — |
| Visual read | Camo-painted mannequin, bare sphere head, flat shoulders, camo-blot surface | DoW armoured trooper |

DEVELOPMENT.md previously claimed edge density 5.68%. The actual fresh render is **1.71%**. Documented geometry greeble work is not materialising in renders.

### 16.2 Root Causes

1. **PBR albedo textures are camo/mud blots, not surface detail.** `assets/pbr_textures/grimdark_metal/albedo.png` is a two-tone camo pattern; `grimdark_leather` is mud-camo; `grimdark_fabric` is green dots. Tiled across a humanoid via smart-project UVs → reads as a camo uniform, not armour. No unit-specific textures (panel lines, rivets, aquila, iconography).
2. **Detail-from-geometry fails at sprite scale.** Generator adds ~7,400 verts of greeble geometry (panel lines, rivets, vents, trim). After LANCZOS downscale to 384×512 these are sub-pixel and blur to nothing → edge density stays 1.71%. Poly count inflates with zero visual payoff.
3. **Normal-map bake has no real detail source.** `bake_normal_maps.py` creates the "high poly" by subsurfing the **same low-poly primitives** → bakes subsurf smoothing, not panel lines/rivets/trim. No sculpted detail exists to transfer.
4. **Silhouette proportions wrong.** Pauldrons r=0.07 sit flush over arms r=0.04 at x=0.30 → protrude only 0.03, no overhang. Head visor/crest cubes scaled to head_r*0.45 → tiny nubs on a sphere, reads as a bare head not a helmet.

### 16.3 Research: DoW1 vs DoW2

| Aspect | DoW1 (2004) | DoW2 (2008) |
|--------|-----------|-----------|
| Geometry | ~2,000–2,600 tris | ~2,000–2,600 tris (same) |
| Diffuse | painted, detail baked in | grayscale, colorised at runtime |
| Team-colour mask | yes (RTX separate files) | yes (RGBA `_tem`) |
| **Normal map** | **none** (DX8-era) | yes — baked from high-poly sculpt |
| Other maps | basic specular | dirt + specular + occlusion + emissive |
| Texture res | 256–512² | 512–1024² |

**DoW1 skips the high-poly sculpt → normal-map bake** (the most expensive, fragile part). DoW1 detail = **painted diffuse + team-colour mask** on lean geometry. Same silhouette readability as DoW2. Target DoW1 first; add normal maps later as enhancement.

### 16.4 DoW1 Implementation Plan

**Phase 1 — Geometry foundation (correct silhouette):** ✅ DONE
- Fix pauldron proportions: larger dome (r ~0.12–0.15), overhang torso edge, flattened dome shape. Heroic +30%.
- Fix head/helmet: larger visor slab, pronounced crest, so it reads as a helmet not a sphere.
- Fix backpack/weapon proportions to read in silhouette.
- Re-render, verify silhouette reads as armoured trooper (not camo mannequin).

**Phase 2 — Surface base textures:** ✅ DONE
- Replace camo-blot PBR albedos with real surface micro-detail (metal grain, leather pebble, fabric weave).
- Regenerate `grimdark_materials.blend`.

**Phase 3 — Per-unit painted diffuse + team-colour mask (atlas + painter):** BUILT, NOT ROBUST
- Procedural per-unit diffuse texture: base faction colour + painted panel lines + rivets + aquila/trim + edge-wear.
- Per-unit team-colour mask (RGBA, 4 channels) for runtime faction tinting.
- UV atlas per unit (replace smart-project per-part with a single atlas unwrap).
- **Blocker**: box-project unwrap (`_remap_obj_uv_to_tile`) scatters cylinder side-faces across tile regions by per-face dominant normal → front/back colour incoherence. Resolved by Phase 3.5.

**Phase 3.5 — Deterministic per-primitive UV unwrap + Island-Footprint Manifest (NEXT):**

The architectural flaw: `parametric_unit_generator.py` owns the semantic knowledge of each mesh part (via `_ANCHOR_NAME_MAP`) but abdicates topological layout to generic box projection. The generator *knows* what each primitive is at creation time, so it must enforce a deterministic, predictable UV topology per primitive type before packing into atlas tiles. Five sub-steps:

**3.5.1 Semantic unwrap by primitive type** (replaces `_remap_obj_uv_to_tile` box-project):
- **Cylindrical limbs** (`upper_arm`, `forearm`, `thigh`, `shin`): select the vertical edge loop furthest back on the −Y axis (away from camera), mark it as a UV seam, then `bpy.ops.uv.unwrap(margin=0.02)`. Produces a flat rectangular island where front/back faces remain continuously connected (back seam = both left & right edges; cylinder front = island horizontal midline).
- **Domes** (`pauldron`): select the bottom circular edge loop facing inward toward the torso, mark seam, `unwrap()`. Flattens the dome into a disc so the centred chapter insignia stamps into the dome apex.
- **Faceted helmets / cubes** (`helmet`, `torso` plates): `smart_project(angle_limit=66°)` then uniformly scale islands to fit the tile without arbitrary face rotation.
- **Dedicated decals** (`aquila` chest plate): unchanged — manual UVs to the `aquila` tile, `atlas_uv_manual=True` skips the general remap.

**3.5.2 UV-Space Island Normaliser** (`normalize_and_map_uv_island` in `parametric_unit_generator.py`):
- Runs *after* the semantic unwrap, operating on bmesh UV loops (NOT object-space vertex bounds — the current `_remap_obj_uv_to_tile` normalises from vertex `.co`, which double-transforms a real unwrap).
- **Canonical orientation lock**: compute island U/V variance (PCA or bbox); if the island's longest axis is horizontal but the part is a vertical limb, rotate UVs exactly 90° about the island centre so "top of tile = top of part".
- **Aspect policies** (matching what `paint_unit_diffuse.py` draws):
  - `CONTAIN` — fit island inside tile preserving true aspect ratio, centre U+V. Used for pauldrons, helmet, torso.
  - `ALIGN_BOTTOM` — contain-scale, pin lowest V to tile floor margin. Used for boots, tabards, belt (short/wide parts where pinning matters).
  - `FILL` — stretch to fill tile. **AVOID for limbs**: causes anisotropic texel stretch (1px vertical line → thick blurry band on mesh). Limbs use `CONTAIN` (tall narrow cylinders fill tile height, centre U) — painter fractions stay correct because the island fills V.
- Map the normalised island into its atlas tile rect via `_tile_uv_rect` (handles the row-0-is-top / UV-v=1-is-top flip).

**3.5.3 Symmetry overlap (half-texture optimisation):**
- L/R pairs are created with identical primitives (`for side, x in [("L",-x),("R",+x)]` → same `vertices=48` / `segments=48, ring_count=32`), so vertex/face index counts match → index-matched UV copy is valid.
- `apply_symmetry_uv_mirror(source_L, target_R)`: copy L's final UV array onto R verbatim. Both sample identical atlas pixels → guaranteed symmetric panel lines, gold trim, insignia. Halves texture real estate.
- **Validate first**: confirm `len(L.data.vertices)==len(R.data.vertices)` and equal face count before copying; if a per-side deformation broke topology parity, skip mirror and unwrap R independently (warn).

**3.5.4 Island-Footprint Manifest bridge** (Blender → Pillow):
- The normaliser writes `build/island_manifest.json`. Schema keys on the **full object name** (e.g. `Pauldron_L`) for topology ownership, and routes back to the **collapsed `tile_id`** (e.g. `pauldron`) the painter uses — decoupling mesh identity from texture placement:
  ```json
  { "Pauldron_L": {"tile_id":"pauldron","tile_grid":[u0,v0,u1,v1],
                   "island_uv":[u0,v0,u1,v1],"policy":"CONTAIN",
                   "orientation":"vertical","mirror_of":null},
    "Pauldron_R": {"tile_id":"pauldron",...,"mirror_of":"Pauldron_L"} }
  ```
- **Option (A) confirmed**: keep ONE shared tile per part type in `TILE_LAYOUT` (no `pauldron_L`/`pauldron_R` split, no dead atlas space). Symmetry is expressed purely as `mirror_of: R→L`; the painter skips `mirror_of != null` parts and they sample L's pixels via UV overlap. This is the DoW1 half-texture optimisation and requires no `TILE_LAYOUT` change.

**3.5.5 Pre-render UV validation gate** (`tools/validate_uv.py` — NEW):
- Runs headlessly right after the manifest is written, BEFORE AO bake / paint / render. Fails fast to protect Cycles + render compute.
- Reads `island_manifest.json` + the `.blend` mesh (skips `mirror_of` parts — they share source metrics).
- Metrics & rules:
  - **Anisotropy** = U-edge-length / V-edge-length ratio (max of the two). FAIL if > 1.5:1. Catches FILL-on-limbs regressions and box-projection scatter.
  - **Island coverage** = island_pixel_area / tile_pixel_area. CONTAIN: FAIL if < 30%. ALIGN_BOTTOM: WARN if < 15% (catches layout drift / over-padded pinning).
  - **Seam integrity** (cylindrical limbs only): confirm the back-seam verts are pinned to the tile's left AND right UV boundaries (tolerance 0.02). FAIL if skewed/rotated — the painter's `mid_x = x0 + footprint_w//2` front-split line depends on this.
  - **Intra-unit texel density variance** = max/min texel_density across the trooper's parts. FAIL if ratio > 2.5×. Enforces within-unit balance (no one limb hogging the tile). Does NOT enforce cross-unit parity (a warlord's shin legitimately has lower absolute texel density than a cultist's — matches DoW1, preserves aspect policies).
  - **Unintended UV overlap** = AABB intersection between any two non-mirror `island_uv` rects. FAIL on collision (silent texture bleed). Intentional L/R mirror overlap is excluded (mirrors are skipped).
  - **Tile-boundary margin violation** = island within 8px (UV `8/atlas_size`) of its tile edge. FAIL — prevents LANCZOS downscale bleed into the adjacent tile.
  - **UV bounds sanity** = all UVs in [0,1], no NaN/Inf. FAIL on any invalid coordinate (catches a failed unwrap scattering coords outside the atlas).
  - **Atlas tile occupancy** = every tile in `TILE_LAYOUT` expected to be painted is referenced by ≥1 non-mirror part. FAIL on a blank tile (would render the atlas background colour).
- Exit code 1 blocks the pipeline; exit 0 proceeds to AO bake.
- **Integration note**: `validate_uv.py` needs the expected-tile set. The canonical source is `tools/pbr/atlas_layout.py` (`TILE_LAYOUT` dict), NOT a JSON file — either import `atlas_layout.TILE_LAYOUT` directly (dependency-free, already imported by the generator) or export it to `tools/pbr/tile_layout.json` at build time. Do not maintain a second copy of the tile list.

**Phase 3.6 — Headless Ambient Occlusion bake (NEW, replaces normal-map bake):**

DoW1 has no normal maps; depth comes from a baked AO pass. Convert `tools/blender/bake_normal_maps.py` → `tools/blender/bake_ao_maps.py`:
- Cycles, `bake_type='AO'`, `samples=64`, `denoise_baking=True`, `margin=4`, `use_selected_to_active=False`.
- One shared 1024×1024 AO image; inject an active `ShaderNodeTexImage` ("AO_Bake_Node") into every material (Cycles writes bake pixels at each object's UV coords; non-overlapping tiles composite correctly).
- **Isolate master sources**: before baking, hide all `mirror_of != null` objects (`hide_render=True`) so an asymmetric weapon/backpack on one side doesn't overwrite the shared tile via overlapping mirrored UVs. Restore visibility post-bake.
- Save `<unit>_ao.png` next to the diffuse atlas. (DEPRECATE `bake_normal_maps.py` — its high-poly source is just subsurfed primitives, bakes smoothing not detail; root cause #3.)

**Phase 3.7 — Footprint-aware 3-layer diffuse comp** (`paint_unit_diffuse.py` refactor):

Discard the static-margin `tile_rect` drawing entirely; replace with `FootprintAwarePainter` reading the manifest:
- `get_island_pixel_rect(part)` converts manifest `island_uv` → atlas pixels (with Blender-V-bottom / Pillow-Y-top flip). Returns `None` for `mirror_of` parts → skip painting (UV overlap samples L).
- Draw panel lines, rivets, edge highlights, insignia **within the true island footprint**, not the full 256×256 tile. Fixes the `ALIGN_BOTTOM` failure mode where `panel_line_h(...,0.65,...)` landed in empty space above a short boot.
- Front-centre of a cylinder = tile horizontal midline (CONTAIN centres U; back seam is both left & right edges → front = midline) → the painter's front-split line at `mid_x` is valid.
- **3-layer comp**: `Final = (Micro-Detail Base) × (AO) + (Procedural Edge/Panel Overlay)`:
  - Base = uniform gunmetal/gold/under-armour from Phase 2.
  - AO = `bake_ao_maps.py` output, loaded grayscale, multiplied (darkens under-armour folds, pauldron undersides, visor slit crevices — instant isometric depth).
  - Edge/panel overlay = UV-island boundary mask, dilated 1–2px, multiplied with bright gold/gunmetal → hand-painted DoW1 edge highlights; dark 1px panel lines offset inward 3–5px from island boundaries; rivet dots along lines.
- Team-colour mask (`<unit>_teammask.png`): R=primary armour, G=secondary, B=accent/trim, A=emissive/lens, 0=fixed (gold trim, dark lenses). Plates painted neutral mid-grey on diffuse so runtime tinting works; swap channels to test Blood Ravens red / Ultramarines blue without rebuilding assets.

**Phase 4 — Scale:** Apply 3.5–3.7 to all 34 units, re-render, re-pack atlases, sync to IoA. The `validate_uv.py` gate runs per unit before its AO bake; `critic.py` (sprite-only, unchanged) remains the post-render downstream signal — its existing `edge_density` metric is the correct "did the painted detail + AO land coherently" check (target 15%, ideal 30%). No new sprite-side metric needed.

**Locked pipeline execution order (per unit):**
```
1. Generate mesh geometry by component (parametric_unit_generator.py)
2. Semantic seam cuts + orientation lock (per-primitive unwrap)
3. UV-Space Island Normaliser → write build/island_manifest.json
3.5. tools/validate_uv.py  → FAIL = stop pipeline + log (protects Cycles/render compute)
4. tools/blender/bake_ao_maps.py  → isolate/hide mirror targets, bake AO into atlas
5. tools/pbr/paint_unit_diffuse.py  → FootprintAwarePainter draws within manifest footprints
6. tools/blender/apply_unit_textures.py  → wire diffuse+AO into materials
7. render_8dir_v2.py  → 8-direction render
8. tools/critic.py  → post-render sprite gate (edge_density = coherence signal)
```

### 16.5 Phase Status

- [x] Phase 1: Geometry proportion fix — DONE (2026-08-02). Pauldrons r 0.07→0.13, raised to shoulder top, now overhang and read as metal domes with gold trim (verified both N/E views). Helmet reshaped sphere→faceted cube with dark visor slit (mat_lens) + pronounced gold crest — reads as a helmet not a bare sphere.
- [x] Phase 2: Surface base textures — DONE (2026-08-02). Replaced camo-blot albedos in `tools/pbr/gen_procedural_textures.py`: grimdark_metal (uniform gunmetal, thin rust streaks not blobs), grimdark_leather (uniform brown, fine grain), grimdark_fabric (dark desaturated under-armour, subtle weave). Rebuilt `grimdark_materials.blend`. Visual read transformed from "camo mannequin" → "armoured trooper" (steel plates + gold trim + dark under-armour). NOTE: edge density unchanged at 1.69% — confirmed this metric measures painted-detail density (Phase 3), not geometry; clean uniform surfaces correctly produce few edges.
- [~] Phase 3: Per-unit painted diffuse + team-colour mask — BUILT, NOT ROBUST (2026-08-02). Built `tools/pbr/paint_unit_diffuse.py` (atlas painter: panel lines, rivets, aquila, chapter insignia, vent slats, gold trim per part-tile), `tools/pbr/atlas_layout.py` (shared tile layout), `tools/blender/apply_unit_textures.py` (wires diffuse atlas into materials, DoW1-style no normal maps). Generator assigns per-part atlas UVs via box-project unwrap + a dedicated chest aquila decal. **Problem**: box-project unwrap scatters cylinder side-faces across tile regions → front/back colour incoherence on the same part. Preview saved to `output/v0.5.1_phase3_preview/`. Lighting fixed: camera-relative orbiting lights (`_orbit_lights_for_direction`) so all 8 directions are evenly lit (DoW-style). Blocked on Phase 3.5.
- [x] Phase 3.5: Deterministic per-primitive UV unwrap + Island-Footprint Manifest — DONE (2026-08-03). GATE PASSED: `tools/validate_uv.py` (71 parts validated: bounds, overlap, tile-margin, occupancy, cylinder anisotropy <1.5:1, seam integrity). Visual verification (analyze_image on idle N+E renders with atlas applied): limbs/pauldrons/torso/helmet all COHERENT (no scattered camo patchwork, front/back continuous, L/R symmetric) — the box-project scatter failure is fixed. Implementation: `unwrap_cylinder` (back-seam + cap-loop seams), `normalize_island_to_tile` (CONTAIN/ALIGN_BOTTOM, UV-space not vertex-space, `_orient_v_to_z`), `apply_symmetry_uv_mirror` (index-matched L→R copy), `build/island_manifest.json` (full-name keys + collapsed tile_id + `primary` flag, Option A single shared tile), `tools/validate_uv.py` (8 metrics, in-process gate pre-join). Note: edge density still 1.05% — expected, that's the Phase 3.7 gate (footprint-aware painter + lens material handling), not 3.5.
- [x] Phase 3.6: Headless AO bake — DONE (2026-08-03). `tools/blender/bake_ao_maps.py` (Cycles AO, 64 samples, OptiX GPU, shared 1024 image into atlas UVs, temporary active image-texture node per material). Outputs `<unit_name>_ao.png`. Naming fixed to unit-name (mesh name) so the painter finds it.
- [x] Phase 3.7: Footprint-aware 3-layer diffuse comp — DONE (2026-08-03). GATE PASSED: `tools/critic.py` 40/40 idle frames PASS, edge density **14.02% alpha-normalised** (DoW1 band 12-16%, target 14%, DoW gap 0.00%). Three fixes from research: (a) high-contrast AO remap `clip((ao-0.2)/0.6,0,1)**2` (isolates darkening to crevices, not raw multiply which crushed mid-tones — edge density 3.47%→14%); (b) Bilinear + UnsharpMask(radius=1,150%,threshold=3) downscale replacing LANCZOS (LANCZOS turned 1px painted lines into muddy gradients); (c) per-tile Phase-2 grain overlay. Critic metric fixed: edge density now alpha-normalised (edge_pixels_in_alpha / visible_pixels), thresholds recalibrated (DoW1 12-16%, DoW2 22-30%). Downscale runs via system-Python PIL (Blender's bundled Python lacks PIL). Pixel stats confirm rich content (1722 unique colours, full 0-255 range). OPEN refinements: painted markings read subtle at sprite scale (bolder/thicker panel lines + brighter gold trim would improve readability); visor/lens material still rewired to atlas (Issue 5 — needs dedicated lens material or skip-list).
- [ ] Phase 4: Scale to all units — IN PROGRESS (2026-08-02). Overnight render of all 34 units (idle, 8 dirs, fast) with Phase 1+2 (coherent PBR, NO atlas) for review via `tools/overnight_render.sh`. Atlas not applied in the batch (pending Phase 3.5–3.7).

## 17. DoW Asset Import — authentic Relic models into the pipeline

Added 2026-10-05. Imports authentic Dawn of War assets (SGA v2 archives,
Definitive Edition) as geometry + material sources: proven end-to-end with the
ork roster (Slugga Boy `boyz.whm`, Shoota Boy `boyz_shoota.whm` extracted,
rendered front-facing textured from the game's own `boyz_unit_page` atlas,
klan-tinted, and pixelised via the PZ pixel stack).

- `tools/dow/whm_v4_patch.py` — Definitive WHM (RSGM chunk v4) compatibility
  shims over `relic.chunky_formats.dow.whm` v3 reader: version gate, STXT
  unknown-chunk tolerance, MSLC v4 non-zero reserved header + extra children,
  relaxed child-count asserts. Import before converting any Definitive WHM.
- `tools/dow/rsh_extract.py` — RSH ("Relic Chunky") material-atlas decoder:
  `FOLDSHRF → FOLDTXTR → DATAATTR/DATADATA` raw DXT mip chains wrapped in a
  synthetic DDS header and decoded with Pillow (fmt 8 = DXT1). MTL material
  names map 1:1 to atlas stems. Force 8-bit RGBA (16-bit breaks Blender GPU
  texture upload).
- `tools/dow/blender_ork_import.py` — OBJ import + atlas texturing
  (`Closest`, `alpha_mode="NONE"`, `blend_method="OPAQUE"` — DXT1 1-bit alpha
  blanks renders otherwise) + ortho front camera auto-framed from bounds +
  key/fill/rim lights with `view_transform="Standard"` (AgX washes colour) +
  klan tint (MULTIPLY 0.45 on cloth parts by name). Atlas dir override via
  `DOW_ATLAS_DIR`.
- Pixel variant: `pz/pixel/` (`pixelise.py` Oklab fixed-palette quantiser,
  `verify_pixel_asset.py` QC, `styles.py`/`palette.py` presets) — the PZ
  sub-pipeline palette-locked path.
- Full reference: `docs/DOW_IMPORT.md`.

Status:
- [x] SGA v2 extraction via `relic-tool-sga-v2` fs opener (monolith
  `relic-tool-sga` 2.0.1 mis-reads DowI file data — do not use).
- [x] WHM v4 shims — boyz.whm/boyz_shoota.whm convert to OBJ+MTL+bones.
- [x] Atlas decode — 43 ork atlases from texture_share (DXT1/5 → PNG).
- [x] Blender render + pixelise + QC — Slugga/Shoota proven end-to-end.
- [ ] Roster batch: nobz, nob_leader, warboss, big_mek, grots, stormboyz,
  stormboy_nob, mega_armoured_nobz, grotbomb, warboss_tgd (same chain).
- [ ] W40kData.sga (unit selection icons + WTP team-colour patterns) —
  pending from owner; unlocks authentic unit portraits + full team colour.
- [ ] Load-out filtering: Slugga/Shoota share one body mesh; per-load-out OBJ
  object filtering if plain variants are wanted.

---

## 18. Image-to-3D Concept-Mesh Stage (2026-10-16)

Concept art → master mesh via local image-to-3D models, feeding the sprite
pipeline (rig/pose/8-dir render) or 3D printing. Full reference:
`docs/IMG23D.md`. Runner: `tools/img23d/img23d.py` (Hunyuan3D-2mini shape-only
default, TripoSR fallback; shared python3.12 venv, RTX 3070 Ti 8 GB).

Status:
- [x] Environment — torch 2.14 cu126, pinned AI stack (`transformers==4.46.3`,
  `diffusers==0.35.1`, `huggingface_hub==0.36.2`), torchmcubes built against
  venv torch (system `cuda` pkg for nvcc).
- [x] Wrapper CLI — batch, seed/steps/resolution control, glb+obj+stl export,
  per-mesh QC stats (watertight/components/bounds), engine-split output dirs.
- [x] Certification run — hunyuan mini-turbo: 87 s, 418 362 verts, watertight,
  1 component (`output/img23d/test_tome-hunyuan/`); triposr: 100 711 verts,
  8 components, repair-before-print (`output/img23d/test_tome-triposr/`).
- [ ] First real concept-to-asset run (unit or prop) through critic gate.
- [ ] Decide Hunyuan Community License posture for shipped game assets.

---

## 19. 3D asset programme and generation-model training (2026-11-09)

The combat loop moved to skinned 3D GLB; the operating manual is
[`3D_ASSETS.md`](3D_ASSETS.md) and the live task list is [`../TODO.md`](../TODO.md).
This section records state, not plans that may change tomorrow.

Delivered and exercised on the line-infantry unit: `tools/glb_contract.py`
(acceptance gate), `tools/blender/uv_prepare.py` (weld 59,987→10,000 verts, 3 UV
islands), `tools/blender/preview_unit_materials.py`, `tools/pbr/`
(manifest → derive → Blender library), `tools/gpu_policy.py` and
`tools/blender_run.sh` (VRAM budgets/profiles).

Status:
- [x] Contract gate implemented; the shipped unit fails it deliberately (clay
      material, no UVs, 3 of 9 clips) — this is now visible rather than assumed.
- [x] Material library scaffold: 79 items planned across 7 faction kits, 17 shared
      surfaces, 14 patterns, 13 decals; 22 image generations total; 4 items built.
- [x] Workstation policy: 8 GB VRAM shared with the desktop, one GPU job at a time,
      profiles from live free VRAM, 31 GB RAM ceiling documented.
- [ ] Retopo / part separation — highest-value quality gap.
- [ ] Clip set `run fire reload hit death melee` (0/81 in the game tree).
- [ ] Training pilot (40 tiles, FLUX.2 klein 4B) — calibration pending, see TODO.md.

Training decision, recorded so it is not re-litigated: image/material LoRAs only,
on small Apache-2.0 bases; no 3D-shape or motion fine-tuning at this hardware tier.
Evidence and VRAM/RAM tables: [`GENERATION_TRAINING_RESEARCH.md`](GENERATION_TRAINING_RESEARCH.md).

---

## 20. Audio programme (2026-11-10)

The operating manual is [`AUDIO_PIPELINE.md`](AUDIO_PIPELINE.md). This section
records state, not intent.

Delivered:
- [x] `tools/audio/sources.py` — licence-verified source registry (Sonniss
      #GameAudioGDC 2015–2026, Kenney CC0) with the rejected sources and why.
- [x] `tools/audio/fetch_library.py` — resumable bulk fetch, extraction,
      `MANIFEST.json` (URL, sha256, licence) and UCS-aware `library_index.json`.
- [x] `tools/audio/cues_ioa.json` + `build_bank.py` — cue sheet (queries,
      recipes, targets), deterministic selection, design chain, convolution
      reverb, loop seam, loudness/peak mastering, OGG+M4A encode, `--verify`
      gate, `--sync-ioa` into the game.
- [x] Game bank v0.1.0: 34 cues / 52 masters built from the complete archive
      (Sonniss 2015–2024 + 2026, Kenney CC0; 8,197 indexed files, ~240 GB), all
      passing the gate (peak or LUFS target, ≤ -1 dBTP, no duplicate variants,
      loop seams clean). Delivery weight 3.3 MB for the whole bank (the
      procedural WAV placeholders it replaces were 7.3 MB for 44 files).
- [x] Game runtime: `audioMixPolicy.ts` (bus gains, voice caps, de-dupe,
      ducking, pan clamp) with 7 unit tests, and `audioBus.ts` (Phaser mixer)
      wired into `LoadingScene` (manifest-driven cue loading), `CombatScene`,
      `CombatTheatreManager`, `CombatActionManager`, `Unit` and both menu scenes.
- [x] `frontend/src/data/audioManifest.json` is generated by the pipeline and is
      the only cue list the game uses; `LoadingScene` falls back to the legacy
      WAV keys when it is empty.

Open:
- [ ] Audition the bank in-engine and add further `picks.json` overrides where a
      cue reads wrong in context (the current picks were chosen from filenames and
      measurements, not by listening in the game).
- [ ] Music: Sonniss supplies SFX and drones, not scored music. A CC0/attribution
      music source (OpenGameArt, Pixabay) is still needed for the campaign theme.
