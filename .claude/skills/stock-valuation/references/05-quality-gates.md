# Phase 9 — Quality gates

Run this before delivering. **Every box is blocking.** An unchecked box is either fixed or
disclosed in the report's limitations section, by name. There is no third option.

## A. Integrity

- [ ] Every figure has a source-log entry with an as-of date, or is labelled as our estimate.
- [ ] No consensus figure, price, share count or KPI was estimated and presented as sourced.
- [ ] One spot price and one as-of date are used throughout, and both appear in the header.
- [ ] Shares are **diluted**, and consistent across the case JSON, the per-share figures and
      the market cap. ADR ratio and FX are applied if an ADR value is quoted.
- [ ] **Stale price**: if an ADR or other line traded after the local close, the implied local
      price is stated and upside is shown from both.
- [ ] Units are consistent: everything in the case JSON is in millions of one currency.
      (Taiwan statements are in NT$ thousands; summaries often use 億. Check the conversion.)

## B. Method — the two-numbers discipline

- [ ] `elasticity` was run on **at least five** candidate *operating* drivers (no WACC, no
      terminal growth, no hazard in the ranking), and each σ has a stated source.
- [ ] Growth was tested split by period (near-term vs duration), and the report says which
      matters more.
- [ ] The engine's verdict is reported verbatim, including when it says "not a two-number
      stock".
- [ ] The noise list is present, and each item carries a numeric elasticity.
- [ ] The reverse DCF was run **before** our own forecast, and its result is in section 3.
- [ ] Bull / Base / Bear differ in the isolated drivers. Any other assumption that differs
      across scenarios is listed and justified.
- [ ] Each probability weight has a one-line justification.

## C. Arithmetic

- [ ] **Currency consistency**: cash flows, WACC (risk-free rate), terminal growth and net
      debt are all in the same currency — and that currency is the business's *economic*
      currency, or the forecast uses forward FX.
- [ ] **Event risk counted once**: either a hazard overlay or a country-risk premium, not
      both. If a hazard is used, its probability is compared with dated external anchors **after
      annualising them**: annual = 1 − (1 − p)^(1/years); for prediction markets also subtract the
      carry cost of holding "No". Describe the chosen rate's position (low end / middle / high end)
      consistently everywhere in the report.
- [ ] **Dates match inside the cost of equity**: an implied ERP is paired with the risk-free rate
      it was solved against, or re-derived by holding the implied market return constant.
- [ ] Terminal growth < WACC, and ≤ long-run nominal GDP for the currency, or argued.
- [ ] Every engine warning is resolved or explained in section 5.5.
- [ ] Net-debt sign: net cash is entered as a **negative** `net_debt_m`, so it adds to equity.
- [ ] Leases: if EBIT is post-IFRS 16 / ASC 842 (lease cost below EBIT), lease liabilities
      are in net debt. If not, they are not. Never both, never neither.
- [ ] Minority interests deducted; associates and non-operating investments added through
      `other_adjustments_m`.
- [ ] No double counting: a value pool appears in exactly one place — not inside the core
      DCF *and* as a separate SOTP line.
- [ ] SBC is expensed (the engine does this; check that `sbc_pct_revenue` is set, not zero
      by omission, for issuers with material equity compensation).
- [ ] DCF and the multiples cross-check agree within ~25%, or the gap is reconciled in prose.
- [ ] **Consensus bridge**: if consensus publishes a target price, the gap to it is decomposed
      assumption by assumption with engine re-runs, with an order-independent (Shapley) attribution
      beside the sequential one (`"shapley": true` in the spec). The "consensus-like" operating set
      reproduces consensus EPS (calibrate margins to it); a set that undershoots consensus EPS loads
      the residual onto the discount rate.
- [ ] **Rating flip points are disclosed**: the input values at which the rating changes (solved in
      the spec), and the buy/sell price triggers the engine reports.
- [ ] **Like-for-like comparisons**: fair value is compared with spot; a 12-month target price
      is compared with a 12-month target price (never fair value vs a consensus target).
- [ ] **Target price is rolled forward**: the 12-month TP = fair value x (1 + quote-currency
      cost of equity) - dividends, and the rating uses it.
- [ ] The Gordon terminal value's implied exit multiple is stated and is plausible against
      sector history.

## C2. Economic coherence (added after the 2330 review)

- [ ] **Margins are cash margins.** When D&A intensity changes over the forecast, drive the margin
      as EBITDA and set EBIT = EBITDA − D&A (`ebitda_margin` driver). A falling EBIT margin with a
      rising D&A ratio can leave cash margins at a record — the 2330 v1 "normalisation" was exactly
      that, and it was invisible until the EBITDA and FCF margins were tabulated.
- [ ] **EBITDA margin, FCF margin and capex intensity are shown beside 10 years of history**, and
      any forecast outside the historical range is argued, not just assumed.
- [ ] **Growth costs capital.** A scenario with faster growth carries higher capex intensity; the
      terminal reinvestment rate is consistent with g / RONIC, and the implied RONIC is stated.
- [ ] **Falsifiers sit where Base and Bull diverge.** A tripwire that the Base case itself satisfies
      falsifies nothing.

## D. Bias

- [ ] **Anchoring**: the base case was built without reference to consensus target prices.
      Consensus is shown afterwards, for comparison only.
- [ ] **Reverse-engineered weights**: compute the equal-weighted value (the simple mean of the
      three scenario values). If equal weights would change the rating, say so in the report
      — the call then depends on the weights, and the weights need defending.
- [ ] **Bear case at full strength**: section 8.2 states the opposing case well enough that a
      holder of that view would sign it.
- [ ] **Rating is mechanical**: it follows from the probability-weighted upside and the stated
      thresholds, not from judgement applied afterwards.
- [ ] **Uncomfortable answers survive**: if the analysis says sharply overvalued, or "cannot be
      valued on available data", the report says that. It has not been softened toward Hold.

## E. Reproducibility

- [ ] `reports/<TICKER>_case.json` is saved, and re-running
      `valuation_engine.py value --input reports/<TICKER>_case.json` reproduces every
      valuation figure in the report.
- [ ] The sensitivity and elasticity tables in the report are the engine's own output.
- [ ] `reports/<TICKER>_numbers.md` was regenerated from the final case and spec, and every
      valuation figure in the report appears in it.
- [ ] As-of date appears in the header and footer; the not-investment-advice line is present.

## Common errors this list exists to catch

| Error | Symptom | Gate |
|---|---|---|
| Net cash entered as positive net debt | Equity value too low by 2 × net cash | C |
| TWD cash flows on a USD WACC | Value understated by the rate differential, compounding | C |
| Option value counted twice | SOTP total looks rich; same venture in core DCF | C |
| Basic share count | Value per share overstated, worst for SBC-heavy issuers | A |
| Weights chosen after the conclusion | Equal-weight value gives a different rating | D |
| Terminal value doing all the work | Engine warning; most value beyond year 10 | C |
| "Not material" noise list | No numbers in the noise table | B |
