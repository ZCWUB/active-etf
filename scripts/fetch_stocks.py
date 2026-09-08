"""抓上市（TWSE）與上櫃（TPEx）個股當日收盤價，供估算持股市值用。

輸出：data/stocks/<日期>.json  {symbol: {"name":..., "close":..., "market":"TWSE"|"TPEx"}}
"""
from __future__ import annotations

import sys

from common import DATA, now_tpe, read_json, retry, session, to_float, write_json

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def _get(sess, url, label):
    def call():
        r = sess.get(url, timeout=45)
        r.raise_for_status()
        return r.json()

    try:
        return retry(call, label=label)
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: {exc}", file=sys.stderr)
        return []


def main() -> int:
    sess = session()
    out = {}

    for row in _get(sess, TWSE_URL, "twse stock_day_all"):
        code = (row.get("Code") or "").strip()
        close = to_float(row.get("ClosingPrice"))
        if code and close:
            out[code] = {"name": (row.get("Name") or "").strip(), "close": close, "market": "TWSE"}

    for row in _get(sess, TPEX_URL, "tpex daily close"):
        code = (row.get("SecuritiesCompanyCode") or row.get("Code") or "").strip()
        close = to_float(row.get("Close") or row.get("ClosingPrice"))
        if code and close and code not in out:
            out[code] = {"name": (row.get("CompanyName") or row.get("Name") or "").strip(),
                         "close": close, "market": "TPEx"}

    if not out:
        print("no stock closes fetched", file=sys.stderr)
        return 1

    date = now_tpe().date().isoformat()
    path = DATA / "stocks" / f"{date}.json"
    prev = read_json(path) or {}
    payload = {"date": date, "fetched_at": now_tpe().isoformat(timespec="seconds"), "stocks": out}
    if prev.get("stocks") == out:
        payload["fetched_at"] = prev.get("fetched_at", payload["fetched_at"])
    write_json(path, payload)
    print(f"stock closes {date}: {len(out)} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
