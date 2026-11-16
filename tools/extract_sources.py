#!/usr/bin/env python3
"""extract_sources.py — bulk-extract the Warhammer 40k model libraries on this machine.

We are building a Warhammer 40,000 world and overlaying XCOM's mechanics and animation
families on it. That needs the raw geometry and clips from every 40k source installed
here, catalogued, so the asset programme (`docs/game-design/WORLD_PROGRAMME.md`) can pick
from a real library instead of hand-authoring every prop.

Sources handled:
  * Dawn of War II - Retribution (Relic SGA + Chunky .model) — world objects and race
    models, plus the authored `.coverbox` cover volumes and animation `.hkx` counts.
  * Warhammer 40,000: Mechanicus (Unity) — meshes to OBJ and the animation clip names.

Outputs (gitignored, regenerable):
  assets/sources/dow2/<category>/<name>.obj
  assets/sources/mechanicus/<name>.obj
  assets/sources/manifest.json   (tracked: the catalogue of what exists)

Usage:
  python3 tools/extract_sources.py [--dow2] [--mechanicus] [--limit N] [--all]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "sources"
DOW2_GAME = Path("/run/media/talzanar/games/SteamLibrary/steamapps/common/Dawn of War II - Retribution")
DOW2_WORK = Path("/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution")
MECH = Path("/run/media/talzanar/games/SteamLibrary/steamapps/common/Mechanicus")
CHUNKY = ROOT / "tools" / "dow2" / "chunky_mesh.py"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def obj_stats(path: Path) -> dict:
    verts = tris = 0
    mn = [1e9] * 3
    mx = [-1e9] * 3
    try:
        with path.open() as fh:
            for line in fh:
                if line.startswith("v "):
                    verts += 1
                    for i, tok in enumerate(line.split()[1:4]):
                        v = float(tok)
                        mn[i] = min(mn[i], v)
                        mx[i] = max(mx[i], v)
                elif line.startswith("f "):
                    tris += 1
    except Exception:
        pass
    return {
        "verts": verts,
        "tris": tris,
        "dims": [round(mx[i] - mn[i], 3) if mx[i] > mn[i] else 0 for i in range(3)],
    }


def extract_dow2(limit: int | None, manifest: dict) -> None:
    """Decode DoW2 world-object and race models to OBJ, catalogued by category."""
    # 1. Make sure the art archives are unpacked (the logic extractor skips art by default).
    art_root = DOW2_WORK / "sga_art"
    if not art_root.exists():
        run([sys.executable, str(DOW2_WORK / "extract_sga.py"), "--all",
             "--match", r"(world_objects|race_)", "--out", str(art_root)], cwd=DOW2_WORK)
    # 2. Catalogue every .model we can see, from both the art extraction and the existing
    #    logic extraction (which already carries the race models).
    models: list[Path] = []
    for base in (art_root, DOW2_WORK / "sga"):
        if base.exists():
            models.extend(base.rglob("*.model"))
    seen: set[str] = set()
    entries = []
    for model in models:
        rel = str(model)
        key = model.name
        if key in seen:
            continue
        seen.add(key)
        if limit and len(entries) >= limit:
            break
        m = re.search(r"art/(world_objects|race_[a-z]+)/(.+?)/[^/]+\.model$", rel)
        category = m.group(2).split("/")[0] if m else "misc"
        family = m.group(1) if m else "misc"
        out_dir = OUT / "dow2" / family / category
        out_dir.mkdir(parents=True, exist_ok=True)
        obj = out_dir / (model.stem + ".obj")
        if not obj.exists():
            r = run([sys.executable, str(CHUNKY), str(model), "-o", str(obj)])
            if not obj.exists():
                continue
        coverbox = model.with_suffix(".coverbox")
        entries.append({
            "id": model.stem,
            "source": "dow2",
            "family": family,
            "category": category,
            "obj": str(obj.relative_to(ROOT)),
            "coverbox": coverbox.exists(),
            **obj_stats(obj),
        })
    manifest["dow2"] = {"count": len(entries), "models": entries}
    print(f"DoW2: {len(entries)} models decoded")


def extract_mechanicus(limit: int | None, manifest: dict) -> None:
    """Export Mechanicus meshes to OBJ and record the animation clip names."""
    try:
        import UnityPy  # noqa: F401
    except ImportError:
        print("Mechanicus: UnityPy not installed — skipping (pip install UnityPy)")
        manifest["mechanicus"] = {"count": 0, "note": "UnityPy missing"}
        return
    import UnityPy

    data = MECH / "Mechanicus_Data"
    out_dir = OUT / "mechanicus"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    clips: set[str] = set()
    files = sorted(data.glob("*.assets"))
    for f in files:
        try:
            env = UnityPy.load(str(f))
        except Exception:
            continue
        for o in env.objects:
            if o.type.name == "AnimationClip":
                try:
                    clips.add(o.read().m_Name)
                except Exception:
                    pass
            if o.type.name != "Mesh":
                continue
            if limit and len(entries) >= limit:
                break
            try:
                mesh = o.read()
                obj = out_dir / (mesh.m_Name.replace("/", "_") + ".obj")
                if not obj.exists():
                    obj.write_text(mesh.export())
            except Exception:
                continue
            entries.append({
                "id": mesh.m_Name,
                "source": "mechanicus",
                "obj": str(obj.relative_to(ROOT)),
                **obj_stats(obj),
            })
        if limit and len(entries) >= limit:
            break
    manifest["mechanicus"] = {"count": len(entries), "meshes": entries, "clips": sorted(clips)}
    print(f"Mechanicus: {len(entries)} meshes, {len(clips)} clip names")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dow2", action="store_true")
    ap.add_argument("--mechanicus", action="store_true")
    ap.add_argument("--all", action="store_true", help="every source")
    ap.add_argument("--limit", type=int, default=None, help="cap meshes per source (probes)")
    args = ap.parse_args()
    if not (args.dow2 or args.mechanicus or args.all):
        args.all = True
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"generated_by": "tools/extract_sources.py"}
    if args.all or args.dow2:
        extract_dow2(args.limit, manifest)
    if args.all or args.mechanicus:
        extract_mechanicus(args.limit, manifest)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"manifest: {OUT / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
