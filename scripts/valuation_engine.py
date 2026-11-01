#!/usr/bin/env python3
"""
valuation_engine.py — deterministic valuation math for the `stock-valuation` skill.

Stdlib only. No network. Every number it emits is reproducible from the input JSON,
which is the point: the LLM supplies judgement (the drivers), this file supplies
arithmetic that a sell-side associate can tie out line by line.

Engines
  dcf       FCFF build from drivers (revenue -> EBIT -> NOPAT -> FCFF), Gordon or
            exit-multiple terminal value, mid-year convention optional.
  sotp      Sum-of-the-parts: per-pool DCF / multiple / explicit value, each with an
            optional probability-of-success haircut (for option-value pools).
  multiple  Straight target-multiple valuation.

Commands
  value        Value every scenario, emit probability-weighted target price.
  reverse      Solve for the driver value that the CURRENT PRICE implies (reverse DCF).
  sensitivity  2-D grid over any two drivers.
  elasticity   Rank candidate drivers by how much a 1-sigma move shifts value (Phase 2).

Usage
  python3 valuation_engine.py value       --input case.json [--markdown]
  python3 valuation_engine.py reverse     --input case.json --scenario Base --solve-for revenue_growth
  python3 valuation_engine.py sensitivity --input case.json --scenario Base \
          --x wacc --x-values 0.08,0.09,0.10 --y terminal_growth --y-values 0.02,0.03
  python3 valuation_engine.py elasticity  --input case.json --scenario Base \
          --driver "Revenue growth@driver_build.revenue_growth=0.04" \
          --driver "EBIT margin@driver_build.ebit_margin=0.02" --markdown

See references/02-valuation-engines.md for the input schema and worked examples.
"""

import argparse
import json
import sys
from copy import deepcopy

# --------------------------------------------------------------------------- #
# driver -> FCFF build
# --------------------------------------------------------------------------- #

SOLVABLE = (
    "revenue_growth",
    "ebit_margin",
    "terminal_growth",
    "wacc",
    "fcff_scale",
    "exit_multiple",
    "hazard_rate",
    "ebitda_margin",
    "roe",
    "payout_ratio",
    "capex_intensity",
)


def _as_path(value, years, label):
    """Scalar -> flat path; list -> validated path."""
    if value is None:
        raise ValueError("missing driver: %s" % label)
    if isinstance(value, list):
        if len(value) < years:
            raise ValueError(
                "driver %s has %d entries but the forecast is %d years"
                % (label, len(value), years)
            )
        return [float(v) for v in value[:years]]
    return [float(value)] * years


def build_fcff(build, horizon=None):
    """
    Turn a driver dict into an explicit FCFF schedule.

    Required: revenue_base_m, ebit_margin, and either revenue_m or revenue_growth
              (+ horizon_years when using revenue_growth as a scalar).
    Optional: tax_rate, da_pct_revenue, capex_pct_revenue, nwc_pct_delta_revenue,
              sbc_pct_revenue.

    SBC is expensed as a real economic cost, not added back. That is deliberate:
    adding it back flatters any equity-comp-heavy issuer and is the single most
    common way a DCF is quietly inflated.
    """
    rev_base = float(build["revenue_base_m"])

    if "revenue_m" in build:
        revenue = [float(r) for r in build["revenue_m"]]
        if horizon:
            revenue = revenue[:horizon]
    elif "units" in build:
        # Volume x price build: the natural home for an operating KPI
        # (wafers x ASP, fleet x revenue per vehicle, subscribers x ARPU).
        units, price = build["units"], build.get("unit_price")
        years = horizon or build.get("horizon_years") or next(
            (len(v) for v in (units, price) if isinstance(v, list)), None
        )
        if not years:
            raise ValueError("units build needs horizon_years or a list-valued units/unit_price")
        years = int(years)
        scale = float(build.get("unit_scale", 1.0))
        u_path = _as_path(units, years, "units")
        p_path = _as_path(price, years, "unit_price")
        revenue = [u * pr * scale for u, pr in zip(u_path, p_path)]
    else:
        years = horizon or build.get("horizon_years")
        if not years:
            raise ValueError("need horizon_years (or an explicit revenue_m path)")
        years = int(years)
        growth = _as_path(build.get("revenue_growth"), years, "revenue_growth")
        revenue, r = [], rev_base
        for g in growth:
            r = r * (1.0 + g)
            revenue.append(r)

    years = len(revenue)
    if years == 0:
        raise ValueError("empty revenue path")

    ebit_margin = _as_path(build.get("ebit_margin"), years, "ebit_margin")
    tax_rate = _as_path(build.get("tax_rate", 0.21), years, "tax_rate")
    da_pct = _as_path(build.get("da_pct_revenue", 0.0), years, "da_pct_revenue")
    capex_pct = _as_path(build.get("capex_pct_revenue", 0.0), years, "capex_pct_revenue")
    nwc_pct = _as_path(build.get("nwc_pct_delta_revenue", 0.0), years, "nwc_pct_delta_revenue")
    sbc_pct = _as_path(build.get("sbc_pct_revenue", 0.0), years, "sbc_pct_revenue")

    rows, prev_rev = [], rev_base
    for i in range(years):
        rev = revenue[i]
        ebit = rev * ebit_margin[i]
        nopat = ebit * (1.0 - tax_rate[i])
        da = rev * da_pct[i]
        capex = rev * capex_pct[i]
        d_nwc = (rev - prev_rev) * nwc_pct[i]
        sbc = rev * sbc_pct[i]
        fcff = nopat + da - capex - d_nwc - sbc
        rows.append(
            {
                "year": i + 1,
                "revenue_m": rev,
                "revenue_growth": (rev / prev_rev - 1.0) if prev_rev else None,
                "ebit_m": ebit,
                "ebit_margin": ebit_margin[i],
                "nopat_m": nopat,
                "da_m": da,
                "capex_m": capex,
                "delta_nwc_m": d_nwc,
                "sbc_m": sbc,
                "fcff_m": fcff,
            }
        )
        prev_rev = rev
    return rows


# --------------------------------------------------------------------------- #
# terminal value
# --------------------------------------------------------------------------- #

def terminal_value(rows, terminal, wacc):
    """Gordon growth or exit multiple. Returns (tv, detail)."""
    mode = terminal.get("mode", "gordon")
    last = rows[-1]

    if mode == "gordon":
        g = float(terminal["terminal_growth"])
        if g >= wacc:
            raise ValueError(
                "terminal growth (%.4f) >= WACC (%.4f): Gordon formula is undefined. "
                "Lower g, raise WACC, or switch to an exit multiple." % (g, wacc)
            )
        base = float(terminal.get("terminal_fcff_m", last["fcff_m"]))
        tv = base * (1.0 + g) / (wacc - g)
        return tv, {"mode": "gordon", "terminal_growth": g, "base_fcff_m": base}

    if mode == "exit_multiple":
        mult = float(terminal["multiple"])
        if "metric_m" in terminal:
            metric = float(terminal["metric_m"])
            name = terminal.get("metric_name", "custom")
        else:
            name = terminal.get("metric_name", "ebitda")
            metrics = {   # lazy: an explicit-FCFF scenario has no EBIT or revenue lines
                "ebitda": lambda: last["ebit_m"] + last["da_m"],
                "ebit": lambda: last["ebit_m"],
                "fcff": lambda: last["fcff_m"],
                "revenue": lambda: last["revenue_m"],
                "nopat": lambda: last["nopat_m"],
            }
            if name not in metrics:
                raise ValueError("unknown terminal metric_name: %s" % name)
            metric = metrics[name]()
            if metric is None:
                raise ValueError("terminal metric %s is not available for this scenario" % name)
        return mult * metric, {
            "mode": "exit_multiple",
            "metric_name": name,
            "metric_m": metric,
            "multiple": mult,
        }

    raise ValueError("unknown terminal mode: %s" % mode)


