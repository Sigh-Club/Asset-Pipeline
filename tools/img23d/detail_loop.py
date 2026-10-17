#!/usr/bin/env python3
"""detail_loop.py — closed-loop detail recovery: scan, repair, verify, repeat.

Per the user spec:
  1. SCAN   audit_regions-style: per-cell capture (reference detail present in
     the mesh) and spurious (mesh detail the reference can't explain)
  2. REPAIR cells below target get a region-locked, normal-directed carve;
     amplitude scales with the deficit, hard-capped
  3. GUARD  a pass is kept only if mean capture rises AND no cell's spurious
     rises >CHISEL_PP -- the over-chisel brake. On rejection the amplitude
     halves once; on second rejection the loop stops.
  4. repeats until every cell passes, iterations exhaust, or amplitudes die

Final mesh exports as STL (printer contract) + the last audit heatmap.

Run under the repo venv (cv2/trimesh) with f3d on PATH; the mesh must be
front=+z, unit-normalised (see trellis_run notes / trel_norm.glb).

Usage:
  detail_loop.py master.glb reference.jpg --stl out.stl --target 70 --max-iters 4
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
from PIL import Image

RES = 1024


# ---------------------------------------------------------------- audit -----

def render_front(mesh_path: Path, workdir: Path):
    out = workdir / "f.png"
    subprocess.run(
        ["f3d", str(mesh_path), "--output", str(out), "--no-background",
         "--camera-orthographic", "--camera-position", "0,0,5",
         "--camera-focal-point", "0,0,0", "--camera-view-up", "0,1,0",
         "--resolution", f"{RES},{RES}", "--filename=0",
         "--light-intensity", "1.2"],
        check=True, capture_output=True)
    im = np.asarray(Image.open(out).convert("RGBA"))
    alpha = im[:, :, 3] > 128
    n, labels, stats, _ = cv2.connectedComponentsWithStats(alpha.astype(np.uint8), 8)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha = labels == big
    rgb = im[:, :, :3].astype(float)
    g = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255
    return np.where(alpha, g, np.nan), alpha


def edge_set(g, mask, pct=80):
    g = np.nan_to_num(g, nan=0)
    e = cv2.GaussianBlur(g, (0, 0), 1.2)
    gy, gx = np.gradient(e)
    m = np.hypot(gx, gy)
    t = np.percentile(m[mask], pct) if mask.any() else 1e9
    return (m > t) & mask


def dilate(mask, r=4):
    return cv2.dilate(mask.astype(np.uint8) * 255, np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0


def audit(mesh_path: Path, ref: np.ndarray, ref_mask: np.ndarray, ty: int, tx: int,
          workdir: Path):
    mesh_g, mesh_mask = render_front(mesh_path, workdir)
    pe = edge_set(ref, ref_mask)
    me = edge_set(mesh_g, mesh_mask & np.isfinite(mesh_g))
    cap = np.zeros((ty, tx))
    spur = np.zeros((ty, tx))
    for r in range(ty):
        for c in range(tx):
            cell = np.zeros((RES, RES), bool)
            cell[int(RES * r / ty):int(RES * (r + 1) / ty),
                 int(RES * c / tx):int(RES * (c + 1) / tx)] = True
            rc = pe & cell
            mc = me & cell
            cap[r, c] = 100 * (rc & dilate(me)).sum() / max(rc.sum(), 1)
            spur[r, c] = 100 * (mc & ~dilate(pe)).sum() / max(mc.sum(), 1)

    heat = np.zeros((RES, RES, 3), np.uint8)
    heat[..., 1] = np.where(pe & dilate(me), 200, 0)
    heat[..., 0] = np.where(pe & ~dilate(me), 220, 0)
    heat[..., 2] = np.where(me & ~dilate(pe), 90, 0)
    for r in range(1, ty):
        heat[int(RES * r / ty)] = 70
    for c in range(1, tx):
        heat[:, int(RES * c / tx)] = 70
    return cap, spur, heat, (pe, me)


# ---------------------------------------------------------------- carve -----

def highpass(img, blur):
    p = np.pad(img, blur, mode="edge")
    acc = np.zeros_like(img)
    n = 0
    for dy in range(0, 2 * blur + 1, 2):
        for dx in range(0, 2 * blur + 1, 2):
            acc += p[dy:dy + img.shape[0], dx:dx + img.shape[1]]
            n += 1
    return np.clip((img - acc / n) * 4, -0.5, 0.5)


def carve(mesh: trimesh.Trimesh, ref_img: np.ndarray, cell_mask: np.ndarray,
          amp: float, cell_amp: np.ndarray = None, blur: int = 6) -> trimesh.Trimesh:
    """Normal-directed hp carve limited to cell_mask (feathered), amp units.

    cell_amp: optional per-cell multiplier map (ty,tx) -- cells near target
    get ~0 amplitude so healthy surface is never re-chiselled (the sand fix).
    """
    v = mesh.vertices.copy()
    x, y = v[:, 0], v[:, 1]
    R = 1920
    nx, ny = R, int(R * (y.max() - y.min()) / (x.max() - x.min()))
    art = np.asarray(Image.fromarray((ref_img * 255).astype(np.uint8)).resize(
        (nx, ny), Image.LANCZOS), float) / 255
    art = cv2.GaussianBlur(art, (0, 0), 1.2)
    hp = highpass(art, blur)

    msk = np.kron(cell_mask, np.ones((ny // RES + 1, nx // RES + 1)))[:ny, :nx]
    msk = np.array(Image.fromarray((msk * 255).astype(np.uint8)).resize((nx, ny))) / 255
    if cell_amp is not None:
        am = np.kron(cell_amp, np.ones((ny // RES + 1, nx // RES + 1)))[:ny, :nx]
        am = np.array(Image.fromarray((am * 255).astype(np.uint8)).resize((nx, ny))) / 255
    else:
        am = np.ones_like(msk)

    col = ((x - x.min()) / (x.max() - x.min()) * (nx - 1)).astype(int).clip(0, nx - 1)
    row = (ny - 1 - ((y - y.min()) / (y.max() - y.min()) * (ny - 1)).astype(int).clip(0, ny - 1))
    n = np.asarray(mesh.vertex_normals)
    w = np.clip((n[:, 2] - 0.1) / 0.4, 0, 1)
    disp = amp * (hp[row, col] * msk[row, col] * am[row, col]) * w
    v += n * disp[:, None]
    out = mesh.copy()
    out.vertices = v
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("reference", type=Path)
    p.add_argument("--stl", type=Path, required=True)
    p.add_argument("--target", type=float, default=70.0, help="per-cell capture goal %%")
    p.add_argument("--chisel-pp", type=float, default=2.0,
                   help="max spurious rise per cell per accepted pass")
    p.add_argument("--max-amp", type=float, default=0.005,
                   help="cell repair cap, model units (0.003 = 1mm)")
    p.add_argument("--max-iters", type=int, default=4)
    p.add_argument("--grid", nargs=2, type=int, default=(4, 4))
    p.add_argument("--outdir", type=Path, default=None)
    a = p.parse_args()
    ty, tx = a.grid
    outdir = a.outdir or a.mesh.parent
    outdir.mkdir(parents=True, exist_ok=True)

    ref = np.asarray(Image.open(a.reference).convert("L").resize(
        (RES, RES), Image.LANCZOS), float) / 255

    cur = a.mesh
    best_cap = None
    amp = a.max_amp
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for it in range(1, a.max_iters + 1):
            cap, spur, heat, _ = audit(cur, ref, np.isfinite(ref), ty, tx, tdp)
            Image.fromarray(heat).save(outdir / f"loop_audit_it{it}.png")
            fail = cap < a.target
            mean, sp = cap.mean(), spur.mean()
            print(f"[loop] it{it}: mean capture {mean:.1f}% spurious {sp:.1f}% "
                  f"failing {fail.sum()}/{ty * tx}", flush=True)
            if best_cap is None or mean > best_cap:
                best_cap = mean
                keep = cur

            if not fail.any():
                print("[loop] all cells pass -- converged", flush=True)
                break

            # repair: failing cells masked; per-cell amplitude ~ deficit so
            # near-target cells get ~0.15x (anti-sand: no blanket re-chisel)
            cell_mask = np.zeros((RES, RES), bool)
            amap = np.zeros((ty, tx))
            dmax = max((a.target - cap).max(), 1e-6)
            for r in range(ty):
                for c in range(tx):
                    if cap[r, c] < a.target:
                        cell_mask[int(RES * r / ty):int(RES * (r + 1) / ty),
                                  int(RES * c / tx):int(RES * (c + 1) / tx)] = True
                    amap[r, c] = 0.15 + 0.85 * ((a.target - cap[r, c]) / dmax)
            deficit = np.clip((a.target - cap[fail].mean()) / 100 * 2, 0.3, 1.0)
            cand = carve(trimesh.load(cur, force="mesh", process=True), ref,
                         cell_mask, amp * deficit, cell_amp=amap)

            cand_path = tdp / "cand.glb"
            cand.export(cand_path)
            cap2, spur2, _, _ = audit(cand_path, ref, np.isfinite(ref), ty, tx, tdp)
            d_cap = cap2.mean() - cap.mean()
            d_spur = (spur2 - spur).max()
            ok = d_cap > 0 and d_spur <= a.chisel_pp
            print(f"[loop] cand: capture {d_cap:+.2f}pp, worst spurious {d_spur:+.2f}pp "
                  f"-> {'KEEP' if ok else 'REJECT'}", flush=True)
            if ok:
                cur = cand_path
                cur_out = outdir / f"loop_iter{it}.glb"
                cand.export(cur_out)
                cur = cur_out
                amp = a.max_amp  # restore full strength on success
            else:
                amp /= 2
                if amp < 0.0008:
                    print("[loop] amplitude floor -- stopping", flush=True)
                    break
        else:
            pass

    # final: best snapshot, STL for the printer
    final = trimesh.load(keep, force="mesh", process=True)
    final.export(a.stl)
    print(f"[loop] DONE best mean capture {best_cap:.1f}% -> {a.stl}", flush=True)


if __name__ == "__main__":
    main()
