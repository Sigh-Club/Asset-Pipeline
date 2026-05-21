#!/usr/bin/env python3
"""
debug_inspect.py — Inspect what's in the scene after loading test_model.blend
"""

import bpy

blend_path = "/home/talzanar/Documents/Projects/asset-pipeline/assets/characters/test_model/model/test_model.blend"
bpy.ops.wm.open_mainfile(filepath=blend_path)

print("=== Objects in scene ===")
for obj in bpy.context.scene.objects:
    print(f"  {obj.name}: type={obj.type}, loc=({obj.location.x:.1f}, {obj.location.y:.1f}, {obj.location.z:.1f}), scale=({obj.scale.x:.1f}, {obj.scale.y:.1f}, {obj.scale.z:.1f})")

print("\n=== Camera ===")
cam = bpy.context.scene.camera
if cam:
    print(f"  Camera: {cam.name}, loc=({cam.location.x:.1f}, {cam.location.y:.1f}, {cam.location.z:.1f})")
    print(f"  Rotation: ({cam.rotation_euler.x:.2f}, {cam.rotation_euler.y:.2f}, {cam.rotation_euler.z:.2f})")
    print(f"  Type: {cam.data.type}, Ortho scale: {cam.data.ortho_scale}")
else:
    print("  No camera!")