# --------------------------------------------------------------------------- #
# DCF
# --------------------------------------------------------------------------- #

def discount_factors(years, wacc, midyear):
    """Explicit cash-flow discount factors (mid-year: flow t arrives at t - 0.5).

    The terminal value is timed in dcf(): a Gordon value sits one period before its first
    flow, so under the mid-year convention it is discounted from N - 0.5 (first terminal flow
    at N + 0.5, half a year after the year-N flow). An exit-multiple value is a sale at the end
    of year N and is discounted from N either way."""
    out = []
    for t in range(1, years + 1):
        exp = t - 0.5 if midyear else t
        out.append(1.0 / (1.0 + wacc) ** exp)
    return out


def _hazard(scenario, case):
    """
    Discrete-event (jump) risk overlay, e.g. a geopolitical disruption.

    {"annual_probability": h, "loss_fraction": L}: each year the event occurs with
    probability h; once it occurs, operating cash flows from then on are cut by L
    permanently. Expected multiplier on a cash flow at time t is
        (1 - L) + L * (1 - h)^t.
    Applied to operating value (EV) only — net cash is assumed recoverable. With L = 1 the
    overlay is exactly equivalent to discounting at (1 + WACC) / (1 - h) - 1, which is why
    a country-risk premium in the discount rate is itself an implicit hazard rate.
    """
    hz = scenario.get("hazard", case.get("hazard")) or {}
    h = float(hz.get("annual_probability", 0.0))
    L = float(hz.get("loss_fraction", 1.0))
    # optional "years": hazard applies only through that year; no new events afterwards
    if not 0.0 <= h < 1.0:
        raise ValueError("hazard annual_probability must be in [0, 1)")
    if not 0.0 <= L <= 1.0:
        raise ValueError("hazard loss_fraction must be in [0, 1]")
    return h, L


def dcf(scenario, case):
    wacc = float(scenario.get("wacc", case["wacc"]))
    midyear = bool(scenario.get("midyear", case.get("midyear", True)))

    if "fcff_m" in scenario:
        rows = [
            {
                "year": i + 1,
                "fcff_m": float(f),
                "revenue_m": None,
                "ebit_m": None,
                "da_m": 0.0,
                "nopat_m": None,
                "capex_m": None,
                "delta_nwc_m": None,
                "sbc_m": None,
                "ebit_margin": None,
                "revenue_growth": None,
            }
            for i, f in enumerate(scenario["fcff_m"])
        ]
    else:
        rows = build_fcff(scenario["driver_build"], scenario.get("horizon_years"))

    fcff_scale = float(scenario.get("fcff_scale", 1.0))
    if fcff_scale != 1.0:
        for r in rows:
            r["fcff_m"] *= fcff_scale

    n = len(rows)
    dfs = discount_factors(n, wacc, midyear)
    h, L = _hazard(scenario, case)
    hz_years = (scenario.get("hazard", case.get("hazard")) or {}).get("years")
    pv_explicit = 0.0
    pv_explicit_no_hazard = 0.0
    for t, (r, df) in enumerate(zip(rows, dfs), 1):
        exp = t - 0.5 if midyear else t
        if hz_years is not None:
            exp = min(exp, float(hz_years))
        mult = (1.0 - L) + L * (1.0 - h) ** exp
        r["discount_factor"] = df
        r["survival_multiplier"] = mult
        r["pv_fcff_m"] = r["fcff_m"] * df * mult
        pv_explicit += r["pv_fcff_m"]
        pv_explicit_no_hazard += r["fcff_m"] * df

    terminal = dict(scenario.get("terminal", {"mode": "gordon"}))
    if terminal.get("mode", "gordon") == "gordon" and "terminal_growth" not in terminal:
        terminal["terminal_growth"] = case.get("terminal_growth")
    if "multiple" in scenario and terminal.get("mode") == "exit_multiple":
        terminal["multiple"] = scenario["multiple"]

    tv, tv_detail = terminal_value(rows, terminal, wacc)
    # Gordon value = value one period before its first flow. Mid-year flows put that flow at
    # N + 0.5, so the value sits at N - 0.5; an exit multiple is a sale at the end of year N.
    tv_time = n - 0.5 if (midyear and tv_detail["mode"] == "gordon") else float(n)
    tv_df = 1.0 / (1.0 + wacc) ** tv_time
    pv_tv_no_hazard = tv * tv_df
    tv_detail["discounted_from_year"] = tv_time
    if h == 0.0:
        pv_tv = pv_tv_no_hazard
    elif hz_years is not None:
        # events possible only through hz_years: terminal flows carry survival to that date
        # (exact while hz_years <= the first terminal flow, tv_time + 1)
        pv_tv = pv_tv_no_hazard * ((1.0 - L) + L * (1.0 - h) ** min(float(hz_years), tv_time + 1.0))
    elif tv_detail["mode"] == "gordon":
        # Closed form, flows at tau_k = tv_time + k (k >= 1):
        #   sum CF_N (1+g)^k [(1-L) + L(1-h)^tau_k] / (1+r)^tau_k
        g, cf = tv_detail["terminal_growth"], tv_detail["base_fcff_m"]
        q_den = (1.0 + wacc) - (1.0 + g) * (1.0 - h)
        pv_tv = tv_df * cf * (1.0 + g) * (
            (1.0 - L) / (wacc - g) + L * (1.0 - h) ** tv_time * (1.0 - h) / q_den
        )
    else:
        pv_tv = pv_tv_no_hazard * ((1.0 - L) + L * (1.0 - h) ** n)

    ev = pv_explicit + pv_tv
    ev_no_hazard = pv_explicit_no_hazard + pv_tv_no_hazard
    warnings = []
    tv_share = (pv_tv / ev) if ev else None
    if tv_share is not None and tv_share > 0.75:
        warnings.append(
            "terminal value is %.0f%% of EV (>75%%): the explicit forecast is not carrying the "
            "valuation. Extend the horizon or cross-check with an exit multiple." % (tv_share * 100)
        )
    if tv_detail.get("mode") == "gordon" and tv_detail["terminal_growth"] > 0.035:
        warnings.append(
            "terminal growth %.2f%% exceeds 3.5%%: above long-run nominal GDP for most markets; "
            "needs an explicit argument." % (tv_detail["terminal_growth"] * 100)
        )
    if rows[-1]["fcff_m"] < 0 and tv_detail.get("mode") == "gordon":
        warnings.append("final-year FCFF is negative, so the Gordon terminal value is negative.")
    last = rows[-1]
    implied = {}
    # Implied multiples are stated at the end of year N, the date an exit multiple refers to
    # (a mid-year Gordon value sits at N - 0.5, so roll it forward half a year).
    tv_at_n = tv * (1.0 + wacc) ** (n - tv_time)
    after = None
    if h > 0.0 and hz_years is None and tv_detail["mode"] == "gordon":
        # same value conditional on no event by year N, i.e. what a buyer in year N would pay
        g = tv_detail["terminal_growth"]
        s_off = tv_time - n
        q_den = (1.0 + wacc) - (1.0 + g) * (1.0 - h)
        after = tv_at_n * (wacc - g) * ((1.0 - L) / (wacc - g) + L * (1.0 - h) ** (s_off + 1.0) / q_den)
    if last.get("ebit_m") is not None:
        ebitda = last["ebit_m"] + (last.get("da_m") or 0.0)
        if ebitda > 0:
            implied["ev_ebitda"] = tv_at_n / ebitda
            if after is not None:
                implied["ev_ebitda_after_event_risk"] = after / ebitda
        if last["ebit_m"] > 0:
            implied["ev_ebit"] = tv_at_n / last["ebit_m"]
    if last["fcff_m"] > 0:
        implied["ev_fcff"] = tv_at_n / last["fcff_m"]
    hazard_info = None
    if h > 0.0:
        hazard_info = {
            "annual_probability": h,
            "loss_fraction": L,
            "cumulative_probability_10y": 1.0 - (1.0 - h) ** 10,
            "enterprise_value_no_hazard_m": ev_no_hazard,
            "ev_haircut_pct": (1.0 - ev / ev_no_hazard) * 100.0 if ev_no_hazard else None,
        }
    return {
        "hazard": hazard_info,
        "implied_terminal_multiples": implied,
        "warnings": warnings,
        "method": "dcf",
        "wacc": wacc,
        "midyear": midyear,
        "horizon_years": n,
        "rows": rows,
        "pv_explicit_m": pv_explicit,
        "terminal": tv_detail,
        "terminal_value_m": tv,
        "pv_terminal_m": pv_tv,
        "terminal_pct_of_ev": (pv_tv / ev) if ev else None,
        "enterprise_value_m": ev,
    }


