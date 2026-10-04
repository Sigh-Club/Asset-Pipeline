#!/usr/bin/env python3
"""MTC icon forge: parametric zombie-family icons in the mod's 16x16 (x2)
chunky moodlet style, PZ themed.

    icon_forge.py sheet --count 12 --out sheet.png      contact sheet of seeds
    icon_forge.py single --spec spec.json --out x.png   one icon from a spec
    icon_forge.py --emit-js icon_forge_data.js          data for the HTML app

Spec keys: palette, eyes, mouth, hair, hat, torso, occupation, prop, wound,
seed, main, dark. `occupation` resolves hat+torso+colours from the vanilla
profession list unless explicitly overridden. Every blueprint row is built
through _row(), which enforces the 16-column width by construction.
"""

import os
import random

from PIL import Image

O = (26, 32, 26, 255)
E = (18, 20, 18, 255)
W = (222, 226, 210, 255)
R = (156, 34, 34, 255)
S = (52, 58, 66, 255)
T = (38, 42, 50, 255)
B = (96, 66, 40, 255)
P = (210, 202, 178, 255)
K = (188, 196, 200, 255)
N = (44, 60, 96, 255)
Y = (230, 200, 60, 255)
M = (86, 98, 66, 255)
H = (70, 76, 84, 255)

PALETTES = {
    "rot":   ((106, 140, 84), (140, 172, 108), (72, 98, 60)),
    "pale":  ((168, 178, 160), (196, 204, 186), (130, 140, 124)),
    "human": ((214, 170, 140), (232, 192, 164), (178, 134, 108)),
    "ghoul": ((120, 132, 120), (146, 158, 142), (94, 104, 94)),
    "toxic": ((150, 170, 60), (180, 200, 90), (110, 128, 44)),
}
EYES = ("red", "alive", "dead", "hollow")
MOUTHS = ("blood", "flat", "fangs", "grin")
HAIR = ("messy", "bald", "cap", "bandana")
PROPS = ("none", "book", "knife")


BLANK = "." * 16


def _row(left, mid, right):
    """A 16-wide blueprint row: left pad + O + mid + O + right pad."""
    width = 16 - left - 2 - right
    assert width >= 0, "row pattern overflows: %r" % ((left, mid, right),)
    if width == 0:
        assert mid == "", "no room for mid in: %r" % ((left, mid, right),)
        return "." * 16
    return "." * left + "O" + mid.ljust(width, ".")[:width] + "O" + "." * right


def _rows(*specs):
    return [_row(l, m, r) for l, m, r in specs]


