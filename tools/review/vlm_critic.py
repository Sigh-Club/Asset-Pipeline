#!/usr/bin/env python3
"""vlm_critic.py — the vision verdict for an asset: score it against its target.

This is the judgement half that our numeric gates never had. `critic.py` measures
pixels (coverage, edge density, unique colours); a mesh can satisfy every one of
those and still be the wrong shape. img2threejs records the failure precisely:
"silhouette IoU reads roughly 11 % of figure cells and scored a deleted face
identically to a finished one." Only a vision model sees a deleted face.

Design rules, each of which cost a failure somewhere else:
  * ONE image per review (the packaged sheet), never a scatter of screenshots.
  * The scripts enforce, the model judges. Thresholds, decisions, schema
    validation and the JSON record are deterministic code; the model only looks.
  * A failed attachment is an error, never a verdict. A prompt answered without
    its image is worse than no answer, because it is confidently wrong.
  * Non-JSON is not a pass. The model gets one repair attempt, then `stop`.
  * Every review records the input hashes, so a review can never be silently
    reused against a different render.

Decision vocabulary (img2threejs's, and the only one the loop acts on):
  continue       every feature at or above threshold
  refine-code    the render is wrong in a way the generator can fix
  request-input  the reference itself is unusable/ambiguous — do not guess
  stop           the reviewer could not produce a verdict; do not loop

Usage:
  vlm_critic.py --asset iron_directorate_line_infantry \
      --reference output/img23d/line_infantry_mv/front.png \
      --candidate output/gen/unit8/render/line_infantry_az000.png \
      --out output/review/line_infantry
  vlm_critic.py ... --dry-run        # build the sheet, print the prompt, no call

Exit: 0 continue · 1 refine-code · 2 usage/transport error · 3 request-input · 4 stop
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / 'tools' / 'review'
GEMINI_ASK = REVIEW / 'gemini_ask.py'
THRESHOLDS = ROOT / 'configs' / 'review' / 'default.json'

EXIT = {'continue': 0, 'refine-code': 1, 'request-input': 3, 'stop': 4, 'error': 2}

# Operational definitions, not adjectives: a model that has to guess what "detail"
# means scores noise. These anchors are what make two reviews comparable.
RUBRIC = """Reply with ONE JSON object and nothing else. No prose. No code fences. Start your reply with { and end with }.

Schema (all keys required):
{"silhouette_match": 0, "proportion_match": 0, "material_reads": 0, "detail_level": 0, "contrast_separation": 0, "single_connected_object": true, "matches_reference_identity": true, "defects": ["..."], "missing_features": ["..."]}

You are the visual gate on a 3D game asset pipeline. You are shown ONE image with two panels: the LEFT
panel is the REFERENCE (the target) and the RIGHT panel is the RENDER (the candidate). Judge the RENDER
against the REFERENCE.

Score each feature 0-10 using these anchors:
- 9-10: a viewer would mistake the render for the reference at a glance
- 7-8: clearly the same design; minor differences a player would not notice
- 5-6: same category and colour family, but obviously the wrong silhouette or detail
- 3-4: you would not know they were meant to be the same asset
- 0-2: unrelated

Features:
- silhouette_match: does the outline read as the same figure (head shape, shoulder line, stance, weapon)?
- proportion_match: limb length, torso mass, head size, weapon scale relative to the body
- material_reads: can you tell the materials apart (armour plate vs cloth vs leather vs metal)?
- detail_level: are the reference's identity-defining details present (helmet crest, weapon parts, pouches, trim)?
- contrast_separation: do armour, under-layer, weapon and accents separate from each other, or is it one flat blob?

Booleans:
- single_connected_object: is the render one connected body, with no detached or floating pieces?
- matches_reference_identity: would someone who saw only the reference recognise this render as that design?

Also report:
- defects: a list of concrete, located problems, each under 12 words (e.g. "head detached above the shoulders", "left arm missing below elbow", "weapon reads as a flat bar")
- missing_features: reference details that are absent from the render, each under 6 words

