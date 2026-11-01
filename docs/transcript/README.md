# 逐字稿：取得方式與目前狀態

**影片**：Terry Chen 泰瑞〈投資特斯拉看這兩個數字，其他都是噪音〉
https://www.youtube.com/watch?v=F7WEN5wOGZs

## 目前狀態：尚未取得

2026-11-01 在雲端環境嘗試過的途徑：

| 途徑 | 結果 |
|---|---|
| `yt-dlp` 下載字幕 | 失敗：YouTube 回傳 HTTP 429，接著要求「登入以確認你不是機器人」。雲端容器的 IP 被限流。 |
| 安裝 JS runtime（deno）以滿足下載器需求 | 被本工作階段的權限政策擋下（下載外部程式碼）。 |
| 改用其他 YouTube 播放器用戶端 | **刻意沒有做**：那屬於繞過機器人驗證。 |
| WhisperAI 轉錄服務 | 連接器已中斷，需要重新授權；且它只接受直接的音訊檔網址，不接受 YouTube 頁面。 |

## 補上逐字稿的四種方式（由簡到繁）

**1. 從 YouTube 網頁複製（最快、零設定）**
在電腦瀏覽器開啟影片 → 影片說明區點「…更多」→ 往下找到「顯示轉錄稿」→ 在右側轉錄稿面板
全選複製 → 直接貼到對話中。

**2. 在自己的電腦執行 yt-dlp**（家用網路通常不會被擋）

```bash
yt-dlp --skip-download --write-auto-subs --write-subs --sub-langs "zh-TW,zh-Hant,zh,en" -o "F7WEN5wOGZs" "https://www.youtube.com/watch?v=F7WEN5wOGZs"
```

把產生的 `.vtt` 檔放進 `docs/transcript/` 並推上 GitHub，或直接貼上內容。

**3. WhisperAI**：到 claude.ai 的連接器設定重新授權 WhisperAI，接著自行下載影片音訊，
透過 WhisperAI 的上傳元件上傳，即可取得含時間戳的逐字稿。

**4. Remote Control**：在 Claude 桌面版（設定 → Claude Code → Remote Control）分享一個資料夾，
雲端工作階段即可在你的電腦上（家用 IP）執行方式 2。

## 取得後會做的事

1. 原文存為 `docs/transcript/F7WEN5wOGZs.md`，註明取得日期與方式。
2. 從逐字稿萃取作者實際的方法：他選的兩個數字、換算成價值的計算方式、情境設計、
   以及他明確視為「噪音」的項目。
3. 若作者的實際方法與目前的標準機構流程不同，修訂技能的第 1–7 階段，
   並把差異記錄在 `00-method-provenance.md`。
