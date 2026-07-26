#!/usr/bin/env python3
"""
critic.py — Automated visual quality analysis for rendered sprite frames.
Analyzes PNGs and produces a JSON report with pass/fail metrics + fix suggestions.

Usage:
    python critic.py <render_dir>  # e.g. output/kits/.../render/raw/idle
"""

import os
import sys
import json
import math
from pathlib import Path
from PIL import Image, ImageFilter

# =============================================================================
# THRESHOLDS
# =============================================================================

THRESHOLDS = {
    "alpha_coverage_min": 0.06,      # < 6% = invisible (humanoids N/S are ~7-12%)
    "alpha_coverage_max": 0.85,        # > 85% = probably clipped or wrong framing
    "mean_brightness_min": 40,       # 0-255 scale; < 40 = too dark
    "mean_brightness_max": 220,      # > 220 = blown out / wrong bg
    "brightness_stddev_min": 10,     # < 10 = flat, no detail
    "edge_density_min": 0.015,      # < 1.5% edge pixels = too low-poly or blurry (humanoid side views are ~1.7%)
    "direction_variance_max": 0.50,  # alpha coverage varies > 50% across dirs = asymmetric (humanoids are ~44% due to anatomy)
}

# =============================================================================
# METRICS
# =============================================================================

def analyze_frame(path: str) -> dict:
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    pixels = list(img.get_flattened_data())

    # Alpha coverage
    alpha_pixels = sum(1 for p in pixels if p[3] > 10)
    alpha_coverage = alpha_pixels / (w * h)

    # Brightness (of visible pixels only)
    visible_pixels = [(r, g, b) for r, g, b, a in pixels if a > 10]
    if not visible_pixels:
        return {
            "path": path,
            "alpha_coverage": 0.0,
            "mean_brightness": 0.0,
            "brightness_stddev": 0.0,
            "edge_density": 0.0,
            "pass": False,
            "fails": ["no_visible_pixels"],
        }

    brightnesses = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in visible_pixels]
    mean_brightness = sum(brightnesses) / len(brightnesses)
    variance = sum((b - mean_brightness) ** 2 for b in brightnesses) / len(brightnesses)
    stddev = math.sqrt(variance)

    # Edge density using Sobel-like filter (simple edge detection via find_edges)
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_pixels = sum(1 for p in edges.get_flattened_data() if p > 30)
    edge_density = edge_pixels / (w * h)

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

    return {
        "path": path,
        "alpha_coverage": round(alpha_coverage, 4),
        "mean_brightness": round(mean_brightness, 2),
        "brightness_stddev": round(stddev, 2),
        "edge_density": round(edge_density, 4),
        "pass": len(fails) == 0,
        "fails": fails,
    }


def analyze_full_render_tree(render_dir: str) -> dict:
    """Analyze all frames across all animations and directions."""
    render_path = Path(render_dir)
    all_frames = sorted(render_path.rglob("*.png"))
    if not all_frames:
        return {"overall_pass": False, "error": "no_frames_found", "frames": []}

    # Group by animation/direction for variance analysis
    direction_sets = {}
    for f in all_frames:
        # Parse path like .../idle/N/frame_01.png
        parts = f.parts
        try:
            anim_idx = parts.index("raw") + 1
            anim = parts[anim_idx]
            direction = parts[anim_idx + 1]
            key = f"{anim}/{direction}"
        except (ValueError, IndexError):
            key = "unknown"
        direction_sets.setdefault(key, []).append(f)

    all_reports = []
    set_reports = {}
    for key, frames in direction_sets.items():
        frame_reports = [analyze_frame(str(f)) for f in frames]
        passing = sum(1 for r in frame_reports if r["pass"])
        coverages = [r["alpha_coverage"] for r in frame_reports]
        if coverages:
            max_cov = max(coverages)
            min_cov = min(coverages)
            variance = (max_cov - min_cov) / max_cov if max_cov > 0 else 0
        else:
            variance = 0
        direction_variance_pass = variance <= THRESHOLDS["direction_variance_max"]
        overall_pass = (passing == len(frame_reports)) and direction_variance_pass
        set_reports[key] = {
            "overall_pass": overall_pass,
            "frames_analyzed": len(frame_reports),
            "frames_passing": passing,
            "direction_variance": round(variance, 4),
            "direction_variance_pass": direction_variance_pass,
        }
        all_reports.extend(frame_reports)

    total_frames = len(all_reports)
    total_passing = sum(1 for r in all_reports if r["pass"])
    all_coverages = [r["alpha_coverage"] for r in all_reports]
    global_variance = (max(all_coverages) - min(all_coverages)) / max(all_coverages) if max(all_coverages) > 0 else 0
    global_variance_pass = global_variance <= THRESHOLDS["direction_variance_max"]

    fail_counts = {}
    for r in all_reports:
        for f in r["fails"]:
            fail_counts[f] = fail_counts.get(f, 0) + 1

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
    if not global_variance_pass:
        suggestions.append("Asymmetric across directions. Check part attachment or rig alignment.")

    overall_pass = (total_passing == total_frames) and global_variance_pass

    return {
        "overall_pass": overall_pass,
        "total_frames": total_frames,
        "total_passing": total_passing,
        "global_direction_variance": round(global_variance, 4),
        "global_variance_pass": global_variance_pass,
        "direction_sets": set_reports,
        "common_failures": fail_counts,
        "suggestions": suggestions,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python critic.py <render_dir>")
        sys.exit(1)

    render_dir = sys.argv[1]
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
    if report["suggestions"]:
        print("[critic] Suggestions:")
        for s in report["suggestions"]:
            print(f"  - {s}")
    print(f"[critic] Report saved: {report_path}")

    sys.exit(0 if report["overall_pass"] else 1)


if __name__ == "__main__":
    main()
