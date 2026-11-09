# Generation-model training: what to train, what not to, and why

**Research report — 2026-11-09 (supersedes the 2026-10-23 draft)**
**Scope:** local fine-tuning of image, 3D, material, motion and VFX models for
Imperium of Ash *and* future projects with different art direction. Constrained to
what one workstation can actually do.

This report answers three questions only: **what is worth training**, **what data
does it need**, and **what must not be trained because the arithmetic does not
work on this machine**. Every number cites the trainer's own documentation.

---

## 1. Executive decision

| Domain | Train locally? | Why |
|---|---|---|
| Image style / albedo / decals | **Yes** — small LoRA, Apache-2.0 base | cheap, fast loop, reusable across projects |
| PBR material sets | **Yes**, as a tileable-albedo LoRA + local map derivation | the bottleneck is style control, not model capability |
| 3D shape | **No, not yet** | 3.3B-parameter DiTs, datacenter training; the real fix is better input images and retopo |
| Motion / animation | **No** | pretrained text-to-motion exists; retargeting beats fine-tuning for a 9-clip set |
| VFX / effects | **No, unless style consistency demands it** | video LoRA is the heaviest tier (24 GB class); procedural + image-model flipbooks cover most needs |
| UI icons / frames | **Yes, optional** | small dataset, high reuse, same pipeline as image LoRA |

The single most important finding: **the 8 GB card is not the binding constraint —
the 31 GB of system RAM is.** Modern low-VRAM training works by block-swapping
weights to system RAM. Hunyuan3D and Qwen-Image both assume 64 GB+ for their low
tiers, so on this box the safe training bases are the *small* Apache models
(FLUX.2 klein 4B, Z-Image-Turbo 6B), not the 20B class.

Second finding: **Gemini is the highest-leverage shortcut in the pipeline and it is
already paid for.** It replaces most of the small-data curation problem (concepts,
orthos, tileable albedo, decals) and it can seed a training corpus. What it cannot
do is produce consistent geometry, alpha, or normal maps.

---

## 2. This workstation, measured

| Resource | Value | Consequence |
|---|---|---|
| GPU | RTX 3070 Ti 8 GB, ~1.4 GB desktop, ~6.5 GB free | training must fit ≈6 GB unless offloaded |
| RAM | 31 GB total, ~20 GB available | block-swap >16 blocks gets tight; 64 GB-class configs are out |
| CPU | 8C/16T | dataloaders are fine; CPU-offloaded optimisers are slow but usable |
| Disk | 622 GB free on the games volume | ample for datasets and checkpoints |
| Existing env | `tools/img23d/.venv` (torch 2.14 cu126) | training needs its own venv; do not disturb inference |

Practical rule: **a training run may use the GPU for hours, so it must be scheduled
like a render, not started casually.** Same one-job-at-a-time policy as
`tools/gpu_policy.py`; add a `train` row before the first run.

---

## 3. Image models — the tier that works here

### 3.1 Documented VRAM floors (from the trainers, 2026)

| Base | Trainer | Floor | Settings behind the floor |
|---|---|---|---|
| **FLUX.2 klein 4B** (Apache-2.0) | SimpleTuner | **8 GB** | int8 base, 32 GB+ RAM, single 16 GB GPU recommended; bf16 needs ~12 GB |
| **Z-Image-Turbo 6B** (Apache-2.0) | SimpleTuner | **10 GB** | NF4/int8, 512 px, batch 1, Lion8bit paged, grad checkpointing |
| Chroma1-HD (Apache-2.0) | SimpleTuner / OneTrainer | 8 GB | rank-16 LoRA, NF4 base; unquantised ~28 GB |
| FLUX.1 dev (non-commercial) | sd-scripts | 8 GB | `--fp8_base --blocks_to_swap 28`, 512 px |
| SDXL | sd-scripts/kohya | 10 GB | batch 1, grad checkpointing, AdamW8bit; 16–24 GB comfortable |
| **Qwen-Image / -Edit 20B** | musubi-tuner | **12 GB** | fp8 base + `--blocks_to_swap 45`, 1024 px, batch 1 — **64 GB RAM recommended** |
| FLUX.2 klein 9B (non-commercial) | OneTrainer | 8 GB | INT_W8A8 transformer, offload 0.7 — but 64 GB RAM recommended |
| HunyuanVideo / Wan 2.2 | musubi-tuner | 24 GB | 720p video; `--fp8_base`, block swap |

