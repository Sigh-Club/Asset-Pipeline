#!/usr/bin/env python3
"""bands.py — measure our style profiles against the published asset bands.

`docs/STYLE_BANDS.md` holds the collected industry numbers. This tool turns that
document into a measurement: for every profile in `configs/styles/profiles.json`,
which band it lands in, and whether the target band (AAA PC by default) is
represented at all. Opinion about "does this look right" is replaced by a row.

Usage:
  bands.py                      # table + verdict for the target band
  bands.py --target mobile      # check a different band
  bands.py --json

Exit 0 when at least one profile satisfies the target band, 1 when none does.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / 'configs' / 'styles' / 'profiles.json'

# Bands from docs/STYLE_BANDS.md §1. tris_max is the LOD0 ceiling for a character.
# Every band has a FLOOR and a ceiling: a 4K-tri mesh is not "AAA" merely because it is
# under 120K. Source: docs/STYLE_BANDS.md §1.
BANDS = {
    'psx':      {'tris_min': 0,      'tris_max': 1_000,   'tex_min': 64,   'tex_max': 512,
                 'normal': False},
    'mobile':   {'tris_min': 2_000,  'tris_max': 10_000,  'tex_min': 512,  'tex_max': 1024,
                 'normal': False},
    'pc_ready': {'tris_min': 20_000, 'tris_max': 50_000,  'tex_min': 1024, 'tex_max': 2048,
                 'normal': True},
    'aaa_pc':   {'tris_min': 80_000, 'tris_max': 120_000, 'tex_min': 2048, 'tex_max': 4096,
                 'normal': True},
}


def load_profiles() -> dict:
    raw = json.loads(PROFILES.read_text())
    # the file is either {profiles:{...}} or a flat map
    return raw.get('profiles', raw)


def geometry(p: dict) -> dict:
    return p.get('geometry', {}) or {}


def texture(p: dict) -> dict:
    return p.get('texture', {}) or {}


def band_of(p: dict) -> str:
    """The band a profile's declared budget lands in (by tris, then shading)."""
    tris = geometry(p).get('tris_max') or 0
    for name in ('psx', 'mobile', 'pc_ready', 'aaa_pc'):
        if tris <= BANDS[name]['tris_max']:
            return name
    return 'above_aaa'


def fits(p: dict, band: str) -> tuple[bool, list[str]]:
    """Does this profile satisfy the band's floor, ceiling and material requirements?"""
    b = BANDS[band]
    tris = geometry(p).get('tris_max') or 0
    tex = texture(p).get('size') or texture(p).get('atlas_max') or 0
    normal = bool(texture(p).get('normal_map'))
    shading = (p.get('render', {}) or {}).get('shading') or p.get('shading')
    gaps = []
    if tris < b['tris_min']:
        gaps.append(f'tris_max {tris} is below the {band} floor {b["tris_min"]}')
    elif tris > b['tris_max']:
        gaps.append(f'tris_max {tris} is above the {band} ceiling {b["tris_max"]}')
    if b['normal'] and not normal:
        gaps.append('normal_map false (baking is what carries detail at game poly counts)')
    if tex and tex < b['tex_min']:
        gaps.append(f'texture {tex} < {b["tex_min"]}')
    if band == 'aaa_pc' and shading in ('flat', 'cel'):
        gaps.append(f'shading {shading} (AAA band expects pbr)')
    return (not gaps), gaps


def main() -> int:
    ap = argparse.ArgumentParser(description='measure profiles against published asset bands')
    ap.add_argument('--target', default='aaa_pc', choices=sorted(BANDS))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    profiles = load_profiles()
    rows = []
    for name in sorted(profiles):
        p = profiles[name]
        if not isinstance(p, dict):
            continue
        if (p.get('representation') or 'mesh_3d') != 'mesh_3d' or 'sprite' in name:
            continue  # sprite tiers have no triangle budget to compare
        band = band_of(p)
        ok, gaps = fits(p, a.target)
        rows.append({
            'profile': name,
            'tris_max': geometry(p).get('tris_max'),
            'normal_map': bool(texture(p).get('normal_map')),
            'lands_in': band,
            'meets_target': ok,
            'gaps': gaps,
        })

    satisfied = [r for r in rows if r['meets_target']]
    if a.json:
        print(json.dumps({'target': a.target, 'satisfied': len(satisfied), 'rows': rows}, indent=2))
        return 0 if satisfied else 1

    print(f'target band: {a.target}  (tris<= {BANDS[a.target]["tris_max"]}, '
          f'normal_map required: {BANDS[a.target]["normal"]})')
    print(f'{"profile":<24}{"tris_max":>9}  {"normal":<7}{"lands in":<12}meets target')
    for r in rows:
        print(f'{r["profile"]:<24}{str(r["tris_max"]):>9}  {str(r["normal_map"]):<7}'
              f'{r["lands_in"]:<12}{"YES" if r["meets_target"] else "no"}')
        for g in r['gaps']:
            print(f'    - {g}')
    print(f'\n{a.target}: {len(satisfied)} of {len(rows)} profiles satisfy the band')
    return 0 if satisfied else 1


if __name__ == '__main__':
    sys.exit(main())
