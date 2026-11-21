#!/usr/bin/env python3
"""check_unit_scale.py — the scale gate: a shipped unit must match its declared height.

A unit whose exported height does not match its declared height makes every cover read wrong: in a
tabletop cover game the silhouette height *is* the tactical read. Measured on the 45 built units, 19
disagreed with `HEIGHTS_M` by more than 0.25 m (worst: a 1.50 m gaunt shipped at 3.51 m, a 5.00 m
Night Bringer at 7.01 m), because the scale step measured an armature-deformed mesh's undeformed bounds.

This gate reads the GLB's own vertex bounds and compares them to the declared height. It measures the
bind pose: a creature whose idle pose raises a weapon or talon above its head measures taller when
posed, which is why the tolerance is 0.25 m rather than a few centimetres. Anything beyond that is a
scaling defect, not a pose.

Usage:
    python3 tools/dow2/check_unit_scale.py --lab ../Imperium-of-Ash/frontend/public/assets/models/units/lab
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOLERANCE_M = 0.25


def declared_heights() -> dict[str, float]:
    src = (ROOT / "tools/dow2/build_community_units.py").read_text()
    block = re.search(r"HEIGHTS_M: dict\[str, float\] = \{(.*?)\n\}", src, re.S)
    out: dict[str, float] = {}
    for line in block.group(1).split("\n"):
        line = line.split("#")[0]
        for name, value in re.findall(r'"([a-z0-9_]+)": ([0-9.]+)', line):
            out[name] = float(value)
    return out


def glb_height(path: Path) -> float | None:
    data = path.read_bytes()
    off, js = 12, None
    while off < len(data):
        length, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8:off + 8 + length]
        if kind == 0x4E4F534A:
            js = json.loads(chunk.decode("utf8").rstrip("\x00 "))
        off += 8 + length
    if not js:
        return None
    lo, hi = 1e9, -1e9
    for mesh in js.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            accessor = js["accessors"][primitive["attributes"]["POSITION"]]
            if "min" not in accessor or "max" not in accessor:
                continue
            lo = min(lo, accessor["min"][1])
            hi = max(hi, accessor["max"][1])
    return hi - lo if hi > -1e8 else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/models/units/lab")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE_M)
    a = ap.parse_args(argv)

    declared = declared_heights()
    rows, failures = [], []
    for path in sorted(a.lab.glob("dow_*.glb")):
        unit = path.stem
        if unit not in declared:
            continue
        measured = glb_height(path)
        if measured is None:
            failures.append((unit, declared[unit], None))
            continue
        delta = measured - declared[unit]
        rows.append((unit, declared[unit], measured, delta))
        if abs(delta) > a.tolerance:
            failures.append((unit, declared[unit], measured))

    rows.sort(key=lambda r: -abs(r[3]))
    print(f"{'unit':32s} {'declared':>9s} {'shipped':>9s} {'delta':>7s}")
    for unit, want, got, delta in rows[:20]:
        print(f"{unit:32s} {want:9.2f} {got:9.2f} {delta:+7.2f}")
    print(f"\n{len(rows) - len(failures)}/{len(rows)} units within {a.tolerance:.2f} m of their declared height")
    if failures:
        print(f"FAIL: {len(failures)} unit(s) out of scale")
        return 1
    print("PASS: every shipped unit matches its declared height")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
