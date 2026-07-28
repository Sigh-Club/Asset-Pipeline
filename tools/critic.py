#!/usr/bin/env python3
"""
critic.py — Automated visual quality analysis for rendered sprite frames.
Analyzes PNGs and produces a JSON report with pass/fail metrics + fix suggestions.

Usage:
    python critic.py <render_dir>  # e.g. output/kits/.../render/raw/idle
    python critic.py <render_dir> --verbose  # Print per-direction metric averages
"""

import os
import sys
import json
import math
from pathlib import Path
from collections import defaultdict
from PIL import Image, ImageFilter

# =============================================================================
# THRESHOLDS
# =============================================================================

THRESHOLDS = {
    # Minimum acceptable thresholds (hard failures)
    "alpha_coverage_min": 0.06,         # < 6% = invisible
    "alpha_coverage_max": 0.85,         # > 85% = clipped or wrong framing
    "mean_brightness_min": 40,          # 0-255; < 40 = too dark
    "mean_brightness_max": 220,         # > 220 = blown out
    "brightness_stddev_min": 10,        # < 10 = flat, no detail
    "edge_density_min": 0.08,           # < 8% alpha-normalised = too flat (hard-surface floor)
    "direction_variance_max": 0.50,     # alpha coverage varies > 50% = asymmetric
    "unique_colors_min": 50,            # < 50 unique colours = material detail too uniform
    # Dawn of War 1/2 target thresholds (alpha-normalised edge density, informational)
    "dow_edge_density_low": 0.08,       # 8% = minimum for visible hard-surface detail
    "dow_edge_density_target": 0.14,    # 14% = DoW1 baseline (12-16% band)
    "dow_edge_density_ideal": 0.26,     # 26% = DoW2 high-detail (22-30% band)
    "dow_unique_colors_target": 200,    # 200+ = material variation target
}

# =============================================================================
# PATH PARSING
# =============================================================================

def _parse_anim_direction(file_path: Path) -> tuple:
    """Extract animation name and direction from file path.
    
    Tries multiple path structures:
      .../raw/{anim}/{direction}/frame_XX.png
      .../processed/{anim}/{direction}/frame_XX.png
      .../{anim}/{direction}/frame_XX.png
      .../frame_XX.png (no grouping)
    Returns (anim, direction) or ("unknown", "unknown").
    """
    parts = file_path.parts
    filename = file_path.name

    # Strategy 1: look for known animation/direction keywords in the path
    known_anims = {"idle", "walk", "attack", "hurt", "die", "move", "scuttle", "destroy"}
    known_dirs = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}

    # Walk from the end of the path backward to find direction then animation
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in known_dirs:
            direction = parts[i]
            if i > 0 and parts[i - 1] in known_anims:
                return parts[i - 1], direction
            return "unknown", direction

    # Strategy 2: check if filename contains pattern like idle_N_01.png
    stem = file_path.stem
    for anim in known_anims:
        if anim in stem:
            for d in known_dirs:
                if f"_{d}_" in stem or stem.endswith(f"_{d}") or f"{anim}_{d}" in stem:
                    return anim, d
            return anim, "unknown"

    return "unknown", "unknown"


# =============================================================================
# METRICS
# =============================================================================

