# ExchangeRate-Viewer

**A tiny Tkinter app that shows the RMB central parity rate for any date, and exports it to Excel.**

It fetches the daily 人民币汇率中间价 announcement, parses the rates out of it, normalises every one of them to **1 CNY = X foreign currency**, shows them in a table, and writes the result to a `.xlsx` on your desktop.

**English** · [中文](README.zh-CN.md)

---

## Where the data actually comes from

The announcement is published on the People's Bank of China website, but its real title is *"China Foreign Exchange Trade System announces the RMB central parity rate under authorisation"* — so the numbers are published by **CFETS**, under PBOC authorisation, with the PBOC site acting as the carrier.

**This tool is not an official channel.** It is a convenience wrapper that scrapes a public web page, does the arithmetic, and lays it out in a table. When the number matters, check the official announcement.

---

## Features

- **Any date** — type `YYYY-MM-DD`, or hit *Latest* for the most recent announcement.
- **Automatic conversion** — the announcement quotes `1 USD = 7.1234 CNY`; the table shows `1 CNY = 0.140382 USD`.
- **Unit-aware** — the announcement quotes most currencies per 1 unit but yen and won per 100. Both forms are handled and normalised to `1 CNY = X`, so **JPY and KRW show up correctly**.
- **Never freezes** — every request runs on a worker thread; the window stays responsive and buttons are re-enabled when the reply lands.
- **Six decimals**, consistently, on screen and in the export.
- **Excel export** — one click, saved to the desktop as `人民币汇率_YYYY-MM-DD.xlsx`, with 币种 and 汇率 columns.
- **Clear** — wipe the table without restarting.

---

## Requirements

- **Python 3.7+**
- `requests`, `pandas`, `openpyxl`
- Network access to `pbc.gov.cn`

```bash
git clone https://github.com/MCNYY117/ExchangeRate-Viewer.git
cd ExchangeRate-Viewer
pip install -r requirements.txt
python pboc_gui.py
```

---

## Using it

The window opens and immediately tries to load the announcement list and the latest rates.

| Button | What it does |
|---|---|
| **刷新公告列表** — Refresh list | Re-fetches the list of available announcements. Use this if the date range shows "请点击刷新". |
| **获取最新** — Latest | Shows the most recent announcement. |
| **查询该日汇率** — Look up date | Shows the announcement for the date you typed. |
| **导出到桌面 Excel** — Export | Writes the current table to an `.xlsx` on your desktop. |
| **清空显示** — Clear | Empties the table. |

The date must be one that was actually loaded into the list; typing a date outside it returns an error rather than searching again.

---

## Output format

Every rate is **1 CNY = X units of the foreign currency**, to six decimals.

| 币种 (currency) | 汇率 (rate) |
|---|---|
| 美元 | 0.140382 |
| 欧元 | 0.132117 |
| 港元 | 1.096200 |

---

## Known limitations

These are real, current behaviours — not hypotheticals:

- **It scrapes HTML.** There is no official API. Parsing is regex over the page's markup and Chinese wording, so a redesign or a class rename can still break it. What it will *not* do is fail quietly: a network error raises a `PBOCError` and a page it cannot parse surfaces as an explicit message, never as a blank table that looks like real data.
- **The site is not fast.** Requests have a 15-second timeout. The UI stays responsive while that runs, but a slow network still means waiting.
- **Unknown currencies are passed through as written.** The parser keys off the Chinese name in the announcement, so a currency the PBOC has not used before appears under whatever name it is quoted with — it is not mapped to a code like `JPY`.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Date range says "请点击刷新" on start | The first list fetch failed | Hit **刷新公告列表**; check your network |
| "没有 XX 的公告数据" | No announcement that day, or a malformed date | Check the date format, or pick from the loaded range |
| Export fails | No write permission on the desktop, or `openpyxl` missing | Check permissions; `pip install openpyxl` |
| Popup: "获取…汇率失败" | The announcement page loaded but nothing could be parsed out of it | The page structure changed — the parser in `_parse_and_convert` needs updating |
| Popup: "访问失败：…" | The request itself failed — offline, blocked, or `pbc.gov.cn` is down | Check the network, then hit **刷新公告列表** |

---

## Notes

- The data is a public government announcement. It can be published late; the official page is authoritative.
- If fetching fails repeatedly, open the [PBOC announcement page](https://www.pbc.gov.cn/zhengcehuobisi/125207/125217/125925/index.html) yourself to check the site is up.
- **The code is MIT licensed** — use and modify it freely. The "check the official source" advice above is about the *data*, not the licence.

---

## Contributing

The UI is Tkinter; the parsing is regex. Parsing bugs and feature requests are welcome as issues or pull requests.

## License

[MIT](LICENSE)
