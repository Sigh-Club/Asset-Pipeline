# Generation-Model Training: Data Requirements & Local Fine-Tuning Research

**IoA asset-pipeline — research report, 2026-02-27**
**Scope**: what training data local LoRA fine-tuning requires to reach hosted-model quality for game, web and marketing art — on one RTX 3070 Ti 8 GB, time-unlimited.

---

## 1. Executive summary

The single most important finding from prior art: **never ask a diffusion model to invent an 8-frame sprite sheet from a text prompt.** Every successful pipeline (academic and community) conditions on *structure* and learns only *style/identity*:

- **Sprite Sheet Diffusion** (Hsieh et al., arXiv 2412.03685) — pose-conditioned sheet generation; ships a CC0 reference dataset and VBench-based subject-consistency eval. MIT code.
- **SpriteForge** (tantk.github.io/spriteforge-pipeline) — the strongest pattern: **character-swap into an existing sprite-sheet template** with a Qwen-Image-Edit-2511 LoRA. "The consistency comes from the template, not the generation." Trained on only **100 image pairs**; generalises to unseen characters *and* unseen animations. Templates sourced from Blender+Mixamo renders — exactly our existing rig.
- **fal Multiple-Angles LoRA** (HF `fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA`, Apache-2.0, 66k downloads) — 96 precise camera poses from a reference image, 3000 training pairs. Directly solves orthographic turnarounds for the img23d stage.

Consequence for us: **the training data is mostly manufactured, not collected.** We already own a perfect paired-data factory (DoW geometry/atlas extracts + Blender render rig + faction configs). TheLoRA corpus is:

1. **Paired synthetic data** — (render, sprite-sheet) and (char, pose/angle) pairs auto-generated from our own meshes. Unlimited, perfectly captionable, zero licence risk.
2. **A small curated style set** (30–80 images) that defines the "IoA look" per faction.
3. **Licence-clean third-party sets** for icons/UI and augmentation.

Model choice on 8 GB: **Qwen-Image-Edit-2511 (Apache-2.0)** as primary — it is the base both SpriteForge and the multi-angle LoRA use, trains via musubi-tuner with block-swapping at ≤8 GB, and is a 2026-generation model. **Z-Image-Turbo (Apache-2.0, 6B)** as the fast T2I workhorse — proven LoRA-trainable on 8 GB cards. FLUX dev/2 only with licence care (non-commercial + paid synthetic-data licence).

---

## 2. Licence landscape (evidence)

| Asset | Licence | Commercial game OK | Train-on-outputs OK | Source |
|---|---|---|---|---|
| Qwen-Image / Qwen-Image-Edit-2511 | Apache-2.0 | Yes | Yes | HF `Qwen/Qwen-Image`, `Qwen/Qwen-Image-Edit-2511` tags |
| Z-Image-Turbo (Tongyi-MAI) | Apache-2.0 | Yes | Yes | HF `Tongyi-MAI/Z-Image-Turbo` tags; 651k downloads |
| FLUX.1-dev / FLUX.2-dev | BFL non-commercial | Yes, self-host terms | **Paid "Synthetic Data" licence required to train on outputs** | bfl.ai/licensing; help.bfl.ai self-serve dev licence FAQ |
| FLUX.1-schnell, Chroma | Apache-2.0 | Yes | Yes | BFL licensing page; DeepWiki FLUX licensing split |
| Gemini API image outputs | Permitted, no general train-on restriction | Yes | Yes — the only "train on" clause in the Gemini API terms applies to *Grounding with Google Search results*, not generated images | ai.google.dev/gemini-api/terms |
| game-icons.net (4k+ icons) | CC-BY 3.0 | Yes, with attribution | Yes | repo README |
| Dawn of War extracted assets | Relic copyright — owned by us as game assets; as *training data* for our own private LoRAs: low risk, but outputs inherit the same posture as using the assets directly | Already our policy | n/a | docs/DOW_IMPORT.md; PIPELINE_GUIDE.md |
| Sprite-Sheet-Diffusion dataset | CC0 | Yes | Yes | repo README |

Note: `docs/AI_GENERATION.md` ("no diffusion, no paid APIs, GLM writes scripts only") predates the img23d / DoW-import / Gemini-concept reality and needs a policy refresh to match this report.

---

## 3. The training-data specification, per asset class

### A. Unit sprites — template-swap LoRA (the core system)

**Task**: `ref(image of unit X) + template(sprite sheet of poses) → sheet of X in IoA style`.

**Data required per model** (SpriteForge showed 100 pairs suffice; budget 150–300 for 2 factions × animations):

| Component | Count | Source | Cost |
|---|---|---|---|
| (ref, sheet) pairs — seen characters | ~120 | Auto-rendered: our Blender rig or DoW meshes → 8-dir/action sheets, one char per identity; ref = single front ortho frame | CPU/GPU render hours only |
| (ref, sheet) pairs — held-out characters | ~20 | Same factory, excluded from train for eval | minutes |
| Template sheets — unseen at train time | 3–5 animations | Hand-built or borrowed; proves generalisation | hours |
| Captions | per pair | Template + deterministic metadata (we *know* the pose/action/camera — captioning is a lookup, not a VLM call) | free |

