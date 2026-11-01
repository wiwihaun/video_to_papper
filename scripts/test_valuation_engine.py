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


class TestQuoteCurrencyAndFromYear(unittest.TestCase):
    def _fade_case(self):
        case = one_year_case(midyear=True, terminal_growth=0.02)
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 5,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": [0.30, 0.20, 0.12, 0.12, 0.12],
                             "ebit_margin": 0.30, "tax_rate": 0.2, "da_pct_revenue": 0.05,
                             "capex_pct_revenue": 0.08},
            "terminal": {"mode": "gordon", "terminal_growth": 0.02},
        }
        return case

    def test_from_year_solve_keeps_early_years(self):
        # price set at the model value; solving years 3-5 must return 12% and keep 30%/20%
        case = self._fade_case()
        case["price"] = ve.value_case(case)["scenarios"][0]["value_per_share"]
        res = ve.reverse_solve(case, "Base", "revenue_growth", from_year=3)
        self.assertAlmostEqual(res["implied_value"], 0.12, places=6)
        s, _ = ve._apply_driver(case["scenarios"][0], case, "revenue_growth", 0.05, from_year=3)
        self.assertEqual(s["driver_build"]["revenue_growth"], [0.30, 0.20, 0.05, 0.05, 0.05])

    def test_from_year_out_of_range(self):
        case = self._fade_case()
        with self.assertRaises(ValueError):
            ve._apply_driver(case["scenarios"][0], case, "revenue_growth", 0.1, from_year=1)

    def test_quote_currency_conversion(self):
        # model in USD: EV 1000, 10 shares -> US$100/share; fx 32 -> NT$3,200/share
        # price_quote NT$2,400 -> US$75 -> upside +33.3%
        case = one_year_case()
        del case["price"]
        case.update({"quote_currency": "TWD", "fx_quote_per_model": 32.0, "price_quote": 2400.0, "adr_ratio": 5})
        out = ve.value_case(case)
        self.assertAlmostEqual(out["price"], 75.0)
        self.assertAlmostEqual(out["probability_weighted_value_per_share_quote"], 3200.0)
        self.assertAlmostEqual(out["probability_weighted_upside_pct"], (100 / 75 - 1) * 100)
        self.assertAlmostEqual(out["probability_weighted_value_per_adr"], 500.0)

    def test_reverse_uses_quote_price(self):
        case = one_year_case()
        del case["price"]
        case.update({"fx_quote_per_model": 32.0, "price_quote": 3200.0})  # = US$100 = model value
        case["scenarios"][0] = self._fade_case()["scenarios"][0]
        v = ve.value_case(case)["scenarios"][0]["value_per_share"]
        case["price_quote"] = v * 32.0
        res = ve.reverse_solve(case, "Base", "ebit_margin")
        self.assertAlmostEqual(res["implied_value"], 0.30, places=6)

    def test_implied_terminal_multiple(self):
        # rev 1100, EBIT 220, D&A 55 -> EBITDA 275; FCFF = 176 + 55 = 231 (no capex/NWC)
        # Gordon g=0, WACC 10%: TV = 231/0.10 = 2310 -> 2310/275 = 8.4x EV/EBITDA
        case = one_year_case()
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 1,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": 0.10, "ebit_margin": 0.20,
                             "tax_rate": 0.20, "da_pct_revenue": 0.05},
            "terminal": {"mode": "gordon", "terminal_growth": 0.0},
        }
        s = ve.value_case(case)["scenarios"][0]
        self.assertAlmostEqual(s["terminal_value_m"], 2310.0)
        self.assertAlmostEqual(s["implied_terminal_multiples"]["ev_ebitda"], 8.4)

    def test_equal_weighted_value(self):
        case = one_year_case()
        a = deepcopy(case["scenarios"][0]); a["name"] = "A"; a["probability"] = 0.8
        b = deepcopy(a); b["name"] = "B"; b["probability"] = 0.2; b["net_debt_m"] = -1000.0
        case["scenarios"] = [a, b]
        out = ve.value_case(case)
        self.assertAlmostEqual(out["equal_weighted_value_per_share"], 150.0)          # (100+200)/2
        self.assertAlmostEqual(out["probability_weighted_value_per_share"], 120.0)    # 0.8*100+0.2*200


