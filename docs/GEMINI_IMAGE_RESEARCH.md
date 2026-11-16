# Gemini image generation — capacity, limits and a pipeline playbook

**Status:** 2026-11-09. Subscription active to **2027-07-07**. Purpose: use the one
high-VRAM image capability we have (hosted Gemini) to remove the local GPU
bottleneck, without letting generation become the new bottleneck.

**Access reality (corrected 2026-11-09):** we have a **Gemini Pro consumer
subscription (browser app)** — **no AI Studio, no API key**. Every API parameter
below (`image_size`, `aspect_ratio`, reference-image counts, `response_format`)
is documented behaviour we may *ask for in the prompt or set in the web UI*, not
something we can pass programmatically. Batch loops, seeds and REST calls are not
available. Quotas are consumer-plan windows, not API rate limits.

**Sources:** official API docs (`ai.google.dev/gemini-api/docs/image-generation`,
retrieved 2026-11-09: 1K/2K/4K sizes, up to 14 reference images) — used as
reference for what the model can do, not as our interface; the operator skill
`~/.pi/agent/skills/gemini-image/SKILL.md`; local observed behaviour. Local
observations A; vendor docs B; community reports C.

---

## 1. What the subscription actually buys

It buys **resolution and reference conditioning we cannot run locally**: 2K/4K
outputs, multi-image reference edits, and Pro-model text rendering. It does not
buy compute for training, rendering or baking — those stay on the 8 GB card.

### What our access can and cannot do

| | Consumer Gemini Pro web app |
|---|---|
| Interface | browser chat, or `~/.pi/agent/bin/gemini-img` driving the same web session |
| API key / AI Studio | **none** |
| Seeds / determinism | none |
| Batch / automation | one prompt at a time through the wrapper; no parallel jobs |
| Resolution | chosen in the UI when offered; state it in the prompt as backup |
| Aspect ratio | UI control if present; state it in the prompt as backup |
| Reference images | attach several in-chat; the API's 14 is not the practical limit here — 3–5 is |
| Quota | consumer windows: ~8–12 standard gens per 5 h, Pro scarcer (14–25/day observed) |

| Capability | Local (8 GB) | Gemini |
|---|---|---|
| Image generation at 2K/4K | no (local models cap at 512–768 in practice) | yes |
| Multi-reference conditioning (up to 14 images) | limited | yes |
| Text/label rendering in sheets | no | yes (Pro) |
| Pixel/per-texel precision | yes (deterministic) | no (no seeds) |
| Tileability, alpha, normal maps | yes (derive/key locally) | no |
| Batch determinism | yes | no |

Rule: **generate at high resolution, decide and cut locally.** Never ask the chat
to do pixel surgery, tiling, or alpha.

## 2. Practical quota model (observed, grade A)

- Consumer Pro has **no fixed daily image count**; a compute allowance refreshes
  every 5 hours toward a weekly cap. Plan **~30–40 standard generations/day** and
  treat a single window as **8–12**.
- **Nano Banana Pro** is scarcer: observed **14–25/day** (2/day under load).
  Reserve Pro passes for hero art, label-heavy sheets and final style sheets.
- **Every edit is a generation.** An 8-step edit chain costs 8. Budget chains.
- Reset is the **5-hour window**, not midnight. Schedule 3–4 batches/day.

Consequence for a 17-unit roster with 3 assets each: ~51 generations ≈ two days
of windows, not one afternoon. Plan the queue accordingly.

## 3. Where to spend generations (ranked by value)

1. **Orthographic turnarounds for units/creatures** — the only input img23d can
   use, and the part we cannot generate locally at 2K.
2. **Material sheets** (2×2 at 2K) for surface families we have not built, and
   for non-grimdark factions.
3. **Style sheets per faction** as *targets* for the pixel gate: palette chips,
   outline weight, cluster density, two example sprites.
4. **Concept exploration** for hero props and buildings before parametric build.
5. **Decals, icons, UI frames** — sheet-multiplier work.
6. **Damaged/destroyed variants** by edit chain from approved art.

Do **not** spend them on: resizing, tiling, alpha keying, normal/roughness
derivation, palette quantisation, or retrying a seed (there are none).

