# STYLE RESEARCH — high-tier pixel art and animation, and what it means for our pipeline

**Status:** research record, 2026-11-09. Scope: the look, shading, effects and
animation of modern high-detail pixel art, and a full-scope production path for
IoA (characters, environment assets, VFX, animation). Covers the AAA → stylised
low-poly → high-detail pixel range, with pixel as the primary target.

**Method:** T2/T3 — primary practitioner accounts where they exist (developer
articles, lead-artist interviews), the shipped games as artefacts, and technique
literature for the craft rules. Every load-bearing claim carries a source and a
grade. Where only the game artefact supports a claim, it is graded D and labelled
inference.

**Terms used below:** *HD pixel* = high-detail pixel art at modern resolutions;
*PSX* = PlayStation-1-era low-poly 3D with pixelated textures; *3D→2D* = render a
3D model to sprite frames; *texel grid* = fixed world-size mapping of texture
pixels on a 3D model.

---

**Implementation:** the profiles derived from this research are defined in
[`STYLE_PROFILES.md`](STYLE_PROFILES.md) and `configs/styles/profiles.json`.

## 1. The finding that changes the plan

The best modern pixel work in the last five years is **not hand-drawn frame by
frame**. It is built in 3D or with heavy tooling, then deliberately degraded and
art-directed into pixels.