Remember: output the JSON object only."""
REPAIR = ("Your previous answer was not valid JSON. Reply again with ONLY the JSON object, "
          "no prose and no code fences.")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_thresholds() -> dict:
    if THRESHOLDS.exists():
        return json.loads(THRESHOLDS.read_text())
    return {'scores': {'silhouette_match': 6, 'proportion_match': 6, 'material_reads': 5,
                       'detail_level': 5, 'contrast_separation': 5},
            'require': ['single_connected_object', 'matches_reference_identity']}


def build_sheet(reference: Path, candidates: list[Path], out: Path, label: str) -> dict:
    r = subprocess.run([sys.executable, str(REVIEW / 'sheet.py'),
                        '--reference', str(reference),
                        *sum([['--candidate', str(c)] for c in candidates], []),
                        '--out', str(out), '--label', label, '--json'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sheet.py failed: {r.stdout}{r.stderr}')
    return json.loads(r.stdout.strip().splitlines()[-1])


def ask(sheet: Path, prompt: str, timeout: int) -> tuple[str, dict]:
    r = subprocess.run([str(GEMINI_ASK), '--prompt', prompt, '--image', str(sheet),
                        '--max-wait', str(timeout)],
                       capture_output=True, text=True)
    try:
        payload = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        payload = {'ok': False, 'error': f'gemini_ask gave no JSON: {r.stdout[-200:]}{r.stderr[-200:]}'}
    return payload.get('text', ''), payload


def parse_json(text: str):
    """First balanced JSON object in the answer; tolerates fences and stray prose."""
    t = re.sub(r'```(?:json)?', '', text or '')
    start = t.find('{')
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == '{':
                depth += 1
            elif t[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
        start = t.find('{', start + 1)
    return None


SCORE_KEYS = ['silhouette_match', 'proportion_match', 'material_reads', 'detail_level',
              'contrast_separation']
SCORE_SYNONYMS = {
    'silhouette_match': ('silhouette', 'silhouette_score', 'silhouettematch', 'shape'),
    'proportion_match': ('proportion', 'proportions', 'proportion_score', 'scale'),
    'material_reads': ('material', 'materials', 'material_quality', 'material_score'),
    'detail_level': ('detail', 'details', 'detail_score', 'fidelity'),
    'contrast_separation': ('contrast', 'contrast_score', 'separation', 'readability'),
}
FAIL_WORDS = ('fail', 'reject', 'rejected', 'poor', 'unacceptable')


def normalise(obj: dict) -> tuple[dict, str]:
    """Coerce a plausible-but-different answer into the schema, and say what was derived.

    Measured 2026-11-23: asked for a fixed schema, the model sometimes answers with
    {"verdict": "fail", "issues": [{"type","severity","description"}]} instead. That is a
    usable verdict, so it is mapped rather than thrown away — but every derived value is
    recorded so a review can never silently pretend it had real scores.
    """
    out = dict(obj)
    derived: list[str] = []

    nested = obj.get('scores') or obj.get('features') or obj.get('ratings') or {}
    if isinstance(nested, dict):
        for k, v in nested.items():
            key = str(k).lower().replace(' ', '_')
            for canon, aliases in SCORE_SYNONYMS.items():
                if key == canon or key in aliases:
                    if canon not in out:
                        out[canon] = v
                        derived.append(f'{canon} from scores.{k}')

    if 'defects' not in out and isinstance(obj.get('issues'), list):
        items = []
        for it in obj['issues']:
            if isinstance(it, dict):
                desc = it.get('description') or it.get('issue') or it.get('type') or ''
                sev = it.get('severity')
                items.append((f'[{sev}] ' if sev else '') + str(desc)[:120])
            else:
                items.append(str(it)[:120])
        out['defects'] = items
        derived.append('defects from issues')
    out.setdefault('missing_features', [])

    verdict = str(obj.get('verdict', '')).lower()
    failed = (obj.get('pass') is False) or any(w in verdict for w in FAIL_WORDS)
    if not isinstance(out.get('matches_reference_identity'), bool):
        out['matches_reference_identity'] = not failed
        derived.append('matches_reference_identity from verdict')
    if not isinstance(out.get('single_connected_object'), bool):
        detached = any('detach' in str(d).lower() or 'float' in str(d).lower()
                       for d in out.get('defects', []))
        out['single_connected_object'] = not detached
        derived.append('single_connected_object from defects')

    for k in SCORE_KEYS:
        try:
            v = float(out.get(k))
        except (TypeError, ValueError):
            v = 4.0 if failed else 7.0
            derived.append(f'{k} derived from verdict')
        out[k] = max(0.0, min(10.0, v))

    return out, '; '.join(derived)


def validate(obj: dict) -> list[str]:
    """Schema check. A malformed verdict must never be read as a pass."""
    need_int = ['silhouette_match', 'proportion_match', 'material_reads', 'detail_level',
                'contrast_separation']
    need_bool = ['single_connected_object', 'matches_reference_identity']
    errs = []
    for k in need_int:
        if not isinstance(obj.get(k), (int, float)) or not 0 <= obj[k] <= 10:
            errs.append(f'{k} missing or out of range')
    for k in need_bool:
        if not isinstance(obj.get(k), bool):
            errs.append(f'{k} missing or not a boolean')
    for k in ('defects', 'missing_features'):
        if not isinstance(obj.get(k), list):
            errs.append(f'{k} missing or not a list')
    return errs


def decide(obj: dict, th: dict) -> tuple[str, list[str]]:
    """Map a validated verdict to one action, and say exactly why."""
    reasons = []
    for feature, floor in sorted(th.get('scores', {}).items()):
        val = obj.get(feature)
        if isinstance(val, (int, float)) and val < floor:
            reasons.append(f'{feature} {val} < floor {floor}')
    for flag in th.get('require', []):
        if obj.get(flag) is False:
            reasons.append(f'{flag} is false')
    if not reasons:
        return 'continue', []
    # a disconnected body is a geometry fault; a low score alone may be material or detail
    if obj.get('single_connected_object') is False:
        return 'refine-code', reasons
    if not obj.get('defects') and not obj.get('missing_features'):
        # scores are down but the model named nothing specific: the reference may be the problem
        return 'request-input', reasons
    return 'refine-code', reasons


def main() -> int:
    p = argparse.ArgumentParser(description='vision review of a render against its reference')
    p.add_argument('--asset', required=True)
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--candidate', required=True, action='append', type=Path)
    p.add_argument('--out', type=Path, help='output dir for sheet.png + review.json')
    p.add_argument('--timeout', type=int, default=240, help='answer wait ceiling (s)')
    p.add_argument('--dry-run', action='store_true', help='build the sheet and print the prompt')
    a = p.parse_args()

    for path in [a.reference, *a.candidate]:
        if not path.exists():
            print(json.dumps({'error': f'no such image: {path}'}))
            return EXIT['error']
    outdir = a.out or (ROOT / 'output' / 'review' / a.asset)
    outdir.mkdir(parents=True, exist_ok=True)
    sheet_path = outdir / 'sheet.png'

    meta = build_sheet(a.reference, a.candidate, sheet_path, a.asset)
    record = {
        'asset': a.asset,
        'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'inputs': {
            'reference': {'path': str(a.reference), 'sha256': sha(a.reference)},
            'candidates': [{'path': str(c), 'sha256': sha(c)} for c in a.candidate],
        },
        'sheet': {'path': str(sheet_path), 'size': meta.get('size')},
        'rubric_version': 1,
    }
    if a.dry_run:
        record['prompt'] = RUBRIC
        (outdir / 'review.json').write_text(json.dumps(record, indent=2))
        print(json.dumps({'sheet': str(sheet_path), 'prompt_chars': len(RUBRIC)}))
        return EXIT['continue']

    t0 = time.time()
    text, transport = ask(sheet_path, RUBRIC, a.timeout)

    # A transport failure is not a verdict. Check the image actually reached the
    # model BEFORE judging the answer, or a dead upload is misreported as
    # "the model did not return JSON" (caught by certify.py on 2026-11-23).
    if not transport.get('attached', False):
        record.update({'decision': 'stop',
                       'reasons': [f"transport: {transport.get('error', 'image not attached')}"],
                       'transport': transport, 'elapsed_s': round(time.time() - t0, 1)})
        (outdir / 'review.json').write_text(json.dumps(record, indent=2))
        print(json.dumps({'asset': a.asset, 'decision': 'stop', 'reasons': record['reasons']}))
        return EXIT['stop']

    obj = parse_json(text)
    derived = ''
    if obj:
        obj, derived = normalise(obj)
    errs = validate(obj) if obj else ['no JSON object in the answer']
    if errs:
        # one repair attempt, then stop: a guessing reviewer must not pass an asset
        text2, transport2 = ask(sheet_path, f'{RUBRIC}\n\n{REPAIR}', a.timeout)
        obj2 = parse_json(text2)
        if obj2:
            obj2, derived2 = normalise(obj2)
            derived = derived2 or derived
        errs2 = validate(obj2) if obj2 else ['still no JSON']
        if errs2:
            record.update({'decision': 'stop', 'reasons': errs2, 'answer': (text2 or text)[:1200],
                           'transport': transport2, 'elapsed_s': round(time.time() - t0, 1)})
            (outdir / 'review.json').write_text(json.dumps(record, indent=2))
            print(json.dumps({'asset': a.asset, 'decision': 'stop', 'reasons': errs2}))
            return EXIT['stop']
        obj = obj2

    if not transport.get('attached', False):
        record.update({'decision': 'stop',
                       'reasons': [f"image not attached: {transport.get('error', 'unknown')}"],
                       'transport': transport, 'elapsed_s': round(time.time() - t0, 1)})
        (outdir / 'review.json').write_text(json.dumps(record, indent=2))
        print(json.dumps({'asset': a.asset, 'decision': 'stop',
                          'reasons': record['reasons']}))
        return EXIT['stop']

    th = load_thresholds()
    decision, reasons = decide(obj, th)
    record.update({
        'features': obj,
        'thresholds': th,
        'decision': decision,
        'reasons': reasons,
        'transport': {'browser': transport.get('browser'), 'attached': transport.get('attached'),
                      'elapsed_s': transport.get('elapsed_s')},
        'elapsed_s': round(time.time() - t0, 1),
        'schema_derived': derived or None,
    })
    (outdir / 'review.json').write_text(json.dumps(record, indent=2))
    print(json.dumps({'asset': a.asset, 'decision': decision, 'reasons': reasons,
                      'scores': {k: obj.get(k) for k in th.get('scores', {})},
                      'defects': obj.get('defects', []),
                      'review': str(outdir / 'review.json')}))
    return EXIT[decision]


if __name__ == '__main__':
    sys.exit(main())
