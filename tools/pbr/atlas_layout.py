"""Atlas tile layout shared between the texture painter and the geometry generator.

Dependency-free so it can be imported inside Blender's bundled Python (no PIL/numpy).
The texture painter (tools/pbr/paint_unit_diffuse.py) and the geometry generator
(tools/blender/parametric_unit_generator.py) must agree on this layout so each body
part's UVs map to the tile that was painted for it.
"""

# 1024x1024 atlas, 4x4 grid of 256x256 tiles. (row, col) per body part.
# row 0 is the TOP of the image (highest UV v).
TILE_LAYOUT = {
    "torso":      (0, 0),
    "helmet":     (0, 1),
    "pauldron":   (0, 2),
    "upper_arm":  (0, 3),
    "forearm":    (1, 0),
    "thigh":      (1, 1),
    "shin":       (1, 2),
    "boot":       (1, 3),
    "belt":       (2, 0),
    "backpack":   (2, 1),
    "weapon":     (2, 2),
    "codpiece":   (2, 3),
    "aquila":     (3, 0),
}

TILES_PER_ROW = 4