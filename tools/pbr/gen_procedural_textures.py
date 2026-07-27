#!/usr/bin/env python3
"""
gen_procedural_textures.py — Generate PBR texture maps procedurally.

Creates normal maps, roughness maps, and metalness maps from scratch using
numpy/Pillow. No external downloads. Fully deterministic. Palette-matched.

Outputs to assets/pbr_textures/<material_name>/:
  - albedo.png     (base color, tinted to grimdark palette)
  - normal.png     (tangent-space normal map)
  - roughness.png  (grayscale roughness variation)
  - metallic.png   (grayscale metalness mask)
  - height.png     (grayscale height/displacement map)

All maps are 512x512, tileable, CC0 (self-generated).
"""

import os
import sys
import numpy as np
from PIL import Image

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "pbr_textures")
OUTPUT_DIR = os.path.abspath(OUTPUT_DIR)

TEX_SIZE = 512


# =============================================================================
# NOISE GENERATORS
# =============================================================================

def value_noise_2d(width, height, scale=32, seed=0):
    """Generate smooth value noise. Tileable if width/height are multiples of scale."""
    rng = np.random.RandomState(seed)
    # Random values at grid points
    gx = width // scale + 1
    gy = height // scale + 1
    grid = rng.rand(gx, gy).astype(np.float32)

    # Bilinear interpolation to full size
    xs = np.linspace(0, gx - 1, width, endpoint=False, dtype=np.float32)
    ys = np.linspace(0, gy - 1, height, endpoint=False, dtype=np.float32)
    xi = xs.astype(int)
    yi = ys.astype(int)
    xf = xs - xi
    yf = ys - yi

    # Smoothstep for nicer interpolation
    xf = xf * xf * (3 - 2 * xf)
    yf = yf * yf * (3 - 2 * yf)

    # Tileable: wrap indices
    xi_wrap = xi % gx
    yi_wrap = yi % gy
    xi1_wrap = (xi + 1) % gx
    yi1_wrap = (yi + 1) % gy

    # Broadcast for 2D interpolation
    XI = xi_wrap[:, None]
    XI1 = xi1_wrap[:, None]
    YI = yi_wrap[None, :]
    YI1 = yi1_wrap[None, :]

    top = grid[XI, YI] * (1 - xf[:, None]) + grid[XI1, YI] * xf[:, None]
    bot = grid[XI, YI1] * (1 - xf[:, None]) + grid[XI1, YI1] * xf[:, None]
    result = top * (1 - yf[None, :]) + bot * yf[None, :]
    return result


