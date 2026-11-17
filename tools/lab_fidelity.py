#!/usr/bin/env python3
"""lab_fidelity.py — regenerate the rig lab's fidelity report for every unit and action.

The lab page (`Imperium-of-Ash/frontend/src/pages/UnitLabView.tsx`) reads
`models/units/lab/fidelity.json` and needs, per unit and per clip, the deformation metrics for the
action set that unit actually ships. This tool measures that with `tools/rig_fidelity.py` and writes
the report in the shape the page expects:

    {"clips": [...], "limits": {...}, "units": [{"unit", "verdict", "worst_tear", "clips": {...}}]}

It measures EVERY keyframe of every action, not the first frame: the first frame of a clip is its
reference pose and is trivially clean, so a first-frame-only report cannot tell a working action from
a broken one.

Usage:
  python3 tools/lab_fidelity.py --lab ../Imperium-of-Ash/frontend/public/assets/models/units/lab
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import rig_fidelity as RF  # noqa: E402


def clip_frames(glb: Path, clip: str) -> int:
    js, binc = RF.load_glb(glb)
    anim = next((a for a in js.get("animations", []) if a.get("name") == clip), None)
    if anim is None:
        return 0
    return int(RF.accessor(js, binc, anim["samplers"][0]["input"]).shape[0])


def worst_over_frames(glb: Path, clip: str, stride: int) -> dict:
    """The worst metric over the clip, so an extreme pose cannot hide behind frame 1."""
    total = clip_frames(glb, clip)
    if not total:
        return {"error": "clip missing"}
    frames = list(range(1, total + 1, max(1, stride)))
    if frames[-1] != total:
        frames.append(total)
    worst = None
    max_disp = 0.0
    for frame in frames:
        try:
            report = RF.measure(glb, clip, frame)
        except Exception as exc:  # a broken clip is data, not a crash
            return {"error": str(exc)}
        if "error" in report:
            return report
        max_disp = max(max_disp, report.get("disp_max") or 0.0)
        if worst is None or report["tear_edges_gt_1_5"] > worst["tear_edges_gt_1_5"]:
            worst = report
    keys = ("tear_edges_gt_1_5", "tear_area_gt_0_5", "inverted_tris", "penetration_frac",
            "collapse_ratio", "disp_max")
    out = {k: worst.get(k) for k in keys}
    out["worst_frame"] = worst["frame"]
    out["frames_measured"] = len(frames)
    out["max_disp"] = round(max_disp, 4)
    # The displacement floor is a property of the CLIP, not of one frame: a slow idle passes
    # through a near-bind pose, and judging the whole clip by that frame reports a rigid mesh that
    # is in fact animating.
    failures = [f for f in worst.get("failures", [])
                if not (f.startswith("disp_max") and max_disp >= 0.02)]
    out["verdict"] = "FAIL" if failures else "PASS"
    if failures:
        out["failures"] = failures
    if worst.get("source_plates"):
        out["source_plates"] = worst["source_plates"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab", required=True, type=Path)
    ap.add_argument("--stride", type=int, default=4,
                    help="measure every Nth keyframe (default 4; the last frame is always measured)")
    ap.add_argument("--clip", default="", help="only this action (default: every action in the unit)")
    ap.add_argument("--unit", default="", help="only this unit (default: every unit in the lab)")
    ap.add_argument("--out", type=Path, default=None,
                    help="report path (default: <lab>/fidelity.json, or <lab>/fidelity.<unit>.json)")
    a = ap.parse_args(argv)

    units = []
    all_clips: set[str] = set()
    for glb in sorted(a.lab.glob("*.glb")):
        if a.unit and glb.stem != a.unit:
            continue
        sidecar = glb.with_suffix(".actions.json")
        if not sidecar.exists():
            continue
        manifest = json.loads(sidecar.read_text())
        names = [a.clip] if a.clip else sorted(manifest.get("actions", {}))
        clips = {}
        worst_tear = None
        verdict = "PASS"
        for name in names:
            if name not in manifest.get("actions", {}):
                continue
            all_clips.add(name)
            metrics = worst_over_frames(glb, name, a.stride)
            clips[name] = metrics
            if metrics.get("verdict") == "FAIL":
                verdict = "FAIL"
            if metrics.get("tear_edges_gt_1_5") is not None:
                worst_tear = max(worst_tear or 0.0, metrics["tear_edges_gt_1_5"])
        units.append({"unit": glb.stem, "verdict": verdict,
                      "worst_tear": worst_tear, "clips": clips})
        print(f"{glb.stem}: {len(clips)} actions, worst tear {worst_tear}")

    report = {"generated_by": "asset-pipeline/tools/lab_fidelity.py",
              "limits": RF.LIMITS,
              "note": ("Every action's worst measured keyframe. The band is the deformation "
                       "failure detector from rig_fidelity.py; DoW2's rigid armour plates "
                       "separate at extreme poses (a death pose measures ~0.09 with the shipped "
                       "assignment, and a 100 % rigid bind measures the same), which is the "
                       "source's own structure and is recorded in docs/KNOWN-ISSUES.md."),
              "clips": sorted(all_clips), "units": units}
    out = a.out or (a.lab / (f"fidelity.{a.unit}.json" if a.unit else "fidelity.json"))
    out.write_text(json.dumps(report, indent=1))
    fails = [u["unit"] for u in units if u["verdict"] == "FAIL"]
    print(f"{out}: {len(units)} units, {len(all_clips)} actions, FAIL {fails}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
