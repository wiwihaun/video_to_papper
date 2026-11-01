#!/usr/bin/env python3
"""
Derived financial summary for the 2330 report (EPS, P/E, FCF) — every input is either a
sourced actual or the Base scenario of reports/2330_case.json. Run:
    python3 reports/2330_financials.py > reports/2330_financials.md
Assumptions (stated in the report): after-tax interest income on cash & marketable securities
at 3.4% pre-tax (3Q26 non-operating items NT$34.59bn on NT$4,016.98bn, annualised) taxed at
the model rate; FY2026E EPS = 1Q-3Q26 reported + 4Q26E at guidance mid-points and spot FX.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import valuation_engine as ve

case = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "2330_case.json"), encoding="utf-8"))
fx = case["fx_quote_per_model"]
sh = case["shares_diluted_m"]
base = [s for s in case["scenarios"] if s["name"] == "Base"][0]
rows = ve.build_fcff(base["driver_build"], base["horizon_years"])
tax = base["driver_build"]["tax_rate"]

cash_usd_m = 4016.98e3 / fx            # 3Q26 cash & marketable securities, US$m
yld = 34.59 * 4 / 4016.98               # annualised 3Q26 non-operating / cash (proxy for interest yield)
div_ps_ntd = 24.0
price = case["price_quote"]

# FY2026E EPS: reported 1Q-3Q26 + 4Q26E (US$53.3bn x 31.8 guidance FX? use spot 32.478 for consistency)
q4_rev_ntd_bn = 53.30 * fx
q4_ebit = q4_rev_ntd_bn * 0.575
q4_pbt = q4_ebit + 34.59
q4_ni = q4_pbt * (1 - 0.1624)
q4_eps = q4_ni * 1000 / 25932
eps26 = 22.08 + 27.25 + 29.43 + q4_eps

out = []
out.append("| Base case, derived | FY2026E | FY2027E | FY2028E | FY2029E |")
out.append("|---|---|---|---|---|")
rev = [176120] + [r["revenue_m"] for r in rows[:3]]
ebit = [176120 * 0.5858] + [r["ebit_m"] for r in rows[:3]]
fcff = [None] + [r["fcff_m"] for r in rows[:3]]
eps = [eps26]
cash = cash_usd_m
for r in rows[:3]:
    ni = r["nopat_m"] + cash * yld * (1 - tax)
    eps.append(ni / sh * fx)
    cash += r["fcff_m"] - div_ps_ntd / fx * sh   # retain FCF after dividends
out.append("| Revenue (US$bn) | %s |" % " | ".join("%.1f" % (x / 1000) for x in rev))
out.append("| Revenue growth (USD) | %s |" % " | ".join(["+43.9%"] + ["%+.1f%%" % (r["revenue_growth"] * 100) for r in rows[:3]]))
out.append("| EBIT margin | %s |" % " | ".join(["58.6%"] + ["%.1f%%" % (r["ebit_margin"] * 100) for r in rows[:3]]))
out.append("| FCFF (US$bn) | n/a | %s |" % " | ".join("%.1f" % (x / 1000) for x in fcff[1:]))
out.append("| EPS (NT$, ours) | %s |" % " | ".join("%.1f" % x for x in eps))
out.append("| EPS (NT$, FactSet consensus median) | 109.21 | 145.69 | 185.61 | n/a |")
out.append("| Ours vs consensus | %+.1f%% | %+.1f%% | %+.1f%% | n/a |" % tuple((a / b - 1) * 100 for a, b in zip(eps, (109.21, 145.69, 185.61))))
out.append("| P/E at NT$%s (ours) | %s |" % (format(price, ","), " | ".join("%.1fx" % (price / x) for x in eps)))
out.append("| P/E at NT$%s (consensus) | %.1fx | %.1fx | %.1fx | n/a |" % (format(price, ","), price / 109.21, price / 145.69, price / 185.61))
print("\n".join(out))
print()
print("Inputs: 4Q26E EPS %.2f (revenue US$53.3bn x %.3f, EBIT margin 57.5%%, non-operating NT$34.59bn, tax 16.24%%); "
      "cash yield %.2f%% pre-tax; dividends NT$%.0f/share retained-cash deduction." % (q4_eps, fx, yld * 100, div_ps_ntd))