HATS = {
    "messy":  None,
    "bald":   None,
    "cap":    _rows((4, "OOOOOOOO", 4), (2, "OSSSSSSSS", 2), (1, "SSSSSSSSSS", 3), (2, "OOOOOOOOOO", 2)),
    "bandana": _rows((4, "OOOOOOOO", 4), (2, "ORRRRRRRR", 2), (1, "RRRRRRRRRR", 3), (1, "OGGGGGGGGGGG", 1)),
    "cop":    _rows((4, "OOOOOOOO", 4), (2, "ONNNNNNNN", 2), (1, "NNNYNNNNNN", 3), (1, "OOOOOOOOOOOO", 2)),
    "fire":   _rows((5, "OYYO", 5), (3, "OYYYYYY", 3), (2, "OYYYYYYYY", 2), (0, "OOOOOOOOOOOOOO", 2)),
    "army":   _rows((4, "OMMMMMO", 4), (2, "OMMMMMMMM", 2), (1, "MMMMMMMMMMMM", 1), (1, "OMMMMMMMMMMO", 1)),
    "swat":   _rows((4, "OOOOOOOO", 4), (2, "OHHHHHHHH", 2), (1, "HHHHHHHHHHHH", 3), (1, "HHHHHHHHHHHH", 3)),
    "paramedic": _rows((4, "OOOOOOOO", 4), (2, "OWWWWWWWW", 2), (1, "WWWWRRWWWW", 3), (1, "WWWWRRWWWW", 3)),
    "toque":  _rows((4, "OOOOOOOO", 4), (3, "WWWWWWW", 4), (2, "WWWWWWWWS", 2), (2, "WWWWWWWWS", 2)),
    "paper":  _rows((4, "OOOOOOOO", 4), (3, "WWWWWWWS", 4), (2, "WWWWWWWWS", 2), (1, "OOOOOOOOOOOOOO", 1)),
    "straw":  _rows((4, "OYYYYYO", 4), (2, "OYYYYYYYY", 2), (1, "OOOOOOOOOOOOOO", 1), (2, "OOOOOOOOOOOO", 2)),
    "ranger": _rows((5, "OOOOOO", 5), (4, "OOOOOOOO", 4), (2, "OOOOOOOOOOOO", 2), (0, "OOOOOOOOOOOOOO", 2)),
    "beanie": _rows((4, "OOOOOOOO", 4), (2, "OTTAATAATTS", 2), (1, "OTAATAATAATS", 3), (1, "OOOOOOOOOOOOOO", 1)),
    "hardhat": _rows((4, "OYYYYYO", 4), (2, "OYYYYYYYY", 2), (1, "OYYYYYYYYYO", 3), (2, "OOOOOOOOOOOO", 2)),
    "cowboy": _rows((5, "OOOOO", 6), (4, "OOOOOOO", 5), (3, "OOOOOOOOO", 4), (0, "OOOOOOOOOOOOOO", 2)),
    "souwest": _rows((5, "OOOOO", 6), (4, "OYYYYYO", 5), (3, "OYYYYYYYO", 4), (1, "OOYYYYYYYYYOO", 2)),
    "headband": [BLANK] * 3 + [_row(2, "ORRRRRRRRRO", 2)],
}

for _name, _rows_in_hat in HATS.items():
    if _rows_in_hat is None:            # hair-driven hats (messy/bald)
        continue
    assert len(_rows_in_hat) == 4, "hat %r must be 4 rows" % _name
    assert all(len(r) == 16 for r in _rows_in_hat), "hat %r has a bad row" % _name

TORSOS = {
    "none":   _rows((3, "CCCCCCC", 4), (2, "CCCFCCCCCC", 2), (2, "CFFFFFFFFC", 2)),
    "cop":    _rows((3, "CCCCCCC", 4), (2, "CCCYCCCCC", 2), (2, "CCCCCFCCC", 2)),
    "fire":   _rows((3, "CCCCCCC", 4), (2, "CKKCKKCKC", 2), (2, "CKKKKKKKK", 2)),
    "army":   _rows((3, "CMCCCMC", 4), (2, "CMCCCMCCM", 2), (2, "CMFMCFMCF", 2)),
    "swat":   _rows((3, "CCCCCCC", 4), (2, "CCFCCFCC", 3), (2, "CCCCCFCC", 2)),
    "paramedic": _rows((3, "CCCRCCC", 4), (2, "CCRRCRCC", 2), (2, "CCCRCCCC", 2)),
    "hi-vis": _rows((3, "CCCCCCC", 4), (2, "CKKCKKCKC", 2), (2, "CKKKKKKKK", 2)),
    "plaid":  _rows((3, "CRCFRCR", 4), (2, "RCRFCRFC", 2), (2, "RFCFRFCF", 2)),
    "apron":  _rows((3, "CCCCCCC", 4), (2, "CPPPPPPPC", 2), (2, "CPPPPPPPC", 2)),
    "coat":   _rows((3, "CWCCCCC", 4), (2, "CWCRCCCC", 2), (2, "CCCCCCCC", 2)),
    "cross":  _rows((3, "CWCCCCC", 4), (2, "CRCRCCCC", 2), (2, "CCCCCCCC", 2)),
    "overalls": _rows((3, "CCCCCCC", 4), (2, "CFCFCFCF", 2), (2, "CFCFCFCF", 2)),
    "tank":   _rows((3, "CCCCCCC", 4), (2, "CWCCWCCC", 2), (2, "CCCCCCCC", 2)),
    "dark":   _rows((3, "CCCCCCC", 4), (2, "CFCCCFCC", 2), (2, "CFCCCFCC", 2)),
    "leather": _rows((3, "BBBBBBB", 4), (2, "CBCBCCBC", 2), (2, "CBBBBBBC", 2)),
    "denim":  _rows((3, "CCCCCCC", 4), (2, "CDCCDCDC", 2), (2, "CDCDCDCD", 2)),
}
TORSO_COLOURS = {
    "none": ((52, 58, 66), (38, 42, 50)),
    "cop": ((44, 60, 96), (34, 46, 74)),
    "fire": ((60, 64, 70), (44, 48, 54)),
    "army": ((96, 108, 72), (66, 76, 50)),
    "swat": ((52, 58, 66), (38, 42, 50)),
    "paramedic": ((206, 206, 212), (170, 170, 178)),
    "hi-vis": ((245, 130, 32), (200, 100, 24)),
    "plaid": ((170, 44, 44), (110, 30, 30)),
    "apron": ((222, 226, 210), (170, 60, 50)),
    "coat": ((226, 226, 226), (180, 180, 186)),
    "cross": ((236, 232, 238), (196, 190, 200)),
    "overalls": ((96, 108, 72), (66, 76, 50)),
    "tank": ((230, 200, 60), (190, 160, 40)),
    "dark": ((60, 64, 70), (44, 48, 54)),
    "leather": ((96, 66, 40), (70, 48, 30)),
    "denim": ((70, 90, 140), (52, 66, 104)),
}

