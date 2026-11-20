#!/usr/bin/env python3
"""ground_library.py — index DoW2's terrain materials into a biome ground library.

The game's ground is painted from `DATA/art/terrain_textures/`: `layers/` (the base ground material),
`tiles/` (the tiling detail), `splats/` (the decal and blend layers — craters, roads, flora, stains)
and `grass/` (blade descriptors). The shipped maps reference these by name, so the library is the
vocabulary a biome recipe is written in.

Nothing here invents a material: every entry is a shipped file, converted to PNG for the pipeline, and
the index records where it came from, its size and its mean colour (the colour is what makes a biome
recipe reproducible — two biomes that both use `nm_flora` are the same ground with different props).

Usage:
  python3 tools/dow2/ground_library.py --art <sga root> --out output/source_lab/ground_library.json
  python3 tools/dow2/ground_library.py --art <sga root> --biome desert
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dow2"))

ART_ENV = "DOW2_RETRIB"

# The folder a material lives in names the biome it belongs to. These are the shipped folder names;
# several are duplicated per biome (the same crater decal ships in desert/jungle/urban folders).
BIOME_BY_FOLDER = {
    "nm_desert_splats": "desert", "desert": "desert", "desert_craters": "desert",
    "nm_snow": "ice", "nm_snow_urban": "ice", "snow": "ice", "ice": "ice",
    "nm_flora": "jungle", "flora": "jungle", "jungle": "jungle", "jungle_craters": "jungle",
    "nm_urban_splats": "urban", "nm_urban_markings": "urban", "nm_roads": "urban",
    "urban": "urban", "urban_craters": "urban", "red_stone": "urban",
    "nm_volcanic": "volcanic", "volcanic": "volcanic",
    "nm_spacehulk": "spacehulk", "spacehulk": "spacehulk", "metal": "spacehulk",
    "nm_stone_natural": "natural", "stone": "natural", "stone_natural": "natural",
    "nm_rubble": "ruins", "rubble": "ruins",
    "nm_craters": "decal", "nm_stains": "decal", "crater": "decal", "chaos": "chaos",
    "tyrannoformation": "tyranid", "dirt": "generic", "sand": "desert",
    "default_textures": "generic", "layers": "generic", "grass": "generic",
}
KIND_BY_DIR = {"layers": "cubemap", "tiles": "tile", "splats": "splat", "grass": "grass"}


def art_root() -> Path:
    base = os.environ.get(ART_ENV)
    if not base:
        raise SystemExit(f"set {ART_ENV} to the unpacked DoW2 data")
    root = Path(base).expanduser()
    return root / "sga_art" if (root / "sga_art").is_dir() else root


def terrain_dirs(root: Path) -> list[Path]:
    """Every extracted terrain_textures directory (they live under several data archives)."""
    out = []
    for base in (root / "sga", root):
        if base.is_dir():
            out.extend(sorted(p for p in base.rglob("terrain_textures") if p.is_dir()))
    return out


def classify(path: Path, terrain_root: Path) -> dict | None:
    rel = path.relative_to(terrain_root)
    parts = rel.parts
    if not parts:
        return None
    kind = KIND_BY_DIR.get(parts[0])
    if kind is None or path.suffix.lower() != ".dds":
        return None
    folder = parts[1] if len(parts) > 2 else parts[0]
    suffix = path.stem.rsplit("_", 1)[-1].lower()
    if suffix not in ("dif", "nrm", "spc", "emi", "ocl", "tem", "drt"):
        suffix = "dif"
    # `layers/` holds one `cubemap.dds` per ground material variant (environment reflection probes,
    # named by the material folder, e.g. layers/dirt/dirt_light_01/.../cubemap.dds), not ground paint.
    if kind == "cubemap":
        suffix = "cubemap"
    return {"kind": kind, "folder": folder, "map": suffix,
            "biome": BIOME_BY_FOLDER.get(folder, "generic")}


def convert(dds: Path, out_dir: Path) -> Path | None:
    from PIL import Image
    dest = out_dir / f"{dds.stem}.png"
    if dest.exists():
        return dest
    try:
        im = Image.open(dds).convert("RGB")
    except Exception as exc:
        print(f"SKIP {dds.name}: {exc}", file=sys.stderr)
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    im.save(dest)
    return dest


def mean_colour(png: Path) -> list[int]:
    from PIL import Image
    import numpy as np
    im = Image.open(png).convert("RGB").resize((32, 32))
    return [int(v) for v in np.asarray(im).reshape(-1, 3).mean(axis=0).round()]


def build(root: Path, out_json: Path, tex_dir: Path) -> dict:
    library: dict[str, dict] = {}
    seen: set[tuple[str, str, str]] = set()
    for terrain_root in terrain_dirs(root):
        for dds in sorted(terrain_root.rglob("*.dds")):
            info = classify(dds, terrain_root)
            if info is None or info["map"] not in ("dif", "cubemap"):
                continue
            key = dds.stem if info["map"] == "dif" else f"{info['folder']}__{dds.parent.name}"
            if key in library:
                continue
            png = convert(dds, tex_dir)
            if png is None:
                continue
            library[key] = {
                "kind": info["kind"],
                "biome": info["biome"],
                "folder": info["folder"],
                "source": str(dds),
                "png": str(png.relative_to(ROOT)) if str(png).startswith(str(ROOT)) else str(png),
                "mean_rgb": mean_colour(png),
            }
    by_biome: dict[str, dict[str, int]] = {}
    for entry in library.values():
        by_biome.setdefault(entry["biome"], {}).setdefault(entry["kind"], 0)
        by_biome[entry["biome"]][entry["kind"]] += 1
    report = {
        "generated_by": "asset-pipeline/tools/dow2/ground_library.py",
        "note": ("DoW2's terrain materials, indexed by biome. `layer` is the base ground material, "
                 "`tile` the tiling detail, `splat` the decal/blend layer (craters, roads, flora, "
                 "stains), `grass` the blade descriptor set. Every entry is a shipped file; the "
                 "mean_rgb is measured from the texture so a biome recipe can be matched by colour."),
        "counts": {"materials": len(library), "by_biome": by_biome},
        "materials": dict(sorted(library.items())),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=1))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", type=Path, default=None, help="unpacked DoW2 data root")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "output/source_lab/ground_library.json")
    ap.add_argument("--tex", type=Path, default=ROOT / "output/source_lab/tex_terrain")
    ap.add_argument("--biome", default=None, help="list one biome's materials")
    a = ap.parse_args(argv)
    root = a.art or art_root()
    if not terrain_dirs(root):
        raise SystemExit(f"no terrain_textures under {root} — extract them first "
                         f"(extract_sga.py --all --match 'art/terrain_textures/')")
    report = build(root, a.out, a.tex)
    if a.biome:
        for name, entry in report["materials"].items():
            if entry["biome"] == a.biome:
                print(f"  {entry['kind']:5s} {name:44s} rgb{entry['mean_rgb']}")
        return 0
    print(f"{report['counts']['materials']} terrain materials -> {a.out}")
    for biome, kinds in sorted(report["counts"]["by_biome"].items()):
        detail = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
        print(f"  {biome:10s} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
