# reports/

每次分析產出：

- `<TICKER>_<YYYY-MM-DD>.md` — 研究報告
- `<TICKER>_case.json` — 估值模型輸入（`_notes` 逐項註明來源）
- `<TICKER>_spec.json` — 報告用到的全部分析
- `<TICKER>_numbers.md／.json` — 數字附錄：`python3 scripts/run_analysis.py --spec reports/<TICKER>_spec.json`
- `<TICKER>_evidence.json` — 研究證據（網址、日期、證據等級）
- `2884_spec_beta072.json`、`2884_numbers_beta072.md／.json` — 玉山金的替代參數（Damodaran 產業 β 0.72）完整附錄，供第 5.2 節引用
- `2330_financials.py／.md` — 台積電十年財務摘要（歷史 + Base 預估）

目前收錄：2330 台積電、2884 玉山金（皆為 2026-11-01）。
