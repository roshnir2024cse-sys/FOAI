import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E  # noqa: E402


def sample_apps():
    apps = []
    for s in E.SAMPLE_HOME:
        p = dict(E.PRESET_BY_KEY[s["key"]])
        p.update(s)
        apps.append(p)
    return apps


class EnergyTests(unittest.TestCase):
    def test_kwh_formula(self):
        a = dict(qty=2, watts=100, hours=5, standby_w=0)
        self.assertAlmostEqual(E.kwh_day(a), 1.0)

    def test_standby_counts_idle_hours(self):
        a = dict(qty=1, watts=100, hours=22, standby_w=10)
        self.assertAlmostEqual(E.kwh_day(a), (100 * 22 + 10 * 2) / 1000)

    def test_flat_tariff(self):
        self.assertAlmostEqual(E.Tariff("flat", 8).monthly_cost(100), 800)

    def test_slab_tariff_is_progressive(self):
        t = E.Tariff("slab")
        self.assertEqual(t.monthly_cost(100), 0)
        self.assertAlmostEqual(t.monthly_cost(150), 50 * 2.35)
        self.assertGreater(t.monthly_cost(300), t.monthly_cost(250))


class ValidationTests(unittest.TestCase):
    def test_rejects_empty(self):
        self.assertTrue(E.parse_request({"appliances": []})[2])

    def test_rejects_bad_numbers(self):
        _, _, errs = E.parse_request({"appliances": [dict(name="X", watts=-5, hours=30)]})
        self.assertTrue(errs)

    def test_min_hours_clamped_to_hours(self):
        apps, _, errs = E.parse_request({"appliances": [dict(name="X", watts=50, hours=2, min_hours=5)]})
        self.assertFalse(errs)
        self.assertEqual(apps[0]["min_hours"], 2)


class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.apps, self.settings, errs = E.parse_request({"appliances": sample_apps(), "settings": {"comfort_target": 80}})
        self.assertFalse(errs)

    def test_plan_respects_constraints(self):
        r = E.run_full(self.apps, self.settings)["optimization"]
        self.assertTrue(r["feasible"])
        self.assertGreaterEqual(r["comfort_retention"], 80 - 0.01)
        for a, p in zip(self.apps, r["plan"]):
            self.assertLessEqual(p["after_hours"], a["hours"] + 1e-9)
            self.assertGreaterEqual(p["after_hours"], a["min_hours"] - 1e-9)
        self.assertGreater(r["savings"]["monthly_cost"], 0)

    def test_cap_is_honoured(self):
        r = E.run_full(self.apps, dict(self.settings, cap_kwh_day=12))["optimization"]
        self.assertTrue(r["feasible"])
        self.assertLessEqual(r["after"]["kwh_day"], 12 + 1e-6)

    def test_impossible_cap_reports_infeasible(self):
        r = E.run_full(self.apps, dict(self.settings, cap_kwh_day=1))["optimization"]
        self.assertFalse(r["feasible"])

    def test_full_comfort_means_no_change(self):
        r = E.run_full(self.apps, dict(self.settings, comfort_target=1.0))["optimization"]
        self.assertEqual(r["moves"], [])

    def test_matches_brute_force_on_small_case(self):
        small = [dict(E.PRESET_BY_KEY[k], qty=1) for k in ("ac", "tv", "fan", "geyser")]
        for x in small:
            x["hours"] = min(x["hours"], 4)
            x["min_hours"] = min(x["min_hours"], x["hours"])
        t, tgt = E.Tariff("flat", 8), 0.75
        res = E.optimize(small, t, tgt)
        best = min(E.evaluate(small, t, list(c))["cost_month"]
                   for c in itertools.product(*[E._domain(x) for x in small])
                   if E.comfort_retention(small, list(c)) >= tgt - 1e-9)
        self.assertAlmostEqual(E.evaluate(small, t, res["hours"])["cost_month"], best, delta=3)

    def test_rules_fire(self):
        res = E.run_full(self.apps, self.settings)
        ids = {r["rule"] for r in res["analysis"]["rules"]}
        self.assertIn("R04", ids)   # incandescent bulbs are in the sample home


if __name__ == "__main__":
    unittest.main()
