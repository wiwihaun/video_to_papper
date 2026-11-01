# Phase 8 — Report template

Write to `reports/<TICKER>_<YYYY-MM-DD>.md`.

## Language and conventions

- **Body language follows the user's request.** A request in Chinese gets a report in
  Traditional Chinese (繁體中文); keep standard English financial terms untranslated
  (TP, EV, WACC, FCFF, SOTP, EPS, ROE, bp, pp) — that is how institutional readers in
  Taipei and Hong Kong actually write.
- **Always include the English Executive Summary block**, whatever the body language. Foreign
  PMs read the first page and decide whether to read the rest.
- Numbers: thousands separators; currency on every money figure; "NT$1,180" or "US$245";
  percentages to one decimal; multiples to one decimal with "x".
- Dates in ISO format (2026-11-01). Fiscal periods as 1Q26, FY26, 2026E.
- `E` suffix for estimates (2027E), `A` for actuals. Consensus labelled "cons."
- Every table has a source line under it.
- Each section opens with its conclusion in one sentence. The first paragraph of the report
  states what the price implies and where we differ — never company history.
- Taiwan usage for Chinese terms: 營收, 毛利率, 營業利益率, 資本支出, 自由現金流, 本益比,
  目標價, 每股盈餘, 淨現金, 法說會; 「億／兆」for NT$ narrative figures, millions in tables.

## Rating framework

Rating is mechanical once the target price exists. Do not choose a rating and then find a
target price for it.

| Rating | 12-month probability-weighted upside |
|---|---|
| **Buy / Overweight** | > +15% |
| **Hold / Neutral** | −15% to +15% |
| **Sell / Underweight** | < −15% |

Add a **conviction** flag: **High** when the driver verdict is "clean two-number stock" and
Bear-to-Bull spread is under 2x; **Low** when the verdict is "not a two-number stock" or
option pools are >40% of EV; **Medium** otherwise. A high-upside, low-conviction call is
legitimate and must be labelled as such.

The user may supply house thresholds; use theirs if given.

---

## Template

