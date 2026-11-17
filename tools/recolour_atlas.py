"""recolour_atlas.py — recolour a unit's palette atlas in place, changing nothing else.

The palette tier ships a flat-colour atlas per unit. Rebuilding the whole asset through Blender to
change one colour re-exports geometry, clips and pose; this rewrites only the atlas image inside the
GLB, so the mesh, the rig, the clips and the bind pose are byte-identical afterwards.

Usage: python3 tools/recolour_atlas.py <unit.glb> 0xRRGGBB [more units...]
"""
from __future__ import annotations
import io, json, struct, sys
from pathlib import Path
from PIL import Image


def recolour(path: Path, colour: str) -> bool:
    d = path.read_bytes()
    if d[:4] != b'glTF':
        return False
    off = 12
    chunks = []
    while off < len(d):
        ln, ty = struct.unpack_from('<II', d, off)
        chunks.append([ty, d[off+8:off+8+ln]])
        off += 8 + ln
    js_i = next(i for i, c in enumerate(chunks) if c[0] == 0x4E4F534A)
    bin_i = next(i for i, c in enumerate(chunks) if c[0] == 0x004E4942)
    js = json.loads(chunks[js_i][1])
    binc = bytearray(chunks[bin_i][1])

    h = colour.replace('0x', '').replace('#', '')
    rgb = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    images = js.get('images', [])
    if not images:
        return False
    for img in images:
        bv = js['bufferViews'][img['bufferView']]
        start = bv.get('byteOffset', 0)
        raw = bytes(binc[start:start + bv['byteLength']])
        old = Image.open(io.BytesIO(raw))
        new = Image.new('RGB', old.size, rgb)
        buf = io.BytesIO()
        new.save(buf, format='PNG')
        data = buf.getvalue()
        # append at the end of the binary chunk and repoint the view, so no other offsets move
        new_off = len(binc)
        binc += data
        bv['byteOffset'] = new_off
        bv['byteLength'] = len(data)
        bv.pop('byteStride', None)
    js['buffers'][0]['byteLength'] = len(binc)
    jsb = json.dumps(js, separators=(',', ':')).encode()
    jsb += b' ' * ((4 - len(jsb) % 4) % 4)
    binc += b'\x00' * ((4 - len(binc) % 4) % 4)
    chunks[js_i][1] = jsb
    chunks[bin_i][1] = bytes(binc)
    body = b''.join(struct.pack('<II', len(c[1]), c[0]) + c[1] for c in chunks)
    path.write_bytes(b'glTF' + struct.pack('<II', 2, 12 + len(body)) + body)
    return True


FACTION = {
    'iron_directorate': '0x6b7280', 'cinderborn': '0x8a4b4b', 'void_corsairs': '0x4b7a7a',
    'wreckstorm_clans': '0x6b7a4b', 'parasitic_bloom': '0x6b5a4b', 'chrono_revenants': '0x4b5a6b',
    'radiant_concord': '0x7a6b4b',
}

if __name__ == '__main__':
    if len(sys.argv) == 3:
        print('ok' if recolour(Path(sys.argv[1]), sys.argv[2]) else 'no atlas')
    else:
        root = Path(sys.argv[1])
        n = 0
        for p in sorted(root.glob('*.glb')):
            fac = next((k for k in FACTION if p.stem.startswith(k)), None)
            if fac and recolour(p, FACTION[fac]):
                n += 1
        print(f'recoloured {n} units in {root}')
