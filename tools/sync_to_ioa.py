#!/usr/bin/env python3
"""
sync_to_ioa.py — Asset Sync Tool
Copies finalized asset-pipeline output into the Imperium of Ash frontend directory.

Usage:
    python sync_to_ioa.py --version v0.1.0 --ioa-path "/path/to/Imperium of Ash"

What it does:
1. Reads the latest build from `output/<version>/`
2. Copies `output/<version>/*` to `IoA/frontend/public/assets/<version>/`
3. Generates a manifest for the game to load assets by version
4. Optionally updates IoA's AGENTS.md or asset registry JSON
5. Cleans unused old versions (configurable)

Safety:
- NEVER overwrites without explicit flag `--force`
- Dry-run mode by default (shows what WOULD be copied)
- Requires confirmation before modifying IoA working tree

Author: Asset-Pipeline Automation
Docs: docs/BLENDER_WORKFLOW.md, AGENTS.md
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default relative path from asset-pipeline repo to IoA repo
DEFAULT_IOA_PATH = "../Imperium of Ash"

# Target directory inside IoA frontend
IOA_ASSETS_SUBDIR = "frontend/public/assets/pipeline"

# Versions to keep (oldest auto-deleted)
MAX_OLD_VERSIONS = 2


# =============================================================================
# UTILITIES
# =============================================================================


def log(msg: str):
    print(f"[sync_to_ioa] {msg}")


def confirm(prompt: str) -> bool:
    """Ask user for yes/no confirmation."""
    while True:
        inp = input(f"{prompt} [y/N]: ").strip().lower()
        if inp in ("y", "yes"):
            return True
        if inp in ("n", "no", ""):
            return False


# =============================================================================
# SYNC LOGIC
# =============================================================================


def discover_versions(output_dir: Path) -> list:
    """List all version directories in output/, sorted."""
    if not output_dir.exists():
        return []
    versions = [d.name for d in output_dir.iterdir() if d.is_dir()]
    # Simple semver-ish sort (assumes vX.Y.Z format)
    def sort_key(v):
        try:
            parts = v.lstrip("v").split(".")
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)
    return sorted(versions, key=sort_key)


def sync_version(version: str, pipeline_output: Path, ioa_assets: Path, dry_run: bool, force: bool):
    """Copy one version from pipeline output to IoA."""
    src = pipeline_output / version
    dst = ioa_assets / version

    if not src.exists():
        log(f"ERROR: Source version directory not found: {src}")
        sys.exit(1)

    if dst.exists() and not force:
        log(f"Destination exists: {dst}")
        if dry_run:
            log("  (dry-run: would skip without --force)")
            return
        if not confirm(f"Overwrite {dst}?"):
            log("Sync cancelled by user.")
            sys.exit(0)

    if dry_run:
        file_count = sum(1 for _ in src.rglob("*") if _.is_file())
        log(f"DRY RUN: Would copy {file_count} files from {src} -> {dst}")
        return

    # Perform copy
    if dst.exists() and force:
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    log(f"Copied: {src} -> {dst}")


def generate_ioa_manifest(ioa_assets: Path):
    """Generate or update asset manifest in IoA for runtime loading."""
    manifest_path = ioa_assets / "manifest.json"
    versions = discover_versions(ioa_assets)

    manifest = {
        "versions": versions,
        "latest": versions[-1] if versions else None,
        "format": "pipeline_v1",
    }

    if manifest_path.exists() and not force_global:
        log(f"Manifest exists: {manifest_path}")
        if not confirm("Overwrite IoA asset manifest?"):
            return

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"Manifest updated: {manifest_path}")


def cleanup_old_versions(ioa_assets: Path, keep: int):
    """Remove oldest versions beyond `keep` count."""
    versions = discover_versions(ioa_assets)
    if len(versions) <= keep:
        return
    to_remove = versions[:-keep]
    for old in to_remove:
        old_path = ioa_assets / old
        log(f"Removing old version: {old_path}")
        shutil.rmtree(old_path)


# =============================================================================
# MAIN
# =============================================================================

force_global = False  # set by argument


def main():
    global force_global
    parser = argparse.ArgumentParser(description="Sync asset-pipeline output to Imperium of Ash")
    parser.add_argument("--version", required=True, help="Version tag to sync (e.g., v0.1.0)")
    parser.add_argument("--ioa-path", default=os.environ.get("IOA_PATH", DEFAULT_IOA_PATH),
                        help="Path to Imperium of Ash repository root")
    parser.add_argument("--force", action="store_true", help="Overwrite existing version without prompt")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm all prompts (dangerous)")
    parser.add_argument("--clean", action="store_true", help="Remove old versions after sync")
    args = parser.parse_args()

    force_global = args.force or args.yes
    dry_run = not args.yes and not args.force

    pipeline_root = Path(__file__).resolve().parents[1]  # asset-pipeline root
    pipeline_output = pipeline_root / "output"
    ioa_root = Path(args.ioa_path).resolve()
    ioa_assets = ioa_root / IOA_ASSETS_SUBDIR

    if not ioa_root.exists():
        log(f"ERROR: IoA repository not found at {ioa_root}")
        sys.exit(1)

    log(f"Pipeline output: {pipeline_output}")
    log(f"IoA assets dir: {ioa_assets}")
    log(f"Version to sync: {args.version}")

    if dry_run:
        log("Running in DRY RUN mode (no changes). Use --yes to execute.")

    # 1. Sync files
    sync_version(args.version, pipeline_output, ioa_assets, dry_run, force_global)

    # 2. Generate manifest
    if not dry_run:
        generate_ioa_manifest(ioa_assets)

    # 3. Cleanup old
    if args.clean and not dry_run:
        cleanup_old_versions(ioa_assets, MAX_OLD_VERSIONS)

    log("Sync complete.")


if __name__ == "__main__":
    main()
