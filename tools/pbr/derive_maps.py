#!/usr/bin/env python3
"""derive_maps.py — turn a generated 2x2 sheet into game-ready PBR materials.

The image model produces **albedo only**. Normal, roughness and metallic are
derived here so they are physically consistent, tileable and reproducible — an
image model cannot guarantee height/normal agreement, and its "normal maps" are
usually decorative purple noise.

For each item in a batch this writes, under
assets/materials/grimdark_scifi/<item_id>/:
    albedo.png      seamless tiling base colour
    normal.png      tangent-space normal (OpenGL +Y, glTF convention)
    roughness.png   greyscale
    metallic.png    greyscale constant
    emissive.png    (emissive items only) glow mask
    meta.json       source, quadrant, seam scores, derived parameters

Usage:
    python3 tools/pbr/derive_maps.py --batch 1
    python3 tools/pbr/derive_maps.py --batch 1 --sheet path/to/sheet.png
    python3 tools/pbr/derive_maps.py --all          # every sheet present
    python3 tools/pbr/derive_maps.py --batch 1 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
MANIFEST = LIB / "manifest.json"
OUT_SIZE = 1024
GUTTER = 0.02  # fraction trimmed from each quadrant edge (sheet gutter + bleed)


# --- image operators -------------------------------------------------------

def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def load_sheet_raw(path: Path):
    """Return (rgb, alpha-or-None) so decals keep their transparency."""
    img = Image.open(path)
    alpha = None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        alpha = np.asarray(img.split()[-1], dtype=np.float32)
    return np.asarray(img.convert("RGB"), dtype=np.float32), alpha


def seamless(a: np.ndarray, band: float = 0.18) -> np.ndarray:
    """Make a near-periodic texture tile.

    The border band is replaced with the rolled copy's interior, so both wrap
    edges sample the *same* content and the seam matches by construction. The
    previous mask (0 at the border) is a no-op at the seam — that is why seam
    scores did not improve.
    """
    h, w = a.shape[:2]
    rolled = np.roll(np.roll(a, h // 2, axis=0), w // 2, axis=1)
    ax = np.abs(np.linspace(-1.0, 1.0, w))[None, :]
    ay = np.abs(np.linspace(-1.0, 1.0, h))[:, None]
    band = max(band, 1e-3)
    tx = np.clip((ax - (1.0 - band)) / band, 0.0, 1.0)
    ty = np.clip((ay - (1.0 - band)) / band, 0.0, 1.0)
    mask = np.maximum(tx, ty)[..., None]
    # smoothstep the mask so the transition has no visible ring
    mask = mask * mask * (3.0 - 2.0 * mask)
    return np.clip(a * (1.0 - mask) + rolled * mask, 0, 255)


def seam_score(a: np.ndarray) -> float:
    """Mean absolute difference across the wrap seam, normalised 0-1."""
    lr = np.abs(a[:, 0] - a[:, -1]).mean()
    tb = np.abs(a[0, :] - a[-1, :]).mean()
    return float((lr + tb) / 2.0 / 255.0)


def seam_ratio(a: np.ndarray) -> float:
    """Wrap-edge roughness divided by the tile's own interior-edge roughness.
    A correct periodic texture has a wrap edge indistinguishable from an interior
    edge. Absolute border difference is not a repair criterion: high-frequency
    materials have a large (and correct) border difference."""
    a = a.astype(np.float32)
    border = (np.abs(a[:, 0] - a[:, -1]).mean() + np.abs(a[0, :] - a[-1, :]).mean()) / 2 / 255
    interior = (np.abs(a[:, 1:] - a[:, :-1]).mean() + np.abs(a[1:, :] - a[:-1, :]).mean()) / 2 / 255
    return float(border / max(interior, 1e-6))


def height_from_albedo(a: np.ndarray) -> np.ndarray:
    luma = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255.0
    img = Image.fromarray((luma * 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    h = np.asarray(img, dtype=np.float32) / 255.0
    # local detail high-pass: albedo texture carries micro relief
    blur = np.asarray(Image.fromarray((h * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(6)), dtype=np.float32) / 255.0
    return np.clip(0.5 + (h - blur) * 2.0, 0, 1)


def normal_map(a: np.ndarray, strength: float) -> np.ndarray:
    h = height_from_albedo(a)
    gx = np.zeros_like(h)
    gy = np.zeros_like(h)
    gx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) * 0.5
    gy[1:-1, :] = (h[2:, :] - h[:-2, :]) * 0.5
    # wrap the gradient so the normal map also tiles
    gx[:, 0] = (h[:, 1] - h[:, -1]) * 0.5
    gx[:, -1] = (h[:, 0] - h[:, -2]) * 0.5
    gy[0, :] = (h[1, :] - h[-1, :]) * 0.5
    gy[-1, :] = (h[0, :] - h[-2, :]) * 0.5
    nx = -gx * strength
    ny = gy * strength  # OpenGL +Y (green up) for glTF
    nz = np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / ln, ny / ln, nz / ln], axis=-1)
    return ((rgb * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)


def roughness_map(a: np.ndarray, metal: float, emissive: bool) -> np.ndarray:
    base = 0.30 if metal >= 0.8 else (0.38 if metal >= 0.4 else 0.55)
    luma = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255.0
    blur = np.asarray(
        Image.fromarray((luma * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(4)),
        dtype=np.float32) / 255.0
    detail = luma - blur           # recesses/dirt read rougher, highlights polish
    r = np.clip(base - detail * 0.35, 0.05, 0.98)
    if emissive:
        r = np.clip(r * 0.8, 0.05, 0.6)
    return (r * 255).clip(0, 255).astype(np.uint8)


def emissive_map(a: np.ndarray) -> np.ndarray:
    luma = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255.0
    mx = a.max(axis=-1) / 255.0
    sat = np.where(mx > 1e-6, (mx - a.min(axis=-1) / 255.0) / mx, 0.0)
    mask = np.clip((luma - 0.45) * 2.2, 0, 1) * np.clip(sat * 2.0, 0, 1)
    return (a * mask[..., None]).clip(0, 255).astype(np.uint8)


# --- sheet handling --------------------------------------------------------

def crop_quadrants(sheet: np.ndarray):
    h, w = sheet.shape[:2]
    ch, cw = h // 2, w // 2
    boxes = []
    for row in range(2):
        for col in range(2):
            y0, x0 = row * ch, col * cw
            patch = sheet[y0:y0 + ch, x0:x0 + cw]
            # centre square crop: keeps material scale uniform and avoids
            # stretching a 1408x768 quadrant into a square map
            side = min(ch, cw)
            iy = (ch - side) // 2
            ix = (cw - side) // 2
            patch = patch[iy:iy + side, ix:ix + side]
            # image models like to draw a border/frame around a "plate"; inset
            # past it or the frame repeats as horizontal bands under box mapping
            ins = int(side * 0.07)
            boxes.append(patch[ins:side - ins, ins:side - ins])
    return boxes


def flatten_lighting(a: np.ndarray, keep: float = 0.15) -> np.ndarray:
    """Remove the low-frequency brightness gradient that image models bake in.
    Albedo must not contain lighting; a blurred-luminance division leaves the
    colour pattern and micro-contrast while flattening studio falloff."""
    luma = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    blur = np.asarray(Image.fromarray(luma.clip(0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(max(a.shape[1] // 8, 8))), dtype=np.float32)
    blur = np.maximum(blur, 1.0)
    gain = (float(blur.mean()) / blur) ** (1.0 - keep)
    return np.clip(a * gain[..., None], 0, 255)


def trim_black_frame(patch: np.ndarray, dark: float = 14.0):
    """Sheets are drawn on black with a white card inside. Trim the black gutter
    first: a global black-key would also erase black artwork."""
    def is_dark(line):
        return np.median(line) < dark

    top = 0
    while top < patch.shape[0] - 1 and is_dark(patch[top]):
        top += 1
    bottom = patch.shape[0] - 1
    while bottom > top and is_dark(patch[bottom]):
        bottom -= 1
    left = 0
    while left < patch.shape[1] - 1 and is_dark(patch[:, left]):
        left += 1
    right = patch.shape[1] - 1
    while right > left and is_dark(patch[:, right]):
        right -= 1
    return patch[top:bottom + 1, left:right + 1]


def key_white_to_alpha(patch: np.ndarray):
    """Key a decal's card/background out, robustly.

    Image models cannot emit alpha: asked for transparency they draw a
    checkerboard; asked for white they often draw a *lit card* with a vignette.
    So the background is estimated locally (downscale -> upscale) and the alpha is
    the distance below it, with a saturation term to protect bright coloured art.
    Cards that are not light (full-bleed patterns like hazard stripes) are left
    fully opaque.
    """
    luma = (0.2126 * patch[..., 0] + 0.7152 * patch[..., 1] + 0.0722 * patch[..., 2])
    small = Image.fromarray(luma.clip(0, 255).astype(np.uint8)).resize((24, 24), Image.BOX)
    bg = np.asarray(small.resize((patch.shape[1], patch.shape[0]), Image.BILINEAR), dtype=np.float32)
    corners = np.array([luma[2, 2], luma[2, -3], luma[-3, 2], luma[-3, -3]])
    if float(np.median(corners)) < 190.0:
        # not a light card: full-bleed pattern, keep everything
        return np.dstack([patch, np.full(luma.shape, 255.0, dtype=np.float32)]).astype(np.uint8)

    depth = bg - luma
    alpha_bg = np.clip((depth - 12.0) / 24.0, 0.0, 1.0)
    sat = patch.max(axis=-1) - patch.min(axis=-1)
    alpha_sat = np.clip((sat - 10.0) / 22.0, 0.0, 1.0)
    alpha = np.maximum(alpha_bg, alpha_sat)
    alpha = np.where(alpha < 0.10, 0.0, alpha)
    return np.dstack([patch, alpha * 255.0]).astype(np.uint8)


def build_item(patch: np.ndarray, item: dict, out_dir: Path, tile: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    before = seam_score(patch)
    before_ratio = seam_ratio(patch)
    patch = flatten_lighting(patch)
    # only repair a genuinely broken seam; the criterion is the wrap/interior
    # ratio, not the absolute border difference (a high-frequency tile has a
    # large and correct border difference; blending it makes the wrap worse)
    if tile and before_ratio > 1.5 and before > 0.02:
        patch = seamless(patch)
    after = seam_score(patch)

    if item["kind"] == "decal":
        card = trim_black_frame(patch)
        if item.get("full_bleed"):
            keyed = np.dstack([card, np.full(card.shape[:2], 255.0, dtype=np.float32)]
                              ).astype(np.uint8)
        else:
            keyed = key_white_to_alpha(card)
            # crop to the graphic's own bounds: a decal filling half its card
            # wastes half the texel budget and misaligns when projected
            mask = keyed[..., 3] > 12
            ys, xs = np.where(mask)
            if len(ys) and len(xs):
                y0, y1 = ys.min(), ys.max()
                x0, x1 = xs.min(), xs.max()
                pad = int(max(y1 - y0, x1 - x0) * 0.04) + 1
                h, w = mask.shape
                y0, y1 = max(0, y0 - pad), min(h, y1 + pad)
                x0, x1 = max(0, x0 - pad), min(w, x1 + pad)
                keyed = keyed[y0:y1, x0:x1]
            # pad to square, never stretch: a wide mark forced into a square tile
            # changes its proportions
            kh, kw = keyed.shape[:2]
            side = max(kh, kw)
            canvas = np.zeros((side, side, 4), dtype=np.uint8)
            oy, ox = (side - kh) // 2, (side - kw) // 2
            canvas[oy:oy + kh, ox:ox + kw] = keyed
            keyed = canvas
        rgba = Image.fromarray(keyed).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
        rgba.save(out_dir / "albedo.png")
        flat = np.asarray(rgba.convert("RGB"), dtype=np.float32)
    else:
        img = Image.fromarray(patch.astype(np.uint8)).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
        img.save(out_dir / "albedo.png")
        flat = np.asarray(img, dtype=np.float32)
    albedo = flat
    Image.fromarray(normal_map(albedo, 1.0 if item.get("emissive") else 1.3)).save(out_dir / "normal.png")
    Image.fromarray(roughness_map(albedo, item.get("metal", 0.0), item.get("emissive", False))).save(
        out_dir / "roughness.png")
    m = np.full((OUT_SIZE, OUT_SIZE), int(item.get("metal", 0.0) * 255), dtype=np.uint8)
    Image.fromarray(m).save(out_dir / "metallic.png")
    if item.get("emissive"):
        Image.fromarray(emissive_map(albedo)).save(out_dir / "emissive.png")

    meta = {
        "id": item["id"], "kind": item["kind"], "faction": item.get("faction"),
        "slot": item.get("slot"), "prompt": item.get("prompt"),
        "tileable": tile, "tileable_before": round(before, 4), "tileable_after": round(after, 4),
        "tileable_ratio_before": round(before_ratio, 3), "tileable_ratio_after": round(seam_ratio(patch), 3),
        "size": OUT_SIZE, "metallic_constant": item.get("metal", 0.0),
        "tile_m": item.get("tile_m", 1.0),
        "emissive": bool(item.get("emissive")), "maps": ["albedo", "normal", "roughness", "metallic"]
        + (["emissive"] if item.get("emissive") else []),
        "derived": "normal/roughness from albedo (tools/pbr/derive_maps.py); not model-generated",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sheet", help="override sheet path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    items = {i["id"]: i for i in manifest["items"]}
    batches = manifest["batches"]
    if args.batch:
        batches = [b for b in batches if b["batch"] == args.batch]
        if not batches:
            print(f"no batch {args.batch}", file=sys.stderr)
            return 2
    elif not args.all:
        print("specify --batch N or --all", file=sys.stderr)
        return 2

    built = 0
    for b in batches:
        if args.sheet:
            sheet_path = Path(args.sheet)
        else:
            stem = Path(b["sheet"]).with_suffix("")
            candidates = sorted(stem.parent.glob(stem.name + "*.png"))
            sheet_path = candidates[-1] if candidates else Path(b["sheet"])
        if not sheet_path.exists():
            print(f"skip batch {b['batch']}: no sheet at {sheet_path}")
            continue
        if args.dry_run:
            print(f"batch {b['batch']}: would build {', '.join(b['items'])}")
            continue
        patch_list = crop_quadrants(load_rgb(sheet_path))
        for idx, item_id in enumerate(b["items"]):
            item = items[item_id]
            tile = item["kind"] != "decal"
            meta = build_item(patch_list[idx], item, LIB / item_id, tile=tile)
            built += 1
            print(f"  {item_id}: seam {meta['tileable_before']:.3f} -> {meta['tileable_after']:.3f}")
    if not args.dry_run:
        print(f"built {built} material(s) under {LIB}")
        if built and built < sum(len(b['items']) for b in batches):
            print("note: some items had no sheet yet — generate them with assets/materials/grimdark_scifi/generate.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
