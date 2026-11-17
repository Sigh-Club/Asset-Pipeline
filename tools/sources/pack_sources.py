#!/usr/bin/env python3
"""pack_sources.py — package every shipped source file the DoW2 import needs.

The pipeline reads Dawn of War II's shipped data directly: `.model` geometry, `.hkx` clips,
`.dds` textures and the wargear blueprints that list a unit's parts. Requiring a DoW2 install to run
the tools is a barrier, so the exact subset a build needs is packaged here into a portable tree plus
a manifest, and published as a release asset.

The unpacked tree is laid out exactly as the tools expect, so `DOW2_RETRIB=<unpacked>` works with no
other change:

    <out>/attrib-decoded/wargear/...          the part lists (render_models)
    <out>/sga_art/<NNN_data>/DATA/art/...     geometry, clips, textures
    <out>/MANIFEST.json                       path, size, sha256 for every file

Usage:
  python3 tools/sources/pack_sources.py --out output/source_pack [--format tar.zst]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/dow2"))
import parts as PARTS  # noqa: E402

# The units the lab builds, and the exact files each one needs. This table is the contract; it is the
# same table as tools/build_source_lab_all.sh.
DEFAULT_UNITS = [
    ("dow_ig_guardsman", "race_imperial_guard/armor/flak_common.txt",
     "race_ig/troops/gaurdsman/animations/range_burst"),
    ("dow_chaos_sorcerer", "race_chaos/armor/survive/sorcerer_defying_death.txt",
     "race_chaos/troops/chaos_lord/animations/melee_blade_range_pistol"),
    ("dow_eldar_farseer", "race_eldar/armor/farseer_armor_common.txt",
     "race_eldar/troops/banshee/animations/melee_blade_range_pistol"),
    ("dow_ork_warboss", "race_ork/armor/war_boss_epic.txt",
     "race_ork/troops/boy/animations/dakka_deff_gun"),
    ("dow_tyranid_lictor", "race_tyranid/armor/lictor_common.txt",
     "race_tyranid/troops/carnifex/animations/talons_venomcannon"),
    ("dow_necron_overlord", "race_necron/armor/survive/nec_crown_tachyon.txt",
     "race_ig/troops/gaurdsman/animations/range_burst"),
]


# The shipped weapon model each lab unit carries, as a path suffix under the art root. The weapon
# is part of the shipped unit (its wargear names `render_models` for it), so a build that has the
# body but not the weapon cannot be 1:1.
WEAPON_MODELS = {
    "dow_ig_guardsman": "race_ig/troops_wargear/weapons_ranged/lasgun/lasgun.model",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(retrib: Path, art: Path):
    """Every file a build of these units reads, as (source, relative-destination) pairs."""
    want: dict[Path, Path] = {}

    def add(src: Path):
        if not src.is_file():
            return
        try:
            rel = src.relative_to(retrib)
        except ValueError:
            rel = Path("sga_art") / src.relative_to(art)
        want[src] = rel

    for _unit, wargear_rel, loadout_rel in DEFAULT_UNITS:
        wargear = retrib / "attrib-decoded/wargear/wargear/core" / wargear_rel
        add(wargear)
        found, _missing = PARTS.resolve(wargear, [art])
        for model in found:
            add(model)
            for dds in sorted(model.parent.glob("*_dif*.dds")):
                add(dds)
            for shared in sorted(model.parent.glob("../shared_textures/*_dif*.dds")):
                add(shared)
            for shared in sorted(model.parent.glob("../../shared_textures/*_dif*.dds")):
                add(shared)
        # The art tree nests race data under <NNN_data>/DATA/art, so the loadout directory is found
        # by suffix rather than by joining onto the root (joining silently collected zero clips).
        loadout = None
        leaf = Path(loadout_rel).name
        for cand in art.rglob(leaf):
            if cand.is_dir() and str(cand).replace("\\", "/").endswith("/" + loadout_rel):
                loadout = cand
                break
        if loadout is None:
            raise SystemExit(f"loadout directory not found for {loadout_rel}")
        for clip in sorted(loadout.rglob("*.hkx")):
            add(clip)
        weapon_rel = WEAPON_MODELS.get(_unit)
        if weapon_rel:
            for cand in art.rglob(Path(weapon_rel).name):
                if cand.is_file() and str(cand).replace("\\", "/").endswith("/" + weapon_rel):
                    add(cand)
                    for dds in sorted(cand.parent.glob("*_dif*.dds")):
                        add(dds)
                    break
        # The unit's own container and marker files carry the timed event table
        # (`FOLDEVCT`/`DATAEVNT` -> `FOLDACTC`/`DATAACTN`) and the attachment markers the action
        # library and the weapon bind read. Without them a build can pose a unit but cannot say
        # when an action fires.
        unit_dir = loadout.parents[1]
        for pattern in ("*.motiontree", "*.marker"):
            for extra in sorted(unit_dir.glob(pattern)):
                add(extra)
    return want


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrib", default="/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution")
    ap.add_argument("--art", default="")
    ap.add_argument("--out", default="output/source_pack")
    ap.add_argument("--format", default="tar.zst", choices=("tar.zst", "tar.gz", "none"))
    a = ap.parse_args(argv)
    retrib = Path(a.retrib)
    art = Path(a.art) if a.art else retrib / "sga_art"
    if not art.is_dir():
        raise SystemExit(f"DoW2 art not found at {art} — set --art or DOW2_RETRIB")

    out = Path(a.out)
    tree = out / "tree"
    if tree.exists():
        shutil.rmtree(tree)
    want = collect(retrib, art)
    entries = []
    for src, rel in sorted(want.items(), key=lambda kv: str(kv[1])):
        dest = tree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        entries.append({"path": rel.as_posix(), "size": dest.stat().st_size, "sha256": sha256(dest)})
    manifest = {
        "pack": "dow2-unit-sources",
        "version": 3,
        "generated_by": "tools/sources/pack_sources.py",
        "units": [u for u, _w, _l in DEFAULT_UNITS],
        "note": ("The exact subset of Dawn of War II's shipped data this pipeline reads: geometry, "
                 "clips, textures and the wargear part lists. Unpack and set DOW2_RETRIB to the "
                 "unpacked directory; no game install is needed."),
        "files": entries,
    }
    (tree / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    total = sum(e["size"] for e in entries)
    print(f"{len(entries)} files, {total/1e6:.1f} MB uncompressed")

    if a.format != "none":
        archive = out / f"dow2-unit-sources-v3.{a.format.split('.')[-1]}"
        if a.format == "tar.zst":
            cmd = f"tar -C {tree} -cf - . | zstd -19 -T0 -q -o {archive} -f"
        else:
            cmd = f"tar -C {tree} -czf {archive} ."
        subprocess.run(cmd, shell=True, check=True)
        print(f"archive {archive} ({archive.stat().st_size/1e6:.1f} MB)")
        print(f"sha256 {sha256(archive)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
