# AI Generation Workflow
## Imperium of Ash Asset Pipeline — Gemini Pro Integration

## Role of AI in This Pipeline

**Gemini Pro is a concept artist, NOT a final asset generator.**  
It generates references, mood boards, and orthographic turnaround guides. Final sprites are Blender-rendered from 3D models that use AI concepts as visual targets.

**Why not AI direct-to-sprite?**
- Copyright risk: AI training data unclear
- Inconsistency: AI struggles with 8-direction consistency, palette-locking, exact frame sizes
- Control: Blender gives exact angles, exact colors, exact timing
- Scale: Re-rendering 5 animations × 8 directions for 10 units = 400 frames. AI batch generation is unreliable; Blender scripting is deterministic.

## What Gemini Pro Generates

### 1. Concept Art (Per Unit / Per Tile Set)

**Prompt structure** (copy this template, fill variables):

```
Isometric sprite concept art for a grimdark tactical game. 
Subject: [UNIT_NAME], [DESCRIPTION].
Style: Industrial military, Warhammer 40K inspired, pre-rendered 3D-to-2D pixel art look.
Palette: Restricted 64-color grimdark — gunmetal, bone, rust, Imperial gold, hazard yellow.
View: True isometric, 30-degree elevation, showing [DIRECTION] facing.
Background: Pure black (void).
Resolution target: 96x128 pixel sprite frame.
Details: [ARMOR_TYPE], [WEAPON], [DISTINCTIVE_FEATURES].
Mood: Oppressive, battle-worn, heavy industrial.
No text, no UI elements, clean sprite on black background.
```

**Example — Imperial Guardsman**:
```
Isometric sprite concept art for a grimdark tactical game. 
Subject: Imperial Guardsman, basic human infantry in flak armor.
Style: Industrial military, Warhammer 40K inspired, pre-rendered 3D-to-2D pixel art look.
Palette: Restricted 64-color grimdark — gunmetal (#1E1E1E), bone (#E8E0D4), rust (#78543C), Imperial gold (#D4A024), hazard yellow (#E8D000).
View: True isometric, 30-degree elevation, showing SOUTH-EAST facing.
Background: Pure black (#0A0A0A void).
Resolution target: 96x128 pixel sprite frame.
Details: Flak armor with aquila chest plate, lasgun held at ready, helmet with rebreather, fatigue pants (green), heavy boots.
Mood: Oppressive, battle-worn, determined.
No text, no UI elements, clean sprite on black background.
```

### 2. Orthographic Turnaround (4-View)

For 3D modeling reference, generate 4 orthographic views (front, side, back, top) in a single prompt:

```
Character orthographic turnaround reference sheet, 4 views arranged in a grid:
Top-left: Front view. Top-right: Side view (facing right).
Bottom-left: Back view. Bottom-right: Top-down view.
Subject: [same as above]
Style: Clean line art, flat colors, no shading, no background.
Useful for 3D modelers.
```

### 3. UI Concept Sheets

```
UI element concept sheet for a grimdark tactical game.
Elements needed:
- Rectangular button, gothic industrial style, 64x32px
- Panel frame segment, modular 64x64
- Circular unit portrait frame with gold aquila border
- Status icons (buff, debuff, wounded, dead), 32x32px each
Style: Dark steel, gold accents, bone parchment textures, hazard stripes.
Palette: grimdark industrial (gunmetal, gold, bone, blood red, hazard yellow).
Arranged on black background with labels.
```

### 4. Environment Mood Boards

```
Environment concept art: industrial battlefield tileset.
5 scenes showing different terrain types:
1. Cracked concrete factory floor with rusted pipes
2. Ash-waste desert with metal ruins
3. Corrupted temple with tentacle growth (Chaos)
4. Imperial trench with sandbag walls
5. Hive city interior with metal walkways
Style: Pre-rendered 3D-to-2D, isometric view, grimdark 40K.
Palette: grimdark 64-color restricted.
Use as reference for Blender tile modeling.
```

## Storing AI-Generated References

**Never commit AI output to git.** Keep it in a refs directory that is gitignored:

```
refs/                            # .gitignore this entire directory
├── units/
│   └── imperial_guardsman/
│       ├── concept_front.png
│       ├── concept_side.png
│       ├── concept_ortho_sheet.png
│       └── mood_battlefield.png
├── ui/
│   └── ui_concept_sheet_01.png
└── tiles/
    └── tile_concrete_01.png
```

Only `.blend` files and final sprite outputs are tracked.

## From AI Concept to Blender Model

Workflow:
```
1. Generate concept with Gemini Pro → Save to refs/
2. Open LibreSprite or GIMP → Trace key silhouette and color blocks
3. Use traced image as background reference in Blender
4. Model in Blender using palette materials (Emission shader)
5. Compare render to concept → Iterate model until match
6. Once concept is matched, run render_8dir.py
7. Archive concept in refs/ (or delete if confident)
```

## Prompt Discipline Tips

- **Always specify "isometric" and angle**: "true isometric, 30-degree elevation"
- **Always specify the palette**: Gemini handles color better when constrained
- **Always specify "no text, no UI"**: Prevents watermarks and labels in output
- **Use "pre-rendered 3D-to-2D pixel art look"**: This cues Gemini to generate images that look like they came from a 3D render pipeline (clean edges, flat color regions, consistent lighting)
- **Generate multiple concepts per prompt**: 3–4 variations, pick best
- **Iterate**: If concept is 70% right, crop the good part and prompt again with "inspired by this image" + corrected details

## API Call Example

The user has Gemini Pro API key in opencode config. A wrapper script (`tools/ai/generate_concept.py`) will eventually automate this. For now, manual via Google AI Studio or API curl:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key=$GEMINI_API_KEY" \
  -H 'Content-Type: application/json' \
  -X POST \
  -d '{
    "contents": [{
      "parts":[{
        "text": "[PROMPT HERE]"
      }]
    }]
  }'
```

## Safety & Policy

- Do not generate content that violates Google AI safety policies
- AI references are temporary creative aids, not final products
- Always verify AI-generated concepts match the grimdark palette before using as modeling targets
- If AI output is unusable (wrong proportions, wrong colors), re-prompt with more specific constraints rather than editing the bad output
