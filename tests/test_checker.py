import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import checker  # noqa: E402
import narrator  # noqa: E402

EVIDENCE = {"minute": 78, "team": "Northbridge Athletic", "player": "Eli Quill",
            "distance_m": 18.8, "xg": 0.085, "home_goals": 3, "away_goals": 1,
            "home_team": "Rivergate United", "away_team": "Northbridge Athletic"}
NAMES = ["Eli Quill", "Tomas Mercer", "Rivergate United", "Northbridge Athletic"]


class CheckerTests(unittest.TestCase):
    def test_accepts_supported_text(self):
        t = "78' Eli Quill scores from 18.8 m (xG 0.09). Score 3-1."
        self.assertTrue(checker.check(t, EVIDENCE, NAMES)["ok"])

    def test_rejects_invented_number(self):
        t = "78' Eli Quill scores from 25 m. Score 3-1."
        r = checker.check(t, EVIDENCE, NAMES)
        self.assertFalse(r["ok"])
        self.assertIn("number 25 is not in the evidence", r["issues"])

    def test_rejects_unlisted_player(self):
        t = "78' Tomas Mercer scores. Score 3-1."
        r = checker.check(t, EVIDENCE, NAMES)
        self.assertFalse(r["ok"])
        self.assertTrue(any("Tomas Mercer" in i for i in r["issues"]))

    def test_devanagari_digits_are_checked(self):
        t = "७८ मिनट: Eli Quill ने गोल किया। स्कोर ३-९।"
        self.assertFalse(checker.check(t, EVIDENCE, NAMES)["ok"])

    def test_rejects_empty(self):
        self.assertFalse(checker.check("  ", EVIDENCE, NAMES)["ok"])


class TemplateTests(unittest.TestCase):
    def test_every_template_passes_checker(self):
        goal = {"kind": "goal", "evidence": {
            "minute": 78, "team": "Northbridge Athletic", "player": "Eli Quill",
            "situation": "goal that cuts the deficit", "distance_m": 18.8, "xg": 0.085,
            "shot_speed_kmh": 119.7, "home_goals": 3, "away_goals": 2,
            "home_team": "Rivergate United", "away_team": "Northbridge Athletic",
            "momentum_share_pct": 63.2, "window_minutes": 5}}
        for mode in ("analyst", "casual"):
            for lang in ("en", "hi"):
                text = narrator.template(goal, mode, lang)
                r = checker.check(text, goal["evidence"], NAMES)
                self.assertTrue(r["ok"], f"{mode}/{lang}: {text} -> {r['issues']}")


if __name__ == "__main__":
    unittest.main()