- **Dead Cells** built characters and monsters in 3DS Max, rendered them at very
  small size **without antialiasing** with a custom program, exported each frame
  **with its normal map** and applied a toon shader. Animations were authored
  pose-to-pose; in-betweens were added only *outside* the key poses. (Thomas
  Vasseur, lead artist; [Game Developer](https://www.gamedeveloper.com/production/art-design-deep-dive-using-a-3d-pipeline-for-2d-animation-in-i-dead-cells-i-), grade B/C.)
- **Warhammer 40,000: Boltgun 2** builds 3D models, captures them from **8 camera
  directions** with a custom renderer, and a script converts the output into
  compressed 2D sprite sheets. Normal and AO maps are used to "fake the look of 3D
  onto 2D sprites"; emission and reflection masks are authored per asset; enemies
  get **per-enemy resolution settings**; detail that is too fine is reduced to "an
  impression of the object"; edge highlights and hand-painted AO are applied for
  in-game readability. (Mark Chambers, lead artist, [Creative Bloq](https://www.creativebloq.com/3d/video-game-design/warhammer-40-000-boltgun-2s-lead-artist-reveals-how-they-made-pixel-art-feel-authentically-retro), grade B.)
- **Eastward** is, in its lead programmer's words, "a 3D game with a 2D
  perspective": assets built in 3D, hand-painted bump maps per asset to control
  lighting, custom engine with shader textures and lighting systems, every detail
  handcrafted. (Tommo Zhou, Pixpil, [Game Developer](https://www.gamedeveloper.com/art/eastward-s-creators-share-insights-on-making-pixel-art-adventures), grade B.)
- **Animal Well** uses procedural animation, a constantly-running fluid simulation
  for water/smoke, normal maps on background art and extensive dynamic lighting —
  "layering on more and more rendering systems over time". (Billy Basso,
  [Game Developer](https://www.gamedeveloper.com/art/animal-well-s-haunting-style-owes-much-to-procedural-animation), grade B.)
- **Sea of Stars** uses pixel sprites inside a modern lighting/VFX stack (dynamic
  lighting, colour highlights, day/night shading). ([Mega Visions](https://www.megavisions.net/the-art-of-sea-of-stars-a-sea-of-pixels/), grade C.)

**The 40K pixel references specifically.** *Boltgun* (2023) and *Boltgun 2* are the
closest published analogue to IoA's target: 3D-built assets, 8-direction captures,
sprite sheets, palette-locked, normal/AO faked onto the sprite. At the other end,
*Shootas, Blood & Teef* (2022) is hand-drawn 2D pixel art with a much smaller
frame budget. Between them they bracket what is achievable: Boltgun proves the
automated 3D→2D route can carry a full commercial 40K game; Shootas proves the
hand-drawn route still wins on character acting per frame. (Boltgun: grade B;
Shootas: grade D, artefact only.)

**Implication:** our existing architecture — 3D model, 8-direction renders,
palette-locked pixelisation — is the *same architecture* as Dead Cells and
Boltgun. We are not missing the big idea. We are missing the art direction layer
that decides what survives pixelisation, and the animation discipline that makes
it read.

---

## 2. What "high detail" actually means in pixel art

This is the part most automated pipelines get wrong. Detail in AAA art is
fidelity: polygons, texel density, PBR response. Detail in pixel art is
**information density per pixel**: contrast placement, cluster economy,
silhouette, and deliberate abstraction.

The Boltgun lead artist states the mechanism directly: detail too fine to survive
is converted into "an impression of the object", with emphasis on weaponry,
armour and skin patterns, plus edge highlights and hand-painted AO "for
readability". (grade B)

Design rules that follow, and that a generator must be taught rather than left to
invent:

1. **Silhouette first.** The largest shapes must read at final on-screen size
   (Dead Cells' characters are about 50 px tall in game — grade B for the figure).
2. **Cluster economy.** Detail lives in a few deliberate clusters (face, weapon,
   chest rig); flat planes carry the rest. Noise is the failure mode.
3. **Contrast zoning.** Light against dark at the focal point; the palette ramp
   does the shading, not gradients.
4. **Abstraction, not reduction.** Scaling down a detailed render produces mush;
   the shapes must be redesigned for the pixel grid.

Consequence for us: **the generation target is not the final sprite.** It is a
clean, flat-shaded 3D master with exaggerated forms, which the pixel stage then
degrades under art direction. That is exactly the Dead Cells/Boltgun/Eastward
pattern.

---

## 3. Shading technique catalogue

| Technique | What it does | Rule / caveat | Source |
|---|---|---|---|
| Hue-shifted ramps | Shading that shifts hue (warm shadows / cool highlights or vice versa) reads as painted, not filtered | 3–5 steps per ramp; never pure black/white | Slynyrd pixelblog catalogue (grade C), Lospec tutorials (grade C) |
| Selout (selective outline) | Outline colour chosen from the adjacent form instead of black | Keeps sprites from reading as stickers; essential at HD sizes | technique literature (grade C) |
| Ordered dither (Bayer) | Creates intermediate tones on a fixed palette | Use for gradients, not for texture; 4×4 at most | our own `pz/pixel/pixelise.py` implements bayer2/4 (artifact A) |
| Hand-painted AO | Faked contact shadow to seat the sprite | Boltgun does this explicitly | Creative Bloq (grade B) |
| Edge highlight | 1 px rim on upper edges | Boltgun names it as a readability technique | grade B |
| Normal/AO as sprite masks | Faking 3D response onto a 2D sprite | Requires the 3D master to carry the maps | Boltgun, Dead Cells (grade B) |
| Emission/reflection masks | Glow and specular as authored layers | Use sparingly or the retro read collapses | Boltgun (grade B) |
| Dynamic lighting layers | Engine-side light that multiplies the sprite | Eastward, Sea of Stars, Animal Well | grade B/C |
| Palette locking | Fixed palette per project/biome | Our `grimdark_64` + `pz/pixel/palette.py` | artifact A |

**Our current state:** palette locking, Bayer dithering, ink outlines and a
verifier already exist (`pz/pixel/styles.py`, `pixelise.py`,
`verify_pixel_asset.py`). Missing: hue-shifted ramp generation, selout, AO/edge
highlight authoring inside the 3D master, and per-asset mask exports.

---

## 4. Animation standards and technique

### 4.1 Timing over frame count

Pixel animation is authored in **frame holds at 12–24 fps** and played back inside
a 60 fps loop. More frames do not equal better animation; timing, anticipation and
impact do. Dead Cells' approach is explicit: pose-to-pose keyframes first, the
minimum number of frames, and interpolation added only after the timing works —
"never in-between" the key poses. (grade B)

Budget guidance for HD pixel at our camera distance (inference from the shipped
games, grade D):

| Action | Frames (authored) | Notes |
|---|---|---|
| idle | 4–8 | breathing loop; sub-pixel motion acceptable |
| walk | 6–10 | contact/pass/contact; 8 directions or 4 + mirror |
| run | 6–8 | longer stride, lean; smear on the fastest frame |
| aim | 3–5 | upper-body layer |
| fire | 3–6 | 1-frame recoil, 1–2-frame muzzle flash, shell eject |
| reload | 8–14 | magazine-out/in beats; can reuse across weapons |
| hit | 2–4 | 1-frame white flash + knockback pose |
| death | 6–12 | ragdoll or staged collapse; can end on a persistent corpse frame |
| melee | 6–10 | wind-up, smear, contact, follow-through |

### 4.2 Techniques that separate professional work from amateur work

- **Sub-pixel animation** — moving a sprite by fractional pixels between frames to
  suggest smooth motion without adding frames. Documented as a standard modern
  technique ([Lospec tutorial by Kiwi](https://lospec.com/pixel-art-tutorials/give-your-sprites-depth-with-sub-pixel-animation-by-kiwi), grade C).
- **Smear / distortion frames** — 1–2 frames where the limb is stretched or the
  weapon is drawn as an arc. This is how impact reads at low frame counts
  (Dead Cells uses VFX for exactly this purpose — grade B).
- **Impact frames** — a single near-white or near-black frame at contact.
- **Afterimages** — 1–2 ghost frames, low alpha, palette-shifted.
- **Anticipation and follow-through** — a 2–3 frame wind-up before every attack,
  and a settle afterwards; without it, attacks read as teleports.
- **Recoil and camera** — screen shake and hit-stop belong to the engine, not the
  sprite, but they are part of the style contract.
- **Directional coverage** — 8 directions for isometric, 4 + mirror for
  side-on. Boltgun renders 8 camera directions (grade B); our `render_8dir_v2.py`
  already does 8.

### 4.3 Hybrid / procedural animation

Animal Well shows the modern alternative: procedural animation, fluid simulation
and dynamic lighting layered over pixel sprites (grade B). That is cheap to author
and expensive to make tasteful. For us it is the right tool for **environment**
motion (water, smoke, growth, flicker) and the wrong tool for **character acting**.

---

## 5. Environment and effects

| Asset class | Standard | Pipeline note |
|---|---|---|
| Tiles | 16/32/64 px grid, seamless, 3–5 value ramp | Generate as 3D tiles then render orthographic, or author as tile sheets; our `tile_generator.py` + `render_8dir_v2.py` cover the first |
| Parallax | 2–4 depth layers with distinct palettes and blur/desaturation by depth | Render layers separately from the 3D scene |
| Props/decals | Same palette; damage states | 2–3 states per prop (intact/damaged/destroyed) |
| Lighting | Separate multiply/add layers, never baked into the albedo | our `derive_maps.flatten_lighting` exists for the 3D tier; the 2D tier needs explicit light layers |
| VFX | 3–6 frame flipbooks, 1–2 px particles, additive only on emissive | generate as sheets and cut, as we already do |
| UI/portraits | 64×64 to 128×128, same palette and outline language | reuse the style registry |

Modern pixel environments are **authored, not tiled randomly**: biome palettes,
height strata, sightline control, and lighting as a storytelling layer (Eastward's
fog/sunbeam work is the benchmark — grade B).

---

## 6. The 3D pixel tier (PSX-adjacent)

This is the tier that lets a 3D scene look pixel-art without becoming a sprite
game. It has its own contract:

- **Texel grid:** a fixed world size per texel (e.g. 1 texel = 2 cm) and UVs
  snapped to it. Without this, pixels swim.
- **Texture budget:** 128–256 px maps, palette-locked, no PBR maps. Boltgun's
  per-enemy resolution is the same idea at sprite level (grade B).
- **Shader:** affine texture warp, optional vertex snapping/jitter, ordered dither
  and palette quantisation in-engine. Crow Country, Signalis and Ultrakill are
  reference artefacts for the read (grade D — game artefacts).
- **Geometry:** 300–2,000 tris, flat shading, hard edges. The silhouette must be
  authored for the grid.

This tier reuses our retopo and bake stages but needs a new material model
(palette-locked albedo, no normals) and a new gate (texel-grid consistency, not
seam scores).

---

## 7. What our pipeline already has

| Capability | Where | Status |
|---|---|---|
| Pixel style registry (palette, size, dither, ink, outline) | `pz/pixel/styles.py` | built — includes `hd` (256 px, bayer2, soft ink) |
| Pixeliser + asset verifier | `pz/pixel/pixelise.py`, `verify_pixel_asset.py` | built |
| 8-direction 3D renders | `tools/blender/render_8dir_v2.py` | built |
| Sprite atlas packing | `tools/packer/pack_sprites.py` | built |
| 2D canvas standards (96×128, 64-colour palette) | `docs/STYLE_GUIDE.md` | documented |
| 3D LOD/retopo/bake | `retopo_unit.py`, `bake_unit_atlas.py` | built (AAA tier) |
| Style identity model | `materials_v3_800` texture LoRA | adopted |

## 8. What is missing

1. **A per-asset style profile** that selects representation and budget
   (`pixel_sprite` / `pixel_3d` / `lowpoly_3d` / `aaa_3d`) and drives every stage.
2. **The 3D master art direction** for pixel targets: exaggerated silhouette, flat
   cel shading, thick ink, authored AO/edge highlights, emission/reflection masks
   exported with the frames (the Boltgun recipe).
3. **Sub-pixel motion and smear/impact frames** in the animation set; today our
   clips are pose-correct but not impact-correct.
4. **A per-style gate.** Palette compliance, silhouette readability at target zoom,
   texel-grid consistency, direction coverage, animation timing — not PBR seam
   scores.
5. **Hue-shifted ramp generation** and selout in the pixeliser; dithering exists,
   ramps do not.
6. **A reference corpus** per style, so an adapter can hold the look (30–80 curated
   frames per style is enough at our training cost).

---

## 9. Recommended full-scope pipeline

```
style profile (representation, budget, palette, shading model, gate set)
  → concept/orthos (hosted image model, per-style prompt fragments from styles.py)
  → 3D master with exaggerated forms + flat cel shading + ink (Blender, scripted)
  → animation: pose-to-pose keys, minimum frames, then in-betweens outside keys
  → 8-direction render, no AA, per-asset resolution (existing render_8dir_v2)
  → masks: normal, AO, emission, reflection (existing bake stages, repurposed)
  → pixelise: area downsample, ink mask, palette (Oklab), dither, selout, ramps
  → sub-pixel motion + smear/impact frames (post-pass on the frame sequence)
  → atlas pack + metadata (existing packer)
  → gate: readability at 1× and 2× zoom, palette compliance, direction coverage,
    animation timing sheet, sheet budget
  → engine: pixel-perfect camera, light layers, particles, hit-stop, shake
```

For the 3D pixel tier the same graph applies, replacing the sprite stages with the
texel-grid UV stage and the palette-locked material build.

## 10. Effort and order

| Step | Effort | Why first |
|---|---|---|
| Style profile + gate schema | 1–2 days | unblocks every style without rework |
| 3D master art direction for pixel targets (ink, flat cel, mask export) | 3–5 days | this is where the look is won or lost |
| Pixeliser upgrade: ramps, selout, sub-pixel, impact frames | 4–6 days | turns correct sprites into professional ones |
| Environment pipeline (tiles/parallax/light layers) | 1–2 weeks | largest asset volume |
| 3D pixel tier (texel grid + palette material + shader) | 1–2 weeks | optional until a 3D pixel scene is required |
| Per-style adapter + reference corpus | 2–3 days per style | holds consistency at volume |

---

## 11. Evidence quality and open questions

- **Strong (B):** the 3D→2D methods at Dead Cells, Boltgun 2 and Eastward; the
  procedural/lighting layer at Animal Well; Boltgun's per-asset resolution and
  mask technique.
- **Moderate (C):** shading rules (hue shifting, selout, dither) from established
  tutorial literature; Sea of Stars' lighting stack from secondary coverage.
- **Weak (D), flagged as inference:** frame-count budgets per action; the claim
  that 8 directions are sufficient at our camera distance; the exact texel-grid
  size for our game.
- **Unresolved:** whether our 3D-master + pixelise route can match hand-drawn
  animation *feel* at 12 fps without a human animator reviewing timing. The
  affordable test is one character, one attack, one walk, reviewed at 1× and 2×
  zoom against a reference sprite from Boltgun/Eastward.
- **What would change the conclusion:** if a pixel-art adapter trained on curated
  frames can hold cluster economy and silhouette as reliably as the 3D-master
  route, the 3D master becomes optional for small props — worth testing on the 79
  material tiles we already have.

## 12. Sources

| # | Source | Grade | Used for |
|---|---|---|---|
| 1 | Vasseur, "Using a 3D pipeline for 2D animation in Dead Cells", Game Developer | B | 3D→2D, pose-to-pose, normal-map toon shading, ~50 px |
| 2 | Chambers interview, Creative Bloq (Boltgun 2) | B | 8-direction capture, sprite-sheet script, normal/AO faking, per-enemy resolution, edge highlights |
| 3 | Zhou interview, Game Developer (Eastward) | B | 3D game/2D perspective, hand-painted bump maps, lighting |
| 4 | Basso interview, Game Developer (Animal Well) | B | procedural animation, fluid sim, normal maps, layered rendering |
| 5 | Mega Visions, "The art of Sea of Stars" | C | modern lighting/VFX over pixel sprites |
| 6 | Lospec pixel-art tutorials (incl. Kiwi, sub-pixel animation) | C | sub-pixel motion, shading vocabulary |
| 7 | Slynyrd pixelblog catalogue | C | hue-shifted ramps, cluster economy, animation timing |
| 8 | Our own artefacts (`pz/pixel/styles.py`, `pixelise.py`, `verify_pixel_asset.py`, `render_8dir_v2.py`) | A | current capability |
| 9 | Crow Country / Signalis / Ultrakill (game artefacts) | D | PSX 3D read |

*Retrieved 2026-11-09. Re-check when a style profile ships, or when a reference
sprite fails the readability gate.*
