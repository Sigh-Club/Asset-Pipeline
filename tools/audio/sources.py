"""Audio source registry — licensed, bulk-downloadable sound libraries.

Every source here was verified on 2026-11-10 against its own licence page.  The
registry is deliberately small: only sources that (a) allow commercial use in a
game/website, (b) can be fetched without a per-sound API token or browser
session, and (c) state their terms in writing.

Licence summary (see docs/AUDIO_PIPELINE.md for the quotes and URLs):

  sonniss  Sonniss #GameAudioGDC bundles, 2015-2026.  Royalty-free, worldwide,
           commercial, no attribution, unlimited projects.  NOT licensed for
           AI/ML training, and not resellable as sound effects.
  kenney   Kenney.nl audio packs.  CC0 1.0 (public domain).

Sources evaluated and rejected (recorded so nobody re-tests them):
  freepd.com       — closed permanently in 2025.
  BBC Sound Effects — RemArc licence: personal/education only, no commercial.
  ZapSplat         — free tier is MP3-only and requires attribution.
  Freesound        — per-sound licences (CC0/CC-BY/CC-BY-NC), API token needed,
                     and original-file download is OAuth2-only; kept as a
                     targeted supplement, not a bulk base.
"""

from __future__ import annotations

import urllib.parse

SONNISS_BASE = "https://downloads.sonniss.com/"

# year -> (filename template, part count).  Templates use {i}.
# 2015 is the unlabelled original bundle; 2023 covers the 2021-2023 period
# (there was no 2021, 2022 or 2025 bundle).
SONNISS_YEARS: dict[str, tuple[str, int]] = {
    "2015": ("Sonniss.com - GDC - Game Audio Bundle {i}of5.zip", 5),
    "2016": ("Sonniss.com - GDC 2016- Game Audio Bundle Part {i}of6.zip", 6),
    "2017": ("Sonniss.com - GDC 2017 - Game Audio Bundle Part {i}of9.zip", 9),
    "2018": ("Sonniss.com - GDC 2018 - Game Audio Bundle Part {i}of8.zip", 8),
    "2019": ("Sonniss.com - GDC 2019 - Game Audio Bundle Part {i}of8.zip", 8),
    "2020": ("Sonniss.com - GDC 2020 - Game Audio Bundle Part {i}of14.zip", 14),
    "2023": ("Sonniss.com-GDC2023-GameAudioBundle{i}of14.zip", 14),
    "2024": ("Sonniss.com-GDC2024-GameAudioBundle{i}of9.zip", 9),
    "2026": ("Sonniss.com-GDC2026-GameAudioBundle{i}of5.zip", 5),
}

SONNISS_LICENCE = "Sonniss #GameAudioGDC EULA v2.0 (27 Aug 2026): royalty-free, commercial, no attribution; no AI training; no resale as SFX"
SONNISS_LICENCE_URL = "https://sonniss.com/gdc-bundle-license/"
SONNISS_INDEX_URL = "https://sonniss.com/gameaudiogdc/"


def sonniss_parts(year: str) -> list[str]:
    """Return the ordered download URLs for one Sonniss year."""
    template, count = SONNISS_YEARS[year]
    return [
        SONNISS_BASE + urllib.parse.quote(template.format(i=i))
        for i in range(1, count + 1)
    ]


# Kenney audio packs.  slug -> title.  Downloads are CC0; the signed-link API is
# documented in docs/AUDIO_PIPELINE.md (kenney.nl/download-link/<hex>).
KENNEY_PACKS: dict[str, str] = {
    "casino-audio": "Casino Audio",
    "digital-audio": "Digital Audio",
    "impact-sounds": "Impact Sounds",
    "interface-sounds": "Interface Sounds",
    "music-jingles": "Music Jingles",
    "rpg-audio": "RPG Audio",
    "sci-fi-sounds": "Sci-Fi Sounds",
    "ui-audio": "UI Audio",
    "voiceover-pack": "Voiceover Pack",
}

KENNEY_LICENCE = "CC0 1.0 Universal (public domain dedication)"
KENNEY_LICENCE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
KENNEY_INDEX_URL = "https://kenney.nl/assets"


def kenney_slug_id(slug: str) -> str:
    """Kenney's signed-link API keys downloads on hex('assets/<slug>')."""
    return ("assets/" + slug).encode().hex()


def source_notes() -> dict[str, dict[str, str]]:
    """Machine-readable provenance block written into every manifest."""
    return {
        "sonniss": {
            "index": SONNISS_INDEX_URL,
            "licence": SONNISS_LICENCE,
            "licence_url": SONNISS_LICENCE_URL,
            "commercial": "yes",
            "attribution": "none required",
            "ai_training": "prohibited",
            "resale_raw": "prohibited",
        },
        "kenney": {
            "index": KENNEY_INDEX_URL,
            "licence": KENNEY_LICENCE,
            "licence_url": KENNEY_LICENCE_URL,
            "commercial": "yes",
            "attribution": "none required (credit appreciated)",
            "ai_training": "permitted",
            "resale_raw": "permitted",
        },
    }
