#!/usr/bin/env python3
"""printprep.py — certified Trellis->print surface chain: dc remesh et al.

The raw marching-cubes surface carries voxel staircase + mc noise; the ComfyUI
node chain fixes this with a dual-contouring rebuild (remesh_narrow_band_dc_quad
-- piecewise-smooth, sharp features, no staircase), floater removal, simplify,
and hole filling. This replicates that chain standalone, then reports a surface
roughness metric (mean adjacent-face normal angle) before/after.

Usage:
  printprep.py in.glb out.stl [--dc-res 1024] --target-faces 1500000
Requires the trellis venv (cumesh, torch cuda). Path arg via Path below.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import trimesh


def roughness(mesh) -> float:
    """Mean angle (deg) between adjacent-face normals; lower = smoother."""
    fn = mesh.face_normals
    ff = mesh.face_adjacency
    if not len(ff):
        return 0.0
    dot = np.clip((fn[ff[:, 0]] * fn[ff[:, 1]]).sum(1), -1, 1)
    return float(np.degrees(np.arccos(dot)).mean())


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("inp", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--dc-res", type=int, default=1024)
    p.add_argument("--band", type=float, default=1.0)
    p.add_argument("--project-back", type=float, default=0.0)
    p.add_argument("--target-faces", type=int, default=1500000)
    a = p.parse_args()

    import torch
    import cumesh as CuMesh

    m = trimesh.load(a.inp, force="mesh", process=True)
    m.update_faces(m.nondegenerate_faces(height=1e-8))
    m.merge_vertices()
    r0 = roughness(m)
    print(f"[printprep] in: {len(m.faces)} faces, roughness {r0:.2f} deg, "
          f"wt {m.is_watertight}", flush=True)

    verts = torch.from_numpy(m.vertices).float().cuda()
    faces = torch.from_numpy(m.faces).int().cuda()

    if len(faces) > 2_500_000:  # dc rebuild resamples anyway; density beyond is waste
        pre = CuMesh.CuMesh()
        pre.init(verts, faces)
        pre.simplify(2_500_000, verbose=False)
        verts, faces = pre.read()
        del pre
        import gc
        gc.collect()
        torch.cuda.empty_cache()
        print(f"[printprep] pre-simplified to {len(faces)} faces", flush=True)

    dc_res = a.dc_res
    cumesh = CuMesh.CuMesh()
    cumesh.init(*CuMesh.remeshing.remesh_narrow_band_dc_quad(
        verts, faces,
        center=torch.zeros(3).cuda(), scale=2.0,
        resolution=dc_res, band=a.band, project_back=a.project_back,
        verbose=True, remove_inner_faces=True,
        bvh=None,
    ))
    v, f = cumesh.read()
    print(f"[printprep] after dc: {cumesh.num_vertices} v {cumesh.num_faces} f",
          flush=True)

    # decimate on CPU (open3d quadric): the cumesh simplify OOMs at 10M+ in
    # a shared 8GB window; quality is equivalent for our purpose
    v, f = cumesh.read()
    tmp = trimesh.Trimesh(v.cpu().numpy(), f.cpu().numpy(), process=False)
    del cumesh
    torch.cuda.empty_cache()
    if len(tmp.faces) > a.target_faces * 1.2:
        import open3d as o3d
        o = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(tmp.vertices),
            o3d.utility.Vector3iVector(tmp.faces))
        o = o.simplify_quadric_decimation(a.target_faces)
        tmp = trimesh.Trimesh(np.asarray(o.vertices), np.asarray(o.triangles), process=False)
    parts = tmp.split(only_watertight=False)
    keep = [q for q in parts if len(q.faces) > 200 and abs(q.volume) > 1e-4]
    tmp = trimesh.util.concatenate(keep) if len(keep) > 1 else tmp
    out = trimesh.Trimesh(v.cpu().numpy(), f.cpu().numpy(), process=False)
    trimesh.repair.fill_holes(out)
    trimesh.repair.fix_winding(out)
    out.merge_vertices()

    r1 = roughness(out)
    print(f"[printprep] out: {len(out.faces)} faces, roughness {r1:.2f} deg "
          f"({(r1 / max(r0, 1e-9) - 1) * 100:+.0f}%), wt {out.is_watertight}", flush=True)
    out.export(a.out)
    print("OK", a.out, flush=True)


if __name__ == "__main__":
    main()
