#!/usr/bin/env python3
"""
run_analysis.py — run every engine analysis a report needs from ONE spec file, and write a
numbers appendix (markdown) plus a JSON of every figure.

Why: the report's prose is written by hand, but every number in it should be traceable to a
single, re-runnable artefact. The quality gate "re-running the engine reproduces every
valuation figure" becomes one command:

    python3 scripts/run_analysis.py --spec reports/2330_spec.json

Spec format (all sections optional except "case"):

{
  "case": "reports/2330_case.json",
  "out_md": "reports/2330_numbers.md",
  "out_json": "reports/2330_numbers.json",
  "quote": true,                       # show per-share values in the quote currency
  "elasticity": [{"title": "...", "scenario": "Base", "drivers": ["Label@path=sigma", ...]}],
  "reverse":    [{"title": "...", "scenario": "Base", "solve_for": "revenue_growth",
                  "from_year": 3, "set": {"case.hazard": null}}],
  "sensitivity":[{"title": "...", "scenario": "Base", "x": "wacc", "x_values": [...],
                  "y": "terminal_growth", "y_values": [...], "set": {...}}],
  "variants":   [{"label": "...", "set": {...}}],          # independent what-ifs
  "bridge":     {"title": "...", "measure": "fair_value|target_12m",
                 "steps": [{"label": "...", "set": {...}}]},                # cumulative
  "solve":      [{"title": "...", "path": "case.wacc", "target": 3300,
                  "measure": "target_12m", "lo": 0.05, "hi": 0.15, "set": {...}}]
}

"set" paths: "case.<field>" for case-level fields; "scenarios.<Name|*>.<path>" for scenario
fields (a trailing [a:b] slice is allowed on list drivers). A value of null deletes the field
(e.g. "case.hazard": null removes the event-risk overlay).
"""
import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import valuation_engine as ve  # noqa: E402


def _delete(obj, parts):
    for part in parts[:-1]:
        obj = ve._walk(obj, part)
    if isinstance(obj, dict):
        obj.pop(parts[-1], None)


def apply_sets(case, sets):
    case = copy.deepcopy(case)
    for path, value in (sets or {}).items():
        parts = path.split(".")
        if parts[0] == "case":
            parts = parts[1:]
            if value is None:
                _delete(case, parts)
            else:
                ve._set_path(case, parts, copy.deepcopy(value))
        elif parts[0] == "scenarios":
            sel = parts[1]
            targets = [s for s in case["scenarios"] if sel == "*" or s.get("name") == sel]
            if not targets:
                raise ValueError("set path %r matches no scenario" % path)
            for s in targets:
                if value is None:
                    _delete(s, parts[2:])
                else:
                    ve._set_path(s, parts[2:], copy.deepcopy(value))
        else:
            raise ValueError("set path must start with 'case.' or 'scenarios.': %r" % path)
    return case


def pw_quote(case, measure="fair_value"):
    """Probability-weighted value in the quote currency. measure: fair_value (today) or
    target_12m (fair value rolled forward 12 months, less dividends)."""
    out = ve.value_case(case)
    fx = ve._fx(case) or 1.0
    if measure == "target_12m":
        if out.get("target_price_12m_quote") is None:
            raise ValueError("measure target_12m needs roll_forward in the case")
        return out, out["target_price_12m_quote"]
    return out, out["probability_weighted_value_per_share"] * fx


def solve(case, path, target, measure, lo, hi, tol=1e-7):
    """Bisect a case path (e.g. case.wacc) until the measure hits the target."""
    def f(x):
        return pw_quote(apply_sets(case, {path: x}), measure)[1] - target
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        raise ValueError("target not bracketed by [%s, %s]" % (lo, hi))
    for _ in range(300):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < tol or hi - lo < tol:
            break
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def _dp(case):
    """Decimals for per-share figures: whole units for large share prices, cents for small ones."""
    try:
        px = float(ve.resolve_price(case) or 0) * float(ve._fx(case) or 1.0)
    except Exception:
        px = 0.0
    return 0 if px >= 1000 else 2


