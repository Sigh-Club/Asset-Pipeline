#!/usr/bin/env python3
"""palette_lock.py — lock a rendered master or a baked atlas onto a style-profile
palette, with ordered dithering, and prove the result is palette-exact.

This is the step that turns a smooth 3D render into a pixel master. Rendering at
the profile canvas without antialiasing gives hard edges but *shaded* colours;
those colours are a product of the palette and lighting, so they are off-palette.
Locking the image to the profile palette is what makes the asset read as pixel art
and what makes `palette_compliance` a measurable fact instead of an aspiration.

Reuses the house pixeliser's Oklab nearest-palette mapping, Bayer matrices and
orphan-pixel cleanup (`pz/pixel/pixelise.py`) rather than reimplementing colour
science.

The verification is not optional: every opaque output pixel must be exactly a
palette entry. `--selftest` builds a deliberately off-palette image and asserts
the check fires.

Usage:
    python3 tools/style/palette_lock.py <img.png> --profile palette_3d
    python3 tools/style/palette_lock.py --dir <dir> --palette grimdark_64 \
        --dither bayer4 --out-dir <dir>/pixel
    python3 tools/style/palette_lock.py --selftest
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PIXEL_DIR = ROOT / "pz" / "pixel"


def _load_pixelise():
    sys.path.insert(0, str(PIXEL_DIR))
    spec = importlib.util.spec_from_file_location("pixelise", PIXEL_DIR / "pixelise.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_palette(palette_id: str) -> np.ndarray:
    """Palette as uint8 RGB rows. Accepts a pixel-style registry key or a .gpl."""
    styles = PIXEL_DIR / "styles.py"
    if styles.exists():
        sys.path.insert(0, str(PIXEL_DIR))
        try:
            spec = importlib.util.spec_from_file_location("pixel_styles", styles)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            entry = getattr(mod, "STYLES", {}).get(palette_id)
            if entry and entry.get("palette"):
                return np.array(entry["palette"], dtype=np.uint8)
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
            return np.array(cols, dtype=np.uint8)
    raise SystemExit(f"palette '{palette_id}' not found")


def profile_palette(profile_id: str) -> str:
    import importlib.util as iu
    spec = iu.spec_from_file_location("style_profiles", ROOT / "tools" / "style" / "profiles.py")
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.load_config()
    resolved = mod.resolve(profile_id, cfg)
    errors = mod.validate(resolved, cfg)
    if errors:
        raise SystemExit("invalid profile: " + "; ".join(errors))
    pid = resolved.get("pixel", {}).get("palette_id")
    if not pid:
        raise SystemExit(f"profile '{profile_id}' has no pixel.palette_id")
    return pid


def despeckle(alpha: np.ndarray, min_px: int) -> tuple[np.ndarray, int]:
    """Drop alpha islands smaller than `min_px`.

    A 1-pixel island in a master is a degenerate face or a rounding sliver, and
    it fails the silhouette component count for reasons no artist would accept.
    Returns the cleaned alpha and how many pixels were removed.
    """
    if min_px <= 1:
        return alpha, 0
    opaque = alpha > 0
    seen = np.zeros_like(opaque)
    removed = 0
    ys, xs = np.where(opaque)
    for y, x in zip(ys, xs):
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        comp = []
        while stack:
            cy, cx = stack.pop()
            comp.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < opaque.shape[0] and 0 <= nx < opaque.shape[1] \
                        and opaque[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(comp) < min_px:
            for cy, cx in comp:
                alpha[cy, cx] = 0
            removed += len(comp)
    return alpha, removed


def lock_array(rgba: np.ndarray, palette: np.ndarray, dither: str,
               orphan: bool = True, strength: float = 12.0,
               min_component: int = 2) -> np.ndarray:
    px = _load_pixelise()
    out = rgba.copy()
    out[..., 3] = np.where(out[..., 3] > 127, 255, 0).astype(np.uint8)
    out[..., 3], removed = despeckle(out[..., 3], min_component)
    alpha = out[..., 3]
    opaque = alpha > 127
    out[..., 3] = np.where(opaque, 255, 0).astype(np.uint8)

    body = out[..., :3].astype(np.int16)
    if dither in ("bayer2", "bayer4") and opaque.any():
        b = px.BAYER2 if dither == "bayer2" else px.BAYER4
        h, w = opaque.shape
        tile = np.tile(b, (h // b.shape[0] + 1, w // b.shape[1] + 1))[:h, :w]
        body[opaque] = np.clip(
            body[opaque] + (tile[:, :, None] * strength)[opaque].astype(np.int16),
            0, 255)
    out[..., :3] = body.astype(np.uint8)
    if opaque.any():
        out[opaque, :3] = px.nearest_palette(out[opaque, :3], palette)
    if orphan:
        out = px.orphan_fix(out)
    return out


def verify(rgba: np.ndarray, palette: np.ndarray) -> dict:
    """Count opaque pixels whose RGB is not exactly a palette entry."""
    opaque = rgba[..., 3] > 0
    rgb = rgba[..., :3]
    pal = {tuple(int(c) for c in row) for row in palette}
    colours, counts = np.unique(rgb[opaque].reshape(-1, 3), axis=0, return_counts=True)
    off = 0
    for c, n in zip(colours, counts):
        if tuple(int(v) for v in c) not in pal:
            off += int(n)
    total = int(opaque.sum())
    return {"opaque_px": total, "off_palette_px": off,
            "off_palette_frac": round(off / total, 6) if total else 0.0,
            "palette_entries_used": int(len(colours)),
            "palette_entries_total": int(len(pal))}


def lock_file(path: Path, palette: np.ndarray, dither: str, out: Path | None,
              strength: float = 12.0, min_component: int = 2) -> dict:
    img = Image.open(path).convert("RGBA")
    before = np.asarray(img, dtype=np.uint8)
    locked = lock_array(before, palette, dither, strength=strength,
                        min_component=min_component)
    removed = int(((before[..., 3] > 127).sum()
                   - (locked[..., 3] > 0).sum()))
    dest = out or (path.parent / (path.stem + "_pixel.png"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(locked, "RGBA").save(dest)
    report = verify(locked, palette)
    report["file"] = str(dest)
    report["source"] = str(path)
    report["dither"] = dither
    report["dither_strength"] = strength
    report["despeckled_px"] = removed
    return report


def selftest() -> int:
    palette = load_palette("grimdark_64")
    cases = []
    # a deliberately off-palette image (antialiased-looking gradient)
    src = np.zeros((24, 24, 4), dtype=np.uint8)
    src[..., 3] = 255
    for y in range(24):
        src[y, :, :3] = (80 + y * 3, 90 + y * 2, 120 + y)
    locked = lock_array(src, palette, "bayer4")
    v = verify(locked, palette)
    cases.append(("off-palette input is flagged before locking",
                  verify(src, palette)["off_palette_px"] > 0))
    cases.append(("locked output is palette-exact", v["off_palette_px"] == 0))
    cases.append(("locking changes the image (not a no-op)",
                  not np.array_equal(locked[..., :3], src[..., :3])))
    # negative control: one hand-edited pixel must be caught
    broken = locked.copy()
    broken[4, 4, :3] = (1, 2, 3)
    broken[4, 4, 3] = 255
    cases.append(("a single off-palette pixel fails verification",
                  verify(broken, palette)["off_palette_px"] >= 1))
    # alpha must become binary
    soft = np.zeros((8, 8, 4), dtype=np.uint8)
    soft[..., 3] = 128
    soft[..., :3] = 40
    l2 = lock_array(soft, palette, "none")
    cases.append(("soft alpha is snapped to binary",
                  set(np.unique(l2[..., 3]).tolist()) <= {0, 255}))

    ok = True
    for name, passed in cases:
        print(f"{'PASS' if passed else 'FAIL'}  selftest: {name}")
        ok = ok and passed
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?")
    ap.add_argument("--dir", help="lock every PNG in a directory")
    ap.add_argument("--profile", help="take the palette from this style profile")
    ap.add_argument("--palette", help="palette id (overrides --profile)")
    ap.add_argument("--dither", default="none",
                    choices=("none", "bayer2", "bayer4"))
    ap.add_argument("--dither-strength", type=float, default=12.0,
                    help="ordered-dither amplitude in 8-bit levels. 24 is right for "
                         "smooth masters; on a texture-dense atlas it reads as noise")
    ap.add_argument("--min-component", type=int, default=2,
                    help="alpha islands smaller than this are dropped (degenerate "
                         "sliver cleanup; 1 disables)")
    ap.add_argument("--out-dir", help="write locked PNGs here (default: beside source)")
    ap.add_argument("--suffix", default="_palette")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    palette_id = args.palette or (profile_palette(args.profile) if args.profile else None)
    if not palette_id:
        raise SystemExit("give --palette or --profile")
    palette = load_palette(palette_id)

    if args.image:
        paths = [Path(args.image)]
    elif args.dir:
        paths = sorted(Path(args.dir).glob("*.png"))
        if args.suffix:
            paths = [p for p in paths if not p.stem.endswith(args.suffix)]
    else:
        raise SystemExit("give an image, --dir or --selftest")
    if not paths:
        raise SystemExit("no PNGs found")
    out_dir = Path(args.out_dir) if args.out_dir else None

    reports, bad = [], 0
    for p in paths:
        dest = (out_dir / (p.stem + args.suffix + ".png")) if out_dir else None
        r = lock_file(p, palette, args.dither, dest, args.dither_strength,
                      args.min_component)
        reports.append(r)
        bad += 1 if r["off_palette_px"] else 0
        print(f"{'FAIL' if r['off_palette_px'] else 'PASS'}  {Path(r['file']).name}  "
              f"colours {r['palette_entries_used']}/{r['palette_entries_total']}  "
              f"off-palette {r['off_palette_px']}")
    if args.json:
        import json
        print(json.dumps(reports, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
