#!/usr/bin/env python3
"""action_motion.py — measure what each action in a built unit actually does, per frame.

The handoff's screening snippet samples frame 0 against the frame at 75 % of the clip, which
under-reports any action whose motion is front-loaded: measured on the Tau battlesuit's
`fb_fire_stand_2cannon`, first-vs-75 % gives 0.001 m ("static") while the clip's own tracks move the
shoulder 21.5 deg and the bones travel 0.282 m inside the first 20 frames — the recoil is over by
75 %. So this tool measures the peak over *every* frame pair, and reports the two numbers a
turn-based action system needs besides motion: the effect time (when the acting hand is fastest) and
the lowest mesh point on the Y (vertical) axis (whether the unit sinks through the floor).

Nothing here decides whether an action is *correct* — that is the render gate. It decides whether an
action is static (a build defect) or moving, and how it sits on the ground.

Usage:
  python3 tools/dow2/action_motion.py <unit.glb> [--json]
  python3 tools/dow2/action_motion.py --lab <dir> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import rig_fidelity as R  # noqa: E402

STATIC_METRES = 0.02


def measure_action(js, binc, action, joints, names) -> dict:
    times = R.accessor(js, binc, action["samplers"][0]["input"]).ravel()
    hand_joints = [i for i in joints
                   if any(k in names[i].lower() for k in ("r hand", "l hand", "weapon"))]
    peak = 0.0
    peak_joint = ""
    hand_peak = 0.0
    effect_time = 0.0
    lowest = 9e9
    previous = None
    base = None
    for t in times:
        worlds = R.node_worlds(js, R.sample_clip(js, binc, action["name"], float(t)))
        if base is None:
            base = worlds
        for k in joints:
            travel = float(np.linalg.norm(worlds[k][:3, 3] - base[k][:3, 3]))
            if travel > peak:
                peak, peak_joint = travel, names[k]
        hand = [worlds[k][:3, 3] for k in hand_joints]
        if previous is not None:
            speed = max(float(np.linalg.norm(h - p)) for h, p in zip(hand, previous))
            if speed > hand_peak:
                hand_peak, effect_time = speed, float(t)
        previous = hand
        parts = R.skin_parts(js, binc, worlds)
        if parts:
            lowest = min(lowest, min(float(p["skinned"][:, 1].min()) for p in parts))
    return {
        "action": action["name"],
        "frames": int(len(times)),
        "duration": round(float(times[-1]), 3),
        "peak_bone_travel_m": round(peak, 3),
        "peak_bone": peak_joint,
        "peak_hand_speed_m_per_frame": round(hand_peak, 4),
        "effect_time_s": round(effect_time, 3),
        "lowest_mesh_y_m": round(lowest, 3),
        "static": peak < STATIC_METRES,
    }


def measure_unit(glb: Path) -> dict:
    js, binc = R.load_glb(glb)
    joints = js["skins"][0]["joints"]
    names = {i: js["nodes"][i].get("name", "") for i in joints}
    parts = R.skin_parts(js, binc, R.node_worlds(js))
    # the GLB is Y-up (a guardsman's body spans y 0.01..2.39; x and z are its width and depth), so
    # the ground and height axis is Y. Blender's importer converts to Z-up, the file does not.
    ys = np.concatenate([p["rest"][:, 1] for p in parts]) if parts else np.array([0.0, 1.0])
    height = float(ys.max() - ys.min())
    actions = [measure_action(js, binc, a, joints, names) for a in js["animations"]]
    return {"unit": glb.stem, "height_m": round(height, 2), "actions": actions}


def report(unit: dict) -> None:
    print(f"{unit['unit']}  height {unit['height_m']} m")
    for a in unit["actions"]:
        flag = "  STATIC" if a["static"] else ""
        ground = ""
        if a["lowest_mesh_y_m"] < -0.05:
            ground = f"  {abs(a['lowest_mesh_y_m']):.2f} m below the origin"
        print(f"  {a['action']:14s} {a['frames']:4d}f {a['duration']:5.2f}s  "
              f"peak {a['peak_bone_travel_m']:5.3f} m ({a['peak_bone']})  "
              f"hand peak {a['peak_hand_speed_m_per_frame']:.3f} m/f at {a['effect_time_s']:5.2f}s"
              f"{flag}{ground}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", nargs="?", type=Path)
    ap.add_argument("--lab", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--static-only", action="store_true")
    a = ap.parse_args(argv)
    targets = sorted(a.lab.glob("*.glb")) if a.lab else ([a.glb] if a.glb else [])
    if not targets:
        ap.error("give a GLB or --lab <dir>")
    units = [measure_unit(p) for p in targets]
    if a.static_only:
        for u in units:
            bad = [x for x in u["actions"] if x["static"]]
            print(f"{u['unit']}: {len(bad)} static of {len(u['actions'])}"
                  f"{' — ' + ', '.join(x['action'] for x in bad) if bad else ''}")
        return 0
    if a.json:
        print(json.dumps(units, indent=1))
    else:
        for u in units:
            report(u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