def analyze_frame(path: str) -> dict:
    """Analyze a single PNG frame for quality metrics."""
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    pixels = list(img.getdata())

    # Alpha coverage
    alpha_pixels = sum(1 for p in pixels if p[3] > 10)
    alpha_coverage = alpha_pixels / (w * h)

    # Brightness (of visible pixels only)
    visible_pixels = [(r, g, b) for r, g, b, a in pixels if a > 10]
    if not visible_pixels:
        return {
            "path": str(path),
            "alpha_coverage": 0.0,
            "mean_brightness": 0.0,
            "brightness_stddev": 0.0,
            "edge_density": 0.0,
            "unique_colors": 0,
            "pass": False,
            "fails": ["no_visible_pixels"],
        }

    brightnesses = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in visible_pixels]
    mean_brightness = sum(brightnesses) / len(brightnesses)
    variance = sum((b - mean_brightness) ** 2 for b in brightnesses) / len(brightnesses)
    stddev = math.sqrt(variance)

    # Edge density using Sobel-like filter, NORMALISED to the sprite's alpha footprint
    # (not the full frame). The old edge_pixels/(w*h) metric was miscalibrated: with
    # ~14% alpha coverage, 15% frame-normalised edge density is mathematically impossible.
    # Alpha-normalised: DoW1 calibre = 12-16%, DoW2 calibre = 22-30%. See DEVELOPMENT.md.
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_data = list(edges.getdata())
    alpha_vals = [p[3] for p in pixels]
    edge_pixels_in_sprite = sum(1 for ep, a in zip(edge_data, alpha_vals) if ep > 30 and a > 10)
    edge_density = edge_pixels_in_sprite / max(alpha_pixels, 1)
    edge_density_frame = sum(1 for ep in edge_data if ep > 30) / (w * h)  # legacy, for reference

    # Unique colours in visible area
    visible_pixel_tuples = {(r, g, b) for r, g, b in visible_pixels if not (r == 0 and g == 0 and b == 0)}
    unique_colors = len(visible_pixel_tuples)

    fails = []
    if alpha_coverage < THRESHOLDS["alpha_coverage_min"]:
        fails.append("alpha_coverage_low")
    if alpha_coverage > THRESHOLDS["alpha_coverage_max"]:
        fails.append("alpha_coverage_high")
    if mean_brightness < THRESHOLDS["mean_brightness_min"]:
        fails.append("brightness_low")
    if mean_brightness > THRESHOLDS["mean_brightness_max"]:
        fails.append("brightness_high")
    if stddev < THRESHOLDS["brightness_stddev_min"]:
        fails.append("contrast_low")
    if edge_density < THRESHOLDS["edge_density_min"]:
        fails.append("edge_density_low")
    if unique_colors < THRESHOLDS["unique_colors_min"]:
        fails.append("unique_colors_low")

    return {
        "path": str(path),
        "alpha_coverage": round(alpha_coverage, 4),
        "mean_brightness": round(mean_brightness, 2),
        "brightness_stddev": round(stddev, 2),
        "edge_density": round(edge_density, 4),
        "unique_colors": unique_colors,
        "pass": len(fails) == 0,
        "fails": fails,
    }