class TestHazardOverlay(unittest.TestCase):
    def _case(self, midyear=False):
        case = one_year_case(midyear=midyear, terminal_growth=0.02)
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 5,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": 0.10, "ebit_margin": 0.25,
                             "tax_rate": 0.2, "da_pct_revenue": 0.05, "capex_pct_revenue": 0.07},
            "terminal": {"mode": "gordon", "terminal_growth": 0.02},
        }
        return case

    def test_zero_hazard_is_identity(self):
        a = ve.value_case(self._case())["scenarios"][0]["enterprise_value_m"]
        c = self._case(); c["hazard"] = {"annual_probability": 0.0, "loss_fraction": 0.8}
        self.assertAlmostEqual(ve.value_case(c)["scenarios"][0]["enterprise_value_m"], a, places=9)

    def test_total_loss_hazard_equals_higher_discount_rate(self):
        # L = 1: E[CF_t] = CF_t (1-h)^t  <=>  discounting at (1+r)/(1-h) - 1. Exact, incl. terminal.
        h = 0.02
        c = self._case(); c["hazard"] = {"annual_probability": h, "loss_fraction": 1.0}
        with_hazard = ve.value_case(c)["scenarios"][0]["enterprise_value_m"]
        d = self._case(); d["wacc"] = (1 + 0.10) / (1 - h) - 1
        self.assertAlmostEqual(with_hazard, ve.value_case(d)["scenarios"][0]["enterprise_value_m"], places=6)

    def test_partial_loss_lies_between(self):
        base = ve.value_case(self._case())["scenarios"][0]["enterprise_value_m"]
        c = self._case(); c["hazard"] = {"annual_probability": 0.02, "loss_fraction": 0.5}
        half = ve.value_case(c)["scenarios"][0]["enterprise_value_m"]
        c["hazard"]["loss_fraction"] = 1.0
        full = ve.value_case(c)["scenarios"][0]["enterprise_value_m"]
        self.assertTrue(full < half < base)

    def test_reverse_solve_recovers_hazard(self):
        c = self._case(midyear=True); c["hazard"] = {"annual_probability": 0.015, "loss_fraction": 0.8}
        c["price"] = ve.value_case(c)["scenarios"][0]["value_per_share"]
        c["hazard"]["annual_probability"] = 0.0
        res = ve.reverse_solve(c, "Base", "hazard_rate")
        self.assertAlmostEqual(res["implied_value"], 0.015, places=6)


class TestPathSlices(unittest.TestCase):
    def test_slice_bumps_only_part_of_a_path(self):
        case = one_year_case(midyear=True, terminal_growth=0.02)
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 4,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": [0.3, 0.2, 0.1, 0.1],
                             "ebit_margin": 0.3, "tax_rate": 0.2},
            "terminal": {"mode": "gordon", "terminal_growth": 0.02},
        }
        s = deepcopy(case["scenarios"][0])
        ve._set_path(s, ["driver_build", "revenue_growth[2:]"],
                     ve._bump(ve._get_path(s, ["driver_build", "revenue_growth[2:]"]), 0.05, "abs"))
        self.assertEqual([round(x, 10) for x in s["driver_build"]["revenue_growth"]], [0.3, 0.2, 0.15, 0.15])
        out = ve.elasticity(case, "Base", [
            ve.parse_driver_spec("Near@driver_build.revenue_growth[0:2]=0.05"),
            ve.parse_driver_spec("Late@driver_build.revenue_growth[2:]=0.05"),
            ve.parse_driver_spec("Margin@driver_build.ebit_margin=0.03"),
        ])
        self.assertEqual(len(out["drivers"]), 3)

    def test_slice_errors(self):
        with self.assertRaises(ValueError):
            ve._get_path({"a": [1, 2]}, ["a[5:]"])
        with self.assertRaises(ValueError):
            ve._get_path({"a": [1, 2]}, ["a[1]"])


class TestRollForward(unittest.TestCase):
    def test_twelve_month_target(self):
        # fair value US$100 x 32 = NT$3,200; x (1 + 6%) - NT$20 dividend = NT$3,372
        # spot NT$3,000 -> target upside +12.4%, total return (3,372 + 20)/3,000 - 1 = +13.07%
        case = one_year_case()
        del case["price"]
        case.update({"fx_quote_per_model": 32.0, "price_quote": 3000.0, "quote_currency": "TWD",
                     "roll_forward": {"cost_of_equity_quote": 0.06, "dividends_quote_next_12m": 20.0}})
        out = ve.value_case(case)
        self.assertAlmostEqual(out["target_price_12m_quote"], 3372.0)
        self.assertAlmostEqual(out["target_upside_pct"], 12.4)
        self.assertAlmostEqual(out["expected_total_return_12m_pct"], (3392 / 3000 - 1) * 100)


