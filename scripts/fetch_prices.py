"""抓上市（TWSE）與上櫃（TPEx）每日收盤行情，含成交均價。

成交均價 = 成交金額 ÷ 成交股數，是推算 ETF 持股成本的基礎
（每日持股變動 × 當日均價，以平均成本法累積）。

輸出：data/prices/<日期>.json  {symbol: [收盤價, 成交均價, 漲跌%]}
     data/names.json          {symbol: [名稱, 市場]}

只留股票與 ETF；權證有一萬多檔且與本專案無關，全部濾掉，否則光價格資料
每天就要多存好幾百 KB，一年下來 repo 會被撐爆。

用法：
    python scripts/fetch_prices.py                 # 抓今天
    python scripts/fetch_prices.py --date 2026-09-05
    python scripts/fetch_prices.py --backfill 30   # 往回補 30 個日曆天（跳過已存在的）
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta

from common import (DATA, TW_SECURITY_RE, now_tpe, read_json, retry, session, to_float,
                    write_json)

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
TAG_RE = re.compile(r"<[^>]+>")
KEEP_RE = TW_SECURITY_RE


def _sign(raw: str) -> int:
    """漲跌欄是一段帶顏色的 HTML，紅漲綠跌，取符號用。"""
    text = TAG_RE.sub("", str(raw or "")).strip()
    if text.startswith("-") or "green" in str(raw):
        return -1
    if text.startswith("+") or "red" in str(raw):
        return 1
    return 0


def _pct(close: float | None, diff: float | None, sign: int) -> float | None:
    if close is None or diff is None:
        return None
    prev = close - sign * diff
    if not prev:
        return None
    return round(sign * diff / prev * 100, 2)


def fetch_twse(sess, day: date) -> dict:
    def call():
        r = sess.get(TWSE_URL, params={"date": day.strftime("%Y%m%d"), "type": "ALL",
                                       "response": "json"}, timeout=60)
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"twse {day}")
    if j.get("stat") != "OK":
        return {}
    out = {}
    for table in j.get("tables") or []:
        fields = table.get("fields") or []
        if "證券代號" not in fields or "收盤價" not in fields:
            continue
        col = {name: i for i, name in enumerate(fields)}
        for row in table.get("data") or []:
            code = str(row[col["證券代號"]]).strip()
            close = to_float(row[col["收盤價"]])
            if not code or close is None:
                continue
            volume = to_float(row[col["成交股數"]]) or 0
            value = to_float(row[col["成交金額"]]) or 0
            sign = _sign(row[col["漲跌(+/-)"]]) if "漲跌(+/-)" in col else 0
            diff = to_float(row[col["漲跌價差"]]) if "漲跌價差" in col else None
            if not KEEP_RE.match(code):
                continue
            out[code] = ([close, round(value / volume, 4) if volume else close,
                          _pct(close, diff, sign)],
                         [str(row[col["證券名稱"]]).strip(), "TWSE"])
    return out


def fetch_tpex(sess, day: date) -> dict:
    def call():
        r = sess.get(TPEX_URL, params={"date": day.strftime("%Y/%m/%d"), "type": "EW",
                                       "response": "json"}, timeout=60)
        r.raise_for_status()
        return r.json()

    try:
        j = retry(call, label=f"tpex {day}")
    except Exception as exc:  # noqa: BLE001
        print(f"  TPEx {day}: {exc}", file=sys.stderr)
        return {}

    out = {}
    for table in j.get("tables") or []:
        fields = [str(f).strip() for f in (table.get("fields") or [])]
        if not fields or "代號" not in fields:
            continue
        col = {name: i for i, name in enumerate(fields)}
        for row in table.get("data") or []:
            code = str(row[col["代號"]]).strip()
            close = to_float(row[col["收盤"]]) if "收盤" in col else None
            if not code or close is None:
                continue
            volume = to_float(row[col["成交股數"]]) or 0
            value = to_float(row[col["成交金額(元)"]]) or 0
            diff = to_float(row[col["漲跌"]]) if "漲跌" in col else None
            sign = -1 if (diff is not None and diff < 0) else (1 if diff else 0)
            if not KEEP_RE.match(code):
                continue
            out[code] = ([close, round(value / volume, 4) if volume else close,
                          _pct(close, abs(diff) if diff else None, sign)],
                         [str(row[col["名稱"]]).strip(), "TPEx"])
    return out


def fetch_day(sess, day: date) -> int:
    path = DATA / "prices" / f"{day.isoformat()}.json"
    rows = fetch_twse(sess, day)
    if not rows:
        return 0  # 非交易日
    for code, row in fetch_tpex(sess, day).items():
        rows.setdefault(code, row)

    prices = {code: quote for code, (quote, _) in rows.items()}
    prev = read_json(path) or {}
    payload = {"date": day.isoformat(),
               "fetched_at": now_tpe().isoformat(timespec="seconds"),
               "prices": prices}
    if prev.get("prices") == prices:
        payload["fetched_at"] = prev.get("fetched_at", payload["fetched_at"])
    write_json(path, payload)

    # 名稱與市場另外存一份累積的對照表，不必每天重複寫
    names_path = DATA / "names.json"
    names = read_json(names_path) or {}
    changed = False
    for code, (_, meta) in rows.items():
        if names.get(code) != meta:
            names[code] = meta
            changed = True
    if changed:
        write_json(names_path, dict(sorted(names.items())))
    return len(prices)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，預設今天")
    ap.add_argument("--backfill", type=int, default=0, help="往回補幾個日曆天")
    args = ap.parse_args()

    sess = session("https://www.twse.com.tw/")
    today = date.fromisoformat(args.date) if args.date else now_tpe().date()

    days = [today]
    if args.backfill:
        days = [today - timedelta(days=i) for i in range(args.backfill, -1, -1)]

    total = 0
    for day in days:
        if day.weekday() >= 5:
            continue
        path = DATA / "prices" / f"{day.isoformat()}.json"
        if args.backfill and path.exists():
            continue  # 已經有了就不重抓
        n = fetch_day(sess, day)
        if n:
            total += 1
            print(f"  {day} {n} 檔")
    print(f"prices: {total} 個交易日")
    return 0 if total or not days else 1


if __name__ == "__main__":
    raise SystemExit(main())
