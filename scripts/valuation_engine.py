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
            metrics = {
                "ebitda": last["ebit_m"] + last["da_m"],
                "ebit": last["ebit_m"],
                "fcff": last["fcff_m"],
                "revenue": last["revenue_m"],
                "nopat": last["nopat_m"],
            }
            if name not in metrics:
                raise ValueError("unknown terminal metric_name: %s" % name)
            metric = metrics[name]
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
    """Cash-flow discount factors. TV is always discounted at full year N."""
    out = []
    for t in range(1, years + 1):
        exp = t - 0.5 if midyear else t
        out.append(1.0 / (1.0 + wacc) ** exp)
    return out


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
    pv_explicit = 0.0
    for r, df in zip(rows, dfs):
        r["discount_factor"] = df
        r["pv_fcff_m"] = r["fcff_m"] * df
        pv_explicit += r["pv_fcff_m"]

    terminal = dict(scenario.get("terminal", {"mode": "gordon"}))
    if terminal.get("mode", "gordon") == "gordon" and "terminal_growth" not in terminal:
        terminal["terminal_growth"] = case.get("terminal_growth")
    if "multiple" in scenario and terminal.get("mode") == "exit_multiple":
        terminal["multiple"] = scenario["multiple"]

    tv, tv_detail = terminal_value(rows, terminal, wacc)
    tv_df = 1.0 / (1.0 + wacc) ** n
    pv_tv = tv * tv_df

    ev = pv_explicit + pv_tv
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
    return {
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

ENGINES = {"dcf": dcf, "sotp": sotp, "multiple": multiple_only}


def to_equity(result, scenario, case):
    """EV -> equity value -> per share, with the bridge itemised."""
    ev = result["enterprise_value_m"]
    net_debt = float(scenario.get("net_debt_m", case.get("net_debt_m", 0.0)))
    minority = float(scenario.get("minority_interest_m", case.get("minority_interest_m", 0.0)))
    other = float(scenario.get("other_adjustments_m", scenario.get("other_claims_m", 0.0)))
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

    price = scenario.get("price", case.get("price"))
    if price:
        price = float(price)
        result["price"] = price
        result["upside_pct"] = (per_share / price - 1.0) * 100.0
    return result


def run_scenario(scenario, case):
    method = scenario.get("method", "dcf")
    if method not in ENGINES:
        raise ValueError("unknown method: %s (expected one of %s)" % (method, ", ".join(ENGINES)))
    res = ENGINES[method](scenario, case)
    res["name"] = scenario.get("name", method)
    res["probability"] = scenario.get("probability")
    return to_equity(res, scenario, case)


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

    out = {
        "ticker": case.get("ticker"),
        "currency": case.get("currency"),
        "valuation_date": case.get("valuation_date"),
        "price": case.get("price"),
        "scenarios": results,
        "probability_weighted_value_per_share": weighted,
    }
    if weighted and case.get("price"):
        out["probability_weighted_upside_pct"] = (weighted / float(case["price"]) - 1.0) * 100.0
    return out


# --------------------------------------------------------------------------- #
# reverse DCF
# --------------------------------------------------------------------------- #

def _apply_driver(scenario, case, name, value):
    """Return a (scenario, case) pair with one driver overridden."""
    s, c = deepcopy(scenario), deepcopy(case)
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
    else:
        raise ValueError("cannot solve for %s (expected one of %s)" % (name, ", ".join(SOLVABLE)))
    return s, c


def reverse_solve(case, scenario_name, solve_for, target_price=None, lo=None, hi=None, tol=1e-7):
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
    price = float(target_price if target_price is not None else case["price"])

    defaults = {
        "revenue_growth": (-0.50, 2.00),
        "ebit_margin": (-0.50, 0.80),
        "terminal_growth": (-0.05, 0.08),
        "wacc": (0.02, 0.60),
        "fcff_scale": (-5.0, 50.0),
        "exit_multiple": (0.1, 200.0),
    }
    lo = defaults[solve_for][0] if lo is None else lo
    hi = defaults[solve_for][1] if hi is None else hi

    def f(x):
        s, c = _apply_driver(base, case, solve_for, x)
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
    s, c = _apply_driver(base, case, solve_for, implied)
    check = run_scenario(s, c)
    return {
        "scenario": scenario_name,
        "solved_for": solve_for,
        "target_price": price,
        "implied_value": implied,
        "model_value_per_share_at_solution": check["value_per_share"],
        "residual": check["value_per_share"] - price,
        "interpretation": (
            "At %s, the current price of %.2f implies %s = %s. "
            "The analyst's job is to judge whether that is achievable, not to re-derive it."
            % (
                case.get("valuation_date", "the valuation date"),
                price,
                solve_for,
                _fmt_driver(solve_for, implied),
            )
        ),
    }


def _fmt_driver(name, v):
    if name in ("revenue_growth", "ebit_margin", "terminal_growth", "wacc"):
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


def _get_path(obj, parts):
    for part in parts:
        obj = _walk(obj, part)
    return obj


def _set_path(obj, parts, value):
    for part in parts[:-1]:
        obj = _walk(obj, part)
    last = parts[-1]
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
    SIGMA is a plausible one-standard-deviation move. ':rel' makes it a relative
    move (0.15 = +/-15%); the default is an absolute move (0.02 = +/-2pp).
    """
    label = None
    if "@" in spec:
        label, spec = spec.split("@", 1)
    if "=" not in spec:
        raise ValueError("driver spec %r must look like PATH=SIGMA" % spec)
    path, sig = spec.rsplit("=", 1)
    mode = "abs"
    if sig.endswith(":rel"):
        mode, sig = "rel", sig[:-4]
    return {"label": (label or path).strip(), "path": path.strip(), "sigma": float(sig), "mode": mode}


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
        sig = ("±%.0f%%" % (r["sigma"] * 100)) if r["mode"] == "rel" else ("±%s" % _fmt_abs(r["sigma"]))
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
    L.append("| Scenario | Prob. | Method | EV (%sm) | Equity (%sm) | Value/share | Upside |" % (cur, cur))
    L.append("|---|---|---|---|---|---|---|")
    for s in out["scenarios"]:
        L.append(
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
    L.append("")
    if out.get("probability_weighted_value_per_share") is not None:
        L.append(
            "**Probability-weighted target price: %s %s**%s"
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

    for s in out["scenarios"]:
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


def md_sensitivity(out, cur=""):
    x, y = out["x"], out["y"]
    L = ["### Sensitivity — %s: value/share%s" % (out["scenario"], (" (%s)" % cur) if cur else "")]
    L.append("")
    L.append("| %s \\ %s | %s |" % (y["driver"], x["driver"], " | ".join(_fmt_driver(x["driver"], v) for v in x["values"])))
    L.append("|---|%s" % ("---|" * len(x["values"])))
    for yv, row in zip(y["values"], out["grid_value_per_share"]):
        L.append(
            "| **%s** | %s |"
            % (_fmt_driver(y["driver"], yv), " | ".join(_m(c, 2) for c in row))
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
            out = reverse_solve(case, a.scenario, a.solve_for, a.price, a.lo, a.hi)
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
