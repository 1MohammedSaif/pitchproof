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


PLAYER = {"player": "Tomas Mercer", "team": "Northbridge Athletic", "role": "RM", "shots": 3, "goals": 1,
          "xg": 0.27, "passes": 29, "tackles_won": 4, "pressures": 4, "pass_accuracy_pct": 62.1}
SCORE = {"minute": 78, "home_goals": 3, "away_goals": 1, "home_team": "Rivergate United",
         "away_team": "Northbridge Athletic", "xg": 0.085}


class UnitBindingTests(unittest.TestCase):
    """A number must match the field for its unit, not just appear somewhere in the evidence."""

    def test_goals_not_confused_with_tackles(self):
        # 4 is in the evidence (tackles, pressures) but goals = 1.
        t = "Tomas Mercer had 3 shots for Northbridge Athletic and scored 4 goals."
        r = checker.check(t, PLAYER, NAMES)
        self.assertFalse(r["ok"])
        self.assertIn("4 is not a valid goals value", r["issues"])

    def test_shots_not_confused_with_pressures(self):
        t = "Tomas Mercer had 4 shots for Northbridge Athletic and scored 1 goal."
        self.assertFalse(checker.check(t, PLAYER, NAMES)["ok"])

    def test_correct_text_still_passes(self):
        t = "Tomas Mercer had 3 shots for Northbridge Athletic and scored 1 goal."
        self.assertTrue(checker.check(t, PLAYER, NAMES)["ok"])

    def test_score_checked_even_before_a_full_stop(self):
        self.assertTrue(checker.check("Score 3-1.", SCORE, NAMES)["ok"])
        self.assertFalse(checker.check("Score 3-2.", SCORE, NAMES)["ok"])

    def test_score_order_matters(self):
        self.assertFalse(checker.check("Rivergate United 1-3 Northbridge Athletic", SCORE, NAMES)["ok"])

    def test_small_xg_is_not_zero(self):
        self.assertFalse(checker.check("(xG 0.00)", SCORE, NAMES)["ok"])
        self.assertTrue(checker.check("(xG 0.09)", SCORE, NAMES)["ok"])

    def test_decimal_is_not_read_as_a_score(self):
        recap = {"home_goals": 3, "away_goals": 2, "home_xg": 2.25, "away_xg": 1.17}
        self.assertTrue(checker.check("xG 2.25-1.17", recap, NAMES)["ok"])
        self.assertFalse(checker.check("xG 1.17-2.25", recap, NAMES)["ok"])


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
