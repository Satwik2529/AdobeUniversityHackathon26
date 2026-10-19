import os
import unittest

import _pathfix  # noqa: F401
from lib import domain_profiler, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _profile(fixture_name):
    snap, digest = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, fixture_name, "snapshot.json"))
    return domain_profiler.build_profile(snap, digest)


class EntitySchemaTest(unittest.TestCase):
    def test_mixed_site_discovers_both_entities(self):
        profile = _profile("mixed-category-site")
        names = {e["text"] for e in profile["entities"]}
        self.assertIn("laptop", names)
        self.assertIn("keyboard", names)

    def test_ram_belongs_to_laptop_schema_not_keyboard(self):
        profile = _profile("mixed-category-site")
        self.assertIn("ram", profile["entity_schemas"]["laptop"]["attributes"])
        self.assertNotIn("ram", profile["entity_schemas"]["keyboard"]["attributes"])

    def test_keyboard_has_its_own_legitimate_attributes(self):
        profile = _profile("mixed-category-site")
        keyboard_attrs = set(profile["entity_schemas"]["keyboard"]["attributes"])
        self.assertTrue({"backlighting", "connectivity", "switch_type"} <= keyboard_attrs)

    def test_students_audience_does_not_leak_from_laptop_to_keyboard(self):
        profile = _profile("mixed-category-site")
        self.assertIn("students", profile["entity_schemas"]["laptop"]["audiences"])
        self.assertNotIn("students", profile["entity_schemas"]["keyboard"]["audiences"])

    def test_price_signals_are_scoped_per_entity_not_site_wide(self):
        profile = _profile("mixed-category-site")
        laptop_price = profile["entity_schemas"]["laptop"]["price_signals"]
        keyboard_price = profile["entity_schemas"]["keyboard"]["price_signals"]
        # Laptops (₹58k-95k) and keyboards (₹3.2k-4.5k) occupy disjoint
        # ranges on this fixture -- scoping proves it, a site-wide range
        # would blend them into one misleading band.
        self.assertGreater(laptop_price["min"], keyboard_price["max"])

    def test_generic_marketing_modifier_is_not_treated_as_an_entity(self):
        # "Pro" appears in both "Pro Laptop X" and "Wireless Keyboard Pro"
        # -- a shared modifier, not a product category.
        profile = _profile("mixed-category-site")
        names = {e["text"] for e in profile["entities"]}
        self.assertNotIn("pro", names)

    def test_no_degenerate_duplicate_word_bigrams(self):
        # Regression for the "laptop laptop" bigram bug: bigrams must only
        # form between words that were truly adjacent in the source text.
        profile = _profile("shopping-site")
        names = {e["text"] for e in profile["entities"]}
        self.assertNotIn("laptop laptop", names)


if __name__ == "__main__":
    unittest.main()
