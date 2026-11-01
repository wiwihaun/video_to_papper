# Valuation engines — schema, WACC, and when to use which

All arithmetic goes through `scripts/valuation_engine.py`. Do not compute a DCF in prose
or in your head: the engine is deterministic, so every figure in the report can be
reproduced from `reports/<TICKER>_case.json` by anyone who re-runs it.

## Commands

For a report, prefer `scripts/run_analysis.py --spec <spec.json>`, which runs all of the below
from one file and writes the numbers appendix. The engine commands remain available for
one-off checks.

| Command | Phase | Purpose |
|---|---|---|
| `elasticity` | 2 | Rank candidate drivers by the swing a 1σ move causes in value per share. |
| `reverse` | 4 | Solve for the driver value the current price implies. |
| `value` | 6 | Value every scenario; probability-weighted target price; model warnings. |
| `sensitivity` | 6 | 2-D grid of value per share over any two solvable drivers. |

`reverse` and `sensitivity` can move: `revenue_growth`, `ebit_margin`, `ebitda_margin`
(sets EBIT = EBITDA − the D&A path, so D&A changes only taxes), `terminal_growth`, `wacc`,
`fcff_scale`, `exit_multiple`, `hazard_rate`. `reverse --from-year N` keeps years
before N as given and solves only from year N on. `elasticity` can move **any numeric field**
by dotted path, including part of a path with a trailing slice
(`driver_build.revenue_growth[2:]`), which is what makes operating KPIs and growth duration
testable.

`value` also reports, per DCF scenario, the **terminal multiples implied** by the Gordon value
(EV/EBITDA, EV/EBIT, EV/FCFF), the **event-risk haircut** when a hazard is set, and, for the
case, the **equal-weighted value** used by the bias gate.

Exit code 2 with a message on stderr means the model is invalid (g ≥ WACC, weights not
summing to 1, missing driver, unsolvable bracket). Fix the input; do not work around it.

## Case schema

```jsonc
{
  "ticker": "2330.TW",
  "currency": "TWD",                // reporting currency of every *_m field
  "valuation_date": "2026-11-01",   // as-of date for price, shares, net debt
  "price": 1000.0,                  // spot, same currency
  "shares_diluted_m": 25930.0,      // diluted, millions
  "net_debt_m": -1500000.0,         // NEGATIVE = net cash (adds to equity)
  "minority_interest_m": 0.0,       // optional, deducted
  "wacc": 0.09,
  "terminal_growth": 0.025,
  "midyear": true,                  // mid-year discounting of explicit cash flows
  "scenarios": [ /* see below */ ]
}
```

Optional case fields:

```jsonc
  "quote_currency": "TWD",          // currency the stock is quoted in, if different
  "fx_quote_per_model": 32.478,     // quote units per 1 model unit (TWD per USD)
  "price_quote": 2370,              // spot in the quote currency (replaces "price")
  "adr_ratio": 5,                   // shares per ADR: adds value per ADR to the output
  "hazard": {"annual_probability": 0.015, "loss_fraction": 0.8},  // event-risk overlay
  "roll_forward": {"quote_rf": 0.0199, "model_rf": 0.0494,         // 12-month target price:
                   "dividends_quote_next_12m": 24.0}               // FV x (1 + r_quote) - dividends
```

With `roll_forward`, `value` also reports `target_price_12m_quote`, `target_upside_pct` and
`expected_total_return_12m_pct`; with `"basis": "model"` the roll-forward uses the model-currency
cost of equity at spot FX (no currency forecast — the default), and with `adr_ratio` it reports an
ADR target assuming the ADR premium closes. With `"rating_thresholds": {"buy": 0.15, "sell":
-0.15}` it also returns the mechanical rating and the buy/sell price triggers. `r_quote` is derived from WACC by interest-rate parity —
`(1 + WACC)(1 + quote_rf)/(1 + model_rf) − 1` — so it stays consistent when WACC is varied;
or give `cost_of_equity_quote` directly.

Any of `wacc`, `net_debt_m`, `shares_diluted_m`, `price`, `minority_interest_m`, `hazard` can
be overridden per scenario. `other_adjustments_m` on a scenario is **added** to equity — use it
for associates, investments and non-operating assets, with a positive sign.

### DCF scenario