class TestResidualIncome(unittest.TestCase):
    def _case(self, roe, payout=0.5, g=0.02, coe=0.10, n=5):
        return {"ticker": "BANK", "currency": "TWD", "price": 30.0, "shares_diluted_m": 100.0,
                "wacc": coe, "terminal_growth": g, "midyear": False,
                "scenarios": [{"name": "Base", "probability": 1.0, "method": "residual_income",
                               "book_value_m": 2000.0, "roe": roe, "payout_ratio": payout,
                               "horizon_years": n}]}

    def test_roe_equal_to_coe_gives_book_value(self):
        # no excess return -> value = book (P/B = 1): 2000 / 100 sh = 20/share
        s = ve.value_case(self._case(0.10))["scenarios"][0]
        self.assertAlmostEqual(s["value_per_share"], 20.0, places=9)
        self.assertAlmostEqual(s["implied_price_to_book"], 1.0, places=9)

    def test_matches_justified_pb_for_constant_roe(self):
        # constant ROE with payout chosen so book grows at g: P/B = (ROE - g)/(COE - g)
        roe, g, coe = 0.15, 0.03, 0.10
        payout = 1 - g / roe       # retention x ROE = g
        s = ve.value_case(self._case(roe, payout=payout, g=g, coe=coe, n=8))["scenarios"][0]
        self.assertAlmostEqual(s["implied_price_to_book"], (roe - g) / (coe - g), places=9)

    def test_net_debt_is_ignored(self):
        c = self._case(0.12); c["net_debt_m"] = 999999.0
        a = ve.value_case(c)["scenarios"][0]["value_per_share"]
        self.assertAlmostEqual(a, ve.value_case(self._case(0.12))["scenarios"][0]["value_per_share"])

    def test_elasticity_and_hazard_work_on_ri(self):
        c = self._case([0.12] * 5)
        out = ve.elasticity(c, "Base", [ve.parse_driver_spec("ROE@roe=0.02"),
                                        ve.parse_driver_spec("Payout@payout_ratio=0.1"),
                                        ve.parse_driver_spec("COE@wacc=0.01")])
        self.assertEqual(out["drivers"][0]["label"] in ("ROE", "COE"), True)
        c["hazard"] = {"annual_probability": 0.02, "loss_fraction": 1.0}
        self.assertLess(ve.value_case(c)["scenarios"][0]["value_per_share"],
                        ve.value_case(self._case([0.12] * 5))["scenarios"][0]["value_per_share"])


class TestRollForwardModelBasis(unittest.TestCase):
    def test_model_basis_uses_wacc_at_spot(self):
        # FV US$100 x 32 = NT$3,200; basis=model -> x (1 + 10% WACC) - 20 = NT$3,500
        case = one_year_case()
        del case["price"]
        case.update({"fx_quote_per_model": 32.0, "price_quote": 3000.0, "quote_currency": "TWD",
                     "roll_forward": {"basis": "model", "dividends_quote_next_12m": 20.0}})
        self.assertAlmostEqual(ve.value_case(case)["target_price_12m_quote"], 3500.0)