# --------------------------------------------------------------------------- #
# SOTP / multiple
# --------------------------------------------------------------------------- #

def sotp(scenario, case):
    pools = []
    total = 0.0
    sub_warnings = []
    for pool in scenario["segments"]:
        name = pool.get("name", "pool")
        method = pool.get("method", "value")
        if method == "value":
            gross = float(pool["value_m"])
            basis = "explicit"
        elif method == "multiple":
            gross = float(pool["metric_m"]) * float(pool["multiple"])
            basis = "%s x %.2f" % (pool.get("metric_name", "metric"), float(pool["multiple"]))
        elif method == "dcf":
            sub = dcf(pool, case)
            gross = sub["enterprise_value_m"]
            basis = "dcf @ %.2f%% WACC" % (sub["wacc"] * 100)
            sub_warnings.extend("[%s] %s" % (name, w) for w in sub["warnings"])
        else:
            raise ValueError("unknown segment method: %s" % method)

        pos = float(pool.get("probability_of_success", 1.0))
        stake = float(pool.get("stake", 1.0))
        net = gross * pos * stake
        total += net
        pools.append(
            {
                "name": name,
                "basis": basis,
                "gross_value_m": gross,
                "probability_of_success": pos,
                "stake": stake,
                "attributable_value_m": net,
            }
        )
    for p in pools:
        p["pct_of_ev"] = (p["attributable_value_m"] / total) if total else None
    option_share = sum(p["pct_of_ev"] or 0 for p in pools if p["probability_of_success"] < 1.0)
    if option_share > 0.40:
        sub_warnings.append(
            "probability-weighted option pools are %.0f%% of EV (>40%%): the target price rests on "
            "events that have not happened. State this on page one." % (option_share * 100)
        )
    return {"method": "sotp", "segments": pools, "enterprise_value_m": total, "warnings": sub_warnings}


def residual_income(scenario, case):
    """
    Residual-income (excess-return) model for banks, insurers and other balance-sheet
    businesses, where FCFF is meaningless because debt is raw material, not financing.

        BV_t   = BV_{t-1} + NI_t - dividends_t,  NI_t = ROE_t x BV_{t-1}, dividends = payout x NI
        RI_t   = (ROE_t - COE) x BV_{t-1}
        Value  = BV_0 + sum RI_t / (1+COE)^t + RI_{N+1} / (COE - g) / (1+COE)^N

    Inputs (scenario or case): book_value_m (equity attributable to shareholders at the
    valuation date), roe (scalar or path), payout_ratio (scalar or path), cost_of_equity
    (falls back to wacc), terminal_growth, horizon_years. The terminal ROE is the last path
    value; a terminal RI is perpetual — set the last ROE to what the franchise can sustain.
    Result is EQUITY value (no EV bridge): net_debt is ignored by construction.
    The hazard overlay applies to the residual-income stream (book value is assumed safe).
    """
    coe = float(scenario.get("cost_of_equity", case.get("cost_of_equity", case.get("wacc"))))
    g = float(scenario.get("terminal_growth", case.get("terminal_growth")))
    if g >= coe:
        raise ValueError("terminal growth (%.4f) >= cost of equity (%.4f)" % (g, coe))
    bv0 = float(scenario.get("book_value_m", case.get("book_value_m")))
    n = int(scenario.get("horizon_years", case.get("horizon_years", 10)))
    if scenario.get("roe", case.get("roe")) is None and scenario.get("roa") is not None:
        # DuPont: ROE = ROA x leverage (assets / equity) — both disclosed quarterly by banks
        roa = _as_path(scenario.get("roa"), n, "roa")
        lev = _as_path(scenario.get("leverage"), n, "leverage")
        roe = [a * b for a, b in zip(roa, lev)]
    else:
        roe = _as_path(scenario.get("roe", case.get("roe")), n, "roe")
    payout = _as_path(scenario.get("payout_ratio", case.get("payout_ratio", 0.5)), n, "payout_ratio")
    h, L = _hazard(scenario, case)

    rows, bv, pv, pv_div = [], bv0, 0.0, 0.0
    hz_years = (scenario.get("hazard", case.get("hazard")) or {}).get("years")
    for t in range(1, n + 1):
        ni = roe[t - 1] * bv
        ri = (roe[t - 1] - coe) * bv
        df = 1.0 / (1.0 + coe) ** t
        div = payout[t - 1] * ni
        exp = min(t, float(hz_years)) if hz_years is not None else t
        mult = (1.0 - L) + L * (1.0 - h) ** exp
        pv += ri * df
        pv_div += div * df * mult
        rows.append({"year": t, "book_value_open_m": bv, "roe": roe[t - 1], "net_income_m": ni,
                     "residual_income_m": ri, "dividends_m": div, "survival_multiplier": mult,
                     "pv_dividend_m": div * df * mult})
        bv = bv + ni - div
    ri_next = (roe[-1] - coe) * bv
    tv_df = 1.0 / (1.0 + coe) ** n
    pv_tv_ri = ri_next / (coe - g) * tv_df
    equity_no_hazard = bv0 + pv + pv_tv_ri            # residual-income value

    # Event risk hits the WHOLE equity of a bank (its book is loans to the same economy), so
    # with a hazard the value is computed in dividend-discount form — identical to residual
    # income when h = 0 (clean surplus) — with the survival multiplier on every dividend.
    if h == 0.0:
        equity = equity_no_hazard
        pv_tv = pv_tv_ri
    else:
        d_next = (roe[-1] - g) * bv                   # steady state: book grows at g after year N
        if hz_years is not None:
            pv_tv = d_next / (coe - g) * tv_df * ((1.0 - L) + L * (1.0 - h) ** min(float(hz_years), n))
        else:
            q_den = (1.0 + coe) - (1.0 + g) * (1.0 - h)
            pv_tv = tv_df * d_next * ((1.0 - L) / (coe - g) + L * (1.0 - h) ** n * (1.0 - h) / q_den)
        equity = pv_div + pv_tv
    implied_pb = equity / bv0 if bv0 else None
    hazard_info = None
    if h > 0.0:
        hazard_info = {"annual_probability": h, "loss_fraction": L,
                       "cumulative_probability_10y": 1.0 - (1.0 - h) ** 10,
                       "enterprise_value_no_hazard_m": equity_no_hazard,
                       "ev_haircut_pct": (1.0 - equity / equity_no_hazard) * 100.0 if equity_no_hazard else None}
    above_book = equity_no_hazard - bv0
    return {
        "hazard": hazard_info,
        "warnings": ([] if abs(pv_tv_ri) <= 0.75 * abs(above_book) or above_book == 0 else
                     ["terminal residual income is %.0f%% of value above book: the explicit years are not "
                      "carrying the valuation" % (abs(pv_tv_ri) / abs(above_book) * 100)]),
        "method": "residual_income",
        "equity_value_no_hazard_m": equity_no_hazard,
        "implied_price_to_book_no_hazard": equity_no_hazard / bv0 if bv0 else None,
        "cost_of_equity": coe,
        "rows": rows,
        "book_value_m": bv0,
        "pv_residual_income_m": pv,
        "terminal_residual_income_m": ri_next,
        "pv_terminal_m": pv_tv,
        "implied_price_to_book": implied_pb,
        "enterprise_value_m": equity,   # equity value; the bridge below must not deduct debt
        "equity_method": True,
    }


