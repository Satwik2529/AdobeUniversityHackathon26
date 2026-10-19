import unittest

import _pathfix  # noqa: F401
from lib import finding_correlator


def _evaluated(category, status, url):
    return {"id": "R-1", "category": category, "key": "ram",
            "evidence": {"status": status, "url": url}}


class FindingCorrelatorTest(unittest.TestCase):
    def test_no_report_returns_empty_list_not_an_error(self):
        self.assertEqual(finding_correlator.correlate([_evaluated("attribute", "NOT_FOUND", None)], None), [])

    def test_supported_requirement_never_correlated(self):
        report = {"findings": [{"id": "F-001", "check_id": "ANS.NO_SPEC", "affected_urls": ["https://x/p"]}]}
        evaluated = [_evaluated("attribute", "SUPPORTED", "https://x/p")]
        self.assertEqual(finding_correlator.correlate(evaluated, report), [])

    def test_weak_requirement_correlates_only_with_matching_url_and_prefix(self):
        report = {"findings": [
            {"id": "F-001", "check_id": "ANS.NO_SPEC", "affected_urls": ["https://x/p"]},
            {"id": "F-002", "check_id": "ACC.ROBOTS_BLOCK", "affected_urls": ["https://x/p"]},
            {"id": "F-003", "check_id": "ANS.NO_SPEC", "affected_urls": ["https://x/other-page"]},
        ]}
        evaluated = [_evaluated("attribute", "NOT_FOUND", "https://x/p")]
        correlations = finding_correlator.correlate(evaluated, report)
        finding_ids = [c["finding_id"] for c in correlations]
        self.assertEqual(finding_ids, ["F-001"])

    def test_relation_language_is_cautious(self):
        report = {"findings": [{"id": "F-001", "check_id": "ANS.NO_SPEC", "affected_urls": ["https://x/p"]}]}
        evaluated = [_evaluated("attribute", "NOT_FOUND", "https://x/p")]
        correlations = finding_correlator.correlate(evaluated, report)
        self.assertIn("Potentially related", correlations[0]["relation"])


if __name__ == "__main__":
    unittest.main()