# One style per vanilla profession (UI_prof_* in the game's EN translations).
OCCUPATIONS = {
    "unemployed":         ("none", "none"),
    "fireoff":            ("fire", "fire"),
    "policeoff":          ("cop", "cop"),
    "securityguard":      ("cop", "dark"),
    "burgerflipper":      ("paper", "apron"),
    "chef":               ("toque", "coat"),
    "doctor":             ("none", "coat"),
    "nurse":              ("none", "cross"),
    "veteran":            ("army", "army"),
    "parkranger":         ("ranger", "army"),
    "constructionworker": ("hardhat", "hi-vis"),
    "carpenter":          ("hardhat", "overalls"),
    "burglar":            ("beanie", "dark"),
    "lumberjack":         ("beanie", "plaid"),
    "electrician":        ("hardhat", "dark"),
    "engineer":           ("hardhat", "coat"),
    "mechanic":           ("cap", "overalls"),
    "welder":             ("none", "dark"),
    "blacksmith":         ("bandana", "leather"),
    "farmer":             ("straw", "overalls"),
    "fisherman":          ("souwest", "hi-vis"),
    "rancher":            ("cowboy", "overalls"),
    "repairman":          ("cap", "overalls"),
    "fitnessinstructor":  ("headband", "tank"),
    "tailor":             ("none", "tank"),
}