def multiple_only(scenario, case):
    metric = float(scenario["metric_m"])
    mult = float(scenario["multiple"])
    ev = metric * mult
    return {
        "warnings": [],
        "method": "multiple",
        "metric_name": scenario.get("metric_name", "metric"),
        "metric_m": metric,
        "multiple": mult,
        "enterprise_value_m": ev,
    }


# --------------------------------------------------------------------------- #
# bridge to per-share
# --------------------------------------------------------------------------- #

ENGINES = {"dcf": dcf, "sotp": sotp, "multiple": multiple_only, "residual_income": residual_income}


def to_equity(result, scenario, case):
    """EV -> equity value -> per share, with the bridge itemised."""
    ev = result["enterprise_value_m"]
    if result.get("equity_method"):
        net_debt, minority = 0.0, 0.0   # residual income already values equity directly
    else:
        net_debt = float(scenario.get("net_debt_m", case.get("net_debt_m", 0.0)))
        minority = float(scenario.get("minority_interest_m", case.get("minority_interest_m", 0.0)))
    other = float(scenario.get("other_adjustments_m",
                               case.get("other_adjustments_m", scenario.get("other_claims_m", 0.0))))
    shares = float(scenario.get("shares_diluted_m", case["shares_diluted_m"]))
    if shares <= 0:
        raise ValueError("shares_diluted_m must be positive")

    equity = ev - net_debt - minority + other
    per_share = equity / shares

    result["bridge"] = {
        "enterprise_value_m": ev,
        "less_net_debt_m": net_debt,
        "less_minority_interest_m": minority,
        "plus_other_adjustments_m": other,
        "equity_value_m": equity,
        "shares_diluted_m": shares,
    }
    result["equity_value_m"] = equity
    result["value_per_share"] = per_share
    result.setdefault("warnings", [])
    if equity <= 0:
        result["warnings"].append("equity value is non-positive: claims exceed enterprise value.")

    price = scenario.get("price", resolve_price(case))
    fx = _fx(case)
    if fx:
        result["value_per_share_quote"] = per_share * fx
    if case.get("adr_ratio"):
        result["value_per_adr"] = per_share * float(case["adr_ratio"])
    if price:
        price = float(price)
        result["price"] = price
        result["upside_pct"] = (per_share / price - 1.0) * 100.0
    return result


def _fx(case):
    fx = case.get("fx_quote_per_model")
    return float(fx) if fx else None


def resolve_price(case):
    """Spot price in the MODEL currency. Accepts `price` directly, or `price_quote`
    (in quote currency) plus `fx_quote_per_model` (quote units per 1 model unit)."""
    if case.get("price") is not None:
        return float(case["price"])
    if case.get("price_quote") is not None:
        fx = _fx(case)
        if not fx:
            raise ValueError("price_quote given without fx_quote_per_model")
        return float(case["price_quote"]) / fx
    return None


def run_scenario(scenario, case):
    method = scenario.get("method", "dcf")
    if method not in ENGINES:
        raise ValueError("unknown method: %s (expected one of %s)" % (method, ", ".join(ENGINES)))
    res = ENGINES[method](scenario, case)
    res["name"] = scenario.get("name", method)
    res["probability"] = scenario.get("probability")
    return to_equity(res, scenario, case)


def roll_forward_rate(case):
    """Cost of equity in the quote currency for the 12-month roll-forward.

    Three conventions:
      basis = "model": roll forward at the model-currency WACC and convert at spot FX —
                       no FX forecast. Default choice when the report takes no FX view.
      quote_rf + model_rf: interest-rate parity, (1 + WACC)(1 + quote_rf)/(1 + model_rf) - 1.
                       This embeds the forward rate as the FX forecast; disclose it.
      cost_of_equity_quote: given directly."""
    rf = case.get("roll_forward") or {}
    if rf.get("basis") == "model":
        # Roll forward at the model-currency cost of equity and convert at SPOT FX:
        # no currency forecast (a random-walk FX view). Equivalent to applying WACC
        # to the quote-currency fair value.
        return float(case["wacc"])
    if "quote_rf" in rf and "model_rf" in rf:
        return (1.0 + float(case["wacc"])) * (1.0 + float(rf["quote_rf"])) / (1.0 + float(rf["model_rf"])) - 1.0
    return float(rf["cost_of_equity_quote"])


def value_case(case):
    scenarios = case.get("scenarios")
    if not scenarios:
        raise ValueError("case has no scenarios")
    results = [run_scenario(s, case) for s in scenarios]

    probs = [r["probability"] for r in results]
    weighted = None
    if all(p is not None for p in probs):
        total_p = sum(probs)
        if abs(total_p - 1.0) > 1e-6:
            raise ValueError(
                "scenario probabilities sum to %.4f, not 1.0 — fix the weights "
                "rather than letting the engine normalise them silently" % total_p
            )
        weighted = sum(r["value_per_share"] * r["probability"] for r in results)

    price = resolve_price(case)
    out = {
        "ticker": case.get("ticker"),
        "currency": case.get("currency"),
        "valuation_date": case.get("valuation_date"),
        "price": price,
        "scenarios": results,
        "probability_weighted_value_per_share": weighted,
    }
    if weighted and price:
        out["probability_weighted_upside_pct"] = (weighted / price - 1.0) * 100.0
    fx = _fx(case)
    if fx:
        out["quote_currency"] = case.get("quote_currency")
        out["fx_quote_per_model"] = fx
        out["price_quote"] = price * fx if price else None
        if weighted is not None:
            out["probability_weighted_value_per_share_quote"] = weighted * fx
    if case.get("adr_ratio") and weighted is not None:
        out["adr_ratio"] = float(case["adr_ratio"])
        out["probability_weighted_value_per_adr"] = weighted * float(case["adr_ratio"])
    # Equal-weight value: the quality gate's test for weights chosen after the conclusion.
    out["equal_weighted_value_per_share"] = sum(r["value_per_share"] for r in results) / len(results)

    # 12-month target price: today's fair value rolled forward at the cost of equity in the
    # QUOTE currency, less dividends paid over the next 12 months. A target price is a price
    # in a year's time; quoting today's fair value as a 12-month target understates it by
    # roughly the cost of equity.
    rf = case.get("roll_forward")
    if rf and weighted is not None:
        r = roll_forward_rate(case)
        d = float(rf.get("dividends_quote_next_12m", 0.0))
        fv_q = weighted * (fx or 1.0)
        tp = fv_q * (1.0 + r) - d
        out["target_price_12m_quote"] = tp
        out["roll_forward"] = {"cost_of_equity_quote": r, "dividends_quote_next_12m": d,
                               "fair_value_today_quote": fv_q, "basis": rf.get("basis")}
        spot_q = (price * (fx or 1.0)) if price else None
        if spot_q:
            out["target_upside_pct"] = (tp / spot_q - 1.0) * 100.0
            out["expected_total_return_12m_pct"] = ((tp + d) / spot_q - 1.0) * 100.0
        for res in results:
            res["target_price_12m_quote"] = res["value_per_share"] * (fx or 1.0) * (1.0 + r) - d
        if case.get("adr_ratio") and rf.get("basis") == "model":
            # ADR target with the ADR premium assumed to close: model-currency roll-forward,
            # dividends converted at spot.
            ratio = float(case["adr_ratio"])
            out["target_price_12m_per_adr_model"] = (weighted * (1.0 + r) - d / (fx or 1.0)) * ratio
            # ADR targets if the ADR keeps a premium to the local line (premium p: ADR = local x (1+p))
            prem = case.get("adr_premiums")
            if prem:
                out["target_price_12m_per_adr_at_premium"] = {
                    "%.4f" % float(p): out["target_price_12m_per_adr_model"] * (1.0 + float(p)) for p in prem}
        th = case.get("rating_thresholds")
        if th and spot_q:
            up = out["target_upside_pct"] / 100.0
            buy, sell = float(th["buy"]), float(th["sell"])
            out["rating"] = "Buy" if up > buy else ("Sell" if up < sell else "Hold")
            out["price_triggers_quote"] = {"buy_below": tp / (1.0 + buy), "sell_above": tp / (1.0 + sell)}
    return out