def analyze_full_render_tree(render_dir: str) -> dict:
    """Analyze all frames across all animations and directions with expanded metrics."""
    render_path = Path(render_dir)
    all_frames = sorted(render_path.rglob("*.png"))
    if not all_frames:
        return {"overall_pass": False, "error": "no_frames_found", "frames": []}

    # Group by animation/direction
    direction_sets = defaultdict(list)
    for f in all_frames:
        anim, direction = _parse_anim_direction(f)
        key = f"{anim}/{direction}" if anim != "unknown" else "unknown"
        direction_sets[key].append(f)

    all_reports = {}
    set_reports = {}
    # Aggregate per-direction-set metrics
    for key, frames in direction_sets.items():
        frame_reports = [analyze_frame(str(f)) for f in frames]
        passing = sum(1 for r in frame_reports if r["pass"])
        
        # Collect metrics over this set
        coverages = [r["alpha_coverage"] for r in frame_reports]
        brightnesses = [r["mean_brightness"] for r in frame_reports]
        stddevs = [r["brightness_stddev"] for r in frame_reports]
        edges = [r["edge_density"] for r in frame_reports]
        colors = [r["unique_colors"] for r in frame_reports]
        
        if coverages:
            max_cov = max(coverages)
            min_cov = min(coverages)
            variance = (max_cov - min_cov) / max_cov if max_cov > 0 else 0
        else:
            variance = 0
            
        direction_variance_pass = variance <= THRESHOLDS["direction_variance_max"]
        overall_pass = (passing == len(frame_reports)) and direction_variance_pass
        
        # Build per-frame detail (limited to first 3 frames to keep report size manageable)
        frame_samples = [
            {
                "file": Path(r["path"]).name,
                "edge_density": r["edge_density"],
                "mean_brightness": r["mean_brightness"],
                "alpha_coverage": r["alpha_coverage"],
                "unique_colors": r["unique_colors"],
                "pass": r["pass"],
            }
            for r in frame_reports[:3]
        ]
        
        set_reports[key] = {
            "overall_pass": overall_pass,
            "frames_analyzed": len(frame_reports),
            "frames_passing": passing,
            "direction_variance": round(variance, 4),
            "direction_variance_pass": direction_variance_pass,
            # Per-direction-set average metrics
            "avg_edge_density": round(sum(edges) / len(edges), 4) if edges else 0,
            "avg_brightness": round(sum(brightnesses) / len(brightnesses), 2) if brightnesses else 0,
            "avg_stddev": round(sum(stddevs) / len(stddevs), 2) if stddevs else 0,
            "avg_alpha_coverage": round(sum(coverages) / len(coverages), 4) if coverages else 0,
            "avg_unique_colors": round(sum(colors) / len(colors), 0) if colors else 0,
            # DoW target comparison
            "dow_edge_density_gap": max(0, round(THRESHOLDS["dow_edge_density_target"] - (sum(edges) / len(edges) if edges else 0), 4)),
            "frame_samples": frame_samples,
        }
        all_reports.update({str(f): r for f, r in zip(frames, frame_reports)})

    total_frames = len(all_reports)
    total_passing = sum(1 for r in all_reports.values() if r["pass"])
    all_coverages = [r["alpha_coverage"] for r in all_reports.values()]
    global_variance = (max(all_coverages) - min(all_coverages)) / max(all_coverages) if max(all_coverages) > 0 else 0
    global_variance_pass = global_variance <= THRESHOLDS["direction_variance_max"]

    # Aggregate fail counts
    fail_counts = {}
    for r in all_reports.values():
        for f in r["fails"]:
            fail_counts[f] = fail_counts.get(f, 0) + 1

    # Per-animation rollup
    animation_summaries = defaultdict(lambda: {"frames": 0, "passing": 0, "edge_densities": [], "brightnesses": [], "stddevs": [], "colors": []})
    for r in all_reports.values():
        anim, _ = _parse_anim_direction(Path(r["path"]))
        if anim != "unknown":
            s = animation_summaries[anim]
            s["frames"] += 1
            s["passing"] += 1 if r["pass"] else 0
            s["edge_densities"].append(r["edge_density"])
            s["brightnesses"].append(r["mean_brightness"])
            s["stddevs"].append(r["brightness_stddev"])
            s["colors"].append(r["unique_colors"])

    animation_summary_output = {}
    for anim, summary in sorted(animation_summaries.items()):
        avg_edge = sum(summary["edge_densities"]) / len(summary["edge_densities"]) if summary["edge_densities"] else 0
        max_edge = max(summary["edge_densities"]) if summary["edge_densities"] else 0
        min_edge = min(summary["edge_densities"]) if summary["edge_densities"] else 0
        avg_bright = sum(summary["brightnesses"]) / len(summary["brightnesses"]) if summary["brightnesses"] else 0
        avg_colors = sum(summary["colors"]) / len(summary["colors"]) if summary["colors"] else 0
        max_colors = max(summary["colors"]) if summary["colors"] else 0
        animation_summary_output[anim] = {
            "frames": summary["frames"],
            "passing": summary["passing"],
            "pass_rate": round(summary["passing"] / summary["frames"], 4) if summary["frames"] else 0,
            "avg_edge_density": round(avg_edge, 4),
            "max_edge_density": round(max_edge, 4),
            "min_edge_density": round(min_edge, 4),
            "avg_brightness": round(avg_bright, 2),
            "avg_unique_colors": round(avg_colors, 0),
            "max_unique_colors": int(max_colors),
            "dow_edge_gap": max(0, round(THRESHOLDS["dow_edge_density_target"] - avg_edge, 4)),
        }

    # Suggestions
    suggestions = []
    if "alpha_coverage_low" in fail_counts:
        suggestions.append("Model too small or invisible. Reduce ortho_scale or scale up model.")
    if "alpha_coverage_high" in fail_counts:
        suggestions.append("Model fills too much frame. Increase ortho_scale or check framing.")
    if "brightness_low" in fail_counts:
        suggestions.append("Too dark. Boost light energy or brighten materials.")
    if "brightness_high" in fail_counts:
        suggestions.append("Blown out. Reduce light energy or darken materials.")
    if "contrast_low" in fail_counts:
        suggestions.append("Too flat. Increase key/fill ratio or add rim light.")
    if "edge_density_low" in fail_counts:
        suggestions.append("Too few edges. Check if model is too low-poly or resolution too low.")
    if "unique_colors_low" in fail_counts:
        suggestions.append("Too few unique colours. Add material variation (wear, faction markings).")

    # DoW target gap analysis
    all_edge_densities = [r["edge_density"] for r in all_reports.values()]
    avg_edge_density = sum(all_edge_densities) / len(all_edge_densities) if all_edge_densities else 0
    max_edge_density = max(all_edge_densities) if all_edge_densities else 0
    min_edge_density = min(all_edge_densities) if all_edge_densities else 0
    
    if avg_edge_density < THRESHOLDS["dow_edge_density_low"]:
        suggestions.append(f"AVG edge density {avg_edge_density:.2%} (alpha-normalised) — below {THRESHOLDS['dow_edge_density_low']:.0%} hard-surface minimum. Add more geometric detail or normal maps.")
    elif avg_edge_density < THRESHOLDS["dow_edge_density_target"]:
        suggestions.append(f"AVG edge density {avg_edge_density:.2%} (alpha-normalised) — below {THRESHOLDS['dow_edge_density_target']:.0%} DoW1 target. Gap: {THRESHOLDS['dow_edge_density_target'] - avg_edge_density:.2%}. Denser painted detail / AO will help bridge this.")
    else:
        suggestions.append(f"AVG edge density {avg_edge_density:.2%} (alpha-normalised) — within DoW target range ({THRESHOLDS['dow_edge_density_target']:.0%}-{THRESHOLDS['dow_edge_density_ideal']:.0%}).")

    if not global_variance_pass:
        suggestions.append("Asymmetric across directions. Check part attachment or rig alignment.")

    overall_pass = (total_passing == total_frames) and global_variance_pass

    return {
        "overall_pass": overall_pass,
        "total_frames": total_frames,
        "total_passing": total_passing,
        "global_direction_variance": round(global_variance, 4),
        "global_variance_pass": global_variance_pass,
        # DoW target comparison at global level
        "dow_analysis": {
            "avg_edge_density": round(avg_edge_density, 4),
            "max_edge_density": round(max_edge_density, 4),
            "min_edge_density": round(min_edge_density, 4),
            "dow_edge_density_low_target": THRESHOLDS["dow_edge_density_low"],
            "dow_edge_density_target": THRESHOLDS["dow_edge_density_target"],
            "dow_edge_density_ideal": THRESHOLDS["dow_edge_density_ideal"],
            "edge_density_gap_to_low": max(0, round(THRESHOLDS["dow_edge_density_low"] - avg_edge_density, 4)),
            "edge_density_gap_to_target": max(0, round(THRESHOLDS["dow_edge_density_target"] - avg_edge_density, 4)),
            "within_dow_range": avg_edge_density >= THRESHOLDS["dow_edge_density_low"],
        },
        "direction_sets": set_reports,
        "animation_summaries": animation_summary_output,
        "common_failures": fail_counts,
        "suggestions": suggestions,
    }