```markdown
# [公司名稱 Company Name] ([TICKER]) — [一句話論點，以「兩個數字」為主語]

| | |
|---|---|
| **評等 Rating** | [Buy / Hold / Sell] · Conviction: [High / Medium / Low] |
| **目標價 Target Price** | [CCY] [TP] (12 個月, probability-weighted) |
| **現價 Price** | [CCY] [spot] ([YYYY-MM-DD] 收盤) |
| **跨市場隱含價 Implied by later-trading line** | [e.g. ADR close after local close implies CCY x; upside from that price y%] — omit if not applicable |
| **潛在漲跌幅 Upside** | [+/-x.x%] |
| **ADR / 其他掛牌** | [e.g. TSM: US$[x] equivalent at [FX], 1 ADR = 5 shares] |
| **市值 Market cap** | [CCY]m [x] · 稀釋股數 [x]m · 淨現金(負債) [x]m |
| **估值方法 Method** | [DCF / SOTP], WACC [x.x%], g [x.x%]; cross-check [EV/EBITDA, P/E] |
| **資料截止 As of** | [YYYY-MM-DD] |

> **Executive Summary (English).** [Four to six sentences. Rating and TP. The two numbers and
> why they set the value. What the current price implies about them (reverse DCF). Where
> our view differs from that and why. The tripwire that would change the call.]

## 1. 投資摘要 Investment Summary

[Standalone page. Thesis in two sentences, naming the numbers. Variant perception: what we
believe that the price does not, in one paragraph. Scenario table (below). Key catalysts
and the key tripwire, one line each.]

| 情境 Scenario | 機率 Prob. | 數字一 [Driver 1] | 數字二 [Driver 2] | 每股價值 Value/sh | 漲跌幅 vs spot |
|---|---|---|---|---|---|
| Bull | [x%] | [value] | [value] | [x] | [x%] |
| Base | [x%] | [value] | [value] | [x] | [x%] |
| Bear | [x%] | [value] | [value] | [x] | [x%] |
| **加權 Weighted** | 100% | | | **[TP]** | **[x%]** |

## 2. 兩個數字 The Two Numbers

[Why these two. The elasticity table straight from the engine. The verdict line. If the
verdict is "not a two-number stock", this section says so in its first sentence.]

[elasticity --markdown output]

| 數字 Driver | 定義 Definition | 公布來源 Published in | 頻率 Frequency | 最新值 Latest | 下次公布 Next release |
|---|---|---|---|---|---|

## 3. 市場隱含預期 What the Price Already Implies

[Reverse-DCF results, one line per driver: "At [price], the market is paying for [driver]
= [implied value] over [N] years." Then the judgement: compare each implied value with the
company's own history, its best-ever period, peers' records and the size of the end market.
This section is where the call is usually decided.]

| 數字 Driver | 現價隱含 Implied | 公司歷史 History | 同業最佳 Peer best | 我們的基本情境 Our base | 判斷 Verdict |
|---|---|---|---|---|---|

## 4. 我們與市場的差異 Variant Perception

[What we expect that the price does not, the evidence for it, and when the market will be
able to see it — which data release will prove or disprove it. If there is no variant
perception, say so: a fair-value Hold is a legitimate conclusion.]

## 5. 估值 Valuation

### 5.1 情境假設 Scenario assumptions
[Table of drivers by scenario, and a one-line justification for each probability weight.]

### 5.2 模型 Model
[value --markdown output: scenario summary, FCFF build or SOTP table, EV-to-equity bridge.]

### 5.3 敏感度分析 Sensitivity
[Two 5x5 grids: driver 1 x driver 2; WACC x terminal growth.]

### 5.4 交叉驗證 Cross-check
[Multiples on peers and own history. Implied exit multiple of the DCF terminal value.
If DCF and multiples differ by more than ~25%: the reconciliation, in prose.]

| 同業 Peer | 代碼 | EV/EBITDA FY1 | P/E FY1 | 營收成長 FY1 | 營益率 | 來源 |
|---|---|---|---|---|---|---|

### 5.5 與市場共識的差距拆解 Bridge to Consensus
[Start from the consensus target price. Switch one assumption at a time from ours to the
consensus-like setting and re-run the engine. Every row is an engine output.]

| 步驟 Step | 假設變動 Assumption switched | 每股價值 Value/sh | 差距貢獻 Contribution |
|---|---|---|---|
| 我們的價值 Our value | — | [x] | |
| + [assumption 1] | [ours → consensus-like] | [x] | [+x] |
| + [assumption 2] | | [x] | [+x] |
| ≈ 共識目標價 Consensus TP | | [x] | |

### 5.6 事件風險定價 Pricing Discrete Event Risk
[Only when a jump risk is material. The implied annual probability from the reverse solve;
external anchors with dates (prediction markets carry-adjusted, superforecasters, expert
surveys); the probability used in the TP and why; value at 0%, our h, and 2x our h.]

### 5.7 模型警示 Model warnings
[Every engine warning, each either resolved or explained. "None" if none.]

## 6. 雜訊清單 Noise List

[The items the market is watching that do not set the value, each dismissed with its
elasticity. Flag items that move the price short term (trading events) while not moving
fair value.]

| 項目 Item | 市場為何關注 Why watched | 彈性 Elasticity (1σ) | 為何不影響價值 Why it is noise |
|---|---|---|---|

## 7. 催化劑 Catalysts

| 日期 Date | 事件 Event | 驗證哪個數字 Tests which driver | 若優於預期 If better | 若低於預期 If worse |
|---|---|---|---|---|

## 8. 風險與證偽 Risks & Falsification

### 8.1 觸發條件 Tripwires
| 條件 Condition | 觀察來源 Where observed | 時點 When | 對評等影響 Effect on call |
|---|---|---|---|

### 8.2 最強反方論點 The strongest case against us
[The bear case (or bull case, if we are negative) at full strength, in its proponents'
best terms. Then our answer. If we cannot answer it, lower conviction and say why.]

### 8.3 其他風險 Other risks
[Risks that are real but not drivers: regulatory, geopolitical, key-person, FX,
accounting. One line each, with direction and rough magnitude where possible.]

## 9. 財務摘要 Financial Summary

| [CCY]m | FY[-2]A | FY[-1]A | FY[0]A/E | FY[+1]E | FY[+2]E | FY[+3]E |
|---|---|---|---|---|---|---|
| 營收 Revenue | | | | | | |
| 成長 Growth | | | | | | |
| 毛利率 Gross margin | | | | | | |
| 營益率 EBIT margin | | | | | | |
| EPS (diluted) | | | | | | |
| FCF | | | | | | |
| ROE | | | | | | |
| 淨現金(負債) Net cash (debt) | | | | | | |
| P/E | | | | | | |
| EV/EBITDA | | | | | | |

Source: actuals [ref]; estimates ours, from the Base scenario. Consensus in a separate row,
labelled, where available.

## 10. 假設與限制 Assumptions & Limitations

| 假設 Assumption | 數值 Value | 依據 Basis | 已驗證? Verified? |
|---|---|---|---|

[Data gaps carried into the valuation, stated plainly. Anything "not sourced".]

## 11. 資料來源 Sources

[1] ...
[2] ...

---
*本報告為分析研究，非投資建議。This report is analysis, not investment advice.
Prices and data as of [YYYY-MM-DD]. Model: `reports/[TICKER]_case.json`, reproducible
with `scripts/valuation_engine.py`.*
```
