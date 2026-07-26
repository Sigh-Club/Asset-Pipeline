#!/usr/bin/env python3
"""
grimdark_palette.py — EXACT palette hex values for emission materials.
All values derived directly from assets/palettes/grimdark_64.gpl.
Import in all Blender scripts for 100% color accuracy.
"""

# 0-1 float values — divide .gpl RGB by 255
PALETTE = {
    # Core neutrals (rows 1-5)
    'void_black':        (0.039, 0.039, 0.039),   # 10, 10, 10
    'soot':              (0.078, 0.078, 0.078),   # 20, 20, 20
    'gunmetal_dark':     (0.118, 0.118, 0.118),   # 30, 30, 30
    'gunmetal_mid':      (0.157, 0.157, 0.157),   # 40, 40, 40
    'battle_grey':       (0.290, 0.290, 0.290),   # 74, 74, 74

    # Browns / leather (rows 6-8)
    'leather_dark':      (0.275, 0.235, 0.196),   # 70, 60, 50
    'leather_mid':       (0.353, 0.290, 0.235),   # 90, 74, 60
    'leather_light':     (0.431, 0.369, 0.298),   # 110, 94, 76

    # Reds / blood (rows 9-11)
    'blood_red':         (0.545, 0.176, 0.176),   # 139, 45, 45
    'blood_mid':         (0.651, 0.227, 0.227),   # 166, 58, 58
    'blood_light':       (0.757, 0.278, 0.278),   # 193, 71, 71

    # Golds (rows 12-17)
    'imperial_gold':     (0.831, 0.627, 0.141),   # 212, 160, 36
    'gold_highlight':    (0.910, 0.784, 0.282),   # 232, 200, 72
    'gold_shine':        (0.941, 0.910, 0.627),   # 240, 232, 160
    'bronze_dark':       (0.549, 0.439, 0.220),   # 140, 112, 56
    'bronze_mid':        (0.659, 0.518, 0.282),   # 168, 132, 72
    'bronze_light':      (0.769, 0.627, 0.345),   # 196, 160, 88

    # Greens (rows 18-20)
    'deep_green':        (0.102, 0.184, 0.102),   # 26, 47, 26
    'fatigue_mid':       (0.306, 0.471, 0.306),   # 78, 120, 78
    'fatigue_light':     (0.376, 0.588, 0.376),   # 96, 150, 96

    # Navy / gunmetal-blue (rows 21-23)
    'navy_dark':         (0.165, 0.165, 0.235),   # 42, 42, 60
    'navy_mid':          (0.235, 0.235, 0.329),   # 60, 60, 84
    'navy_light':        (0.306, 0.306, 0.424),   # 78, 78, 108

    # Rust (rows 24-27)
    'rust_dark':         (0.361, 0.251, 0.204),   # 92, 64, 52
    'rust_mid':          (0.471, 0.329, 0.235),   # 120, 84, 60
    'rust_light':        (0.580, 0.408, 0.282),   # 148, 104, 72
    'rust_highlight':    (0.690, 0.486, 0.329),   # 176, 124, 84

    # Bone (rows 28-30)
    'bone':              (0.910, 0.878, 0.831),   # 232, 224, 212
    'bone_shadow':       (0.784, 0.753, 0.706),   # 200, 192, 180
    'bone_dark':         (0.659, 0.627, 0.580),   # 168, 160, 148

    # Hazard yellow (rows 31-32)
    'hazard_yellow':     (0.910, 0.816, 0.000),   # 232, 208, 0
    'hazard_dark':       (0.722, 0.659, 0.000),   # 184, 168, 0

    # Bruised purple (rows 33-35)
    'bruise_purple':     (0.298, 0.165, 0.361),   # 76, 42, 92
    'purple_mid':        (0.392, 0.227, 0.471),   # 100, 58, 120
    'purple_light':      (0.486, 0.290, 0.580),   # 124, 74, 148

    # Steel blue (rows 36-39)
    'steel_blue_dark':   (0.141, 0.227, 0.298),   # 36, 58, 76
    'steel_blue_mid':    (0.204, 0.353, 0.471),   # 52, 90, 120
    'steel_blue_light':  (0.290, 0.478, 0.612),   # 74, 122, 156
    'steel_blue_highlight': (0.361, 0.549, 0.690), # 92, 140, 176

    # Dirt / earth (rows 40-43)
    'dirt_dark':         (0.290, 0.220, 0.157),   # 74, 56, 40
    'dirt_mid':          (0.392, 0.314, 0.235),   # 100, 80, 60
    'dirt_light':        (0.494, 0.408, 0.314),   # 126, 104, 80
    'dirt_highlight':    (0.596, 0.502, 0.439),   # 152, 128, 112

    # Concrete (rows 44-47)
    'concrete_dark':     (0.424, 0.424, 0.353),   # 108, 108, 90
    'concrete_mid':      (0.541, 0.541, 0.471),   # 138, 138, 120
    'concrete_highlight': (0.659, 0.659, 0.588),  # 168, 168, 150
    'concrete_shine':    (0.776, 0.776, 0.706),   # 198, 198, 180

    # Plasma orange (rows 48-50)
    'plasma_orange':     (0.988, 0.298, 0.016),   # 252, 76, 4
    'plasma_mid':        (1.000, 0.471, 0.000),   # 255, 120, 0
    'plasma_light':      (1.000, 0.643, 0.125),   # 255, 164, 32

    # Toxic green (rows 51-53)
    'toxic_green':       (0.000, 0.722, 0.000),   # 0, 184, 0
    'toxic_mid':         (0.000, 0.878, 0.000),   # 0, 224, 0
    'toxic_light':       (0.251, 1.000, 0.251),   # 64, 255, 64

    # Void blue (rows 54-57)
    'void_blue_dark':    (0.102, 0.102, 0.141),   # 26, 26, 36
    'void_blue_mid':     (0.180, 0.180, 0.243),   # 46, 46, 62
    'void_blue_light':   (0.267, 0.267, 0.353),   # 68, 68, 90
    'void_blue_highlight': (0.361, 0.361, 0.471),  # 92, 92, 120

    # Gore red (rows 58-60)
    'gore_dark':         (0.502, 0.000, 0.000),   # 128, 0, 0
    'gore_mid':          (0.627, 0.000, 0.000),   # 160, 0, 0
    'gore_light':        (0.753, 0.125, 0.125),   # 192, 32, 32

    # Wood (rows 61-63)
    'wood_dark':         (0.235, 0.165, 0.118),   # 60, 42, 30
    'wood_mid':          (0.361, 0.259, 0.188),   # 92, 66, 48
    'wood_light':        (0.486, 0.353, 0.267),   # 124, 90, 68

    # Pure (row 64)
    'pure_red':          (1.000, 0.000, 0.000),   # 255, 0, 0
}

