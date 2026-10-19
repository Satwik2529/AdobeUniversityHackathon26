import os
import unittest

import _pathfix  # noqa: F401
from lib import domain_profiler, evidence_index, evidence_matcher, nlp_engine, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class EvidenceMatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap, cls.digest = snapshot_adapter.load_snapshot(
            os.path.join(FIXTURES, "shopping-site", "snapshot.json"))
        cls.profile = domain_profiler.build_profile(cls.snap, cls.digest)
        cls.index = evidence_index.EvidenceIndex(cls.snap)

    def _evaluate(self, query):
        nlp_result = nlp_engine.analyze_query(query, self.profile)
        return evidence_matcher.evaluate_requirements(
            nlp_result, self.index, self.profile["entity_schemas"], domain_type=self.profile["domain_type"])

    def _status(self, evaluated, category):
        return next(r for r in evaluated if r["category"] == category)["evidence"]["status"]

    def test_price_max_supported_when_a_qualifying_price_exists(self):
        evaluated = self._evaluate("laptop under ₹60,000")
        self.assertEqual(self._status(evaluated, "price_constraint"), "SUPPORTED")

    def test_price_max_contradicted_when_all_prices_exceed_it(self):
        evaluated = self._evaluate("laptop under ₹10,000")
        self.assertEqual(self._status(evaluated, "price_constraint"), "CONTRADICTED")

    def test_price_max_supported_even_when_pricier_products_also_exist(self):
        # A qualifying product (₹45,000) exists even though others on the
        # site cost more -- that range is normal catalog variety, not a
        # contradiction of "there is a laptop under ₹50,000".
        evaluated = self._evaluate("laptop under ₹50,000")
        self.assertEqual(self._status(evaluated, "price_constraint"), "SUPPORTED")

    def test_price_max_partially_supported_when_one_products_own_prices_conflict(self):
        # Genuinely mixed evidence: ONE product's own page cites two prices
        # that disagree about the constraint -- unlike catalog-wide variety,
        # this is ambiguous evidence about a single product.
        requirement = {"id": "R-TEST", "category": "price_constraint", "key": "price_max",
                        "raw": "under ₹50,000", "detail": {"type": "price_max", "value": 50000.0}}
        entity_pages = [{
            "url": "https://example-shop.test/products/confusing-listing",
            "offers": [],
            "blob": "this laptop is priced at rs. 45000 but the older listing still shows rs. 65000",
        }]
        evidence = evidence_matcher.match_price_constraint(requirement, entity_pages)
        self.assertEqual(evidence["status"], "PARTIALLY_SUPPORTED")

    def test_attribute_supported_with_matching_value(self):
        evaluated = self._evaluate("laptop with 16gb ram")
        self.assertEqual(self._status(evaluated, "attribute"), "SUPPORTED")

    def test_attribute_contradicted_with_different_value(self):
        evaluated = self._evaluate("laptop with 4gb ram")
        self.assertEqual(self._status(evaluated, "attribute"), "CONTRADICTED")

    def test_attribute_not_found_when_never_mentioned(self):
        evaluated = self._evaluate("laptop with fingerprint sensor")
        # No unit/attribute pattern in this phrase at all, so no attribute
        # requirement is even extracted -- confirms no fabricated claim.
        categories = [r["category"] for r in evaluated]
        self.assertNotIn("attribute", categories)

    def test_entity_not_found_for_a_product_never_mentioned(self):
        evaluated = self._evaluate("best desktop tower")
        # "desktop" isn't a discovered entity, so no entity requirement is
        # extracted at all -- nothing to falsely claim NOT_FOUND against.
        categories = [r["category"] for r in evaluated]
        self.assertNotIn("entity", categories)

    def test_no_entity_makes_everything_else_not_assessable(self):
        evaluated = self._evaluate("things under ₹5,000 for enthusiasts")
        for req in evaluated:
            if req["category"] != "entity":
                self.assertEqual(req["evidence"]["status"], "NOT_ASSESSABLE")


if __name__ == "__main__":
    unittest.main()