def _head_rows(pal, eyes, mouth, hair, wound, rng, hat):
    g, l, d = PALETTES[pal]
    rows = [
        "....OOOOOOOO....",
        "..OOGGLLGGGGO...",
        ".OGLLGGGGGGGDO..",
        ".OGGGGGGGGGGDO..",
        "OGGDGGGGGGGDGGO.",
        "OGDGGGGGGGGGDGO.",
    ]
    if hair == "bald":
        rows[1] = rows[1].replace("L", "G")
        rows[2] = rows[2].replace("L", "G")
    elif hair == "cap":
        rows[0] = _row(4, "OSSSSSSS", 4)
        rows[1] = _row(2, "OSSSSSSSSS", 2)
        rows[2] = _row(1, "SSSSSSSSSSS", 2)
    elif hair == "bandana":
        rows[1] = _row(2, "ORRRRRRRR", 2)
        rows[2] = _row(1, "RRRRRRRRRRR", 2)
    elif hair == "messy" and rng.random() < 0.5:
        x = rng.randrange(4, 12)
        rows[0] = rows[0][:x] + "G" + rows[0][x + 1:]
    if hat in HATS and HATS[hat]:
        rows[0:4] = HATS[hat]
    rows += {
        "red":    _rows((0, "GREEGGGGGEEE", 1), (0, "GRWEGGGGEEE", 2)),
        "alive":  _rows((0, "GEEEGGGGGEEE", 1), (0, "GEWEGGGGGEWE", 2)),
        "dead":   _rows((0, "GEEEGGGGGEEE", 1), (0, "GEEEGGGGGEEE", 2)),
        "hollow": _rows((0, "GEEEEGGGEEEEG", 0), (0, "GEEEEGGGEEEEG", 0)),
    }[eyes]
    rows += _rows((0, "GGGGGGGGGGGGG", 1), (1, "GGDGGGGGDGG", 2))
    rows += {
        "blood": _rows((1, "GGRRGRRGRG", 2), (1, "GGGRRRRRG", 3)),
        "flat":  _rows((1, "GGDDDDDDDG", 2), (1, "GGGGGGGGG", 3)),
        "fangs": _rows((1, "GGEEREEREG", 2), (1, "GGGWGGWGG", 3)),
        "grin":  _rows((1, "GGDGGGGGDG", 2), (1, "GGGGRRRGG", 3)),
    }[mouth]
    rows += _rows((2, "OOGGGGGG", 4))
    if wound and rng.random() < 0.8:
        x = rng.randrange(8, 12)
        if rows[1][x] in "GLD":
            rows[1] = rows[1][:x] + "R" + rows[1][x + 1:]
            rows[2] = rows[2][:x] + "R" + rows[2][x + 1:]
    return rows


def _prop_rows(prop):
    if prop == "book":
        return _rows((3, "OBBBBBB", 4), (2, "OSBPPPPPB", 2), (2, "OSBPPPPPP", 2))
    if prop == "knife":
        return _rows((3, "OSSSSSS", 4), (2, "OSSSLLSSS", 2), (2, "OSSSSLLSS", 2))
    return _rows((3, "OSSSSSS", 4), (2, "OSSSSTSSS", 2), (2, "OSTTTTTTT", 2))


def rows_for(spec):
    pal = spec.get("palette", "rot")
    eyes = spec.get("eyes", "red")
    mouth = spec.get("mouth", "blood")
    hair = spec.get("hair", "messy")
    prop = spec.get("prop", "none")
    wound = bool(spec.get("wound", True))
    occupation = spec.get("occupation")
    hat = spec.get("hat")
    torso = spec.get("torso")
    if occupation in OCCUPATIONS:
        hat, torso = OCCUPATIONS[occupation]
    if not torso:
        torso = "none"
    rng = random.Random(spec.get("seed", 1))

    rows = _head_rows(pal, eyes, mouth, hair, wound, rng, hat or "none")
    rows += TORSOS[torso]
    overlay = spec.get("overlay")
    if overlay in OVERLAYS:
        rows = OVERLAYS[overlay](rows)
    return rows


def render(spec):
    rows = rows_for(spec)
    pal = spec.get("palette", "rot")
    g, l, d = PALETTES.get(pal, PALETTES["rot"])
    main = spec.get("main")
    dark = spec.get("dark")
    if not main or not dark:
        occupation = spec.get("occupation")
        if occupation in OCCUPATIONS:
            _, torso = OCCUPATIONS[occupation]
            main, dark = TORSO_COLOURS[torso]
        else:
            torso = spec.get("torso", "none")
            main, dark = TORSO_COLOURS[torso]

    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    px = img.load()
    pmap = {".": (0, 0, 0, 0), "O": O, "E": E, "W": W, "R": R, "S": S, "T": T,
            "B": B, "P": P, "K": K, "N": N, "Y": Y, "M": M, "H": H,
            "G": g + (255,), "L": l + (255,), "D": d + (255,),
            "C": main + (255,), "F": dark + (255,), "A": (170, 60, 60, 255),
            "U": (100, 140, 210, 255)}
    for y, row in enumerate(rows):
        assert len(row) == 16, "row %d is %d wide: %r" % (y, len(row), row)
        for x, ch in enumerate(row):
            for dy in (0, 1):
                for dx in (0, 1):
                    px[x * 2 + dx, y * 2 + dy] = pmap[ch]
    return img


