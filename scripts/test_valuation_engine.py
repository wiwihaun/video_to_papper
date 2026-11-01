#!/usr/bin/env python3
"""
Hand-checkable tests for valuation_engine.py.

Every expected value below can be verified with a calculator; the comment beside each
assertion shows the arithmetic. Run:  python3 -m unittest scripts/test_valuation_engine.py -v
"""
import os
import sys
import unittest
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import valuation_engine as ve  # noqa: E402


def one_year_case(**overrides):
    case = {
        "ticker": "T", "currency": "USD", "valuation_date": "2026-11-01",
        "price": 100.0, "shares_diluted_m": 10.0, "net_debt_m": 0.0,
        "wacc": 0.10, "terminal_growth": 0.0, "midyear": False,
        "scenarios": [{"name": "Base", "probability": 1.0, "method": "dcf",
                       "fcff_m": [100.0], "terminal": {"mode": "gordon", "terminal_growth": 0.0}}],
    }
    case.update(overrides)
    return case


class TestDCF(unittest.TestCase):
    def test_gordon_exact(self):
        # PV(FCF) = 100/1.1 = 90.909; TV = 100/0.10 = 1000, PV = 909.091; EV = 1000.000
        out = ve.value_case(one_year_case())
        s = out["scenarios"][0]
        self.assertAlmostEqual(s["pv_explicit_m"], 100 / 1.1, places=9)
        self.assertAlmostEqual(s["terminal_value_m"], 1000.0, places=9)
        self.assertAlmostEqual(s["enterprise_value_m"], 1000.0, places=9)
        self.assertAlmostEqual(s["value_per_share"], 100.0, places=9)

    def test_midyear_discounts_cash_flow_but_not_tv(self):
        # PV(FCF) = 100/1.1^0.5; PV(TV) still 1000/1.1
        out = ve.value_case(one_year_case(midyear=True))
        s = out["scenarios"][0]
        self.assertAlmostEqual(s["pv_explicit_m"], 100 / 1.1 ** 0.5, places=9)
        self.assertAlmostEqual(s["pv_terminal_m"], 1000 / 1.1, places=9)

    def test_fcff_build_line_items(self):
        # rev 1000 -> 1100; EBIT 20% = 220; NOPAT @25% = 165; D&A 5% = 55;
        # capex 8% = 88; dNWC 10% x 100 = 10; SBC 1% = 11  => FCFF = 165+55-88-10-11 = 111
        rows = ve.build_fcff({
            "revenue_base_m": 1000, "revenue_growth": 0.10, "horizon_years": 1,
            "ebit_margin": 0.20, "tax_rate": 0.25, "da_pct_revenue": 0.05,
            "capex_pct_revenue": 0.08, "nwc_pct_delta_revenue": 0.10, "sbc_pct_revenue": 0.01,
        })
        r = rows[0]
        self.assertAlmostEqual(r["revenue_m"], 1100.0)
        self.assertAlmostEqual(r["nopat_m"], 165.0)
        self.assertAlmostEqual(r["delta_nwc_m"], 10.0)
        self.assertAlmostEqual(r["fcff_m"], 111.0)

    def test_units_times_price_build(self):
        # 10 units x 20 price x scale 1 = 200; 12 x 25 = 300
        rows = ve.build_fcff({"revenue_base_m": 180, "units": [10, 12], "unit_price": [20, 25],
                              "ebit_margin": 0.1})
        self.assertEqual([r["revenue_m"] for r in rows], [200.0, 300.0])

    def test_exit_multiple_uses_ebitda(self):
        # rev 1100, EBIT 220, D&A 55 -> EBITDA 275; x10 = 2750
        case = one_year_case()
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 1,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": 0.10, "ebit_margin": 0.20,
                             "tax_rate": 0.25, "da_pct_revenue": 0.05},
            "terminal": {"mode": "exit_multiple", "metric_name": "ebitda", "multiple": 10},
        }
        s = ve.value_case(case)["scenarios"][0]
        self.assertAlmostEqual(s["terminal_value_m"], 2750.0)


