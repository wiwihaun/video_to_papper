# Phase 3 — Sourcing: where the numbers come from

## The rule

**Every number in the report carries a source and an as-of date, or it is labelled as an
estimate.** If something cannot be sourced, write "not sourced" in its place and carry the
gap into the limitations section. Never fill a gap with a plausible-looking figure.

## Evidence hierarchy

Use the highest available tier. When tiers disagree, the higher tier wins and the
disagreement is worth noting.

| Tier | Source type | Use for | Label in report |
|---|---|---|---|
| 1 | Audited annual filings; reviewed quarterly filings | Historical financials, share count, debt | (source, period) |
| 2 | Official company releases: monthly revenue, quarterly results, KPI letters | Recent run-rate, operating KPIs | (source, date) |
| 3 | Management guidance; earnings-call statements | Near-term outlook | **"guidance"** |
| 4 | Industry data: TrendForce, SEMI, Gartner, IDC, WSTS, shipping indices, regulators | End-market size, prices, share | (provider, date) |
| 5 | Sell-side consensus (FactSet, LSEG, Bloomberg — often via news summaries) | Benchmark to beat, not an input | **"consensus"** |
| 6 | Press and news | Events, dates, context | (outlet, date) |
| 7 | YouTube, social media, forums | **Idea generation only** — never evidence for a number | do not cite as a source of data |

## Taiwan-listed (4-digit codes)

| Need | Primary source | Notes |
|---|---|---|
| Financial statements, material announcements | MOPS 公開資訊觀測站 — `mops.twse.com.tw` | Quarterly statements within 45 days of quarter end; annual by 31 March |
| **Monthly revenue** | MOPS (每月營收) and company IR | Filed by the 10th of the following month. For most Taiwan tech this is the highest-frequency hard data point you have. |
| Daily price, P/E, P/B, yield | TWSE `twse.com.tw` (listed) / TPEx `tpex.org.tw` (OTC) | |
| Institutional flows | TWSE 三大法人買賣超 (foreign, investment trust, dealer) | Flow, not value — context only |
| Shareholding distribution | TDCC 集保結算所 | |
| Earnings-call materials | Company IR site (法說會簡報, management report, transcript) | Node mix, segment mix, guidance |
| Consensus | News summaries of FactSet surveys (e.g. 鉅亨 cnyes 「Factset 最新調查」) | Label as consensus, with survey date and number of analysts |
| Aggregators | Goodinfo, CMoney, StatementDog (財報狗) | Convenient; **verify any number you use against MOPS** |

Units trap: Taiwan statements report in NT$ thousands; many summaries use NT$ hundred
millions (億) or billions. Convert everything to NT$ millions in the case JSON and say so.

## US-listed

| Need | Primary source | Notes |
|---|---|---|
| Filings | SEC EDGAR: 10-K, 10-Q, 8-K, proxy (DEF 14A), 20-F / 6-K for foreign issuers | Large accelerated filers: 10-Q within 40 days, 10-K within 60 days |
| KPIs | Earnings release, shareholder letter, investor presentation | Tesla publishes deliveries quarterly and a quarterly update letter |
| Diluted shares | 10-Q cover page + treasury-stock-method dilution from the equity footnote | Not the basic count from a quote page |
| SBC | Cash-flow statement and equity footnote | Expensed in the engine |

## Dual listings and ADRs

State which line the target price is for. Value in the reporting currency, then convert the
per-share result: ADR value = local value × ADR ratio ÷ FX. TSMC: `2330.TW` and `TSM`,
1 ADR = 5 common shares. The ADR premium or discount to local is real and persistent;
report it rather than assuming it closes.

## Operating KPIs — the Phase 2 numbers

Find the **publication schedule** for each isolated driver, because the KPI dashboard in
Phase 7 needs the next release date. Typical sources:

- Semiconductors: monthly revenue (TW), quarterly node and platform mix, TrendForce contract
  prices, SEMI equipment billings, hyperscaler capex guidance.
- Autos and autonomy: quarterly deliveries, regulator datasets (e.g. NHTSA crash reporting,
  California DMV and CPUC autonomous-vehicle reports), company fleet and mileage disclosures.
- Shipping: SCFI (weekly), orderbook data.
- Banks: quarterly NIM and credit-cost disclosures, central-bank rate decisions.

## Retrieval in this environment

Verified on 2026-11-01 in this cloud container:

| Route | Status |
|---|---|
| `WebSearch` | **works** — use for discovery, news, consensus summaries |
| `WebFetch` on official pages (IR sites, MOPS, EDGAR, TWSE) | **works** for most pages — use for the numbers themselves |
| Direct market-data APIs from the shell (e.g. stooq CSV) | **blocked** — returned nothing |
| YouTube | **blocked** (HTTP 429 and bot check) |

So: use `WebSearch` to find, `WebFetch` to read the primary page, and record the URL and
access date for each figure. If a primary page will not load, try the company IR mirror
or the filing PDF. If nothing loads, ask the user to paste the figure or the page, and
meanwhile proceed with everything that does not depend on it.

## Source log

Keep a numbered source list as you go, and reference figures as [1], [2] in the report:

```
[1] TSMC, 3Q26 Management Report, IR site, accessed 2026-11-01
[2] MOPS, 2330 monthly revenue, September 2026, accessed 2026-11-01
[3] cnyes, "Factset 最新調查: 台積電...", 2026-10-xx — consensus, n analysts
```

A figure without a source-log entry does not go in the report.
