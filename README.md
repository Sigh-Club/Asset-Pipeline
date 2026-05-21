# Asset-Pipeline for Imperium of Ash

**Automated 3D-to-2D isometric sprite generation pipeline for grimdark tactical games.**

Built for **Imperium of Ash** (IoA), a Warhammer 40K-inspired tactical combat game transitioning to true isometric gameplay.

## Quick Start

```bash
# 1. Generate a character in Blender, save as .blend in assets/characters/<name>/model/
# 2. Render 8 directions + animations
blender assets/characters/imperial_guardsman/model/imperial_guardsman.blend --background --python tools/blender/render_8dir.py

# 3. Post-process to palette-locked pixel art
python tools/gimp/batch_pixelate.py --source assets/characters/imperial_guardsman/render/raw --output assets/characters/imperial_guardsman/render/processed

# 4. Pack into sprite sheets
python tools/packer/pack_sprites.py --source assets/characters/imperial_guardsman/render/processed --output output/v0.1.0/characters --name imperial_guardsman

# 5. Sync to IoA
python tools/sync_to_ioa.py --version v0.1.0 --ioa-path "../Imperium of Ash" --yes
```

## Repository Layout

```
asset-pipeline/
├── AGENTS.md              # Master rules for all AI assistants
├── README.md              # This file
├── docs/
│   ├── STYLE_GUIDE.md     # Resolution, palette, naming conventions
│   ├── BLENDER_WORKFLOW.md # Step-by-step 3D-to-2D pipeline
│   └── AI_GENERATION.md   # Gemini Pro prompts and concept workflow
├── assets/
│   ├── palettes/           # Shared color palettes (.gpl)
│   ├── ui/                 # Buttons, panels, menus
│   ├── tiles/              # Isometric environment tiles
│   ├── characters/         # 3D models + renders + sheets (per unit)
│   └── effects/            # VFX sprite sheets
├── tools/
│   ├── blender/
│   │   ├── render_8dir.py      # 8-direction isometric auto-render
│   │   └── batch_render_all.py # Batch render all characters
│   ├── gimp/
│   │   └── batch_pixelate.py   # Post-process: quantize, noise removal, pad
│   ├── packer/
│   │   └── pack_sprites.py     # Sprite sheet atlas packer + JSON metadata
│   ├── ai/
│   │   └── (Gemini Pro wrapper scripts — TBD)
│   └── sync_to_ioa.py          # Auto-sync output to IoA repo
└── output/
    └── v<X.Y.Z>/           # Game-ready exports per release
```

## Design Philosophy

1. **Pre-rendered 3D to 2D**: The Fallout/Diablo 2 method, modernized. Models exist in 3D. Sprites are derived products.
2. **True 8 Directions**: No mirroring. All 8 compass points (N, NE, E, SE, S, SW, W, NW) are individually rendered.
3. **Palette-Locked**: All sprites use the `grimdark_64` palette. Visual consistency is mandatory.
4. **Fully Automated**: From `.blend` to sprite sheet, zero manual clicking.
5. **AI-Assisted, Not AI-Generated**: Gemini Pro creates concepts and references. Blender creates final pixels.

## IoA Integration

Read `AGENTS.md` for exact IoA specs:
- Tile footprint: 96×48 px, canvas 96×128
- Character frames: 96×128 px
- Animation target: 12 FPS
- Grimdark palette: 64 colors (industrial, rust, bone, gold, blood)

## Documentation

| Document | Purpose |
|----------|---------|
| `AGENTS.md` | Rules, naming conventions, tool defaults for AI assistants |
| `docs/STYLE_GUIDE.md` | Visual identity, resolution tables, palette specs, animation standards |
| `docs/BLENDER_WORKFLOW.md` | Blender setup, camera rig, lighting, render automation, troubleshooting |
| `docs/AI_GENERATION.md` | Gemini Pro prompt templates, reference storage rules, concept→model workflow |

## Tool Dependencies

All tools are **free**:
- **Blender** 3.6+ (render engine)
- **LibreSprite** (sprite cleanup)
- **GIMP** 2.10+ (optional batch processing — script uses Pillow)
- **Python** 3.10+ with **Pillow** (`pip install pillow`)
- **Gemini Pro API** (user key in opencode config)

## Phase Status

| Phase | Status | Description |
|-------|--------|-------------|
| Foundation | COMPLETE | Repo, docs, palette, tooling |
| UI & Menus | READY TO START | Buttons, panels, icons |
| Isometric Tiles | PENDING | Ground, walls, cover, props |
| 8-Direction Characters | PENDING | Imperial Guardsman, Scout, Cultist, Marine, Officer |
| Higher Fidelity | PLANNED | Normal maps, particles, LOD variants, re-render at higher resolution |

## License

MIT — Tools and scripts are open. Game assets (sprites, textures) belong to Imperium of Ash project.

## Contributing

All asset creation follows the documentation in `docs/`. No undocumented code, no unapproved palette deviations.

For IoA-specific requirements, see `AGENTS.md` Section 2: "IoA Integration Specs".