# --------------------------------------------------------------------------- #
# reverse DCF
# --------------------------------------------------------------------------- #

def _apply_driver(scenario, case, name, value, from_year=None):
    """Return a (scenario, case) pair with one driver overridden.

    from_year (1-based) overrides a path driver only from that forecast year on,
    keeping earlier years — e.g. take consensus for years 1-2 and solve for what
    the price implies from year 3."""
    s, c = deepcopy(scenario), deepcopy(case)
    if from_year and name in ("revenue_growth", "ebit_margin"):
        b = s.setdefault("driver_build", {})
        cur = b.get(name)
        if cur is None:
            raise ValueError("--from-year needs an existing %s path in driver_build" % name)
        horizon = int(s.get("horizon_years") or b.get("horizon_years") or 0)
        path = list(cur) if isinstance(cur, list) else [cur] * horizon
        if not path:
            raise ValueError("--from-year needs horizon_years or a list-valued %s" % name)
        if horizon and len(path) < horizon:
            path += [path[-1]] * (horizon - len(path))
        k = int(from_year) - 1
        if not 0 < k < len(path):
            raise ValueError("from_year must be between 2 and %d" % len(path))
        b[name] = path[:k] + [value] * (len(path) - k)
        return s, c
    if name == "revenue_growth":
        s.setdefault("driver_build", {})["revenue_growth"] = value
        for k in ("revenue_m", "units", "unit_price"):
            s["driver_build"].pop(k, None)
    elif name == "ebit_margin":
        s.setdefault("driver_build", {})["ebit_margin"] = value
    elif name == "terminal_growth":
        s.setdefault("terminal", {"mode": "gordon"})["terminal_growth"] = value
        c["terminal_growth"] = value
    elif name == "wacc":
        s["wacc"] = value
        c["wacc"] = value
    elif name == "fcff_scale":
        s["fcff_scale"] = value
    elif name == "exit_multiple":
        s.setdefault("terminal", {})["mode"] = "exit_multiple"
        s["terminal"]["multiple"] = value
    elif name == "ebitda_margin":
        # Cash-margin driver: EBIT_t = EBITDA - D&A_t, so D&A changes taxes only.
        b = s.setdefault("driver_build", {})
        n = int(s.get("horizon_years") or b.get("horizon_years") or 0)
        da = b.get("da_pct_revenue", 0.0)
        da_path = list(da) if isinstance(da, list) else [da] * n
        if not da_path:
            raise ValueError("ebitda_margin needs horizon_years or a list-valued da_pct_revenue")
        if from_year:
            cur = b.get("ebit_margin")
            cur = list(cur) if isinstance(cur, list) else [cur] * len(da_path)
            k = int(from_year) - 1
            b["ebit_margin"] = cur[:k] + [value - d for d in da_path[k:]]
        else:
            b["ebit_margin"] = [value - d for d in da_path]
    elif name == "capex_intensity":
        b = s.setdefault("driver_build", {})
        n = int(s.get("horizon_years") or b.get("horizon_years") or 0)
        cur = b.get("capex_pct_revenue", 0.0)
        path = list(cur) if isinstance(cur, list) else [cur] * n
        k = int(from_year) - 1 if from_year else 0
        b["capex_pct_revenue"] = path[:k] + [value] * (len(path) - k)
    elif name == "roe":
        # residual-income scenarios: a flat ROE replaces any ROE / DuPont path
        s["roe"] = value
        s.pop("roa", None)
        s.pop("leverage", None)
    elif name == "payout_ratio":
        s["payout_ratio"] = value
    elif name == "hazard_rate":
        hz = dict(s.get("hazard") or c.get("hazard") or {})
        hz.setdefault("loss_fraction", 1.0)
        hz["annual_probability"] = value
        s["hazard"] = hz
    else:
        raise ValueError("cannot solve for %s (expected one of %s)" % (name, ", ".join(SOLVABLE)))
    return s, c


def reverse_solve(case, scenario_name, solve_for, target_price=None, lo=None, hi=None, tol=1e-7,
                  from_year=None):
    """
    Bisect for the driver value at which the model's per-share value equals the
    market price. This is the market-implied expectation — the number the price
    is already paying for.
    """
    scenarios = {s.get("name", "Base"): s for s in case.get("scenarios", [])}
    if scenario_name not in scenarios:
        raise ValueError(
            "scenario %r not found (have: %s)" % (scenario_name, ", ".join(scenarios) or "none")
        )
    base = scenarios[scenario_name]
    price = target_price if target_price is not None else resolve_price(case)
    if price is None:
        raise ValueError("no price: set price, or price_quote with fx_quote_per_model")
    price = float(price)

    defaults = {
        "revenue_growth": (-0.50, 2.00),
        "ebit_margin": (-0.50, 0.80),
        "terminal_growth": (-0.05, 0.08),
        "wacc": (0.02, 0.60),
        "fcff_scale": (-5.0, 50.0),
        "exit_multiple": (0.1, 200.0),
        "hazard_rate": (0.0, 0.5),
        "ebitda_margin": (0.0, 0.95),
        "roe": (-0.10, 0.60),
        "capex_intensity": (0.0, 0.80),
        "payout_ratio": (0.0, 1.0),
    }
    lo = defaults[solve_for][0] if lo is None else lo
    hi = defaults[solve_for][1] if hi is None else hi

    def f(x):
        s, c = _apply_driver(base, case, solve_for, x, from_year)
        try:
            return run_scenario(s, c)["value_per_share"] - price
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

    f_lo, f_hi = f(lo), f(hi)
    # Walk the bracket inward past undefined regions (e.g. g >= WACC).
    steps = 0
    while f_lo is None and steps < 200:
        lo += (hi - lo) * 0.01
        f_lo, steps = f(lo), steps + 1
    steps = 0
    while f_hi is None and steps < 200:
        hi -= (hi - lo) * 0.01
        f_hi, steps = f(hi), steps + 1

    if f_lo is None or f_hi is None:
        raise ValueError("could not evaluate the model across the %s bracket" % solve_for)
    if f_lo * f_hi > 0:
        raise ValueError(
            "no solution for %s in [%.4f, %.4f]: implied value is %s the price at both ends. "
            "The price cannot be reconciled by this driver alone — widen the bracket with "
            "--lo/--hi, or solve for a different driver."
            % (solve_for, lo, hi, "above" if f_lo > 0 else "below")
        )

    for _ in range(400):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if f_mid is None:
            lo = mid  # undefined region: push the bracket away from it
            continue
        if abs(f_mid) < tol or (hi - lo) < tol:
            break
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid

    implied = (lo + hi) / 2.0
    s, c = _apply_driver(base, case, solve_for, implied, from_year)
    check = run_scenario(s, c)
    span = (" from forecast year %d onward" % from_year) if from_year else ""
    return {
        "scenario": scenario_name,
        "solved_for": solve_for,
        "from_year": from_year,
        "target_price": price,
        "implied_value": implied,
        "model_value_per_share_at_solution": check["value_per_share"],
        "residual": check["value_per_share"] - price,
        "interpretation": (
            "At %s, the current price of %.2f implies %s = %s%s. "
            "The analyst's job is to judge whether that is achievable, not to re-derive it."
            % (
                case.get("valuation_date", "the valuation date"),
                price,
                solve_for,
                _fmt_driver(solve_for, implied),
                span,
            )
        ),
    }


