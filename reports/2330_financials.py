#!/usr/bin/env python3
"""
Derived financial summary for the 2330 report — sourced actuals (FY2023-25, TSMC 4Q
management reports) beside the Base scenario of reports/2330_case.json. Run:
    python3 reports/2330_financials.py > reports/2330_financials.md
Assumptions (stated in the report): EPS forecasts add after-tax interest income on cash and
marketable securities at 3.44% pre-tax (3Q26 non-operating items NT$34.59bn on NT$4,016.98bn,
annualised) taxed at the model rate; cash accumulates FCFF less NT$24/share dividends.
FY2026E: revenue = 1Q-3Q26 reported + 4Q26 guidance mid-point; EPS = reported 1Q-3Q26 +
4Q26E at the guidance mid-points and spot FX.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import valuation_engine as ve

case = json.load(open(os.path.join(HERE, "2330_case.json"), encoding="utf-8"))
fx, sh = case["fx_quote_per_model"], case["shares_diluted_m"]
base = [s for s in case["scenarios"] if s["name"] == "Base"][0]
rows = ve.build_fcff(base["driver_build"], base["horizon_years"])
tax = base["driver_build"]["tax_rate"]
cash = 4016.98e3 / fx
yld = 34.59 * 4 / 4016.98
price = case["price_quote"]

# FY2026E EPS
q4_eps = (53.30 * fx * 0.575 + 34.59) * (1 - 0.1624) * 1000 / 25932
eps26 = 22.08 + 27.25 + 29.43 + q4_eps

eps = []
for r in rows[:3]:
    eps.append((r["nopat_m"] + cash * yld * (1 - tax)) / sh * fx)
    cash += r["fcff_m"] - 24.0 / fx * sh

hist = {  # FY: (rev US$bn, growth, GM, OPM, D&A/rev (NT$ basis), capex US$bn, FCF/rev (NT$), EPS NT$)
    "FY2023A": (69.30, -8.7, 54.4, 42.6, 24.6, 30.45, 13.5, 32.34),
    "FY2024A": (90.08, 30.0, 56.1, 45.7, 22.9, 29.76, 30.1, 45.25),
    "FY2025A": (122.42, 35.9, 59.9, 50.8, 18.1, 40.90, 26.3, 66.25),
}
cols = list(hist) + ["FY2026E", "FY2027E", "FY2028E", "FY2029E"]
L = ["| | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
def row(label, vals): L.append("| " + label + " | " + " | ".join(vals) + " |")
rev26 = 176.12
row("營收 Revenue (US$bn)", ["%.2f" % h[0] for h in hist.values()] + ["%.1f" % rev26] + ["%.1f" % (r["revenue_m"] / 1000) for r in rows[:3]])
row("美元營收成長 Growth (USD)", ["%+.1f%%" % h[1] for h in hist.values()] + ["+43.9%"] + ["%+.1f%%" % (r["revenue_growth"] * 100) for r in rows[:3]])
row("毛利率 GM", ["%.1f%%" % h[2] for h in hist.values()] + ["66–67%（1Q–3Q 實際，4Q 指引）", "—", "—", "—"])
row("營業利益率 EBIT margin", ["%.1f%%" % h[3] for h in hist.values()] + ["58.6%"] + ["%.1f%%" % (r["ebit_margin"] * 100) for r in rows[:3]])
row("EBITDA 利益率", ["%.1f%%" % (h[3] + h[4]) for h in hist.values()] + ["約 74%"] + ["%.1f%%" % ((r["ebit_m"] + r["da_m"]) / r["revenue_m"] * 100) for r in rows[:3]])
row("資本支出 Capex (US$bn)", ["%.2f" % h[5] for h in hist.values()] + ["60–64（指引）"] + ["%.1f" % (r["capex_m"] / 1000) for r in rows[:3]])
row("資本支出／營收", ["%.1f%%" % (h[5] / h[0] * 100) for h in hist.values()] + ["約 35%"] + ["%.1f%%" % (r["capex_m"] / r["revenue_m"] * 100) for r in rows[:3]])
row("自由現金流利益率 FCF margin", ["%.1f%%" % h[6] for h in hist.values()] + ["—"] + ["%.1f%%" % (r["fcff_m"] / r["revenue_m"] * 100) for r in rows[:3]])
row("EPS（NT$，實際／我們）", ["%.2f" % h[7] for h in hist.values()] + ["%.1f" % eps26] + ["%.1f" % x for x in eps])
row("EPS（NT$，FactSet 共識中位數）", ["", "", "", "109.21", "145.69", "185.61", "n/a"])
row("我們 vs 共識", ["", "", "", "%+.1f%%" % ((eps26 / 109.21 - 1) * 100), "%+.1f%%" % ((eps[0] / 145.69 - 1) * 100), "%+.1f%%" % ((eps[1] / 185.61 - 1) * 100), "n/a"])
row("本益比（NT$%s，我們的 EPS）" % format(price, ","), ["", "", "", "%.1fx" % (price / eps26)] + ["%.1fx" % (price / x) for x in eps])
row("本益比（NT$%s，共識 EPS）" % format(price, ","), ["", "", "", "%.1fx" % (price / 109.21), "%.1fx" % (price / 145.69), "%.1fx" % (price / 185.61), "n/a"])
print("\n".join(L))
print()
print("FY2023-25: TSMC 4Q management reports (EBITDA = OPM + D&A/revenue, NT$ basis; FCF = CFO - capex, TSMC definition). "
      "Forecasts: Base scenario. 4Q26E EPS %.2f; cash yield %.2f%%; NTM EPS (ours) %.1f, (consensus) %.1f."
      % (q4_eps, yld * 100, 2 / 12 * eps26 + 10 / 12 * eps[0], 2 / 12 * 109.21 + 10 / 12 * 145.69))
