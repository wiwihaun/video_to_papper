# video_to_papper — 個股估值工作流（「兩個數字」法）

把一支 YouTube 投資影片的核心觀點，轉成可重複執行的 Claude Code 技能：
**只要輸入股票代號或名稱（例如 `2330`、`TSMC`、`台積電`、`NVDA`），就照固定流程完成估值，
並產出券商賣方研究員與外資／私募基金分析師、經理人可直接閱讀的研究報告。**

## 使用方式

在這個 repo 裡開啟 Claude Code，直接輸入：

```
2330
```

或 `TSMC`、`分析 2454`、`NVDA 目標價`。技能會自動觸發，報告輸出到
`reports/<代號>_<日期>.md`，並附上可重算驗證的全套檔案：

| 檔案 | 內容 |
|---|---|
| `reports/<代號>_case.json` | 模型輸入，`_notes` 欄位逐項註明來源 |
| `reports/<代號>_spec.json` | 報告用到的所有分析（估值、彈性、反向 DCF、變體、共識拆解、敏感度） |
| `reports/<代號>_numbers.md／.json` | 由規格檔產生的數字附錄——報告中每個估值數字都在這裡 |
| `reports/<代號>_evidence.json` | 研究證據：每個數字的來源網址、日期與證據等級 |

**完整範例（2026-11-01）：**
- 台積電（2330）— 美元 DCF、四情境、台海事件風險覆蓋層 — [`reports/2330_2026-11-01.md`](reports/2330_2026-11-01.md)
- 玉山金（2884）— 金控用剩餘收益模型（ROA × 槓桿）、併購後淨值推估 — [`reports/2884_2026-11-01.md`](reports/2884_2026-11-01.md)

想在其他專案也能用：把 `.claude/skills/stock-valuation/` 複製到 `~/.claude/skills/`，
並把 `scripts/valuation_engine.py` 一起帶過去（技能用相對路徑呼叫它）。

## 方法：兩個數字，其餘都是噪音

來源影片：Terry Chen 泰瑞〈投資特斯拉看這兩個數字，其他都是噪音〉
（https://www.youtube.com/watch?v=F7WEN5wOGZs）。

> **重要：逐字稿目前尚未取得**（雲端環境被 YouTube 封鎖，詳見
> [`docs/transcript/README.md`](docs/transcript/README.md)）。本技能的骨幹來自影片標題所
> 陳述的論點；估值計算則是標準的機構投資方法，並非影片內容。哪些已驗證、哪些是推論，
> 完整記錄在 [`00-method-provenance.md`](.claude/skills/stock-valuation/references/00-method-provenance.md)。

| 階段 | 做什麼 | 產出 |
|---|---|---|
| 0 | 確認標的：掛牌、ADR 換算、幣別、現價與日期 | 報告表頭 |
| 1 | 把企業價值拆成價值池（現金流型 vs 選擇權型） | 價值池表 |
| 2 | **用彈性測試找出「兩個數字」**，其餘列入雜訊清單 | 彈性排序表 + 判定 |
| 3 | 只針對這兩個數字深入蒐證，每個數字附來源與日期 | 來源清單 |
| 4 | **反向 DCF：現價已經隱含了什麼**（先做，避免錨定） | 市場隱含預期 |
| 5 | 三情境預測，只在兩個數字上做出差異，權重逐一說明 | 情境表 |
| 6 | DCF / SOTP 估值、敏感度矩陣、同業倍數交叉驗證 | 機率加權目標價 |
| 7 | 證偽：觸發條件、最強反方論點、KPI 追蹤儀表板 | 風險與追蹤 |
| 8 | 依機構格式撰寫報告（中文內文＋英文摘要） | 研究報告 |
| 9 | 品質關卡：硬性檢查清單 | 交付 |

## 結構

```
.claude/skills/stock-valuation/
  SKILL.md                         # 工作流主檔（觸發條件與 9 個階段）
  references/
    00-method-provenance.md        # 方法溯源：已驗證 vs 推論
    01-driver-isolation.md         # 第 2 階段：如何找出兩個數字、雜訊清單寫法
    02-valuation-engines.md        # 估值引擎規格、WACC、終值紀律
    03-data-sources.md             # 台股／美股資料來源、證據等級
    04-report-template.md          # 報告範本與評等規則
    05-quality-gates.md            # 交付前硬性檢查
scripts/
  valuation_engine.py              # 估值計算引擎（純標準函式庫、可重現）
  run_analysis.py                  # 一份規格檔跑完所有分析，產生數字附錄
  test_valuation_engine.py         # 可手算驗證的單元測試
  render_report.py                 # 把報告與數字附錄轉成可分享的 HTML 頁面（評等區間圖、目錄）
docs/transcript/README.md          # 逐字稿取得方式
reports/                           # 報告輸出目錄
```

## 估值引擎

所有計算都經過 `scripts/valuation_engine.py`，不在文字裡心算。寫報告時，用一份規格檔一次產生全部數字：

```bash
python3 scripts/run_analysis.py --spec reports/2330_spec.json
```

也可以單獨執行各個分析：

```bash
# 第 2 階段：哪些驅動因子真正影響價值（可用路徑切片分開測近期與遠期成長）
python3 scripts/valuation_engine.py elasticity --input reports/2330_case.json --markdown \
  --driver "2029-36 成長@driver_build.revenue_growth[2:]=0.03" \
  --driver "營業利益率@driver_build.ebit_margin=0.05"

# 第 4 階段：前兩年採共識，求 2029 年起的隱含成長
python3 scripts/valuation_engine.py reverse --input reports/2330_case.json \
  --solve-for revenue_growth --from-year 3

# 第 4 階段：股價隱含的年化事件機率
python3 scripts/valuation_engine.py reverse --input reports/2330_case.json --solve-for hazard_rate

# 第 6 階段：三情境估值、機率加權公允價值與 12 個月目標價
python3 scripts/valuation_engine.py value --input reports/2330_case.json --markdown
```

引擎功能：

- **雙幣別**：以經濟幣別建模（台積電用美元），每股價值以即期匯率換回報價幣別，並換算 ADR。
- **12 個月目標價**：公允價值以報價幣別股權成本（依利率平價由 WACC 推得）滾動 12 個月，扣除股利。
- **事件風險覆蓋層**：「年化發生機率 × 營運價值損失比例」，終值有封閉解；可反推股價隱含的機率。
- **反向 DCF**：可只從第 N 年起求解（例如前兩年採共識，求之後的隱含成長）。
- **彈性測試**：支援路徑切片，可分開檢驗近期成長與成長延續期間。
- **金融股**：剩餘收益模型，ROE 可用杜邦拆解（ROA × 槓桿）；事件風險以股利折現形式衝擊全部權益。
- **機械式評等**：依門檻輸出評等與買進／賣出觸發價；規格檔可求解評等翻轉點。

內建護欄：終值成長率 ≥ WACC 會拒絕計算；情境機率加總不為 1 會拒絕（不會偷偷正規化）；
終值占 EV 超過 75%、選擇權型價值池超過 40%、終值成長率高於 3.5% 都會發出警告。
SBC 一律視為費用，不加回。

測試：

```bash
python3 -m unittest scripts/test_valuation_engine.py -v
```

---
*本專案為分析工具，非投資建議。*
