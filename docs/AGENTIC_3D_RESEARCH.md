# How ChatGPT / Claude actually drive Blender — and what our pipeline is missing

**Research report — 2026-11-23.** Sources are cited inline with the date the claim was checked.
Every claim about our own pipeline cites the file and the measurement.

Question answered: *how do the commercial assistants take an input and produce good-looking 3D
assets, and where is our pipeline short?*

---

## 0. The one-paragraph answer

Neither ChatGPT nor Claude is the artist. They get four capabilities — **read the scene, run code,
look at an image, search the API reference** — and the visible quality comes from a loop built on
top of them: a written contract before generation, API grounding, an execution-error repair loop, a
staged pass sequence where each pass needs a **vision model's** pass verdict against a reference, and
a fixed post-generation chain (remesh → unwrap → texture → segment → rig). Where that loop is
missing, results vary wildly — including in our pipeline, which has the scripts but not the loop.

---

## 1. The transport layer (what "interfacing with Blender" means)

| fact | evidence |
|---|---|
| Blender ships its own MCP server: Blender Lab `blender_mcp`, GPL-3.0-or-later, v1.0.0 released **27 Apr 2026** (v0.1.0 24 Mar 2026, v1.0.3 11 Sep 2026), Blender 5.1+, add-on opens a local TCP socket and a stdio MCP process relays to it | Blender Lab repo `projects.blender.org/lab/blender_mcp`; release table reproduced in [StraySpark, updated 3 Nov 2026](https://www.strayspark.studio/blog/official-blender-mcp-server-comparison-2026) |
| It exposes **26 tools**: code execution, blend-file summaries (datablocks, missing files, linked libraries), object/collection summaries, area or window screenshots, viewport navigation, thumbnail and viewport renders, and **two search tools over bundled copies of the Blender Python API reference and the user manual**. **Six tools have `_for_cli` variants that open a `.blend` in a background Blender process** | same source, tool listing as of 25 Sep 2026 |
| It is the **Blender connector in Claude**: Anthropic announced nine creative-tool connectors on **28 Apr 2026**, Blender among them — "The Blender developers have created an MCP connector, which is now officially available for Claude." Anthropic made a donation to the Blender project; Blender took it as a one-off rather than through the Dev Fund | [anthropic.com/news/claude-for-creative-work](https://www.anthropic.com/news/claude-for-creative-work), published 28 Apr 2026, updated 1 May 2026 |
| Blender has **not** taken a generative-AI position: chairman Francesco Siddi — "no generative AI functionality is currently available or planned to be integrated in Blender" | quoted in StraySpark, 25 Sep 2026 |
| Safety model is deliberately thin: "will execute LLM generated code in Blender without any guards"; the add-on's `weak_sandbox.py` docstring calls itself "more of a slap on the wrist"; the Lab recommends a VM | Blender Lab page, quoted in StraySpark |
| The community server (Ahujasid, formerly `blender-mcp`, renamed **`MCP for Blender`** on 16 Sep 2026 to stop being mistaken for the official one) exposes **36 tools**: scene/object info, screenshot, `execute_blender_code`, `describe_node_type`, live `bpy_api_lookup`, and generation/asset integrations (Poly Haven, Sketchfab, Poly Pizza, Hyper3D Rodin, Hunyuan3D, Tripo) plus `export_scene` | same source; `ahujasid/mcp-for-blender`, 35,462 stars at 2026-11-23 (GitHub API) |
| **ChatGPT has no first-party Blender connector.** It reaches a local Blender through MCP over a remote URL / secure tunnel, or through the community server | [fenbs.ai](https://fenbs.ai/blog/chatgpt-blender-connector); [kapunakap/chatgpt-blender-bridge](https://github.com/kapunakap/chatgpt-blender-bridge) (verified live 2026-09-06) |

**The four capabilities are the whole interface**: read state, run code, see an image, search the
docs. Everything in §2 is a loop built from those four.

---

## 2. Where the "good looking" results actually come from

Two distinct production recipes. Both are documented, and neither is "the model is a good artist".

### 2.1 Code-as-geometry, with agents and a vision verifier (LL3M)

LL3M (arXiv 2508.08228) generates 3D assets by writing Blender Python, with six agents: planner,
retrieval, coding, critic, verification, user-proxy. Its measured findings are the useful part:

| finding | number | source |
|---|---|---|
| A retrieval base built from **1,729 official Blender 4.4 documentation pages** ("BlenderRAG") | — | §4.1 |
| With BlenderRAG: **5× increase in complex bpy operations** (the operations that make a mesh good rather than a primitive pile) | 5× | §4.4, Table 1 |
| With BlenderRAG: **26 % lower code execution error rate** across the whole generation process | −26 % | §4.4 |
| Without retrieval the coder "often defaults to using primitive shapes and simpler constructs, which compromises on mesh quality" | qualitative | §4.4, Fig. 15 |
| Agent ablation: planner adds parts, retrieval makes those parts geometrically rich, and **the visual critic is what brings them together** | qualitative | Fig. 16 |
| Shared code context matters: without it "the coding agent will rewrite the code to produce a different 3D asset" | qualitative | §3.2, Fig. 17 |
| The critic agent renders the scene from **five angles** and submits them to a vision-language model to find mismatches and disconnected components; a separate **verification agent re-renders and checks whether the critic's points were actually addressed** | — | Appendix A.2.4, A.2.5 |

The strongest single sentence in the paper for our purposes: *"A straightforward use of an LLM to
write Blender scripts leads to code that produces low-quality outputs or fails to execute."* That is
the baseline. Everything above it is scaffolding.

### 2.2 The same shape, productised (img2threejs)

`img2threejs` (21.8k stars, Apache-2.0) is the clearest public implementation of the loop, and its
`docs/ARCHITECTURE.md` states the design rules plainly:

- **Locked passes**: `blockout → structural-pass → form-refinement → material-pass → surface-pass →
  lighting-pass → interaction-pass → optimization-pass`. "A pass unlocks only after the previous one
  is reviewed and accepted."
- **A pass is `continue` only with a real render, a comparison sheet, an agent-vision score at or
  above threshold, and every identity-defining feature at or above its own threshold.**
- **Geometric gates run before the browser does** — "a bald patch or a self-intersection is found on
  points, so a pass is never spent rendering geometry that was already wrong."
- **Strict-quality gate blocks shallow specs before codegen** — "you never spend tokens rendering a
  model that was underspecified from the start."
- **Routing can refuse**: below a confidence of 0.82 it returns `request-input` rather than guessing.
- **Scripts enforce, the model judges**: "The Python scripts handle validation, gating, spec
  authoring, PBR extraction, comparison-sheet packaging, and pipeline state. They never score
  visuals. The model's tokens go to one thing: looking at a single side-by-side sheet and deciding
  pass or fail."
- **One image per review**: each pass is judged from exactly one packaged comparison sheet
  (reference beside render).
- A **detail inventory** of identity-defining small details (gloss, bevels, rivets, engraved
  linework, stains) must be complete before generation starts; every detail must map to a real
  component or material entry.
- **Chirality gate**: every `-l`/`-r` pair must be a sagittal mirror, not a rotated copy — a pair
  built by negating two axes comes out as the same hand twice.

### 2.3 Model-based generation plus a fixed post chain (Meshy, Tripo)

The commercial generators do not hand you a finished asset. They hand you a mesh and then run a
fixed, ordered chain:

- **Meshy**: after generation, "use them in this order: **Remesh → Unwrap UV → AI Texturing →
  Rigging → Animate**. After the last step, export." Remesh exists "if the face count is too high or
  the topology is messy"; `Make Printable` for watertightness; `Model Edit` to fix one part.
  ([docs.meshy.ai, choose a post-processing step](https://docs.meshy.ai/en/webapp/guides/choosing/post-processing), checked 2026-11-23)
- **Tripo**: **Segmentation** splits a finished mesh into "clean, meaningful parts — head, body,
  limbs, accessories", with a precision dial (Simple 3–6 parts / Balanced 6–15 / Detailed 15+), and
  the documented use case is *"Animation preparation — separate rigid parts before rigging for
  cleaner deformation"* and *"game asset modularization — break characters into modular equipment
  pieces"*. "Segment before texturing."
  ([tripo3d.ai/product-doc/module-post-processing/segmentation](https://www.tripo3d.ai/product-doc/module-post-processing/segmentation), Oct 2026)
- Both now wrap the chain in an agent: **Meshy 3D Agent** ("Batch visual concepts… The agent can keep
  the style consistent across batches, which matters for asset sets that belong to the same world";
  it asks approval before spending credits) and **Tripo Agentic Canvas** ("an AI agent that plans and
  runs 3D workflows — from generation and refinement to export… Node = one step… Workflow = the
  connected chain").

The pattern is the same as §2.1: **a fixed, ordered, gated chain**, with the model doing routing and
judgement rather than free-form creation.

### 2.4 The open-weight ceiling that matters to us

| model | what it adds | size / VRAM | licence |
|---|---|---|---|
| `tencent/Hunyuan3D-2.1` | production PBR texture synthesis; "first production-ready 3D asset generation model" | 3.3B shape / 2B paint; **10 GB shape, 21 GB texture, 29 GB both** | Tencent Hunyuan Community |
| `tencent/Hunyuan3D-Omni` | **controllable generation**: accepts *point clouds, voxels, bounding boxes and skeletal pose priors* as conditioning "enabling precise control over geometry, topology, and pose" | built on 2.1 | Tencent Hunyuan Community |
| `tencent/Hunyuan3D-Part` | **P3-SAM** native 3D part segmentation + **X-Part** structure-coherent part completion | — | Tencent Hunyuan Community |
| `microsoft/TRELLIS.2-4B` | native compact structured latents, up to **1536³** PBR assets, 16× spatial compression | 4B; **24 GB VRAM** cited | MIT-family (check card) |

Hunyuan3D **2.1 is the last release with open weights** — the Hugging Face `tencent` org at
2026-11-23 lists `Hunyuan3D-1, -2, -2.1, -2mini, -2mv, -Omni, -Part` and no 2.5/3.0/3.1
(verified via `huggingface.co/api/models?author=tencent&search=Hunyuan3D`). 2.5/3.0/3.1 are hosted.

---

## 3. The five transferable mechanisms

These are the mechanisms, not the products. Each one is independently justified by the sources above.

| # | mechanism | why it changes the result | evidence |
|---|---|---|---|
| M1 | **Contract before generation** — a spec deep enough for the object's complexity, plus a detail inventory, blocks codegen | removes the "underspecified from the start" class of failure entirely; a bad spec cannot be rescued by a good render | img2threejs strict-quality + detail inventory; LL3M planner ablation |
| M2 | **API grounding** — retrieve from the *actual* API docs of the installed version | 5× more complex operations and −26 % error rate at once: better geometry *and* fewer failures | LL3M §4.4; Blender Lab's bundled API/manual search tools; `bpy_api_lookup` in the community server |
| M3 | **Execution-error repair loop** with the traceback and docs retrieval, before any visual review | all execution errors in LL3M were corrected by this loop; without it a visual pass is wasted on a broken scene | LL3M §3.1, A.2.2 |
| M4 | **Per-pass VLM acceptance against the reference**, plus a verifier agent that checks the critic's points were implemented | the only mechanism that sees "this is the wrong shape" — numeric metrics score a deleted face the same as a finished one | LL3M critic/verifier agents; img2threejs "screenshot feedback" and "silhouette IoU reads roughly 11 % of figure cells and scored a deleted face identically to a finished one" |
| M5 | **Fixed ordered post chain + part structure** (remesh → unwrap → PBR → segment → rig), with segmentation *before* rigging | turns a fused blob into editable, riggable, per-material parts; this is what the commercial tools sell | Meshy post-processing order; Tripo segmentation ("separate rigid parts before rigging") |

BlenderGym (arXiv 2504.01786) adds the meta-finding that makes M4 actionable rather than
aspirational: **the verifier is the bottleneck, and it can itself be improved by inference scaling**
— "inference compute is not uniformly effective and can be optimized by strategically distributing
it between generation and verification." In other words: spend the extra samples on the judge, not
only on the generator.

---

## 4. Our pipeline, measured

What exists (all paths verified in-tree at 2026-11-23):

| stage | tool | what it actually does |
|---|---|---|
| concept / orthos | `gemini-img` | image generation, 4-up sheets, edits of the approved front |
| shape | `tools/img23d/img23d.py` | `Hunyuan3D-2mini` (default) / `Hunyuan3D-2mv` (multiview) / `TripoSR`; single seed, single sample |
| shape (alternate) | `tools/img23d/run21_offload.py` | Hunyuan3D **2.1** shape on 8 GB via manual CPU offload — **not wired into `img23d.py`** |
| shape (alternate) | `tools/img23d/trellis_run.py`, `refine_run.py` | TRELLIS.2 4B via ComfyUI nodes; separate venv (`~/ComfyUI-trellis`), own normalisation, own OOM ladder |
| detail recovery | `tools/img23d/detail_loop.py`, `hero_sculpt.py`, `sculpt_detail.py`, `audit_regions.py`, `verify.py` | deterministic scan → carve → guard loop on **heightfield detail** against the artwork; per-cell capture heatmap |
| retopo / UV / rig | `tools/blender/uv_prepare.py`, `rig_unit_proof.py`, `decimate_unit.py` | 22-bone humanoid template rig on a **fused** mesh |
| materials | `tools/pbr/*` | albedo from Gemini, normal/roughness/metallic derived locally, box-projected library |
| gates | `tools/glb_contract.py`, `tools/spec/validate_assets.py`, `tools/style/check_*`, `tools/critic.py`, `tools/visual_check.py`, `tools/rig_fidelity.py` | structural + numeric thresholds |
| orchestration | `tools/build_unit.sh`, `pipeline_cli.py` | fixed 8-step shell sequence |

Measured properties that matter for this comparison:

- `tools/glb_contract.py` is a **post-hoc** gate: it rejects a bad GLB, it cannot prevent one.
  `LIMITS["unit"]` = max 25 000 tris / min 700 / skinned / UV / texture / 9 clips.
- `tools/critic.py` thresholds are hand-set numbers (`alpha_coverage_min 0.06`,
  `edge_density_min 0.08`, `unique_colors_min 50`, …). Nothing in it reads the *reference*.
- `tools/visual_check.py` is the one reference-anchored metric (per-view silhouette IoU), and its
  documented use is **copy detection** (`--copy-iou 0.90`), not quality scoring.
- **No tool in the tree sends a render to a vision model.** `grep -l gemini tools/*.py tools/*/*.py`
  returns only the PBR albedo generators.
- **Three generation engines, three interfaces, three normalisation conventions, no shared
  provenance record.** `img23d.py` normalises nothing; `refine_run.py` normalises to a unit AABB and
  keeps the inverse transform; `trellis_run.py` requires a front=+Z unit-normalised input (per
  `detail_loop.py`'s header). A unit's mesh depends on which script was used.
- Generation is **single-sample, single-seed** — there is no candidate set and no selection step.
- The rig is a **22-bone template on a fused mesh**; there is no semantic part structure, so
  per-part materials and per-part deformation are unavailable.

---

## 5. Where we are short, ranked by expected gain per unit of work

| # | gap | what it costs us now | mechanism it maps to |
|---|---|---|---|
| **G1** | **No vision judgement in the loop.** Gates are numbers; the only "does it look right" step is a human reading a PNG. | This is the direct cause of "results vary wildly": a render that is structurally legal, correctly coloured and wrong in shape passes every gate. img2threejs measured that silhouette IoU alone "scored a deleted face identically to a finished one". | M4 |
| **G2** | **No single generator contract.** Three engines, three conventions, no manifest. | Same prompt, same concept art, different script → different scale, orientation and detail density. Nothing records which engine/seed/resolution produced a shipped mesh. | M1 (partly), M5 |
| **G3** | **No candidate set.** One seed, one mesh, accept or restart. | We cannot pick the best of five; we can only re-roll and hope. BlenderGym: distribute inference compute between generation *and* verification. | M4 |
| **G4** | **No pre-generation spec for units.** `ASSET_SPEC.md` is a post-hoc contract; there is no per-unit detail inventory, part list, socket list or texel target. | Underspecified units are discovered at gate time, after the expensive stages have run. | M1 |
| **G5** | **No API grounding for the agent writing bpy.** We rely on the model's memory of Blender 5.1 (layered Actions, ChannelBag fcurves) and pay for it in debugging rounds. | LL3M: 5× complex operations and −26 % error rate from grounding alone. This is the cheapest quality lever we have and it is a one-off build. | M2 |
| **G6** | **Fused mesh, template rig, no parts.** | No per-part materials, no rigid-part deformation, no equipment modularity. Tripo/Meshy both treat segmentation as the step *before* rigging. | M5 |
| **G7** | **No reference-anchored appearance metric for units.** | We can measure "is it a copy" but not "did the concept's material language survive". | M4 |
| **G8** | **Model-side PBR is skipped** (2.1 Paint needs 21 GB; our card is 8 GB) and substituted with the library. | Acceptable by policy — but it means the texture stage must be *judged*, not generated, so G1 matters more for us than for Meshy. | M5 |

### 5.1 One correction to our own documentation

`docs/BLENDER_MCP.md` §5 states the add-on "refuses to start under `blender -b`" and that the host
must be GUI-mode under `xvfb-run`. That is still true of the **community** add-on (verified
2026-11-17), but the **Blender Lab** server ships six `_for_cli` tools that open a `.blend` in a
background Blender process (StraySpark tool listing, 25 Sep 2026). That is a capability we currently
believe we do not have: **headless batch auditing of a `.blend` through MCP**. Worth verifying
before relying on it — the source is secondary.

---

## 6. What to build, in order

Each item names its check, per the decisions rule (no check, no divergence).

| step | build | check that proves it |
|---|---|---|
| **T1** | `tools/review/sheet.py` + `tools/review/vlm_critic.py`: package one reference-vs-render side-by-side sheet, send it to a vision model with an explicit rubric (silhouette, part presence, material language, defects), write `review.json` with per-feature scores and one decision from `continue / refine-code / request-input / stop`. Wire as a step in `build_unit.sh`. | Run on a known-good unit and a known-bad one: the good one scores above threshold, the bad one below, and the recorded reason names the actual defect. Reject the tool if it cannot separate those two. |
| **T2** | `tools/gen/contract.py`: one interface over `img23d`, `run21_offload`, `trellis_run` — normalise scale/orientation, record engine + seed + resolution + input hashes into `gen_manifest.json`, refuse to emit a mesh without a manifest. | Build the same concept through two engines and diff the manifest + the normalised bounds; both must be front=+Z, unit-normalised, and traceable. |
| **T3** | Candidate sampling with measured selection: 5 seeds, score each with T1, keep the best, record all five scores. Tail-sample (keep p < 0.10) per the decisions rule rather than averaging. | The kept candidate's score must exceed the mean of the rejected four by a recorded margin on ≥ 10 units; if it does not, the selector is not working and T3 is reverted. |
| **T4** | `tools/spec/unit_spec.py --strict`: per-unit detail inventory, part list, socket list, texel target, material slots; blocks the build if the spec is shallower than the unit's complexity. | A deliberately shallow spec must exit non-zero; a complete spec must pass. Then measure gate-failure rate before/after on the same 5 units. |
| **T5** | Local Blender API index + a `bpy_api_lookup`-shaped helper (the official Lab server already bundles the API reference and manual — adopt it for investigation, and index the docs locally for the batch scripts). | Count execution-error retries per unit build before/after; LL3M's benchmark is −26 %. Record the number. |
| **T6** | Part segmentation before rigging (P3-SAM from `Hunyuan3D-Part` is open-weight; Tripo/Meshy segmentation as the hosted fallback). Emit parts as separate meshes with semantic names. | The rig gate must report per-part deformation instead of whole-mesh tear, and `glb_contract` must see >1 named part on a unit that has gear. |
| **T7** | `Hunyuan3D-Omni` conditioning with **skeleton and bounding-box priors** for roster units, so proportions and pose are constrained rather than sampled. | Measure proportion variance across the roster before/after (height/limb ratios from the GLB); a roster that is *supposed* to be uniform must tighten. |

Sequencing note: **T1 first**. Every other item is either wasted (T3 without a judge selects
nothing) or unverifiable (T6 without a judge cannot tell "clean parts" from "shattered mesh").

---

## 7. What we already get right — do not change these

| our choice | why it stays |
|---|---|
| MCP for investigation, scripts for the pipeline | every MCP action is a round trip; our pass is 145 units. The Blender Lab page itself pitches its server at "analysis, debugging and scripting", and Blender's own position is that no generative AI is planned inside Blender. |
| `.blend` + JSON as source of truth | generated meshes are opaque; code and configs are diffable. img2threejs reaches the same conclusion from the other direction ("Text output, not binaries… small, reviewable, version-controllable"). |
| Nothing generated ships unmodified | confirmed by every commercial chain: they all run a fixed post-processing sequence over the generated mesh. |
| Deterministic gates that block | img2threejs: "Scripts enforce, the model judges." Our gates are the enforce half and they are correct — the missing half is the judge. |
| 1:1 DoW2 import for the shipping roster | this is the one place we are ahead of the generative pipelines: shipped geometry, materials, rig and clips beat anything a 4B image-to-3D model produces on this hardware. |

---

## 8. Dead ends — do not chase

- **"Give the model a prompt and let it model."** LL3M's own baseline: "A straightforward use of an
  LLM to write Blender scripts leads to code that produces low-quality outputs or fails to execute."
- **A single render scored by hand-written numeric thresholds.** Already tried, already shipped a
  0 %-tear frozen mesh and a mis-scaled Carnifex (see `docs/BLENDER_MCP.md` §2). Numbers are the
  pre-filter, not the verdict.
- **Training our own 3D shape model.** 3.3B DiTs at datacenter scale; `GENERATION_TRAINING_RESEARCH.md`
  §1 already settled this. The fix is input quality, selection and retopo, not a local fine-tune.
- **Waiting for Hunyuan3D 3.x open weights.** 2.1 is the last open release (HF org listing,
  2026-11-23). Plan around 2.1 + Omni + Part + TRELLIS.2.

---

## 8b. Addendum 2026-11-23 — the transport for the T1 judge, measured

T1 needs a vision model to look at a render. The route to Gemini from this machine is not the one the
docs assumed, and the difference cost most of a session, so it is recorded here.

| transport | state | evidence |
|---|---|---|
| `gemini_webapi` via `gemini-img` | **fails on any turn carrying an image** | `Unknown API error code: 1100` on lib 2.0.0 and 2.1.1, every Gemini 3 model; `list_models()` returns one model = guest mode (upstream issue #365); text-only turns answer correctly |
| headless browser + injected cookies | **fails** | Google serves `google.com/sorry/index`; the app keys the session on localStorage and a fingerprint, not cookies alone |
| **real Chrome profile seeded + CDP, headless** | **works** | `tools/review/gemini_ask.py`: `attached: true`, answer captured in 41–85 s, no window, no interstitial |

Cookies were never the fault: the pair returned 200 from `gemini.google.com/app` and the upload
endpoint returned 200 in 0.8 s throughout. The lesson for this repo is the same one M1–M5 teach about
assets: **the failure was in the transport's model of the session, not in the credential** — which is
why re-supplying the credential did nothing.

This does not change the research findings in §3. It supplies the one component T1 was missing.

## 9. Sources
Primary
- Anthropic, *Claude for Creative Work*, 28 Apr 2026 (updated 1 May 2026) — https://www.anthropic.com/news/claude-for-creative-work
- Blender Lab, `blender_mcp` — https://projects.blender.org/lab/blender_mcp and https://www.blender.org/lab/mcp-server/ (both behind a Cloudflare challenge; tool list and release history read via the StraySpark mirror below)
- LL3M: *Large Language 3D Modelers*, arXiv 2508.08228 — https://arxiv.org/html/2508.08228
- BlenderGym, arXiv 2504.01786 — https://arxiv.org/abs/2504.01786
- img2threejs, `docs/ARCHITECTURE.md` — https://github.com/img2threejs/img2threejs
- Meshy docs, *Choose a post-processing step* — https://docs.meshy.ai/en/webapp/guides/choosing/post-processing
- Meshy 3D Agent — https://docs.meshy.ai/en/webapp/3d-agent
- Tripo, *Segmentation* (Oct 2026) — https://www.tripo3d.ai/product-doc/module-post-processing/segmentation
- Tripo, *Agentic Canvas Guide* (Oct 2026) — https://www.tripo3d.ai/product-doc/agentic-canvas
- Hunyuan3D-2.1 README (VRAM figures) — https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- Hunyuan3D-Omni model card — https://huggingface.co/tencent/Hunyuan3D-Omni
- Hunyuan3D-Part (P3-SAM, X-Part) — https://github.com/Tencent-Hunyuan/Hunyuan3D-Part
- TRELLIS.2 — https://microsoft.github.io/TRELLIS.2/
- Hugging Face org listing check — `https://huggingface.co/api/models?author=tencent&search=Hunyuan3D` (2026-11-23)

Secondary (used where the primary is Cloudflare-gated, and labelled as such)
- StraySpark, *Is There an Official Blender MCP?* (updated 3 Nov 2026) — https://www.strayspark.studio/blog/official-blender-mcp-server-comparison-2026
- fenbs.ai, *ChatGPT Blender connector* — https://fenbs.ai/blog/chatgpt-blender-connector
- kapunakap/chatgpt-blender-bridge — https://github.com/kapunakap/chatgpt-blender-bridge
- GitHub API star counts — `https://api.github.com/search/repositories?q=blender_mcp+in:name` (2026-11-23)
