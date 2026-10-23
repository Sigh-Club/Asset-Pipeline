# Generation-Model Training: Data Requirements & Local Fine-Tuning Research

**IoA asset-pipeline — research report, 2026-10-23**
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

## 10. Requirements & staged plan — hardware-verified (2026-10-23)

Every number below was checked against the primary source on 2026-10-23. Claims that could
not be verified are marked **UNVERIFIED — stage-0 experiment**; none are assumed.

### 10.0 Machine state (measured)

- GPU: RTX 3070 Ti, 8192 MiB, driver 615.71.09. RAM 32 GiB, 16 threads.
- `/home` (nvme): 83 GiB free of 930G — too small for the model set; see 10.2.
- `games` (sdb, btrfs): 670G free — datasets, checkpoints, trainer venvs (small-file IO + snapshots).
- `SAMSUNG-1TB` (sdc, NTFS): mounted `/mnt/samsung`, **931G free, empty, user-writable** —
  verified 2026-10-23. Hosts model weights / HF cache (large sequential files; NTFS fine).
  (`games2` referenced in older docs is a different, currently absent volume.)
- `~/ComfyUI`: present, near-empty (SD1.5 only). `~/.cache/huggingface`: 40G already.
- `gemini-img`: LIVE, auth installed, proven 2048px generation (skill: Gemini section).

### 10.1 Verified capability matrix (8 GB training)

| Model | Trainer | Verified status | Evidence |
|---|---|---|---|
| Qwen-Image-Edit-2511 LoRA | musubi-tuner `--model_version edit-2511` | Documented floor **12 GB** (fp8_base + swap 45, 1024px, bs1). 8 GB UNVERIFIED. Swap >45 raises RAM sharply; 64 GB RAM recommended — we have 32. | musubi docs/qwen_image.md VRAM table |
| Z-Image-Turbo LoRA | ai-toolkit (`low_vram: true`) | 8 GB UNVERIFIED (5090 ~1 h/3k steps documented; lower cards "enable Low VRAM"); musubi also ships zimage support | ai-toolkit README; HF blog engineering notes |
| SDXL LoRA | any | 8 GB comfortable, widely documented | sanj.dev tiers; kohya guides |
| FLUX.1-dev LoRA 8 GB | sd-scripts fp8 + split, 512px | Verified by maintainer in-issue; licence = non-commercial + paid synthetic-data clause | sd-scripts #1595; bfl.ai/licensing |
| FLUX.1-schnell | — | Apache-2.0 licence-safe FLUX fallback | HF tags |

Empirical stage-0 tests required (the two UNVERIFIED rows are cheap and gate the model
choice): (a) musubi Qwen-Edit swap>=45 on 8GB VRAM / 32GB RAM — watch RAM, not just VRAM;
(b) ai-toolkit Z-Image low_vram on 8GB. Until then the proven 8 GB path is SDXL, then Z-Image.

### 10.2 Disk budget (sizes verified via HF API) — host on `games`, not /home

| Item | Size | Note |
|---|---|---|
| qwen_image_edit_2511_bf16.safetensors | 40.9 GB | musubi: fp8_e4m3fn single-file "cannot be used" for Edit; a 2511 fp8mixed 20.5GB exists — musubi compat UNVERIFIED |
| Qwen2.5-VL-7B text encoder | 16.6 GB | shared with Qwen-Image |
| Z-Image-Turbo repo (bf16) | 32.8 GB | 24.7 transformer + 8.1 text enc + 0.2 vae |
| SDXL base 1.0 | 6.94 GB | |
| wd-eva02-large-tagger-v3 | 3.8 GB | captioner |
| fal Multiple-Angles LoRA | 0.30 GB | Apache-2.0, 66k downloads |
| Total core stack | ~101 GB | + checkpoints/datasets; split: weights + HF cache on `/mnt/samsung` (931G), datasets/checkpoints on `games`, nothing heavy on /home (83G) |

### 10.3 Pause / resume (verified)

- musubi-tuner: `--resume <state>` (src/musubi_tuner/training/parser_common.py:622) plus
  `--resume_from_huggingface`.
- ai-toolkit: ctrl+c anytime, restart resumes from last checkpoint — caveat: interrupting
  during a checkpoint save can corrupt it (README). Queue wrapper must wait for
  save-complete before signalling stop.

### 10.4 Corpus requirements (quantities; rationale in section 3)

Sprite-swap pairs 150-300 + 20 held-out (render factory); faction anchors 20-30 + exemplars
20-40 + regularisation 10-20 per faction (Gemini harvest + curated); icons 100-300
(game-icons.net CC-BY + own); turnaround: none needed (fal pretrained). Gemini quota:
30-40 gens/day, sheet-multiplier cropping gives ~300-500 crops/day ceiling; Pro model
reserved for hero anchors.

### 10.5 Staged gates (verified-first ordering)

0. Env and empirics: install trainers in pinned venvs on `games`; run the two 10.1 tests;
   verify gemini cookie; choose primary model FROM TEST RESULTS, not preference.
1. Pair factory: (ref, sheet, mask, metadata) from existing units; 100 percent critic-pass;
   at least 5 unit-types x 3 anims.
2. Gemini harvest (parallel from day 1): 3-4 windows/day; 600+ banked crops before stage 4.
3. Caption/QC/bucket + MANIFESTs; critic gate on every synthetic frame.
4. Style LoRA on the stage-0 winning base; blind side-by-side at LOD2 vs anchors.
5. Sprite-swap LoRA; unseen-character consistency at least hand-render variance.
6. img23d turnaround integration; re-run img23d gate (verify >= 85).
7. Icons/UI/marketing + train jobs in queue dashboard; prove pause/resume incl. the
   save-window caveat from 10.3.