def _fmt_driver(name, v):
    if name in ("revenue_growth", "ebit_margin", "terminal_growth", "wacc", "hazard_rate", "ebitda_margin",
                "roe", "payout_ratio", "capex_intensity"):
        return "%.2f%%" % (v * 100)
    if name == "exit_multiple":
        return "%.2fx" % v
    return "%.4f" % v


# --------------------------------------------------------------------------- #
# sensitivity
# --------------------------------------------------------------------------- #

def sensitivity(case, scenario_name, x_name, x_values, y_name, y_values):
    scenarios = {s.get("name", "Base"): s for s in case.get("scenarios", [])}
    if scenario_name not in scenarios:
        raise ValueError("scenario %r not found" % scenario_name)
    base = scenarios[scenario_name]

    grid = []
    for yv in y_values:
        row = []
        for xv in x_values:
            s, c = _apply_driver(base, case, y_name, yv)
            s, c = _apply_driver(s, c, x_name, xv)
            try:
                row.append(run_scenario(s, c)["value_per_share"])
            except (ValueError, ZeroDivisionError, OverflowError):
                row.append(None)
        grid.append(row)

    return {
        "scenario": scenario_name,
        "x": {"driver": x_name, "values": x_values},
        "y": {"driver": y_name, "values": y_values},
        "grid_value_per_share": grid,
    }


# --------------------------------------------------------------------------- #
# elasticity — Phase 2 driver isolation, made computable
# --------------------------------------------------------------------------- #

def _walk(obj, part):
    return obj[int(part)] if isinstance(obj, list) else obj[part]


def _split_slice(parts):
    """Allow a trailing list slice: 'driver_build.revenue_growth[2:]' -> (parts, slice(2, None))."""
    last = parts[-1]
    if "[" in last and last.endswith("]"):
        key, spec = last[:-1].split("[", 1)
        if ":" not in spec:
            raise ValueError("slice %r must contain ':' (use .N for a single element)" % last)
        lo, hi = spec.split(":", 1)
        sl = slice(int(lo) if lo.strip() else None, int(hi) if hi.strip() else None)
        return parts[:-1] + [key], sl
    return parts, None


def _get_path(obj, parts):
    parts, sl = _split_slice(parts)
    for part in parts:
        obj = _walk(obj, part)
    if sl is not None:
        if not isinstance(obj, list):
            raise ValueError("slice applied to a non-list driver")
        if not obj[sl]:
            raise ValueError("empty slice")
        return obj[sl]
    return obj


def _set_path(obj, parts, value):
    parts, sl = _split_slice(parts)
    for part in parts[:-1]:
        obj = _walk(obj, part)
    last = parts[-1]
    if sl is not None:
        target = obj[int(last)] if isinstance(obj, list) else obj[last]
        if not isinstance(value, list):
            value = [value] * len(target[sl])          # broadcast a scalar over the slice
        target[sl] = value
        return
    if isinstance(obj, list):
        obj[int(last)] = value
    else:
        obj[last] = value


def _bump(v, delta, mode):
    if isinstance(v, list):
        return [_bump(x, delta, mode) for x in v]
    return v + delta if mode == "abs" else v * (1.0 + delta)


def parse_driver_spec(spec):
    """
    LABEL@PATH=SIGMA[:rel]   e.g.  "N2 wafer volume@driver_build.units=0.15:rel"
    PATH=SIGMA[:rel]         label defaults to the path.
    PATH is dotted, relative to the scenario; prefix with "case." for case-level
    fields. List indices are plain integers: segments.1.driver_build.ebit_margin.
    A trailing slice moves part of a path only: driver_build.revenue_growth[2:]
    (years 3 onward) or driver_build.revenue_growth[0:2] (years 1-2).
    SIGMA is a plausible one-standard-deviation move. ':rel' makes it a relative
    move (0.15 = +/-15%); the default is an absolute move (0.02 = +/-2pp).
    """
    label = None
    if "@" in spec:
        label, spec = spec.split("@", 1)
    if "=" not in spec:
        raise ValueError("driver spec %r must look like PATH=SIGMA" % spec)
    path, sig = spec.rsplit("=", 1)
    mode, unit = "abs", "pp"
    if sig.endswith(":rel"):
        mode, sig = "rel", sig[:-4]
    elif sig.endswith(":x"):          # absolute move in a multiple (e.g. leverage), shown as "x"
        unit, sig = "x", sig[:-2]
    return {"label": (label or path).strip(), "path": path.strip(), "sigma": float(sig), "mode": mode, "unit": unit}


def elasticity(case, scenario_name, specs):
    scenarios = {s.get("name", "Base"): s for s in case.get("scenarios", [])}
    if scenario_name not in scenarios:
        raise ValueError("scenario %r not found" % scenario_name)
    base = scenarios[scenario_name]
    v0 = run_scenario(deepcopy(base), deepcopy(case))["value_per_share"]

    rows = []
    for spec in specs:
        path = spec["path"]
        at_case = path.startswith("case.")
        parts = (path[5:] if at_case else path).split(".")
        values = {}
        for sign in (-1, 1):
            s, c = deepcopy(base), deepcopy(case)
            obj = c if at_case else s
            try:
                cur = _get_path(obj, parts)
            except (KeyError, IndexError, ValueError, TypeError):
                # A scenario inherits wacc / terminal_growth etc. from the case.
                if not at_case and len(parts) == 1 and parts[0] in case:
                    cur = case[parts[0]]
                else:
                    raise ValueError("driver path not found in scenario %r: %s" % (scenario_name, path))
            _set_path(obj, parts, _bump(cur, sign * spec["sigma"], spec["mode"]))
            values[sign] = run_scenario(s, c)["value_per_share"]
        swing = values[1] - values[-1]
        rows.append(
            {
                "label": spec["label"],
                "path": path,
                "sigma": spec["sigma"],
                "mode": spec["mode"],
                "unit": spec.get("unit", "pp"),
                "value_minus_1sd": values[-1],
                "value_plus_1sd": values[1],
                "swing": swing,
                "elasticity": (swing / (2.0 * v0)) if v0 > 0 else None,
            }
        )

    rows.sort(key=lambda r: abs(r["swing"]), reverse=True)
    total = sum(r["swing"] ** 2 for r in rows)
    cum = 0.0
    for r in rows:
        r["variance_share"] = (r["swing"] ** 2 / total) if total else None
        cum += r["variance_share"] or 0.0
        r["cumulative_share"] = cum

    top2 = sum((r["variance_share"] or 0.0) for r in rows[:2])
    if len(rows) < 3:
        verdict = "Fewer than three candidate drivers tested: the ranking is not yet a test. Add candidates."
    elif top2 >= 0.70:
        verdict = "Top two drivers explain %.0f%% of tested variance: a clean two-number stock." % (top2 * 100)
    elif top2 >= 0.50:
        verdict = ("Top two drivers explain %.0f%% of tested variance: two numbers lead, but the residual "
                   "is material and must be named in the report." % (top2 * 100))
    else:
        verdict = ("Top two drivers explain only %.0f%% of tested variance: this is NOT a two-number stock. "
                   "Say so in the report and widen the driver set; do not force the frame." % (top2 * 100))

    return {
        "scenario": scenario_name,
        "base_value_per_share": v0,
        "drivers": rows,
        "top_two_variance_share": top2,
        "verdict": verdict,
        "caveat": "Variance shares assume drivers are independent and locally linear. "
                  "Correlated drivers (e.g. growth and operating leverage) overstate the total; "
                  "merge them into one driver before ranking.",
    }


