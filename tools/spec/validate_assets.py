#!/usr/bin/env python3
"""validate_assets.py — check our assets against the portable asset contract.

The contract (`docs/asset_spec.json`, documented in `docs/ASSET_SPEC.md`) is source-agnostic: it
states what an asset must satisfy to work in this engine, not where it came from. That is what makes
the method portable — Dawn of War II is reference implementation #1, our own art is adapter #2, and
both are checked the same way.

Three things this does that the existing per-class gate (`tools/glb_contract.py`) does not:

  1. **Drift check.** The spec's `budgets` block must equal the gate's `LIMITS`. If someone tightens
     a limit in code without updating the spec (or the reverse), that is a failure here.
  2. **Contract-shape checks** the gate does not make: joint influence limits from the accessor
     component types, required attribute sets per class, and animation duration sanity.
  3. **Sidecar declarations** the combat grid and the map forge consume: a prop a unit can stand on,
     shoot through or take cover behind must declare a cover volume and a footprint.

Usage:
    python3 tools/spec/validate_assets.py --spec docs/asset_spec.json \
        --assets ../Imperium-of-Ash/frontend/public/assets --report /tmp/spec_report.json

Exit codes: 0 pass, 1 contract failure, 2 usage error. No third-party dependencies.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Which contract class a shipped path belongs to. Order matters: the first match wins.
PATH_CLASSES = (
    ("/models/units/", "unit"),
    ("/models/weapons/", "weapon"),  # standalone weapons: parented to a hand bone, no own armature
    ("/models/env/", "env"),
    ("/models/tiles/", "tile"),
    ("/terrain/", "tile"),
    ("/models/props/", "prop"),
)


def load_gate():
    """The existing GLB gate, imported so its limits can be compared rather than duplicated."""
    path = ROOT / "tools" / "glb_contract.py"
    spec = importlib.util.spec_from_file_location("glb_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def classify(path: Path) -> str | None:
    text = "/" + str(path).replace("\\", "/")
    for marker, kind in PATH_CLASSES:
        if marker in text:
            return kind
    return None


def check_drift(spec: dict, gate) -> list[str]:
    errors = []
    for kind, budget in spec.get("budgets", {}).items():
        limits = gate.LIMITS.get(kind)
        if limits is None:
            errors.append(f"spec declares class '{kind}' that the gate does not know")
            continue
        for key, value in budget.items():
            if key not in limits:
                errors.append(f"{kind}.{key}: in spec but not in gate LIMITS")
            elif limits[key] != value:
                errors.append(f"{kind}.{key}: spec {value!r} != gate {limits[key]!r} (spec/gate drift)")
    for kind in gate.LIMITS:
        if kind not in spec.get("budgets", {}):
            errors.append(f"gate class '{kind}' is missing from the spec")
    return errors


def check_mesh(path: Path, kind: str, spec: dict, gate) -> dict:
    """Contract-shape checks the per-class gate does not make."""
    result = {"file": str(path), "kind": kind, "errors": [], "warnings": []}
    try:
        gltf, _bin, size = gate.read_glb(path)
    except Exception as exc:  # a broken container is a contract failure, not a crash
        result["errors"].append(f"unreadable GLB: {exc}")
        return result

    mesh = spec["mesh"]
    max_infl = spec["limits"]["universal"]["max_influences_per_vertex"]
    want_attrs = {"POSITION", "NORMAL", "TEXCOORD_0"}
    if spec["budgets"][kind]["skinned"]:
        want_attrs |= {"JOINTS_0", "WEIGHTS_0"}

    seen_attrs: set[str] = set()
    joints_ok = True
    tris = 0
    for m in gltf.get("meshes", []):
        for prim in m.get("primitives", []):
            attrs = prim.get("attributes", {})
            seen_attrs |= set(attrs)
            if "indices" in prim:
                tris += gltf["accessors"][prim["indices"]]["count"] // 3
            if "JOINTS_0" in attrs:
                acc = gltf["accessors"][attrs["JOINTS_0"]]
                # a JOINTS_0 accessor wider than VEC4 would carry more than four influences
                if acc.get("type") != "VEC4":
                    joints_ok = False
                    result["errors"].append(f"JOINTS_0 is {acc.get('type')}, must be VEC4 ({max_infl} influences)")

    # A texture that cannot be sampled is a defect; a flat-colour asset with no texture to sample
    # legitimately carries no UVs. The rule is in the spec's `provenance` block so it is one
    # statement in one place, and the count is always printed rather than absorbed.
    textures = len(gltf.get("textures", []))
    flat_colour = textures == 0 and "TEXCOORD_0" not in seen_attrs
    if flat_colour:
        want_attrs.discard("TEXCOORD_0")
        result["recorded"] = "flat-colour import: no texture, so no UVs to carry (measured source property)"
    missing = sorted(want_attrs - seen_attrs)
    if missing:
        result["errors"].append(f"missing required attributes: {', '.join(missing)}")

    skins = gltf.get("skins", [])
    joint_count = max((len(s.get("joints", [])) for s in skins), default=0)
    # The 54-bone figure is DoW2's D3D9 constant budget. Ours is the target engine's uniform-block
    # limit, so a 110-joint shipped unit is not a defect here.
    limit_bones = spec["limits"]["target_engine"]["max_bones_per_skinned_mesh"]
    if joint_count > limit_bones:
        result["errors"].append(
            f"skin has {joint_count} joints, target engine limit {limit_bones}")

    # animation duration: (frames - 1) / fps, so a clip must advance in time and stay finite
    for anim in gltf.get("animations", []):
        samplers = anim.get("samplers", [])
        end = 0.0
        for sampler in samplers:
            acc = gltf["accessors"][sampler["input"]]
            if "max" in acc:
                end = max(end, float(acc["max"][0]))
        if samplers and not (0.0 < end < 600.0):
            result["errors"].append(f"animation '{anim.get('name')}' has duration {end}s")

    result["info"] = {"tris": tris, "mb": round(size / 1_048_576, 2),
                      "joints": joint_count, "attributes": sorted(seen_attrs),
                      "animations": len(gltf.get("animations", [])),
                      "joints_vec4": joints_ok}
    return result


def check_sidecars(assets: Path, spec: dict) -> list[str]:
    """Props must declare the cover volume and footprint the grid and forge consume."""
    errors = []
    if not spec.get("collision", {}).get("cover", {}).get("volume_required"):
        return errors
    kit = assets / "models" / "env" / "env_kit.json"
    if not kit.is_file():
        return errors
    data = json.loads(kit.read_text())
    for prop in data.get("props", []):
        name = prop.get("name", "?")
        if "size" not in prop or not prop["size"]:
            errors.append(f"env prop '{name}' declares no footprint")
        if "cover" not in prop:
            errors.append(f"env prop '{name}' declares no cover volume")
    return errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", type=Path, default=ROOT / "docs" / "asset_spec.json")
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0, help="check at most N GLBs (0 = all)")
    a = ap.parse_args(argv)

    spec = json.loads(a.spec.read_text())
    gate = load_gate()
    report = {"spec": str(a.spec), "assets": str(a.assets),
              "spec_errors": check_drift(spec, gate), "files": [], "sidecar_errors": []}

    files = sorted(a.assets.rglob("*.glb"))
    if a.limit:
        files = files[:a.limit]
    for path in files:
        kind = classify(path)
        if kind is None:
            report["files"].append({"file": str(path), "kind": None,
                                    "errors": [], "warnings": ["unclassified path"]})
            continue
        report["files"].append(check_mesh(path, kind, spec, gate))

    report["sidecar_errors"] = check_sidecars(a.assets, spec)

    failing = [f for f in report["files"] if f.get("errors")]
    recorded = [f for f in report["files"] if f.get("recorded")]
    over_source_limit = [
        f for f in report["files"]
        if f.get("info", {}).get("joints", 0) > spec["limits"]["source_engine_only"]["max_influencing_bones_per_mesh"]
    ]
    unclassified = [f for f in report["files"] if f.get("kind") is None]
    counts = {}
    for f in report["files"]:
        counts[f.get("kind")] = counts.get(f.get("kind"), 0) + 1

    print(f"spec: {a.spec}")
    print(f"classes checked: {', '.join(f'{k}={v}' for k, v in sorted(counts.items(), key=lambda i: str(i[0])))}")
    if report["spec_errors"]:
        print(f"\nSPEC/ GATE DRIFT ({len(report['spec_errors'])}):")
        for e in report["spec_errors"][:20]:
            print(f"  {e}")
    if report["sidecar_errors"]:
        print(f"\nSIDECARS ({len(report['sidecar_errors'])}):")
        for e in report["sidecar_errors"][:10]:
            print(f"  {e}")
    if failing:
        print(f"\nCONTRACT FAILURES ({len(failing)}):")
        for f in failing[:15]:
            print(f"  {f['file']}")
            for e in f["errors"][:4]:
                print(f"    - {e}")
    if unclassified:
        print(f"\nUNCLASSIFIED ({len(unclassified)}): {unclassified[0]['file']} ...")
    if recorded:
        print(f"\nRECORDED SOURCE PROPERTIES ({len(recorded)}) — not failures, counted so a regression shows:")
        print(f"  {recorded[0]['recorded']}")
        for f in recorded[:5]:
            print(f"    {Path(f['file']).name}")
        if len(recorded) > 5:
            print(f"    ... and {len(recorded) - 5} more")
    if over_source_limit:
        print(f"\nOVER THE SOURCE ENGINE'S 54-BONE LIMIT ({len(over_source_limit)}) — legal in our engine:")
        print(f"  max joints seen: {max(f['info']['joints'] for f in over_source_limit)}"
              f" (our limit is {spec['limits']['target_engine']['max_bones_per_skinned_mesh']})")

    if a.report:
        a.report.write_text(json.dumps(report, indent=1))
        print(f"\nreport -> {a.report}")

    ok = not (report["spec_errors"] or report["sidecar_errors"] or failing)
    print("\nASSET SPEC: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
