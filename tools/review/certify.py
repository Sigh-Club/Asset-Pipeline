#!/usr/bin/env python3
"""certify.py — prove the vision gate can tell a good render from a broken one.

T1's certification is not "it ran". It is: given a good render and two renders
broken in KNOWN ways, the gate must pass the good one, fail both broken ones, and
name the defect that was actually injected. A reviewer that scores everything 7/10
passes this only by accident, and the assertions below catch that.

Injected defects (deterministic, from the candidate itself, so the ground truth is
not a matter of opinion):
  detached  the head region is lifted out of the body and displaced — the gate
            must say a part is detached/floating and refuse the pass
  flat      the render is desaturated, blurred and contrast-compressed — the gate
            must drop detail_level and/or contrast_separation below the floor

Usage:
  certify.py --reference <ref.png> --candidate <render.png> [--work DIR]
Exit 0 = the gate separates the three cases as required; 1 = it does not.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
CRITIC = ROOT / 'tools' / 'review' / 'vlm_critic.py'

DETACHED_WORDS = re.compile(r'detach|float|separat|disconnect|hover|gap|offset|apart', re.I)


def alpha_bbox(im: Image.Image) -> tuple[int, int, int, int] | None:
    return im.split()[-1].getbbox() if im.mode == 'RGBA' else None


def make_detached(src: Path, out: Path) -> None:
    """Lift the head out of the body and displace it, leaving a visible gap."""
    im = Image.open(src).convert('RGBA')
    box = alpha_bbox(im)
    if not box:
        raise SystemExit('candidate needs an alpha channel to cut a part out of')
    x0, y0, x1, y1 = box
    h = y1 - y0
    cut = (x0, y0, x1, y0 + max(8, int(h * 0.26)))          # head band
    head = im.crop(cut)
    body = im.copy()
    body.paste((0, 0, 0, 0), cut)                            # erase the head from the body
    dx, dy = int((x1 - x0) * 0.22), -int(h * 0.10)           # up and to the right: clearly floating
    body.alpha_composite(head, (dx, dy))
    out.parent.mkdir(parents=True, exist_ok=True)
    body.save(out)


def make_flat(src: Path, out: Path) -> None:
    """Desaturate, blur and compress contrast: material and detail signals die."""
    im = Image.open(src).convert('RGBA')
    rgb = im.convert('RGB')
    rgb = ImageEnhance.Color(rgb).enhance(0.12)
    rgb = rgb.filter(ImageFilter.GaussianBlur(2.2))
    rgb = ImageEnhance.Contrast(rgb).enhance(0.55)
    flat = rgb.convert('RGBA')
    flat.putalpha(im.split()[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    flat.save(out)


def run_critic(asset: str, ref: Path, cand: Path, work: Path) -> dict:
    r = subprocess.run([sys.executable, str(CRITIC), '--asset', asset,
                        '--reference', str(ref), '--candidate', str(cand),
                        '--out', str(work / asset)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {'decision': 'error', 'raw': (r.stdout + r.stderr)[-400:]}


def main() -> int:
    p = argparse.ArgumentParser(description='certify the vision review gate')
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--work', type=Path, default=ROOT / 'output' / 'review' / 'certify')
    a = p.parse_args()

    work = a.work
    work.mkdir(parents=True, exist_ok=True)
    detached = work / 'candidate_detached.png'
    flat = work / 'candidate_flat.png'
    make_detached(a.candidate, detached)
    make_flat(a.candidate, flat)

    cases = [('good', a.candidate), ('detached', detached), ('flat', flat)]
    results = {}
    for name, cand in cases:
        print(f'[{name}] reviewing {cand.name} …', flush=True)
        results[name] = run_critic(f'certify_{name}', a.reference, cand, work)
        r = results[name]
        print(f'[{name}] decision={r.get("decision")} reasons={r.get("reasons")} '
              f'defects={r.get("defects")}', flush=True)

    def mean_score(r: dict) -> float:
        s = r.get('scores') or {}
        vals = [v for v in s.values() if isinstance(v, (int, float))]
        return sum(vals) / len(vals) if vals else 0.0

    checks: list[tuple[str, bool, str]] = []
    good, det, flt = results['good'], results['detached'], results['flat']

    checks.append(('good render is not stopped',
                   good.get('decision') in ('continue', 'refine-code'),
                   f"decision={good.get('decision')}"))
    checks.append(('detached part is rejected',
                   det.get('decision') == 'refine-code',
                   f"decision={det.get('decision')}"))
    checks.append(('detached defect is named',
                   bool(DETACHED_WORDS.search(' '.join(det.get('defects') or []) + ' '
                                               + ' '.join(det.get('reasons') or []))),
                   f"defects={det.get('defects')}"))
    checks.append(('flat render is rejected',
                   flt.get('decision') == 'refine-code',
                   f"decision={flt.get('decision')}"))
    flat_reasons = ' '.join(flt.get('reasons') or []) + ' ' + ' '.join(flt.get('defects') or [])
    checks.append(('flat defect lands on detail or contrast',
                   bool(re.search(r'detail|contrast|flat|blur|muddy|washed', flat_reasons, re.I)),
                   f"reasons={flt.get('reasons')}"))
    checks.append(('good outscores both broken renders',
                   mean_score(good) > mean_score(det) and mean_score(good) > mean_score(flt),
                   f'good={mean_score(good):.1f} detached={mean_score(det):.1f} flat={mean_score(flt):.1f}'))

    print('\n=== T1 certification')
    ok = True
    for label, passed, detail in checks:
        print(f'  [{"PASS" if passed else "FAIL"}] {label}: {detail}')
        ok = ok and passed
    (work / 'certification.json').write_text(json.dumps(
        {'checks': [{'check': l, 'pass': p, 'detail': d} for l, p, d in checks],
         'results': results}, indent=2))
    print(f'\n{"CERTIFIED" if ok else "NOT CERTIFIED"} — {work / "certification.json"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
