import os
import unittest

import _pathfix  # noqa: F401
from lib import domain_profiler, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(fixture_name):
    return snapshot_adapter.load_snapshot(os.path.join(FIXTURES, fixture_name, "snapshot.json"))


class DomainProfilerTest(unittest.TestCase):
    def test_shopping_site_classified_as_shopping(self):
        snap, digest = _load("shopping-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertEqual(profile["domain_type"], "shopping")

    def test_shopping_site_discovers_laptop_entity(self):
        snap, digest = _load("shopping-site")
        profile = domain_profiler.build_profile(snap, digest)
        entity_texts = [e["text"] for e in profile["entities"]]
        self.assertIn("laptop", entity_texts)

    def test_shopping_site_discovers_ram_attribute(self):
        snap, digest = _load("shopping-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertIn("ram", profile["attributes"])

    def test_shopping_site_discovers_students_audience(self):
        snap, digest = _load("shopping-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertIn("students", profile["audiences"])

    def test_shopping_site_price_signals(self):
        snap, digest = _load("shopping-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertIsNotNone(profile["price_signals"])
        self.assertGreaterEqual(profile["price_signals"]["sample_size"], 3)

    def test_blog_site_classified_as_content(self):
        snap, digest = _load("blog-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertEqual(profile["domain_type"], "content")

    def test_sparse_site_has_no_price_signals(self):
        snap, digest = _load("sparse-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertIsNone(profile["price_signals"])

    def test_profile_is_deterministic(self):
        snap, digest = _load("shopping-site")
        p1 = domain_profiler.build_profile(snap, digest)
        p2 = domain_profiler.build_profile(snap, digest)
        self.assertEqual(p1, p2)

    def test_university_site_classified_as_education(self):
        snap, digest = _load("university-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertEqual(profile["domain_type"], "education")

    def test_university_site_discovers_tuition_attribute_not_shopping_attributes(self):
        snap, digest = _load("university-site")
        profile = domain_profiler.build_profile(snap, digest)
        cs_schema = profile["entity_schemas"]["computer science"]
        self.assertIn("tuition", cs_schema["attributes"])
        self.assertNotIn("ram", cs_schema["attributes"])  # a shopping concept, not education's

    def test_hospital_site_classified_as_healthcare(self):
        snap, digest = _load("hospital-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertEqual(profile["domain_type"], "healthcare")

    def test_hospital_site_discovers_insurance_attribute(self):
        snap, digest = _load("hospital-site")
        profile = domain_profiler.build_profile(snap, digest)
        cardiology_schema = profile["entity_schemas"]["cardiology"]
        self.assertIn("insurance_accepted", cardiology_schema["attributes"])

    def test_unclassifiable_site_falls_back_honestly(self):
        # Not shopping, not education, not healthcare -- must never be
        # misclassified into one of the three just because SOME vocabulary
        # coincidentally matches; it should land in a residual bucket
        # (corporate/generic) and its entities get NO fabricated attributes.
        snap, digest = _load("unknown-domain-site")
        profile = domain_profiler.build_profile(snap, digest)
        self.assertIn(profile["domain_type"], ("generic", "corporate", "content"))
        for schema in profile["entity_schemas"].values():
            self.assertEqual(schema["attributes"], [])

    def test_structured_data_type_outranks_generic_page_type_heuristic(self):
        # A course/clinic page the collector's own (education/healthcare-
        # unaware) classifier happened to label "product" must not cause a
        # shopping misclassification when a specific schema.org type says
        # otherwise -- see classify_domain_type's docstring.
        schema_counts = {"Course": 2}
        page_type_counts = {"product": 2, "homepage": 1}
        self.assertEqual(
            domain_profiler.classify_domain_type(schema_counts, page_type_counts), "education")


if __name__ == "__main__":
    unittest.main()
