"""抓證交所 MIS 的 ETF 淨值／市價／折溢價／受益權單位數。

來源：https://mis.twse.com.tw/stock/data/all_etf.txt
欄位：a=代號 b=名稱 c=已發行受益權單位數 d=當日單位增減 e=市價 f=淨值 g=折溢價%
     i=日期 j=時間
d（單位增減）等於當日淨申購／買回，是主動式 ETF 的資金流指標。
輸出：data/quotes/<日期>.json
"""
from __future__ import annotations

import re
import sys

from common import DATA, now_tpe, read_json, retry, session, to_float, write_json

URL = "https://mis.twse.com.tw/stock/data/all_etf.txt"
REFERER = "https://mis.twse.com.tw/stock/index.jsp"
ACTIVE_RE = re.compile(r"^00\d{3}[AD]$")


def main() -> int:
    s = session(REFERER)

    def call():
        r = s.get(URL, timeout=30)
        r.raise_for_status()
        return r.json()

    j = retry(call, label="mis all_etf")
    rows = [x for g in j.get("a1", []) for x in g.get("msgArray", [])]
    if not rows:
        print("MIS returned no rows", file=sys.stderr)
        return 1

    quotes, trade_date = {}, ""
    for x in rows:
        code = (x.get("a") or "").strip().upper()
        if not ACTIVE_RE.match(code):
            continue
        d = str(x.get("i") or "")
        if len(d) == 8:
            trade_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        quotes[code] = {
            "price": to_float(x.get("e")),
            "nav": to_float(x.get("f")),
            "premium_pct": to_float(x.get("g")),
            "units": to_float(x.get("c")),
            "units_change": to_float(x.get("d")),
            "quoted_at": (x.get("j") or "").strip(),
        }
    for q in quotes.values():
        if q["units"] and q["nav"]:
            q["aum"] = q["units"] * q["nav"]

    if not trade_date:
        trade_date = now_tpe().date().isoformat()

    path = DATA / "quotes" / f"{trade_date}.json"
    prev = read_json(path) or {}
    payload = {
        "date": trade_date,
        "fetched_at": now_tpe().isoformat(timespec="seconds"),
        "source": "TWSE MIS all_etf",
        "quotes": quotes,
    }
    if prev.get("quotes") == quotes:
        payload["fetched_at"] = prev.get("fetched_at", payload["fetched_at"])
    write_json(path, payload)
    print(f"quotes {trade_date}: {len(quotes)} active ETFs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
