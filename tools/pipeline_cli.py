#!/usr/bin/env python3
"""
pipeline_cli.py — Unified entry point for the IoA asset pipeline.

Routes commands to the correct sub-pipeline based on asset type.
Handles versioning, orchestration, and quality gates for all asset types.

Usage:
    # List available commands
    python pipeline_cli.py --help

    # Generate + render a character unit
    python pipeline_cli.py character generate --config configs/iron_directorate/line_infantry.json
    python pipeline_cli.py character render --unit line_infantry --engine CYCLES

    # Full pipeline (generate → render → pack → sync)
    python pipeline_cli.py character full --config configs/iron_directorate/line_infantry.json

    # Batch all characters
    python pipeline_cli.py character batch --config-dir configs/iron_directorate/

    # Generate tiles
    python pipeline_cli.py tile generate --tile-set urban_concrete --output-dir assets/units/tiles/

    # Generate UI elements
    python pipeline_cli.py ui icons --output-dir assets/ui/icons/
    python pipeline_cli.py ui buttons --theme iron_directorate

    # Quality check
    python pipeline_cli.py critic --dir assets/units/line_infantry/model/render/raw/
    python pipeline_cli.py critic batch --check-dir assets/units/

    # Pack and sync
    python pipeline_cli.py pack --unit line_infantry --version v0.4.0
    python pipeline_cli.py sync --version v0.4.0 --target ../imperium-of-ash/frontend/public/assets/atlases/

    # Materials
    python pipeline_cli.py materials generate
    python pipeline_cli.py materials list

    # Pipeline info and maintenance
    python pipeline_cli.py info
    python pipeline_cli.py doctor              # check all tool dependencies
"""

import os
import sys
import json
import signal
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)


# =============================================================================
# BLENDER PROCESS MANAGEMENT
# =============================================================================

