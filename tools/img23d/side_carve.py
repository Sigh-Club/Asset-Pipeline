#!/usr/bin/env python3
"""side_carve.py — pass 4: pose-registered carving from true side photos.

Front carving (sculpt_detail.py) is blind to x-facing surfaces. This tool
carves the mesh's +/-x faces using the side-view photos:

  1. register photo -> mesh side projection (moments init, ECC refine,
     mirrored candidate; silhouette IoU picks the winner)
  2. render the mesh from +/-x with f3d (ortho), map into the same projection
     space, and pick the camera side by edge-capture against the photo
  3. warp the photo into mesh space, high-pass it, displace x-facing vertices
     along the camera axis (same rule as sculpt_detail => tiles stay seamless)
  4. re-render, re-audit; exit 1 if capture did not rise

The audit is the honest render-edge one: photo edges covered by render edges
in the shared projection space. Front is +z, up is +y, side axis x (certified,
HANDOFF_IMG23D.md). Requires the repo venv (cv2, trimesh) and f3d on PATH.

Usage:
  side_carve.py mesh.glb --left l.png --right r.png            # carve in place
  side_carve.py mesh.glb --left l.png --audit-only             # baseline only
  side_carve.py mesh.glb --left l.png --strength 0.03 --out carved.glb
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw

AXIS = 0        # side axis: x (front z, up y)
REG = 256       # registration raster
RES = 960       # carve/audit grid (matches sculpt_detail's 960-wide front grid)
F3D = "f3d"


# ---------------------------------------------------------------- photos ----

def photo_data(path: Path):
    """Return (mask, grey) cropped to the alpha bbox, longest side = REG."""
    im = Image.open(path).convert("RGBA")
    arr = np.asarray(im)
    mask0 = arr[:, :, 3] > 128
    ys, xs = np.where(mask0)
    pad = max(xs.max() - xs.min(), ys.max() - ys.min()) // 20
    x0, x1 = max(0, xs.min() - pad), min(im.width, xs.max() + pad)
    y0, y1 = max(0, ys.min() - pad), min(im.height, ys.max() + pad)
    im = im.crop((x0, y0, x1, y1))
    arr = np.asarray(im)
    mask = arr[:, :, 3] > 128
    grey = np.asarray(im.convert("L"), float) / 255
    scale = REG / max(mask.shape)
    size = (max(1, int(mask.shape[1] * scale)), max(1, int(mask.shape[0] * scale)))
    mask = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.NEAREST)) > 128
    grey = np.asarray(Image.fromarray((grey * 255).astype(np.uint8)).resize(size, Image.LANCZOS), float) / 255
    return mask, grey


# ---------------------------------------------------------------- mesh ------

def _plane_bounds(m):
    pts = m.vertices[:, [2, 1]]  # (z, y)
    lo, hi = pts.min(0), pts.max(0)
    pad = 0.02 * (hi - lo)
    return lo - pad, hi + pad


def _project(pts, lo, hi, shape):
    """(z,y) -> (col,row) image coords, row inverted."""
    col = ((pts[:, 0] - lo[0]) / (hi[0] - lo[0]) * (shape[1] - 1)).astype(int).clip(0, shape[1] - 1)
    row = ((1 - (pts[:, 1] - lo[1]) / (hi[1] - lo[1])) * (shape[0] - 1)).astype(int).clip(0, shape[0] - 1)
    return col, row


def mesh_silhouette(m, size=REG):
    """Ortho silhouette raster; col = z, row = y inverted (image convention)."""
    lo, hi = _plane_bounds(m)
    col, row = _project(m.vertices[:, [2, 1]], lo, hi, (size, size))
    img = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(img)
    uv = np.stack([col, row], 1)
    for tri in m.faces:
        dr.polygon([tuple(uv[i]) for i in tri], fill=255)
    return np.asarray(img) > 128, lo, hi


# ---------------------------------------------------------------- reg -------

def _moments(mask):
    ys, xs = np.where(mask)
    p = np.stack([xs, ys], 1).astype(float)
    mu = p.mean(0)
    c = np.cov((p - mu).T) + 1e-6 * np.eye(2)
    return mu, np.linalg.cholesky(c)


def similarity_init(src, dst) -> np.ndarray:
    """Affine src-pixel -> dst-pixel from silhouette moments."""
    mu_s, l_s = _moments(src)
    mu_d, l_d = _moments(dst)
    a = l_d @ np.linalg.inv(l_s)
    m = np.eye(3)
    m[:2, :2] = a
    m[:2, 2] = mu_d - a @ mu_s
    return m


def _mask_iou(src_mask, dst_mask, m):
    warped = cv2.warpAffine(src_mask.astype(np.float32), m[:2], (dst_mask.shape[1], dst_mask.shape[0])) > 0.5
    return (warped & dst_mask).sum() / max((warped | dst_mask).sum(), 1), warped


def register_all(src_mask, dst_mask, tag="") -> dict:
    """src -> dst warps for both parities; ECC-refined. Returns {flip: M}."""
    dst_blur = cv2.GaussianBlur(dst_mask.astype(np.float32), (0, 0), 3)
    out = {}
    for flip in (False, True):
        src = src_mask[:, ::-1] if flip else src_mask
        m = similarity_init(src, dst_mask).astype(np.float32)
        try:
            _, m2 = cv2.findTransformECC(
                dst_blur, cv2.GaussianBlur(src.astype(np.float32), (0, 0), 3), m[:2].copy(),
                cv2.MOTION_AFFINE,
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
            m = np.vstack([m2, [0, 0, 1]])
        except cv2.error as e:
            print(f"    ECC failed ({e}); moments init only", file=sys.stderr)
        m = np.asarray(m, np.float64)
        if flip:
            f = np.array([[-1, 0, src_mask.shape[1] - 1], [0, 1, 0], [0, 0, 1]], np.float64)
            m = m @ f
        iou, _ = _mask_iou(src_mask, dst_mask, m)
        print(f"    registration{tag} flip={flip}: IoU {iou:.3f}")
        out[flip] = m
    return out


# ---------------------------------------------------------------- render ----

def render_side(mesh_path: Path, sign: int, workdir: Path, res: int = RES):
    """Ortho render from sign*x via f3d. Returns (grey, mask)."""
    out = workdir / f"render_{'p' if sign > 0 else 'm'}x.png"
    cmd = [
        F3D, str(mesh_path), "--output", str(out), "--no-background",
        "--camera-orthographic", "--camera-position", f"{5 * sign},0,0",
        "--camera-focal-point", "0,0,0", "--camera-view-up", "0,1,0",
        "--resolution", f"{res},{res}", "--filename=0", "--light-intensity", "1.5",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    im = np.asarray(Image.open(out).convert("RGBA"))
    alpha = im[:, :, 3] > 128
    # keep only the largest blob: f3d draws an orientation gizmo in a corner
    n, labels, stats, _ = cv2.connectedComponentsWithStats(alpha.astype(np.uint8), 8)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha = labels == big
    mask = alpha
    rgb = im[:, :, :3].astype(float)
    grey = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]) / 255
    grey = np.where(mask, grey, 0)
    return grey, mask


def render_to_plane(grey_r, mask_r, sign):
    """Map a square render into plane space via mask bbox (ortho => exact).

    Parity is deterministic: camera at +x with +y up puts -z on screen-right
    (mirrored); camera at -x does not.
    """
    shape = (RES, RES)
    ys, xs = np.where(mask_r)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    sx = (shape[1] - 1) / (x1 - x0)
    sy = (shape[0] - 1) / (y1 - y0)
    if sign > 0:  # mirrored: u runs opposite
        m = np.array([[-sx, 0, shape[1] - 1 + sx * x0],
                      [0, sy, -sy * y0], [0, 0, 1]], np.float64)
    else:
        m = np.array([[sx, 0, -sx * x0], [0, sy, -sy * y0], [0, 0, 1]], np.float64)
    grey_m = cv2.warpAffine(grey_r.astype(np.float32), m[:2], (shape[1], shape[0]),
                            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mask_m = cv2.warpAffine(mask_r.astype(np.float32), m[:2], (shape[1], shape[0])) > 0.5
    return grey_m, mask_m


# ---------------------------------------------------------------- audit -----

def gradmag(a):
    gy, gx = np.gradient(a)
    return np.hypot(gx, gy)


def dilate(mask, r=4):
    return cv2.dilate(mask.astype(np.uint8) * 255, np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0


def edge_capture(photo_grey, photo_mask, mesh_grey, mesh_mask):
    """Capture: photo edges covered by render edges (both in plane space)."""
    inside = photo_mask & cv2.erode(mesh_mask.astype(np.uint8) * 255, np.ones((5, 5), np.uint8)).astype(bool)

    def edges(g, m):
        g = cv2.GaussianBlur(g, (0, 0), 2)  # tame sub-pixel carve fringes
        e = gradmag(g)
        e = e / (np.percentile(e[m], 97) + 1e-9)
        return (e > 0.30) & m

    pe = edges(photo_grey, photo_mask & np.isfinite(photo_grey))
    me = edges(mesh_grey, mesh_mask)
    capture = 100 * (pe & dilate(me)).sum() / max(pe.sum(), 1)
    spurious = 100 * (me & dilate(pe)).sum() / max(me.sum(), 1)
    return capture, spurious, me, pe


# ---------------------------------------------------------------- carve -----

def highpass(img, blur):
    """Centred, contrast-boosted high-pass; +0.5 protrude, -0.5 recess."""
    p = np.pad(img, blur, mode="edge")
    acc = np.zeros_like(img)
    n = 0
    for dy in range(0, 2 * blur + 1, 2):
        for dx in range(0, 2 * blur + 1, 2):
            acc += p[dy:dy + img.shape[0], dx:dx + img.shape[1]]
            n += 1
    return np.clip((img - acc / n) * 4, -0.5, 0.5)


def carve_pass(m, photo960, sign, strength, blur, nthresh, lo, hi):
    """Displace axis-facing verts by the warped-photo high-pass. In place ok."""
    shape = photo960.shape
    fn, faces = m.face_normals, m.faces
    vn = np.zeros(len(m.vertices))
    cnt = np.zeros(len(m.vertices))
    np.add.at(vn, faces.ravel(), np.repeat(fn[:, AXIS] * sign, 3))
    np.add.at(cnt, faces.ravel(), 1)
    w = np.clip((vn / np.maximum(cnt, 1) - nthresh + 0.2) / 0.3, 0, 1)

    col, row = _project(m.vertices[:, [2, 1]], lo, hi, shape)
    disp = strength * highpass(photo960, blur)[row, col] * w

    out = m.copy()
    v = m.vertices.copy()
    v[:, AXIS] += sign * disp
    out.vertices = v
    return out, float(np.abs(disp).max()), int((w > 0.01).sum())


# ---------------------------------------------------------------- main ------

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("--left", type=Path, default=None)
    p.add_argument("--right", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--strength", type=float, default=0.02,
                   help="max displacement, model units (0.01 ~= 3mm at panel scale)")
    p.add_argument("--blur", type=int, default=9)
    p.add_argument("--nthresh", type=float, default=0.35, help="min axis-normal to carve")
    p.add_argument("--audit-only", action="store_true")
    p.add_argument("--audit-dir", type=Path, default=None)
    p.add_argument("--swap-signs", action="store_true",
                   help="photos named against the convention (default: left=-x, right=+x)")
    a = p.parse_args()

    views = {k: v for k, v in dict(left=a.left, right=a.right).items() if v}
    if not views:
        sys.exit("give --left and/or --right")

    workdir = Path(tempfile.mkdtemp(prefix="side_carve_"))
    audit_dir = a.audit_dir or a.mesh.parent
    audit_dir.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(a.mesh, force="mesh", process=True)

    # registration, per view (photo -> 256 sil, scaled to RES for carve/audit)
    sil, lo, hi = mesh_silhouette(m)
    scale = RES / sil.shape[0]
    S = np.diag([scale, scale, 1.0])
    prep = {}
    for name, path in views.items():
        print(f"[side-carve] view {name}: {path.name}")
        mask, grey = photo_data(path)
        Hs = register_all(mask, sil)
        per_flip = {}
        for flip, H in Hs.items():
            Hres = S @ H
            photo = cv2.warpPerspective(grey.astype(np.float32), Hres.astype(np.float32),
                                        (RES, RES), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_REPLICATE)
            pmask = cv2.warpPerspective(mask.astype(np.float32), Hres.astype(np.float32),
                                        (RES, RES)) > 0.5
            per_flip[flip] = (photo, pmask)
        prep[name] = dict(per_flip=per_flip)

    # camera side + parity + baseline audit. Sign convention (verified on the
    # photos: front content appears on the right in left.png, left in right.png):
    # left view => camera -x, right view => camera +x. --swap-signs overrides.
    signs = dict(left=-1, right=1)
    if a.swap_signs:
        signs = {k: -v for k, v in signs.items()}
    renders = {}
    for s in set(signs.values()):
        g, mk = render_side(a.mesh, s, workdir)
        renders[s] = render_to_plane(g, mk, s)
    for name, d in prep.items():
        s = signs[name]
        g_r, m_r = renders[s]
        best = None
        for flip, (photo, pmask) in d["per_flip"].items():
            cap, spur, me, pe = edge_capture(photo, pmask, g_r, m_r)
            print(f"    flip={flip}: capture {cap:.1f}% (spurious {spur:.1f}%)")
            if best is None or cap > best[1]:
                best = (cap, spur, me, pe, flip, photo, pmask)
        (d["cap0"], d["spur0"], d["me0"], d["pe0"],
         d["flip"], d["photo"], d["pmask"]) = best
        d["sign"] = s
        print(f"[side-carve] {name}: baseline capture {d['cap0']:.1f}% "
              f"(spurious {d['spur0']:.1f}%, sign {'+x' if s > 0 else '-x'}, "
              f"flip={d['flip']})")
        _audit_png(d["pe0"], d["me0"], audit_dir / f"side_audit_{name}_pre.png")

    if a.audit_only:
        return 0

    # carve
    for name, d in prep.items():
        m, moved, touched = carve_pass(m, d["photo"], d["sign"], a.strength, a.blur,
                                       a.nthresh, lo, hi)
        print(f"    carved {name} ({'+' if d['sign'] > 0 else '-'}x): "
              f"max {moved:.4f} units on {touched} verts")

    # post audit: re-render both sides, re-map, compare
    tmp = workdir / "carved.glb"
    m.export(tmp)
    ok_all = True
    for s in (1, -1):
        g, mk = render_side(tmp, s, workdir)
        renders[s] = render_to_plane(g, mk, s)
    for name, d in prep.items():
        g_r, m_r = renders[d["sign"]]
        cap, spur, me, pe = edge_capture(d["photo"], d["pmask"], g_r, m_r)
        delta = cap - d["cap0"]
        ok = delta > 0
        ok_all &= ok
        print(f"[side-carve] {name}: capture {d['cap0']:.1f} -> {cap:.1f}% "
              f"({delta:+.1f}pp) {'PASS' if ok else 'FAIL'}")
        _audit_png(pe, me, audit_dir / f"side_audit_{name}_post.png")

    out = a.out or a.mesh
    m.export(out)
    print(f"[side-carve] wrote {out}")
    return 0 if ok_all else 1


def _audit_png(photo_edges, mesh_edges, path):
    overlay = np.zeros((*photo_edges.shape, 3), np.uint8)
    overlay[..., 1] = photo_edges * 255  # green: photo (wanted)
    overlay[..., 0] = mesh_edges * 160   # red: mesh render (got)
    Image.fromarray(overlay).save(path)
    print(f"[side-carve] audit overlay (green=photo, red=render) -> {path}")


if __name__ == "__main__":
    sys.exit(main())
