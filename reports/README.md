# reports/

每次分析產出兩個檔案：

- `<TICKER>_<YYYY-MM-DD>.md` — 研究報告
- `<TICKER>_case.json` — 估值模型輸入；以 `python3 scripts/valuation_engine.py value --input reports/<TICKER>_case.json --markdown` 可重現報告中所有估值數字