def kill_blender_processes(include_gui: bool = False):
    """Force-kill all stale Blender --background processes.

    Prevents resource exhaustion from orphaned/crashed renders.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-x", "blender"],
            capture_output=True, text=True, timeout=5,
        )
        if not result.stdout.strip():
            return

        killed = 0
        for pid_str in result.stdout.strip().split():
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
                cmdline = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "args="],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()

                is_background = "--background" in cmdline
                is_gui = not is_background and "blender" in cmdline.lower()

                if is_background or (include_gui and is_gui):
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                    log(f"Killed stale blender PID {pid}")
            except (ProcessLookupError, OSError, ValueError):
                pass

        if killed > 0:
            import time as _t
            _t.sleep(0.5)
            log(f"Cleaned {killed} stale Blender process(es)")
    except FileNotFoundError:
        pass  # pgrep not available
    except subprocess.TimeoutExpired:
        pass

# =============================================================================
# PATHS (anchored to project root — NEVER hardcode absolute paths)
# =============================================================================

PATHS = {
    "project_root": PROJECT_ROOT,
    "tools": SCRIPT_DIR,
    "assets": os.path.join(PROJECT_ROOT, "assets"),
    "configs": os.path.join(PROJECT_ROOT, "configs"),
    "output": os.path.join(PROJECT_ROOT, "output"),
    "palette": os.path.join(PROJECT_ROOT, "assets", "palettes", "grimdark_64.gpl"),
    "materials_blend": os.path.join(PROJECT_ROOT, "assets", "materials", "grimdark_materials.blend"),
    "material_script": os.path.join(SCRIPT_DIR, "blender", "create_material_library.py"),
    "texture_generator": os.path.join(SCRIPT_DIR, "pbr", "gen_procedural_textures.py"),
    "unit_generator": os.path.join(SCRIPT_DIR, "blender", "parametric_unit_generator.py"),
    "render_script": os.path.join(SCRIPT_DIR, "blender", "render_8dir_v2.py"),
    "pixelate_script": os.path.join(SCRIPT_DIR, "gimp", "batch_pixelate.py"),
    "packer_script": os.path.join(SCRIPT_DIR, "packer", "pack_sprites.py"),
    "batch_script": os.path.join(SCRIPT_DIR, "batch_pipeline.py"),
    "critic_script": os.path.join(SCRIPT_DIR, "critic.py"),
    "sync_script": os.path.join(SCRIPT_DIR, "sync_to_ioa.py"),
    "icon_script": os.path.join(SCRIPT_DIR, "generate_status_icons.py"),
    "units_dir": os.path.join(PROJECT_ROOT, "assets", "units"),
}

# =============================================================================
# VERSION MANAGEMENT
# =============================================================================

CURRENT_VERSION = "v0.5.0"
VERSIONS_FILE = os.path.join(PROJECT_ROOT, ".pipeline_version")


def get_latest_version() -> str:
    """Get the latest pipeline version from file, or return default."""
    if os.path.exists(VERSIONS_FILE):
        with open(VERSIONS_FILE) as f:
            return f.read().strip()
    return CURRENT_VERSION


def set_latest_version(version: str):
    """Persist the current pipeline version."""
    with open(VERSIONS_FILE, "w") as f:
        f.write(version.strip())
    print(f"[pipeline] Version set to {version}")


def versioned_output_dir(version: str = None) -> str:
    """Get the versioned output directory, creating it if needed."""
    v = version or get_latest_version()
    out = os.path.join(PATHS["output"], v)
    os.makedirs(out, exist_ok=True)
    return out


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO"):
    print(f"[pipeline] {level}: {msg}")


def run_command(cmd: list, cwd: str = None, check: bool = True) -> int:
    """Run a shell command and return exit code."""
    log(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, check=check)
        return result.returncode
    except subprocess.CalledProcessError as e:
        log(f"Command failed with exit code {e.returncode}", "ERROR")
        return e.returncode
    except FileNotFoundError:
        log(f"Command not found: {cmd[0]}", "ERROR")
        return 1


# =============================================================================
# SUB-COMMANDS — CHARACTER PIPELINE
# =============================================================================

def cmd_character_generate(args):
    """Generate a rigged .blend from a JSON config."""
    kill_blender_processes()
    if not args.config:
        log("No config file specified. Use --config <path>", "ERROR")
        return 1
    if not os.path.exists(args.config):
        log(f"Config not found: {args.config}", "ERROR")
        return 1
    return run_command([
        "blender", "--background", "--python", PATHS["unit_generator"],
        "--", "--config", args.config
    ])


def cmd_character_render(args):
    """Render all 8 directions × 5 animations for a unit."""
    kill_blender_processes()
    units_dir = PATHS["units_dir"]
    if args.unit:
        # Find the .blend file for this unit — prefer model/ subdir and v2
        unit_dir = Path(units_dir) / args.unit
        if unit_dir.exists():
            # Check model/ subdirectory first (canonical location)
            model_blends = list((unit_dir / "model").rglob("*.blend"))
            if model_blends:
                blend_files = model_blends
            else:
                blend_files = list(unit_dir.rglob("*.blend"))
        else:
            # Fallback: search by name
            blend_files = list(Path(units_dir).rglob(f"**/{args.unit}*.blend"))
        if not blend_files:
            log(f"No .blend found for unit '{args.unit}' in {units_dir}", "ERROR")
            return 1
        # Prefer v2 blends if multiple exist
        v2_blends = [f for f in blend_files if "v2" in f.name.lower()]
        blend_path = str((v2_blends or blend_files)[0])
    else:
        log("No unit specified. Use --unit <name>", "ERROR")
        return 1

    engine = args.engine or "CYCLES"
    extra_args = ["--engine", engine]
    if args.no_depth:
        extra_args.append("--no-depth")
    if args.no_normal:
        extra_args.append("--no-normal")
    if getattr(args, 'fast', False):
        extra_args.append("--fast")
    if getattr(args, 'samples', None):
        extra_args.extend(["--samples", str(args.samples)])

    return run_command([
        "blender", "--background", blend_path, "--python", PATHS["render_script"],
        "--", *extra_args
    ])


def cmd_character_full(args):
    """Full pipeline: generate → render → pack for a single unit."""
    log(f"Full character pipeline for config: {args.config}")

    # Step 1: Generate
    if cmd_character_generate(args) != 0:
        log("Generation failed, aborting full pipeline", "ERROR")
        return 1

    # Step 2: Render
    # Extract unit_name from config for render step
    try:
        with open(args.config) as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log(f"Failed to read config: {e}", "ERROR")
        return 1

    unit_name = config.get("unit_name", "")
    if not unit_name:
        log("Config missing 'unit_name'", "ERROR")
        return 1

    render_args = argparse.Namespace(
        unit=unit_name,
        engine=args.engine or "CYCLES",
        no_depth=args.no_depth or False,
        no_normal=args.no_normal or False,
    )
    if cmd_character_render(render_args) != 0:
        log("Render failed, aborting full pipeline", "ERROR")
        return 1

    # Step 3: Run critic
    raw_dir = os.path.join(PATHS["units_dir"], unit_name, "model", "render", "raw")
    if os.path.exists(raw_dir):
        critic_result = run_command(
            ["python3", PATHS["critic_script"], raw_dir],
            check=False
        )
        if critic_result != 0:
            log(f"Critic failed for {unit_name} — check render quality", "WARN")

    # Step 4: Post-process and pack via batch pipeline
    log("Running batch pipeline for pack...")
    return run_command(["python3", PATHS["batch_script"]])


def cmd_character_batch(args):
    """Generate + render + pack all units in a config directory."""
    config_dir = args.config_dir
    if not config_dir or not os.path.isdir(config_dir):
        log(f"Invalid config directory: {config_dir}", "ERROR")
        return 1

    configs = sorted([
        os.path.join(config_dir, f)
        for f in os.listdir(config_dir)
        if f.endswith(".json")
    ])
    log(f"Batch processing {len(configs)} configs from {config_dir}")

    successes = 0
    failures = 0
    for cfg in configs:
        log(f"--- Processing {os.path.basename(cfg)} ---")
        result = cmd_character_full(argparse.Namespace(
            config=cfg,
            engine=args.engine or "CYCLES",
            no_depth=args.no_depth or False,
            no_normal=args.no_normal or False,
        ))
        if result == 0:
            successes += 1
        else:
            failures += 1
            log(f"FAILED: {os.path.basename(cfg)}", "ERROR")

    log(f"Batch complete: {successes} succeeded, {failures} failed")
    return 0 if failures == 0 else 1


# =============================================================================
# SUB-COMMANDS — TILE PIPELINE (new)
# =============================================================================

def cmd_tile_generate(args):
    """Generate a tile set using Blender."""
    tile_set = args.tile_set or "urban_concrete"
    output_dir = args.output_dir or os.path.join(PATHS["units_dir"], "tiles", tile_set, "model")
    os.makedirs(output_dir, exist_ok=True)

    log(f"Tile pipeline: generating tile set '{tile_set}' -> {output_dir}")

    # Check if a tile generation script exists
    tile_script = os.path.join(SCRIPT_DIR, "blender", "tile_generator.py")
    if not os.path.exists(tile_script):
        log(f"Tile generator script not found at {tile_script}", "WARN")
        log("Create tools/blender/tile_generator.py for procedural tile generation")
        return 0

    return run_command([
        "blender", "--background", "--python", tile_script,
        "--", "--tile-set", tile_set, "--output", output_dir
    ])


def cmd_tile_render(args):
    """Render a tile set."""
    tile_set = args.tile_set or "urban_concrete"
    blend_dir = os.path.join(PATHS["units_dir"], "tiles", tile_set, "model")
    blend_files = list(Path(blend_dir).rglob("*.blend"))
    if not blend_files:
        log(f"No .blend files found in {blend_dir}", "ERROR")
        return 1
    blend_path = str(blend_files[0])

    # Use a tile-specific render script, or the main render_8dir
    tile_render_script = os.path.join(SCRIPT_DIR, "blender", "render_tiles.py")
    render_script = tile_render_script if os.path.exists(tile_render_script) else PATHS["render_script"]

    return run_command([
        "blender", "--background", blend_path,
        "--python", render_script,
        "--", "--engine", args.engine or "CYCLES",
        "--tile-only"  # hint for tile renderer to use top-down isometric
    ])


# =============================================================================
# SUB-COMMANDS — UI PIPELINE (new)
# =============================================================================

def cmd_ui_icons(args):
    """Generate status effect icons."""
    log("Generating status effect icons...")
    return run_command(["python3", PATHS["icon_script"]])


def cmd_ui_buttons(args):
    """Generate UI button set for a faction."""
    theme = args.theme or "default"
    log(f"Generating UI buttons for theme: {theme}")
    ui_script = os.path.join(SCRIPT_DIR, "generate_ui_elements.py")
    if not os.path.exists(ui_script):
        log(f"UI element script not found at {ui_script}", "WARN")
        log("Create tools/generate_ui_elements.py for UI button/panel generation")
        return 0
    output_dir = args.output or os.path.join(PATHS["output"], get_latest_version(), "ui")
    return run_command([
        "python3", ui_script, "--theme", theme,
        "--output", output_dir
    ])


# =============================================================================
# SUB-COMMANDS — MATERIALS
# =============================================================================

def cmd_materials_generate(args):
    """Generate PBR textures + rebuild material library."""
    # Step 1: Generate procedural PBR textures
    log("Generating PBR textures...")
    result = run_command(["python3", PATHS["texture_generator"]])
    if result != 0:
        log("PBR texture generation failed", "ERROR")
        return result

    # Step 2: Build material library .blend
    log("Building Blender material library...")
    result = run_command([
        "blender", "--background", "--python", PATHS["material_script"]
    ])
    if result == 0:
        log("Material library built successfully")
    return result


def cmd_materials_list(args):
    """List all available materials."""
    pbr_dir = os.path.join(PATHS["assets"], "pbr_textures")
    if not os.path.exists(pbr_dir):
        log("No PBR textures directory found. Run 'pipeline materials generate' first.", "WARN")
        return 1

    materials = sorted([
        d for d in os.listdir(pbr_dir)
        if os.path.isdir(os.path.join(pbr_dir, d))
    ])
    print(f"\nAvailable materials ({len(materials)}):")
    for m in materials:
        maps = os.listdir(os.path.join(pbr_dir, m))
        print(f"  {m}: {len(maps)} maps ({', '.join(maps)})")
    return 0


# =============================================================================
# SUB-COMMANDS — QUALITY
# =============================================================================

def cmd_critic_single(args):
    """Run quality critic on a render directory."""
    if not args.dir:
        log("No directory specified. Use --dir <path>", "ERROR")
        return 1
    return run_command(["python3", PATHS["critic_script"], args.dir])


def cmd_critic_batch(args):
    """Run critic on all unit render directories."""
    check_dir = args.check_dir or PATHS["units_dir"]
    if not os.path.exists(check_dir):
        log(f"Check directory not found: {check_dir}", "ERROR")
        return 1

    raw_dirs = []
    for root, dirs, files in os.walk(check_dir):
        if "raw" in dirs:
            raw_dirs.append(os.path.join(root, "raw"))

    if not raw_dirs:
        log(f"No render/raw directories found under {check_dir}", "WARN")
        return 0

    log(f"Running critic on {len(raw_dirs)} render directories...")
    results = []
    for raw_dir in sorted(raw_dirs):
        unit = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(raw_dir))))
        # Better: walk up the path to find the unit name
        parts = raw_dir.split(os.sep)
        try:
            unit_idx = parts.index("units") + 1
            unit = parts[unit_idx] if unit_idx < len(parts) else "unknown"
        except ValueError:
            unit = "unknown"

        log(f"  Checking {unit}...")
        result = run_command(
            ["python3", PATHS["critic_script"], raw_dir],
            check=False
        )
        results.append((unit, result))

    passed = sum(1 for _, r in results if r == 0)
    failed = sum(1 for _, r in results if r != 0)
    log(f"Critic batch: {passed} passed, {failed} failed")

    for unit, result in results:
        status = "PASS" if result == 0 else "FAIL"
        print(f"  {status}: {unit}")

    return 0 if failed == 0 else 1


# =============================================================================
# SUB-COMMANDS — PACK & SYNC
# =============================================================================

def cmd_pack(args):
    """Run the batch packer for all units."""
    log("Running batch packer...")
    # The batch_pipeline.py script now respects the VERSION env var
    env = os.environ.copy()
    env["PIPELINE_VERSION"] = args.version or get_latest_version()
    return run_command(["python3", PATHS["batch_script"]], check=False)


def cmd_sync(args):
    """Sync atlases to the IoA game repo."""
    target = args.target
    if not target:
        log("No target directory. Use --target <path>", "ERROR")
        return 1

    version = args.version or get_latest_version()
    src_dir = versioned_output_dir(version)

    if not os.path.exists(src_dir):
        log(f"Version directory not found: {src_dir}", "ERROR")
        return 1

    os.makedirs(target, exist_ok=True)

    # Copy atlas files
    import shutil
    count = 0
    for ext in (".png", ".json"):
        for f in Path(src_dir).glob(f"*{ext}"):
            shutil.copy2(str(f), os.path.join(target, f.name))
            count += 1

    log(f"Synced {count} files from {src_dir} to {target}")
    return 0


# =============================================================================
# SUB-COMMANDS — RELEASE (timestamped snapshot)
# =============================================================================

def cmd_release(args):
    """Create a timestamped release snapshot with MANIFEST.md."""
    import shutil
    from datetime import datetime

    version = args.version or get_latest_version()
    src_dir = versioned_output_dir(version)

    if not os.path.exists(src_dir):
        log(f"Version directory not found: {src_dir}", "ERROR")
        return 1

    # Gather atlas files
    atlas_extensions = (".png", ".json")
    atlas_files = [f for f in Path(src_dir).iterdir()
                   if f.suffix in atlas_extensions and f.is_file()]

    if not atlas_files:
        log(f"No atlas files found in {src_dir}. Run `pipeline pack` first.", "ERROR")
        return 1

    # Build release directory name
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    release_dirname = f"{version}-{timestamp}"
    releases_root = os.path.join(PATHS["output"], "releases")
    release_dir = os.path.join(releases_root, release_dirname)
    os.makedirs(release_dir, exist_ok=True)

    # Copy all atlas files
    count = 0
    for f in atlas_files:
        shutil.copy2(str(f), os.path.join(release_dir, f.name))
        count += 1

    # Generate MANIFEST.md
    manifest_lines = [
        f"# Release: {release_dirname}",
        "",
        f"**Pipeline Version**: {version}",
        f"**Created**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Source**: {src_dir}",
        f"**Assets**: {count} files ({len(atlas_files)} atlas packages)",
        "",
        "## Contents",
        "",
    ]

    # Group files by unit name
    unit_files = {}
    for f in atlas_files:
        # Parse unit name from filename: "<unit>_atlas[_(lod\d+)]?.ext"
        name = f.stem
        # Strip _atlas, _atlas_lod1, _atlas_lod2
        unit_key = name.replace("_atlas_lod1", "").replace("_atlas_lod2", "").replace("_atlas", "")
        if unit_key not in unit_files:
            unit_files[unit_key] = []
        unit_files[unit_key].append(f.name)

    for unit in sorted(unit_files.keys()):
        files = unit_files[unit]
        # Determine LOD levels present
        has_lod = any("lod1" in f or "lod2" in f for f in files)
        lod_info = " (LOD0" + (", LOD1, LOD2" if any("lod1" in f for f in files) else "")
        lod_info += ")" if has_lod else ""
        manifest_lines.append(f"- **{unit}**{lod_info}: {len(files)} files")

    manifest_lines.extend([
        "",
        "## Usage",
        "",
        "These atlases are ready for import into the IoA game engine.",
        "See the README for atlas format documentation.",
        "",
    ])

    manifest_path = os.path.join(release_dir, "MANIFEST.md")
    with open(manifest_path, "w") as f:
        f.write("\n".join(manifest_lines))

    log(f"Wrote manifest: {manifest_path}")

    # Create/update latest symlink
    latest_link = os.path.join(releases_root, "latest")
    # Remove old symlink if it exists
    if os.path.islink(latest_link) or os.path.exists(latest_link):
        os.remove(latest_link)
    os.symlink(release_dirname, latest_link)

    log(f"Created release: {release_dir}")
    log(f"  {count} atlas files copied")
    log(f"  Latest symlink: {latest_link} -> {release_dirname}")
    return 0


# =============================================================================
# SUB-COMMANDS — PREVIEW (interactive 3D model inspection)
# =============================================================================

PREVIEW_SCRIPT = os.path.join(SCRIPT_DIR, "blender", "preview_model.py")


def cmd_preview(args):
    """Open Blender with a unit's model for interactive 3D inspection."""
    units_dir = PATHS["units_dir"]
    unit_dir = Path(units_dir) / args.unit

    if not unit_dir.exists():
        log(f"Unit directory not found: {unit_dir}", "ERROR")
        log(f"Available units: {', '.join(sorted(os.listdir(units_dir)))}", "INFO")
        return 1

    # Find .blend files — prefer model/ subdir and v2 blends
    model_blends = list((unit_dir / "model").rglob("*.blend")) if (unit_dir / "model").exists() else []
    if not model_blends:
        # Look for any .blend in unit directory
        unit_blends = list(unit_dir.rglob("*.blend"))
        if not unit_blends:
            log(f"No .blend file found in {unit_dir}", "ERROR")
            return 1
        blend_files = unit_blends
    else:
        blend_files = model_blends

    # Prefer v2 blends if multiple exist
    v2_blends = [f for f in blend_files if "v2" in f.name.lower()]
    blend_path = str((v2_blends or blend_files)[0])

    if not os.path.exists(blend_path):
        log(f"Blend file not found: {blend_path}", "ERROR")
        return 1

    log(f"Opening Blender with: {blend_path}")
    log("Controls: Middle-mouse orbit | Scroll zoom | Shift+MMB pan")

    # Build shading arg for the preview script
    shading_arg = f"--shading={args.shading}"

    # Launch Blender with UI (not --background)
    cmd = [
        "blender", blend_path, "--python", PREVIEW_SCRIPT, "--",
        args.unit, shading_arg
    ]
    return run_command(cmd)


