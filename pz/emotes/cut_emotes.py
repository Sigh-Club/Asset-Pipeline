#!/usr/bin/env python3
"""Cut Discord emotes from Gemini sheets using the IoA defringe tool.

Pipeline per sheet:
  1. defringe_rgba on the FULL sheet (bg from corners, flood-fill key,
     binary alpha, silhouette fringe cull),
  2. per grid cell: clear enclosed background pockets (letter counters)
       - badge zone = top 35% of the cell, plus any extra hand-picked points,
       - pocket = connected near-bg component whose pixels are ALL opaque
         (the connected outer bg is already transparent at this point),
  3. tight-crop, resize to 128x128 (Lanczos for HQ art, box for pixel art),
  4. re-run defringe_rgba on the resized emote (re-culls any blended fringe,
     re-binarises alpha), pad to a 128x128 transparent canvas.
"""
import os
import sys
import collections
import numpy as np
from PIL import Image

TOOLS = "/run/media/talzanar/games/Projects/IoA/asset-pipeline/tools"
sys.path.insert(0, TOOLS)
import defringe  # noqa: E402

OUT = "/home/talzanar/Downloads/mtc_emotes"

defringe_tol = 40      # bg key tolerance (sum of channel diffs)
defringe_keep = 100    # fringe-cull threshold (colour distance to bg)


def ring_stats(comp_pix, alpha, rgb, h, w, rad=2):
    """Brightness/saturation stats of the ring of art around a component."""
    comp = set(comp_pix)
    ring = []
    for (y, x) in comp_pix:
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and (ny, nx) not in comp:
                    ring.append((ny, nx))
    ring = list(set(ring))
    mx = rgb[:, :, :3].max(axis=2).astype(int)
    mn = rgb[:, :, :3].min(axis=2).astype(int)
    bright = np.zeros((h, w))
    sat = np.zeros((h, w))
    sat[mx > 0] = (mx[mx > 0] - mn[mx > 0]) / mx[mx > 0]
    bright = (mx + mn) / 2.0
    vals = [(bright[y, x], sat[y, x]) for (y, x) in ring]
    mb = sum(v[0] for v in vals) / len(vals)
    ms = sum(v[1] for v in vals) / len(vals)
    dark_frac = sum(1 for v in vals if v[0] < 80) / len(vals)
    return mb, ms, dark_frac


def enclosed_near_bg_comps(rgb, bg, tol, alpha):
    """Connected near-bg components that are fully opaque = enclosed pockets."""
    h, w = rgb.shape[:2]
    diff = np.abs(rgb.astype(int) - np.array(bg[:3], dtype=int)).sum(axis=2)
    near = diff <= tol
    seen = np.zeros((h, w), bool)
    comps = []
    for yy in range(h):
        for xx in range(w):
            if near[yy, xx] and not seen[yy, xx] and alpha[yy, xx] == 255:
                # BFS this component; track opacity
                pix = []
                dq = collections.deque([(yy, xx)])
                seen[yy, xx] = True
                ok = True
                while dq:
                    y, x = dq.popleft()
                    pix.append((y, x))
                    if alpha[y, x] != 255:
                        ok = False
                    for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                        if 0 <= ny < h and 0 <= nx < w and near[ny, nx] \
                           and not seen[ny, nx]:
                            seen[ny, nx] = True
                            dq.append((ny, nx))
                if ok and len(pix) >= 12:
                    ys = [p[0] for p in pix]
                    xs = [p[1] for p in pix]
                    comps.append({
                        "pix": pix, "area": len(pix),
                        "bbox": (min(xs), min(ys), max(xs), max(ys)),
                        "cx": sum(xs) // len(pix), "cy": sum(ys) // len(pix),
                    })
    return comps


def pocket_should_clear(comp, rgb, alpha, light_bg):
    """Decide per component. A true background pocket is ringed by the dark
    outline art. A dark-bubble's TEXT is ringed by bright white (keep). A
    heart sheen is ringed by saturated colour (keep)."""
    h, w = alpha.shape
    mb, ms, dark_frac = ring_stats(comp["pix"], alpha, rgb, h, w)
    if light_bg:
        return dark_frac >= 0.4
    return not (mb >= 170 and ms <= 0.25)   # dark sheet: keep bubble text only