```jsonc
{
  "name": "Base", "probability": 0.5, "method": "dcf",
  "horizon_years": 10,
  "driver_build": {
    "revenue_base_m": 3800000,       // last reported full year, the base for year 1
    // ONE of the three revenue forms:
    "revenue_growth": 0.14,          // scalar (flat) or a list per year
    // "revenue_m": [ ... ],         // explicit path
    // "units": [...], "unit_price": [...], "unit_scale": 1.0,   // KPI build
    "ebit_margin": 0.45,             // scalar or list
    "tax_rate": 0.15,
    "da_pct_revenue": 0.18,
    "capex_pct_revenue": 0.30,
    "nwc_pct_delta_revenue": 0.05,   // NWC investment per unit of revenue CHANGE
    "sbc_pct_revenue": 0.0           // expensed, never added back
  },
  "terminal": {"mode": "gordon", "terminal_growth": 0.025}
  // or {"mode": "exit_multiple", "metric_name": "ebitda", "multiple": 12}
  // metric_name: ebitda | ebit | fcff | revenue | nopat — or supply metric_m directly
}
```

`fcff_m: [..]` may replace `driver_build` when FCFF comes from a separate model; the engine
then cannot show the FCFF build, so prefer `driver_build`.

FCFF = EBIT × (1 − t) + D&A − Capex − ΔNWC − SBC. Explicit cash flows use mid-year
discounting by default; the terminal value is always discounted at the full year N.

### SOTP scenario

```jsonc
{
  "name": "Bull", "probability": 0.25, "method": "sotp",
  "segments": [
    {"name": "Foundry core", "method": "dcf", "horizon_years": 8,
     "driver_build": { ... }, "terminal": { ... }},
    {"name": "Advanced packaging", "method": "multiple",
     "metric_name": "EBITDA", "metric_m": 120000, "multiple": 14},
    {"name": "Equity stakes", "method": "value", "value_m": 90000, "stake": 1.0},
    {"name": "New venture (option)", "method": "value", "value_m": 300000,
     "probability_of_success": 0.15}
  ]
}
```