def md_elasticity(out, cur=""):
    L = ["### Driver isolation — %s (base value/share %s %s)" % (out["scenario"], cur, _m(out["base_value_per_share"], 2))]
    L.append("")
    L.append("| Rank | Driver | 1σ move | Value @ −1σ | Value @ +1σ | Swing | Elasticity | Var. share | Cumulative |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(out["drivers"], 1):
        if r["mode"] == "rel":
            sig = "±%.0f%%" % (r["sigma"] * 100)
        elif r.get("unit") == "x":
            sig = "±%.2fx" % r["sigma"]
        else:
            sig = "±%s" % _fmt_abs(r["sigma"])
        L.append(
            "| %d | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                i, r["label"], sig, _m(r["value_minus_1sd"], 2), _m(r["value_plus_1sd"], 2),
                _m(r["swing"], 2),
                ("±%.1f%%" % (abs(r["elasticity"]) * 100)) if r["elasticity"] is not None else "n/a",
                ("%.0f%%" % (r["variance_share"] * 100)) if r["variance_share"] is not None else "n/a",
                "%.0f%%" % (r["cumulative_share"] * 100),
            )
        )
    L.append("")
    L.append("**%s**" % out["verdict"])
    L.append("")
    L.append("_%s_" % out["caveat"])
    return "\n".join(L)


def _fmt_abs(v):
    return ("%.2fpp" % (v * 100)) if abs(v) < 1 else _m(v, 2)


# --------------------------------------------------------------------------- #
# markdown rendering
# --------------------------------------------------------------------------- #

def _m(x, dp=0):
    if x is None:
        return "n/a"
    return format(round(x, dp), ",.%df" % dp)


def md_value(out):
    cur = out.get("currency") or ""
    L = []
    L.append("### Valuation summary — %s (as of %s)" % (out.get("ticker", "n/a"), out.get("valuation_date", "n/a")))
    L.append("")
    qcols = out.get("fx_quote_per_model") is not None
    tpcols = any(s.get("target_price_12m_quote") is not None for s in out["scenarios"])
    qc0 = out.get("quote_currency") or "quote"
    head = "| Scenario | Prob. | Method | EV (%sm) | Equity (%sm) | Value/share | Upside |" % (cur, cur)
    if qcols:
        head += " Value/share (%s) |" % qc0
    if tpcols:
        head += " 12m TP (%s) |" % qc0
    L.append(head)
    L.append("|---" * (7 + int(qcols) + int(tpcols)) + "|")
    for s in out["scenarios"]:
        line = (
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (
                s["name"],
                ("%.0f%%" % (s["probability"] * 100)) if s.get("probability") is not None else "n/a",
                s["method"].upper(),
                _m(s["enterprise_value_m"]),
                _m(s["equity_value_m"]),
                _m(s["value_per_share"], 2),
                ("%+.1f%%" % s["upside_pct"]) if s.get("upside_pct") is not None else "n/a",
            )
        )
        if qcols:
            line += " %s |" % _m(s["value_per_share"] * out["fx_quote_per_model"], 0)
        if tpcols:
            line += " %s |" % (_m(s["target_price_12m_quote"], 0) if s.get("target_price_12m_quote") is not None else "n/a")
        L.append(line)
    L.append("")
    if out.get("probability_weighted_value_per_share_quote") is not None:
        qc = out.get("quote_currency") or "quote"
        L.append(
            "**Probability-weighted value per share: %s %s**  (= %s %s at %.4f %s/%s; spot %s %s, %+.1f%%)"
            % (
                qc, _m(out["probability_weighted_value_per_share_quote"], 0),
                cur, _m(out["probability_weighted_value_per_share"], 2),
                out["fx_quote_per_model"], qc, cur,
                qc, _m(out["price_quote"], 0) if out.get("price_quote") else "n/a",
                out.get("probability_weighted_upside_pct") or 0.0,
            )
        )
        if out.get("probability_weighted_value_per_adr") is not None:
            L.append("")
            L.append("Per ADR (%s, ratio %g): %s" % (cur, out["adr_ratio"], _m(out["probability_weighted_value_per_adr"], 2)))
        L.append("")
        L.append("Equal-weighted value (bias check): %s %s" % (cur, _m(out["equal_weighted_value_per_share"], 2)))
        L.append("")
        if out.get("target_price_12m_quote") is not None:
            rf = out["roll_forward"]
            L.append(
                "**12-month target price: %s %s** = fair value %s x (1 + %.2f%% roll-forward rate%s) "
                "- %s dividends; vs spot %+.1f%%, expected 12-month total return %+.1f%%"
                % (
                    qc, _m(out["target_price_12m_quote"], 0), _m(rf["fair_value_today_quote"], 0),
                    rf["cost_of_equity_quote"] * 100,
                    ", model-currency cost of equity at spot FX" if rf.get("basis") == "model"
                    else ", cost of equity in %s" % qc,
                    _m(rf["dividends_quote_next_12m"], 0),
                    out.get("target_upside_pct") or 0.0, out.get("expected_total_return_12m_pct") or 0.0,
                )
            )
            L.append("")
            if out.get("target_price_12m_per_adr_model") is not None:
                parts = ["%s %s with no ADR premium" % (cur, _m(out["target_price_12m_per_adr_model"], 2))]
                for k, v in (out.get("target_price_12m_per_adr_at_premium") or {}).items():
                    if float(k) != 0.0:
                        parts.append("%s %s at a %.1f%% premium" % (cur, _m(v, 2), float(k) * 100))
                L.append("12-month target per ADR: " + "; ".join(parts))
                L.append("")
            if out.get("rating"):
                pt = out["price_triggers_quote"]
                L.append("**Rating (mechanical): %s** — buy below %s %s, sell above %s %s"
                         % (out["rating"], qc, _m(pt["buy_below"], 0), qc, _m(pt["sell_above"], 0)))
                L.append("")
    elif out.get("probability_weighted_value_per_share") is not None:
        L.append(
            "**Probability-weighted fair value: %s %s**%s"
            % (
                cur,
                _m(out["probability_weighted_value_per_share"], 2),
                ("  (vs spot %s %s, %+.1f%%)" % (cur, _m(out["price"], 2), out["probability_weighted_upside_pct"]))
                if out.get("probability_weighted_upside_pct") is not None
                else "",
            )
        )
        L.append("")

    flagged = [(s["name"], w) for s in out["scenarios"] for w in s.get("warnings", [])]
    if flagged:
        L.append("**Model warnings — resolve or explain each in the report:**")
        L.append("")
        for name, w in flagged:
            L.append("- WARNING (%s): %s" % (name, w))
        L.append("")

    if out.get("target_price_12m_quote") is not None and out.get("probability_weighted_value_per_share_quote") is None:
        rf = out["roll_forward"]
        L.append("**12-month target price: %s %s** = fair value %s x (1 + %.2f%% cost of equity) - %s dividends; "
                 "vs spot %+.1f%%, expected 12-month total return %+.1f%%"
                 % (cur, _m(out["target_price_12m_quote"], 2), _m(rf["fair_value_today_quote"], 2),
                    rf["cost_of_equity_quote"] * 100, _m(rf["dividends_quote_next_12m"], 2),
                    out.get("target_upside_pct") or 0.0, out.get("expected_total_return_12m_pct") or 0.0))
        L.append("")
        if out.get("rating"):
            pt = out["price_triggers_quote"]
            L.append("**Rating (mechanical): %s** — buy below %s %s, sell above %s %s"
                     % (out["rating"], cur, _m(pt["buy_below"], 2), cur, _m(pt["sell_above"], 2)))
            L.append("")

    for s in out["scenarios"]:
        if s["method"] == "residual_income":
            L.append("#### %s — residual income (%sm)" % (s["name"], cur))
            L.append("")
            L.append("| Year | Opening book | ROE | Net income | Residual income | Dividends | Survival |")
            L.append("|---|---|---|---|---|---|---|")
            for r in s["rows"]:
                L.append("| %d | %s | %.2f%% | %s | %s | %s | %.3f |" % (
                    r["year"], _m(r["book_value_open_m"]), r["roe"] * 100, _m(r["net_income_m"]),
                    _m(r["residual_income_m"]), _m(r["dividends_m"]), r["survival_multiplier"]))
            L.append("")
            L.append("Cost of equity %.2f%% · implied P/B %.2fx (no event risk %.2fx)%s" % (
                s["cost_of_equity"] * 100, s["implied_price_to_book"], s["implied_price_to_book_no_hazard"],
                (" · event-risk haircut %.1f%%" % s["hazard"]["ev_haircut_pct"]) if s.get("hazard") else ""))
            L.append("")
        if s["method"] == "dcf" and s["rows"] and s["rows"][0].get("revenue_m") is not None:
            L.append("#### %s — FCFF build (%sm)" % (s["name"], cur))
            L.append("")
            L.append("| Year | Revenue | Growth | EBIT | Margin | NOPAT | +D&A | −Capex | −ΔNWC | −SBC | FCFF | PV |")
            L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for r in s["rows"]:
                L.append(
                    "| %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                    % (
                        r["year"], _m(r["revenue_m"]),
                        ("%.1f%%" % (r["revenue_growth"] * 100)) if r.get("revenue_growth") is not None else "n/a",
                        _m(r["ebit_m"]),
                        ("%.1f%%" % (r["ebit_margin"] * 100)) if r.get("ebit_margin") is not None else "n/a",
                        _m(r["nopat_m"]), _m(r["da_m"]), _m(r["capex_m"]),
                        _m(r["delta_nwc_m"]), _m(r["sbc_m"]), _m(r["fcff_m"]), _m(r["pv_fcff_m"]),
                    )
                )
            L.append("")
            L.append(
                "PV of explicit forecast %s · PV of terminal value %s (%.0f%% of EV) · WACC %.2f%%"
                % (
                    _m(s["pv_explicit_m"]), _m(s["pv_terminal_m"]),
                    (s["terminal_pct_of_ev"] or 0) * 100, s["wacc"] * 100,
                )
            )
            hz = s.get("hazard")
            if hz:
                L.append("")
                L.append(
                    "Event-risk overlay: %.2f%%/yr probability, %.0f%% loss of operating value "
                    "(%.1f%% cumulative over 10 years) — EV haircut %.1f%% vs no-event value %s"
                    % (
                        hz["annual_probability"] * 100, hz["loss_fraction"] * 100,
                        hz["cumulative_probability_10y"] * 100, hz["ev_haircut_pct"],
                        _m(hz["enterprise_value_no_hazard_m"]),
                    )
                )
            im = s.get("implied_terminal_multiples") or {}
            if im:
                L.append("")
                L.append(
                    "Terminal value implies (at the end of year N): %s"
                    % " · ".join("%s %.1fx" % (k.replace("_after_event_risk", " after event risk").replace("_", "/").upper(), v)
                                 for k, v in sorted(im.items()))
                )
            L.append("")
        if s["method"] == "sotp":
            L.append("#### %s — sum of the parts (%sm)" % (s["name"], cur))
            L.append("")
            L.append("| Value pool | Basis | Gross | P(success) | Stake | Attributable | % of EV |")
            L.append("|---|---|---|---|---|---|---|")
            for p in s["segments"]:
                L.append(
                    "| %s | %s | %s | %.0f%% | %.0f%% | %s | %.0f%% |"
                    % (
                        p["name"], p["basis"], _m(p["gross_value_m"]),
                        p["probability_of_success"] * 100, p["stake"] * 100,
                        _m(p["attributable_value_m"]), (p["pct_of_ev"] or 0) * 100,
                    )
                )
            L.append("")
    return "\n".join(L)


