# Asset-Pipeline Style Guide
## Imperium of Ash — Asset Standards

> **Style authority:** the look, shading, effects and animation standards for the
> pixel tiers, with sources, are in [`STYLE_RESEARCH.md`](STYLE_RESEARCH.md).
>
> **Scope 2026-11-09:** these style rules apply to both the 2D sprite bake and the
> 3D GLB units; the faction-level palettes, silhouettes and weapon language are
> ratified in `Imperium-of-Ash/docs/game-design/FACTION_IDENTITY.md`, which wins
> where the two disagree. 3D-specific technique is in [`3D_ASSETS.md`](3D_ASSETS.md).

## 1. Visual Identity: Grimdark Industrial

IoA is an **original grimdark science-fiction setting with Warhammer 40K lineage** —
we inherit the roles and the structural language, never the setting, names or
insignia. The visual language is:
- **Heavy**: Solid, weighty, overbuilt machinery and armor
- **Worn**: Scratches, rust, battle damage, soot stains
- **Oppressive**: Deep shadows, limited light sources, claustrophobic
- **Regimented**: Iron Directorate = clean lines, gold trim, standardised patterns
- **Chaotic**: Sons of Cinder = asymmetrical, branded, ritual markings

**Never**: Clean anime lines, bright saturated colors, cute proportions, smooth gradients.

## 2. Resolution Standards

| Asset Type | Base (LOD0) | LOD1 | LOD2 | Ratio |
|------------|-----------|------|------|-------|
| Isometric Tile Canvas | 96×128 | 48×64 | 24×32 | 2:1 iso footprint |
| Tile Footprint (ground) | 96×48 | 48×24 | 24×12 | 2:1 |
| Character Frame | 96×128 | 48×64 | 24×32 | ~2.67× tile height |
| Small Icon (UI) | 32×32 | — | — | 1:1 |
| Medium Icon (UI) | 48×48 | — | — | 1:1 |
| Button | 64×32 or 48×48 | — | — | — |
| Panel Segment | 64×64 modular | — | — | — |
| Portrait | 64×64 | 32×32 | — | 1:1 |

**Canvas Rule**: Every sprite canvas MUST be a multiple of 32. This ensures clean scaling and pixel-perfect alignment in the isometric grid.

## 3. The Grimdark 64 Palette

This palette is LOCKED. All indexed-color sprites use it. See `assets/palettes/grimdark_64.gpl` for the GIMP palette file.

| Slot | Hex | Name | Usage |
|------|-----|------|-------|
| 0 | #0A0A0A | Void Black | Deepest shadows, outlines |
| 1 | #141414 | Soot | Dark armor recesses |
| 2 | #1E1E1E | Gunmetal Dark | Imperial Guard armor base |
| 3 | #282828 | Gunmetal Mid | Armor midtones |
| 4 | #323232 | Gunmetal Light | Armor highlights |
| 5 | #463C32 | Leather Dark | Boots, straps, pouches |
| 6 | #5A4A3C | Leather Mid | Leather main |
| 7 | #6E5E4C | Leather Light | Leather highlights, worn edges |
| 8 | #8B2D2D | Blood Red | Chaos accents, wounds, banners |
| 9 | #A63A3A | Blood Mid | — |
| 10 | #C14747 | Blood Light | — |
| 11 | #D4A024 | Imperial Gold | Aquilas, officer trim |
| 12 | #E8C848 | Gold Highlight | — |
| 13 | #F0E8A0 | Gold Shine | Specular hits |
| 14 | #8C7038 | Bronze Dark | Casings, pistons |
| 15 | #A88448 | Bronze Mid | — |
| 16 | #C4A058 | Bronze Light | — |
| 17 | #3C5A3C | Fatigue Dark | Guard uniform base |
| 18 | #4E784E | Fatigue Mid | — |
| 19 | #609660 | Fatigue Light | — |
| 20 | #2A2A3C | Navy Dark | Officer coats |
| 21 | #3C3C54 | Navy Mid | — |
| 22 | #4E4E6C | Navy Light | — |
| 23 | #5C4034 | Rust Dark | Corroded metal |
| 24 | #78543C | Rust Mid | — |
| 25 | #946848 | Rust Light | — |
| 26 | #B07C64 | Rust Highlight | — |
| 27 | #E8E0D4 | Bone | Skeletons, purity seals, parchment |
| 28 | #C8C0B4 | Bone Shadow | — |
| 29 | #A8A094 | Bone Dark | — |
| 30 | #E8D000 | Hazard Yellow | WARNING stripes, industrial markers |
| 31 | #B8A800 | Hazard Dark | — |
| 32 | #4C2A5C | Bruise Purple | Chaos magic, corruption, tentacles |
| 33 | #643A78 | Purple Mid | — |
| 34 | #7C4A94 | Purple Light | — |
| 35 | #243A4C | Steel Blue Dark | Environment shadows, water |
| 36 | #345A78 | Steel Blue Mid | — |
| 37 | #4A7A9C | Steel Blue Light | — |
| 38 | #5C8CB0 | Steel Blue Highlight | — |
| 39 | #4A3828 | Dirt Dark | Ground, mud, ash |
| 40 | #64503C | Dirt Mid | — |
| 41 | #7E6850 | Dirt Light | — |
| 42 | #988070 | Dirt Highlight | — |
| 43 | #6C6C5A | Concrete Dark | Industrial ground tiles |
| 44 | #8A8A78 | Concrete Mid | — |
| 45 | #A8A896 | Concrete Light | — |
| 46 | #C6C6B4 | Concrete Highlight | — |
| 47 | #FC4C04 | Plasma Orange | Energy weapons, muzzle flash |
| 48 | #FF7800 | Plasma Mid | — |
| 49 | #FFA420 | Plasma Light | — |
| 50 | #00B800 | Toxic Green | Chemical spills, poison |
| 51 | #00E000 | Toxic Mid | — |
| 52 | #40FF40 | Toxic Light | — |
| 53 | #1A1A24 | Void Blue | Deepest space shadows |
| 54 | #2E2E3E | Void Blue Mid | — |
| 55 | #44445A | Void Blue Light | — |
| 56 | #5C5C78 | Void Blue Highlight | — |
| 57 | #800000 | Gore Dark | Fresh blood pools |
| 58 | #A00000 | Gore Mid | — |
| 59 | #C02020 | Gore Light | — |
| 60 | #3C2A1E | Wood Dark | Furniture, rough barricades |
| 61 | #5C4230 | Wood Mid | — |
| 62 | #7C5A44 | Wood Light | — |
| 63 | #FF0000 | Pure Red | Screen ONLY, emergency UI, not sprites |

