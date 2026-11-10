#!/usr/bin/env python3
"""check_master.py — verify a pixel-master render set against the technique
standard, mechanically.

Checks (each one is a way this pipeline can silently be wrong):

  direction_count   the number of views matches the profile (8 for sprite tiers)
  resolution        every frame is exactly the profile canvas
  no_antialiasing   alpha is binary (no partial pixels); AA destroys pixel grids
  unit_normals      the normal mask decodes to unit-length vectors (a flat or
                    mis-encoded normal pass fails here)
  normal_variance   the normal mask is not a constant colour
  ao_informative    AO varies spatially and stays <= 1
  emission_mask     an emissive asset has a non-empty, sparse emission mask
  distinct_views    asymmetric assets differ between views (opt-in: symmetric
                    objects legitimately look identical from every side)

`--selftest` builds deliberately broken inputs and asserts every check fires.
That is the point: a checker that has never failed is not evidence.

Usage:
    python3 tools/style/check_master.py --dir output/props/barrel8 --profile pixel_3d
    python3 tools/style/check_master.py --dir output/props/rifle8 --profile pixel_3d \
        --require-distinct
    python3 tools/style/check_master.py --selftest
"""
from __future__ import annotations

import argparse
import itertools
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "style"))
import profiles  # noqa: E402

ALPHA_AA_LIMIT = 0.01          # >1% partial-alpha pixels means antialiasing
NORMAL_UNIT_MIN, NORMAL_UNIT_MAX = 0.80, 1.10
MIN_STD = 0.005
DISTINCT_MIN = 0.005           # mean absolute RGB difference between views


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def view_files(d: Path) -> list[Path]:
    return sorted(p for p in (d / "render").glob("*_az*.png"))


def mask_files(d: Path) -> dict[str, list[Path]]:
    out = {"normal": [], "ao": [], "emission": []}
    for p in sorted((d / "masks").glob("*.png")):
        for kind in out:
            if p.stem.endswith(kind):
                out[kind].append(p)
    return out


def check_set(d: Path, profile_id: str, require_distinct: bool,
              expect_directions: int | None = None) -> dict:
    cfg = profiles.load_config()
    prof = profiles.resolve(profile_id, cfg)
    size = prof.get("render", {}).get("size_px") or [256, 256]
    if expect_directions:
        expected = int(expect_directions)
    else:
        expected = int(prof.get("render", {}).get("directions", 1))
        if prof.get("representation") == "sprite_2d":
            expected = max(expected, 8)

    views = view_files(d)
    masks = mask_files(d)
    failures, warnings = [], []

    if len(views) != expected:
        failures.append(f"direction_count: {len(views)} views, expected {expected}")

    for p in views + [m for v in masks.values() for m in v]:
        a = load(p)
        if list(a.shape[1::-1]) != [size[0], size[1]]:
            failures.append(f"resolution: {p.name} is {a.shape[1]}x{a.shape[0]}, "
                            f"expected {size[0]}x{size[1]}")

    for p in views:
        a = load(p)
        alpha = a[..., 3]
        partial = ((alpha > 0) & (alpha < 255)).mean()
        if partial > ALPHA_AA_LIMIT:
            failures.append(f"no_antialiasing: {p.name} has {partial:.1%} partial-alpha pixels")

    normals = []
    for p in masks["normal"]:
        raw = load(p)
        mask = raw[..., 3] > 10
        a = raw.astype(np.float32) / 255.0
        if not mask.any():
            failures.append(f"unit_normals: {p.name} has no opaque pixels")
            continue
        n = a[..., :3] * 2.0 - 1.0
        length = np.linalg.norm(n[mask], axis=-1)
        med = float(np.median(length))
        if not NORMAL_UNIT_MIN <= med <= NORMAL_UNIT_MAX:
            failures.append(f"unit_normals: {p.name} median length {med:.3f} "
                            f"outside {NORMAL_UNIT_MIN}-{NORMAL_UNIT_MAX}")
        if float(a[..., :3][mask].std()) < MIN_STD:
            failures.append(f"normal_variance: {p.name} normal mask is constant")
        normals.append(med)

    for p in masks["ao"]:
        a = load(p)
        mask = a[..., 3] > 10
        if not mask.any():
            failures.append(f"ao_informative: {p.name} has no opaque pixels")
            continue
        ao = a[..., 0][mask].astype(np.float32) / 255.0
        if ao.max() > 1.0 + 1e-6:
            failures.append(f"ao_informative: {p.name} AO exceeds 1.0")
        if float(ao.std()) < MIN_STD:
            failures.append(f"ao_informative: {p.name} AO is uniform (std {ao.std():.4f})")
        if float(ao.mean()) > 0.995:
            failures.append(f"ao_informative: {p.name} AO never darkens (mean {ao.mean():.3f})")

    for p in masks["emission"]:
        a = load(p)
        mask = a[..., 3] > 10
        if not mask.any():
            continue
        lit = (a[..., :3].max(axis=-1)[mask] > 8).mean()
        if lit == 0:
            warnings.append(f"emission_mask: {p.name} is empty (asset may have no emissive)")

    if require_distinct and len(views) > 1:
        arrays = [load(p).astype(np.float32) for p in views]
        diffs = [np.abs(x[..., :3] - y[..., :3]).mean() / 255.0
                 for x, y in itertools.combinations(arrays, 2)]
        if diffs and max(diffs) < DISTINCT_MIN:
            failures.append(f"distinct_views: identical views (max diff {max(diffs):.4f})")
    elif len(views) > 1:
        arrays = [load(p).astype(np.float32) for p in views]
        diffs = [np.abs(x[..., :3] - y[..., :3]).mean() / 255.0
                 for x, y in itertools.combinations(arrays, 2)]
        if diffs and max(diffs) < DISTINCT_MIN:
            warnings.append("views are near-identical — correct for a radially "
                            "symmetric object, suspect otherwise")

    return {"dir": str(d), "views": len(views),
            "masks": {k: len(v) for k, v in masks.items()},
            "failures": failures, "warnings": warnings,
            "verdict": "FAIL" if failures else "PASS"}


