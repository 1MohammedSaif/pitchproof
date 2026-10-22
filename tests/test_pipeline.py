"""End-to-end tests: generate a match, load SQL, run all agents, and measure the Checker."""
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
import checker  # noqa: E402
import generator  # noqa: E402
import metrics  # noqa: E402
import pipeline  # noqa: E402

NUM = re.compile(r"\d+(?:\.\d+)?")


def _mutations(tok):
    if "." in tok:
        dec = len(tok.split(".")[1])
        v = float(tok)
        out = [f"{v + 1.0:.{dec}f}", f"{max(v - 1.0, 0):.{dec}f}", f"{max(v - 0.1, 0):.{dec}f}"]
    else:
        v = int(tok)
        out = [str(v + 1), str(v + 2), str(max(v - 1, 0))]
    return [m for m in out if m != tok]


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = {k: os.environ.pop(k, None) for k in ("PITCHPROOF_PROVIDER", "PITCHPROOF_DEMO_FAULT")}
        os.environ["PITCHPROOF_PROVIDER"] = "mock"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "t.db")
        conn = metrics.connect(cls.db)
        metrics.load(conn, generator.generate(26), os.path.join(ROOT, "sql", "schema.sql"))
        cls.facts = metrics.match_facts(conn)
        cls.names = [r[0] for r in conn.execute("SELECT name FROM players")]
        cls.names += list(conn.execute("SELECT home_name, away_name FROM matches").fetchone())
        conn.close()
        cls.out = pipeline.run(cls.db)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        cls.tmp.cleanup()

    def test_sql_goals_match_final_score(self):
        m = self.facts["match"]
        self.assertEqual(sum(t["goals"] for t in self.facts["team_shots"]), m["home_goals"] + m["away_goals"])

    def test_clean_run_has_no_rejections_or_fallbacks(self):
        s = self.out["summary"]
        self.assertEqual(s["checker_rejections"], 0)
        self.assertEqual(s["template_fallbacks"], 0)
        self.assertEqual(s["model_errors"], 0)

    def test_every_moment_has_all_four_variants(self):
        for item in self.out["moments"] + self.out["spotlights"]:
            self.assertEqual(sorted(item["narrations"]),
                             ["analyst_en", "analyst_hi", "casual_en", "casual_hi"])

    def test_spotlights_exist_and_use_real_players(self):
        self.assertGreaterEqual(len(self.out["spotlights"]), 1)
        for sp in self.out["spotlights"]:
            self.assertIn(sp["evidence"]["player"], self.names)

    def test_every_published_text_passes_the_checker(self):
        for item in self.out["moments"] + self.out["spotlights"]:
            for key, n in item["narrations"].items():
                self.assertTrue(checker.check(n["text"], item["evidence"], self.names)["ok"], (item["id"], key))

    def test_injected_faults_are_caught_and_repaired(self):
        os.environ["PITCHPROOF_DEMO_FAULT"] = "1"
        try:
            out = pipeline.run(self.db)
        finally:
            os.environ.pop("PITCHPROOF_DEMO_FAULT", None)
        s = out["summary"]
        self.assertEqual(s["checker_rejections"], s["narrations"])
        self.assertEqual(s["repaired_after_retry"], s["narrations"])
        self.assertEqual(s["template_fallbacks"], 0)

    def test_checker_mutation_score(self):
        """Change every number in every narration, one at a time. Nearly all must be rejected.

        The few that pass are whole-number roundings (72.1 -> 72.0), which are tolerated on purpose.
        """
        total = caught = 0
        for item in self.out["moments"] + self.out["spotlights"]:
            for n in item["narrations"].values():
                text = n["text"]
                for m in NUM.finditer(text):
                    for wrong in _mutations(m.group(0)):
                        bad = text[:m.start()] + wrong + text[m.end():]
                        total += 1
                        if not checker.check(bad, item["evidence"], self.names)["ok"]:
                            caught += 1
        self.assertGreater(total, 400)
        self.assertGreaterEqual(caught / total, 0.98, f"caught {caught} of {total}")


if __name__ == "__main__":
    unittest.main()