**Why our factory is uniquely good**: every pair's caption, mask and pose metadata is exact because we rendered it. No WD14/JoyCaption noise. This is the same insight SpriteForge used (VRoid→Mixamo→Blender); our version is already half-built (`parametric_unit_generator.py`, `render_8dir_v2.py`, DoW import chain).

**Base model**: Qwen-Image-Edit-2511. **Trainer**: kohya `musubi-tuner` (`--model_version qwen_image_edit_2511`), LoRA rank 16–32, block-swap for 8 GB.

### B. Faction style LoRA ("the IoA look")

**Task**: make *any* generation (concepts, web art, marketing) gravitate to our grimdark identity without prompt gymnastics.

**Data required**: **30–80 images per faction**, hierarchy:
1. **Anchor set (mandatory, ~20–30)**: our best existing renders/plates, post-processed — these define palette, edge language, lighting.
2. **Style-exemplar set (~20–40)**: hand-picked references matching the target (DoW 1/2 renders we own, miniature photography, faction mood boards). Licenced-by-possession for private fine-tune; keep `refs/` out of git per repo rule.
3. **Regularisation (~10–20)**: neutral genre images so the LoRA learns style, not specific models.

**Captions**: natural-language, structure `"<faction> <unit type>, <materials>, <lighting>, grimdark tactical game art"` — trigger word per faction (`ioa_iron_directorate` style). Caption with an ensemble (see §5) then hand-fix the anchors.

### C. Multi-angle / turnaround LoRA (feeds img23d)

**Task**: single concept image → consistent 8-direction ortho set → `tools/img23d/` reconstruction. This is the missing bridge that makes AI concepts *usable* by the 3D stage.

**Data required**: none initially — use the pre-trained **fal Multi-Angles LoRA** (96 poses, Apache-2.0). Fine-tune our own only if faction style drift appears; ~300–1000 (ref, angle) pairs from the same factory as (A), pose indices = our 8 directions × elevation.

### D. Icons, UI, web graphics

- **Icon style LoRA**: 100–300 icons. Seed set: game-icons.net (CC-BY, 4000+, thematically ideal — grimdark RPG iconography), recoloured to faction palettes; plus our generated status icons. Qwen-Image's text/layout strength also handles icon sheets zero-shot; LoRA adds consistency.
- **UI**: keep procedural (`generate_ui_elements.py`) — deterministic UI needs no diffusion. LoRA only for hero illustrations (faction crests, loading screens): covered by (B).
- **Marketing/web art**: style LoRA (B) + 2× upscaler (SDXL/ESGAN); no extra dataset beyond (B).

### E. What we deliberately do NOT train

- 3D generation models (Hunyuan/Trellis) — use pretrained; 8 GB forbids meaningful fine-tuning; the quality lever there is *input image quality*, which (C) fixes.
- Video models — out of scope until the game needs them.

---

## 4. 8 GB trainer matrix (evidence-backed)

| Model | Trainer | 8 GB config | Evidence |
|---|---|---|---|
| Qwen-Image / -Edit 2511 (20B) | kohya **musubi-tuner** | fp8 base + `--blocks_to_swap` (user-tunable to VRAM); community LoRA runs reported at 6–12 GB | musubi-tuner docs `qwen_image.md`; Gözükara stage-1 configs ("as low as 6 GB"); lilting.ch VRAM tables |
| FLUX.1-dev (12B) | kohya sd-scripts | fp8 T5 + split mode, 512–768 px | sd-scripts issue #1595 ("Yes you can… 8 gb vram at 512") |
| Z-Image-Turbo (6B) | ostris **ai-toolkit** | documented configs for RTX 3060/3080-class 8–12 GB; ~1 h/LoRA anecdotal | smartart.live; HF blog "Training a LoRA for Z-Image Turbo"; civitai article 23863 |
| SDXL | any trainer | comfortable at 8 GB, fp16 + gradient checkpointing + 8-bit Adam | universal; sanj.dev VRAM tiers |

**Quality-parity argument** (the "equivalent to competitors" requirement): Qwen-Image-2511 and Z-Image are current-generation Apache models — the same bases the community LoRA scene and the ModelScope competition use. A LoRA does not downgrade the base; hosted services (the "competitors") run these exact weights. Our disadvantages are only throughput and the 8 GB resolution ceiling during *training* — mitigated by training 768–1024 px and inferring at 1536+ (tiles/VAE), and by the fact that sprite work is small-format by nature.

**Throughput expectation** on 3070 Ti: Qwen-Image LoRA ~1–3 min/step-image-budget-hour scale — a 100-pair × 3–5k-step run is an overnight job, matching our existing overnight render-queue discipline.

---

## 5. Dataset manufacturing & QC chain (to build)

