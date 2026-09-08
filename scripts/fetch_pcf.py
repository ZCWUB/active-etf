"""逐檔抓主動式 ETF 的持股／申購買回清單，存成每日快照。

輸出：data/pcf/<代號>/<資料基準日>.json
     data/fetch_report.json（每次執行的成功/失敗紀錄）
"""
from __future__ import annotations

import argparse
import sys
import traceback

from datetime import timedelta

from common import DATA, now_tpe, read_json, session, write_json
from issuers import ADAPTERS, BY_ISSUER


def validate(snap: dict) -> None:
    if not snap.get("as_of"):
        raise ValueError("missing as_of")
    holdings = snap.get("holdings") or []
    if not holdings:
        raise ValueError("no holdings")
    if not any(h.get("weight") or h.get("shares") for h in holdings):
        raise ValueError("holdings have neither weight nor shares")


def fetch_latest(mod, sess, code: str, internal: str) -> dict:
    """抓最新一筆。海外型基金當天常常還沒公告，就往回找幾個營業日。"""
    try:
        snap = mod.fetch(sess, code, internal)
        validate(snap)
        return snap
    except Exception:
        if not getattr(mod, "SUPPORTS_BACKFILL", False):
            raise
    today = now_tpe().date()
    last = None
    for back in range(1, 8):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        try:
            snap = mod.fetch(sess, code, internal, on_date=day)
            validate(snap)
            return snap
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"no usable snapshot in the last 7 days: {last}")


def save(snap: dict) -> tuple[str, bool]:
    path = DATA / "pcf" / snap["code"] / f"{snap['as_of']}.json"
    old = read_json(path)
    changed = old is None or old.get("holdings") != snap.get("holdings")
    snap = dict(snap, fetched_at=now_tpe().isoformat(timespec="seconds"))
    if old and not changed:
        # 內容沒變就保留原本的 fetched_at，避免每天產生無意義的 diff
        snap["fetched_at"] = old.get("fetched_at", snap["fetched_at"])
    write_json(path, snap)
    return str(path.relative_to(DATA.parent)), changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="只抓這些 ETF 代號")
    ap.add_argument("--issuer", nargs="*", help="只抓這些投信")
    args = ap.parse_args()

    universe = read_json(DATA / "universe.json") or {}
    funds = universe.get("funds") or []
    if not funds:
        print("universe.json is empty — run fetch_universe.py first", file=sys.stderr)
        return 1

    wanted = {f["code"]: f for f in funds}
    if args.only:
        wanted = {c: f for c, f in wanted.items() if c in set(args.only)}
    if args.issuer:
        wanted = {c: f for c, f in wanted.items() if f["issuer"] in set(args.issuer)}

    ok, failed, skipped = [], [], []
    claimed: set[str] = set()
    unknown = [c for c, f in wanted.items() if not f["issuer"]]
    for mod in ADAPTERS:
        codes = [c for c, f in wanted.items() if f["issuer"] == mod.ISSUER]
        # 只有「查得到自家基金清單」的投信才有資格認領來源不明的新基金
        probe = sorted(set(codes)) if getattr(mod, "IDENTITY", False)             else sorted(set(codes) | (set(unknown) - claimed))
        if not probe:
            continue
        sess = session()
        try:
            found = mod.discover(sess, probe)
        except Exception as exc:  # noqa: BLE001
            for c in codes:
                failed.append({"code": c, "issuer": mod.ISSUER, "error": f"discover: {exc}"})
            continue
        # 清單裡沒標發行投信的（多半是剛掛牌），哪一家查得到就算誰的
        codes = sorted(set(codes) | {c for c in unknown if c in found and c not in claimed})
        claimed.update(codes)
        for code in codes:
            internal = found.get(code)
            if not internal:
                failed.append({"code": code, "issuer": mod.ISSUER, "error": "not found on issuer site"})
                continue
            try:
                snap = fetch_latest(mod, sess, code, internal)
                validate(snap)
                path, changed = save(snap)
                ok.append({"code": code, "issuer": mod.ISSUER, "as_of": snap["as_of"],
                           "holdings": len(snap["holdings"]), "basis": snap["basis"],
                           "changed": changed})
                print(f"  {code} {mod.ISSUER:<5} {snap['as_of']} "
                      f"{len(snap['holdings']):>3} 檔 ({snap['basis']})")
            except Exception as exc:  # noqa: BLE001
                failed.append({"code": code, "issuer": mod.ISSUER,
                               "error": f"{type(exc).__name__}: {exc}"})
                print(f"  {code} {mod.ISSUER:<5} FAILED {exc}", file=sys.stderr)
                if "--debug" in sys.argv:
                    traceback.print_exc()

    covered = {m.ISSUER for m in ADAPTERS}
    skipped = sorted({f["issuer"] for f in wanted.values() if f["issuer"]} - covered)

    write_json(DATA / "fetch_report.json", {
        "ran_at": now_tpe().isoformat(timespec="seconds"),
        "ok": ok, "failed": failed, "issuers_without_adapter": skipped,
    })
    print(f"\n{len(ok)} ok / {len(failed)} failed / {len(skipped)} issuers without adapter")
    if skipped:
        print("no adapter yet: " + "、".join(skipped))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
