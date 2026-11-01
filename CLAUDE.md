# CLAUDE.md

This repo turns a stock-valuation method into a reusable workflow.

## Routing

If the user's message is a ticker or a company name — alone or with a few words such as
"分析", "目標價", "估值", "看一下" (e.g. `2330`, `TSMC`, `台積電`, `NVDA`, `分析 2454`) —
invoke the `stock-valuation` skill and run its full workflow. Do not ask what kind of
analysis is wanted; the bare ticker is the instruction.

## Rules

- All valuation arithmetic goes through `scripts/valuation_engine.py`. Never compute a DCF
  in prose.
- Never fabricate a financial figure. Unsourced data is written as "not sourced".
- Before changing the engine, run `python3 -m unittest scripts/test_valuation_engine.py`.
- On the provenance of the method, defer to
  `.claude/skills/stock-valuation/references/00-method-provenance.md`. The source video's
  transcript has not been obtained; do not attribute specific techniques to its author.
