"""unit_pose.py — shared authored arm poses for the modular unit rig.

The image-to-3D rig uses a neutral A-pose because the mesh is a blob. An authored
unit has deliberate hands, so the arm chain is posed for the weapon it carries:

  relaxed — arms down/forward, no weapon socket
  ranged  — right hand on the pistol grip, left hand on the foregrip (the
            standard right-hand-socket + left-hand-socket two-handed hold)
  melee   — right hand forward for a blade, left arm free

Both the mesh generator (`parametric_unit.py`) and the rig builder
(`rig_unit_proof.py`) import this module, so the hand geometry and the bones can
never drift apart. Coordinates are metres, Z up, forward -Y (the engine's +Z after
the glTF Y-up conversion), matching `rig_unit_proof.bone_layout`.
"""
from __future__ import annotations

# Shoulder / elbow / wrist / hand points per side and pose. The hand point is the
# socket the weapon geometry is built around.
ARM_POSES = {
    "relaxed": {
        "Left": {"shoulder": (0.16, 0.00, 1.50), "elbow": (0.28, -0.10, 1.36),
                 "wrist": (0.19, -0.28, 1.30), "hand": (0.10, -0.32, 1.28)},
        "Right": {"shoulder": (-0.16, 0.00, 1.50), "elbow": (-0.28, -0.10, 1.36),
                  "wrist": (-0.19, -0.28, 1.30), "hand": (-0.10, -0.32, 1.28)},
    },
    "ranged": {
        # Right hand is the primary socket (pistol grip); left hand is the
        # foregrip. The left elbow is tucked so the forearm reaches the barrel.
        "Right": {"shoulder": (-0.16, 0.00, 1.50), "elbow": (-0.23, -0.10, 1.37),
                  "wrist": (-0.11, -0.30, 1.34), "hand": (-0.05, -0.38, 1.33)},
        "Left": {"shoulder": (0.16, 0.00, 1.50), "elbow": (0.24, -0.16, 1.35),
                 "wrist": (0.10, -0.48, 1.33), "hand": (0.04, -0.56, 1.32)},
    },
    "melee": {
        "Right": {"shoulder": (-0.16, 0.00, 1.50), "elbow": (-0.27, -0.08, 1.35),
                  "wrist": (-0.22, -0.30, 1.28), "hand": (-0.16, -0.36, 1.26)},
        "Left": {"shoulder": (0.16, 0.00, 1.50), "elbow": (0.26, -0.08, 1.36),
                 "wrist": (0.20, -0.24, 1.30), "hand": (0.13, -0.30, 1.28)},
    },
}


def arm_points(pose: str, side: str):
    return ARM_POSES[pose][side]


def bone_layout(height: float, pose: str = "relaxed") -> dict:
    """Full 22-bone layout. Only the arm chain changes with the pose."""
    s = height / 1.9

    def p(x, y, z):
        return (x * s, y * s, z * s)

    arms = ARM_POSES[pose]
    layout = {
        "Hips": (p(0, 0, 0.98), p(0, 0, 1.08), None, False),
        "Spine": (p(0, 0, 1.08), p(0, 0, 1.20), "Hips", True),
        "Spine1": (p(0, 0, 1.20), p(0, 0, 1.34), "Spine", True),
        "Spine2": (p(0, 0, 1.34), p(0, 0, 1.50), "Spine1", True),
        "Neck": (p(0, 0, 1.50), p(0, 0, 1.60), "Spine2", True),
        "Head": (p(0, 0, 1.60), p(0, 0, 1.86), "Neck", True),
    }
    for side, sx in (("Left", 1), ("Right", -1)):
        a = arms[side]
        shoulder = p(*a["shoulder"])
        elbow = p(*a["elbow"])
        wrist = p(*a["wrist"])
        hand = p(*a["hand"])
        layout[f"{side}Shoulder"] = (p(sx * 0.04, 0, 1.48), shoulder, "Spine2", False)
        layout[f"{side}Arm"] = (shoulder, elbow, f"{side}Shoulder", True)
        layout[f"{side}ForeArm"] = (elbow, wrist, f"{side}Arm", True)
        layout[f"{side}Hand"] = (wrist, hand, f"{side}ForeArm", True)
    for side, sx in (("Left", 1), ("Right", -1)):
        layout[f"{side}UpLeg"] = (p(sx * 0.13, 0, 0.94), p(sx * 0.14, 0, 0.55), "Hips", False)
        layout[f"{side}Leg"] = (p(sx * 0.14, 0, 0.55), p(sx * 0.15, 0, 0.12), f"{side}UpLeg", True)
        layout[f"{side}Foot"] = (p(sx * 0.15, 0, 0.12), p(sx * 0.15, -0.14, 0.03), f"{side}Leg", True)
        layout[f"{side}ToeBase"] = (p(sx * 0.15, -0.14, 0.03), p(sx * 0.15, -0.24, 0.02), f"{side}Foot", True)
    return layout
