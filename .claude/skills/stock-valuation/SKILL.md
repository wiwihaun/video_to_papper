---
name: stock-valuation
description: Institutional-grade single-stock valuation and research report. Use whenever the user supplies a bare ticker or company name with little or no other instruction ("2330", "TSMC", "台積電", "NVDA", "分析 2454", "看一下 AAPL"), or asks for a target price, 目標價, 估值, 合理價, fair value, price target, investment thesis, bull/bear case, or a sell-side / buy-side research note on a listed company. Produces a driver-isolation analysis (the one or two numbers that actually set the value), a reverse-DCF of what the current price already implies, a scenario-weighted target price, and a report written for sell-side research analysts and institutional PMs.
---

# Single-stock valuation — the "two numbers" method

A bare ticker is a complete instruction. `2330` means: run this workflow end to end and
give me the report. Do not ask what kind of analysis is wanted.

## The doctrine

Most equity research fails by being comprehensive. It assembles forty facts of equal
visual weight, and the one or two that actually set the share price are buried among
thirty-eight that do not move it at all.

This workflow inverts that. **Find the one or two numbers that drive the majority of
enterprise value, forecast those to the exclusion of everything else, and name the rest
as noise in writing.** A reader must be able to finish the report and state, in one
sentence, which number they are really betting on.

Two rules follow, and they are not optional:

1. **The noise list is a deliverable.** Every report explicitly names what it is
   ignoring and why it does not matter. A report with no noise list has not done the
   work — it has just hidden the step.
2. **Price the expectations before pricing the stock.** Always reverse-DCF the current
   price first (Phase 4) to recover what the market already assumes, *before* building
   your own forecast. This is the single strongest defence against anchoring: once you
   have built a target price, you can no longer see the market's assumption honestly.

On the provenance of this method, read `references/00-method-provenance.md`. Be
accurate about it if the user asks where the method came from.

## Workflow

Work through the phases in order. Phase 4 must precede Phase 5.

### Phase 0 — Resolve the security

Pin down, and state in the report header, before any analysis:

- **Ticker and listing.** Default a bare 4-digit code to Taiwan — TWSE (`.TW`) first, then
  TPEx/OTC (`.TWO`) — so `2330` = TSMC. Tokyo and Hong Kong also use numeric codes
  (`7203.T`, `2318.HK`); switch only if the user adds a suffix or says so, or the code does
  not exist in Taiwan. Disambiguate dual listings — TSMC trades as `2330.TW` and as the `TSM` ADR (1 ADR =
  5 common shares), and a target price is meaningless until you say which line it is for.
  Default to the primary local listing and give the ADR equivalent alongside.
- **Reporting currency vs trading currency**, and the FX assumption if they differ.
- **Fiscal year end**, and whether the market quotes calendar or fiscal years.
- **Spot price, as-of date and time, shares outstanding (diluted), and net debt.**
  Every valuation in this repo is stamped with its as-of date. An undated target price
  is not a research product.

If the ticker is ambiguous (`TSM` could be the ADR; `BABA` has HK and US lines), state
your reading in one line and continue. Do not stop to ask.

### Phase 1 — Decompose enterprise value into pools

Break the business into value pools, not reporting segments. A pool is a block of value
with its own economics and its own risk of being worth zero. For each, record a
first-pass share of EV. Keep it to three to six pools.

Separate **cash-generating pools** (value today) from **option pools** (value only if
something lands). Option pools carry an explicit probability of success and must never
be folded silently into a DCF — `valuation_engine.py` has `probability_of_success` on
each SOTP segment for exactly this.

### Phase 2 — Isolate the drivers

For each candidate driver, compute **valuation elasticity**: the percentage change in
value per share for a plausible one-standard-deviation move in that driver. Test at least
five candidates, and let the engine rank them — do not eyeball it:

```bash
python3 scripts/valuation_engine.py elasticity --input reports/<TICKER>_case.json \
  --scenario Base --markdown \
  --driver "Wafer volume@driver_build.units=0.12:rel" \
  --driver "EBIT margin@driver_build.ebit_margin=0.03" \
  --driver "WACC@wacc=0.005"   # ...and at least two more
```

It returns each driver's share of tested variance and a verdict. Then draw the line:

- **The numbers** — the top one or two by elasticity, which together should explain the
  large majority of the dispersion in value. These get the rest of the report.
- **The noise list** — everything else, each with a one-line dismissal that cites its
  elasticity. "Quarterly gross margin ±100bp moves fair value 2.1%, inside the error of
  the terminal assumption" is a dismissal. "Not material" is not.

A driver qualifies only if it is **forecastable and observable** — something you can
track in a filing, a monthly sales release or a regulatory dataset. A driver nobody can
measure is a narrative, not a driver, and belongs in the risk section.

If the engine's verdict is "not a two-number stock" (top two explain <50% of variance),
**that is the finding.** Say so on page one and widen the driver set. Never force the frame.

Full method, including the elasticity test and the common failure modes, in
`references/01-driver-isolation.md`.