Each segment: attributable value = gross × `probability_of_success` × `stake`. A segment
`dcf` uses the case WACC unless it sets its own — set its own when its risk differs
(a venture pool should not be discounted at the core business's WACC).

### Multiple scenario

`{"method": "multiple", "metric_name": "EBITDA", "metric_m": ..., "multiple": ...}` — an
EV multiple. For an equity multiple (P/E, P/B), value per share directly in the report and
do not run it through the EV bridge.

## Choosing the method

| Situation | Primary | Cross-check |
|---|---|---|
| One pool is >70% of value and cash-generative | DCF | EV/EBITDA or P/E vs history and peers |
| Several pools with different economics or risk | SOTP | Group DCF |
| Option pools (unlaunched products, pipelines, ventures) | SOTP with `probability_of_success` | Reverse DCF on core alone: what is the market paying for the options? |
| Banks, insurers, financial holding companies (e.g. 2881, 2882, 2891) | `residual_income` (excess return on book) | Justified P/B = (ROE − g)/(COE − g); dividend discount |
| Deep cyclicals (memory, shipping, commodities) | Mid-cycle normalised earnings × mid-cycle multiple | DCF with cycle in the explicit forecast |
| Holding companies | NAV with look-through, minus a justified discount | Historical discount range |

For financials the FCFF framework does not apply — debt is raw material, not financing.
Use the `residual_income` method, which values equity directly:

```jsonc
{
  "name": "Base", "probability": 0.5, "method": "residual_income",
  "book_value_m": 1250000,          // equity attributable to shareholders, latest balance sheet
  "roe": [0.11, 0.115, 0.12, 0.12, 0.12, 0.115, 0.11, 0.11, 0.11, 0.11],
  "payout_ratio": 0.6,              // scalar or path; book grows by retained earnings
  "horizon_years": 10
  // cost_of_equity (else wacc) and terminal_growth come from the case
}
```

Residual income_t = (ROE_t − COE) × opening book value; terminal = next-year residual income
/ (COE − g). Net debt is ignored by construction. With constant ROE and a payout that grows
book at g, it reproduces the justified P/B exactly (tested). The two numbers for a financial
are usually **through-cycle ROE** (net interest margin × leverage, less credit cost) and
**book-value growth** (payout policy and capital requirements) — test them with
`elasticity --driver "ROE@roe=0.015" --driver "Payout@payout_ratio=0.1"`. For a life insurer,
read ROE through IFRS 17: contractual service margin release and investment spread, and the
hedging cost of the FX book.

## WACC

Build it every time; never import a third party's WACC without its components.

| Component | Source | Notes |
|---|---|---|
| Risk-free rate | 10-year government bond yield **in the cash-flow currency**, on the valuation date | TWD cash flows → Taiwan 10Y; USD cash flows → US 10Y |
| Equity risk premium | Damodaran's implied ERP (updated monthly) + country risk premium for the domicile | Cite the month used |
| Beta | Bottom-up: unlevered industry beta, relevered at the target D/E | Regression beta as cross-check; state window and index |
| Cost of debt | Yield on the company's bonds, or rating-implied spread over rf | After tax |
| Weights | Market values of equity and debt | Target structure if current is temporary |

**Model in the economic currency.** Choose the currency the business earns in, not the one it
reports in. A company that prices in USD and reports in TWD (TSMC, most Taiwan tech exporters)
should be modelled in USD, discounted at a USD rate, and converted per share at spot FX.

The trap this avoids: discounting at a TWD rate (Taiwan 10Y ~1.5–2%) while converting USD
cash flows at today's FX. Under interest-rate parity, a ~3pp lower TWD rate is the market's
forecast that TWD appreciates ~3% a year against USD; a TWD DCF that takes the low rate but
keeps FX flat books that ~3pp twice — compounded over a terminal-value horizon, that is tens
of percent of value. Either model in USD, or model in TWD with forward FX. Never mix.

**Currency consistency is the most common fatal error.** Cash flows, WACC, terminal growth
and net debt must all be in one currency. A TWD forecast discounted at a USD WACC overstates
the discount rate by roughly the inflation differential and understates value. If the
ADR is the line being priced, value in the reporting currency and convert the per-share
result at spot FX and the ADR ratio — do not convert the cash flows.

## Terminal value discipline

- Terminal growth ≤ long-run nominal GDP growth of the currency (rule of thumb: ~3% USD,
  ~2–2.5% TWD). The engine warns above 3.5%.
- If PV of the terminal value exceeds 75% of EV the engine warns: the forecast is not
  doing the work. Extend the horizon until growth has faded to the terminal rate, and
  cross-check with an exit multiple.
- Gordon and exit multiple should agree within reason. Back out the multiple implied by
  the Gordon value and state it: "our terminal value implies 14x terminal EBITDA versus a
  10-year sector median of 11x."

## Event-risk overlay (`hazard`)

For a discrete jump risk — war or blockade, expropriation, a binary regulatory event — set
`"hazard": {"annual_probability": h, "loss_fraction": L}`. Each year the event occurs with
probability h; once it does, operating cash flows are cut by L for good. The expected
multiplier on the cash flow at time t is `(1 − L) + L(1 − h)^t`, and the terminal value uses
the closed form of the same series. Net cash is left outside the overlay (stated assumption).

Properties worth knowing, all covered by tests:

- With L = 1 the overlay equals discounting at `(1 + WACC)/(1 − h) − 1`. A country-risk premium
  of ~0.8pp is therefore an implicit ~0.8% a year probability of total loss. Use the overlay
  **or** a CRP, never both.
- `reverse --solve-for hazard_rate` returns the event probability the price implies, given
  your operating case.
- `"years": N` inside `hazard` confines new events to the first N years (the terminal value then
  carries survival to year N only). A perpetual hazard charges far more than "N% over a decade"
  suggests — in 2330 about half the event-risk cost sat after year 10 — so show both. That converts a valuation gap into a number a PM can hold a view on.
- External anchors for h: prediction-market prices (a long-dated "Yes" price overstates the
  probability by roughly the carry cost of holding "No" — at 5% rates, ~5pp a year), Good
  Judgment superforecasts, Metaculus, and expert surveys such as CSIS. Cite date and source.

## Reverse DCF in practice

Solve for **each** Phase 2 number in turn, holding the others at the neutral base:

```bash
python3 scripts/valuation_engine.py reverse --input reports/2330_case.json --scenario Base --solve-for revenue_growth
python3 scripts/valuation_engine.py reverse --input reports/2330_case.json --scenario Base --solve-for ebit_margin
```

Take consensus for the visible years and solve for the rest:

```bash
python3 scripts/valuation_engine.py reverse --input reports/2330_case.json --scenario Base \
  --solve-for revenue_growth --from-year 3
```

If the bracket fails ("no solution"), the price cannot be reconciled by that driver alone
within a plausible range. That is a finding: report it as "no plausible value of X alone
justifies the price; the market must also be assuming Y."

For ADRs or per-share targets in another currency, pass `--price` in the case currency.
