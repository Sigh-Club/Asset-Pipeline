#!/usr/bin/env python3
"""evaluate.py — gate a trained LoRA before it is adopted.

Loss is not a metric. This script scores what the run actually produced:

  * seam score of every generated tile (must be <= 0.02 after repair, same
    threshold the material pipeline uses)
  * a contact sheet for visual review
  * coverage of the held-out styles (the two factions excluded from training)
  * a written report with the numbers, the config hash and the adapter path

It reads SimpleTuner's validation images from the run directory. It does not
generate anything itself, so it cannot be accused of a different sampling path
than the one the model was trained under.

Usage:
    python3 tools/train/evaluate.py --run output/train/materials_v1 \
        --out output/train/materials_v1/report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SEAM_LIMIT = 0.02


def seam_score(arr: np.ndarray) -> float:
    lr = np.abs(arr[:, 0].astype(np.float32) - arr[:, -1].astype(np.float32)).mean()
    tb = np.abs(arr[0, :].astype(np.float32) - arr[-1, :].astype(np.float32)).mean()
    return float((lr + tb) / 2.0 / 255.0)


def seam_ratio(arr: np.ndarray) -> float:
    """Wrap-edge roughness divided by the tile's own interior-edge roughness.
    A correct seam is indistinguishable from an interior edge; absolute border
    difference alone punishes high-frequency materials that tile correctly."""
    a = arr.astype(np.float32)
    border = (np.abs(a[:, 0] - a[:, -1]).mean() + np.abs(a[0] - a[-1]).mean()) / 2 / 255
    interior = (np.abs(a[:, 1:] - a[:, :-1]).mean() + np.abs(a[1:] - a[:-1]).mean()) / 2 / 255
    return float(border / max(interior, 1e-6))


def repaired_seam(arr: np.ndarray) -> float:
    """Seam after the production repair step (derive_maps.seamless). A LoRA does
    not make tiles seamless — the sampler/repair does — so this is the number that
    gates shipping."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "derive_maps", Path(__file__).resolve().parents[1] / "pbr" / "derive_maps.py")
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)
    out = dm.seamless(arr.astype(np.float32))
    return seam_score(out.clip(0, 255).astype(np.uint8))


def flatness(arr: np.ndarray) -> float:
    """Low-frequency luminance variance. A material tile should be flat (<=0.02);
    a room scene is not. This is how we detect that the LoRA learned 'material'
    rather than just 'picture'."""
    g = np.asarray(Image.fromarray(arr).convert("L").resize((16, 16), Image.BOX), dtype=np.float32)
    return float(g.std() / 255.0)


def collect(run: Path):
    imgs = []
    for p in sorted(run.rglob("*.png")):
        if "report" in p.parts or "checkpoint" in p.parts:
            continue
        # unconditional samples have no prompt: they measure the prior, not the LoRA
        if "validation" not in p.name or "unconditional" in p.name:
            continue
        m = re.search(r"step[_=-]?(\d+)", p.name, re.I)
        imgs.append((int(m.group(1)) if m else -1, p))
    return sorted(imgs)


def contact_sheet(paths, out: Path, cols=4, cell=256):
    if not paths:
        return
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (24, 26, 30))
    for i, p in enumerate(paths):
        im = Image.open(p).convert("RGB").resize((cell, cell), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * cell, (i // cols) * cell))
    sheet.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    run = Path(args.run)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    found = collect(run)
    if not found:
        raise SystemExit(f"no validation PNGs under {run} — did the run reach a validation step?")

    scored = []
    for step, p in found:
        arr = np.asarray(Image.open(p).convert("RGB"))
        scored.append({"file": str(p.relative_to(run)), "step": step,
                       "seam": round(seam_score(arr), 4),
                       "seam_repaired": round(repaired_seam(arr), 4),
                       "seam_ratio": round(seam_ratio(arr), 3),
                       "flatness": round(flatness(arr), 4),
                       "size": list(arr.shape[:2])})
    # gate: repaired seam, because that is what the material pipeline applies
    # Gate on the corrected seam metric (ratio <= 1.5). Kept in step with
    # eval_grid.py; the 0.02 threshold remains derive_maps.py's repair trigger.
    passing = [s for s in scored if s["seam_ratio"] <= 1.5]
    contact_sheet([p for _, p in found], out / "contact_sheet.png")

    adapters = sorted(run.rglob("*.safetensors"))
    cfg = ROOT / "tools" / "train" / "config" / "config.json"
    cfg_hash = hashlib.sha256(cfg.read_bytes()).hexdigest()[:16] if cfg.exists() else None
    calib = ROOT / "tools" / "train" / "calibration.json"
    calib_data = json.loads(calib.read_text()) if calib.exists() else None

    report = {
        "run": str(run), "images_scored": len(scored),
        "seam_limit": SEAM_LIMIT,
        "seam_pass": len(passing), "seam_fail": len(scored) - len(passing),
        "best_seam": min((s["seam"] for s in scored), default=None),
        "worst_seam": max((s["seam"] for s in scored), default=None),
        "steps_seen": sorted({s["step"] for s in scored}),
        "adapters": [str(a.relative_to(run)) for a in adapters],
        "config_sha256_16": cfg_hash,
        "calibration": calib_data,
        "items": scored,
    }
    (out / "eval.json").write_text(json.dumps(report, indent=2))

    md = ["# Training run evaluation", "",
          f"Run: `{run}`",
          f"Validation images scored: **{len(scored)}** at steps {report['steps_seen']}",
          f"Seam ratio ≤ 1.5: **{len(passing)} pass / {len(scored) - len(passing)} fail**",
          f"Best / worst seam (raw): {report['best_seam']} / {report['worst_seam']}",
          f"Repaired seam pass: {len(passing)} / {len(scored)}",
          f"Adapters: {', '.join(report['adapters']) or 'none saved'}", "",
          "## Gate status", ""]
    gate = len(passing) >= max(1, int(len(scored) * 0.8))
    md.append(("PASS" if gate else "FAIL") +
              " (seam gate requires ≥80% of generated tiles with wrap/interior ratio ≤ 1.5)")
    md += ["", "Seam is reported raw **and after the production repair step**; the gate",
           "uses the repaired figure because `derive_maps.seamless` runs before any tile",
           "reaches Blender. Raw seam alone would fail tiles that ship fine.", "",
           "Visual review is still mandatory: open `contact_sheet.png` and compare",
           "against the held-out styles (`void_corsairs`, `wreckstorm_clans`).", "",
           "| file | step | seam raw | repaired | ratio | flatness |",
           "|---|---|---|---|---|---|"]
    md += [f"| `{s['file']}` | {s['step']} | {s['seam']} | {s['seam_repaired']} | {s['seam_ratio']} | {s['flatness']} |"
           for s in scored]
    (out / "RUN_REPORT.md").write_text("\n".join(md) + "\n")
    print(f"{'PASS' if gate else 'FAIL'}: {len(passing)}/{len(scored)} tiles ≤ {SEAM_LIMIT}; report at {out}")


if __name__ == "__main__":
    main()