def sheet(specs, path, scale=3):
    from PIL import ImageDraw
    n = len(specs)
    cell = 32 * scale
    img = Image.new("RGBA", (n * (cell + 8) + 8, cell + 26), (30, 30, 30, 255))
    dr = ImageDraw.Draw(img)
    for i, spec in enumerate(specs):
        icon = render(spec).resize((cell, cell), Image.NEAREST)
        img.alpha_composite(icon, (8 + i * (cell + 8), 4))
        dr.text((8 + i * (cell + 8), cell + 8),
                "#%s" % (spec.get("label") or spec.get("occupation")
                         or spec.get("seed", 1)), fill=(200, 200, 200))
    img.save(path)
    print("wrote", os.path.normpath(path), "(%d icons)" % n)


def emit_js(path):
    """Write the blueprint data as JS (icon_forge_data.js) so the HTML forge
    renders from the same source of truth as this engine."""
    import json
    occupations = {}
    for pid, (hat, torso) in OCCUPATIONS.items():
        main, dark = TORSO_COLOURS[torso]
        occupations[pid] = {"hat": HATS[hat] if hat in HATS else None,
                            "torso": TORSOS[torso],
                            "main": list(main), "dark": list(dark)}
    head_base = [
        "....OOOOOOOO....", "..OOGGLLGGGGO...", ".OGLLGGGGGGGDO..",
        ".OGGGGGGGGGGDO..", "OGGDGGGGGGGDGGO.", "OGDGGGGGGGGGDGO.",
    ]
    parts = [
        "// GENERATED by tools/icon_forge.py --emit-js - do not hand-edit.",
        "const OCCUPATIONS = " + json.dumps(occupations, indent=1) + ";",
        "const OCCUPATION_KEYS = Object.keys(OCCUPATIONS);",
        "const PALETTES = " + json.dumps(
            {k: [list(c) for c in v] for k, v in PALETTES.items()}) + ";",
        "const HEAD_BASE = " + json.dumps(head_base) + ";",
        "const HAT_COLOURS = { N: [44,60,96,255], Y: [230,200,60,255], "
        "M: [86,98,66,255], H: [70,76,84,255] };",
    ]
    open(path, "w").write("\n".join(parts) + "\n")
    print("wrote", os.path.normpath(path))





# ------------------------------------------------------------- emoji pack --
# Discord emotes (128x128 = the 32x32 art x4, nearest-neighbour): the zombie
# family acting out chat. Each entry is a spec plus an optional overlay
# painter; overlays only paint over skin/shirt/hair pixels, never the outline.
BLUE = (100, 140, 210, 255)
HEART = (200, 40, 60, 255)


def _overlay_heart(rows):
    import math
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] not in "OE":
            grid[y][x] = ch
    for y in range(9, 16):
        for x in range(2, 14):
            d1 = (x - 5.5) ** 2 + (y - 11.0) ** 2
            d2 = (x - 10.5) ** 2 + (y - 11.0) ** 2
            tri = y >= 11 and abs(x - 8) <= (15.5 - y) * 0.85
            if d1 <= 7.5 or d2 <= 7.5 or tri:
                put(x, y, "R")
    put(4, 10, "W"); put(5, 10, "W")
    return ["".join(r) for r in grid]



MITTEN = [
    ".OOO.",
    "OWWWO",
    "OWWWO",
    ".OOO.",
]


def _stamp(grid, blueprint, x0, y0):
    for dy, row in enumerate(blueprint):
        for dx, ch in enumerate(row):
            x, y = x0 + dx, y0 + dy
            if 0 <= x < 16 and 0 <= y < 16 and ch != ".":
                grid[y][x] = ch