def edge_polish(img):
    """Recolour low-saturation bright rim pixels (anti-aliased outline/bg
    blend) with the local darkest colour. Only pixels whose 3x3 neighbourhood
    contains a dark outline pixel are touched, so flat grey badge letters
    (RIP) are left alone."""
    a = np.array(img).astype(int)
    rgb, alpha = a[:, :, :3], a[:, :, 3]
    op = alpha == 255
    tr = alpha == 0
    adj = np.zeros(op.shape, bool)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        adj |= np.roll(np.roll(tr, dy, 0), dx, 1)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    bright = (mx + mn) / 2
    dark_nb = np.zeros(op.shape, bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            dark_nb |= np.roll(np.roll(rgb.max(axis=2) < 60, dy, 0), dx, 1)
    cand = op & adj & (sat < 0.3) & (bright > 90) & dark_nb
    # local 3x3 minimum per channel
    loc = rgb.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            loc = np.minimum(loc, np.roll(np.roll(rgb, dy, 0), dx, 1))
    rgb[cand] = loc[cand]
    a[:, :, :3] = rgb
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def cut_sheet(src, names, grid, cell, prefix, resample, zone_pct=35,
              full_cell_names=(), outdir=".", tag=""):
    """grid=(cols,rows), cell=(w,h). Returns list of output paths."""
    cols, rows = grid
    cw, ch = cell
    sheet = Image.open(src).convert("RGBA")
    arr = np.array(sheet)
    bg = defringe.estimate_bg(arr)
    clean = np.array(defringe.defringe_rgba(
        Image.fromarray(arr, "RGBA"), bg, defringe_tol, defringe_keep))
    outs = []
    for i, n in enumerate(names):
        r, c = divmod(i, cols)
        x0, y0 = c * cw, r * ch
        cell_a = clean[y0:y0 + ch, x0:x0 + cw].copy()
        rgb = cell_a[:, :, :3]
        alpha = cell_a[:, :, 3]
        comps = enclosed_near_bg_comps(rgb, bg, defringe_tol, alpha)
        light_bg = bg[:3].mean() > 128
        chosen = []
        for comp in comps:
            in_zone = (100.0 * comp["cy"] / ch) < zone_pct
            if (n in full_cell_names or in_zone) and \
               pocket_should_clear(comp, rgb, alpha, light_bg):
                chosen.append(comp)
        for comp in chosen:
            for (y, x) in comp["pix"]:
                alpha[y, x] = 0
        print("%s%s: pockets cleared: %s" % (
            prefix, n, [(c["cx"], c["cy"], c["area"]) for c in chosen] or "none"))
        cell_a[:, :, 3] = alpha
        img = Image.fromarray(cell_a, "RGBA")
        bbox = img.getbbox()
        img = img.crop(bbox)
        # black-out transparent RGB so downscale blending cannot pull the old
        # white background into the silhouette edge
        a = np.array(img)
        a[a[:, :, 3] == 0, :3] = 0
        img = Image.fromarray(a, "RGBA")
        img = img.resize((128, 128), resample)
        # re-cull blended fringe + re-binarise alpha after downscale
        img = defringe.defringe_rgba(img, bg, defringe_tol, defringe_keep)
        img = edge_polish(img)
        canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        canvas.paste(img, ((128 - img.width) // 2, (128 - img.height) // 2), img)
        path = os.path.join(OUT, outdir, "%s%s.png" % (prefix, n))
        canvas.save(path)
        outs.append(path)
    return outs


def cut_master(src, name, outdir):
    """Single-emote master: full-frame key/pockets/polish, then 128 derivative."""
    sheet = Image.open(src).convert("RGBA")
    arr = np.array(sheet)
    bg = defringe.estimate_bg(arr)
    clean = np.array(defringe.defringe_rgba(
        Image.fromarray(arr, "RGBA"), bg, defringe_tol, defringe_keep))
    rgb, alpha = clean[:, :, :3], clean[:, :, 3]
    comps = enclosed_near_bg_comps(rgb, bg, defringe_tol, alpha)
    light_bg = bg[:3].mean() > 128
    cleared = 0
    for comp in comps:
        if pocket_should_clear(comp, rgb, alpha, light_bg):
            for (y, x) in comp["pix"]:
                alpha[y, x] = 0
            cleared += 1
    clean[:, :, 3] = alpha
    print("%s: pockets cleared: %d" % (name, cleared))
    img = Image.fromarray(clean, "RGBA")
    img = img.crop(img.getbbox())
    os.makedirs(os.path.dirname(os.path.join(OUT, outdir, name)), exist_ok=True)
    img.save(os.path.join(OUT, outdir, "%s.png" % name))
    # black-back transparent RGB, then 128 discord derivative
    a = np.array(img)
    a[a[:, :, 3] == 0, :3] = 0
    small = Image.fromarray(a, "RGBA").resize((128, 128), Image.LANCZOS)
    small = defringe.defringe_rgba(small, bg, defringe_tol, defringe_keep)
    small = edge_polish(small)
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    canvas.paste(small, ((128 - small.width) // 2, (128 - small.height) // 2), small)
    dd = os.path.join(OUT, outdir, "discord")
    os.makedirs(dd, exist_ok=True)
    canvas.save(os.path.join(dd, "%s.png" % name))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "masters":
        raw = "/home/talzanar/Downloads/mtcde_masters/raw"
        out = "../mtcde_masters"
        for f in sorted(os.listdir(raw)):
            if f.endswith(".png"):
                cut_master(os.path.join(raw, f), f[:-4], out)
        print("done")
        return
    # ---- HQ sheet (white bg, smooth cartoon art) ----
    if which in ("all", "hq"):
        hq_names = ["hype", "hi", "gg", "lol", "rip", "love", "rage", "wtf"]
        cut_sheet("/home/talzanar/Downloads/faafc0c2-af86-4efd-ab74-520215a6a9f4.jpeg",
                  hq_names, grid=(4, 2), cell=(256, 286), prefix="mtc_",
                  resample=Image.LANCZOS,
                  full_cell_names=("wtf",),   # arm-gap pockets sit below the badge zone
                  outdir="cells", tag="hq")
    # ---- pixel sheet (dark bg, fake-pixel art) ----
    if which in ("all", "px"):
        px_names = ["hi", "o7", "gg", "wtf", "love", "zzz", "rage", "rip"]
        cut_sheet("/home/talzanar/Downloads/91f47a66-8460-4e1d-b04f-326dd8ca697e.jpeg",
                  px_names, grid=(4, 2), cell=(256, 280), prefix="z_",
                  resample=Image.BOX, tag="px")
    print("done")


if __name__ == "__main__":
    main()