def fractal_noise(width, height, octaves=5, base_scale=64, seed=0):
    """Fractal (fBm) value noise — sum of octaves for natural detail."""
    result = np.zeros((width, height), dtype=np.float32)
    amplitude = 1.0
    total_amp = 0.0
    for octave in range(octaves):
        scale = max(2, base_scale // (2 ** octave))
        result += amplitude * value_noise_2d(width, height, scale=scale, seed=seed + octave * 17)
        total_amp += amplitude
        amplitude *= 0.5
    result /= total_amp
    return result


def worley_noise(width, height, num_points=20, seed=0):
    """Worley (cellular) noise — distance to nearest random point. Good for rivets/pitting."""
    rng = np.random.RandomState(seed)
    px = rng.rand(num_points) * width
    py = rng.rand(num_points) * height

    xs = np.arange(width, dtype=np.float32)[:, None]
    ys = np.arange(height, dtype=np.float32)[None, :]

    # Compute distance to each point, take minimum
    min_dist = np.full((width, height), 1e9, dtype=np.float32)
    for i in range(num_points):
        dx = xs - px[i]
        dy = ys - py[i]
        # Tileable wrapping
        dx = np.minimum(dx, width - dx)
        dy = np.minimum(dy, height - dy)
        dist = np.sqrt(dx * dx + dy * dy)
        min_dist = np.minimum(min_dist, dist)

    # Normalize to 0-1
    max_d = min_dist.max()
    if max_d > 0:
        min_dist /= max_d
    return min_dist


# =============================================================================
# NORMAL MAP FROM HEIGHT
# =============================================================================

def height_to_normal(height_map, strength=2.0):
    """Convert a grayscale height map to a tangent-space normal map."""
    h = height_map.astype(np.float32)
    # Sobel-like gradient
    grad_x = np.zeros_like(h)
    grad_y = np.zeros_like(h)

    grad_x[1:-1, :] = (h[2:, :] - h[:-2, :]) / 2.0
    grad_y[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / 2.0

    # Edges
    grad_x[0, :] = h[1, :] - h[0, :]
    grad_x[-1, :] = h[-1, :] - h[-2, :]
    grad_y[:, 0] = h[:, 1] - h[:, 0]
    grad_y[:, -1] = h[:, -1] - h[:, -2]

    # Tangent-space normal
    nx = -grad_x * strength
    ny = -grad_y * strength
    nz = np.ones_like(h)

    # Normalize
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx = nx / length
    ny = ny / length
    nz = nz / length

    # Encode to 0-255 RGB
    r = ((nx + 1) * 0.5 * 255).clip(0, 255).astype(np.uint8)
    g = ((ny + 1) * 0.5 * 255).clip(0, 255).astype(np.uint8)
    b = ((nz + 1) * 0.5 * 255).clip(0, 255).astype(np.uint8)

    return np.stack([r, g, b], axis=-1)


# =============================================================================
# MATERIAL DEFINITIONS
# =============================================================================

def save_maps(name, albedo_rgb, normal_rgb, roughness_gray, metallic_gray, height_gray):
    """Save all PBR maps for a material."""
    out_dir = os.path.join(OUTPUT_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    Image.fromarray(albedo_rgb, "RGB").save(os.path.join(out_dir, "albedo.png"))
    Image.fromarray(normal_rgb, "RGB").save(os.path.join(out_dir, "normal.png"))
    Image.fromarray(roughness_gray.astype(np.uint8), "L").save(os.path.join(out_dir, "roughness.png"))
    Image.fromarray(metallic_gray.astype(np.uint8), "L").save(os.path.join(out_dir, "metallic.png"))
    Image.fromarray((height_gray * 255).clip(0, 255).astype(np.uint8), "L").save(os.path.join(out_dir, "height.png"))
    print(f"  Generated: {name}/ (albedo, normal, roughness, metallic, height)")


def gen_grimdark_metal(seed=42):
    """Weathered gunmetal — uniform dark steel with fine micro-detail and thin rust streaks.

    DoW1 base surface texture: a near-uniform faction-colour base with FINE micro-detail
    (fine pitting, thin scratches, subtle rust staining). NO large high-contrast blobs —
    those read as camouflage at sprite scale. Large features (panel lines, rivets, aquila)
    come from the per-unit painted diffuse, not this tiled surface texture.
    """
    w = h = TEX_SIZE

    # Base: uniform dark gunmetal with subtle fine variation (amplitude kept small so it
    # reads as a solid colour, not camo).
    base_noise = fractal_noise(w, h, octaves=4, base_scale=64, seed=seed)
    base_val = 38 + base_noise * 10  # 38-48 — tight range, uniform steel
    r = base_val * 1.00
    g = base_val * 0.99
    b = base_val * 1.02  # faint cool tint

    # Fine pitting (subtle, low amplitude) — surface micro-detail, not visible blobs
    pit_noise = worley_noise(w, h, num_points=40, seed=seed + 3)
    pit = (1 - pit_noise) * 6  # ±6 variation only
    r = (r - pit * 0.9).clip(0, 255)
    g = (g - pit * 0.9).clip(0, 255)
    b = (b - pit * 1.0).clip(0, 255)

    # Thin rust STREAKS (low coverage, thin) — not large blobs. Reads as weathering, not camo.
    streak_noise = fractal_noise(w, h, octaves=3, base_scale=32, seed=seed + 1)
    streak_mask = (streak_noise > 0.82).astype(np.float32)  # <18% coverage, thin
    streak_r = streak_mask * 96
    streak_g = streak_mask * 66
    streak_b = streak_mask * 48
    r = (r * (1 - streak_mask) + streak_r).clip(0, 255)
    g = (g * (1 - streak_mask) + streak_g).clip(0, 255)
    b = (b * (1 - streak_mask) + streak_b).clip(0, 255)

    # Fine scratches (broad low-contrast lines that survive downscale)
    scratch_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed + 2)
    scratches = (scratch_noise > 0.78).astype(np.float32) * 12
    r = (r + scratches).clip(0, 255)
    g = (g + scratches).clip(0, 255)
    b = (b + scratches * 0.95).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height map: fine pitting + scratches
    height = (1 - pit_noise) * 0.25 + scratches * 0.1 + streak_mask * 0.15
    height = height / max(height.max(), 0.01)

    # Normal from height
    normal = height_to_normal(height, strength=3.0)

    # Roughness: base semi-rough, rust streaks rougher, scratches smoother
    roughness = 0.45 + base_noise * 0.15 + streak_mask * 0.3 - scratches * 0.15
    roughness = (roughness * 255).clip(0, 255)

    # Metallic: mostly metal (high), rust streaks less metallic
    metallic = (1.0 - streak_mask * 0.5) * 255

    save_maps("grimdark_metal", albedo, normal, roughness, metallic, height)


def gen_grimdark_leather(seed=100):
    """Worn leather — uniform brown with fine grain and thin creases.

    DoW1 base surface: near-uniform leather colour with fine grain micro-detail and thin
    crease lines. NO large mud/blob variation (reads as camo at sprite scale).
    """
    w = h = TEX_SIZE

    # Base: uniform leather (90, 74, 60) with subtle fine variation
    base_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed)
    r = 90 + base_noise * 8
    g = 74 + base_noise * 7
    b = 60 + base_noise * 6

    # Fine grain (subtle)
    grain = fractal_noise(w, h, octaves=3, base_scale=48, seed=seed + 2)
    r = (r + grain * 6 - 3).clip(0, 255)
    g = (g + grain * 5 - 2).clip(0, 255)
    b = (b + grain * 4 - 2).clip(0, 255)

    # Thin crease lines (low coverage) — reads as leather creases, not mud blobs
    crease_noise = fractal_noise(w, h, octaves=2, base_scale=96, seed=seed + 1)
    creases = (crease_noise < 0.22).astype(np.float32) * 18
    r = (r - creases).clip(0, 255)
    g = (g - creases * 0.85).clip(0, 255)
    b = (b - creases * 0.7).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: fine grain + thin crease depressions
    height = grain * 0.25 + (1 - crease_noise) * 0.3
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=2.0)

    # Roughness: leather is fairly rough, creases are rougher
    roughness = 0.65 + grain * 0.12 + (1 - crease_noise) * 0.08
    roughness = (roughness * 255).clip(0, 255)

    # Non-metallic
    metallic = np.zeros((w, h), dtype=np.uint8)

    save_maps("grimdark_leather", albedo, normal, roughness, metallic, height)


