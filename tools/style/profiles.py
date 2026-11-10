#!/usr/bin/env python3
"""profiles.py — style profiles: one object that selects how an asset is made.

A profile names a representation (mesh or sprite), geometry and texture budgets, a
shading model, a pixel treatment and the gate set that accepts the result. Stage
tools read the resolved profile instead of hard-coding a look; that is what makes
AAA, low-poly, pixel-3D and HD pixel selectable without parallel pipelines.

Design rules:
  * JSON only, no code in the profiles.
  * `extends` allows a derived profile to inherit and override (one level of
    indirection is normal; cycles are rejected).
  * unknown keys are errors, not silently ignored — a typo must not quietly change
    the art direction.
  * the validator checks values against enums and budget ranges and verifies that
    every declared gate exists.

Usage:
    python3 tools/style/profiles.py list
    python3 tools/style/profiles.py show hd_pixel_sprite
    python3 tools/style/profiles.py validate
    python3 tools/style/profiles.py gates pixel_sprite
    python3 tools/style/profiles.py show pixel_sprite --json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "styles" / "profiles.json"
PALETTE_DIR = ROOT / "assets" / "palettes"

REPRESENTATIONS = {"mesh_3d", "sprite_2d"}
SHADING = {"pbr", "cel", "flat"}
UV_MODES = {"pbr", "texel_grid", "none"}
MATERIAL_MODELS = {"pbr", "palette", "flat"}
DITHERS = {"none", "bayer2", "bayer4", "error_diffusion"}
DIRECTIONS = {1, 4, 8}
CLIP_NAMES = {"idle", "walk", "run", "aim", "fire", "reload", "hit", "death", "melee"}

SECTION_KEYS = {
    "label", "extends", "representation", "notes",
    "geometry", "texture", "render", "pixel", "animation", "gates",
}
GEOMETRY_KEYS = {"tris_max", "tris_min", "shading", "uv"}
TEXTURE_KEYS = {"atlas_px", "material_model", "normal_map", "ao", "emission", "texel_world_m"}
RENDER_KEYS = {"directions", "size_px", "aa", "per_asset_resolution"}
PIXEL_KEYS = {"palette_id", "dither", "outline", "ink_luma", "selout", "ramps",
              "subpixel", "smear_frames"}
ANIMATION_KEYS = {"fps_authored", "clips"}
CLIP_KEYS = {"frames"}


# --------------------------------------------------------------------- load ---

def load_config(path: Path = CONFIG) -> dict:
    if not path.exists():
        raise SystemExit(f"no style profiles at {path}")
    return json.loads(path.read_text())


def _strip_comments(obj):
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not k.startswith("//")}
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def resolve(profile_id: str, config: dict | None = None) -> dict:
    """Resolve a profile, applying defaults and `extends` chains."""
    cfg = _strip_comments(config or load_config())
    profiles = cfg.get("profiles", {})
    if profile_id not in profiles:
        raise KeyError(f"unknown style profile '{profile_id}' "
                       f"(have: {', '.join(sorted(profiles))})")

    chain, seen, current = [], set(), profile_id
    while current:
        if current in seen:
            raise ValueError(f"extends cycle at '{current}'")
        seen.add(current)
        if current not in profiles:
            raise KeyError(f"profile '{current}' extends unknown profile")
        chain.append(profiles[current])
        current = profiles[current].get("extends")

    resolved = copy.deepcopy(cfg.get("defaults", {}))
    for layer in reversed(chain):
        resolved = _merge(resolved, layer)
    resolved["id"] = profile_id
    resolved.pop("extends", None)
    return resolved


# ----------------------------------------------------------------- validate ---

def _check_keys(obj, allowed, where, errors):
    for key in obj:
        if key == "id":
            continue
        if key not in allowed:
            errors.append(f"{where}: unknown key '{key}'")


def _palette_ids() -> set[str]:
    """Palette ids available to profiles: the pixel style registry plus any .gpl
    file in assets/palettes."""
    ids = {p.stem for p in PALETTE_DIR.glob("*.gpl")} if PALETTE_DIR.exists() else set()
    registry = ROOT / "pz" / "pixel" / "styles.py"
    if registry.exists():
        import importlib.util
        sys.path.insert(0, str(registry.parent))
        try:
            spec = importlib.util.spec_from_file_location("pixel_styles", registry)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ids |= set(getattr(mod, "STYLES", {}))
        except Exception:  # noqa: BLE001 - palette validation must not fail the CLI
            pass
        finally:
            sys.path.pop(0)
    return ids


def validate(profile: dict, config: dict | None = None) -> list[str]:
    cfg = _strip_comments(config or load_config())
    errors: list[str] = []
    where = profile.get("id", "<profile>")

    _check_keys(profile, SECTION_KEYS, where, errors)
    if profile.get("representation") not in REPRESENTATIONS:
        errors.append(f"{where}: representation must be one of {sorted(REPRESENTATIONS)}")

    geometry = profile.get("geometry", {})
    if geometry:
        _check_keys(geometry, GEOMETRY_KEYS, f"{where}.geometry", errors)
        tris_max, tris_min = geometry.get("tris_max"), geometry.get("tris_min", 0)
        if not isinstance(tris_max, int) or tris_max <= 0:
            errors.append(f"{where}.geometry: tris_max must be a positive integer")
        elif not isinstance(tris_min, int) or tris_min < 0 or tris_min >= tris_max:
            errors.append(f"{where}.geometry: tris_min must be >= 0 and < tris_max")
        if geometry.get("shading") not in SHADING:
            errors.append(f"{where}.geometry: shading must be one of {sorted(SHADING)}")
        if geometry.get("uv") not in UV_MODES:
            errors.append(f"{where}.geometry: uv must be one of {sorted(UV_MODES)}")

    texture = profile.get("texture", {})
    if texture:
        _check_keys(texture, TEXTURE_KEYS, f"{where}.texture", errors)
        atlas = texture.get("atlas_px", 0)
        if not isinstance(atlas, int) or atlas < 32 or atlas & (atlas - 1):
            errors.append(f"{where}.texture: atlas_px must be a power of two >= 32")
        if texture.get("material_model") not in MATERIAL_MODELS:
            errors.append(f"{where}.texture: material_model must be one of "
                          f"{sorted(MATERIAL_MODELS)}")
        if geometry.get("uv") == "texel_grid":
            tw = texture.get("texel_world_m")
            if not isinstance(tw, (int, float)) or tw <= 0:
                errors.append(f"{where}.texture: uv=texel_grid requires texel_world_m > 0")

    render = profile.get("render", {})
    if render:
        _check_keys(render, RENDER_KEYS, f"{where}.render", errors)
        if render.get("directions") not in DIRECTIONS:
            errors.append(f"{where}.render: directions must be one of {sorted(DIRECTIONS)}")
        size = render.get("size_px")
        if size is not None:
            if (not isinstance(size, list) or len(size) != 2
                    or not all(isinstance(v, int) and v >= 8 for v in size)):
                errors.append(f"{where}.render: size_px must be [width, height] >= 8")
            elif render.get("directions", 1) > 1 and size[0] < 64:
                errors.append(f"{where}.render: multi-direction sprites need width >= 64")
        if profile.get("representation") == "sprite_2d" and size is None:
            errors.append(f"{where}.render: sprite_2d profiles must set size_px")

    pixel = profile.get("pixel", {})
    if pixel:
        _check_keys(pixel, PIXEL_KEYS, f"{where}.pixel", errors)
        if pixel.get("dither") not in DITHERS:
            errors.append(f"{where}.pixel: dither must be one of {sorted(DITHERS)}")
        if not 0.0 <= float(pixel.get("outline", 0.0)) <= 1.5:
            errors.append(f"{where}.pixel: outline must be within 0.0-1.5")
        if pixel.get("palette_id") and pixel["palette_id"] not in _palette_ids():
            errors.append(f"{where}.pixel: unknown palette_id '{pixel['palette_id']}'")
        if profile.get("representation") == "sprite_2d" and not pixel.get("palette_id"):
            errors.append(f"{where}.pixel: sprite_2d profiles must set palette_id")
        if texture.get("material_model") == "palette" and not pixel.get("palette_id"):
            errors.append(f"{where}.pixel: palette material requires palette_id")

    animation = profile.get("animation", {})
    if animation:
        _check_keys(animation, ANIMATION_KEYS, f"{where}.animation", errors)
        if not 1 <= int(animation.get("fps_authored", 12)) <= 60:
            errors.append(f"{where}.animation: fps_authored must be 1-60")
        for clip, spec in (animation.get("clips") or {}).items():
            if clip not in CLIP_NAMES:
                errors.append(f"{where}.animation: unknown clip '{clip}'")
            if not isinstance(spec, dict):
                errors.append(f"{where}.animation.{clip}: expected an object")
                continue
            _check_keys(spec, CLIP_KEYS, f"{where}.animation.{clip}", errors)
            frames = spec.get("frames")
            if (not isinstance(frames, list) or len(frames) != 2
                    or not all(isinstance(f, int) for f in frames)
                    or frames[0] > frames[1] or frames[0] < 1):
                errors.append(f"{where}.animation.{clip}: frames must be [min, max] integers")

    gates = profile.get("gates", [])
    known = cfg.get("gates", {})
    for gate in gates:
        if gate not in known:
            errors.append(f"{where}.gates: unknown gate '{gate}'")
    if len(set(gates)) != len(gates):
        errors.append(f"{where}.gates: duplicate gate ids")

    return errors


# --------------------------------------------------------------------- main ---

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("list", "show", "validate", "gates"))
    ap.add_argument("profile", nargs="?")
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = load_config(Path(args.config))

    if args.command == "list":
        rows = []
        for pid in sorted(cfg.get("profiles", {})):
            resolved = resolve(pid, cfg)
            rows.append({"id": pid, "label": resolved.get("label", ""),
                         "representation": resolved.get("representation", "")})
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['id']:18s} {r['representation']:10s} {r['label']}")
        return 0

    if args.command == "validate" and not args.profile:
        failed = 0
        for pid in sorted(cfg.get("profiles", {})):
            resolved = resolve(pid, cfg)
            errors = validate(resolved, cfg)
            if errors:
                failed += 1
                for e in errors:
                    print(f"ERROR  {e}", file=sys.stderr)
            else:
                print(f"{pid}: OK ({len(resolved.get('gates', []))} gates, "
                      f"{resolved.get('representation')})")
        return 1 if failed else 0

    if not args.profile:
        raise SystemExit("this command needs a profile id")

    resolved = resolve(args.profile, cfg)
    if args.command == "show":
        print(json.dumps(resolved, indent=2))
        return 0
    if args.command == "gates":
        print("\n".join(resolved.get("gates", [])))
        return 0

    errors = validate(resolved, cfg)
    if errors:
        for e in errors:
            print(f"ERROR  {e}", file=sys.stderr)
        return 1
    print(f"{args.profile}: OK ({len(resolved.get('gates', []))} gates, "
          f"{resolved.get('representation')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
