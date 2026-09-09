"""抓三大法人（主要取外資）每日買賣超股數，用來判斷 ETF 的動作是否與外資同向。

來源：TWSE 三大法人買賣超日報（上市）與 TPEx 法人買賣超（上櫃）。
輸出：data/inst/<日期>.json  {symbol: 外資買賣超股數}
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from common import (DATA, TW_SECURITY_RE, now_tpe, read_json, retry, session, to_float,
                    write_json)

TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/insti/summary"


def fetch_twse(sess, day: date) -> dict:
    def call():
        r = sess.get(TWSE_URL, params={"date": day.strftime("%Y%m%d"), "selectType": "ALL",
                                       "response": "json"}, timeout=60)
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"t86 {day}")
    if j.get("stat") != "OK":
        return {}
    fields = j.get("fields") or []
    col = {name: i for i, name in enumerate(fields)}
    # 欄位名是「外陸資買賣超股數(不含外資自營商)」，不是「外資買賣超股數」
    key = next((f for f in fields if f.startswith("外") and "買賣超股數" in f), None)
    if not key:
        return {}
    out = {}
    for row in j.get("data") or []:
        code = str(row[col["證券代號"]]).strip()
        net = to_float(row[col[key]])
        if net is not None and TW_SECURITY_RE.match(code):
            out[code] = net
    return out


def fetch_tpex(sess, day: date) -> dict:
    def call():
        r = sess.get(TPEX_URL, params={"date": day.strftime("%Y/%m/%d"), "type": "Daily",
                                       "response": "json"}, timeout=60)
        r.raise_for_status()
        return r.json()

    try:
        j = retry(call, label=f"tpex inst {day}")
    except Exception as exc:  # noqa: BLE001
        print(f"  TPEx 法人 {day}: {exc}", file=sys.stderr)
        return {}

    out = {}
    for table in j.get("tables") or []:
        fields = [str(f).strip() for f in (table.get("fields") or [])]
        if "代號" not in fields:
            continue
        col = {name: i for i, name in enumerate(fields)}
        key = next((f for f in fields if "外資" in f and "買賣超" in f), None)
        if not key:
            continue
        for row in table.get("data") or []:
            code = str(row[col["代號"]]).strip()
            net = to_float(row[col[key]])
            if net is not None and TW_SECURITY_RE.match(code):
                out.setdefault(code, net)
    return out


def fetch_day(sess, day: date) -> int:
    data = fetch_twse(sess, day)
    if not data:
        return 0
    for code, net in fetch_tpex(sess, day).items():
        data.setdefault(code, net)

    path = DATA / "inst" / f"{day.isoformat()}.json"
    prev = read_json(path) or {}
    payload = {"date": day.isoformat(),
               "fetched_at": now_tpe().isoformat(timespec="seconds"),
               "foreign_net_shares": data}
    if prev.get("foreign_net_shares") == data:
        payload["fetched_at"] = prev.get("fetched_at", payload["fetched_at"])
    write_json(path, payload)
    return len(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", type=int, default=0)
    args = ap.parse_args()

    sess = session("https://www.twse.com.tw/")
    today = date.fromisoformat(args.date) if args.date else now_tpe().date()
    days = [today] if not args.backfill else [
        today - timedelta(days=i) for i in range(args.backfill, -1, -1)]

    total = 0
    for day in days:
        if day.weekday() >= 5:
            continue
        if args.backfill and (DATA / "inst" / f"{day.isoformat()}.json").exists():
            continue
        n = fetch_day(sess, day)
        if n:
            total += 1
            print(f"  {day} {n} 檔")
    print(f"institutions: {total} 個交易日")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
