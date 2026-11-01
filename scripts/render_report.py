#!/usr/bin/env python3
"""
Render a report (reports/<TICKER>_<DATE>.md) and its numbers appendix (<TICKER>_numbers.json)
into a self-contained HTML page body for sharing (e.g. as a Claude Artifact). Stdlib only.

    python3 scripts/render_report.py reports/2330_2026-11-01.md reports/2330_numbers.json OUT.html

The page has: a cover (headline, rating, target, price, the rating ladder and the report's own
key-data table), a section index, the report body, and the disclaimer. It renders the subset of
Markdown the reports use: headings, paragraphs, bold, code spans, tables, block quotes, lists.
"""
import html
import json
import re
import sys

NUM = re.compile(r"[\s約~]*(NT\$|US\$)?\s*[+\-−–]?[\d,]+(\.\d+)?\s*(%|x|倍|pp|bp)?[*+]*(\s*[（(][^）)]*[）)])?\s*")


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return t


def plain(t):
    return re.sub(r"\*\*|`", "", t).strip()


def cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def table_html(rows):
    head, body = cells(rows[0]), [cells(r) for r in rows[2:]]
    ncol = len(head)
    numeric = []
    for j in range(ncol):
        col = [plain(r[j]) for r in body if j < len(r) and plain(r[j])]
        hits = sum(1 for c in col if NUM.fullmatch(c))
        numeric.append(j > 0 and col and hits / len(col) >= 0.6)
    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    for j, h in enumerate(head):
        out.append('<th%s>%s</th>' % (' class="num"' if numeric[j] else "", inline(h)))
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>")
        for j in range(ncol):
            c = r[j] if j < len(r) else ""
            out.append('<td%s>%s</td>' % (' class="num"' if numeric[j] else "", inline(c)))
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def parse(md):
    lines = md.split("\n")
    title, facts, blocks, toc, disclaimer = "", [], [], [], ""
    i, n, sec = 0, len(lines), 0
    starts = ("#", "|", ">", "- ")
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s or s == "---":
            i += 1
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            i += 1
            continue
        if line.startswith("## "):
            sec += 1
            txt = line[3:].strip()
            toc.append(("sec-%d" % sec, plain(txt)))
            blocks.append('<h2 id="sec-%d">%s</h2>' % (sec, inline(txt)))
            i += 1
            continue
        if line.startswith("### "):
            blocks.append("<h3>%s</h3>" % inline(line[4:].strip()))
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            if not facts and sec == 0:
                facts = [(plain(cells(r)[0]), inline(cells(r)[1])) for r in rows[2:] if len(cells(r)) >= 2]
            else:
                blocks.append(table_html(rows))
            continue
        if s.startswith(">"):
            q = []
            while i < n and lines[i].strip().startswith(">"):
                q.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append('<aside class="summary">%s</aside>' % "".join("<p>%s</p>" % inline(x) for x in q if x))
            continue
        if re.match(r"^- ", s):
            items = []
            while i < n and re.match(r"^- ", lines[i].strip()):
                items.append(lines[i].strip()[2:])
                i += 1
            blocks.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x) for x in items))
            continue
        if re.match(r"^\d+\. ", s):
            items = []
            while i < n and re.match(r"^\d+\. ", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            blocks.append("<ol>%s</ol>" % "".join("<li>%s</li>" % inline(x) for x in items))
            continue
        para = []
        while i < n and lines[i].strip() and not lines[i].strip().startswith(starts) and lines[i].strip() != "---" \
                and not re.match(r"^\d+\. ", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        text = "".join(para)
        if text.startswith("*") and text.endswith("*") and not text.startswith("**"):
            disclaimer = inline(text[1:-1])
        else:
            blocks.append("<p>%s</p>" % inline(text))
    return title, facts, blocks, toc, disclaimer


def ladder_svg(spot, tp, buy, sell, cur):
    lo = min(buy, tp, spot) - (sell - buy) * 0.28
    hi = max(sell, spot) + (sell - buy) * 0.24
    x0, x1 = 16.0, 704.0
    X = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)
    dp = 0 if spot >= 1000 else 2
    f = lambda v: ("{:,.%df}" % dp).format(v)
    zones = [("zone-buy", lo, buy, "買進 < %s" % f(buy)), ("zone-hold", buy, sell, "中立"),
             ("zone-sell", sell, hi, "賣出 > %s" % f(sell))]
    parts = ['<svg class="ladder" viewBox="0 0 720 124" role="img" aria-label="評等區間：現價 %s %s，目標價 %s %s">'
             % (cur, f(spot), cur, f(tp))]
    for cls, a, b, lab in zones:
        xa, xb = X(a), X(b)
        parts.append('<rect class="%s" x="%.1f" y="46" width="%.1f" height="30"></rect>' % (cls, xa, xb - xa))
        if xb - xa > 70:
            parts.append('<text class="zone-label" x="%.1f" y="66" text-anchor="middle">%s</text>'
                         % ((xa + xb) / 2, html.escape(lab)))
    for v, cls, y, lab, anchor_y in ((spot, "mark-spot", 30, "現價 %s %s" % (cur, f(spot)), 40),
                                     (tp, "mark-tp", 106, "12 個月目標價 %s %s" % (cur, f(tp)), 82)):
        x = X(v)
        anchor = "middle" if 120 < x < 600 else ("start" if x <= 120 else "end")
        parts.append('<line class="%s" x1="%.1f" x2="%.1f" y1="%d" y2="%d"></line>' % (cls, x, x, 40 if cls == "mark-spot" else 46, 76 if cls == "mark-spot" else 86))
        parts.append('<circle class="%s-dot" cx="%.1f" cy="%d" r="4"></circle>' % (cls, x, anchor_y))
        parts.append('<text class="mark-label" x="%.1f" y="%d" text-anchor="%s">%s</text>' % (x, y, anchor, html.escape(lab)))
    parts.append("</svg>")
    return "".join(parts)


CSS = r"""
/* Layout: a broker research note. A fact-sheet cover with the rating ladder, then one reading
   column with a sticky section index beside it on wide screens. */
:root {
  --paper: #f6f8f9; --panel: #ebf0f2; --ink: #15212b; --muted: #586774; --rule: #d3dbe1;
  --accent: #0b676c; --buy: #1d7a4b; --hold: #9a6400; --sell: #b02a21; --on-zone: #ffffff;
  --font-display: "IBM Plex Serif", "Noto Serif TC", "Songti TC", serif;
  --font-body: "IBM Plex Sans", "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
  --font-data: "IBM Plex Mono", ui-monospace, "SFMono-Regular", monospace;
  --step--1: 0.8125rem; --step-0: 1rem; --step-1: 1.1875rem; --step-2: 1.5rem; --step-3: 2.125rem;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper: #0f161b; --panel: #16212a; --ink: #e2e9ee; --muted: #93a3b0; --rule: #263440;
  --accent: #62c6c2; --buy: #5ccf92; --hold: #e3b14c; --sell: #f2877d; --on-zone: #0f161b; color-scheme: dark } }
:root[data-theme="dark"] {
  --paper: #0f161b; --panel: #16212a; --ink: #e2e9ee; --muted: #93a3b0; --rule: #263440;
  --accent: #62c6c2; --buy: #5ccf92; --hold: #e3b14c; --sell: #f2877d; --on-zone: #0f161b; color-scheme: dark }
* { box-sizing: border-box; }
body { background: var(--paper); color: var(--ink); font-family: var(--font-body); font-size: var(--step-0);
  line-height: 1.75; -webkit-font-smoothing: antialiased; }
.page { max-width: 1240px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 56px; }
.cover { display: grid; gap: 18px; padding-block: 8px 28px; border-bottom: 2px solid var(--ink); }
.eyebrow { font-family: var(--font-data); font-size: var(--step--1); letter-spacing: 0.06em; color: var(--muted);
  display: flex; flex-wrap: wrap; gap: 6px 14px; }
.eyebrow .ticker { color: var(--accent); font-weight: 600; }
h1 { font-family: var(--font-display); font-size: var(--step-3); line-height: 1.3; font-weight: 700; margin: 0;
  text-wrap: balance; max-width: 34em; }
.company { font-family: var(--font-display); font-size: var(--step-1); color: var(--muted); margin: 0; }
.verdict { display: flex; flex-wrap: wrap; gap: 12px 28px; align-items: flex-end; }
.chip { display: inline-flex; align-items: center; gap: 8px; padding: 4px 12px; border-radius: 3px;
  font-weight: 600; font-size: var(--step-0); color: var(--on-zone); }
.chip.sell { background: var(--sell); } .chip.hold { background: var(--hold); } .chip.buy { background: var(--buy); }
.figure { display: grid; gap: 0; }
.figure .k { font-size: var(--step--1); color: var(--muted); letter-spacing: 0.04em; }
.figure .v { font-family: var(--font-body); font-size: var(--step-2); font-weight: 600; font-variant-numeric: tabular-nums; }
.figure .v.down { color: var(--sell); } .figure .v.up { color: var(--buy); }
.ladder { width: 100%; max-width: 720px; height: auto; display: block; }
.ladder .zone-buy { fill: var(--buy); } .ladder .zone-hold { fill: var(--hold); } .ladder .zone-sell { fill: var(--sell); }
.ladder .zone-label { fill: var(--on-zone); font-family: var(--font-body); font-size: 13px; font-weight: 600; }
.ladder .mark-label { fill: var(--ink); font-family: var(--font-body); font-size: 13px; font-weight: 600; }
.ladder line { stroke: var(--ink); stroke-width: 2; }
.ladder .mark-tp { stroke-dasharray: 3 3; }
.ladder circle { fill: var(--ink); }
.facts { display: grid; grid-template-columns: minmax(8rem, 12rem) minmax(0, 1fr); margin: 0;
  border-top: 1px solid var(--rule); font-size: 0.9375rem; }
.facts dt, .facts dd { padding: 7px 0; border-bottom: 1px solid var(--rule); margin: 0; }
.facts dt { color: var(--muted); padding-right: 16px; }
.facts dd { min-width: 0; font-variant-numeric: tabular-nums; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 32px; padding-top: 28px; }
nav.toc { font-size: 0.9375rem; }
nav.toc details { border: 1px solid var(--rule); border-radius: 3px; padding: 8px 12px; background: var(--panel); }
nav.toc summary { cursor: pointer; font-weight: 600; }
nav.toc ol { list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 4px; }
nav.toc a { color: var(--ink); text-decoration: none; }
nav.toc a:hover, nav.toc a:focus-visible { color: var(--accent); text-decoration: underline; }
article { min-width: 0; max-width: 46rem; }
article h2 { font-family: var(--font-display); font-size: var(--step-2); line-height: 1.35; margin: 2.4em 0 0.6em;
  padding-top: 0.6em; border-top: 1px solid var(--rule); text-wrap: balance; scroll-margin-top: 16px; }
article h2:first-of-type { margin-top: 1.2em; }
article h3 { font-family: var(--font-display); font-size: var(--step-1); margin: 1.8em 0 0.4em; text-wrap: balance; }
article p, article li { max-width: 42rem; }
article p { margin: 0.7em 0; }
article ul, article ol { padding-left: 1.4em; margin: 0.6em 0; display: grid; gap: 0.35em; }
article strong { font-weight: 600; }
code { font-family: var(--font-data); font-size: 0.85em; background: var(--panel); padding: 1px 5px; border-radius: 3px;
  overflow-wrap: anywhere; }
aside.summary { background: var(--panel); border-left: 3px solid var(--accent); padding: 4px 18px; margin: 1.2em 0;
  font-size: 0.9375rem; line-height: 1.7; }
.table-wrap { overflow-x: auto; margin: 1em 0 1.2em; max-width: 100%; }
article .table-wrap { width: min(100%, 72rem); }
table { border-collapse: collapse; font-size: 0.875rem; line-height: 1.55; min-width: 100%; }
th, td { text-align: left; vertical-align: top; padding: 7px 10px; border-bottom: 1px solid var(--rule); }
thead th { border-bottom: 2px solid var(--ink); font-weight: 600; white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tbody tr:nth-child(even) td { background: color-mix(in srgb, var(--panel) 55%, transparent); }
footer.disclaimer { margin-top: 48px; padding-top: 16px; border-top: 2px solid var(--ink); color: var(--muted);
  font-size: var(--step--1); line-height: 1.7; max-width: 46rem; }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (min-width: 1180px) {
  .layout { grid-template-columns: 15rem minmax(0, 1fr); }
  nav.toc { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px); align-self: start;
    max-height: calc(100vh - 32px); overflow-y: auto; }
  nav.toc details { background: transparent; border: 0; padding: 0; }
  nav.toc summary { list-style: none; font-family: var(--font-data); font-size: var(--step--1); letter-spacing: 0.06em;
    color: var(--muted); }
}
@media (max-width: 640px) {
  h1 { font-size: 1.625rem; }
  .facts { grid-template-columns: minmax(0, 1fr); }
  .facts dt { border-bottom: 0; padding-bottom: 0; font-size: var(--step--1); }
}
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
"""


def main(md_path, numbers_path, out_path, page_title, date, ticker_line):
    md = open(md_path, encoding="utf-8").read()
    nums = json.load(open(numbers_path, encoding="utf-8"))["value"]
    title, facts, blocks, toc, disclaimer = parse(md)
    company, _, headline = title.partition("— ")
    cur = nums.get("quote_currency") or nums.get("currency") or ""
    cur = "NT$" if cur == "TWD" else cur
    spot = nums.get("price_quote") or nums.get("price")
    tp = nums["target_price_12m_quote"]
    trig = nums["price_triggers_quote"]
    up = nums["target_upside_pct"]
    rating = nums.get("rating", "")
    chip_cls = {"Sell": "sell", "Hold": "hold", "Buy": "buy"}.get(rating, "hold")
    rating_text = next((v for k, v in facts if k.startswith("評等")), "")
    dp = 0 if spot >= 1000 else 2
    f = lambda v: ("{:,.%df}" % dp).format(v)
    out = ["<title>%s</title>" % html.escape(page_title),
           '<meta name="claude:viewport-fit-sides" content="cover">',
           '<link rel="preconnect" href="https://fonts.googleapis.com">',
           '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Serif:wght@700&family=Noto+Sans+TC:wght@400;600&family=Noto+Serif+TC:wght@700&display=swap">',
           "<style>%s</style>" % CSS, '<div class="page">', '<header class="cover">',
           '<div class="eyebrow"><span class="ticker">%s</span><span>個股研究</span><span>資料截至 %s</span></div>'
           % (html.escape(ticker_line), html.escape(date)),
           '<p class="company">%s</p>' % inline(company.strip()), "<h1>%s</h1>" % inline(headline.strip() or title),
           '<div class="verdict"><span class="chip %s">%s</span>' % (chip_cls, re.sub(r"<[^>]+>", "", rating_text).split("·")[0].strip()),
           '<div class="figure"><span class="k">12 個月目標價</span><span class="v">%s %s</span></div>' % (cur, f(tp)),
           '<div class="figure"><span class="k">現價</span><span class="v">%s %s</span></div>' % (cur, f(spot)),
           '<div class="figure"><span class="k">潛在漲跌幅</span><span class="v %s">%+.1f%%</span></div></div>'
           % ("down" if up < 0 else "up", up),
           ladder_svg(spot, tp, trig["buy_below"], trig["sell_above"], cur),
           '<dl class="facts">%s</dl>' % "".join("<dt>%s</dt><dd>%s</dd>" % (html.escape(k), v) for k, v in facts),
           "</header>", '<div class="layout"><nav class="toc" aria-label="目錄"><details open><summary>目錄</summary><ol>%s</ol></details></nav>'
           % "".join('<li><a href="#%s">%s</a></li>' % (a, html.escape(t)) for a, t in toc),
           "<article>%s</article></div>" % "".join(blocks),
           '<footer class="disclaimer"><p>%s</p><p>原始檔：<code>%s</code>；數字附錄：<code>%s</code>。</p></footer>'
           % (disclaimer, html.escape(md_path), html.escape(numbers_path.replace(".json", ".md"))),
           "</div>"]
    open(out_path, "w", encoding="utf-8").write("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) != 7:
        sys.exit("usage: render_report.py REPORT.md NUMBERS.json OUT.html TITLE DATE TICKER_LINE")
    main(*sys.argv[1:])
