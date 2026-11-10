# Style profiles — schema and stage wiring

**Status:** implemented 2026-11-09 (`configs/styles/profiles.json`,
`tools/style/profiles.py`). Phase 1 of the style programme in `TODO.md`.
Design authority: [`STYLE_RESEARCH.md`](STYLE_RESEARCH.md).

A profile is the single object that decides how one asset is made: representation,
budgets, shading model, pixel treatment and the gate set that accepts it. Stage
tools read a resolved profile; they never hard-code a look. This is what makes
AAA, low-poly, pixel-3D and HD pixel selectable without four parallel pipelines.

## Profiles shipped

| id | Representation | Budget | Gates |
|---|---|---|---|
| `aaa_3d` | 3D mesh | ≤25k tris, 2K PBR, 1 direction | contract, seam, flatness, style |
| `lowpoly_3d` | 3D mesh | ≤3k tris, 512 palette, cel | contract, palette, readability |
| `pixel_3d` | 3D mesh | ≤1.2k tris, 256, texel grid 2 cm | contract, texel grid, palette, readability, timing |
| `pixel_sprite` | 8-direction sprite | 96×128, rotbile palette, bayer4 | palette, silhouette, directions, timing, sheet |
| `hd_pixel_sprite` | 8-direction sprite | 192×256, bayer2, 5-step ramps | as above + readability |

## Schema

```json
{
  "id": "<from the key>",
  "label": "human name",
  "representation": "mesh_3d | sprite_2d",
  "geometry": {"tris_max": 25000, "tris_min": 4000, "shading": "pbr|cel|flat",
                "uv": "pbr|texel_grid|none"},
  "texture": {"atlas_px": 2048, "material_model": "pbr|palette|flat",
               "normal_map": true, "ao": true, "emission": true,
               "texel_world_m": 0.02},
  "render": {"directions": 1, "size_px": [192, 256], "aa": false,
              "per_asset_resolution": true},
  "pixel": {"palette_id": "rotbile", "dither": "none|bayer2|bayer4|error_diffusion",
             "outline": 0.5, "ink_luma": 0.3, "selout": true, "ramps": 5,
             "subpixel": true, "smear_frames": true},
  "animation": {"fps_authored": 12, "clips": {"walk": {"frames": [6, 10]}}},
  "gates": ["palette_compliance", "..."]
}
```

Rules enforced by the validator:

- **Unknown keys are errors.** A typo must not silently change the art direction.
- `extends` chains are resolved with defaults; cycles are rejected.
- `sprite_2d` requires `render.size_px` and `pixel.palette_id`.
- `uv: texel_grid` requires `texture.texel_world_m > 0`.
- `atlas_px` must be a power of two; animation frame ranges must be `[min, max]`
  with `min ≤ max` and `min ≥ 1`; clip names must be in the 9-clip contract set.
- `palette_id` must resolve to a `.gpl` in `assets/palettes/` or a key in
  `pz/pixel/styles.py`.
- Every gate id must exist in the `gates` registry at the top of the config.

## CLI

```bash
python3 tools/style/profiles.py list
python3 tools/style/profiles.py show hd_pixel_sprite
python3 tools/style/profiles.py validate            # every profile
python3 tools/style/profiles.py validate pixel_3d
python3 tools/style/profiles.py gates pixel_sprite
```

Exit code 1 with `ERROR <path>: <reason>` lines on any invalid profile.

## Asset requests

A profile is selected by an asset request (`configs/assets/*.json`): `id`, `kind`,
`route`, `profile`, `params`, `materials`, optional `references`, and the gates to
run. Routes are `parametric_hard_surface`, `parametric_modular`,
`procedural_organic`, `image_to_3d`, `pixel_ui`. Weapons, props, buildings and
tiles must use a parametric route — image-to-3D fuses parts and loses dimensions.

```bash
# hard-surface prop from a request, rendered at the profile canvas
tools/blender_run.sh --job render -- -b -P tools/blender/parametric_prop.py -- \
    --request configs/assets/examples.json --id iron_directorate_barrel_a \
    --out output/props/barrel --render --library <library.blend>

# pixel gate: palette drift + silhouette integrity
python3 tools/style/check_pixel_asset.py output/props/barrel/render/<file>.png \
    --profile pixel_3d --kind prop
```

## Stage wiring

Current: `retopo_unit.py --profile <id>` takes the LOD0 tri budget and
`bake_unit_atlas.py --profile <id>` takes the atlas size. Explicit CLI flags still
override.

Planned (Phase 5): the profile's `uv`, `material_model` and `pixel` blocks drive the
texel-grid stage, the palette-locked material build and the pixeliser parameters;
`render.directions`/`size_px` drive the 8-direction capture.

## Adding a profile

1. Add an entry under `profiles` (use `extends` to inherit a base).
2. Add any new gate to the `gates` registry first.
3. `profiles.py validate <id>` must be clean.
4. Add the profile to the table in this file.

The 13 unit tests (`python3 -m unittest discover -s tools/style/tests`) cover
inheritance, defaults, cycles, unknown keys/gates/palettes, budget shapes, and the
sprite requirements. Any change to the validator must keep them green.
