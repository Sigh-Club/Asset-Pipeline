# Training environment — exact recipe that works on this box

Written 2026-11-09 after getting a FLUX.2 klein-4B LoRA to train on the 8 GB card.
Every step below was needed; none is optional decoration.

## Constraints this recipe is built around

8 GB VRAM shared with the desktop (~1.1 GB held by kwin/Chrome), 31 GB RAM,
Ryzen 5700X3D. The RAM ceiling is why only small bases are viable — see
`docs/GENERATION_TRAINING_RESEARCH.md`.

## Install (once)

```bash
cd /run/media/talzanar/games/Projects/IoA/asset-pipeline
python3.12 -m venv tools/train/.venv
tools/train/.venv/bin/pip install -U pip
tools/train/.venv/bin/pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu126
tools/train/.venv/bin/pip install simpletuner
```

Then apply three fixes, each of which otherwise blocks startup:

1. **TorchAudio must match the CUDA build.** The default PyPI wheel is a CUDA
   13.2 build and aborts with `Detected that PyTorch and TorchAudio were compiled
   with different CUDA major versions`. Pin the cu126 wheel:
   ```bash
   tools/train/.venv/bin/pip install --force-reinstall --no-deps \
       "torchaudio==2.11.0" --index-url https://download.pytorch.org/whl/cu126
   ```
2. **`kernels` breaks the transformers import.** With transformers 5.6 and
   `kernels` 0.16.2 the import dies with
   `Either a revision or a version must be specified`. Remove it:
   ```bash
   tools/train/.venv/bin/pip uninstall -y kernels kernels-data
   ```
3. **transformers must be 5.6.0.** Newer 5.x releases drop `BloomPreTrainedModel`,
   which peft 0.21.2 still imports:
   ```bash
   tools/train/.venv/bin/pip install "transformers==5.6.0"
   ```

Also note: the `simpletuner-train` console script is broken in 4.11.0
(`cannot import name 'main'`). Use `python -m simpletuner.train` instead.

## Config

The working configuration is `tools/train/config/config.json` (base) and
`tools/train/config/multidatabackend.json` (dataset). The settings that make it
fit in ~6.3 GB:

```json
"base_model_precision": "int8-sdnq",
"text_encoder_1_precision": "int8-sdnq",
"offload_during_startup": true,
"gradient_checkpointing": true,
"gradient_checkpointing_offload_attention": true,
"quantize_via": "cpu",
"sdnq_use_quantized_matmul": true,
"train_batch_size": 1,
"num_train_epochs": 0
```

Without the text-encoder quantisation and the two offloads, model loading OOMs at
5.88 GB. With them: 6.28 GB resident, ~1.6 GB left for the desktop.

## Run

```bash
R=/run/media/talzanar/games/Projects/IoA/asset-pipeline
CONFIG_PATH=$R/tools/train/config CONFIG_BACKEND=json \
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  tools/train/.venv/bin/python -m simpletuner.train
```

Measured on 2026-11-09 (do not re-derive): the first 50 steps cost 3.17 s/step while
caches were cold; steady state is **1.05 s/step**. A 1,500-step run therefore takes
**~28 minutes**, not hours. VRAM peaks at ~7.4 GB, leaving ~0.5–0.8 GB for the
desktop — 1080p video survives, 4K does not.

Outcome of the first run (`output/train/materials_v1`): the LoRA learned the
intended lesson — the base model renders *rooms* for a material prompt, the adapted
model renders flat material tiles — but it **over-trains past ~750 steps** (1000+
collapse toward flat grey/blank). The usable adapter from that run is
`checkpoint-750`. Next iteration: 600–750 steps, LR 5e-5, shorter captions, more
images, and circular-padding at inference for exact tiling.

## Dataset

Built by `tools/train/build_dataset.py` from the merged material library:
112 train tiles (5 factions + shared + patterns, 2 crops each) and 10 eval tiles
from two factions held out entirely (`void_corsairs`, `wreckstorm_clans`).
Captions come from each item's `meta.json`, never from a captioning model.

## Do not

- Run a render or img23d job while training: one GPU job at a time.
- Watch 4K video during a run (1080p is fine, ~1.6 GB headroom).
- Change rank, learning rate and resolution in the same run.

## From adapter to assets (production path)

The pilot run was scored by reading SimpleTuner's single validation prompt. That is
diagnostic, not an adoption gate. The production path is two scripts:

- `generate.py` — the only sampler. Loads `FLUX.2-klein-base-4B` + adapter, optional
  periodic-latent blending (`--seamless blend`, default), then the **production**
  material treatment in the same order as `derive_maps.py`: flatten baked lighting,
  repair the seam only if it is broken. Writes `meta.jsonl` with prompt, seed,
  adapter hash, base model and measured seam. Sequential CPU offload is the default
  because the desktop holds 1–3 GB of the card; `--offload model` is faster when the
  card is free.
- `eval_grid.py` — the adoption gate. Fixed prompt set in
  `prompts/eval_materials.json`: 12 in-domain prompts (half held-out factions) and
  8 out-of-domain regression prompts. Gates on tiling, material flatness, palette
  containment and regression vs the base model, and records the provenance hashes.