```
configs/*.json + DoW OBJ/atlas + .blend library
        │  render_8dir_v2 / dedicated pair-renderer
        ▼
raw renders ──► pair assembler (ref, sheet, mask, pose-metadata)
        │
        ├─► captions: deterministic from render metadata (pairs)
        │             VLM ensemble for photographic/style sets:
        │             WD14-EVA02 (tags) + JoyCaption/Florence-2 (natural) + hand-fix anchors
        ├─► QC: LoRA-Dataset-Coach-style checks (dupes, embed spread, tag balance)
        │       + our critic.py metrics on every synthetic frame
        ▼
bucketed dataset (aspect-ratio buckets, 768–1024 px) ──► musubi-tuner / ai-toolkit
```

- Never train on frames that fail `critic.py` — the critic becomes the dataset gate, not just the render gate.
- Keep every dataset versioned and regenerable (`datasets/<name>/MANIFEST.md`: source commit, seed, counts) — same discipline as `.blend` masters.

## 6. Evaluation (extend the critic, don't invent)

From SSD: per-frame **SSIM/PSNR/LPIPS** vs ground truth + **VBench subject-consistency** across the sheet. Both are scriptable and run on 8 GB. Gate: a sprite-swap LoRA ships when unseen-character consistency ≥ our hand-render baseline's variance, and the existing visual checklist (silhouette, material fidelity, faction identity) passes on held-out characters.

## 7. Long-run control (pause/resume/queue — user requirement)

All three trainers checkpoint and **resume**: musubi-tuner/sd-scripts `--resume from weights`, ai-toolkit `--resume`. Plan:
- Wrap training jobs in the existing `render_queue.py`/`queue_dashboard.py` job model (job type `train`): live step loss, ETA, pause = SIGINT at checkpoint boundary, resume = requeue with `--latest`.
- Checkpoint every 250 steps + on pause; keep last 3.
- GPU arbitration: reuse the img23d GPU-budget gate pattern (desktop reserve, single tenant at a time).

## 8. Risks / open items

1. **Qwen-Image-Edit 20B training wall-time** on 8 GB with heavy block-swap — measure before committing; Z-Image/SDXL fallbacks are instant swaps.
2. **Style-set licence hygiene** for the 20–40 reference images per faction — keep out of git, record sources in the dataset MANIFEST.
3. **DoW-derived LoRA outputs** — same ownership posture as using DoW assets directly; fine for IoA, record the decision.
4. `docs/AI_GENERATION.md` policy doc contradicts this strategy — refresh it when the first LoRA ships.
5. img23d stage still has open gate items (`[ ] First real concept-to-asset run`) — the turnaround LoRA (C) is its missing input-quality fix; sequence C before that gate re-run.

## 9. Phased delivery

1. **P1 — pair factory**: extend render rig to emit (ref, sheet, metadata) pairs from existing units; critic-gated. *No training yet.*
2. **P2 — style LoRA (B)** on Z-Image or SDXL (cheapest loop, proves toolchain end-to-end, feeds web/marketing immediately).
3. **P3 — sprite-swap LoRA (A)** on Qwen-Image-Edit-2511 via musubi; eval per §6; first real unit through full chain.
4. **P4 — turnaround LoRA adoption (C)**: integrate fal Multi-Angles into img23d input stage; re-run the img23d gate.
5. **P5 — icons (D)** + queue/dashboard integration for `train` jobs.

---

## Source index

- sd-scripts 8 GB FLUX: https://github.com/kohya-ss/sd-scripts/issues/1595
- musubi-tuner Qwen-Image(-Edit) training: https://github.com/kohya-ss/musubi-tuner/blob/main/docs/qwen_image.md
- Sprite Sheet Diffusion: https://arxiv.org/abs/2412.03685 ; https://github.com/chenganhsieh/Sprite-Sheet-Diffusion
- SpriteForge: https://tantk.github.io/spriteforge-pipeline/
- fal Multiple-Angles LoRA: https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA
- Qwen-Image-Edit VRAM tables: https://lilting.ch/en/articles/qwen-image-edit-2511-local-specs
- Z-Image LoRA on 8 GB cards: https://smartart.live/articles/267-tired-of-vram-errors-and-failed-training-rtx-306030804070-owners-train-z-image-turbo-lora-in-1-hour-with-this-proven-ostris-ai-toolkit-configuration.html ; https://huggingface.co/blog/content-and-code/training-a-lora-for-z-image-turbo
- BFL licensing / synthetic-data clause: https://bfl.ai/licensing ; https://help.bfl.ai/articles/9272590838
- Gemini API terms (train-on clause scope): https://ai.google.dev/gemini-api/terms
- Dataset QC tooling: https://github.com/akalavol/LoRA-Dataset-Coach; captioner comparison https://artificialguy.com/blog/captioning-tools-2026-joycaption-wd-tagger/
- VRAM calculators / tiers: https://www.bestfreewebresources.com/lora-training-vram-requirements-2026 ; https://sanj.dev/post/lora-training-2025-ultimate-guide/
