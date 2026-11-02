#!/usr/bin/env python3
"""
Derived financial summary for the 2330 report: ten years of sourced history (FY2015-25, TSMC
4Q management reports) beside the Base scenario of reports/2330_case.json. Run:
    python3 reports/2330_financials.py > reports/2330_financials.md

FY2026E = 1Q-3Q26 reported (SEC 6-K releases and the 2Q26 consolidated report) + 4Q26 at the
guidance mid-points (US$53.3bn, OPM 57.5%, at the guidance FX of 31.8). FY2026E D&A: 1Q-3Q26
reported plus 4Q26 between flat and +10% QoQ (management guided 2026 depreciation up a
"high-teens percentage", 4Q25 call, 2026-01-15).
EPS forecasts add after-tax interest income on cash and marketable securities at 3.44%
pre-tax (3Q26 non-operating items NT$34.59bn on NT$4,016.98bn, annualised), taxed at the
model rate; cash accumulates FCFF less NT$24/share dividends.
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

# ---- FY2026E from reported quarters (NT$bn) ----
q_rev = [1134.10, 1270.38, 1494.24]                 # 1Q26, 2Q26, 3Q26 net revenue
q_oi = [1425.57 - 766.60, 766.60, 1494.24 * 0.587]  # 1H26 and 2Q26 income from operations; 3Q26 OPM 58.7%
q_da = [584.19 - 198.54 - 220.20, 198.54, 220.20]   # 9M26 D&A 584.19; 2Q 198.54; 3Q 220.20
q4_rev = 53.30 * 31.8
q4_oi = q4_rev * 0.575
rev26_nt = sum(q_rev) + q4_rev
opm26 = (sum(q_oi) + q4_oi) / rev26_nt
da26_lo, da26_hi = sum(q_da) + q_da[2], sum(q_da) + q_da[2] * 1.10
ebitda26_lo, ebitda26_hi = opm26 + da26_lo / rev26_nt, opm26 + da26_hi / rev26_nt
ebitda_9m = (sum(q_oi) + sum(q_da)) / sum(q_rev)
q4_eps = (53.30 * fx * 0.575 + 34.59) * (1 - 0.1624) * 1000 / 25932
eps26 = 22.08 + 27.25 + 29.43 + q4_eps

eps = []
for r in rows[:3]:
    eps.append((r["nopat_m"] + cash * yld * (1 - tax)) / sh * fx)
    cash += r["fcff_m"] - 24.0 / fx * sh

# FY: rev US$bn, USD growth %, GM, OPM, D&A/NT$ rev, capex/rev (US$), FCF/NT$ rev (TSMC def.), EPS NT$
hist = {
    "FY2015A": (26.61, 5.7, 48.7, 37.9, 26.4, 30.5, 32.3, 11.82),
    "FY2016A": (29.43, 10.6, 50.1, 39.9, 23.6, 34.6, 22.3, 12.89),
    "FY2017A": (32.11, 9.1, 50.6, 39.4, 26.6, 33.8, 26.1, 13.23),
    "FY2018A": (34.20, 6.5, 48.3, 37.2, 28.4, 30.6, 25.0, 13.54),
    "FY2019A": (34.63, 1.3, 46.0, 34.8, 26.8, 43.0, 14.5, 13.32),
    "FY2020A": (45.51, 31.4, 53.1, 42.3, 24.8, 37.9, 23.6, 19.97),
    "FY2021A": (56.82, 24.9, 51.6, 40.9, 26.6, 52.9, 17.2, 23.01),
    "FY2022A": (75.88, 33.5, 59.6, 49.5, 19.3, 47.8, 23.3, 39.20),
    "FY2023A": (69.30, -8.7, 54.4, 42.6, 24.6, 43.9, 13.5, 32.34),
    "FY2024A": (90.08, 30.0, 56.1, 45.7, 22.9, 33.0, 30.1, 45.25),
    "FY2025A": (122.42, 35.9, 59.9, 50.8, 18.1, 33.4, 26.3, 66.25),
}
L = ["| 年度 | 營收（US$ 十億） | 美元成長 | 毛利率 | 營業利益率 | EBITDA 利潤率 | 資本支出／營收 | 自由現金流利潤率（歷史 FCF／預估 FCFF） | EPS（NT$） |",
     "|---|---|---|---|---|---|---|---|---|"]
for y, h in hist.items():
    L.append("| %s | %.2f | %+.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%%（FCF） | %.2f |"
             % (y, h[0], h[1], h[2], h[3], h[3] + h[4], h[5], h[6], h[7]))
L.append("| FY2026E | 176.12 | +43.9%% | 66.2/67.7/66.4%%（1–3Q）；4Q 指引 66%% | %.1f%% | %.1f–%.1f%%（1–3Q 實際 %.1f%%） | 約 35%%（指引 600–640 億美元） | — | %.1f |"
         % (opm26 * 100, ebitda26_lo * 100, ebitda26_hi * 100, ebitda_9m * 100, eps26))
for i, r in enumerate(rows[:3]):
    L.append("| FY%dE | %.1f | %+.1f%% | — | %.1f%% | %.1f%% | %.1f%% | %.1f%%（FCFF） | %.1f |"
             % (2027 + i, r["revenue_m"] / 1000, r["revenue_growth"] * 100, r["ebit_margin"] * 100,
                (r["ebit_m"] + r["da_m"]) / r["revenue_m"] * 100, r["capex_m"] / r["revenue_m"] * 100,
                r["fcff_m"] / r["revenue_m"] * 100, eps[i]))
r = rows[-1]
L.append("| FY2036E | %.1f | %+.1f%% | — | %.1f%% | %.1f%% | %.1f%% | %.1f%%（FCFF） | — |"
         % (r["revenue_m"] / 1000, r["revenue_growth"] * 100, r["ebit_margin"] * 100,
            (r["ebit_m"] + r["da_m"]) / r["revenue_m"] * 100, r["capex_m"] / r["revenue_m"] * 100,
            r["fcff_m"] / r["revenue_m"] * 100))
print("\n".join(L))
print()
H = list(hist.values())
ebitda_hist = [h[3] + h[4] for h in H]
mean = sum(ebitda_hist) / len(ebitda_hist)
sd = (sum((x - mean) ** 2 for x in ebitda_hist) / (len(ebitda_hist) - 1)) ** 0.5
print("FY2015-25 EBITDA margin: mean %.1f%%, SD %.2fpp, range %.1f-%.1f%%. Capex/revenue mean %.1f%%, min %.1f%%. "
      "FCF margin (TSMC definition, CFO - capex) mean %.1f%%, range %.1f-%.1f%%."
      % (mean, sd, min(ebitda_hist), max(ebitda_hist), sum(h[5] for h in H) / len(H), min(h[5] for h in H),
         sum(h[6] for h in H) / len(H), min(h[6] for h in H), max(h[6] for h in H)))
print()
L = ["| | FY2026E | FY2027E | FY2028E |", "|---|---|---|---|"]
L.append("| EPS（NT$，我們） | %.1f | %.1f | %.1f |" % (eps26, eps[0], eps[1]))
L.append("| EPS（NT$，FactSet 共識中位數） | 109.21 | 145.69 | 185.61 |")
L.append("| 我們 vs 共識 | %+.1f%% | %+.1f%% | %+.1f%% |" % ((eps26 / 109.21 - 1) * 100, (eps[0] / 145.69 - 1) * 100, (eps[1] / 185.61 - 1) * 100))
L.append("| 本益比（NT$%s，我們的 EPS） | %.1f 倍 | %.1f 倍 | %.1f 倍 |" % (format(price, ","), price / eps26, price / eps[0], price / eps[1]))
L.append("| 本益比（NT$%s，共識 EPS） | %.1f 倍 | %.1f 倍 | %.1f 倍 |" % (format(price, ","), price / 109.21, price / 145.69, price / 185.61))
print("\n".join(L))
print()
print("FY2015-25: TSMC 4Q management reports (EBITDA = OPM + D&A / NT$ revenue; FCF = CFO - capex, TSMC definition, / NT$ revenue). "
      "FY2026E: 1Q-3Q26 reported + 4Q26 guidance mid-points; EBITDA range from 4Q26 D&A flat to +10%% QoQ. "
      "FY2027E onward: Base scenario (FCFF = model free cash flow to the firm, / US$ revenue). "
      "4Q26E EPS %.2f; cash yield %.2f%%; NTM EPS (ours) %.1f, (consensus) %.1f; FY2026E OPM %.2f%%."
      % (q4_eps, yld * 100, 2 / 12 * eps26 + 10 / 12 * eps[0], 2 / 12 * 109.21 + 10 / 12 * 145.69, opm26 * 100))
