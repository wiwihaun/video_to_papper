# Phase 2 — Driver isolation: finding the two numbers

The question this phase answers: **if you could know only one or two facts about this
company five years from now, which would you choose to know?** Those are the numbers.
Everything else is noise, and the report must say so in writing.

## What qualifies as a driver

A candidate must pass all four tests. Failing any one disqualifies it.

| Test | Question | Fails when… |
|---|---|---|
| **Elastic** | Does a plausible 1σ move shift value per share materially? | It is salient in the news but moves fair value <3%. |
| **Observable** | Is it published on a schedule — filing, monthly sales, regulator dataset, company KPI? | Nobody outside the company can measure it. That is a narrative; it goes in Risks. |
| **Forecastable** | Can you form a view with an evidence trail, not a guess? | The honest forecast is "no idea" — then it is a risk factor, not a driver. |
| **Primary** | Is it a cause, not an output of something else on the list? | It is a ratio of two other candidates, or a valuation output such as P/E. |

## The elasticity test

Do not rank drivers by intuition. Rank them with the engine.

1. Build a neutral base case in `reports/<TICKER>_case.json` (structure only; no view yet).
2. For each candidate, set **σ** to a plausible one-standard-deviation annual move. Source σ
   from the company's own history (stdev of the annual change over 5–10 years), from
   analyst dispersion, or from the range of management guidance. Write down where σ came
   from — an unsourced σ quietly decides the ranking.
3. Run:

```bash
python3 scripts/valuation_engine.py elasticity --input reports/<TICKER>_case.json \
  --scenario Base --markdown \
  --driver "Leading-edge wafer volume@driver_build.units=0.12:rel" \
  --driver "Blended ASP@driver_build.unit_price=0.06:rel" \
  --driver "EBIT margin@driver_build.ebit_margin=0.03" \
  --driver "Capex intensity@driver_build.capex_pct_revenue=0.03" \
  --driver "WACC@wacc=0.005"
```

The output ranks drivers by swing in value per share, gives each one's share of the
tested variance, and returns a verdict:

| Top-two variance share | Verdict | What the report does |
|---|---|---|
| ≥ 70% | Clean two-number stock | Report is built around the two. |
| 50–70% | Two numbers lead, residual is material | Lead with the two, and name the third explicitly. |
| < 50% | **Not a two-number stock** | Say so on page one. Do not force the frame. |

The third row is a legitimate finding, not a failure. Diversified conglomerates, holding
companies and early-stage businesses often have no dominant driver, and claiming two numbers
for them would be false precision.

**Test operating drivers only.** Leave WACC, terminal growth and event risk out of the
ranking: they are valuation parameters that no data release reveals, and their large swings
would push the business's real drivers off the list. They belong in the WACC × g grid and the
event-risk overlay.

**Split growth into near-term and duration** with path slices
(`driver_build.revenue_growth[0:2]` vs `driver_build.revenue_growth[2:]`). Report whichever
way it comes out — but only with sourced σ's. In the 2330 run (2026-11-01) a placeholder σ of
±6pp on 2027–28 growth made duration look three times as important as the near term; once σ
was anchored on TSMC's own history (annual USD growth SD 15.2pp → ±10pp given partial
visibility) the two were about equal (35% vs 33% of variance). The "finding" was an artefact
of the σ. Merge the two into one growth driver for the final two-number verdict, and use the
split only to say which part of the growth debate carries the value.

**Calibrating σ.** σ is the uncertainty of the *forecast quantity*, which is usually smaller
than a driver's annual volatility and larger than analysts' dispersion:

| Driver type | Anchor for σ |
|---|---|
| Next 1–2 years' growth | Historical one-year forecast error, or the gap between guidance/consensus and the last downturn's print |
| Growth duration (years 3+) | Spread of credible long-run views (industry growth vs bull case), as ± around your base |
| Through-cycle margin | Half the gap between the current level and the 10-year average, or management's floor vs current |
| Capex intensity | Range of the last cycle (peak vs trough capex/revenue), halved |

Write the anchor next to each σ in the report.

**Test at least five candidates.** With fewer than three the engine refuses to call a
verdict, because a ranking of two is not a test.

**Merge correlated drivers before ranking.** Revenue growth and operating leverage usually
move together; testing both independently double-counts. Express them as one driver
(e.g. "volume", which mechanically drives both through the build) or the variance shares
are overstated.

## Make the drivers operating KPIs where possible

