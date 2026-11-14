#!/usr/bin/env python3
"""part_catalogue.py — measure the reference part library.

P1 of the kit method: before authoring parts we need to know what the reference
library actually contains and what each slot costs. Scans the extracted DoW2 art,
classifies each model by slot from its path, and writes a catalogue with measured
triangle counts and bounding boxes.

Usage:
  python3 tools/dow2/part_catalogue.py --out output/part_catalogue.json \
      [--sga /path/to/sga] [--races race_marine,race_chaos,...]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunky_mesh as C  # noqa: E402

DEFAULT_SGA = Path("/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/sga")
SLOTS = ("armour", "head", "helm", "shoulder", "pauldron", "backpack", "weapon",
         "gun", "sword", "claws", "shield")

# Faction-specific part names that carry no slot word: ork ranged wargear is named
# after the weapon ("shoota", "deffgun", "rokkit"), not after the slot, so those
# files landed in "other" and the ork kit read as almost weaponless.
SLOT_SYNONYMS = {
    "gun": ("shoota", "slugga", "deffgun", "rokkit", "burna", "zzap", "blasta",
            "lobba", "kannon", "kustom", "dakka"),
    "sword": ("choppa", "claw", "big_choppa", "power_klaw", "weirdboy_staff"),
    "armour": ("body", "wargear_body"),
    "backpack": ("pole", "trophy", "banner"),
}


def classify(name: str) -> str:
    low = name.lower()
    for slot in SLOTS:
        if slot in low:
            return slot
    for slot, words in SLOT_SYNONYMS.items():
        if any(w in low for w in words):
            return slot
    return "other"


def measure(path: Path):
    try:
        blob = path.read_bytes()
        root = C.parse(blob)
    except Exception:
        return None
    payloads = []

    def walk(chunk):
        if chunk.type == "DATADATA" and chunk.version == 7:
            payloads.append(blob[chunk.data_offset:chunk.file_offset + chunk.size])
        for kid in chunk.children:
            walk(kid)

    walk(root)
    tris = 0
    verts = 0
    lo = [9e9] * 3
    hi = [-9e9] * 3
    for payload in payloads:
        try:
            decoded = C.decode_geometry(payload)
        except Exception:
            continue
        if not decoded:
            continue
        pos, subs = decoded
        verts += len(pos)
        tris += sum(len(s["indices"]) // 3 for s in subs)
        for p in pos:
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    if not tris:
        return None
    return {"file": path.name, "tris": tris, "verts": verts,
            "dims": [round(hi[i] - lo[i], 2) for i in range(3)]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sga", default=str(DEFAULT_SGA))
    ap.add_argument("--out", default="output/part_catalogue.json")
    ap.add_argument("--races", default="race_marine,race_chaos,race_eldar,race_tyranid,race_ig,race_ork")
    args = ap.parse_args(argv)

    root = Path(args.sga)
    if not root.is_dir():
        raise SystemExit(f"missing extracted art at {root}")

    catalogue = {"source": str(root), "races": {}}
    for race in [r.strip() for r in args.races.split(",") if r.strip()]:
        files = sorted(root.glob(f"**/{race}/**/*.model"))
        if not files:
            print(f"{race:16s} 0 models (not extracted)")
            continue
        slots = defaultdict(list)
        for f in files:
            m = measure(f)
            if not m:
                continue
            slots[classify(f.name)].append(m)
        entry = {}
        for slot, items in sorted(slots.items()):
            tris = sorted(i["tris"] for i in items)
            entry[slot] = {
                "count": len(items),
                "tris_min": tris[0],
                "tris_median": tris[len(tris) // 2],
                "tris_max": tris[-1],
                "examples": [i["file"] for i in items[:5]],
            }
        catalogue["races"][race] = entry
        summary = ", ".join(f"{s}:{v['count']}" for s, v in sorted(entry.items()))
        print(f"{race:16s} {len(files):4d} models  {summary}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(catalogue, indent=1) + "\n")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