```bash
# asset generation
tools/train/.venv/bin/python tools/train/generate.py \
    --adapter output/train/materials_v2/checkpoint-750 \
    --prompts tools/train/prompts/eval_materials.json --seeds 11,22 \
    --out output/gen/batch

# adoption gate (spends GPU; do not run beside a render)
tools/train/.venv/bin/python tools/train/eval_grid.py \
    --adapter output/train/materials_v2/checkpoint-750 \
    --out output/eval/materials_v2_750
# re-score without the GPU
tools/train/.venv/bin/python tools/train/eval_grid.py --score-only output/eval/materials_v2_750 \
    --out output/eval/materials_v2_750
```

### Tiling metric (corrected 2026-11-09)

The old gate used absolute wrap-edge difference ≤ 0.02. That number is not a seam
measurement: a correct periodic texture has a wrap edge with the same difference as
any interior adjacent-pixel edge, so high-frequency materials fail while tiling
perfectly. The gate now measures `wrap-edge difference / interior-edge difference`
and accepts a tile when the ratio is ≤ 1.5 **or** the absolute border step is
≤ 0.02. The disjunction matters: the ratio explodes on near-flat materials because
its denominator is near zero, which is a metric degeneracy, not a bad tile.
A textured tile must look like its own interior; a flat tile must be imperceptibly
stepped. `derive_maps.py` and `ingest_generated.py`
use the same ratio as the repair trigger (repair only when ratio > 1.5), so a
correct high-frequency tile is never blended into a worse one.

### Palette metric

`dE` is the CIE76 distance between the generated tile's mean Lab colour and the
nearest reference tile of the same material. The tolerance is the library's own p95
crop-to-crop variation (measured; ~6.7 dE), floored at 10. A tile that drifts off the
faction palette fails; a tile that varies like the reference passes.

### Regression metric

The adapter must not collapse general capability. For each out-of-domain prompt the
base model and the adapter are sampled with the same seed, and a scene-structure
score (low-frequency contrast + edge energy) is compared. The adapter passes when it
retains ≥ 50 % of the base structure on ≥ 75 % of prompts. Visual review of
`regression_sheet.png` still decides.

## Adoption record

`configs/train/adapters.json` is the registry. An adapter is usable only when its
entry has `"adopted": true`, a completed `eval.json`, and the same adapter hash as
the file on disk. Adapters are never referenced by checkpoint number in pipeline
code — always by registry id.

## Certified runs

| id | dataset | steps / res / LR | gate | status |
|---|---|---|---|---|
| `materials_v1_750` | 112 tiles incl. 28 trim patterns | 750 / 512 / 1e-4 | tiling 0.833, material 1.0, style 1.0, regression 1.0 | experimental — pattern motifs leak onto surfaces |
| `materials_v2_800` | 168 tiles, material only | 800 / 384 / 5e-5 | tiling 0.958 (mean ratio 0.996), material 1.0, style 1.0, regression 1.0 | **adopted** — generic surfaces |
| `materials_v3_800` | 168 tiles, material only | 800 / 512 / 5e-5 | tiling 0.917 (mean ratio 1.369), material 1.0, style 1.0, regression 1.0 | **adopted** — panelled armour/trim |

The v1→v2 quality change came from dataset hygiene, not hyperparameters. See
`docs/GENERATION_TRAINING_RESEARCH.md` §10b.

## Workstation reality (measured)

Training needs ~6.2 GB resident; the box OOMs at 448/512 px when a browser plus a
1 GB Wine game hold the card. 384 px runs at 1.42 s/step with ~0.1–0.5 GB spare.
Close GPU consumers before a run (`python3 tools/gpu_policy.py status`), and sample
at 448 px afterwards — the 384 px adapter samples cleanly above its training size.

## In-pipeline proof (2026-11-09)

`tools/pbr/ingest_generated.py` is the bridge from adapter output to the material
library: it flattens lighting, applies the ratio-based repair and derives
normal/roughness/metallic exactly as `derive_maps.py` does, then writes the item
layout the Blender library builder expects.

```bash
# 1. generate the four Iron Directorate slots with the adopted adapter
tools/train/.venv/bin/python tools/train/generate.py \
    --adapter output/train/materials_v2/checkpoint-800 \
    --prompts /tmp/iron_directorate_prompts.json --seeds 11 \
    --out output/gen/iron_directorate --size 448 --steps 16
# 2. ingest into a copy of the library (never mutate the shipped tree)
python3 tools/pbr/ingest_generated.py --gen output/gen/iron_directorate \
    --library assets/materials/grimdark_scifi --out output/gen/adapted_library \
    --items iron_directorate__armour_primary,iron_directorate__armour_secondary,iron_directorate__underlayer,iron_directorate__metal_trim
# 3. build a preview .blend and render it on the real unit mesh
tools/blender_run.sh --job render -- -b -P tools/pbr/build_blender_library.py -- \
    --library "$PWD/output/gen/adapted_library" --only iron_directorate
tools/blender_run.sh --job render -- -b -P tools/blender/preview_unit_materials.py -- \
    --glb output/img23d/line_infantry_mv/uv/lod0_uv.glb \
    --library "$PWD/output/gen/adapted_library/grimdark_scifi.blend" \
    --faction iron_directorate --out output/gen/unit_proof --samples 32
```

Result: `output/gen/unit_proof/{front,three_quarter}.png` — navy enamel with gold
pinstripe edging on the line-infantry proof mesh, all four slots box-projected from
adapter tiles. The crude zone heuristic leaves the boots grey; that is the known
preview limitation, not a texture defect.