Accounting lines — "revenue growth", "EBIT margin" — are outputs. The better number is
the operating quantity that produces them, because it is what gets published monthly and
what the market reacts to. The `units` × `unit_price` revenue build in the engine is
there so a KPI can be the driver directly (illustrative numbers, not a forecast):

```json
"driver_build": {
  "revenue_base_m": 2894000,
  "units":      [16.1, 17.8, 19.6, 21.2, 22.9],
  "unit_price": [195000, 206000, 216000, 225000, 233000],
  "unit_scale": 1.0
}
```

Then `--driver "Wafer volume@driver_build.units=0.12:rel"` tests the KPI itself.
Units, prices and scale are yours to define — make the product equal revenue in millions
of the reporting currency, and state the definition in the report.

## Starting hypotheses by business model

This table **generates candidates; it does not choose them.** The elasticity test chooses.
Where the test disagrees with this table, the test wins and the disagreement is worth a
sentence in the report.

| Business model | Usual first candidate | Usual second candidate | Where it is observed |
|---|---|---|---|
| Foundry (TSMC 2330, UMC 2303) | Leading-edge / advanced-packaging revenue (wafer volume × ASP) | Gross margin (utilisation, node mix, FX) | Monthly revenue (TW: by the 10th); quarterly node mix; guidance |
| Memory (Micron, Nanya 2408) | Contract ASP (DRAM/NAND) | Bit shipment growth | TrendForce contract prices; quarterly bit growth |
| Fabless / IC design (MediaTek 2454) | Flagship SoC share / content per device | Gross margin | Monthly revenue; customer launch cycles |
| EMS / server ODM (Hon Hai 2317, Quanta 2382) | AI-server rack volume | Operating margin (mix) | Monthly revenue; hyperscaler capex guidance |
| EV + autonomy (Tesla) | Autonomy KPI — FSD-supervised miles / robotaxi fleet and paid miles | Auto gross margin ex-credits | Quarterly deliveries and update letter; regulator filings |
| Banks | Net interest margin | Credit cost | Quarterly results; central-bank rate path |
| Life insurers | New business value / CSM growth | Investment yield vs guaranteed rate | IFRS 17 disclosures; FX hedging cost |
| SaaS / software | Net revenue retention | FCF margin (rule of 40) | Quarterly KPIs |
| Consumer / retail | Same-store sales growth | Gross margin | Monthly or quarterly comps |
| Container shipping (Evergreen 2603) | Freight rate (SCFI/CCFI) | Fleet supply growth / utilisation | Weekly index; orderbook |
| Pharma / biotech | Probability of approval | Peak sales | Trial readouts; regulator calendar |
| REITs / property | Occupancy and rental reversion | Cap rate | Quarterly leasing; transaction comps |
| Commodity producers | Realised price | Cash cost per unit | Spot and futures; quarterly cost disclosure |
| Holding companies | NAV of the largest holding | Discount to NAV | Look-through; listed subsidiaries |

## Writing the noise list

The noise list is a required section of the report. Include the items readers *expect* to
see discussed — the ones in the news, in the earnings call Q&A, in competitor notes — and
dismiss each with a number:

| Item | Why the market watches it | Elasticity (1σ) | Why it does not set the value |
|---|---|---|---|
| Quarterly gross margin beat/miss | Headline on results day | ±2.1% | Inside the error of the terminal assumption; mean-reverts within a year |
| Tax rate changes | Policy headlines | ±3.3% | Real but bounded; does not compound |
| [item] | [reason] | [engine output] | [one line, quantitative] |

"Not material" is not a dismissal. A number is.

Some noise is short-term **price** noise and long-term **value** noise at once. Say which.
An item that moves the stock 8% on results day while moving fair value 1% is noise for
this method, and is also exactly why the method finds mispricings — so it belongs in the
catalysts section as well, flagged as a trading event rather than a value event.

## Failure modes

1. **Salience over elasticity.** The most-discussed topic is often the least
   value-relevant. Let the engine decide.
2. **Picking an input of the driver.** "Number of fabs" is an input to wafer volume.
   Forecast the volume; the fab count is evidence for it.
3. **Picking an output.** P/E, EV/EBITDA and dividend yield are results of the
   valuation, not drivers of it.
4. **An unmeasurable driver.** "Technology leadership" cannot be tracked. Translate it
   into what it produces — share of leading-edge revenue, pricing premium versus peers —
   or move it to risks.
5. **Stale σ.** A σ taken from a calm decade understates a cyclical driver. Use a window
   that includes a downturn.
6. **Correlated pair counted twice.** See above. Merge before ranking.
7. **Forcing two.** If the test says the stock is multi-driver, the report says so.