Sources: `musubi-tuner/docs/qwen_image.md` VRAM table (42 GB → 30 GB fp8 → 24 GB
swap 16 → 12 GB swap 45); `musubi-tuner/docs/wan.md` (24 GB for 720p training);
vramready.com's aggregation of SimpleTuner, OneTrainer, sd-scripts, fluxgym and
ai-toolkit official configs (2026-09-25).

**Correction to the previous draft:** it claimed Qwen-Image-Edit trains at ≤8 GB.
The documented floor is **12 GB with 45 swapped blocks and 64 GB RAM**. On a 31 GB
box that is a swap-heavy, slow proposition. Treat Qwen as the *aspirational* base,
not the first one.

### 3.2 Licence reality (this decides the base more than VRAM does)

| Model | Licence | Commercial game | Train on its outputs |
|---|---|---|---|
| FLUX.2 klein **4B** | Apache-2.0 | yes | yes |
| FLUX.2 klein **9B**, FLUX.1/2 dev | BFL non-commercial | yes, with terms | paid synthetic-data licence |
| Z-Image-Turbo 6B | Apache-2.0 | yes | yes |
| Chroma1-HD, FLUX.1 schnell | Apache-2.0 | yes | yes |
| Qwen-Image / -Edit 2511 | Apache-2.0 | yes | yes |
| SDXL / SD 3.5 | OpenRAIL-based | yes | yes |
| Gemini outputs | Google terms | yes | yes (only *grounded search* results are restricted) |

The klein licence split is not a detail: **4B is Apache-2.0, 9B is non-commercial.**
A quantised community port inherits the upstream licence — check the model card, not
the downloader's label (there are already mislabelled Z-Image quantisations).

### 3.3 Decision

**Primary training base: FLUX.2 klein 4B (Apache-2.0) on SimpleTuner**, because it is
the only current-generation Apache model with a documented 8 GB floor and a
commercial-clean licence. **Secondary: Z-Image-Turbo** for speed and text rendering
(10 GB floor; run at 512 px). **Qwen-Image-Edit 2511** is the right base for
template-swap work (SpriteForge pattern) but needs more RAM than we have today —
revisit on a 24 GB/64 GB upgrade.

**Rank and steps:** rank 16 for style, 32 for a broad material library; 1,000–2,500
steps at 512–768 px. Community datasets for style LoRAs are 30–80 curated images;
character-consistency LoRAs work from 10–30. We do not need a character LoRA — our
characters are 3D meshes.

---

## 4. Materials and textures — train the tiling, derive the maps

The local pipeline already does the hard engineering (`build_material_manifest.py`
→ Gemini albedo → `derive_maps.py` → Blender box-projected library). What a LoRA
adds is **style consistency at volume**: one model that produces IoA-looking
grimdark sci-fi albedo for any surface, and the same for a future project with a
different palette.

Training data recipe (this is the part that decides success):

| Item | Count | Notes |
|---|---|---|
| Tileable albedo tiles | 150–300 | mixed materials, neutrally lit, no baked shadows, no border frames |
| Captions | one per tile | material, era, wear level, colour — use the existing prompt vocabulary from `families.json` |
| Held-out set | 20 | never trained on; used for the gate |
| Negative examples | 20 | the failure modes: framed plates, baked lighting, non-tiling edges |