def main():
    verbose = "--verbose" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if len(args) < 1:
        print("Usage: python critic.py <render_dir> [--verbose]")
        sys.exit(1)

    render_dir = args[0]
    report = analyze_full_render_tree(render_dir)

    if "error" in report:
        print(f"[critic] ERROR: {report['error']}")
        sys.exit(1)

    report_path = os.path.join(render_dir, "critic_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    status = "PASS" if report["overall_pass"] else "FAIL"
    print(f"[critic] {status} — {report['total_passing']}/{report['total_frames']} frames pass")
    print(f"[critic] Global direction variance: {report['global_direction_variance']:.2%} (max {THRESHOLDS['direction_variance_max']:.0%})")
    
    if "dow_analysis" in report:
        da = report["dow_analysis"]
        print(f"[critic] Edge density: avg={da['avg_edge_density']:.2%} min={da['min_edge_density']:.2%} max={da['max_edge_density']:.2%}")
        print(f"[critic] DoW target: {da['dow_edge_density_low_target']:.0%}(low)-{da['dow_edge_density_target']:.0%}(tgt)-{da['dow_edge_density_ideal']:.0%}(ideal)")
        print(f"[critic] DoW gap: {da['edge_density_gap_to_target']:.2%} below 15% target")
    
    if verbose and "animation_summaries" in report:
        print(f"\n[critic] Per-animation quality:")
        for anim, s in sorted(report["animation_summaries"].items()):
            print(f"  {anim}: pass={s['passing']}/{s['frames']} edge={s['avg_edge_density']:.2%} bright={s['avg_brightness']:.0f}/255 colors={s['avg_unique_colors']:.0f}")

    if report["suggestions"]:
        print("[critic] Suggestions:")
        for s in report["suggestions"]:
            print(f"  - {s}")
    print(f"[critic] Report saved: {report_path}")

    sys.exit(0 if report["overall_pass"] else 1)


if __name__ == "__main__":
    main()