**Reserved**: Slots 0–3 are ONLY for true black/void. Never use #000000 as a color — it is reserved for "no data" / alpha failed regions in post-processing.

## 4. Isometric Projection Math

**True Isometric** (used by Fallout, Diablo 2):
- Horizontal angle: 30°
- Vertical tilt: 45° (azimuth)
- Scale ratio: 1.0 (no foreshortening compensation needed for pixel art)

**Pixel Math** (for tile drawing):
```
tile_screen_x = (grid_x - grid_y) × (tile_width / 2)
tile_screen_y = (grid_x + grid_y) × (tile_height / 2)
```

With 96×48 tiles:
```
tile_screen_x = (grid_x - grid_y) × 48
tile_screen_y = (grid_x + grid_y) × 24
```

**Z-Index Rule**: `z = grid_x + grid_y` (or `z = iso_y` in screen space). Lower screen Y = higher Z (painter's algorithm).

## 5. Character Proportions

- **Standard human**: 2.5 tiles tall (120 px in a 48px tile world). In our 96×128 frame, roughly 96 px tall.
- **Head**: ~1/6 total height
- **Shoulders**: ~1/4 total height
- **Waist**: ~1/2 total height
- **Feet**: aligned to tile bottom edge (origin point at center-bottom of tile footprint)

**Origin Point (pivot)**: Center of tile footprint, at ground level. The sprite is drawn upward from this point.

## 6. Animation Standards

| Animation | Frames | Duration @ 12 FPS | Notes |
|-----------|--------|-------------------|-------|
| idle | 4–6 | 333–500ms | Subtle breathing/weapon sway |
| walk | 6–8 | 500–667ms | Contact pose, passing, contact |
| attack | 4–6 | 333–500ms | Anticipation → strike → recovery |
| hurt | 2–3 | 167–250ms | Recoil, blood flash |
| die | 6–10 | 500–833ms | Collapse, maybe linger as corpse |

**Frame Naming**: `units_<name>_<anim>_<dir>_<frame>.png` where frame is zero-padded 2 digits: `units_guardsman_idle_N_01.png`

## 7. UI Design Rules

- **Borders**: 2–3 px thick, using Gunmetal Dark with Gold corners
- **Inset vs Outset**: Active buttons = outset (light top/left, dark bottom/right). Pressed = inset (reversed).
- **Text Area**: Minimum 4 px padding from border. Text color = Bone (#E8E0D4) on dark panels.
- **Icons**: Silhouette-first. Recognizable at 32×32. No fine details that vanish at small size.
- **Disabled State**: Desaturate to 50% opacity, NO hover state.
- **Hover State**: Slight Gold (#D4A024) glow on border (1–2 px outward).

## 8. Tile Design Rules

- **Seamlessness**: Ground tiles must tile without visible seams in all directions.
- **Transitions**: Between tile types (concrete → dirt), use 1–2 dedicated transition tiles per edge type (N, E, S, W, NW, NE, SE, SW).
- **Elevation**: Each elevation level = +24 px in canvas height (half tile height). A wall on elevated ground = base 96×128 + 24 for each level.
- **Break Repetition**: Every 3–4 tiles, minor variation (crack, stain, rust spot) so grid pattern doesn't show.

## 9. File Format Rules

| Stage | Format | Why |
|-------|--------|-----|
| Source | .blend, .ase, .xcf | Preserve layers, editable |
| Raw Render | .png (RGBA) | Blender native, lossless |
| Post-Process | .png (Indexed) | GIMP/LibreSprite, palette-locked |
| Final Export | .png (Indexed or RGBA) | Game-ready, compressed |
| Atlas | .png + .json | Packed image + metadata |
| Metadata | .json | Frame bounds, offsets, timing |

**Indexed PNG**: REQUIRED for all character sprites and tiles. UI elements MAY use RGBA if transparency gradients are needed (but prefer crisp edges).

## 10. LOD Visual Rules

| LOD | Visual Treatment |
|-----|------------------|
| LOD0 | Full detail, all colors, crisp edges |
| LOD1 | Merge adjacent similar colors, drop fine details (laces, small emblems), simplify shadows |
| LOD2 | Silhouette + 2-tone (base + highlight), no interior detail. Readable class silhouette only. |

LOD1 and LOD2 are generated automatically by the pixelation script — no manual redrawing.