def fmt_q(v, case):
    return "%s %s" % (case.get("quote_currency") or case.get("currency") or "", ve._m(v, _dp(case)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--spec", required=True)
    a = ap.parse_args(argv)
    spec = json.load(open(a.spec, encoding="utf-8"))
    case = json.load(open(spec["case"], encoding="utf-8"))
    if spec.get("case_set"):
        # an alternative parameterisation of the same case file (e.g. a different beta), so the
        # appendix for it is generated rather than hand-computed
        case = apply_sets(case, spec["case_set"])
    fx = ve._fx(case) or 1.0
    DP = _dp(case)
    use_quote = bool(spec.get("quote")) and ve._fx(case) is not None
    qcur = case.get("quote_currency") if use_quote else case.get("currency")
    md, js = [], {"case": spec["case"], "valuation_date": case.get("valuation_date")}

    md.append("# Numbers appendix — %s (as of %s)" % (case.get("ticker"), case.get("valuation_date")))
    md.append("")
    md.append("Generated by `python3 scripts/run_analysis.py --spec %s`. Every valuation figure in the "
              "report should appear here. Model currency %s%s." % (
                  a.spec, case.get("currency"),
                  ("; per-share values converted to %s at %s" % (qcur, fx)) if use_quote else ""))
    md.append("")

    # ---- value
    out = ve.value_case(case)
    js["value"] = out
    md.append("## 1. Valuation")
    md.append("")
    md.append(ve.md_value(out))
    md.append("")
    if use_quote:
        md.append("| Scenario | Value/share (%s) |" % qcur)
        md.append("|---|---|")
        for s in out["scenarios"]:
            md.append("| %s | %s |" % (s["name"], ve._m(s["value_per_share"] * fx, DP)))
        md.append("| **Probability-weighted** | **%s** |" % ve._m(out["probability_weighted_value_per_share"] * fx, DP))
        md.append("| Equal-weighted (bias check) | %s |" % ve._m(out["equal_weighted_value_per_share"] * fx, DP))
        md.append("")

    # ---- elasticity
    js["elasticity"] = []
    for i, el in enumerate(spec.get("elasticity", []), 1):
        c = apply_sets(case, el.get("set"))
        r = ve.elasticity(c, el.get("scenario", "Base"), [ve.parse_driver_spec(d) for d in el["drivers"]])
        r["title"] = el.get("title")
        js["elasticity"].append(r)
        md.append("## 2.%d Elasticity — %s" % (i, el.get("title", "")))
        md.append("")
        md.append(ve.md_elasticity(r, case.get("currency", "")))
        md.append("")

    # ---- reverse
    js["reverse"] = []
    if spec.get("reverse"):
        md.append("## 3. Reverse DCF — what the price implies")
        md.append("")
        md.append("| # | Question | Scenario | Solve for | From year | Implied | Residual |")
        md.append("|---|---|---|---|---|---|---|")
        for i, rv in enumerate(spec["reverse"], 1):
            c = apply_sets(case, rv.get("set"))
            try:
                r = ve.reverse_solve(c, rv.get("scenario", "Base"), rv["solve_for"],
                                     from_year=rv.get("from_year"))
                implied = ve._fmt_driver(rv["solve_for"], r["implied_value"])
                if rv["solve_for"] == "hazard_rate":
                    implied += " (10y cumulative %.1f%%)" % ((1 - (1 - r["implied_value"]) ** 10) * 100)
                resid = "%.2e" % r["residual"]
            except ValueError as exc:
                r = {"error": str(exc)}
                implied, resid = "no solution: %s" % str(exc).split(":")[0], "—"
            r["title"] = rv.get("title")
            js["reverse"].append(r)
            md.append("| %d | %s | %s | %s | %s | %s | %s |" % (
                i, rv.get("title", ""), rv.get("scenario", "Base"), rv["solve_for"],
                rv.get("from_year") or "—", implied, resid))
        md.append("")

    # ---- variants
    js["variants"] = []
    if spec.get("variants"):
        md.append("## 4. Variants (independent what-ifs, probability-weighted value per share)")
        md.append("")
        has_tp = bool(case.get("roll_forward"))
        md.append("| Variant | Fair value/share (%s) | vs spot |%s" % (qcur, " 12-month TP | TP vs spot |" if has_tp else ""))
        md.append("|---|---|---|%s" % ("---|---|" if has_tp else ""))
        spot = (ve.resolve_price(case) or 0) * (fx if use_quote else 1)
        for v in spec["variants"]:
            c = apply_sets(case, v.get("set"))
            o, q = pw_quote(c)
            val = q if use_quote else o["probability_weighted_value_per_share"]
            tp = o.get("target_price_12m_quote")
            js["variants"].append({"label": v["label"], "value": val, "target_12m": tp, "scenarios": {
                s["name"]: s["value_per_share"] * (fx if use_quote else 1) for s in o["scenarios"]}})
            row = "| %s | %s | %+.1f%% |" % (v["label"], ve._m(val, DP), (val / spot - 1) * 100 if spot else 0)
            if has_tp:
                row += " %s | %+.1f%% |" % (ve._m(tp, DP), (tp / spot - 1) * 100 if spot else 0)
            md.append(row)
        md.append("")

    # ---- bridge
    if spec.get("bridge"):
        br = spec["bridge"]
        measure = br.get("measure", "fair_value")
        mlabel = "12-month target price" if measure == "target_12m" else "probability-weighted fair value"
        md.append("## 5. Bridge — %s" % br.get("title", ""))
        md.append("")
        md.append("Measure: %s." % mlabel)
        md.append("")
        md.append("| Step | Value/share (%s) | Contribution |" % qcur)
        md.append("|---|---|---|")
        c = copy.deepcopy(case)
        o, q = pw_quote(c, measure)
        prev = q if (use_quote or measure == "target_12m") else o["probability_weighted_value_per_share"]
        rows = [{"label": "Our " + mlabel, "value": prev, "delta": None}]
        md.append("| Our %s | %s | — |" % (mlabel, ve._m(prev, DP)))
        for st in br["steps"]:
            c = apply_sets(c, st.get("set"))
            o, q = pw_quote(c, measure)
            val = q if (use_quote or measure == "target_12m") else o["probability_weighted_value_per_share"]
            rows.append({"label": st["label"], "value": val, "delta": val - prev})
            md.append("| + %s | %s | %+s |" % (st["label"], ve._m(val, DP), ve._m(val - prev, DP)))
            prev = val
        if br.get("target"):
            md.append("| Target to explain: %s | %s | residual %+s |" % (
                br.get("target_label", "target"), ve._m(br["target"], DP), ve._m(br["target"] - prev, DP)))
        md.append("")
        js["bridge"] = rows

        if br.get("shapley"):
            # Order-independent attribution: average marginal contribution over all orderings.
            import itertools, math
            steps = br["steps"]
            n = len(steps)
            cache = {}

            def v(mask):
                if mask not in cache:
                    c2 = copy.deepcopy(case)
                    for i in range(n):
                        if mask & (1 << i):
                            c2 = apply_sets(c2, steps[i].get("set"))
                    cache[mask] = pw_quote(c2, measure)[1]
                return cache[mask]

            phi = []
            for i in range(n):
                tot = 0.0
                for mask in range(1 << n):
                    if mask & (1 << i):
                        continue
                    k = bin(mask).count("1")
                    w = math.factorial(k) * math.factorial(n - k - 1) / math.factorial(n)
                    tot += w * (v(mask | (1 << i)) - v(mask))
                phi.append(tot)
            md.append("**Order-independent (Shapley) attribution of the same gap:**")
            md.append("")
            md.append("| Step | Shapley contribution | Range across orderings |")
            md.append("|---|---|---|")
            for i in range(n):
                contribs = []
                for perm in itertools.permutations(range(n)):
                    mask = 0
                    for j in perm:
                        if j == i:
                            contribs.append(v(mask | (1 << i)) - v(mask))
                            break
                        mask |= (1 << j)
                md.append("| %s | %+s | %+s to %+s |" % (steps[i]["label"], ve._m(phi[i], DP),
                                                        ve._m(min(contribs), DP), ve._m(max(contribs), DP)))
            md.append("| Total | %+s | |" % ve._m(sum(phi), DP))
            md.append("")
            js["bridge_shapley"] = [{"label": steps[i]["label"], "shapley": phi[i]} for i in range(n)]

    # ---- solve: bisect a case path so a measure hits a target
    js["solve"] = []
    if spec.get("solve"):
        md.append("## 5b. Solves — the input that makes a measure hit a target")
        md.append("")
        md.append("| # | Question | Path | Measure | Target | Solution |")
        md.append("|---|---|---|---|---|---|")
        for i, sv in enumerate(spec["solve"], 1):
            c = apply_sets(case, sv.get("set"))
            tgt = sv["target"]
            if isinstance(tgt, str):
                # named targets: the as-modelled measure (e.g. the no-event rate that reproduces our value)
                if tgt not in ("as_modelled_fair_value", "as_modelled_target_12m"):
                    raise ValueError("unknown named solve target %r" % tgt)
                tgt = pw_quote(case, tgt.replace("as_modelled_", ""))[1]
                sv = dict(sv, target=tgt)
            try:
                x = solve(c, sv["path"], float(tgt), sv.get("measure", "fair_value"),
                          float(sv["lo"]), float(sv["hi"]))
                sol = ("%.2f%%" % (x * 100)) if sv.get("percent", True) else ("%.4f" % x)
            except ValueError as exc:
                x, sol = None, "no solution: %s" % exc
            js["solve"].append({"title": sv.get("title"), "solution": x})
            md.append("| %d | %s | %s | %s | %s | %s |" % (i, sv.get("title", ""), sv["path"],
                                                     sv.get("measure", "fair_value"), ve._m(float(sv["target"]), DP), sol))
        md.append("")

    # ---- grids: a probability-weighted measure over two case paths (e.g. the rating's TP);
    # rendered after the sensitivity tables so the appendix reads 6.x then 7.x
    js["grids"] = []
    gmd = []
    for i, gd in enumerate(spec.get("grids", []), 1):
        measure = gd.get("measure", "target_12m")
        base_c = apply_sets(case, gd.get("set"))
        rows = []
        for yv in gd["y_values"]:
            row = []
            for xv in gd["x_values"]:
                c2 = apply_sets(base_c, {gd["y_path"]: yv, gd["x_path"]: xv})
                try:
                    row.append(pw_quote(c2, measure)[1])
                except (ValueError, ZeroDivisionError):
                    row.append(None)
            rows.append(row)
        js["grids"].append({"title": gd.get("title"), "x": gd["x_values"], "y": gd["y_values"], "grid": rows})
        mark = gd.get("mark_below")
        buy = gd.get("mark_buy")
        dec = int(gd.get("decimals", 0))
        gmd.append("## 7.%d Grid — %s" % (i, gd.get("title", "")))
        gmd.append("")
        gmd.append("Measure: %s (probability-weighted)%s%s." % (
            "12-month target price" if measure == "target_12m" else "fair value",
            ("; cells at or above %s marked with *" % ve._m(mark, dec)) if mark else "",
            ("; cells at or above %s (Buy) marked with +" % ve._m(buy, dec)) if buy else ""))
        gmd.append("")
        fmt = lambda v, lab: ("%.2f%%" % (v * 100)) if gd.get(lab + "_percent", True) else str(v)
        gmd.append("| %s \\ %s | %s |" % (gd.get("y_label", gd["y_path"]), gd.get("x_label", gd["x_path"]),
                                          " | ".join(fmt(x, "x") for x in gd["x_values"])))
        gmd.append("|---|%s" % ("---|" * len(gd["x_values"])))
        for yv, row in zip(gd["y_values"], rows):
            cells = []
            for v in row:
                if v is None:
                    cells.append("n/a")
                else:
                    tag = "+" if (buy is not None and v >= buy) else ("*" if (mark is not None and v >= mark) else "")
                    cells.append(ve._m(v, dec) + tag)
            gmd.append("| **%s** | %s |" % (fmt(yv, "y"), " | ".join(cells)))
        gmd.append("")

    # ---- sensitivity
    js["sensitivity"] = []
    for i, sv in enumerate(spec.get("sensitivity", []), 1):
        c = apply_sets(case, sv.get("set"))
        r = ve.sensitivity(c, sv.get("scenario", "Base"), sv["x"], sv["x_values"], sv["y"], sv["y_values"])
        if use_quote:
            r["grid_value_per_share"] = [[(v * fx if v is not None else None) for v in row]
                                         for row in r["grid_value_per_share"]]
        r["title"] = sv.get("title")
        js["sensitivity"].append(r)
        md.append("## 6.%d Sensitivity — %s" % (i, sv.get("title", "")))
        md.append("")
        md.append(ve.md_sensitivity(r, qcur or "", dp=0 if use_quote else 2))
        md.append("")

    md.extend(gmd)
    out_md = spec.get("out_md")
    out_json = spec.get("out_json")
    text = "\n".join(md)
    if out_md:
        open(out_md, "w", encoding="utf-8").write(text + "\n")
    if out_json:
        json.dump(js, open(out_json, "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    if not out_md:
        print(text)
    else:
        print("wrote %s%s" % (out_md, (" and %s" % out_json) if out_json else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
