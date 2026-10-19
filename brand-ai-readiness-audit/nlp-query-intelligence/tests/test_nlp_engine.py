import unittest

import _pathfix  # noqa: F401
from lib import nlp_engine

PROFILE = {
    "domain_type": "shopping",
    "entities": [{"text": "laptop", "page_count": 4, "confidence": "high"}],
    "attributes": ["ram", "storage"],
    "audiences": ["students"],
    "use_cases": ["programming"],
}


class NlpEngineTest(unittest.TestCase):
    def test_full_query_extraction(self):
        result = nlp_engine.analyze_query(
            "Best laptop for CSE students under ₹60,000 with 16GB RAM", PROFILE)
        self.assertEqual(result["intent"], "recommendation")
        self.assertEqual(result["entity"]["text"], "laptop")
        self.assertEqual(result["audience"][0]["key"], "students")
        categories = {r["category"] for r in result["requirements"]}
        self.assertEqual(
            categories,
            {"entity", "audience", "price_constraint", "attribute", "quality_qualifier"},
        )

    def test_price_max_cue(self):
        result = nlp_engine.analyze_query("laptop under ₹60,000", PROFILE)
        constraint = result["constraints"][0]
        self.assertEqual(constraint["type"], "price_max")
        self.assertEqual(constraint["value"], 60000.0)

    def test_price_min_cue(self):
        result = nlp_engine.analyze_query("laptop over $1000", PROFILE)
        self.assertEqual(result["constraints"][0]["type"], "price_min")

    def test_cheap_does_not_invent_a_price_constraint(self):
        result = nlp_engine.analyze_query("cheap laptop", PROFILE)
        self.assertEqual(result["constraints"], [])
        qualifier_keys = [q["key"] for q in result["qualifiers"]]
        self.assertIn("budget", qualifier_keys)

    def test_best_is_flagged_unverifiable(self):
        result = nlp_engine.analyze_query("best laptop", PROFILE)
        best = next(q for q in result["qualifiers"] if q["key"] == "best")
        self.assertFalse(best["verifiable"])

    def test_ram_attribute_resolved_by_context(self):
        result = nlp_engine.analyze_query("laptop with 16gb ram", PROFILE)
        attr = result["attributes"][0]
        self.assertEqual(attr["attribute"], "ram")
        self.assertEqual(attr["value"], 16.0)

    def test_comparison_intent_not_triggered_by_the_word_for(self):
        result = nlp_engine.analyze_query("laptop for students", PROFILE)
        self.assertNotEqual(result["intent"], "comparison")

    def test_comparison_intent_triggered_by_vs(self):
        result = nlp_engine.analyze_query("laptop A vs laptop B", PROFILE)
        self.assertEqual(result["intent"], "comparison")

    def test_no_known_entity_in_query_yields_no_entity_requirement(self):
        result = nlp_engine.analyze_query("premium subscription plan", PROFILE)
        self.assertIsNone(result["entity"])
        categories = [r["category"] for r in result["requirements"]]
        self.assertNotIn("entity", categories)

    def test_comparison_query_recognizes_both_entities(self):
        # Regression: the second name in "X vs Y" used to fall through to
        # unrecognized_term word by word instead of being understood as
        # the other side of the comparison.
        profile = dict(PROFILE, entities=[
            {"text": "laptop", "page_count": 4, "confidence": "high"},
            {"text": "keyboard", "page_count": 3, "confidence": "high"},
        ])
        result = nlp_engine.analyze_query("Laptop vs Keyboard", profile)
        entity_requirements = [r for r in result["requirements"] if r["category"] == "entity"]
        self.assertEqual({r["key"] for r in entity_requirements}, {"laptop", "keyboard"})
        self.assertEqual(result["unrecognized_terms"], [])

    def test_comparison_entity_only_searched_for_when_intent_is_comparison(self):
        # A single-entity query must never spuriously pull in a second
        # entity just because it happens to be discoverable in the text.
        profile = dict(PROFILE, entities=[
            {"text": "laptop", "page_count": 4, "confidence": "high"},
            {"text": "keyboard", "page_count": 3, "confidence": "high"},
        ])
        result = nlp_engine.analyze_query("Best laptop for programming", profile)
        entity_requirements = [r for r in result["requirements"] if r["category"] == "entity"]
        self.assertEqual({r["key"] for r in entity_requirements}, {"laptop"})


if __name__ == "__main__":
    unittest.main()
