import unittest

import _pathfix  # noqa: F401
from lib import domain_vocabulary


class DomainVocabularyTest(unittest.TestCase):
    def test_get_vocabulary_resolves_each_named_domain(self):
        self.assertIs(domain_vocabulary.get_vocabulary("shopping"), domain_vocabulary.SHOPPING)
        self.assertIs(domain_vocabulary.get_vocabulary("education"), domain_vocabulary.EDUCATION)
        self.assertIs(domain_vocabulary.get_vocabulary("healthcare"), domain_vocabulary.HEALTHCARE)

    def test_unknown_or_missing_domain_falls_back_to_generic(self):
        self.assertIs(domain_vocabulary.get_vocabulary("corporate"), domain_vocabulary.GENERIC)
        self.assertIs(domain_vocabulary.get_vocabulary("content"), domain_vocabulary.GENERIC)
        self.assertIs(domain_vocabulary.get_vocabulary(None), domain_vocabulary.GENERIC)
        self.assertIs(domain_vocabulary.get_vocabulary("nonsense"), domain_vocabulary.GENERIC)

    def test_generic_has_no_attribute_guesses(self):
        # Inventing "attributes" for an unclassified domain would be
        # exactly the kind of unfounded assumption this subsystem refuses
        # to make elsewhere -- see GENERIC's own docstring.
        self.assertEqual(domain_vocabulary.GENERIC["attributes"], {})

    def test_each_domain_bundle_has_the_same_shape(self):
        for bundle in domain_vocabulary.ALL_DOMAINS:
            self.assertEqual(set(bundle.keys()), {"attributes", "audiences", "use_cases"})

    def test_concept_words_are_domain_scoped_not_a_global_union(self):
        # Regression for a real bug: "business" is a SHOPPING audience
        # word; it must not appear in education's concept words and
        # thereby block "Business Administration" from being a candidate
        # entity name on an education site.
        education_words = domain_vocabulary.concept_words_for("education")
        shopping_words = domain_vocabulary.concept_words_for("shopping")
        self.assertNotIn("business", education_words)
        self.assertIn("business", shopping_words)
        self.assertNotIn("science", education_words)  # from shopping's "data science"

    def test_education_and_healthcare_vocabularies_are_distinct(self):
        education_words = domain_vocabulary.concept_words_for("education")
        healthcare_words = domain_vocabulary.concept_words_for("healthcare")
        self.assertIn("tuition", education_words)
        self.assertNotIn("tuition", healthcare_words)
        self.assertIn("patient", healthcare_words)
        self.assertNotIn("patient", education_words)


if __name__ == "__main__":
    unittest.main()
