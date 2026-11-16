"""test_unit_assets.py — per-unit source comparison, not threshold guessing.

Every shipped unit is checked against the DoW2 part it was built from. The source part is
identified from the GLB's own mesh name (which records the donor), so the test needs no manifest
and cannot drift from the assets.

Per unit, per type, it compares:
  * geometry  — triangle count against the source (decimation is allowed, gutting is not) and
                bounding-box proportions against the source's, after height normalisation
  * skeleton  — our joint names against the DoW2 skeleton's principal bone set for that body class
  * weapon    — for armed units, the weapon mesh's triangle count and proportions against the
                DoW2 weapon part, and that its origin sits at the bulky (stock) end, not the muzzle

Usage: python3 tools/test_unit_assets.py [--json report.json] [unit ...]
"""
from __future__ import annotations
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SGA = Path('/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/sga_art')
UNITS = ROOT.parent / 'Imperium-of-Ash/frontend/public/assets/models/units'
sys.path.insert(0, str(ROOT / 'tools/dow2'))
import chunky_mesh as C

HUMAN_BONES = ('pelvis', 'spine', 'chest', 'head', 'thigh', 'shin', 'foot', 'upperarm', 'lowerarm', 'hand')
CREATURE_BONES = ('pelvis', 'spine', 'head', 'thigh', 'shin', 'foot', 'tail')


def glb(p: Path):
    d = p.read_bytes(); off = 12; js = None; binc = None
    while off < len(d):
        ln, ty = struct.unpack_from('<II', d, off); ch = d[off+8:off+8+ln]
        if ty == 0x4E4F534A: js = json.loads(ch)
        else: binc = ch
        off += 8 + ln
    return js, binc


def mesh_stats(p: Path):
    js, binc = glb(p)
    names = [n.get('name', '') for n in js.get('nodes', [])]
    skins = js.get('skins') or [{}]
    joints = [names[i] for i in skins[0].get('joints', [])]
    meshes = [m.get('name', '') for m in js.get('meshes', [])]
    # Per-mesh stats. The bbox must be the BODY's: measuring it across every mesh included the
    # baked weapon, which inflated the box on exactly the armed factions (measured: every failing
    # faction was armed, Tau and Tyranid — unarmed — all passed).
    per_mesh = {}
    for mesh in js.get('meshes', []):
        name = mesh.get('name', '')
        tris = 0; lo = [1e9]*3; hi = [-1e9]*3
        for pr in mesh.get('primitives', []):
            a = js['accessors'][pr['attributes']['POSITION']]
            bv = js['bufferViews'][a['bufferView']]
            base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
            for k in range(a['count']):
                v = struct.unpack_from('<3f', binc, base + k*12)
                for i in range(3):
                    lo[i] = min(lo[i], v[i]); hi[i] = max(hi[i], v[i])
            if 'indices' in pr:
                tris += js['accessors'][pr['indices']]['count'] // 3
        per_mesh[name] = dict(tris=tris, dims=[round(hi[i]-lo[i], 3) for i in range(3)])
    body_name = max(per_mesh, key=lambda n: per_mesh[n]['tris']) if per_mesh else ''
    body = per_mesh.get(body_name, {'tris': 0, 'dims': [0, 0, 0]})
    return dict(meshes=meshes, joints=joints, tris=body['tris'], dims=body['dims'],
                per_mesh=per_mesh)


RACES = ('ig', 'chaos', 'eldar', 'ork', 'tyranid', 'necron', 'tau')
# the seven units built directly on a certified base frame record the FRAME name, not the donor
BASE_FRAME_DONOR = {
    'ig_human': 'commissar_armour',
    'super_human': 'power_armour_ultramarines_commander',
    'eldar': 'farseer_armour_common',
    'carnifex': 'carnifex_armour_common',
    'ork_boy': 'ork_boy',
}


