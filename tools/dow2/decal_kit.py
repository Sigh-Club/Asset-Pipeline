#!/usr/bin/env python3
"""decal_kit.py — the ground decal palette, taken from the maps' own decal records.

A shipped map paints 350-800 decals over its terrain: snow slabs, cracks, rubble, road markings,
stains, craters. They are the layer that makes ground read as worn and used rather than as a plane
with props on it, and they are a third of what a map is made of (measured: 349 per map against 68
props).

`scenario_decode.py` decodes each decal's record (name, position, size, rotation). This resolves the
names to the shipped textures and writes the palette the forge renders from, ordered by how often the
corpus uses each one.

Usage:
    python3 tools/dow2/decal_kit.py --maps output/source_lab/maps \
        --out ../Imperium-of-Ash/frontend/public/assets/decals [--art <sga root>] [--min-uses 1]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def art_roots(explicit: Path | None) -> list[Path]:
    roots = []
    if explicit:
        roots.append(explicit)
    env = os.environ.get("DOW2_RETRIB")
    if env:
        roots.append(Path(env).expanduser())
    return [r for r in roots if r.is_dir()]


def resolve_decal(roots: list[Path], name: str) -> Path | None:
    """A decal's material path to its shipped diffuse texture.

    Measured layout: a decal named `nm_snow/snow_slab_01` ships as
    `DATA/art/terrain_textures/splats/nm_snow/snow_slab_01_dif.dds`, with `_nrm` and `_spc` beside it.
    """
    rel = Path(name.replace("\\", "/"))
    for root in roots:
        for base in (root / "sga", root, root / "sga_art"):
            if not base.is_dir():
                continue
            direct = base.rglob(f"{rel.name}_dif.dds")
            for hit in direct:
                if "terrain_textures" in str(hit).replace("\\", "/"):
                    return hit
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=Path, default=ROOT / "output/source_lab/maps")
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/decals")
    ap.add_argument("--art", type=Path, default=None)
    ap.add_argument("--min-uses", type=int, default=1,
                    help="only export decals the corpus uses at least this many times")
    ap.add_argument("--max-size", type=int, default=512, help="texture edge cap, px")
    a = ap.parse_args(argv)

    uses: Counter[str] = Counter()
    sizes: dict[str, list[float]] = {}
    maps = 0
    for path in sorted(a.maps.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        decals = data.get("decals") or []
        if decals:
            maps += 1
        for decal in decals:
            name = decal.get("name") or ""
            if not name:
                continue
            uses[name] += 1
            span = sizes.setdefault(name, [1e9, 0.0])
            span[0] = min(span[0], min(decal.get("size") or [1.0, 1.0]))
            span[1] = max(span[1], max(decal.get("size") or [1.0, 1.0]))

    roots = art_roots(a.art)
    if not roots:
        raise SystemExit("set DOW2_RETRIB to the unpacked DoW2 data (or pass --art)")
    from PIL import Image

    a.out.mkdir(parents=True, exist_ok=True)
    palette = []
    missing = []
    for name, count in uses.most_common():
        if count < a.min_uses:
            continue
        dds = resolve_decal(roots, name)
        if dds is None:
            missing.append(name)
            continue
        stem = name.replace("\\", "/").replace("/", "__")
        dest = a.out / f"{stem}.png"
        if not dest.exists():
            try:
                image = Image.open(dds).convert("RGBA")
                if max(image.size) > a.max_size:
                    image.thumbnail((a.max_size, a.max_size))
                image.save(dest)
            except Exception as exc:  # a broken texture is reported, not silently dropped
                print(f"  SKIP {name}: {exc}", file=sys.stderr)
                missing.append(name)
                continue
        lo, hi = sizes.get(name, [1.0, 1.0])
        palette.append({
            "name": name,
            "url": f"/assets/decals/{dest.name}",
            "uses": count,
            "size_m": [round(lo, 2), round(hi, 2)],
        })

    manifest = a.out / "decal_kit.json"
    manifest.write_text(json.dumps({
        "generated_by": "asset-pipeline/tools/dow2/decal_kit.py",
        "note": ("The ground decals the shipped maps paint, with the corpus's usage count and the "
                 "size range each is drawn at. A decal is a ground patch (name, position, size, "
                 "rotation) decoded from SCEN/GEWD/TERR/TTEX/COMP/RCSP/SPLT; this palette is the "
                 "texture side of that layer."),
        "decals": palette,
        "unresolved": missing[:40],
    }, indent=1))
    total = sum(p["uses"] for p in palette)
    print(f"{maps} maps, {len(uses)} distinct decals used {sum(uses.values())} times")
    print(f"{len(palette)} exported ({total} uses), {len(missing)} unresolved -> {manifest}")
    for entry in palette[:8]:
        print(f"  {entry['name'][:44]:44s} x{entry['uses']:4d} size {entry['size_m']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
