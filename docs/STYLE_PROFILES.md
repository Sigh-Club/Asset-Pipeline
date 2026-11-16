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
| `pbr_3d` | 3D mesh | ≤25k tris, 2K PBR, 1 direction | contract, seam, flatness, style |
| `lowpoly_3d` | 3D mesh | ≤3k tris, 512 palette, cel | contract, palette, readability |
| `palette_3d` | 3D mesh | ≤4k tris, 256, texel grid 2 cm | contract, texel grid, palette, readability, timing |
| `palette_sprite` | 8-direction sprite | 96×128, rotbile palette, bayer4 | palette, silhouette, directions, timing, sheet |
| `hd_sprite` | 8-direction sprite | 192×256, bayer2, 5-step ramps | as above + readability |

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
python3 tools/style/profiles.py show hd_sprite
python3 tools/style/profiles.py validate            # every profile
python3 tools/style/profiles.py validate palette_3d
python3 tools/style/profiles.py gates palette_sprite
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
python3 tools/style/check_palette_asset.py output/props/barrel/render/<file>.png \
    --profile palette_3d --kind prop
```

## Stage wiring

Implemented (2026-11-10):

| Stage | Reads from the profile |
|---|---|
| `retopo_unit.py --profile` | `geometry.tris_max` (LOD0 budget) |
| `decimate_unit.py --profile` | `geometry.tris_max` (pixel-tier LOD) |
| `bake_unit_atlas.py --profile` | `texture.atlas_px` (AAA atlas) |
| `bake_palette_atlas.py --stage texel --profile` | `texture.texel_world_m`, `texture.atlas_px`; raises if the surface area does not fit the atlas at that density |
| `bake_palette_atlas.py --stage final --profile` | `texture.atlas_px`, `material_model: palette` (one palette material, `Closest` filtering, no PBR maps) |
| `palette_lock.py --profile` | `pixel.palette_id` (and refuses an unregistered palette) |
| `render_master.py` / `master_render.py` | canvas size and direction count are passed by the driver from the profile |

`render.directions`/`size_px` still come from the driver because `palette_3d`
declares `directions: 1` (the in-engine mesh needs no turnaround); the master set
is a render product, so `--directions 8` is explicit at the capture stage.

Explicit CLI flags still override every profile value.

## palette_3d budget change (2026-11-10)

`geometry.tris_max` moved from 1200 to 4000. Choice (not Rejected: 1200, the PSX
figure) — Because: `tools/glb_contract.py` floors a unit at 4000 tris, so a
pixel-tier unit below that cannot pass the engine contract, and the contract is the
engine's authority, not the art tier's. Weapon/prop recipes stay far below the
budget (barrel and lasrifle are 460 tris each).

## palette_3d palette (2026-11-10)

`pixel.palette_id` is now `grimdark_3d` (`assets/palettes/grimdark_3d.gpl`):
`grimdark_64` plus a completed neutral/steel ramp. Measured cause: `grimdark_64`
jumps from 40 to 74 in the neutral ramp, so every mid-grey between them quantised
to `Leather Mid` (70,60,50) — 8,845 atlas pixels of neutral steel became brown on
the first floor tile. The sprite tier keeps `grimdark_64` unchanged; the 3D tier
gets the completed ramp. Adding entries to a locked palette would silently move
sprite colours, which is why this is a second palette and not an edit.

The tick-list gates are unchanged; the two new checks that make them verifiable are
`tools/style/check_texel_grid.py` (density, UV lattice, atlas size, atlas palette)
and `tools/style/palette_lock.py --selftest` (palette exactness).

## Adding a profile

1. Add an entry under `profiles` (use `extends` to inherit a base).
2. Add any new gate to the `gates` registry first.
3. `profiles.py validate <id>` must be clean.
4. Add the profile to the table in this file.

The 13 unit tests (`python3 -m unittest discover -s tools/style/tests`) cover
inheritance, defaults, cycles, unknown keys/gates/palettes, budget shapes, and the
sprite requirements. Any change to the validator must keep them green.
