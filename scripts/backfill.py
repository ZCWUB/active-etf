"""回補歷史持股。

部分投信（目前是統一）可指定公告日查詢，能把過去幾週的持股補齊，
網站第一天就有加減碼可看，不必等隔天。
"""
from __future__ import annotations

import argparse
from datetime import timedelta

from common import now_tpe, read_json, session, DATA
from fetch_pcf import save, validate
from issuers import ADAPTERS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="往回幾個日曆天")
    ap.add_argument("--only", nargs="*", help="只回補這些 ETF 代號")
    ap.add_argument("--issuer", nargs="*", help="只回補這些投信")
    args = ap.parse_args()

    universe = read_json(DATA / "universe.json") or {}
    funds = {f["code"]: f for f in universe.get("funds") or []}
    if args.only:
        funds = {c: f for c, f in funds.items() if c in set(args.only)}
    if args.issuer:
        funds = {c: f for c, f in funds.items() if f["issuer"] in set(args.issuer)}

    today = now_tpe().date()
    saved = skipped = 0
    for mod in ADAPTERS:
        if not getattr(mod, "SUPPORTS_BACKFILL", False):
            continue
        codes = [c for c, f in funds.items() if f["issuer"] == mod.ISSUER]
        if not codes:
            continue
        sess = session()
        found = mod.discover(sess, codes)
        for code in codes:
            internal = found.get(code)
            if not internal:
                continue
            for back in range(args.days, -1, -1):
                day = today - timedelta(days=back)
                if day.weekday() >= 5:  # 週末沒有公告
                    continue
                try:
                    snap = mod.fetch(sess, code, internal, on_date=day)
                    validate(snap)
                except Exception:  # noqa: BLE001 — 非營業日/尚無資料是常態
                    skipped += 1
                    continue
                path, changed = save(snap)
                saved += 1
                print(f"  {code} 公告日 {day} → 基準日 {snap['as_of']} "
                      f"{len(snap['holdings'])} 檔{'' if changed else '（已存在）'}")
    print(f"\nbackfilled {saved} snapshots ({skipped} days had no data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