def gen_grimdark_fabric(seed=200):
    """Military under-armour fabric — dark, desaturated, subtle weave.

    DoW1 base surface: a near-uniform DARK under-armour colour with a subtle weave,
    not a bright green checkered plaid (which reads as camo at sprite scale). Faction
    colour is applied via the per-unit team-colour mask, not this base texture.
    """
    w = h = TEX_SIZE

    # Base: dark desaturated under-armour (48, 54, 46) — dark, not bright green
    base_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed)
    r = 48 + base_noise * 8
    g = 54 + base_noise * 9
    b = 46 + base_noise * 7

    # Subtle weave (low amplitude — reads as fabric texture, not a plaid grid)
    weave_x = np.sin(np.arange(w)[:, None] * np.pi / 12) * 0.5 + 0.5
    weave_y = np.sin(np.arange(h)[None, :] * np.pi / 12) * 0.5 + 0.5
    weave = (weave_x * weave_y) * 5  # ±5 only — very subtle
    r = (r + weave - 2).clip(0, 255)
    g = (g + weave - 2).clip(0, 255)
    b = (b + weave - 2).clip(0, 255)

    # Subtle folds (low amplitude)
    fold_noise = fractal_noise(w, h, octaves=2, base_scale=128, seed=seed + 1)
    r = (r + fold_noise * 6 - 3).clip(0, 255)
    g = (g + fold_noise * 7 - 3).clip(0, 255)
    b = (b + fold_noise * 6 - 3).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: subtle weave + folds
    height = weave * 0.1 + fold_noise * 0.2
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=1.5)

    # Roughness: fabric is rough
    roughness = 0.75 + base_noise * 0.12
    roughness = (roughness * 255).clip(0, 255)

    metallic = np.zeros((w, h), dtype=np.uint8)

    save_maps("grimdark_fabric", albedo, normal, roughness, metallic, height)


