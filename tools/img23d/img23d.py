#!/usr/bin/env python3
"""img23d — image-to-3D stage for the IoA asset pipeline.

Turns generated concept images into watertight-ish meshes (GLB/OBJ/STL) for
the sprite render pipeline or 3D printing. Two engines, shared venv:

  hunyuan  Tencent Hunyuan3D-2mini shape-only (default; best geometry, ~6 GB VRAM)
  triposr  Stability AI TripoSR (fast fallback, ~6 GB VRAM)

Usage:
  img23d.py concept.png                      # hunyuan -> out/<stem>/ 
  img23d.py a.png b.png --engine triposr     # batch
  img23d.py concept.png --resolution 320 --seed 1234

Requires tools/img23d/.venv (python3.12) — see docs/IMG23D.md. Run with the
venv python directly or ensure `.venv/bin` is first on PATH.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUNYUAN_REPO = HERE / "Hunyuan3D-2"
TRIPOSR_REPO = HERE / "TripoSR"

MC_RESOLUTION_DEFAULT = 256  # marching-cubes grid; 256 fits 8 GB, 320/384 tighter


def _ensure_venv() -> None:
    """Re-exec under the stage venv if we are not already in it."""
    venv_python = HERE / ".venv" / "bin" / "python"
    if Path(sys.executable).resolve() != venv_python.resolve() and venv_python.exists():
        os.execv(str(venv_python), [str(venv_python), __file__, *sys.argv[1:]])


def _maybe_remove_bg(image, force: bool):
    """Return an RGBA image with background removed. Rembg is optional —
    images that already have a real alpha channel skip it entirely."""
    from PIL import Image

    image = Image.open(image)
    has_alpha = image.mode == "RGBA" and image.getextrema()[3][0] < 250
    if has_alpha and not force:
        return image.convert("RGBA")
    try:
        from hy3dgen.rembg import BackgroundRemover
    except ImportError:
        print("[img23d] rembg unavailable; compositing on white instead", file=sys.stderr)
        canvas = Image.new("RGBA", image.size, (255, 255, 255, 255))
        canvas.alpha_composite(image.convert("RGBA"))
        return canvas
    return BackgroundRemover()(image)


def run_hunyuan(image_path: Path, out_dir: Path, args) -> None:
    sys.path.insert(0, str(HUNYUAN_REPO))
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: E402

    image = _maybe_remove_bg(image_path, args.no_rembg)
    model = args.hunyuan_model
    if args.hunyuan_subfolder:
        subfolder = args.hunyuan_subfolder
    else:
        subfolder = ("hunyuan3d-dit-v2-mini-turbo" if "mini" in model
                     else "hunyuan3d-dit-v2-0-turbo")
    print(f"[img23d] hunyuan: loading {model} [{subfolder}]")
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        model, subfolder=subfolder)

    kwargs = {}
    if args.steps:
        kwargs["steps"] = args.steps
    if args.seed is not None:
        kwargs["seed"] = args.seed
    if args.resolution:
        kwargs["resolution"] = args.resolution
    t0 = time.time()
    mesh = pipe(image=image, **kwargs)[0]
    print(f"[img23d] shape generated in {time.time() - t0:.1f}s")

    _export(mesh, out_dir, image_path.stem, args.formats, args.quiet)


def run_triposr(image_path: Path, out_dir: Path, args) -> None:
    tmp = out_dir / f".tsr_{image_path.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(TRIPOSR_REPO / "run.py"), str(image_path),
        "--device", "cuda:0",
        "--output-dir", str(tmp),
        "--model-save-format", "glb",
        "--mc-resolution", str(args.resolution or MC_RESOLUTION_DEFAULT),
    ]
    if args.no_rembg:
        cmd.append("--no-remove-bg")
    subprocess.run(cmd, check=True, cwd=TRIPOSR_REPO)

    import trimesh

    glbs = sorted(tmp.glob("*/0.glb")) or sorted(tmp.rglob("*.glb"))
    if not glbs:
        raise RuntimeError(f"TripoSR produced no mesh under {tmp}")
    mesh = trimesh.load(glbs[0], force="mesh", process=False)
    _export(mesh, out_dir, image_path.stem, args.formats, args.quiet)
    shutil.rmtree(tmp, ignore_errors=True)


def _export(mesh, out_dir: Path, stem: str, formats, quiet: bool) -> None:
    import trimesh

    out_dir.mkdir(parents=True, exist_ok=True)
    if not hasattr(mesh, "export"):  # hunyuan may return a scene-less list
        mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.th)

    watertight = bool(mesh.is_watertight)
    if not watertight and not quiet:
        print("[img23d] mesh NOT watertight — run the Blender 3D-Print Toolbox "
              "repair before printing (docs/IMG23D.md)")
    bounds = mesh.bounds
    size = (bounds[1] - bounds[0]).round(3)

    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        if fmt == "stl":
            # binary STL, no colour — the print/roundtrip format
            mesh.export(path, file_type="stl")
        else:
            mesh.export(path)
        print(f"[img23d] wrote {path}")
    print(f"[img23d] stats: verts={len(mesh.vertices)} faces={len(mesh.faces)} "
          f"watertight={watertight} bounds={size.tolist()} "
          f"components={mesh.body_count if hasattr(mesh, 'body_count') else '?'}")


def main() -> None:
    _ensure_venv()  # no-op when already running under .venv

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("image", nargs="+", type=Path, help="concept image(s)")
    p.add_argument("--engine", choices=["hunyuan", "triposr"], default="hunyuan")
    p.add_argument("--out", type=Path, default=None,
                   help="output dir (default: output/img23d/<image stem>)")
    p.add_argument("--resolution", type=int, default=None,
                   help=f"marching-cubes resolution (default {MC_RESOLUTION_DEFAULT})")
    p.add_argument("--steps", type=int, default=None, help="diffusion steps (hunyuan)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--hunyuan-model", default="tencent/Hunyuan3D-2mini",
                   help="HF repo id")
    p.add_argument("--hunyuan-subfolder", default=None,
                   help="shape-model subfolder (default: hunyuan3d-dit-v2-mini-turbo "
                        "for the -mini repo, hunyuan3d-dit-v2-0-turbo otherwise)")
    p.add_argument("--formats", nargs="+", default=["glb", "obj", "stl"],
                   choices=["glb", "obj", "stl"])
    p.add_argument("--no-rembg", action="store_true",
                   help="trust image alpha / skip background removal")
    p.add_argument("--quiet", action="store_true", help="suppress repair hints")
    args = p.parse_args()

    if not (HERE / ".venv").exists():
        sys.exit("missing tools/img23d/.venv — run: "
                 "python3.12 -m venv .venv && .venv/bin/pip install ... "
                 "(see docs/IMG23D.md)")

    for image in args.image:
        if not image.exists():
            sys.exit(f"no such image: {image}")
        out_dir = args.out or (HERE.parent.parent / "output" / "img23d" / f"{image.stem}-{args.engine}")
        runner = run_hunyuan if args.engine == "hunyuan" else run_triposr
        print(f"[img23d] {image.name} -> {out_dir} ({args.engine})")
        runner(image, out_dir, args)


if __name__ == "__main__":
    main()