class TestV2Features(unittest.TestCase):
    def _case(self):
        case = one_year_case(midyear=True, terminal_growth=0.02)
        case["scenarios"][0] = {
            "name": "Base", "probability": 1.0, "method": "dcf", "horizon_years": 4,
            "driver_build": {"revenue_base_m": 1000, "revenue_growth": 0.1, "ebit_margin": 0.3,
                             "tax_rate": 0.2, "da_pct_revenue": [0.10, 0.12, 0.14, 0.16],
                             "capex_pct_revenue": 0.15},
            "terminal": {"mode": "gordon", "terminal_growth": 0.02}}
        return case

    def test_ebitda_driver_sets_ebit_net_of_da(self):
        s, _ = ve._apply_driver(self._case()["scenarios"][0], self._case(), "ebitda_margin", 0.50)
        self.assertEqual([round(x, 10) for x in s["driver_build"]["ebit_margin"]], [0.40, 0.38, 0.36, 0.34])

    def test_hazard_years_zero_equals_no_hazard(self):
        a = ve.value_case(self._case())["scenarios"][0]["enterprise_value_m"]
        c = self._case(); c["hazard"] = {"annual_probability": 0.05, "loss_fraction": 0.8, "years": 0}
        self.assertAlmostEqual(ve.value_case(c)["scenarios"][0]["enterprise_value_m"], a, places=6)

    def test_hazard_years_between_none_and_perpetual(self):
        c = self._case(); c["hazard"] = {"annual_probability": 0.03, "loss_fraction": 0.8}
        perpetual = ve.value_case(c)["scenarios"][0]["enterprise_value_m"]
        c["hazard"]["years"] = 4
        limited = ve.value_case(c)["scenarios"][0]["enterprise_value_m"]
        none = ve.value_case(self._case())["scenarios"][0]["enterprise_value_m"]
        self.assertTrue(perpetual < limited < none)

    def test_rating_and_triggers(self):
        case = one_year_case()
        del case["price"]
        case.update({"fx_quote_per_model": 32.0, "price_quote": 4000.0, "quote_currency": "TWD",
                     "roll_forward": {"basis": "model", "dividends_quote_next_12m": 20.0},
                     "rating_thresholds": {"buy": 0.15, "sell": -0.15}})
        out = ve.value_case(case)          # TP = 3200 x 1.1 - 20 = 3500 -> -12.5% -> Hold
        self.assertEqual(out["rating"], "Hold")
        self.assertAlmostEqual(out["price_triggers_quote"]["sell_above"], 3500 / 0.85)
        self.assertAlmostEqual(out["price_triggers_quote"]["buy_below"], 3500 / 1.15)


class TestResidualIncomeHazard(unittest.TestCase):
    def _case(self, roe=0.13, payout=0.65, coe=0.07, g=0.025):
        return {"ticker": "BANK", "currency": "TWD", "price": 30.0, "shares_diluted_m": 100.0,
                "wacc": coe, "terminal_growth": g,
                "scenarios": [{"name": "Base", "probability": 1.0, "method": "residual_income",
                               "book_value_m": 2000.0, "roe": [0.15, 0.14, 0.13, roe, roe],
                               "payout_ratio": payout, "horizon_years": 5}]}

    def test_tiny_hazard_converges_to_residual_income(self):
        # DDM-with-hazard and RI must agree as h -> 0 (clean-surplus identity)
        base = ve.value_case(self._case())["scenarios"][0]["value_per_share"]
        c = self._case(); c["hazard"] = {"annual_probability": 1e-9, "loss_fraction": 0.9}
        self.assertAlmostEqual(ve.value_case(c)["scenarios"][0]["value_per_share"], base, places=5)

    def test_total_loss_equals_higher_cost_of_equity(self):
        h = 0.02
        c = self._case(); c["hazard"] = {"annual_probability": h, "loss_fraction": 1.0}
        with_h = ve.value_case(c)["scenarios"][0]["value_per_share"]
        d = self._case(coe=(1.07) / (1 - h) - 1)
        self.assertAlmostEqual(with_h, ve.value_case(d)["scenarios"][0]["value_per_share"], places=6)

    def test_hazard_hits_book_value_too(self):
        # with ROE == COE the no-hazard value equals book; a hazard must take value BELOW book
        c = self._case(roe=0.07); c["scenarios"][0]["roe"] = 0.07
        c["hazard"] = {"annual_probability": 0.02, "loss_fraction": 0.9}
        self.assertLess(ve.value_case(c)["scenarios"][0]["value_per_share"], 20.0)


class TestDuPont(unittest.TestCase):
    def test_roa_times_leverage_equals_roe(self):
        a = {"ticker": "B", "currency": "TWD", "price": 30.0, "shares_diluted_m": 100.0, "wacc": 0.07,
             "terminal_growth": 0.025, "scenarios": [{"name": "Base", "probability": 1.0,
             "method": "residual_income", "book_value_m": 2000.0, "roe": 0.12, "payout_ratio": 0.6, "horizon_years": 5}]}
        b = deepcopy(a)
        del b["scenarios"][0]["roe"]
        b["scenarios"][0].update({"roa": 0.0075, "leverage": 16.0})
        self.assertAlmostEqual(ve.value_case(a)["scenarios"][0]["value_per_share"],
                               ve.value_case(b)["scenarios"][0]["value_per_share"], places=9)


if __name__ == "__main__":
    unittest.main()