# =============================================================================
# SUB-COMMANDS — GALLERY (web-based sprite browser)
# =============================================================================

UNIFIED_SERVER_SCRIPT = os.path.join(SCRIPT_DIR, "server.py")
GALLERY_SCRIPT = os.path.join(SCRIPT_DIR, "gallery_server.py")
DASHBOARD_SCRIPT = os.path.join(SCRIPT_DIR, "queue_dashboard.py")


def cmd_gallery(args):
    """Launch the web-based sprite atlas gallery (standalone)."""
    cmd = [sys.executable, GALLERY_SCRIPT,
           "--port", str(args.port),
           "--host", args.host]
    if args.no_browser:
        cmd.append("--no-browser")
    log(f"Starting gallery on http://{args.host}:{args.port}")
    return run_command(cmd)


def cmd_queue(args):
    """Route queue commands to the render_queue module."""
    if not os.path.exists(QUEUE_SCRIPT):
        log(f"Queue module not found: {QUEUE_SCRIPT}", "ERROR")
        return 1

    # Build subcommand args
    cmd_args = [sys.executable, "-m", "tools.render_queue", args.action]

    if args.action == "add":
        cmd_args.extend(["--unit", args.unit])
        if args.config:
            cmd_args.extend(["--config", args.config])
        if args.body_type:
            cmd_args.extend(["--body-type", args.body_type])
        if args.priority:
            cmd_args.extend(["--priority", str(args.priority)])
        if args.force:
            cmd_args.append("--force")

    elif args.action == "list":
        if args.status:
            cmd_args.extend(["--status", args.status])
        if args.verbose:
            cmd_args.append("--verbose")

    elif args.action == "remove":
        cmd_args.extend(["--id", str(args.id)])
        if args.force:
            cmd_args.append("--force")

    elif args.action == "clear":
        if args.all:
            cmd_args.append("--all")
        if args.status:
            cmd_args.extend(["--status"] + args.status)

    elif args.action in ("status",):
        pass  # No extra args needed

    elif args.action in ("run",):
        if args.engine:
            cmd_args.extend(["--engine", args.engine])
        if args.fast:
            cmd_args.append("--fast")

    log(f"Queue command: {args.action}")
    return run_command(cmd_args, check=False)


