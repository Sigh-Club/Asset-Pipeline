#!/usr/bin/env python3
"""check_pixel_asset.py — palette and silhouette gate for a pixel-tier asset.

The PBR gates (seam, flatness) are meaningless for a palette-locked asset. This
gate measures what the pixel tier actually cares about:

  * silhouette integrity — one connected shape (or the expected count), and a
    bounding-box fill ratio that is neither a stringy mess nor a featureless blob
  * palette drift — how far the source render sits from the profile palette, in
    Oklab. Low drift means the master is palette-compatible; high drift means the
    pixeliser will have to destroy detail to reach the palette.
  * a palette-locked preview written next to the input for visual review

It does not replace the human readability review; it catches the mechanical
failures before a human spends time on the asset.

Usage:
    python3 tools/style/check_pixel_asset.py render.png --profile pixel_3d
    python3 tools/style/check_pixel_asset.py render.png --profile hd_pixel_sprite --json
    python3 tools/style/check_pixel_asset.py --dir output/props/barrel/render --profile pixel_3d
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "style"))
import profiles  # noqa: E402

DRIFT_MEAN_LIMIT = 0.10
DRIFT_P95_LIMIT = 0.20
# A long thin weapon legitimately fills little of its bounding box; a tile fills
# most of it. The expected range is per asset kind, not one global constant.
KIND_FILL = {
    "weapon": (0.10, 0.95), "prop": (0.25, 0.95), "tile": (0.45, 1.0),
    "unit": (0.15, 0.92), "building": (0.35, 0.95), "foliage": (0.10, 0.95),
    "ui_icon": (0.10, 0.95),
}
ALPHA_THRESHOLD = 10


# --------------------------------------------------------------------- colour ---

def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rgb_to_oklab(rgb):
    r, g, b = (srgb_to_linear(rgb[..., i]) for i in range(3))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(l), np.cbrt(m), np.cbrt(s)
    return np.stack([
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    ], axis=-1)


def load_palette(palette_id: str) -> np.ndarray:
    """Palette colours as float RGB in 0..1, from the pixel style registry or a
    .gpl file."""
    import importlib.util
    styles = ROOT / "pz" / "pixel" / "styles.py"
    if styles.exists():
        sys.path.insert(0, str(styles.parent))
        try:
            spec = importlib.util.spec_from_file_location("pixel_styles", styles)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            entry = getattr(mod, "STYLES", {}).get(palette_id)
            if entry and entry.get("palette"):
                return np.array(entry["palette"], dtype=np.float32) / 255.0
        except Exception:  # noqa: BLE001
            pass
        finally:
            sys.path.pop(0)
    gpl = ROOT / "assets" / "palettes" / f"{palette_id}.gpl"
    if gpl.exists():
        cols = []
        for line in gpl.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    cols.append([int(parts[0]), int(parts[1]), int(parts[2])])
                except ValueError:
                    continue
        if cols:
            return np.array(cols, dtype=np.float32) / 255.0
    raise SystemExit(f"palette '{palette_id}' not found")


# -------------------------------------------------------------------- metrics ---

def alpha_metrics(alpha: np.ndarray) -> dict:
    mask = alpha > ALPHA_THRESHOLD
    if not mask.any():
        return {"coverage": 0.0, "bbox_fill": 0.0, "components": 0}
    ys, xs = np.where(mask)
    h = ys.max() - ys.min() + 1
    w = xs.max() - xs.min() + 1
    fill = float(mask.sum()) / float(h * w)

    # 4-connected components, iterative (no scipy dependency)
    seen = np.zeros_like(mask, dtype=bool)
    comps = 0
    stack = []
    for y, x in zip(ys, xs):
        if seen[y, x]:
            continue
        comps += 1
        stack.append((y, x))
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] \
                        and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return {"coverage": round(float(mask.mean()), 4),
            "bbox_fill": round(fill, 3), "components": comps}


def palette_drift(rgb: np.ndarray, mask: np.ndarray, palette: np.ndarray) -> dict:
    lab = rgb_to_oklab(rgb)
    pal_lab = rgb_to_oklab(palette)
    px = lab[mask]
    # nearest palette entry per pixel
    d = np.linalg.norm(px[:, None, :] - pal_lab[None, :, :], axis=-1)
    if d.size == 0:
        return {"drift_mean": 0.0, "drift_p95": 0.0}
    nearest = d.min(axis=1)
    return {"drift_mean": round(float(nearest.mean()), 4),
            "drift_p95": round(float(np.percentile(nearest, 95)), 4)}


def quantise(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    lab = rgb_to_oklab(rgb)
    pal_lab = rgb_to_oklab(palette)
    px = lab.reshape(-1, 3)
    d = np.linalg.norm(px[:, None, :] - pal_lab[None, :, :], axis=-1)
    idx = d.argmin(axis=1)
    return (palette[idx].reshape(rgb.shape) * 255).astype(np.uint8)


# ----------------------------------------------------------------------- main ---

def check(path: Path, profile_id: str, write_preview: bool, kind: str = "prop") -> dict:
    cfg = profiles.load_config()
    resolved = profiles.resolve(profile_id, cfg)
    errors = profiles.validate(resolved, cfg)
    if errors:
        raise SystemExit("invalid profile: " + "; ".join(errors))
    palette_id = resolved.get("pixel", {}).get("palette_id")
    if not palette_id:
        raise SystemExit(f"profile '{profile_id}' has no pixel.palette_id")

    img = Image.open(path).convert("RGBA")
    a = np.asarray(img, dtype=np.uint8)
    rgb = a[..., :3].astype(np.float32) / 255.0
    alpha = a[..., 3]
    mask = alpha > ALPHA_THRESHOLD

    palette = load_palette(palette_id)
    drift = palette_drift(rgb, mask, palette)
    shape = alpha_metrics(alpha)

    preview = None
    if write_preview:
        q = quantise(rgb, palette)
        out = np.dstack([q, a[..., 3]])
        (path.parent / "pixel").mkdir(exist_ok=True)
        preview = path.parent / "pixel" / (path.stem + f"_{palette_id}.png")
        Image.fromarray(out, "RGBA").save(preview)

    gates = resolved.get("gates", [])
    result = {"file": str(path), "profile": profile_id, "palette": palette_id,
              "metrics": {**shape, **drift}, "gates": gates,
              "preview": str(preview) if preview else None}

    failures = []
    if "palette_compliance" in gates:
        if drift["drift_mean"] > DRIFT_MEAN_LIMIT:
            failures.append(f"palette drift mean {drift['drift_mean']} > {DRIFT_MEAN_LIMIT}")
        if drift["drift_p95"] > DRIFT_P95_LIMIT:
            failures.append(f"palette drift p95 {drift['drift_p95']} > {DRIFT_P95_LIMIT}")
    if "silhouette" in gates or "readability" in gates:
        fill_min, fill_max = KIND_FILL.get(kind, KIND_FILL["prop"])
        if shape["components"] != 1:
            failures.append(f"silhouette has {shape['components']} components (expected 1)")
        if not fill_min <= shape["bbox_fill"] <= fill_max:
            failures.append(f"bbox fill {shape['bbox_fill']} outside {fill_min}-{fill_max} "
                            f"for kind '{kind}'")
        if shape["coverage"] < 0.01:
            failures.append("silhouette covers <1% of the canvas")

    result["failures"] = failures
    result["verdict"] = "FAIL" if failures else "PASS"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?")
    ap.add_argument("--dir", help="check every PNG in a directory")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--kind", default="prop",
                    choices=sorted(KIND_FILL))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    if not args.image and not args.dir:
        raise SystemExit("give an image or --dir")
    paths = ([Path(args.image)] if args.image
             else sorted(Path(args.dir).glob("*.png")))
    if not paths:
        raise SystemExit("no PNGs found")

    results = [check(p, args.profile, not args.no_preview, args.kind) for p in paths]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            m = r["metrics"]
            print(f"{r['verdict']}  {Path(r['file']).name}  drift {m['drift_mean']}/{m['drift_p95']}"
                  f"  fill {m['bbox_fill']}  comps {m['components']}")
            for f in r["failures"]:
                print(f"      {f}")
    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