# Alias map for backward compatibility with old script names
ALIASES = {
    'armor_green': 'fatigue_mid',      # was (0.290, 0.404, 0.255)
    'olive_drab':  'fatigue_mid',       # was (0.251, 0.290, 0.212)
    'gunmetal':    'gunmetal_mid',       # was (0.224, 0.224, 0.224)
    'gunmetal_light': 'concrete_mid',   # was (0.373, 0.373, 0.373)
    'bone_white':  'bone',
    'hazard_yellow': 'hazard_yellow',
    'rust':        'rust_mid',
    'bruised_purple': 'bruise_purple',
    'blood_red':   'blood_red',
    'imperial_gold': 'imperial_gold',
    'electric_blue': 'steel_blue_light',
    'deep_purple': 'purple_mid',
    'void_black':  'void_black',
}

def get_color(name):
    """Get exact 0-1 float color tuple by name. Supports aliases."""
    if name in ALIASES:
        name = ALIASES[name]
    return PALETTE.get(name, (0.5, 0.5, 0.5))

if __name__ == '__main__':
    # Verify all colors round-trip correctly
    import os
    gpl_path = os.path.join(os.path.dirname(__file__), 'grimdark_64.gpl')
    errors = []
    with open(gpl_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('GIMP') or line.startswith('Name:') or line.startswith('Columns:'):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                except:
                    continue
                # Check if this exact RGB exists in PALETTE
                found = False
                for name, (pr, pg, pb) in PALETTE.items():
                    if (int(pr*255), int(pg*255), int(pb*255)) == (r, g, b):
                        found = True
                        break
                if not found:
                    errors.append(f'({r},{g},{b}) not in PALETTE')
    if errors:
        print(f'ERRORS: {len(errors)}')
        for e in errors[:10]:
            print(f'  {e}')
    else:
        print('All .gpl colors verified in PALETTE ✓')
