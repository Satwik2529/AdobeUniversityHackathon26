#!/usr/bin/env python3
"""Unit tests for opportunity-and-monitoring.

Unlike every detector's tests, this skill's input is not a snapshot of pages but a list
of already-computed detector findings (the raw per-detector finding dicts, before the
entrypoint's own deduplication, severity assignment, or sequential id numbering). These
tests build minimal finding dicts directly.

Run: python3 skills/opportunity-and-monitoring/scripts/test_opportunity.py
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import select_opportunities as opp  # noqa: E402

ORIGIN = "https://example.test"


# ------------------------------------------------------------------ finding factories

def finding(check_id, detector, gate_impact="degrades", reach="template",
           certainty="measured", affected_urls=None, confidence="high",
           effort="template-change", owner="engineering", sample=None,
           severity_ceiling=None, funnel_stage="understood"):
    return {
        "check_id": check_id,
        "title": "Finding for %s" % check_id,
        "gate_impact": gate_impact,
        "reach": reach,
        "certainty": certainty,
        "funnel_stage": funnel_stage,
        "detector": detector,
        "evidence": "Evidence for %s" % check_id,
        "affected_urls": affected_urls if affected_urls is not None else
                        [ORIGIN + "/p1.html", ORIGIN + "/p2.html", ORIGIN + "/p3.html"],
        "evidence_detail": {"check_id": check_id, "method": "m", "observed": {},
                            "expected": "e", "sample": sample or {"checked": 3,
                                                                  "failing": 3},
                            "confidence": confidence, "nondeterministic": False,
                            "detector": detector},
        "suggested_action": {"summary": "Fix %s" % check_id, "how": ["step"],
                             "mechanism": "mechanism text for %s" % check_id,
                             "effort": effort, "owner": owner,
                             "verification": "verify"},
        **({"severity_ceiling": severity_ceiling} if severity_ceiling else {}),
    }


def snapshot(archetype="ecommerce"):
    return {"schema_version": "1.0", "site": "example.test", "origin": ORIGIN,
           "site_archetype": archetype, "audited_at": "2026-09-06T00:00:00Z",
           "coverage": {}}


# ============================================================ severity/score helpers

class TestSeverityMirror(unittest.TestCase):
    """These must reproduce merge_findings.derive_severity's outputs exactly, since
    the whole point of duplicating it is byte-identical prioritisation."""

    def test_blocks_sitewide_measured_is_critical(self):
        f = finding("X.Y", "d", gate_impact="blocks", reach="sitewide",
                   certainty="measured")
        self.assertEqual(opp._derive_severity(f), "critical")

    def test_page_reach_steps_down_one_level(self):
        f = finding("X.Y", "d", gate_impact="blocks", reach="page",
                   certainty="measured")
        self.assertEqual(opp._derive_severity(f), "high")

    def test_template_reach_steps_down_only_from_critical(self):
        f = finding("X.Y", "d", gate_impact="degrades", reach="template",
                   certainty="measured")
        self.assertEqual(opp._derive_severity(f), "high")

    def test_inferred_certainty_caps_at_high(self):
        f = finding("X.Y", "d", gate_impact="blocks", reach="sitewide",
                   certainty="inferred")
        self.assertEqual(opp._derive_severity(f), "high")

    def test_low_confidence_caps_at_medium(self):
        f = finding("X.Y", "d", gate_impact="blocks", reach="sitewide",
                   certainty="measured", confidence="low")
        self.assertEqual(opp._derive_severity(f), "medium")

    def test_severity_ceiling_is_respected(self):
        f = finding("X.Y", "d", gate_impact="blocks", reach="sitewide",
                   certainty="measured", severity_ceiling="low")
        self.assertEqual(opp._derive_severity(f), "low")

    def test_severity_override_wins_outright(self):
        f = finding("X.Y", "d", gate_impact="weakens", reach="page")
        f["severity_override"] = "info"
        self.assertEqual(opp._derive_severity(f), "info")

    def test_small_sample_caps_at_medium_except_origin_level(self):
        f = finding("X.Y", "d", gate_impact="blocks", reach="template",
                   certainty="measured", sample={"checked": 1, "failing": 1})
        self.assertEqual(opp._derive_severity(f), "medium")

    def test_score_is_higher_for_more_severe_and_wider_reach(self):
        critical_sitewide = finding("X.A", "d", gate_impact="blocks", reach="sitewide")
        low_page = finding("X.B", "d", gate_impact="weakens", reach="page")
        self.assertGreater(opp._score(critical_sitewide), opp._score(low_page))


# ==================================================================== load_findings

class TestLoadFindings(unittest.TestCase):

    def test_reads_detector_shaped_payload(self):
        path = "/tmp/opp_test_findings_%d.json" % os.getpid()
        with open(path, "w") as h:
            json.dump({"detector": "d", "findings": [finding("X.Y", "d")],
                      "not_assessed": []}, h)
        try:
            result = opp.load_findings([path])
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["check_id"], "X.Y")
        finally:
            os.remove(path)

    def test_skips_missing_file_without_crashing(self):
        result = opp.load_findings(["/tmp/does-not-exist-%d.json" % os.getpid()])
        self.assertEqual(result, [])

    def test_skips_malformed_json_without_crashing(self):
        path = "/tmp/opp_test_malformed_%d.json" % os.getpid()
        with open(path, "w") as h:
            h.write("{not valid json")
        try:
            result = opp.load_findings([path])
            self.assertEqual(result, [])
        finally:
            os.remove(path)

    def test_ignores_findings_with_no_check_id(self):
        path = "/tmp/opp_test_nocheckid_%d.json" % os.getpid()
        with open(path, "w") as h:
            json.dump({"findings": [{"title": "no check_id here"}]}, h)
        try:
            result = opp.load_findings([path])
            self.assertEqual(result, [])
        finally:
            os.remove(path)


# ================================================================ cross-detector compounds

class TestCompoundDetection(unittest.TestCase):

    def test_access_and_render_on_overlapping_urls_produces_compound(self):
        shared = [ORIGIN + "/p1.html", ORIGIN + "/p2.html"]
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit", gate_impact="blocks",
                   affected_urls=shared),
            finding("RND.CSR_SHELL", "render-readability-audit",
                   affected_urls=shared),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        cats = [o["category"] for o in opportunities]
        self.assertIn("cross-detector-template", cats)

    def test_no_compound_without_url_overlap(self):
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit",
                   affected_urls=[ORIGIN + "/a.html"]),
            finding("RND.CSR_SHELL", "render-readability-audit",
                   affected_urls=[ORIGIN + "/completely-different.html"]),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        related = [o["related_findings"] for o in opportunities]
        for r in related:
            self.assertFalse({"ACC.UA_BLOCKED", "RND.CSR_SHELL"} <= set(r))

    def test_no_named_compound_from_a_single_detector_alone(self):
        """The named cross-detector-pair rules (access+render, sde+ans, etc.) never
        fire from findings within one detector -- a same-detector pair sharing a page
        set may still surface as generic 'template-leverage', a distinct, correctly
        named category, which this test does not forbid."""
        findings = [finding("ACC.UA_BLOCKED", "crawl-access-audit"),
                   finding("ACC.ROBOTS_BLOCKS_ALL", "crawl-access-audit")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        for o in opportunities:
            self.assertNotEqual(o["category"], "cross-detector-template")
            self.assertNotIn(o["category"], {
                "access-remediation", "rendering-readability-remediation",
                "entity-schema-alignment", "answer-surface-improvement",
                "freshness-source-of-truth", "engagement-action-pathway"})

    def test_sde_ans_compound_produces_entity_schema_alignment(self):
        shared = [ORIGIN + "/p1.html"]
        findings = [
            finding("SDE.INCOMPLETE_REQUIRED_PROPS", "structured-data-entity-audit",
                   affected_urls=shared),
            finding("ANS.SPECS_NOT_EXTRACTABLE", "answer-retrievability-audit",
                   affected_urls=shared),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        cats = [o["category"] for o in opportunities]
        self.assertIn("entity-schema-alignment", cats)

    def test_ans_eng_compound_produces_engagement_action_pathway(self):
        shared = [ORIGIN + "/p1.html"]
        findings = [
            finding("ANS.NO_DIRECT_ANSWER_LEAD", "answer-retrievability-audit",
                   affected_urls=shared),
            finding("ENG.DEAD_END_HIGH_VALUE_PAGE", "engagement-audit",
                   affected_urls=shared),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        cats = [o["category"] for o in opportunities]
        self.assertIn("engagement-action-pathway", cats)

    def test_compound_scope_is_sample_scoped_language(self):
        shared = [ORIGIN + "/p1.html", ORIGIN + "/p2.html"]
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit", affected_urls=shared),
            finding("RND.CSR_SHELL", "render-readability-audit", affected_urls=shared),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        compound = next(o for o in opportunities
                        if o["category"] == "cross-detector-template")
        self.assertIn("sampled", compound["scope"].lower())
        self.assertNotIn("the entire site", compound["scope"].lower())
        self.assertNotIn("sitewide", compound["scope"].lower())


# ==================================================================== template leverage

class TestTemplateLeverage(unittest.TestCase):

    def test_multiple_checks_same_urls_produces_leverage_opportunity(self):
        shared = [ORIGIN + "/p1.html", ORIGIN + "/p2.html"]
        findings = [
            finding("RND.NO_H1", "render-readability-audit", affected_urls=shared),
            finding("RND.THIN_CONTENT", "render-readability-audit", affected_urls=shared),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        leverage = [o for o in opportunities
                   if "One template fix" in o["title"]]
        self.assertEqual(len(leverage), 1)

    def test_single_check_id_alone_is_not_leverage(self):
        findings = [finding("RND.NO_H1", "render-readability-audit")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        self.assertFalse(any("One template fix" in o["title"] for o in opportunities))

    def test_already_covered_by_compound_is_not_double_counted_as_leverage(self):
        shared = [ORIGIN + "/p1.html", ORIGIN + "/p2.html"]
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit", affected_urls=shared),
            finding("RND.CSR_SHELL", "render-readability-audit", affected_urls=shared),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        leverage = [o for o in opportunities if "One template fix" in o["title"]]
        self.assertEqual(len(leverage), 0,
                         "the compound rule already covers this exact pair; a "
                         "second, generic leverage opportunity for the same finding "
                         "set would be a near-duplicate")

    def test_single_page_overlap_is_not_leverage(self):
        findings = [
            finding("RND.NO_H1", "render-readability-audit",
                   affected_urls=[ORIGIN + "/only-one.html"]),
            finding("RND.THIN_CONTENT", "render-readability-audit",
                   affected_urls=[ORIGIN + "/only-one.html"]),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        self.assertFalse(any("One template fix" in o["title"] for o in opportunities))


# ========================================================================= monitoring

class TestMonitoring(unittest.TestCase):

    def test_intra_site_fact_conflict_produces_monitoring_opportunity(self):
        findings = [finding("FRC.INTRA_SITE_FACT_CONFLICT",
                           "freshness-corroboration-audit")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        monitoring = [o for o in opportunities if o["category"] == "monitoring"]
        self.assertEqual(len(monitoring), 1)
        self.assertEqual(monitoring[0]["related_findings"],
                         ["FRC.INTRA_SITE_FACT_CONFLICT"])

    def test_no_monitoring_without_the_triggering_check(self):
        findings = [finding("ACC.UA_BLOCKED", "crawl-access-audit")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        self.assertFalse(any(o["category"] == "monitoring" for o in opportunities))

    def test_monitoring_states_cadence(self):
        findings = [finding("SDE.ORG_IDENTITY_CONFLICT",
                           "structured-data-entity-audit")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        monitoring = next(o for o in opportunities if o["category"] == "monitoring")
        self.assertTrue(any("quarterly" in a or "monthly" in a
                           for a in monitoring["recommended_actions"]))


# ================================================================= deferred capabilities

class TestDeferredCapabilities(unittest.TestCase):

    def test_always_present_on_a_clean_site(self):
        opportunities, _ = opp.select_opportunities(snapshot(), [])
        deferred = [o for o in opportunities if o["category"] == "deferred-capability"]
        self.assertGreaterEqual(len(deferred), 1)

    def test_never_worded_as_an_observed_result(self):
        opportunities, _ = opp.select_opportunities(snapshot(), [])
        for o in opportunities:
            if o["category"] != "deferred-capability":
                continue
            text = json.dumps(o).lower()
            for forbidden in ("click-through rate:", "conversion rate:", "ctr is",
                             "bounce rate is", "actual engagement is"):
                self.assertNotIn(forbidden, text)

    def test_have_no_related_findings_since_they_are_not_a_finding_result(self):
        opportunities, _ = opp.select_opportunities(snapshot(), [])
        for o in opportunities:
            if o["category"] == "deferred-capability":
                self.assertEqual(o["related_findings"], [])


# ===================================================================== healthy site

class TestHealthySiteBehavior(unittest.TestCase):

    def test_zero_findings_produces_zero_remediation_opportunities(self):
        opportunities, plan = opp.select_opportunities(snapshot(), [])
        remediation_categories = {"access-remediation",
                                  "rendering-readability-remediation",
                                  "entity-schema-alignment",
                                  "answer-surface-improvement",
                                  "freshness-source-of-truth",
                                  "engagement-action-pathway",
                                  "cross-detector-template"}
        self.assertFalse(any(o["category"] in remediation_categories
                            for o in opportunities))

    def test_measurement_plan_is_always_present(self):
        _, plan = opp.select_opportunities(snapshot(), [])
        self.assertIn("tracks", plan)
        self.assertGreaterEqual(len(plan["tracks"]), 4)

    def test_informational_only_findings_do_not_trigger_remediation(self):
        findings = [finding("SDE.MICRODATA_ONLY", "structured-data-entity-audit",
                           gate_impact="weakens", severity_ceiling="low")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        # A single, low-severity, informational-style finding alone should not
        # spawn a manufactured remediation opportunity (non-duplication gate).
        self.assertFalse(any(len(o["related_findings"]) == 1
                            and o["category"] not in ("monitoring",
                                                       "deferred-capability")
                            for o in opportunities))

    def test_independent_low_severity_findings_do_not_combine_falsely(self):
        findings = [
            finding("RND.NO_HEADING_ANCHORS", "render-readability-audit",
                   affected_urls=[ORIGIN + "/a.html"]),
            finding("SDE.NO_SAMEAS", "structured-data-entity-audit",
                   affected_urls=[ORIGIN + "/b.html"]),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        for o in opportunities:
            self.assertFalse({"RND.NO_HEADING_ANCHORS", "SDE.NO_SAMEAS"}
                            <= set(o["related_findings"]))


# ================================================================= determinism/robustness

class TestDeterminismAndRobustness(unittest.TestCase):

    def test_compound_description_detector_order_is_stable_across_hash_seeds(self):
        """Regression: _COMPOUND_TEMPLATES keys are frozensets, and iterating a
        frozenset has no guaranteed order across Python processes (hash
        randomization). This was found during final-integration testing: the same
        input produced a different detector-name order in the description text
        between two subprocess runs. detectors must be sorted, not merely listed."""
        shared = [ORIGIN + "/p1.html", ORIGIN + "/p2.html"]
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit", affected_urls=shared),
            finding("RND.CSR_SHELL", "render-readability-audit", affected_urls=shared),
        ]
        results = set()
        for _ in range(20):
            opportunities, _ = opp.select_opportunities(snapshot(),
                                                         copy.deepcopy(findings))
            compound = next(o for o in opportunities
                           if o["category"] == "cross-detector-template")
            results.add(compound["description"])
        self.assertEqual(len(results), 1,
                         "description text varied across repeated calls: %s" % results)

    def test_output_is_deterministic_across_runs(self):
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit"),
            finding("RND.CSR_SHELL", "render-readability-audit"),
            finding("FRC.INTRA_SITE_FACT_CONFLICT", "freshness-corroboration-audit"),
        ]
        o1, p1 = opp.select_opportunities(snapshot(), copy.deepcopy(findings))
        o2, p2 = opp.select_opportunities(snapshot(), copy.deepcopy(findings))
        self.assertEqual(json.dumps(o1, sort_keys=True), json.dumps(o2, sort_keys=True))
        self.assertEqual(json.dumps(p1, sort_keys=True), json.dumps(p2, sort_keys=True))

    def test_output_order_independent_of_input_order(self):
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit"),
            finding("RND.CSR_SHELL", "render-readability-audit"),
        ]
        o1, _ = opp.select_opportunities(snapshot(), findings)
        o2, _ = opp.select_opportunities(snapshot(), list(reversed(findings)))
        self.assertEqual([o["category"] for o in o1], [o["category"] for o in o2])

    def test_duplicate_findings_do_not_produce_duplicate_opportunities(self):
        f = finding("FRC.INTRA_SITE_FACT_CONFLICT", "freshness-corroboration-audit")
        opportunities, _ = opp.select_opportunities(snapshot(), [f, copy.deepcopy(f)])
        monitoring = [o for o in opportunities if o["category"] == "monitoring"]
        self.assertEqual(len(monitoring), 1)

    def test_unknown_detector_id_does_not_crash(self):
        findings = [finding("XYZ.SOMETHING", "not-a-real-detector")]
        opportunities, plan = opp.select_opportunities(snapshot(), findings)
        self.assertIsInstance(opportunities, list)

    def test_missing_severity_inputs_do_not_crash(self):
        f = finding("X.Y", "d")
        del f["gate_impact"]
        del f["reach"]
        opportunities, _ = opp.select_opportunities(snapshot(), [f])
        self.assertIsInstance(opportunities, list)

    def test_missing_evidence_detail_does_not_crash(self):
        f = finding("X.Y", "d")
        del f["evidence_detail"]
        opportunities, _ = opp.select_opportunities(snapshot(), [f])
        self.assertIsInstance(opportunities, list)

    def test_unknown_archetype_falls_back_to_unknown(self):
        opportunities, _ = opp.select_opportunities(snapshot(archetype="not-a-real-one"),
                                                     [])
        self.assertIsInstance(opportunities, list)

    def test_findings_are_not_mutated(self):
        f = finding("ACC.UA_BLOCKED", "crawl-access-audit")
        original = copy.deepcopy(f)
        opp.select_opportunities(snapshot(), [f])
        self.assertEqual(f, original)

    def test_no_more_than_the_cap_total_opportunities(self):
        findings = []
        pairs = [("ACC.UA_BLOCKED", "crawl-access-audit"),
                ("RND.CSR_SHELL", "render-readability-audit"),
                ("SDE.INCOMPLETE_REQUIRED_PROPS", "structured-data-entity-audit"),
                ("ANS.SPECS_NOT_EXTRACTABLE", "answer-retrievability-audit"),
                ("FRC.INTRA_SITE_FACT_CONFLICT", "freshness-corroboration-audit"),
                ("ENG.DEAD_END_HIGH_VALUE_PAGE", "engagement-audit")]
        shared = [ORIGIN + "/p1.html", ORIGIN + "/p2.html"]
        for check_id, detector in pairs:
            findings.append(finding(check_id, detector, affected_urls=shared))
        findings.append(finding("SDE.ORG_IDENTITY_CONFLICT",
                                "structured-data-entity-audit"))
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        self.assertLessEqual(len(opportunities), opp.MAX_OPPORTUNITIES)

    def test_sequential_ids_are_assigned_and_unique(self):
        findings = [finding("ACC.UA_BLOCKED", "crawl-access-audit"),
                   finding("RND.CSR_SHELL", "render-readability-audit")]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        ids = [o["id"] for o in opportunities]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertTrue(i.startswith("OPP-"))


# ============================================================== evidence and honesty rules

class TestEvidenceAndHonesty(unittest.TestCase):

    def _all_opportunities(self):
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit",
                   affected_urls=[ORIGIN + "/p1.html"]),
            finding("RND.CSR_SHELL", "render-readability-audit",
                   affected_urls=[ORIGIN + "/p1.html"]),
            finding("SDE.INCOMPLETE_REQUIRED_PROPS", "structured-data-entity-audit",
                   affected_urls=[ORIGIN + "/p2.html"]),
            finding("ANS.SPECS_NOT_EXTRACTABLE", "answer-retrievability-audit",
                   affected_urls=[ORIGIN + "/p2.html"]),
            finding("FRC.INTRA_SITE_FACT_CONFLICT", "freshness-corroboration-audit"),
        ]
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        return opportunities

    def test_every_opportunity_has_required_fields(self):
        required = ("id", "category", "title", "summary", "description", "rationale",
                   "related_findings", "scope", "mechanism", "expected_effect",
                   "recommended_actions", "verification", "owner", "effort")
        for o in self._all_opportunities():
            for field in required:
                self.assertIn(field, o, "%s missing %s" % (o.get("title"), field))

    def test_no_causal_or_business_outcome_claims(self):
        forbidden = ("conversion loss", "will increase", "guarantees higher",
                    "guarantees ranking", "revenue impact", "will improve rankings",
                    "increase ai traffic by", "% increase", "% decrease",
                    "boost sales", "drive revenue")
        for o in self._all_opportunities():
            text = json.dumps(o).lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, text, "%s contains %r" % (o["title"], phrase))

    def test_summary_is_not_a_verbatim_repeat_of_title(self):
        for o in self._all_opportunities():
            if o["category"] == "deferred-capability":
                continue
            self.assertNotEqual(o["title"], o["summary"],
                               "%s: summary should not repeat the title verbatim"
                               % o["title"])

    def test_related_findings_reference_real_check_ids_from_input(self):
        findings = [
            finding("ACC.UA_BLOCKED", "crawl-access-audit",
                   affected_urls=[ORIGIN + "/p1.html"]),
            finding("RND.CSR_SHELL", "render-readability-audit",
                   affected_urls=[ORIGIN + "/p1.html"]),
        ]
        input_ids = {f["check_id"] for f in findings}
        opportunities, _ = opp.select_opportunities(snapshot(), findings)
        for o in opportunities:
            for check_id in o["related_findings"]:
                self.assertIn(check_id, input_ids)

    def test_never_recommends_paid_placement(self):
        for o in self._all_opportunities():
            text = json.dumps(o).lower()
            for phrase in ("paid placement", "sponsorship", "influencer",
                          "pay for", "advertising"):
                self.assertNotIn(phrase, text)

    def test_owner_and_effort_use_established_vocabulary(self):
        for o in self._all_opportunities():
            self.assertIn(o["owner"], ("engineering", "content", "brand-ops",
                                       "marketing", "mixed"))
            self.assertIn(o["effort"], ("trivial", "config", "content",
                                        "template-change", "platform-change"))


# ============================================================== measurement plan

class TestMeasurementPlan(unittest.TestCase):

    def test_tracks_have_required_fields(self):
        _, plan = opp.select_opportunities(snapshot(), [])
        for track in plan["tracks"]:
            for field in ("track", "what", "how", "cadence"):
                self.assertIn(field, track)

    def test_no_invented_baseline_values(self):
        _, plan = opp.select_opportunities(snapshot(), [])
        text = json.dumps(plan)
        # No fabricated numeric baseline like "current CTR is 3.2%".
        import re
        self.assertIsNone(re.search(r"is currently \d+%", text))
        self.assertIsNone(re.search(r"baseline: \d", text))

    def test_engagement_track_only_added_when_engagement_findings_present(self):
        _, plan_without = opp.select_opportunities(snapshot(), [])
        tracks_without = {t["track"] for t in plan_without["tracks"]}
        self.assertNotIn("Engagement pathway coverage", tracks_without)

        findings = [finding("ENG.DEAD_END_HIGH_VALUE_PAGE", "engagement-audit")]
        _, plan_with = opp.select_opportunities(snapshot(), findings)
        tracks_with = {t["track"] for t in plan_with["tracks"]}
        self.assertIn("Engagement pathway coverage", tracks_with)

    def test_caveat_is_present(self):
        _, plan = opp.select_opportunities(snapshot(), [])
        self.assertTrue(plan.get("caveat"))


# =============================================================================== CLI/main

class TestMainCli(unittest.TestCase):

    def test_end_to_end_via_main(self):
        wd = "/tmp/opp_cli_test_%d" % os.getpid()
        os.makedirs(wd, exist_ok=True)
        snap_path = os.path.join(wd, "snapshot.json")
        findings_path = os.path.join(wd, "findings.json")
        out_path = os.path.join(wd, "opp.json")
        with open(snap_path, "w") as h:
            json.dump(snapshot(), h)
        with open(findings_path, "w") as h:
            json.dump({"detector": "d", "findings": [finding("ACC.UA_BLOCKED",
                                                              "crawl-access-audit")],
                      "not_assessed": []}, h)
        rc = opp.main(["--snapshot", snap_path, "--findings", findings_path,
                      "--out", out_path])
        self.assertEqual(rc, 0)
        result = json.load(open(out_path))
        self.assertIn("opportunities", result)
        self.assertIn("measurement_plan", result)

    def test_no_network_capability_used(self):
        """Static confirmation that no networking module is imported."""
        source = open(os.path.join(HERE, "select_opportunities.py")).read()
        for forbidden in ("import requests", "import urllib.request", "import socket",
                         "import httpx", "urlopen("):
            self.assertNotIn(forbidden, source)


# ======================================================= file-based synthesis fixtures

FIXTURE_DIR = os.path.join(HERE, "fixtures")


class TestFileBasedFixtures(unittest.TestCase):
    """Exercises the real --findings CLI path (glob expansion, multi-file loading)
    against static JSON fixtures, not just in-memory factories -- see
    scripts/fixtures/README.md for what each file represents."""

    def _run(self, *names):
        paths = [os.path.join(FIXTURE_DIR, n + ".json") for n in names]
        return opp.select_opportunities(snapshot(), opp.load_findings(paths))

    def test_clean_fixture_pair_produces_no_remediation(self):
        opportunities, _ = self._run("clean-access", "clean-render")
        remediation = {"access-remediation", "rendering-readability-remediation",
                       "entity-schema-alignment", "answer-surface-improvement",
                       "freshness-source-of-truth", "engagement-action-pathway",
                       "cross-detector-template", "template-leverage"}
        self.assertFalse(any(o["category"] in remediation for o in opportunities))

    def test_access_render_fixture_pair_produces_compound(self):
        opportunities, _ = self._run("compound-access", "compound-render")
        self.assertTrue(any(o["category"] == "cross-detector-template"
                           for o in opportunities))

    def test_sde_ans_fixture_pair_produces_entity_schema_alignment(self):
        opportunities, _ = self._run("compound-sde", "compound-ans")
        self.assertTrue(any(o["category"] == "entity-schema-alignment"
                           for o in opportunities))

    def test_freshness_fixture_produces_monitoring(self):
        opportunities, _ = self._run("freshness-conflict")
        self.assertTrue(any(o["category"] == "monitoring" for o in opportunities))

    def test_leverage_fixture_produces_template_leverage(self):
        opportunities, _ = self._run("leverage")
        self.assertTrue(any(o["category"] == "template-leverage"
                           for o in opportunities))

    def test_glob_pattern_loads_all_matching_fixtures(self):
        pattern = os.path.join(FIXTURE_DIR, "compound-*.json")
        findings = opp.load_findings([pattern])
        detectors = {f["detector"] for f in findings}
        self.assertGreaterEqual(len(detectors), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
