"""抓主動式 ETF 清單（代號、名稱、發行投信、規模、受益人數）。

來源：證交所 ETF e添富投資篩選器 ajaxProductsResult。
主動式 ETF 代號規則：00xxxA（股票型）、00xxxD（債券型）。
"""
from __future__ import annotations

import re
import sys

from common import DATA, now_tpe, retry, session, to_float, write_json

URL = "https://www.twse.com.tw/zh/ETFortune/ajaxProductsResult"
REFERER = "https://www.twse.com.tw/zh/ETFortune/products"
MIS_URL = "https://mis.twse.com.tw/stock/data/all_etf.txt"
MIS_REFERER = "https://mis.twse.com.tw/stock/index.jsp"
ACTIVE_RE = re.compile(r"^00\d{3}[AD]$")


def from_mis(known: set[str]) -> list[dict]:
    """證交所篩選器偶爾會漏掉剛掛牌的基金，用 MIS 即時報價補齊。

    這裡拿不到發行投信，留空由 fetch_pcf 依各投信自己的清單認領。
    """
    s = session(MIS_REFERER)
    try:
        rows = [x for g in retry(lambda: s.get(MIS_URL, timeout=30).json(), label="mis").get("a1", [])
                for x in g.get("msgArray", [])]
    except Exception as exc:  # noqa: BLE001
        print(f"MIS 補齊失敗，略過：{exc}", file=sys.stderr)
        return []
    extra = []
    for x in rows:
        code = (x.get("a") or "").strip().upper()
        if not ACTIVE_RE.match(code) or code in known:
            continue
        units, nav = to_float(x.get("c")), to_float(x.get("f"))
        extra.append({
            "code": code,
            "name": (x.get("b") or "").strip(),
            "issuer": "",
            "kind": "bond" if code.endswith("D") else "equity",
            "listing_date": "",
            "aum_100m": (units * nav / 1e8) if units and nav else None,
            "holders": None,
            "close": to_float(x.get("e")),
        })
    return extra


def main() -> int:
    s = session(REFERER)
    s.headers["X-Requested-With"] = "XMLHttpRequest"

    def call():
        r = s.post(URL, data={}, timeout=30)
        r.raise_for_status()
        return r.json()

    payload = retry(call, label="twse products")
    rows = [r for r in payload.get("data", []) if ACTIVE_RE.match(r.get("stockNo", ""))]
    if not rows:
        print("no active ETF rows returned", file=sys.stderr)
        return 1

    funds = []
    for r in rows:
        issuer = (r.get("issuer") or "").replace("證券投資信託股份有限公司", "").strip()
        funds.append({
            "code": r["stockNo"],
            "name": r.get("stockName", "").strip(),
            "issuer": issuer,
            "kind": "bond" if r["stockNo"].endswith("D") else "equity",
            "listing_date": (r.get("listingDate") or "").replace(".", "-"),
            "aum_100m": to_float(r.get("totalAv")),
            "holders": to_float(r.get("holders")),
            "close": to_float(r.get("close1")),
        })
    funds += from_mis({f["code"] for f in funds})
    funds.sort(key=lambda f: -(f["aum_100m"] or 0))

    write_json(DATA / "universe.json", {
        "updated_at": now_tpe().isoformat(timespec="seconds"),
        "source": "TWSE ETF e添富",
        "count": len(funds),
        "funds": funds,
    })
    print(f"universe: {len(funds)} active ETFs from {len({f['issuer'] for f in funds})} issuers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