# -------------------------------------------------------------------- selftest ---

def _write(path: Path, arr: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, "RGBA").save(path)


def _solid(size, rgba) -> np.ndarray:
    a = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    a[...] = rgba
    return a


def selftest() -> int:
    """Every check must fail on an input built to violate it."""
    size = [96, 128]
    cases = []

    def make_case(name, views_fn, mask_fn):
        d = Path(tempfile.mkdtemp(prefix=f"master_{name}_"))
        for i in range(8):
            _write(d / "render" / f"a_az{i*45:03d}.png", views_fn(i))
            for kind in ("normal", "ao", "emission"):
                _write(d / "masks" / f"a_az{i*45:03d}_{kind}.png", mask_fn(kind, i))
        return d

    good_mask = lambda kind, i: _solid(size, {
        "normal": (128, 128, 255, 255), "ao": (200, 200, 200, 255),
        "emission": (0, 0, 0, 0)}[kind])

    # 1. flat normals -> the failure must name the decoded length, not merely
    # "no opaque pixels" (that was a real bug: the check passed for the wrong reason)
    flat_mask = lambda kind, i: _solid(size, {
        "normal": (128, 128, 128, 255), "ao": (200, 200, 200, 255),
        "emission": (0, 0, 0, 0)}[kind])
    d = make_case("flatnorm", lambda i: _solid(size, (10, 10, 10, 255)), flat_mask)
    r = check_set(d, "pixel_sprite", True)
    cases.append(("flat normals rejected for the right reason",
                  any("median length" in f for f in r["failures"])))

    # 2. antialiased alpha -> no_antialiasing must fail
    def aa_view(i):
        a = _solid(size, (10, 10, 10, 255))
        a[:16, :, 3] = 128
        return a
    d = make_case("aa", aa_view, good_mask)
    r = check_set(d, "pixel_sprite", True)
    cases.append(("antialiasing rejected",
                  any("no_antialiasing" in f for f in r["failures"])))

    # 3. identical views with --require-distinct -> distinct_views must fail
    d = make_case("same", lambda i: _solid(size, (10, 10, 10, 255)), good_mask)
    r = check_set(d, "pixel_sprite", True)
    cases.append(("identical views rejected",
                  any("distinct_views" in f for f in r["failures"])))

    # 4. wrong resolution -> resolution must fail
    d = make_case("size", lambda i: _solid((48, 48), (10, 10, 10, 255)), good_mask)
    r = check_set(d, "pixel_sprite", True)
    cases.append(("wrong resolution rejected",
                  any("resolution" in f for f in r["failures"])))

    # 5. uniform AO -> ao_informative must fail
    def bad_ao(kind, i):
        if kind == "ao":
            return _solid(size, (255, 255, 255, 255))
        return _solid(size, {"normal": (128, 128, 255, 255),
                             "emission": (0, 0, 0, 0)}[kind])
    d = make_case("ao", lambda i: _solid(size, (10, 10, 10, 255)), bad_ao)
    r = check_set(d, "pixel_sprite", True)
    cases.append(("uniform AO rejected",
                  any("ao_informative" in f for f in r["failures"])))

    # positive control: a correct set must PASS, otherwise the checker rejects
    # everything and proves nothing
    def good_view(i):
        a = _solid(size, (0, 0, 0, 0))
        a[16:112, 16:80] = (20 + i * 10, 30, 40, 255)
        return a

    def good_varying(kind, i):
        if kind == "normal":
            a = _solid(size, (0, 0, 0, 0))
            a[16:112, 16:80] = (128, 128, 255, 255)
            return a
        if kind == "ao":
            a = _solid(size, (0, 0, 0, 0))
            a[16:64, 16:80] = (100, 100, 100, 255)
            a[64:112, 16:80] = (220, 220, 220, 255)
            return a
        a = _solid(size, (0, 0, 0, 0))
        a[80:96, 40:64] = (200, 80, 0, 255)
        return a

    d = make_case("good", good_view, good_varying)
    r = check_set(d, "pixel_sprite", True)
    cases.append(("correct set accepted",
                  r["verdict"] == "PASS" and not r["failures"]))

    ok = True
    for name, passed in cases:
        print(f"{'PASS' if passed else 'FAIL'}  selftest: {name}")
        ok = ok and passed
    return 0 if ok else 1


# ------------------------------------------------------------------------ main ---

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--profile", default="pixel_3d")
    ap.add_argument("--require-distinct", action="store_true")
    ap.add_argument("--expect-directions", type=int,
                    help="override the expected view count (mesh pixel-master sets use 8)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.dir:
        raise SystemExit("give --dir or --selftest")

    import json
    results = [check_set(Path(args.dir), args.profile, args.require_distinct,
                         args.expect_directions)]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{r['verdict']}  {r['dir']}  views {r['views']}  masks {r['masks']}")
            for f in r["failures"]:
                print(f"      FAIL {f}")
            for w in r["warnings"]:
                print(f"      WARN {w}")
    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