### Phase 3 — Gather evidence on the numbers only

Depth on one or two things, not breadth on twenty. Sourcing rules, the hierarchy of
evidence, and what each market's filings are called: `references/03-data-sources.md`.

Non-negotiable: **every number in the report carries a source and a date.** Company
filing beats management guidance beats sell-side consensus beats press. Label consensus
as consensus. If you could not source something, write "not sourced" rather than
estimating silently.

### Phase 4 — Reverse-DCF the current price

Before forecasting anything, build a neutral base-case structure and solve for what the
spot price implies about each of the numbers from Phase 2:

```bash
python3 scripts/valuation_engine.py reverse --input reports/<TICKER>_case.json \
  --scenario Base --solve-for revenue_growth
```

Report it as a sentence of the form: *"At 1,180, the market is paying for X% revenue
CAGR for ten years at a Y% EBIT margin. The question is not whether the company is good.
It is whether that is achievable."*

Then judge that number against history and against physical limits — the company's own
best decade, the size of the end market, the industry's record margin. A price implying
a result no company in the sector has ever delivered is the finding, and often the whole
report.

### Phase 5 — Forecast the numbers: three scenarios

Only now build your own view. Bull / Base / Bear, each **defined by the Phase 2 numbers
and nothing else** — the scenarios must differ in those drivers, not in a vague mood.

Assign probabilities that sum to exactly 1.0 and **justify each weight in one line**.
The engine refuses to normalise weights for you, deliberately: unexamined weights are
where undisclosed bias enters a model.

Guardrails: terminal growth must not exceed long-run nominal GDP for the market
(~3% USD, ~2.5% TWD) without an argument; if PV of terminal value exceeds ~75% of EV,
extend the horizon or switch to an exit multiple and say so; expense SBC rather than
adding it back — the engine already does.

### Phase 6 — Value it

```bash
python3 scripts/valuation_engine.py value --input reports/<TICKER>_case.json --markdown
```

Prefer SOTP when option pools matter; prefer a single DCF when one pool dominates.
Always cross-check the DCF output against a multiples view on comparables — if they
disagree by more than about 25%, find out why and write the reconciliation down. That
gap is usually the most interesting paragraph in the report.

Produce a 5×5 sensitivity grid on the two highest-elasticity drivers, and a second on
WACC × terminal growth. Input schema, WACC construction and every engine flag:
`references/02-valuation-engines.md`.

### Phase 7 — Falsification

State what would make you wrong, in terms a reader can check without you:

- **Tripwires** — specific observable thresholds that break the thesis, each with the
  data release that reveals it and its date. "Monthly revenue below NT$X for two
  consecutive months" is a tripwire. "Competition intensifies" is not.
- **The strongest argument against the call**, stated at full strength, in the other
  side's own best terms, and then answered. If the bear case cannot be written
  convincingly, the thesis has not been tested.
- **A KPI dashboard** — the Phase 2 numbers, where each is published, and the next
  release date, so the reader can run the thesis without re-reading the report.

### Phase 8 — Write the report

Write to `reports/<TICKER>_<YYYY-MM-DD>.md`, following
`references/04-report-template.md`. Conventions institutional readers expect:

- One-page summary that stands alone: rating, target price, methodology in a clause,
  upside, and the thesis in two sentences naming the numbers.
- Target price with explicit method, horizon (12-month unless stated) and the scenario
  weights that produced it.
- Tables for anything numeric. Prose for judgement only.
- Separate **fact** (sourced, dated) from **estimate** (yours, labelled) from
  **consensus** (theirs, labelled). Never blend them in one sentence.
- No recommendation without a target price, and no target price without a horizon.

### Phase 9 — Quality gates

Run `references/05-quality-gates.md` before delivering. It is a hard checklist: an
unchecked box is a blocking defect, not a nitpick. It catches circular valuation,
anchoring on the spot price, scenario weights reverse-engineered to a conclusion,
double-counted option pools, and the two or three arithmetic errors that most often
survive into a published note.

## Output

A single markdown report at `reports/<TICKER>_<YYYY-MM-DD>.md`, plus the case JSON at
`reports/<TICKER>_case.json` so every number is reproducible by re-running the engine.
Send the report to the user with `SendUserFile`.

In chat, give only: rating, target price, upside, the one-sentence thesis, and the link.
The analysis belongs in the report, not in the reply.

## Honesty requirements

These override any instinct to produce a complete-looking report:

- **Never fabricate a figure.** No invented revenue, margin, consensus estimate, price
  or date. If data is unavailable, the report says so and the valuation carries the gap
  as a stated limitation. A report with holes is useful; a report with invented numbers
  is worse than nothing, because it cannot be audited.
- **Distinguish what you verified from what you assumed.** Assumptions get a table of
  their own.
- **Report the uncomfortable answer.** If the work says the stock is 60% overvalued, or
  that the position cannot be valued on available data, that is the finding. Do not
  soften it toward a hold.
- This is analysis, not investment advice. Close every report with that line and the
  as-of date.