class TestBridgeAndGuards(unittest.TestCase):
    def test_net_cash_adds_to_equity(self):
        # EV 1000, net debt -500 (net cash) -> equity 1500 -> 150/share
        s = ve.value_case(one_year_case(net_debt_m=-500.0))["scenarios"][0]
        self.assertAlmostEqual(s["equity_value_m"], 1500.0)
        self.assertAlmostEqual(s["value_per_share"], 150.0)

    def test_g_at_or_above_wacc_is_rejected(self):
        case = one_year_case()
        case["scenarios"][0]["terminal"]["terminal_growth"] = 0.10
        with self.assertRaises(ValueError):
            ve.value_case(case)

    def test_probabilities_must_sum_to_one(self):
        case = one_year_case()
        case["scenarios"][0]["probability"] = 0.9
        with self.assertRaises(ValueError):
            ve.value_case(case)

    def test_probability_weighting(self):
        # values 100 (EV 1000) and 200 (net cash 1000 -> equity 2000), 50/50 -> 150
        case = one_year_case()
        a = deepcopy(case["scenarios"][0]); a["name"] = "A"; a["probability"] = 0.5
        b = deepcopy(a); b["name"] = "B"; b["net_debt_m"] = -1000.0
        case["scenarios"] = [a, b]
        self.assertAlmostEqual(ve.value_case(case)["probability_weighted_value_per_share"], 150.0)

    def test_sotp_applies_probability_and_stake(self):
        # 1000 x 0.5 x 1.0 + 400 x 1.0 x 0.5 = 500 + 200 = 700
        case = one_year_case()
        case["scenarios"] = [{"name": "Base", "probability": 1.0, "method": "sotp", "segments": [
            {"name": "Option", "method": "value", "value_m": 1000, "probability_of_success": 0.5},
            {"name": "Stake", "method": "value", "value_m": 400, "stake": 0.5},
        ]}]
        self.assertAlmostEqual(ve.value_case(case)["scenarios"][0]["enterprise_value_m"], 700.0)

    def test_terminal_heavy_valuation_warns(self):
        # one-year horizon: TV is 909/1000 = 91% of EV -> warning
        s = ve.value_case(one_year_case())["scenarios"][0]
        self.assertTrue(any("terminal value is" in w for w in s["warnings"]))


class TestReverse(unittest.TestCase):
    def _growth_case(self):
        case = one_year_case(midyear=True, terminal_growth=0.02)
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 5,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": 0.12, "ebit_margin": 0.20,
                             "tax_rate": 0.2, "da_pct_revenue": 0.04, "capex_pct_revenue": 0.05},
            "terminal": {"mode": "gordon", "terminal_growth": 0.02},
        }
        return case

    def test_round_trip_recovers_the_driver(self):
        # value at 12% growth, set price to that value, solve: must return 12%
        case = self._growth_case()
        case["price"] = ve.value_case(case)["scenarios"][0]["value_per_share"]
        res = ve.reverse_solve(case, "Base", "revenue_growth")
        self.assertAlmostEqual(res["implied_value"], 0.12, places=6)
        self.assertLess(abs(res["residual"]), 1e-4)

    def test_round_trip_on_margin(self):
        case = self._growth_case()
        case["price"] = ve.value_case(case)["scenarios"][0]["value_per_share"]
        res = ve.reverse_solve(case, "Base", "ebit_margin")
        self.assertAlmostEqual(res["implied_value"], 0.20, places=6)

    def test_unreachable_price_raises(self):
        case = self._growth_case()
        case["price"] = 1e12
        with self.assertRaises(ValueError):
            ve.reverse_solve(case, "Base", "ebit_margin")


class TestElasticity(unittest.TestCase):
    def _case(self):
        case = one_year_case(midyear=True, terminal_growth=0.02)
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 5,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": 0.10, "ebit_margin": 0.20,
                             "tax_rate": 0.2, "da_pct_revenue": 0.04, "capex_pct_revenue": 0.05},
            "terminal": {"mode": "gordon", "terminal_growth": 0.02},
        }
        return case

    def test_dominant_driver_ranks_first_and_shares_sum_to_one(self):
        specs = [ve.parse_driver_spec(x) for x in (
            "Margin@driver_build.ebit_margin=0.10",       # huge move: should dominate
            "Tax@driver_build.tax_rate=0.005",
            "Capex@driver_build.capex_pct_revenue=0.002",
        )]
        out = ve.elasticity(self._case(), "Base", specs)
        self.assertEqual(out["drivers"][0]["label"], "Margin")
        self.assertAlmostEqual(sum(d["variance_share"] for d in out["drivers"]), 1.0, places=9)
        self.assertIn("clean two-number", out["verdict"])

    def test_case_level_and_inherited_paths(self):
        # "wacc" is not on the scenario; it must be inherited from the case.
        out = ve.elasticity(self._case(), "Base", [ve.parse_driver_spec("WACC@wacc=0.01"),
                                                   ve.parse_driver_spec("case.wacc=0.01")])
        a, b = out["drivers"]
        self.assertAlmostEqual(a["swing"], b["swing"], places=9)
        self.assertLess(a["swing"], 0)  # higher WACC -> lower value

    def test_spec_parsing(self):
        d = ve.parse_driver_spec("Vol@driver_build.units=0.15:rel")
        self.assertEqual((d["label"], d["path"], d["sigma"], d["mode"]),
                         ("Vol", "driver_build.units", 0.15, "rel"))

    def test_fewer_than_three_drivers_gets_no_verdict(self):
        out = ve.elasticity(self._case(), "Base", [ve.parse_driver_spec("driver_build.ebit_margin=0.02")])
        self.assertIn("not yet a test", out["verdict"])


if __name__ == "__main__":
    unittest.main()