The technique that matters is **tileability at inference**, not in the weights:
circular-padding the latent at every denoising step (ComfyUI-seamless_latent_tiling)
gives mathematically exact tiling; a LoRA plus circular padding is the strong
combination. We already measure the result with `seam_score` in `derive_maps.py`,
so the gate exists before the model does.

PBR maps stay derived locally. Two research-grade alternatives exist and should be
evaluated before building them ourselves:

- **Material Anything** (CVPR 2025 Highlight, 3DTopia/MaterialAnything) — feed-forward
  PBR generation for texture-less or albedo-only meshes, geometry- and
  lighting-aware, outputs albedo/normal/roughness/metalness.
- **DreamMat** (SIGGRAPH 2024) — geometry- and light-aware PBR material diffusion
  explicitly designed to avoid baked-in shading in albedo.

Both solve the exact weakness of our derived-map shortcut (plausible micro-relief
that is not tied to real height). Neither needs training. Action: benchmark Material
Anything on one unit mesh, compare against `derive_maps.py`, and adopt only if the
VRAM fits the 6 GB working budget.

---

## 5. 3D shape — do not train it yet

Both credible open pipelines release training code, and both are built for
multi-GPU:

- **Hunyuan3D-2.1** (Tencent): 3.3B shape DiT + PBR paint model, full weights and
  **training code** released; training infrastructure uses DeepSpeed at datacenter
  scale; the repo ships an 8-case preprocessed `mini_trainset` for overfitting
  experiments. Dataset format is image/multiview → mesh with camera metadata.
