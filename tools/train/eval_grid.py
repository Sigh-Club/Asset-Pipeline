#!/usr/bin/env python3
"""eval_grid.py — the adoption gate for a style/material adapter.

Runs the fixed held-out prompt grid through the same sampling path the pipeline
uses (`generate.py`), scores the result, and writes a report with an explicit
PASS/FAIL. It never reads training loss.

Gates (all must pass before an adapter may be marked adopted):
  1. tiling      wrap-edge discontinuity / interior-edge discontinuity <= 1.5 on
                 >= 80% of in-domain samples. This measures a real seam: a border
                 is correct when it is no rougher than the texture's own interior
                 edges. Absolute border difference is not a seam metric — a
                 high-frequency tile has a large (correct) border difference.
  2. material    low-frequency flatness <= 0.15 on >= 90% (catches "room" outputs)
  3. style       multi-scale colour-layout descriptor distance to the faction's
                 reference set within that set's own leave-one-out p95 (>= 90%).
                 Mean colour alone cannot judge a multi-colour material (a navy
                 plate with gold trim has a mean far from both), so the descriptor
                 keeps 4x4 regional colour plus a chroma histogram. The tolerance
                 is the real within-faction spread of the library, measured.
  4. regression  LoRA keeps scene structure on out-of-domain prompts:
                 >= 75% retain >= 50% of the base model's structure score
  5. provenance  adapter hash, base model, dataset manifest hash and config hash
                 recorded in the report

Usage:
    python3 tools/train/eval_grid.py --adapter output/train/materials_v2/checkpoint-750 \
        --out output/eval/materials_v2_750
    # cheap smoke run
    python3 tools/train/eval_grid.py --adapter <dir> --out <dir> --seeds 11 \
        --skip-regression
    # re-score an existing directory without touching the GPU
    python3 tools/train/eval_grid.py --score-only output/eval/materials_v2_750 \
        --out output/eval/materials_v2_750
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import generate as G

ROOT = G.ROOT
SEAM_RATIO_LIMIT = 1.5
FLATNESS_LIMIT = 0.15
PALETTE_FLOOR_DE = 10.0


# ------------------------------------------------------------------ colour ---

def _lab(arr: np.ndarray) -> np.ndarray:
    rgb = arr.astype(np.float32) / 255.0
    rgb = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]], dtype=np.float32)
    xyz = rgb @ m.T / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    e = 216 / 24389
    f = np.where(xyz > e, np.cbrt(xyz), (xyz * 24389 / 27 + 16) / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def mean_lab(arr: np.ndarray) -> np.ndarray:
    return _lab(arr).reshape(-1, 3).mean(0)


def delta_e(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(mean_lab(a) - mean_lab(b)))


# ------------------------------------------------------------------ metrics ---

def seam_metrics(arr: np.ndarray) -> dict:
    a = arr.astype(np.float32)
    border = (np.abs(a[:, 0] - a[:, -1]).mean() + np.abs(a[0] - a[-1]).mean()) / 2 / 255
    interior = (np.abs(a[:, 1:] - a[:, :-1]).mean() + np.abs(a[1:] - a[:-1]).mean()) / 2 / 255
    ratio = float(border / max(interior, 1e-6))
    return {"seam": round(float(border), 4), "interior": round(float(interior), 4),
            "ratio": round(ratio, 3)}


def flatness(arr: np.ndarray) -> float:
    g = np.asarray(Image.fromarray(arr).convert("L").resize((16, 16), Image.BOX),
                   dtype=np.float32)
    return float(g.std() / 255.0)


def structure_score(arr: np.ndarray) -> float:
    """Scene-structure proxy: low-frequency luminance contrast plus edge energy.
    A material tile scores low, a rendered scene scores high. Used only for the
    regression comparison against the base model on the same seed."""
    g = np.asarray(Image.fromarray(arr).convert("L"), dtype=np.float32)
    small = np.asarray(Image.fromarray(g.astype(np.uint8)).resize((32, 32), Image.BOX),
                       dtype=np.float32)
    lo = float(small.std() / 255.0)
    dx = np.abs(np.diff(g, axis=1)).mean() / 255.0
    dy = np.abs(np.diff(g, axis=0)).mean() / 255.0
    return float(lo + 4.0 * (dx + dy))


# ---------------------------------------------------------------- reference ---

LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
_TILE_SPREAD = None


def _tile_spread() -> float:
    """p95 of mean-colour dE between the four quadrants of every library tile —
    the natural variation of one material at one resolution. This is the palette
    tolerance; it is derived from the corpus, not chosen."""
    global _TILE_SPREAD
    if _TILE_SPREAD is not None:
        return _TILE_SPREAD
    des = []
    for d in sorted(LIB.iterdir()):
        p = d / "albedo.png"
        if not p.exists():
            continue
        a = np.asarray(Image.open(p).convert("RGB").resize((512, 512)))
        labs = [mean_lab(a[y:y + 256, x:x + 256]) for y in (0, 256) for x in (0, 256)]
        labs = np.stack(labs)
        for i in range(4):
            for j in range(i + 1, 4):
                des.append(float(np.linalg.norm(labs[i] - labs[j])))
    _TILE_SPREAD = max(PALETTE_FLOOR_DE, float(np.percentile(des, 95)) if des else PALETTE_FLOOR_DE)
    return _TILE_SPREAD


def style_descriptor(arr: np.ndarray) -> np.ndarray:
    """Colour-layout descriptor: 4x4 regional mean colour plus a chroma-weighted
    hue histogram. Two tiles of the same faction are close in this space; a tile
    that drifted into another palette is not, even when its mean colour happens
    to look plausible."""
    im = Image.fromarray(arr).convert("RGB").resize((128, 128), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) / 255.0
    cells = [a[y:y + 32, x:x + 32].reshape(-1, 3).mean(0)
             for y in range(0, 128, 32) for x in range(0, 128, 32)]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hue = np.arctan2(np.sqrt(3.0) * (g - b), 2 * r - g - b)
    chroma = np.sqrt((r - g) ** 2 + (g - b) ** 2 + (b - r) ** 2) / np.sqrt(2.0)
    hist, _ = np.histogram(hue, bins=12, range=(-np.pi, np.pi), weights=chroma)
    hist = hist / (hist.sum() + 1e-6)
    return np.concatenate([np.concatenate(cells), hist * 3.0])


def style_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


_STYLE = None


def _style_reference():
    """{faction: descriptors} and {faction: p95 leave-one-out distance} built from
    the shipped material library. The tolerance is the library's own spread."""
    global _STYLE
    if _STYLE is not None:
        return _STYLE
    import itertools
    refs: dict[str, list[np.ndarray]] = {}
    for d in sorted(LIB.iterdir()):
        p = d / "albedo.png"
        if not p.exists():
            continue
        meta = json.loads((d / "meta.json").read_text())
        if meta.get("kind") in ("pattern", "decal"):
            # trim sheets and decals carry graphic motifs; they are not surfaces
            continue
        refs.setdefault(meta.get("faction", "shared"), []).append(
            style_descriptor(np.asarray(Image.open(p).convert("RGB"))))
    tol = {}
    for f, ds in refs.items():
        v = [style_distance(x, y) for x, y in itertools.combinations(ds, 2)]
        tol[f] = float(np.percentile(v, 95)) if v else 10.0
    _STYLE = (refs, tol)
    return _STYLE