def gen_imperial_gold(seed=300):
    """Imperial gold — warm metallic, tarnish spots, engraved detail."""
    w = h = TEX_SIZE

    # Base: imperial gold (212, 160, 36)
    base_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed)
    r = 200 + base_noise * 40
    g = 150 + base_noise * 30
    b = 30 + base_noise * 20

    # Tarnish spots
    tarnish_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed + 1)
    tarnish = (tarnish_noise > 0.7).astype(np.float32)
    r = (r * (1 - tarnish * 0.4) + tarnish * 80).clip(0, 255)
    g = (g * (1 - tarnish * 0.4) + tarnish * 70).clip(0, 255)
    b = (b * (1 - tarnish * 0.4) + tarnish * 40).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: broad engraving + tarnish pits (low-freq for downscale survival)
    detail_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed + 2)
    height = detail_noise * 0.4 + tarnish * 0.2
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=2.0)

    # Roughness: gold is smooth, tarnish is rough
    roughness = 0.25 + base_noise * 0.1 + tarnish * 0.4
    roughness = (roughness * 255).clip(0, 255)

    # Metallic
    metallic = np.full((w, h), 255, dtype=np.uint8)

    save_maps("imperial_gold", albedo, normal, roughness, metallic, height)


def gen_chaos_rust(seed=400):
    """Chaos-corroded metal — heavy rust, pitting, warp damage."""
    w = h = TEX_SIZE

    # Base: dark rust (92, 64, 52) rust_dark
    base_noise = fractal_noise(w, h, octaves=4, base_scale=48, seed=seed)
    r = 92 + base_noise * 60
    g = 64 + base_noise * 40
    b = 52 + base_noise * 30

    # Heavy pitting
    pit_noise = worley_noise(w, h, num_points=25, seed=seed + 1)
    pit_dark = (1 - pit_noise) * 40
    r = (r - pit_dark).clip(0, 255)
    g = (g - pit_dark * 0.8).clip(0, 255)
    b = (b - pit_dark * 0.6).clip(0, 255)

    # Blood/warp stains
    stain_noise = fractal_noise(w, h, octaves=3, base_scale=96, seed=seed + 2)
    stains = (stain_noise > 0.6).astype(np.float32)
    r = (r + stains * 47).clip(0, 255)  # blood red tint
    g = (g - stains * 10).clip(0, 255)
    b = (b - stains * 10).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: heavy pitting
    height = (1 - pit_noise) * 0.5 + stain_noise * 0.2
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=4.0)

    # Roughness: very rough
    roughness = 0.7 + base_noise * 0.2 + stains * 0.1
    roughness = (roughness * 255).clip(0, 255)

    # Partially metallic (rust reduces metalness)
    metallic = (0.3 + (1 - stains) * 0.4) * 255

    save_maps("chaos_rust", albedo, normal, roughness, metallic, height)