def md_sensitivity(out, cur="", dp=2):
    x, y = out["x"], out["y"]
    L = ["### Sensitivity — %s: value/share%s" % (out["scenario"], (" (%s)" % cur) if cur else "")]
    L.append("")
    L.append("| %s \\ %s | %s |" % (y["driver"], x["driver"], " | ".join(_fmt_driver(x["driver"], v) for v in x["values"])))
    L.append("|---|%s" % ("---|" * len(x["values"])))
    for yv, row in zip(y["values"], out["grid_value_per_share"]):
        L.append(
            "| **%s** | %s |"
            % (_fmt_driver(y["driver"], yv), " | ".join(_m(c, dp) for c in row))
        )
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _floats(s):
    return [float(x) for x in s.split(",") if x.strip() != ""]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Valuation engine for the stock-valuation skill.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("value", help="value all scenarios")
    p.add_argument("--input", required=True)
    p.add_argument("--markdown", action="store_true")

    r = sub.add_parser("reverse", help="reverse DCF: solve for the market-implied driver")
    r.add_argument("--input", required=True)
    r.add_argument("--scenario", default="Base")
    r.add_argument("--solve-for", required=True, choices=SOLVABLE)
    r.add_argument("--price", type=float, default=None)
    r.add_argument("--lo", type=float, default=None)
    r.add_argument("--hi", type=float, default=None)
    r.add_argument("--from-year", type=int, default=None,
                   help="solve only from this forecast year on, keeping earlier years as given")

    s = sub.add_parser("sensitivity", help="2-D sensitivity grid")
    s.add_argument("--input", required=True)
    s.add_argument("--scenario", default="Base")
    s.add_argument("--x", required=True, choices=SOLVABLE)
    s.add_argument("--x-values", required=True)
    s.add_argument("--y", required=True, choices=SOLVABLE)
    s.add_argument("--y-values", required=True)
    s.add_argument("--markdown", action="store_true")

    e = sub.add_parser("elasticity", help="rank candidate drivers by valuation elasticity (Phase 2)")
    e.add_argument("--input", required=True)
    e.add_argument("--scenario", default="Base")
    e.add_argument("--driver", action="append", required=True,
                   help="LABEL@PATH=SIGMA[:rel]; repeat once per candidate driver")
    e.add_argument("--markdown", action="store_true")

    a = ap.parse_args(argv)
    with open(a.input, "r", encoding="utf-8") as fh:
        case = json.load(fh)

    try:
        if a.cmd == "value":
            out = value_case(case)
            if a.markdown:
                print(md_value(out))
            else:
                print(json.dumps(out, indent=2, ensure_ascii=False))
        elif a.cmd == "reverse":
            out = reverse_solve(case, a.scenario, a.solve_for, a.price, a.lo, a.hi,
                                from_year=a.from_year)
            print(json.dumps(out, indent=2, ensure_ascii=False))
        elif a.cmd == "elasticity":
            out = elasticity(case, a.scenario, [parse_driver_spec(d) for d in a.driver])
            if a.markdown:
                print(md_elasticity(out, case.get("currency", "")))
            else:
                print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            out = sensitivity(case, a.scenario, a.x, _floats(a.x_values), a.y, _floats(a.y_values))
            if a.markdown:
                print(md_sensitivity(out, case.get("currency", "")))
            else:
                print(json.dumps(out, indent=2, ensure_ascii=False))
    except (ValueError, KeyError) as exc:
        sys.stderr.write("valuation_engine: %s\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
