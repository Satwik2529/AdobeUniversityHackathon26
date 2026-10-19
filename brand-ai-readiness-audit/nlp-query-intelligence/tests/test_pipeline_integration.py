"""End-to-end tests that invoke pipeline.py exactly as the frontend
orchestrator will: as a subprocess with --snapshot/--out flags, reading
its JSON output back off disk.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline.py")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SHOPPING_SNAPSHOT = os.path.join(FIXTURES, "shopping-site", "snapshot.json")


def run(*args):
    proc = subprocess.run([sys.executable, PIPELINE] + list(args), capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class PipelineIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _out(self, name):
        return os.path.join(self.tmp.name, name)

    def test_profile_command_writes_valid_json(self):
        out = self._out("profile.json")
        code, _, err = run("profile", "--snapshot", SHOPPING_SNAPSHOT, "--out", out)
        self.assertEqual(code, 0, err)
        profile = _load(out)
        self.assertEqual(profile["domain_type"], "shopping")

    def test_full_chain_profile_generate_test_compare(self):
        profile_path = self._out("profile.json")
        queries_path = self._out("queries.json")
        result_a = self._out("a.json")
        result_b = self._out("b.json")
        comparison_path = self._out("cmp.json")

        self.assertEqual(run("profile", "--snapshot", SHOPPING_SNAPSHOT, "--out", profile_path)[0], 0)
        self.assertEqual(
            run("generate", "--snapshot", SHOPPING_SNAPSHOT, "--profile", profile_path, "--out", queries_path)[0], 0)
        self.assertEqual(
            run("test", "--query", "laptop", "--snapshot", SHOPPING_SNAPSHOT,
                "--profile", profile_path, "--out", result_a)[0], 0)
        self.assertEqual(
            run("test", "--query", "premium laptop", "--snapshot", SHOPPING_SNAPSHOT,
                "--profile", profile_path, "--out", result_b)[0], 0)
        code, _, err = run("compare", "--results", result_a, result_b, "--out", comparison_path)
        self.assertEqual(code, 0, err)
        comparison = _load(comparison_path)
        self.assertIn("score_delta", comparison)

    def test_missing_snapshot_fails_cleanly_not_a_crash(self):
        code, _, err = run("profile", "--snapshot", "/no/such/file.json", "--out", self._out("x.json"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", err)

    def test_test_command_works_without_an_explicit_profile(self):
        out = self._out("result.json")
        code, _, err = run("test", "--query", "laptop", "--snapshot", SHOPPING_SNAPSHOT, "--out", out)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(out))

    def test_analyzing_the_same_query_twice_is_deterministic(self):
        out1, out2 = self._out("r1.json"), self._out("r2.json")
        run("test", "--query", "laptop under 60000", "--snapshot", SHOPPING_SNAPSHOT, "--out", out1)
        run("test", "--query", "laptop under 60000", "--snapshot", SHOPPING_SNAPSHOT, "--out", out2)
        r1, r2 = _load(out1), _load(out2)
        for key in ("nlp", "requirements", "scoring"):
            self.assertEqual(r1[key], r2[key])

    def test_never_writes_into_the_snapshot_or_its_directory(self):
        with open(SHOPPING_SNAPSHOT, "rb") as fh:
            before = fh.read()
        run("test", "--query", "laptop", "--snapshot", SHOPPING_SNAPSHOT, "--out", self._out("r.json"))
        with open(SHOPPING_SNAPSHOT, "rb") as fh:
            after = fh.read()
        self.assertEqual(before, after)
        fixture_dir_before = sorted(os.listdir(os.path.dirname(SHOPPING_SNAPSHOT)))
        run("generate", "--snapshot", SHOPPING_SNAPSHOT, "--out", self._out("q.json"))
        fixture_dir_after = sorted(os.listdir(os.path.dirname(SHOPPING_SNAPSHOT)))
        self.assertEqual(fixture_dir_before, fixture_dir_after)


if __name__ == "__main__":
    unittest.main()