def gen_bio_flesh(seed=500):
    """Parasitic Bloom — green/flesh organic material with vein networks."""
    w = h = TEX_SIZE

    # Base: sickly flesh-green (78, 100, 60)
    base_noise = fractal_noise(w, h, octaves=3, base_scale=48, seed=seed)
    r = 78 + base_noise * 30
    g = 100 + base_noise * 35
    b = 60 + base_noise * 20

    # Vein network (dark green/purple lines)
    vein_noise = fractal_noise(w, h, octaves=4, base_scale=32, seed=seed + 1)
    veins = (vein_noise > 0.75).astype(np.float32)
    r = (r - veins * 30).clip(0, 255)
    g = (g - veins * 10).clip(0, 255)
    b = (b - veins * 10).clip(0, 255)

    # Spore/mucus spots (brighter green)
    spore_noise = worley_noise(w, h, num_points=15, seed=seed + 2)
    spores = (spore_noise > 0.85).astype(np.float32)
    r = (r + spores * 30).clip(0, 255)
    g = (g + spores * 50).clip(0, 255)
    b = (b + spores * 20).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: organic bumps and vein ridges
    height = base_noise * 0.3 + veins * 0.5 + (1 - spore_noise) * 0.2
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=3.0)

    # Roughness: organic, slightly wet
    roughness = 0.5 + base_noise * 0.2 - spores * 0.3
    roughness = (roughness * 255).clip(0, 255)

    # Non-metallic
    metallic = np.zeros((w, h), dtype=np.uint8)

    save_maps("bio_flesh", albedo, normal, roughness, metallic, height)


def gen_chrome_white(seed=600):
    """Harmonic Collective — white/chrome, clean, precise, minimal wear."""
    w = h = TEX_SIZE

    # Base: bright white-chrome (200, 200, 200)
    base_noise = fractal_noise(w, h, octaves=2, base_scale=128, seed=seed)
    r = 200 + base_noise * 30
    g = 200 + base_noise * 28
    b = 200 + base_noise * 25

    # Panel lines (sharp, geometric divisions)
    panel_noise = fractal_noise(w, h, octaves=2, base_scale=64, seed=seed + 1)
    panel_lines = (panel_noise < 0.2).astype(np.float32)
    r = (r - panel_lines * 40).clip(0, 255)
    g = (g - panel_lines * 40).clip(0, 255)
    b = (b - panel_lines * 40).clip(0, 255)

    # Minimal surface scratches
    scratch_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed + 2)
    scratches = (scratch_noise > 0.75).astype(np.float32) * 0.2
    r = (r + scratches * 20).clip(0, 255)
    g = (g + scratches * 20).clip(0, 255)
    b = (b + scratches * 20).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: shallow panel lines
    height = panel_lines * 0.3 + scratches * 0.1
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=1.5)

    # Roughness: very smooth (chrome)
    roughness = 0.15 + base_noise * 0.1 + panel_lines * 0.2
    roughness = (roughness * 255).clip(0, 255)

    # Highly metallic
    metallic = np.full((w, h), 230, dtype=np.uint8)

    save_maps("chrome_white", albedo, normal, roughness, metallic, height)


def gen_cyan_bone(seed=700):
    """Chrono Revenants — cyan-tinted bone, aged, temporal decay."""
    w = h = TEX_SIZE

    # Base: pale cyan bone (180, 200, 210)
    base_noise = fractal_noise(w, h, octaves=3, base_scale=48, seed=seed)
    r = 180 + base_noise * 20
    g = 200 + base_noise * 20
    b = 210 + base_noise * 20

    # Porous bone texture
    pore_noise = worley_noise(w, h, num_points=30, seed=seed + 1)
    pores = (1 - pore_noise) * 30
    r = (r - pores * 0.5).clip(0, 255)
    g = (g - pores * 0.5).clip(0, 255)
    b = (b - pores).clip(0, 255)

    # Temporal cracks (bright cyan glow lines)
    crack_noise = fractal_noise(w, h, octaves=3, base_scale=48, seed=seed + 2)
    cracks = (crack_noise > 0.7).astype(np.float32)
    r = (r - cracks * 20).clip(0, 255)
    g = (g + cracks * 30).clip(0, 255)  # cyan glow
    b = (b + cracks * 40).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: porous surface with crack depressions
    height = (1 - pore_noise) * 0.3 + cracks * 0.4
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=2.0)

    # Roughness: bone is somewhat rough
    roughness = 0.6 + base_noise * 0.2 - cracks * 0.3
    roughness = (roughness * 255).clip(0, 255)

    # Non-metallic
    metallic = np.zeros((w, h), dtype=np.uint8)

    save_maps("cyan_bone", albedo, normal, roughness, metallic, height)