def cmd_dashboard(args):
    """Launch the unified web dashboard (gallery + render queue)."""
    if not os.path.exists(UNIFIED_SERVER_SCRIPT):
        log(f"Unified server not found: {UNIFIED_SERVER_SCRIPT}", "ERROR")
        return 1
    cmd = [sys.executable, UNIFIED_SERVER_SCRIPT,
           "--port", str(args.port),
           "--host", args.host]
    if args.no_browser:
        cmd.append("--no-browser")
    log(f"Starting unified dashboard on http://{args.host}:{args.port}")
    return run_command(cmd)


# =============================================================================
# SUB-COMMANDS — INFO & DOCTOR
# =============================================================================

def cmd_info(args):
    """Display pipeline configuration and status."""
    version = get_latest_version()
    print(f"\n=== IoA Asset Pipeline ===")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Current version: {version}")
    print(f"Output directory: {versioned_output_dir(version)}")
    print(f"Palette: {PATHS['palette']}")
    print(f"Materials library: {PATHS['materials_blend']}")
    print(f"  Exists: {os.path.exists(PATHS['materials_blend'])}")
    print(f"Configs: {PATHS['configs']}")
    print(f"  Iron Directorate: {len(list(Path(PATHS['configs'], 'iron_directorate').glob('*.json')))} configs")
    print(f"  Cinderborn: {len(list(Path(PATHS['configs'], 'cinderborn').glob('*.json')))} configs")

    # Count units with renders
    units_dir = PATHS["units_dir"]
    if os.path.exists(units_dir):
        render_dirs = list(Path(units_dir).rglob("render/raw"))
        print(f"Rendered units: {len(render_dirs)}")
    return 0