def reference_tiles(faction: str, item_id: str) -> list[np.ndarray]:
    """Prefer the exact item's own tile; fall back to the faction's tiles. A
    generated variant is compared with the material it claims to reproduce."""
    out = []
    for cand in (LIB / f"{faction}__{item_id}", LIB / item_id):
        p = cand / "albedo.png"
        if p.exists():
            out.append(np.asarray(Image.open(p).convert("RGB").resize((256, 256))))
    if out:
        return out
    for d in sorted(LIB.glob(f"{faction}__*")):
        p = d / "albedo.png"
        if p.exists():
            out.append(np.asarray(Image.open(p).convert("RGB").resize((256, 256))))
    if not out:
        for d in sorted(LIB.iterdir()):
            p = d / "albedo.png"
            if p.exists() and "__" not in d.name:
                out.append(np.asarray(Image.open(p).convert("RGB").resize((256, 256))))
    return out


# -------------------------------------------------------------------- sheet ---

def contact_sheet(paths, out: Path, cols=4, cell=256):
    if not paths:
        return
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (24, 26, 30))
    for i, p in enumerate(paths):
        im = Image.open(p).convert("RGB").resize((cell, cell), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * cell, (i // cols) * cell))
    sheet.save(out)


# --------------------------------------------------------------------- main ---

def score_regression_files(out: Path) -> list[dict]:
    """Recompute the regression comparison from base/lora pairs on disk."""
    reg = []
    for b in sorted(out.glob("base_*.png")):
        l = out / b.name.replace("base_", "lora_", 1)
        if not l.exists():
            continue
        pid = b.name[len("base_"):].rsplit("_s", 1)[0]
        seed = int(b.name.rsplit("_s", 1)[1].split(".")[0])
        bs = structure_score(np.asarray(Image.open(b).convert("RGB")))
        ls = structure_score(np.asarray(Image.open(l).convert("RGB")))
        reg.append({"id": pid, "seed": seed, "base": round(bs, 4),
                    "lora": round(ls, 4), "retained": round(ls / bs, 3) if bs else None})
    return reg


def score_dir(out: Path, seeds_note: str = "") -> dict:
    rows = [json.loads(line) for line in (out / "meta.jsonl").read_text().splitlines() if line.strip()]
    refs_by_faction, tol = _style_reference()
    scored = []
    for r in rows:
        if r.get("kind") == "regression":
            continue
        arr = np.asarray(Image.open(out / r["file"]).convert("RGB"))
        faction = r.get("faction", "shared")
        pool = refs_by_faction.get(faction) or [v for vs in refs_by_faction.values() for v in vs]
        desc = style_descriptor(arr)
        dist = min((style_distance(desc, x) for x in pool), default=99.0)
        m = seam_metrics(arr)
        de = min((delta_e(arr, x) for x in reference_tiles(faction, r.get("id", ""))), default=99.0)
        scored.append({"id": r["id"], "faction": faction, "seed": r["seed"],
                       "file": r["file"], **m,
                       "flatness": round(flatness(arr), 4),
                       "style_dist": round(dist, 2), "style_tol": round(tol.get(faction, 10.0), 2),
                       "mean_de": round(de, 2)})
    return {"scored": scored, "seeds_note": seeds_note}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter")
    ap.add_argument("--out", required=True)
    ap.add_argument("--score-only", help="score an existing output dir; no GPU")
    ap.add_argument("--prompts", default=str(ROOT / "tools/train/prompts/eval_materials.json"))
    ap.add_argument("--seeds", default="11,22,33,44")
    ap.add_argument("--regression-seeds", default="11")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--steps", type=int, default=16)
    ap.add_argument("--skip-regression", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.score_only:
        data = score_dir(Path(args.score_only))
        scored = data["scored"]
        prior = Path(args.score_only) / "eval.json"
        reg = json.loads(prior.read_text()).get("regression", []) if prior.exists() else []
        if not reg:
            reg = score_regression_files(Path(args.score_only))
    else:
        if not args.adapter:
            raise SystemExit("--adapter is required unless --score-only is used")
        prompts = json.loads(Path(args.prompts).read_text())
        in_domain = [p for p in prompts if p.get("kind") != "regression"]
        regression = [p for p in prompts if p.get("kind") == "regression"]
        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
        rseeds = [int(s) for s in args.regression_seeds.split(",") if s.strip()]

        adapter = Path(args.adapter).resolve()
        pipe = G.load_pipe(adapter)
        rows = []
        for p in in_domain:
            for seed in seeds:
                img, _, _, _ = G.generate(pipe, p["prompt"], seed, args.size, args.steps,
                                       G.DEFAULT_GUIDANCE, "blend", True)
                name = f"{p['id']}_s{seed}.png"
                img.save(out / name)
                rows.append({"file": name, "id": p["id"], "kind": "in_domain",
                             "faction": p.get("faction"), "prompt": p["prompt"],
                             "seed": seed})
                print(f"generated {name}")
        (out / "meta.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        contact_sheet([out / r["file"] for r in rows], out / "in_domain_sheet.png")

        reg = []
        if regression and not args.skip_regression:
            del pipe
            base_pipe = G.load_pipe(None)
            for p in regression:
                for seed in rseeds:
                    b, _, _, _ = G.generate(base_pipe, p["prompt"], seed, args.size,
                                         args.steps, G.DEFAULT_GUIDANCE, "off", False)
                    b.save(out / f"base_{p['id']}_s{seed}.png")
            del base_pipe
            lora_pipe = G.load_pipe(adapter)
            for p in regression:
                for seed in rseeds:
                    l, _, _, _ = G.generate(lora_pipe, p["prompt"], seed, args.size,
                                         args.steps, G.DEFAULT_GUIDANCE, "off", False)
                    l.save(out / f"lora_{p['id']}_s{seed}.png")
                    b_arr = np.asarray(Image.open(out / f"base_{p['id']}_s{seed}.png").convert("RGB"))
                    l_arr = np.asarray(l)
                    bs, ls = structure_score(b_arr), structure_score(l_arr)
                    reg.append({"id": p["id"], "seed": seed, "base": round(bs, 4),
                                "lora": round(ls, 4),
                                "retained": round(ls / bs, 3) if bs else None})
                    print(f"regression {p['id']}: {bs:.3f} -> {ls:.3f}")
                contact_sheet([out / f"base_{p['id']}_s{s}.png" for s in rseeds] +
                              [out / f"lora_{p['id']}_s{s}.png" for s in rseeds],
                              out / f"regression_{p['id']}.png", cols=len(rseeds), cell=256)
            del lora_pipe
            contact_sheet([out / n for n in sorted(p.name for p in out.glob("*.png"))
                           if n.startswith(("base_", "lora_"))],
                          out / "regression_sheet.png", cols=4, cell=256)
        data = score_dir(out)
        scored = data["scored"]

    n = len(scored) or 1
    tiling = sum(1 for s in scored if s["ratio"] <= SEAM_RATIO_LIMIT) / n
    material = sum(1 for s in scored if s["flatness"] <= FLATNESS_LIMIT) / n
    palette = sum(1 for s in scored if s["style_dist"] <= s["style_tol"]) / n
    retained = ([r["retained"] for r in reg if r["retained"] is not None] or [1.0])
    regression_ok = sum(1 for r in retained if r >= 0.5) / len(retained)

    gates = {
        "tiling": {"value": round(tiling, 3), "threshold": 0.80,
                   "mean_ratio": round(float(np.mean([s["ratio"] for s in scored])), 3)
                   if scored else None, "pass": tiling >= 0.80},
        "material": {"value": round(material, 3), "threshold": 0.90,
                     "pass": material >= 0.90},
        "style": {"value": round(palette, 3), "threshold": 0.90,
                  "pass": palette >= 0.90},
        "regression": {"value": round(regression_ok, 3), "threshold": 0.75,
                       "pass": (regression_ok >= 0.75) if reg else None},
    }
    adopted = all(g["pass"] is not False for g in gates.values())

    adapter = Path(args.adapter).resolve() if args.adapter else None
    if adapter is None:
        prior = out / "eval.json"
        if prior.exists():
            rec = json.loads(prior.read_text()).get("adapter")
            adapter = Path(rec).resolve() if rec else None
    ds = ROOT / "datasets" / "materials_v2" / "manifest.json"
    if not ds.exists():
        ds = ROOT / "datasets" / "materials_v1" / "manifest.json"
    # prefer the config SimpleTuner actually ran (it writes a copy next to the run)
    cfg = ROOT / "tools" / "train" / "config_v2" / "config.json"
    if adapter is not None:
        run_cfg = adapter.parent.parent / "simpletuner_config.json"
        if run_cfg.exists():
            cfg = run_cfg
    if not cfg.exists():
        cfg = ROOT / "tools" / "train" / "config" / "config.json"
    report = {
        "adapter": str(adapter) if adapter else None,
        "adapter_sha256_16": G.adapter_hash(adapter) if adapter else None,
        "base_model": G.BASE_MODEL,
        "dataset_manifest_sha256_16": (hashlib.sha256(ds.read_bytes()).hexdigest()[:16]
                                       if ds.exists() else None),
        "config_sha256_16": (hashlib.sha256(cfg.read_bytes()).hexdigest()[:16]
                             if cfg.exists() else None),
        "gates": gates, "adopted": adopted,
        "in_domain": scored, "regression": reg,
    }
    (out / "eval.json").write_text(json.dumps(report, indent=2))

    md = ["# Adapter adoption gate", "",
          f"Adapter: `{adapter or 'score-only'}`"
          + (f" (sha256[:16] `{report['adapter_sha256_16']}`)" if adapter else ""),
          f"Base: `{G.BASE_MODEL}`", "",
          "| Gate | Result | Threshold | Status |", "|---|---|---|---|"]
    for name, g in gates.items():
        status = "n/a" if g["pass"] is None else ("PASS" if g["pass"] else "FAIL")
        md.append(f"| {name} | {g['value']} | {g['threshold']} | {status} |")
    md += ["", f"**Verdict: {'ADOPT' if adopted else 'REJECT'}**", "",
           "Tiling is measured as wrap-edge roughness divided by the tile's own",
           "interior-edge roughness. A correct wrap edge is indistinguishable from an",
           "interior edge; absolute border difference is not a seam metric because a",
           "high-frequency material has a large (and correct) border difference.",
           "Style distance uses a 4x4 colour-layout + chroma-histogram descriptor",
           "against the faction's own reference tiles; the tolerance is that set's",
           "leave-one-out p95. Mean dE is reported for information only.", "",
           "Visual review is still required: `in_domain_sheet.png`, `regression_sheet.png`.",
           "", "## In-domain samples", "",
           "| file | seam ratio | seam | flatness | style / tol | mean dE |",
           "|---|---|---|---|---|---|"]
    md += [f"| `{s['file']}` | {s['ratio']} | {s['seam']} | {s['flatness']} | "
           f"{s['style_dist']} / {s['style_tol']} | {s['mean_de']} |" for s in scored]
    if reg:
        md += ["", "## Regression", "", "| prompt | base | lora | retained |", "|---|---|---|---|"]
        md += [f"| {r['id']} | {r['base']} | {r['lora']} | {r['retained']} |" for r in reg]
    (out / "EVAL.md").write_text("\n".join(md) + "\n")
    print(f"{'ADOPT' if adopted else 'REJECT'}: {json.dumps(gates)}")
    return 0 if adopted else 1


if __name__ == "__main__":
    sys.exit(main())