def _overlay_wave(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16:
            grid[y][x] = ch
    _stamp(grid, MITTEN, 11, 0)              # raised glove above the head
    put(13, 4, "W"); put(13, 5, "G")         # arm
    put(9, 1, "W"); put(15, 2, "W")          # motion arcs
    return ["".join(r) for r in grid]


def _overlay_zzz(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] in ".GLD":
            grid[y][x] = ch
    for x, y in ((12, 0), (13, 0), (13, 1), (12, 2), (13, 2)):
        put(x, y, "W")
    return ["".join(r) for r in grid]


def _overlay_drool(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] in "GLDSCF":
            grid[y][x] = ch
    for x, y in ((11, 11), (11, 12), (11, 13), (12, 12), (12, 13), (12, 14)):
        put(x, y, "R")
    return ["".join(r) for r in grid]


def _overlay_brows(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] in "GLD":
            grid[y][x] = ch
    for x in (3, 4, 10, 11):
        put(x, 5, "R")
        put(x, 6, "D")
    return ["".join(r) for r in grid]


def _overlay_shades(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16:
            grid[y][x] = ch
    for x in range(2, 14):
        put(x, 5, "D"); put(x, 6, "D")
    put(4, 6, "W"); put(11, 6, "W")
    return ["".join(r) for r in grid]


def _overlay_tears(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] in "GLDSCF":
            grid[y][x] = ch
    for x, y in ((3, 8), (3, 9), (4, 10), (12, 8), (12, 9), (11, 10)):
        put(x, y, "U")
    return ["".join(r) for r in grid]


def _overlay_salute(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16:
            grid[y][x] = ch
    _stamp(grid, MITTEN, 11, 1)              # gloved hand at the brow
    put(14, 5, "G"); put(14, 6, "G"); put(14, 7, "G")    # arm
    return ["".join(r) for r in grid]


def _overlay_party(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch, force=False):
        if 0 <= x < 16 and 0 <= y < 16 and (force or grid[y][x] in ".GLD"):
            grid[y][x] = ch
    put(7, 0, "R", True); put(8, 0, "Y", True)
    put(6, 1, "Y", True); put(7, 1, "R", True); put(8, 1, "Y", True); put(9, 1, "R", True)
    for x in range(5, 11):
        put(x, 2, "R" if x % 2 else "Y", True)
    for x in range(4, 12):
        put(x, 3, "R", True)                             # brim
    put(2, 2, "Y"); put(13, 2, "W"); put(3, 6, "Y")      # confetti
    return ["".join(r) for r in grid]


def _overlay_bandage(rows):
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] not in "O":
            grid[y][x] = ch
    for x in range(3, 13):
        put(x, 2, "W"); put(x, 3, "W")
    put(7, 3, "R")                                       # the scrape showing through
    return ["".join(r) for r in grid]


# "HI!" speech bubble: 5-row box (cols 7-15) with 3-row pixel letters
# H I ! in dark-on-white, tail pointing at the speaker
_HI_GLYPHS = {
    "H": ["E.E", "E.E", "EEE", "E.E"],
    "I": ["E.", "E.", "E.", "E."],
    "!": ["E.", "E.", ".", "E"],
}


def _overlay_hibubble(rows):
    # banner across the top (rows 0-3): white fill, dark border, "HI!" in
    # 3-tall dark letters - big enough to read at chat size. The zombie
    # peeks out from under it, face fully visible below.
    grid = [list(r) for r in rows]

    def put(x, y, ch):
        if 0 <= x < 16 and 0 <= y < 16:
            grid[y][x] = ch
    for y in range(0, 4):
        for x in range(2, 14):
            put(x, y, "W")
    for x in range(1, 15):
        put(x, 0, "O"); put(x, 3, "O")
    for y in range(0, 4):
        put(1, y, "O"); put(14, y, "O")
    # H (cols 3-5), I (col 7-8), ! (col 10-11), 3 rows starting at row 1... rows 1-3
    Hg = ["E.E", "E.E", "EEE"]
    Ig = ["EE", "E.", "E."]
    Xg = ["E.", "E.", "E."]
    for dy in range(3):
        for dx, g in enumerate(Hg[dy]):
            if g == "E":
                put(3 + dx, 1 + dy, "E")
        for dx, g in enumerate(Ig[dy]):
            if g == "E":
                put(7 + dx, 1 + dy, "E")
        for dx, g in enumerate(Xg[dy]):
            if g == "E":
                put(10 + dx, 1 + dy, "E")
    put(8, 4, "W"); put(7, 5, "W")       # tail toward the speaker
    return ["".join(r) for r in grid]


OVERLAYS = {
    "heart": _overlay_heart, "wave": _overlay_wave, "zzz": _overlay_zzz,
    "drool": _overlay_drool, "brows": _overlay_brows, "shades": _overlay_shades,
    "tears": _overlay_tears, "salute": _overlay_salute, "party": _overlay_party,
    "bandage": _overlay_bandage, "hibubble": _overlay_hibubble,
}

EMOJIS = {
    "zlove":   {"palette": "rot", "eyes": "red", "mouth": "blood", "hair": "messy",
                "wound": False, "overlay": "heart"},
    "zwave":   {"palette": "rot", "eyes": "alive", "mouth": "grin", "hair": "messy",
                "wound": False, "overlay": "wave"},
    "swave":   {"palette": "human", "eyes": "alive", "mouth": "grin", "hair": "messy",
                "wound": False, "overlay": "wave"},
    "zhi":     {"palette": "rot", "eyes": "alive", "mouth": "flat", "hair": "messy",
                "wound": False, "overlay": "hibubble"},
    "sshi":    {"palette": "human", "eyes": "alive", "mouth": "flat", "hair": "messy",
                "wound": False, "overlay": "hibubble"},
    "zdead":   {"palette": "rot", "eyes": "dead", "mouth": "blood", "hair": "messy",
                "wound": True},
    "zbite":   {"palette": "rot", "eyes": "red", "mouth": "fangs", "hair": "messy",
                "wound": True},
    "zdrool":  {"palette": "toxic", "eyes": "hollow", "mouth": "fangs", "hair": "bald",
                "wound": False, "overlay": "drool"},
    "zangry":  {"palette": "rot", "eyes": "red", "mouth": "flat", "hair": "messy",
                "wound": False, "overlay": "brows"},
    "zscared": {"palette": "pale", "eyes": "hollow", "mouth": "blood", "hair": "messy",
                "wound": False},
    "zsleep":  {"palette": "ghoul", "eyes": "dead", "mouth": "flat", "hair": "bald",
                "wound": False, "overlay": "zzz"},
    "zcool":   {"palette": "rot", "eyes": "dead", "mouth": "grin", "hair": "bald",
                "wound": False, "overlay": "shades"},
    "zlol":    {"palette": "human", "eyes": "dead", "mouth": "blood", "hair": "messy",
                "wound": False},
    "zcry":    {"palette": "human", "eyes": "alive", "mouth": "flat", "hair": "messy",
                "wound": False, "overlay": "tears"},
    "zparty":  {"palette": "toxic", "eyes": "alive", "mouth": "grin", "hair": "bald",
                "wound": False, "overlay": "party"},
    "zheal":   {"palette": "human", "eyes": "alive", "mouth": "flat", "hair": "messy",
                "wound": False, "overlay": "bandage"},
    "zcop":    {"palette": "human", "eyes": "alive", "mouth": "flat", "wound": False,
                "occupation": "policeoff"},
    "zfire":   {"palette": "human", "eyes": "red", "mouth": "grin", "wound": True,
                "occupation": "fireoff"},
    "zarmy":   {"palette": "rot", "eyes": "dead", "mouth": "flat", "wound": False,
                "occupation": "veteran"},
    "zswat":   {"palette": "rot", "eyes": "hollow", "mouth": "flat", "wound": False,
                "hat": "swat", "torso": "dark", "main": (52, 58, 66),
                "dark": (38, 42, 50)},
    "zmedic":  {"palette": "human", "eyes": "alive", "mouth": "flat", "wound": False,
                "occupation": "doctor"},
    "zspiffo": {"palette": "human", "eyes": "alive", "mouth": "grin", "wound": False,
                "hat": "paper", "torso": "apron", "main": (222, 226, 210),
                "dark": (170, 60, 50)},
}


def render_emoji(name, size=128):
    """Render one emote at `size` (square)."""
    entry = EMOJIS[name]
    img = render(entry)
    return img.resize((size, size), Image.NEAREST)


def emoji_pack(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name in EMOJIS:
        render_emoji(name).save(os.path.join(out_dir, name + ".png"))
    strip = Image.new("RGBA", (len(EMOJIS) * 138 + 8, 144), (30, 30, 30, 255))
    x = 8
    for name in EMOJIS:
        strip.alpha_composite(render_emoji(name, 128), (x, 8))
        x += 138
    strip.save(os.path.join(out_dir, "_contact_sheet.png"))
    print("wrote %d emojis + contact sheet to %s" % (len(EMOJIS), os.path.normpath(out_dir)))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="MTC icon forge")
    ap.add_argument("mode", nargs="?", choices=["sheet", "single", "occupations", "manifest", "emoji"])
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--palette", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--spec", default=None)
    ap.add_argument("--occupation", default=None,
                    help="sheet of seeds for one occupation")
    ap.add_argument("--emit-js", dest="emit_js", default=None,
                    help="write icon_forge_data.js for the HTML forge")
    ap.add_argument("--check", action="store_true",
                    help="with manifest: verify shipped PNGs match their specs")
    ap.add_argument("--manifest", dest="manifest", default=None,
                    help="icon manifest JSON (name -> spec) to render/verify")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.emit_js:
        emit_js(args.emit_js)
        if not args.mode:
            return
    if not args.out:
        ap.error("--out required")
    if args.mode == "emoji":
        emoji_pack(args.out)
        return
    if args.mode == "manifest":
        import json, sys
        manifest = json.load(open(args.manifest))
        entries = manifest["icons"] if isinstance(manifest, dict) else manifest
        os.makedirs(args.out, exist_ok=True)
        bad = []
        for name, spec in sorted(entries.items()):
            want = render(spec)
            out = os.path.join(args.out, name + ".png")
            if args.check or "--check" in sys.argv:
                if not os.path.exists(out):
                    bad.append(name + " missing")
                    continue
                with Image.open(out) as im:
                    if im.size != (32, 32) or im.tobytes() != want.tobytes():
                        bad.append(name + " differs from spec")
                continue
            want.save(out)
            print("wrote", os.path.normpath(out))
        if bad:
            for b in bad:
                print("FAIL:", b)
            return 1
        print("manifest OK:", len(entries), "icons verified" if (args.check or "--check" in sys.argv)
              else "written to " + os.path.normpath(args.out))
        return
    if args.mode == "occupations":
        specs = []
        for pid, (hat, torso) in sorted(OCCUPATIONS.items()):
            main, dark = TORSO_COLOURS[torso]
            specs.append({"palette": "rot", "eyes": "alive", "mouth": "flat",
                          "prop": "none", "wound": False, "seed": 1,
                          "hat": hat, "torso": torso, "main": main,
                          "dark": dark, "occupation": pid, "label": pid})
        sheet(specs, args.out, scale=4)
        return
    if args.mode == "sheet":
        rng = random.Random(args.seed)
        specs = []
        for i in range(args.count):
            spec = {
                "palette": args.palette or rng.choice(list(PALETTES)),
                "eyes": rng.choice(EYES), "mouth": rng.choice(MOUTHS),
                "hair": rng.choice(HAIR), "hat": rng.choice(list(HATS)),
                "torso": rng.choice(list(TORSOS)), "wound": rng.random() < 0.6,
                "seed": rng.randint(1, 999), "label": str(i + 1),
            }
            if spec["torso"] in TORSO_COLOURS:
                spec["main"], spec["dark"] = TORSO_COLOURS[spec["torso"]]
            specs.append(spec)
        sheet(specs, args.out)
        return
    import json
    spec = json.load(open(args.spec)) if args.spec else {"seed": args.seed or 1}
    render(spec).save(args.out)
    print("wrote", os.path.normpath(args.out))


if __name__ == "__main__":
    main()