## 4. Techniques that measurably improve results

These are the "tricks" that matter for our pipeline, in order of effect.

1. **Generate at 4K, downsample locally to the target canvas.** A 4K image
   reduced to 256/96 px with area/nearest downsampling keeps structure that a
   native 256 generation loses. This is the single biggest quality lever for
   pixel targets.
2. **Ask for a pixel-art *target* only when the output is the target.** For 3D
   sources, ask for "flat studio light, pure white background, high contrast,
   clean silhouette" — not "pixel art".
3. **Palette injection.** List the exact hexes and say "use only these colours,
   no gradients, no anti-aliasing, hard pixel edges". Works best on the Pro
   model; verify with our palette gate rather than trusting it.
4. **Sheet multiplier.** One generation with a labelled N-up grid (4 tile
   variants, 6 icons, 4 damage states) is N assets per generation. Cut locally
   with the packer; this is the highest-leverage quota move.
5. **4-view turnaround recipe.** One 16:9 sheet: front, left, right, back, all on
   white, same scale, same light, feet on the same baseline. Then crop into four
   images for img23d. Do not regenerate each view separately — they will drift.
6. **Edit-chain anchoring.** Always attach the approved image and say "keep
   everything identical except …". Chain at most 2–3 edits before regenerating
   from the winner; identity drifts with every pass.
7. **Region layout beats adjectives.** "Left third: …, centre: …, right: …" is
   obeyed; "beautiful, detailed" is not.
8. **Text discipline.** ≤4 words per label, repeat exact strings in quotes at the
   end, digits not words, fix labels in an edit rather than regenerating.
9. **Aspect ratio in both places.** State it in the prompt and set the ratio in
   the UI/response_format; dense sheets drift otherwise.
10. **Never ask for transparency.** Prompt a pure-white background and key it
    locally; the model renders a checkerboard if you ask for alpha.

## 5. Failure modes and the checks that catch them

| Failure | Detection | Mitigation |
|---|---|---|
| No alpha | inspect PNG channels | white bg + local key |
| Baked lighting | compare two light directions | flat-light prompt for sources |
| Identity drift across edits | side-by-side review | re-anchor, regenerate from winner |
| Off-palette pixels | `check_palette_asset.py` drift | palette injection + local quantise |
| Anti-aliased "pixel art" | alpha/edge inspection, downscale test | 4K→nearest downsample, no AA prompt |
| Sheet cropped / wrong ratio | pixel dimensions vs requested | ratio in prompt + UI |
| Text typos | visual review at 1:1 | Pro model, short labels, edit fix |

## 6. Capacity plan for the pixel regeneration

Per unit: 1 turnaround sheet (Pro) + 1 material sheet (standard) + 1 concept
(standard) ≈ 3 generations. Per faction: 1 style sheet (Pro) ≈ 1. Per prop kit:
1 concept sheet + local parametric build ≈ 1.

| Batch | Generations | Window |
|---|---|---|
| 5 Iron Directorate units (turnarounds) | 5 Pro + 5 std | 2 windows |
| 7 faction material sheets | 7 std | 1 window |
| 7 faction style sheets | 7 Pro | 2 windows |
| 10 props/concepts | 10 std | 1–2 windows |
| **Total pilot** | **~34** | **~1 week of windows** |

## 7. Integration points

- Outputs land in `output/gemini/<batch>/`; crops are cut locally with
  `tools/packer` / PIL scripts.
- Turnarounds feed `tools/img23d` → retopo → profile build.
- Material sheets feed `tools/pbr/derive_maps.py` (never trust Gemini for normals).
- Style sheets become review targets; the palette gate is
  `tools/style/check_palette_asset.py`.
- Every generation is recorded in `docs/game-design/ASSET_LEDGER.md` with the
  prompt and model used.

## 8. What would change this

- An API key/AI Studio would allow batching, explicit `image_size`/ratio and a
  predictable RPM/RPD quota; today we ask in prose and drive the web app.
- If a local 24 GB card arrives, materials and orthos move local; Gemini stays for
  hero concepts and text-heavy sheets.
- If consumer Pro quotas tighten, the sheet multiplier and 4K-downsample tricks
  become mandatory rather than recommended.