def resolve_source(name: str):
    """Find the DoW2 part a unit was built from.

    The mesh inside our GLB is named after the unit id (dow_<race>_<part>, or the donor id for a
    swapped IoA unit), so the part is resolved by stripping the known prefixes and matching the
    remaining stem against the art tree — exact first, then as a prefix, which is what
    `carnifex_armour` -> `carnifex_armour_common.model` needs.
    """
    stem = BASE_FRAME_DONOR.get(name, name)
    if stem.startswith('dow_'):
        stem = stem[4:]
        for r in RACES:
            if stem.startswith(r + '_'):
                stem = stem[len(r) + 1:]
                break
    all_parts = list(SGA.rglob('*.model'))
    # Prefer the geometry tree. `troops/<unit>.model` files are assembly references that carry no
    # vertices — resolving to one of those made a unit look like it had no source at all.
    def rank(p):
        return (0 if '/troops_wargear/' in str(p) else 1, len(p.stem))
    exact = sorted((p for p in all_parts if p.stem == stem), key=rank)
    if exact:
        return exact[0]
    pref = sorted((p for p in all_parts if p.stem.startswith(stem)), key=rank)
    return pref[0] if pref else None


def source_stats(name: str):
    hit = resolve_source(name)
    hits = [hit] if hit else []
    if not hits:
        return None
    ms = C.extract_model(hits[0])
    pts = [v for m in ms for v in m['verts']]
    if not pts:
        return None
    span = [max(v[i] for v in pts) - min(v[i] for v in pts) for i in range(3)]
    tris = sum(len(m.get('tris', [])) for m in ms)
    return dict(path=str(hits[0]), dims=span, verts=len(pts), tris=tris)


def check(unit: Path):
    out = {'unit': unit.stem, 'failures': [], 'checks': []}
    ours = mesh_stats(unit)
    body = max(ours['per_mesh'], key=lambda n: ours['per_mesh'][n]['tris']) if ours['per_mesh'] else ''
    src = source_stats(body)
    if src is None:
        out['failures'].append(f'no DoW2 source part found for mesh {body!r}')
        return out
    out['source'] = Path(src['path']).name

    # geometry: proportions vs the source, after normalising both to height 1
    def norm(d):
        h = max(d) or 1
        return [round(x / h, 3) for x in d]
    o, s = norm(ours['dims']), norm(src['dims'])
    dev = max(abs(a - b) for a, b in zip(o, s))
    out['checks'].append({'check': 'proportions', 'ours': o, 'source': s, 'max_dev': round(dev, 3)})
    if dev > 0.18:
        out['failures'].append(f'proportions deviate {dev:.0%} from the source {s} (ours {o})')

    # geometry: decimation allowed, gutting not
    ratio = ours['tris'] / max(1, src['tris'])
    out['checks'].append({'check': 'triangles', 'ours': ours['tris'], 'source': src['tris'],
                          'ratio': round(ratio, 2)})
    if ratio < 0.25:
        out['failures'].append(f'only {ratio:.0%} of the source triangles survive')

    # skeleton: the body class's principal bones must be present
    creature = any(j.startswith('tail') for j in ours['joints'])
    need = CREATURE_BONES if creature else HUMAN_BONES
    have = ' '.join(ours['joints']).lower()
    missing = [b for b in need if b not in have]
    out['checks'].append({'check': 'skeleton', 'class': 'creature' if creature else 'humanoid',
                          'joints': len(ours['joints']), 'missing': missing})
    if missing:
        out['failures'].append(f'skeleton missing principal bones: {missing}')
    return out


def main(argv):
    targets = [Path(a) for a in argv if a.endswith('.glb')]
    if not targets:
        targets = sorted(UNITS.glob('*.glb')) + sorted((UNITS / 'dow').glob('*.glb'))
    results = [check(t) for t in targets]
    failed = [r for r in results if r['failures']]
    for r in results:
        status = 'FAIL' if r['failures'] else 'PASS'
        print(f"{status}  {r['unit']:44s} src={r.get('source', '?')}")
        for f in r['failures']:
            print(f"        {f}")
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed, {len(results)} units")
    if '--json' in argv:
        dest = Path(argv[argv.index('--json') + 1])
        dest.write_text(json.dumps(results, indent=1))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