- **TRELLIS** (Microsoft): ~2B rectified-flow transformer on Structured Latents,
  trained on a curated ~500K-asset dataset; training framework is modular and
  designed for fine-tuning, and LoRA adapters have been requested upstream
  (issue #339). TRELLIS.2 continues the line.

What that means in practice: a meaningful shape fine-tune needs **thousands** of
(multiview, mesh) pairs. We can manufacture them — every Blender render is an exact
pair — but the payoff is low while the model's failure mode is *input image quality*
and the missing retopo stage, not style. Conditioning beats fine-tuning at this
scale.

**Decision:** keep img23d zero-shot; improve its inputs (better orthos, consistent
turnarounds), and spend the engineering on retopo/part separation. Revisit a shape
LoRA when we have 1,000+ manufactured pairs and a 24 GB card.

---

## 6. Animation — retarget, don't train

Text-to-motion research is mature (MoMask, MotionLCM, MoMask++) but the outputs are
SMPL-format skeletons from HumanML3D-scale corpora, and every game use of them
requires retargeting to the game rig anyway. Our rig is already Mixamo-compatible,
which is the cheapest interchange in the ecosystem.

- **Now:** retarget free/CC0 Mixamo clips onto the shared rig, bake, export via NLA
  tracks, and author the 9-clip set. Procedural clips are acceptable for proof, not
  for shipping locomotion.
- **Later, if faction gait matters** (Bloom quadrupeds, Revenant stutter): a motion
  LoRA or a small fine-tune is possible, but only after the retarget path is
  exhausted and the clip set exists.

---

## 7. VFX and effects — procedural first, generate the exceptions

- Particles, muzzle flashes, decals, trails, weather, shader glow: **procedural** in
  Three.js/Blender. Free, deterministic, parameterised per faction.
- Flipbook sheets and animated textures (explosions, warpfire, smoke plumes): image
  model for the key frames, assembled locally into an atlas. Cheap, and the agent
  can review each frame.
- Video-model LoRAs (Wan 2.2 class): 24 GB-tier training. Use pretrained models
  zero-shot for short effects; fine-tune only when a project's VFX style must be
  consistent across dozens of effects.

---

## 8. Gemini as the shortcut engine

Gemini is not a substitute for a renderer or a trainer; it is what removes the
expensive parts of *dataset creation* and *material authoring*. Current capability
(verified in the `gemini-image` skill and Google's terms):

- Up to 14 reference images (Pro: 6 objects + 5 characters); edit chains for
  consistency; 1K/2K/4K; explicit commercial-use permission; training on outputs
  permitted.
- Known limits: **no alpha channel** (any "transparent" result is a fake
  background), identity drift across edits, dense-sheet cropping, and it has no idea
  what a normal map is.

Where it should replace slow work:

| Task | Gemini shortcut | What still must be local |
|---|---|---|
| Concept exploration for a new project/style | 4–8 variants in one window | selection and style ratification |
| Orthographic turnarounds for img23d | one 4-view sheet, then cut locally | consistency check against the reference |
| Tileable albedo for the material library | 4-up sheets, 22 generations for 79 items | seamless repair, flattening, normal/rough/metal derivation |
| Decals, insignia, UI icons | sheet-multiplier: N-up grids | alpha extraction (keying locally) |
| Style reference sheet for a LoRA dataset | a 20-image grid in 5 generations | captioning, dedupe, split |
| VFX key frames | frame-by-frame edit chains | atlas assembly, timing, engine hooks |

Where it must not be used: geometry (it has none), normal maps (inconsistent),
final PBR sets (no channel semantics), anything requiring exact dimensions.

**Quota economics:** roughly 30–40 standard generations/day on the Pro consumer
plan, 8–12 per 5-hour window. The library plan needs 22; a style dataset needs 5–8
sheets. One window per task, not one task per window.

**The distilled-data risk, stated plainly:** training a local model on Gemini output
is legally permitted, but it teaches the local model to imitate a *derived* style,
not the source art. For our purpose (consistency + volume) that is correct. For a
project that must match an external art bible, prefer Blender renders and human
picks as the corpus, using Gemini only for augmentation.

---

## 9. Dataset manufacture — our unfair advantage

We own a paired-data factory that most studios pay for: every asset we make is
generated from a config, so its caption, camera, palette and mask are exact.

```
configs/ (unit, faction, palette)
   → Blender render (orthos, turnaround, albedo, PBR maps)
   → exact metadata (camera, light, material slot, seed)
   → dataset shard: (image | multiview | mask | motion clip) + caption
```

This is the same insight SpriteForge used (VRoid → Mixamo → Blender → sprite sheet
templates; trained on 100 pairs and generalising to unseen characters), and the
fal Multiple-Angles LoRA (96 camera poses from 3,000 manufactured pairs) is the
proof that manufactured multiview data works for the img23d stage.

Rules that keep the corpus honest:

1. **Caption from the config, never from a captioning model.** WD14/JoyCaption noise
   is what makes small datasets fail.
2. **Split by asset, not by frame.** Frames of one unit in both train and eval leak
   and inflate every metric.
3. **Hold out a style.** For a multi-project model, train on projects A–C and test
   on D; a style LoRA that memorises one project is a filter, not a model.
4. **Record the seed, the render script hash and the config in each shard's
   manifest.** Otherwise the corpus cannot be regenerated when Blender changes.
5. **Licence provenance per shard** (own render / Gemini / CC0 / third-party).

---

## 10. Evaluation — loss is not a metric

A LoRA that trains cleanly can still be worthless. Gates, in order:

1. **Held-out prompt grid** — 12 prompts × 4 seeds, generated at fixed settings,
   reviewed visually. Fail if the base model's general knowledge collapses (text,
   anatomy, lighting) or the style is only present at the training resolution.
2. **Material-specific:** seam score of every generated tile must be ≤ 0.02 after
   the existing repair step; texel density unchanged; no baked lighting (low-frequency
   luminance variance below the flatness threshold in `derive_maps.py`).
3. **Regression set** — 8 prompts unrelated to the training domain. Any degradation
   means the rank or learning rate is too high.
4. **Style distance** — CLIP/DINO embedding distance to the reference style set
   versus the base model. Direction must improve; absolute value is not a gate.
5. **In-pipeline proof** — apply to a real unit and render it (the existing
   `preview_unit_materials.py` loop). This is the only gate that decides shipping.
6. **Licence check** — base model, training data provenance, and any third-party
   LoRA stacked on top.

Never accept "the samples look nice" as the sole evidence, and never accept a
lower loss as evidence at all.

---

## 10a. Measured on this box (2026-11-09) — first pilot

| Fact | Measured |
|---|---|
| Base/model | FLUX.2 klein-4B, int8-sdnq DiT + int8-sdnq text encoder |
| Memory recipe | `offload_during_startup`, `gradient_checkpointing_offload_attention`, batch 1, 512 px → peaks at 7.4 GB |
| Speed | 3.17 s/step cold, **1.05 s/step steady**; 1,500 steps in ~28 min |
| Dataset | 112 train / 10 eval tiles, two factions held out completely |
| Result | base model rendered *rooms* for a material prompt; the LoRA rendered flat material tiles |
| Failure | over-trains past ~750 steps (1,000–1,500 collapse to flat grey); usable adapter `checkpoint-750` |
| Tiling | not a property of the LoRA — repaired seam ≤0.02 on 7/9 conditional samples; exact tiling needs circular padding at inference |

Consequence for the plan: training is cheap enough on this box to iterate several
times per evening. The scarce resources are dataset quality and evaluation
attention, not GPU time. The next run should hold everything constant except
steps (600–750) and caption length.

## 11. Plan, in the order the constraints allow

| Phase | Work | Cost | Gate |
|---|---|---|---|
| T0 | Add a `train` profile to `gpu_policy.py`; create a separate `tools/train/.venv` (SimpleTuner) | minutes | `plan --job train` resolves |
| T1 | Material style LoRA on FLUX.2 klein 4B: 150 tiles, rank 16, 512–768 px | one overnight run | §10 gates 1–3 on 20 held-out tiles |
| T2 | Adopt or reject Material Anything by benchmarking one unit mesh | one afternoon | visual A/B vs `derive_maps.py`; fits ≤6 GB |
| T3 | Style LoRA per new project (the reusable procedure) | same as T1 | held-out style split (§9 rule 3) |
| T4 | Optional: icon/decal LoRA; VFX flipbook workflow | small | in-engine proof |
| T5 (deferred) | 3D shape LoRA, motion fine-tune, video LoRA | 24 GB class | only after T1–T4 are stable |

Do T1 before touching 3D training. It is the cheapest end-to-end proof that the
dataset factory, the trainer, the evaluation and the licence chain all work — and it
feeds the material library that the game needs *now*.

---

## 12. Corrections recorded against the 2026-10-23 draft

1. Qwen-Image-Edit is **12 GB / 64 GB RAM**, not 8 GB. Our 31 GB RAM is the real
   limit; klein 4B and Z-Image are the appropriate bases.
2. FLUX licensing is not uniform: **klein 4B is Apache-2.0; klein 9B and dev are
   non-commercial.**
3. "AI cannot generate final assets" was too absolute. It cannot generate *shippable*
   assets unaided; it is the correct front-end for concepts, albedo and dataset
   seeding.
4. The derived-map shortcut is now known to have a stronger alternative (Material
   Anything / DreamMat) and should be benchmarked, not assumed.
5. Shape fine-tuning was implied to be on the table; it is not, at this scale.

---

## 13. Open questions to settle with measurements

- Actual step rate and wall-clock for klein 4B at 512 px on this card with SimpleTuner
  (expect hours; measure before scheduling an overnight run).
- Whether 20 GB available RAM survives `--blocks_to_swap` for a klein 4B run under
  the desktop's normal load.
- Whether Material Anything's VRAM fits the 6 GB working budget at 512 px.
- Whether Gemini-generated albedo is a better *training* corpus than Blender-rendered
  albedo for tile consistency. Test with the same 150-tile recipe and compare gates.
- Whether a single LoRA can serve two visually different projects, or whether
  per-project adapters are the honest answer (likely the latter).

---

## 14. Sources

- kohya-ss/musubi-tuner, `docs/qwen_image.md` VRAM table and `docs/wan.md`
  (fetched 2026-11-09)
- vramready.com/lora-training — aggregation of SimpleTuner, OneTrainer, sd-scripts,
  fluxgym, ai-toolkit documented minimums (data dated 2026-09-25)
- Tencent-Hunyuan/Hunyuan3D-2.1 — repo, training page, `mini_trainset`; arXiv 2506.15442
- microsoft/TRELLIS — project page, training framework, issue #339 (LoRA fine-tune)
- 3DTopia/MaterialAnything — CVPR 2025 Highlight; xhuangcv.github.io/MaterialAnything
- zzzyuqing/DreamMat — SIGGRAPH 2024
- EricGuo5513/momask-codes, MotionLCM — text-to-motion baselines
- Google Gemini API Additional Terms; `gemini-image` skill (verified capability and
  quota notes)
- SpriteForge (tantk.github.io/spriteforge-pipeline) and fal Qwen-Image-Edit
  Multiple-Angles LoRA — manufactured-pair precedents
- bfl.ai/licensing and DeepWiki FLUX.2 licensing — Apache-2.0 vs non-commercial split
- ComfyUI-seamless_latent_tiling — circular-padding tileability technique

---

## 10b. Second pilot and operational tooling (2026-11-09, later session)

| Fact | Measured |
|---|---|
| Corpus v2 | 168 train / 10 eval tiles, `kind=material` only. The v1 corpus carried 28 trim-sheet **pattern** tiles; the adapter drew their chevrons and grids onto rust surfaces. Patterns and decals are now excluded from the material corpus. |
| Training | 800 steps at 384 px, LR 5e-5, 1.42 s/step steady, 18 min 52 s wall. Checkpoints every 200. No OOM once the 1 GB Wine game was closed, but the box ran with ~0.1–0.5 GB free; 448 px and 512 px both OOM'd while desktop GPU consumers held 0.9–1.0 GB. |
| Sampling | `generate.py` (FLUX.2 klein + adapter, sequential CPU offload, ~40 s per 448 px / 16-step tile). Model-level offload OOMs with a browser holding 3 GB; sequential offload fits in ~2 GB. |
| Tiling | Latent-space periodic blending (unpack → border cross-fade → repack every denoising step) cut raw wrap-edge difference from 0.104 to 0.035 on the same prompt and seed. Production repair still runs afterwards. |
| Metric correction | Absolute wrap-edge difference is not a seam metric: a correct high-frequency tile has a large border difference. The gate now uses wrap-edge / interior-edge ratio ≤ 1.5 (measured 0.56–2.08 on real samples). `derive_maps.py` and `ingest_generated.py` now use the same ratio as the repair trigger (repair only above 1.5), so a correct high-frequency tile is no longer blended into a worse one. |
| Style gate | Mean-colour dE cannot judge a multi-colour material and falsely rejected 15/24 correct tiles. Replaced with a 4×4 colour-layout + chroma-histogram descriptor against the faction's reference set, tolerance = that set's leave-one-out p95. |
| Regression gate | 8 out-of-domain prompts, base vs adapter at the same seed, scene-structure score. All retained ≥ 50 % of base structure (no capability collapse at 800 steps). |

Consequence: the dataset is the product. The single largest quality change between
v1 and v2 was removing 28 trim-sheet tiles from the corpus, not changing any
hyperparameter. Do not add pattern/decal art to a surface-material corpus.

In-pipeline proof (same session): the adopted adapter's four Iron Directorate slot
tiles were ingested into a copy of the library and box-projected onto the
line-infantry proof mesh, then rendered (`output/gen/unit_proof/`). The navy enamel
and gold pinstriping survive derivation, projection and lighting. This is the only
gate that actually decides adoption; the tile grid alone is not enough.