### 10.6 Standing risks (operational; none assumed away)

1. 8 GB Qwen-Edit training may not fit in 32 GB RAM — fallback chain: Z-Image -> SDXL
   style/sprite via img2img templates, Chroma / FLUX-schnell (Apache) thereafter.
2. PSIDTS cookie rot stalls harvest silently — add gemini-img auth check to morning queue.
3. ai-toolkit checkpoint corruption on interrupt-during-save — wrapper waits for save.
4. /home disk pressure — weights on `/mnt/samsung`, datasets on `games`; audit before stage 2.
5. NTFS on Linux: no symlinks/permissions — keep venvs and anything symlinked on btrfs/ext4,
   only plain weights/caches on the Samsung. Mount is not in fstab — verify at boot or add entry.
6. docs/AI_GENERATION.md still contradicts this strategy — refresh at stage 4 sign-off.

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

### Additional primary sources (verified 2026-10-23)

- musubi-tuner Qwen-Image docs (VRAM table, Edit-2511, fp8 notes): https://github.com/kohya-ss/musubi-tuner/blob/main/docs/qwen_image.md
- musubi-tuner `--resume`: https://github.com/kohya-ss/musubi-tuner/blob/main/src/musubi_tuner/training/parser_common.py (line 622)
- musubi-tuner Z-Image support: `src/musubi_tuner/zimage/` in repo tree
- ai-toolkit (MIT, 12.4k stars; resume behaviour + checkpoint-save caveat): https://github.com/ostris/ai-toolkit/blob/main/README.md
- Z-Image-Turbo file sizes: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo/tree/main
- Qwen-Image-Edit ComfyUI splits (2511 bf16 40.9GB / fp8mixed 20.5GB): https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/tree/main/split_files/diffusion_models
- Qwen2.5-VL-7B-Instruct (16.6GB): https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct/tree/main
- SDXL base 1.0 (6.94GB): https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/tree/main
- wd-eva02-large-tagger-v3 (3.8GB): https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3
- fal Multiple-Angles LoRA (0.30GB): https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA
- Z-Image LoRA engineering notes (low_vram, 5090 baseline): https://huggingface.co/blog/content-and-code/training-a-lora-for-z-image-turbo

### 10.7 Environment audit + trainer landscape (2026-10-23 pm, all verified from primaries)

**Have**: GPU 8GB + driver 615.71 (cu13x-capable), CUDA toolkit 13.4 (`/opt/cuda`), python
3.12 + 3.14, `uv`, `hf` CLI, git, 1.6T combined free (games 670G + samsung 931G), HF cache
40G (SD1.5 family, IP-Adapter, ControlNet, Hunyuan, Trellis, **facebook/dino-vitb16 — reuse
as the similarity-eval backbone**), `gemini-img` live. ComfyUI cloned, stale/empty.

**Missing (the entire setup gap)**: no trainer repos or venvs; no SDXL/Qwen/Z-Image weights;
no captioner models. The `.venv-assets` venv in Imperium-of-Ash has no torch (img23d venv
must be rebuilt or relocated — do not assume it works).

**Trainer landscape (verified from each repo's own docs, 2026-10-23)**:

| Trainer | Qwen-Edit | Z-Image | Notes |
|---|---|---|---|
| musubi-tuner 0.3.6 | edit-2511 yes (12GB documented floor) | yes (`zimage/`) | py>=3.10, torch>=2.6; `--resume`; Apache-friendly |
| ai-toolkit (MIT, 12.4k stars) | Edit-2511 yes; **Qwen-Image-2.1/-Turbo yes (unified t2i+edit!)** | yes + low_vram | pins torch 2.13 cu130 in README |
| diffusion-pipe (tdrussell) | **yes + LoRA directly on fp8_scaled quantised weights** | yes | DeepSpeed hard req (Linux OK); offloading = best 8GB hope for Qwen |
| SimpleTuner (bghira) | Qwen Image + edit paths ("reference-input training ... Qwen Edit") | yes | widest model table; licence per-model |
| OneTrainer | not verified this pass — check before use | ? | |

**New model fact — licence change**: Qwen-Image-2.1 / 2.1-Turbo (7B visual DiT! transformer
14.3GB, total ~33GB bf16) are **Qwen Research Licence — commercial use needs a separate
licence** (LICENSE §2b). The older Qwen-Image / Edit-2511 remain Apache-2.0. For shipped game
assets: prefer Apache bases (Edit-2511, Z-Image, SDXL) or secure the 2.1 commercial licence.
2.1-Turbo's unified t2i+edit would simplify the stack to ONE base — worth a licence email.

**Stage-0 install order (all free, ~60 min + download time)**:
1. `uv venv` per trainer on `games`; torch per repo pin (musubi: any>=2.6 cu128/cu130;
   ai-toolkit: 2.13 cu130) — driver 615.71 supports both.
2. Clone musubi-tuner + ai-toolkit (+ diffusion-pipe for the fp8-weights experiment).
3. Weights to `/mnt/samsung`: SDXL 6.9G, Z-Image-Turbo 32.8G, qwen_edit_2511_bf16 40.9G +
   Qwen2.5-VL-7B 16.6G (only if the Qwen path survives testing; fp8_scaled via diffusion-pipe
   would halve it — UNVERIFIED).
4. Run the two 8GB empirics; record nvidia-smi + RAM peaks in this doc.
