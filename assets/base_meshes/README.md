# Base meshes

`human-base-meshes-bundle-v1.4.1/` is the Blender Studio Human Base Meshes bundle
(https://www.blender.org/download/demo-files/), licence **CC0 1.0**. It provides
production-topology human bodies, heads, hands and feet used as the body source for the
`pixel_3d` unit roster. Do not edit the bundle; derive working copies.

`tools/blender/base_unit_proof.py` is the current proof pipeline: load the stylized male
body, decimate to ~9k tris, bind the Rigify human metarig with automatic weights, pose
with IK, fit armour/weapon shells, render. It is intentionally a proof harness, not yet
wired into `build_pixel_authored_unit.sh`.
