#!/usr/bin/env python3
"""retune_material.py — apply recorded art-direction fixes to derived library items.

The 2026-11-09 review of the first pixel-tier masters found faults that are not
generation failures but surface-language faults: a glossy blue "gunmetal", a
flat low-contrast steel, a gold motif that reads as an insignia at 2 cm texels.
Re-generating the sheet costs a Gemini generation and changes everything; most of
these are a deterministic colour/tone/scale correction on the existing sheet.

Operations are declared in `configs/materials/retune.json` (data, not code), so
every change carries the defect it fixes. After retuning the albedo the normal
and roughness maps are re-derived from it — a retuned albedo with old normals
would disagree with itself.

Usage:
    python3 tools/pbr/retune_material.py --id iron_directorate__metal_trim
    python3 tools/pbr/retune_material.py --all
    python3 tools/pbr/retune_material.py --id gunmetal_worn --dry-run
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
CONFIG = ROOT / "configs" / "materials" / "retune.json"


def derive_module():
    spec = importlib.util.spec_from_file_location(
        "derive_maps", ROOT / "tools" / "pbr" / "derive_maps.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def desaturate(a: np.ndarray, to_luma: float) -> np.ndarray:
    """Pull chroma toward the pixel's own luma. A gunmetal is a neutral alloy;
    the generated sheet carried a blue screen-space sheen that reads as paint."""
    luma = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2])
    return np.clip(a * (1.0 - to_luma) + luma[..., None] * to_luma, 0, 255)


def level_stretch(a: np.ndarray, low_pct: float, high_pct: float,
                  out_low: float, out_high: float) -> np.ndarray:
    """Widen the value histogram to a measured target. Flat steel reads as one
    mass at 256 px; the fix is value separation, not more detail."""
    luma = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2])
    lo = float(np.percentile(luma, low_pct))
    hi = float(np.percentile(luma, high_pct))
    if hi - lo < 1e-3:
        return a
    gain = (out_high - out_low) / (hi - lo)
    return np.clip((a - lo) * gain + out_low, 0, 255)


OPS = {"desaturate": desaturate, "level_stretch": level_stretch}


def apply_retune(item_id: str, spec: dict, dry_run: bool) -> dict:
    item_dir = LIB / item_id
    albedo_path = item_dir / "albedo.png"
    if not albedo_path.exists():
        raise SystemExit(f"no albedo for {item_id} at {albedo_path}")
    before = np.asarray(Image.open(albedo_path).convert("RGB"), dtype=np.float32)
    a = before.copy()
    for op in spec.get("ops", []):
        fn = OPS.get(op["op"])
        if fn is None:
            raise SystemExit(f"unknown retune op '{op['op']}' for {item_id}")
        params = {k: v for k, v in op.items() if k != "op"}
        a = fn(a, **params)

    luma_b = before @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    luma_a = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    report = {
        "id": item_id,
        "because": spec.get("because"),
        "luma_std_before": round(float(luma_b.std()), 2),
        "luma_std_after": round(float(luma_a.std()), 2),
        "luma_range_before": [round(float(luma_b.min()), 1), round(float(luma_b.max()), 1)],
        "luma_range_after": [round(float(luma_a.min()), 1), round(float(luma_a.max()), 1)],
        "chroma_before": round(float((before.max(-1) - before.min(-1)).mean()), 2),
        "chroma_after": round(float((a.max(-1) - a.min(-1)).mean()), 2),
    }
    if dry_run:
        report["dry_run"] = True
        return report

    dm = derive_module()
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(albedo_path)
    Image.fromarray(dm.normal_map(a, 1.3)).save(item_dir / "normal.png")
    Image.fromarray(dm.roughness_map(a, 0.0, False)).save(item_dir / "roughness.png")

    meta_path = item_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.setdefault("retunes", []).append(report)
    for k, v in (spec.get("meta") or {}).items():
        meta[k] = v
    meta["maps"] = sorted(meta.get("maps", ["albedo", "normal", "roughness", "metallic"]))
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    retunes = cfg["retunes"]
    if args.id:
        if args.id not in retunes:
            raise SystemExit(f"no retune recorded for '{args.id}' in {CONFIG}")
        targets = {args.id: retunes[args.id]}
    elif args.all:
        targets = retunes
    else:
        raise SystemExit("give --id or --all")
    for item_id, spec in sorted(targets.items()):
        r = apply_retune(item_id, spec, args.dry_run)
        print(f"{'DRY ' if args.dry_run else ''}{item_id}: luma std "
              f"{r['luma_std_before']} -> {r['luma_std_after']}, chroma "
              f"{r['chroma_before']} -> {r['chroma_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
