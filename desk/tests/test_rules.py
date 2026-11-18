"""Pure-Python tests of the business rules (no Django needed):
    python -m unittest desk.tests.test_rules
"""
import json
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from desk import rules

SEED = Path(__file__).resolve().parents[1] / "data" / "loans_seed.json"
T = date(2026, 11, 18)


def calc(**kw):
    base = dict(total_due=1000, paid=0, status="Current", due=date(2026, 11, 18), issued=date(2026, 10, 20),
                officer="Oscar", today=T)
    base.update(kw)
    return rules.compute(**base)


class FlagTests(unittest.TestCase):
    def test_due_today(self):
        self.assertEqual(calc().flag, "DUE TODAY")

    def test_due_soon_window(self):
        self.assertEqual(calc(due=date(2026, 11, 21)).flag, "DUE SOON")
        self.assertEqual(calc(due=date(2026, 11, 22)).flag, "Not Due")
        self.assertEqual(calc(due=date(2026, 11, 22), window=5).flag, "DUE SOON")

    def test_defaulter_and_severe(self):
        self.assertEqual(calc(due=date(2026, 11, 17)).flag, "DEFAULTER")
        self.assertEqual(calc(due=date(2026, 10, 19)).flag, "SEVERE DEFAULT")  # 30 days late
        self.assertEqual(calc(due=date(2026, 10, 20)).flag, "DEFAULTER")      # 29 days late

    def test_paid_and_completed(self):
        self.assertEqual(calc(paid=1000).flag, "Paid")
        c = calc(status="Completed", paid=0)
        self.assertEqual((c.flag, c.out), ("Paid", 0))
        self.assertEqual(calc(paid=1000, status="Current").status, "Completed")

    def test_check_flags(self):
        self.assertEqual(calc(due=None).flag, "CHECK DATE")
        self.assertEqual(calc(total_due=0).flag, "CHECK DATA")

    def test_partial_payment_reduces_outstanding(self):
        self.assertEqual(calc(paid=400).out, 600)


class CleaningTests(unittest.TestCase):
    def test_officer_cleaning(self):
        self.assertEqual(rules.clean_officer("oscar", "G"), "Oscar")
        self.assertEqual(rules.clean_officer("  sangai   moris ", "A"), "Sangai Moris")
        self.assertEqual(rules.clean_officer(None, "A"), "Unassigned")
        self.assertEqual(rules.clean_officer("Brand New Person", "G"), "Brand New Person")

    def test_status_cleaning(self):
        for raw, out, want in [("Compeleted", 5, "Completed"), ("Deafult", 5, "Default"),
                               ("On Going", 5, "Current"), ("Issued", 0, "Current"),
                               (None, 0, "Completed"), (None, 5, "Current")]:
            self.assertEqual(rules.clean_status(raw, out), want, raw)

    def test_parse_date(self):
        self.assertEqual(rules.parse_date("2026-11-18"), date(2026, 11, 18))
        for bad in (None, "9/92025", "2019-01-01", "2031-01-01", "2026-02-30", 5):
            self.assertIsNone(rules.parse_date(bad), bad)


class SeedRegression(unittest.TestCase):
    """Totals that were verified against the original HTML page's JavaScript on 18 Nov 2026."""

    def test_flag_counts(self):
        data = json.loads(SEED.read_text(encoding="utf8"))
        flags = Counter()
        for d in data:
            p, i = d.get("p") or 0, d.get("i") or 0
            td = d["td"] if isinstance(d.get("td"), (int, float)) else p + i
            rc = d.get("rc") or 0
            c = rules.compute(
                total_due=td, paid=rc, status=rules.clean_status(d.get("st"), max(0, td - rc)),
                due=rules.parse_date(d.get("dd")), issued=rules.parse_date(d.get("di")),
                officer=rules.clean_officer(d.get("off"), d["b"]), today=T)
            flags[c.flag] += 1
        self.assertEqual(len(data), 4153)
        self.assertEqual(dict(flags), {"Paid": 3469, "SEVERE DEFAULT": 433, "CHECK DATE": 7,
                                       "Not Due": 182, "DEFAULTER": 34, "DUE SOON": 21, "DUE TODAY": 7})


if __name__ == "__main__":
    unittest.main()