def cmd_doctor(args):
    """Check tool dependencies."""
    errors = []
    warnings = []

    # Check Blender
    try:
        result = subprocess.run(
            ["blender", "--version"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            print(f"  ✓ Blender: {version_line}")
        else:
            errors.append("Blender not found or not working")
    except FileNotFoundError:
        errors.append("Blender not found in PATH")

    # Check Python
    try:
        result = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True, text=True, check=False
        )
        print(f"  ✓ Python: {result.stdout.strip()}")
    except Exception:
        errors.append("Python not found")

    # Check Pillow
    try:
        from PIL import Image
        print(f"  ✓ Pillow: {Image.__version__}")
    except ImportError:
        errors.append("Pillow not installed (pip install Pillow)")

    # Check numpy
    try:
        import numpy
        print(f"  ✓ numpy: {numpy.__version__}")
    except ImportError:
        warnings.append("numpy not installed (needed for PBR texture generation)")

    # Check paths
    for name, path in [
        ("Palette file", PATHS["palette"]),
        ("Materials library", PATHS["materials_blend"]),
        ("Material script", PATHS["material_script"]),
        ("Texture generator", PATHS["texture_generator"]),
        ("Unit generator", PATHS["unit_generator"]),
        ("Render script", PATHS["render_script"]),
        ("Packer script", PATHS["packer_script"]),
        ("Critic script", PATHS["critic_script"]),
        ("Batch script", PATHS["batch_script"]),
    ]:
        if os.path.exists(path):
            print(f"  ✓ {name}: {os.path.relpath(path, PROJECT_ROOT)}")
        else:
            errors.append(f"{name} not found: {path}")

    print()
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")
    if not errors and not warnings:
        print("All checks passed ✓")
    return len(errors)


# =============================================================================
# CLI DEFINITION
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="IoA Asset Pipeline — unified entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full character pipeline
  pipeline_cli.py character full --config configs/iron_directorate/line_infantry.json

  # Batch all Iron Directorate units
  pipeline_cli.py character batch --config-dir configs/iron_directorate/

  # Materials rebuild
  pipeline_cli.py materials generate

  # Quality check all units
  pipeline_cli.py critic batch

  # Check tool dependencies
  pipeline_cli.py doctor
        """
    )
    parser.add_argument("--version", "-V", action="store_true", help="Show version")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # --- character ---
    char_parser = subparsers.add_parser("character", help="Character unit pipeline")
    char_sub = char_parser.add_subparsers(dest="subcommand", help="Character action")

    char_gen = char_sub.add_parser("generate", help="Generate .blend from JSON config")
    char_gen.add_argument("--config", "-c", required=True, help="Path to JSON config")

    char_ren = char_sub.add_parser("render", help="Render 8 directions × 5 animations")
    char_ren.add_argument("--unit", "-u", required=True, help="Unit name")
    char_ren.add_argument("--engine", "-e", default="CYCLES", choices=["CYCLES", "BLENDER_EEVEE"])
    char_ren.add_argument("--fast", action="store_true", help="Fast mode (16 samples)")
    char_ren.add_argument("--samples", type=int, default=None, help="Cycles render samples")
    char_ren.add_argument("--no-depth", action="store_true")
    char_ren.add_argument("--no-normal", action="store_true")

    char_full = char_sub.add_parser("full", help="Full pipeline: generate → render → pack")
    char_full.add_argument("--config", "-c", required=True, help="Path to JSON config")
    char_full.add_argument("--engine", "-e", default="CYCLES")
    char_full.add_argument("--no-depth", action="store_true")
    char_full.add_argument("--no-normal", action="store_true")

    char_batch = char_sub.add_parser("batch", help="Process all configs in a directory")
    char_batch.add_argument("--config-dir", "-d", required=True, help="Directory of JSON configs")
    char_batch.add_argument("--engine", "-e", default="CYCLES")
    char_batch.add_argument("--no-depth", action="store_true")
    char_batch.add_argument("--no-normal", action="store_true")

    # --- tile ---
    tile_parser = subparsers.add_parser("tile", help="Tile/terrain pipeline (new)")
    tile_sub = tile_parser.add_subparsers(dest="subcommand", help="Tile action")
    tile_gen = tile_sub.add_parser("generate", help="Generate tile set")
    tile_gen.add_argument("--tile-set", "-t", default="urban_concrete")
    tile_gen.add_argument("--output-dir", "-o")
    tile_ren = tile_sub.add_parser("render", help="Render tile set")
    tile_ren.add_argument("--tile-set", "-t", default="urban_concrete")
    tile_ren.add_argument("--engine", "-e", default="CYCLES")

    # --- ui ---
    ui_parser = subparsers.add_parser("ui", help="UI asset generation (new)")
    ui_sub = ui_parser.add_subparsers(dest="subcommand", help="UI action")
    ui_sub.add_parser("icons", help="Generate status effect icons")
    ui_btn = ui_sub.add_parser("buttons", help="Generate UI button set")
    ui_btn.add_argument("--theme", "-t", default="default", help="Faction theme")
    ui_btn.add_argument("--output", "-o", default=None, help="Output directory (default: output/<version>/ui/<theme>)")

    # --- materials ---
    mat_parser = subparsers.add_parser("materials", help="PBR material management")
    mat_sub = mat_parser.add_subparsers(dest="subcommand", help="Material action")
    mat_sub.add_parser("generate", help="Generate PBR textures + rebuild material library")
    mat_sub.add_parser("list", help="List available materials")

    # --- critic ---
    crit_parser = subparsers.add_parser("critic", help="Quality analysis")
    crit_sub = crit_parser.add_subparsers(dest="subcommand", help="Critic action")
    c1 = crit_sub.add_parser("single", help="Run critic on a render directory")
    c1.add_argument("--dir", "-d", required=True, help="Render/raw directory")
    c2 = crit_sub.add_parser("batch", help="Run critic on all units")
    c2.add_argument("--check-dir", help="Override units directory")

    # --- pack ---
    pack_parser = subparsers.add_parser("pack", help="Pack processed frames into atlases")
    pack_parser.add_argument("--unit", "-u", required=True, help="Unit name")
    pack_parser.add_argument("--version", default=CURRENT_VERSION, help="Output version tag")

    # --- sync ---
    sync_parser = subparsers.add_parser("sync", help="Sync atlases to IoA repo")
    sync_parser.add_argument("--target", "-t", required=True, help="IoA atlases directory")
    sync_parser.add_argument("--version", default=CURRENT_VERSION, help="Version to sync")

    # --- release ---
    release_parser = subparsers.add_parser(
        "release",
        help="Create a timestamped release snapshot with MANIFEST.md"
    )
    release_parser.add_argument(
        "--version", default=CURRENT_VERSION,
        help="Pipeline version to release (default: current)"
    )

    # --- preview ---
    preview_parser = subparsers.add_parser(
        "preview",
        help="Open Blender with a unit's 3D model for interactive inspection"
    )
    preview_parser.add_argument("--unit", "-u", required=True, help="Unit name")
    preview_parser.add_argument(
        "--shading", default="material", choices=["solid", "material", "rendered"],
        help="Viewport shading mode (default: material)"
    )

    # --- dashboard (unified) ---
    dash_parser = subparsers.add_parser(
        "dashboard",
        help="Launch unified web dashboard (gallery + render queue)"
    )
    dash_parser.add_argument("--port", "-p", type=int, default=8080, help="Port (default: 8080)")
    dash_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    dash_parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    # --- gallery (standalone, for compatibility) ---
    gallery_parser = subparsers.add_parser(
        "gallery",
        help="Launch web-based sprite atlas gallery browser"
    )
    gallery_parser.add_argument("--port", "-p", type=int, default=8082, help="Port (default: 8082)")
    gallery_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    gallery_parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    # --- queue ---
    queue_parser = subparsers.add_parser("queue", help="Render queue management")
    queue_sub = queue_parser.add_subparsers(dest="action", help="Queue action")

    q_add = queue_sub.add_parser("add", help="Add a unit to the render queue")
    q_add.add_argument("--unit", "-u", required=True, help="Unit name")
    q_add.add_argument("--config", "-c", default=None, help="Path to JSON config")
    q_add.add_argument("--body-type", "-t", default="humanoid", help="Body type")
    q_add.add_argument("--priority", "-p", type=int, default=0, help="Priority (higher = sooner)")
    q_add.add_argument("--force", action="store_true", help="Queue even if already queued")

    q_list = queue_sub.add_parser("list", help="List queued jobs")
    q_list.add_argument("--status", "-s", default=None, help="Filter by status")
    q_list.add_argument("--verbose", "-v", action="store_true", help="Detailed output")

    q_remove = queue_sub.add_parser("remove", help="Remove a job from the queue")
    q_remove.add_argument("--id", "-i", type=int, required=True, help="Job ID")
    q_remove.add_argument("--force", action="store_true")

    q_clear = queue_sub.add_parser("clear", help="Clear completed/failed jobs")
    q_clear.add_argument("--status", nargs="+", default=["done", "failed"])
    q_clear.add_argument("--all", action="store_true")

    queue_sub.add_parser("status", help="Show queue status")

    q_run = queue_sub.add_parser("run", help="Process all queued renders")
    q_run.add_argument("--engine", "-e", default="CYCLES")
    q_run.add_argument("--fast", action="store_true", help="Fast mode (16 samples)")

    queue_sub.add_parser("pause", help="Pause after current job finishes")
    queue_sub.add_parser("resume", help="Resume paused queue processing")
    queue_sub.add_parser("clean", help="Reset stale running jobs + detect already-rendered")

    # --- info / doctor ---
    subparsers.add_parser("info", help="Show pipeline configuration")
    subparsers.add_parser("doctor", help="Check tool dependencies")

    return parser


# =============================================================================
# MAIN DISPATCH
# =============================================================================

COMMANDS = {
    ("character", "generate"): cmd_character_generate,
    ("character", "render"): cmd_character_render,
    ("character", "full"): cmd_character_full,
    ("character", "batch"): cmd_character_batch,
    ("tile", "generate"): cmd_tile_generate,
    ("tile", "render"): cmd_tile_render,
    ("ui", "icons"): cmd_ui_icons,
    ("ui", "buttons"): cmd_ui_buttons,
    ("materials", "generate"): cmd_materials_generate,
    ("materials", "list"): cmd_materials_list,
    ("critic", "single"): cmd_critic_single,
    ("critic", "batch"): cmd_critic_batch,
    ("pack",): cmd_pack,
    ("sync",): cmd_sync,
    ("release",): cmd_release,
    ("preview",): cmd_preview,
    ("gallery",): cmd_gallery,
    ("queue",): cmd_queue,
    ("dashboard",): cmd_dashboard,
    ("info",): cmd_info,
    ("doctor",): cmd_doctor,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Only intercept --version flag (bool), not subcommand --version (string)
    if args.version is True:
        print(f"IoA Asset Pipeline {CURRENT_VERSION}")
        return 0

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch
    if args.command == "character":
        if not args.subcommand:
            parser.parse_args(["character", "--help"])
            return 1
        handler = COMMANDS.get(("character", args.subcommand))
    elif args.command == "tile":
        if not args.subcommand:
            parser.parse_args(["tile", "--help"])
            return 1
        handler = COMMANDS.get(("tile", args.subcommand))
    elif args.command == "ui":
        if not args.subcommand:
            parser.parse_args(["ui", "--help"])
            return 1
        handler = COMMANDS.get(("ui", args.subcommand))
    elif args.command == "materials":
        if not args.subcommand:
            parser.parse_args(["materials", "--help"])
            return 1
        handler = COMMANDS.get(("materials", args.subcommand))
    elif args.command == "critic":
        if not args.subcommand:
            parser.parse_args(["critic", "--help"])
            return 1
        handler = COMMANDS.get(("critic", args.subcommand))
    elif args.command == "queue":
        handler = COMMANDS.get(("queue",))
    elif args.command == "dashboard":
        handler = COMMANDS.get(("dashboard",))
    else:
        handler = COMMANDS.get((args.command,))

    if not handler:
        log(f"Unknown command: {args.command} {getattr(args, 'subcommand', '')}", "ERROR")
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
