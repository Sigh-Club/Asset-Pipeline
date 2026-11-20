# Method portability — keeping the technique, replacing the art

> Audience: whoever decides what to build next, and anyone who has to explain to a lawyer or a
> publisher why this pipeline is not built on Relic's content.
>
> The pipeline was bootstrapped by reverse engineering Dawn of War II. That was the fastest way to
> get a *correct* answer to questions that are expensive to guess: how many bone influences a vertex
> gets, how a terrain shader blends eight ground layers, what a cover volume is for, what a map file
> must contain. Those answers are the asset. The meshes and textures are not.

## 1. The legal boundary, stated with a source

US Copyright Office Circular 31 ("Ideas, Methods, or Systems — What Is Not Protected by Copyright")
quotes 17 U.S.C. §102(b):

> "In no case does copyright protection for an original work of authorship extend to any idea,
> procedure, process, system, method of operation, concept, principle, or discovery, regardless of
> the form in which it is described, explained, illustrated, or embodied in such work."

And, in the same circular: "Copyright in such a case protects the particular literary or pictorial
expression chosen by the author. But it gives the copyright owner no exclusive rights in the idea
or system itself."

Source: <https://www.copyright.gov/circs/circ31.pdf> (retrieved 2026-11-18).

Applied to this project:

**We inherit (facts, methods, functional constraints):**
- the vertex format and its 4-influence limit, and the reason it exists;
- the terrain model: 8 layers, 2 RGBA weight masks, an activity grid, normalised weighted blend;
- the material *conventions*: a specular map whose RGB is specular colour and whose A is gloss, and
  the arithmetic that converts that to metalness and roughness;
- the cover/physics/collision decomposition: what a cover volume is, what a damage-state collision
  mesh is for, which Havok body properties a static building uses;
- the animation data model: per-frame local transforms, quaternion continuity, duration from frame
  count;
- the map container's *shape*: a chunk tree with placements referencing a blueprint table, plus a
  heightmap and a nav grid;
- every measurement: 2 m tiles, 0.35 m elevation steps, 8–32 m ground tiles, the tri counts that
  read correctly at gameplay camera distance.

**We replace (expression):**
- every mesh, every texture, every audio file;
- every proper noun: unit names, faction names, ability names, map names;
- any *distinctive* silhouette. A generic sci-fi trooper is not protected; a Space Marine's
  shoulder-pad proportions arguably are. When in doubt, re-proportion rather than copy.

**Grey area, handled by practice:** a *format* (SGA, WHM, RSH, HKX) is a functional interface, and we
read it rather than redistribute it. We do not ship DoW2 files to players; we ship glTF and PNG that
we generated. That is the cleanest position available and it is the one this pipeline takes.

## 2. What portability means concretely: the adapter boundary

A pipeline is portable when the source is an adapter, not an assumption. The contract in
`docs/ASSET_SPEC.md` is the boundary. Anything that satisfies it can feed the pipeline; anything that
does not is rejected by `tools/spec/validate_assets.py` with a reason.

```
  source adapter  ──►  canonical asset bundle  ──►  contract check  ──►  game
  (DoW2, #1)            (glTF + sidecars)           (asset_spec.json)
  (our own art, #2)
```

**What an adapter must supply** (this is the whole interface):

| artefact | requirement | why |
|---|---|---|
| meshes | glTF 2.0, POSITION/NORMAL/TEXCOORD_0 (+1), ≤4 influences/vertex, ≤256 bones | §2 and §9 of the spec |
| rig | named bones matching the clip library's bone names | clips address bones by name; a rename silently drops the track |
| clips | per-frame local transforms, true duration, contract clip names | §4 of the spec |
| materials | albedo + normal + packed specular/gloss (RGB spec, A gloss) | §5 of the spec |
| sidecars | cover volume + footprint per prop; collision per damage state; optional physics hull | §6 of the spec |
| maps | heightmap, ground layer set + masks, placements, nav grid | §7–8 of the spec |

**Adapter #1 — DoW2 (built):** `tools/dow2/*` (SGA read, WHM/RSH decode, scenario decode, action
library, env kit, ground kit), `tools/hkx/hkxread.py` (clip decode), `tools/blender/dow2_*` (import
into Blender), plus the community add-on's constants and validation as the reference for what the
engine demands. Its measured exceptions are recorded in the spec, not hidden.

**Adapter #2 — our own art (designed, not yet built):** a generator or a human modelling session
that outputs the same bundle. Because the contract is machine-checked, adapter #2 needs no knowledge
of DoW2 at all: it needs to pass `npm run guard:spec`. That is the test of whether the reverse
engineering was worth doing — a new artist can be onboarded with `docs/ASSET_SPEC.md` alone.

## 3. What is still DoW2-shaped, and what it costs to leave

Honest inventory of coupling. None of these block shipping; all of them are the work of leaving.

| coupling | where | cost to remove |
|---|---|---|
| clip library is baked from DoW2 `.hkx` | `tools/hkx/hkxread.py`, `action_library.json` | medium: the *data model* is generic (per-frame local transforms); a new source needs a converter into it, which is one exporter |
| bone names are DoW2's | clip binding by name | low: an alias map per source |
| ground textures are DoW2 tile DDS | `ground_kit.py` | low: the format is PNG at the end; any 4 m-tileable albedo works |
| props are DoW2 models | `build_env_kit.py` | medium: our own props need cover volumes and footprints authored, which is exactly the spec's requirement |
| `.coverbox` volumes come from the shipped corpus | `env_kit.json` | low for new props: author them; the shape is a box |
| the map forge's palette is the DoW2 prop set | `env_kit.json` | none structurally: it is a manifest, swap the entries |
| terrain layer *names* are DoW2 paths | `ground_kit.json` | none: they are strings |

The pattern: **geometry and texture are replaceable file-by-file; the contract and the tooling are
what carry over.** That is the point of the exercise.

## 4. How to add a source without touching the pipeline

1. Produce glTF + sidecars meeting `docs/ASSET_SPEC.md`.
2. Run `python3 tools/spec/validate_assets.py --assets <your-dir> --report /tmp/r.json`.
3. Fix what it reports. Do not weaken the spec; if a requirement is genuinely wrong for the new
   source, that is a spec change with a reason and an entry in `CHANGELOG.md`.
4. Add the assets to a manifest the game reads (`env_kit.json`-shaped), and the map forge and combat
   grid will use them without code changes.

## 5. The one rule that keeps this honest

If a claim about how the engine works is not in `docs/ASSET_SPEC.md` with a label
(**measured** / **engine** / **choice**) and a source, it is not knowledge yet — it is a memory. The
labels exist so that a future session can tell which constraints are physics (the 4-influence limit),
which are one engine's budget (54 bones), and which were our judgement (cover volumes required). A
portable method is one where that distinction survives the loss of the source.