def gen_red_rust(seed=800):
    """Wreckstorm Clans — aggressive red/rust, battle-worn, hot metal."""
    w = h = TEX_SIZE

    # Base: hot red-orange rust (160, 50, 30)
    base_noise = fractal_noise(w, h, octaves=3, base_scale=48, seed=seed)
    r = 160 + base_noise * 40
    g = 50 + base_noise * 30
    b = 30 + base_noise * 15

    # Heat scoring (dark burn marks)
    burn_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed + 1)
    burns = (burn_noise > 0.65).astype(np.float32)
    r = (r - burns * 40).clip(0, 255)
    g = (g - burns * 20).clip(0, 255)
    b = (b - burns * 10).clip(0, 255)

    # Fresh scratches (bright metal exposed)
    scratch_noise = fractal_noise(w, h, octaves=3, base_scale=48, seed=seed + 2)
    scratches = (scratch_noise > 0.7).astype(np.float32)
    r = (r + scratches * 40).clip(0, 255)
    g = (g + scratches * 40).clip(0, 255)
    b = (b + scratches * 40).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: heavy pitting + burn depressions
    pit_noise = worley_noise(w, h, num_points=20, seed=seed + 3)
    height = (1 - pit_noise) * 0.4 + burns * 0.3 + scratches * 0.1
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=3.5)

    # Roughness: rough with smooth scratch marks
    roughness = 0.65 + base_noise * 0.2 - scratches * 0.3
    roughness = (roughness * 255).clip(0, 255)

    # Partially metallic
    metallic = (0.5 + scratches * 0.5) * 255

    save_maps("red_rust", albedo, normal, roughness, metallic, height)


def gen_black_silver(seed=900):
    """Void Corsairs — black/silver tactical, worn but functional."""
    w = h = TEX_SIZE

    # Base: dark grey-black (30, 30, 35)
    base_noise = fractal_noise(w, h, octaves=3, base_scale=64, seed=seed)
    r = 30 + base_noise * 20
    g = 30 + base_noise * 20
    b = 35 + base_noise * 20

    # Silver edge wear (exposed bright metal along edges)
    edge_noise = fractal_noise(w, h, octaves=2, base_scale=96, seed=seed + 1)
    edges = (edge_noise > 0.6).astype(np.float32)
    r = (r + edges * 100).clip(0, 255)
    g = (g + edges * 100).clip(0, 255)
    b = (b + edges * 100).clip(0, 255)

    # Tactical markings (faint grey bands)
    marking_noise = fractal_noise(w, h, octaves=2, base_scale=32, seed=seed + 2)
    markings = (marking_noise > 0.7).astype(np.float32) * 0.3
    r = (r + markings * 30).clip(0, 255)
    g = (g + markings * 30).clip(0, 255)
    b = (b + markings * 30).clip(0, 255)

    albedo = np.stack([r, g, b], axis=-1).astype(np.uint8)

    # Height: shallow wear patterns
    height = edges * 0.2 + marking_noise * 0.15
    height = height / max(height.max(), 0.01)

    normal = height_to_normal(height, strength=2.0)

    # Roughness: mostly matte with shiny worn edges
    roughness = 0.5 + base_noise * 0.2 - edges * 0.3
    roughness = (roughness * 255).clip(0, 255)

    # Metallic on worn edges
    metallic = (0.3 + edges * 0.7) * 255

    save_maps("black_silver", albedo, normal, roughness, metallic, height)


# =============================================================================
# MAIN
# =============================================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Generating PBR textures in: {OUTPUT_DIR}")
    print()

    gen_grimdark_metal(seed=42)
    gen_grimdark_leather(seed=100)
    gen_grimdark_fabric(seed=200)
    gen_imperial_gold(seed=300)
    gen_chaos_rust(seed=400)
    gen_bio_flesh(seed=500)
    gen_chrome_white(seed=600)
    gen_cyan_bone(seed=700)
    gen_red_rust(seed=800)
    gen_black_silver(seed=900)

    print()
    print("All PBR textures generated. 10 materials x 5 maps = 50 files.")
    print("Materials: grimdark_metal, grimdark_leather, grimdark_fabric, imperial_gold, chaos_rust,")
    print("           bio_flesh, chrome_white, cyan_bone, red_rust, black_silver")


if __name__ == "__main__":
    main()