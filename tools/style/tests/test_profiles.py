#!/usr/bin/env python3
"""Tests for the style profile loader/validator. Stdlib only:

    python3 -m unittest discover -s tools/style/tests -v
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import profiles  # noqa: E402


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = profiles.load_config()

    def test_every_shipped_profile_is_valid(self):
        for pid in self.cfg["profiles"]:
            resolved = profiles.resolve(pid, self.cfg)
            errors = profiles.validate(resolved, self.cfg)
            self.assertEqual(errors, [], f"{pid}: {errors}")

    def test_registry_covers_the_requested_style_range(self):
        ids = set(self.cfg["profiles"])
        for required in ("aaa_3d", "lowpoly_3d", "pixel_3d", "pixel_sprite",
                         "hd_pixel_sprite"):
            self.assertIn(required, ids)

    def test_extends_inherits_and_overrides(self):
        derived = profiles.resolve("hd_pixel_sprite", self.cfg)
        self.assertEqual(derived["render"]["size_px"], [192, 256])
        self.assertEqual(derived["animation"]["fps_authored"], 12)
        self.assertIn("idle", derived["animation"]["clips"])
        self.assertEqual(derived["pixel"]["dither"], "bayer2")
        self.assertNotIn("extends", derived)

    def test_defaults_are_applied(self):
        resolved = profiles.resolve("aaa_3d", self.cfg)
        self.assertFalse(resolved["render"]["aa"])
        self.assertEqual(resolved["animation"]["fps_authored"], 12)

    def test_unknown_profile_raises(self):
        with self.assertRaises(KeyError):
            profiles.resolve("nope", self.cfg)

    def test_cycle_is_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["profiles"]["a"] = {"extends": "b", "representation": "sprite_2d"}
        cfg["profiles"]["b"] = {"extends": "a", "representation": "sprite_2d"}
        with self.assertRaises(ValueError):
            profiles.resolve("a", cfg)

    def test_unknown_key_is_rejected(self):
        bad = profiles.resolve("pixel_sprite", self.cfg)
        bad["geometry"] = {"tris_max": 10, "tris_min": 1, "shading": "flat",
                           "uv": "none", "tris_maX": 99}
        errors = profiles.validate(bad, self.cfg)
        self.assertTrue(any("unknown key 'tris_maX'" in e for e in errors), errors)

    def test_unknown_gate_is_rejected(self):
        bad = profiles.resolve("pixel_sprite", self.cfg)
        bad["gates"] = ["palette_compliance", "vibes"]
        errors = profiles.validate(bad, self.cfg)
        self.assertTrue(any("unknown gate 'vibes'" in e for e in errors), errors)

    def test_texel_grid_requires_world_size(self):
        bad = profiles.resolve("pixel_3d", self.cfg)
        del bad["texture"]["texel_world_m"]
        errors = profiles.validate(bad, self.cfg)
        self.assertTrue(any("texel_world_m" in e for e in errors), errors)

    def test_sprite_profile_requires_canvas_and_palette(self):
        bad = profiles.resolve("pixel_sprite", self.cfg)
        del bad["render"]["size_px"]
        del bad["pixel"]["palette_id"]
        errors = profiles.validate(bad, self.cfg)
        self.assertTrue(any("size_px" in e for e in errors), errors)
        self.assertTrue(any("palette_id" in e for e in errors), errors)

    def test_unknown_palette_is_rejected(self):
        bad = profiles.resolve("pixel_sprite", self.cfg)
        bad["pixel"]["palette_id"] = "not_a_palette"
        errors = profiles.validate(bad, self.cfg)
        self.assertTrue(any("unknown palette_id" in e for e in errors), errors)

    def test_animation_budget_shape_is_enforced(self):
        bad = profiles.resolve("pixel_sprite", self.cfg)
        bad["animation"]["clips"]["walk"] = {"frames": [10, 6]}
        errors = profiles.validate(bad, self.cfg)
        self.assertTrue(any("animation.walk" in e for e in errors), errors)

    def test_comments_are_stripped(self):
        raw = {"//": "note", "a": {"//": "x", "b": 1}}
        self.assertEqual(profiles._strip_comments(raw), {"a": {"b": 1}})


if __name__ == "__main__":
    unittest.main()
