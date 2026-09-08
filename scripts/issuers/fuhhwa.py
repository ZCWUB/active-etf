"""復華投信。

申購買回清單只有現金部位的數字，真正的持股在「基金資產」：
    GET /api/assets?fundID=<內部代號>&qDate=<YYYY/MM/DD>
可帶日期，所以支援回補。內部代號（ETF23 之類）由 /api/fundList 對照 etf002 取得。
"""
from __future__ import annotations

from common import now_tpe, parse_date, retry, split_symbol, to_float

ISSUER = "復華"
SUPPORTS_BACKFILL = True
BASE = "https://www.fhtrust.com.tw"
LIST_URL = f"{BASE}/api/fundList?ec001=3"
ASSETS_URL = f"{BASE}/api/assets"

FTYPE_KIND = {"股票": "stock", "ETF": "etf", "債券": "bond", "期貨": "future"}


def discover(sess, codes) -> dict[str, str]:
    def call():
        r = sess.get(LIST_URL, timeout=40)
        r.raise_for_status()
        return r.json()

    rows = retry(call, label="fuhhwa fundList").get("result") or []
    return {(r.get("etf002") or "").strip().upper(): r.get("fundID")
            for r in rows if r.get("etf002") and r.get("fundID")}


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    # 這支 API 少了 qDate 會回 HTML，一律帶日期
    params = {"fundID": internal_id,
              "qDate": (on_date or now_tpe().date()).strftime("%Y/%m/%d")}

    def call():
        r = sess.get(ASSETS_URL, params=params, timeout=45,
                     headers={"Referer": f"{BASE}/ETF/etf_detail/{internal_id}"})
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"fuhhwa {code}")
    rows = j.get("result") or []
    if not rows:
        raise ValueError("no assets returned")
    doc = rows[0]

    holdings = []
    for d in doc.get("detail") or []:
        sym, suffix = split_symbol(d.get("stockid"))
        if not sym:
            continue
        kind = FTYPE_KIND.get((d.get("ftype") or "").strip(), "other")
        if kind == "other":
            continue  # 現金與應收付款項不列入持股
        currency = (d.get("qshareCur") or "NTD").strip().upper()
        holdings.append({
            "symbol": sym,
            "name": (d.get("stockname") or "").strip(),
            "market": suffix or ("TW" if currency in {"NTD", "TWD"} else currency[:2]),
            "shares": to_float(d.get("qshare")),
            "weight": to_float(d.get("prate_addaccint")),
            "market_value": to_float(d.get("mvalue")) if currency in {"NTD", "TWD"} else None,
            "kind": kind,
        })

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": (doc.get("twNameFull") or "").strip(),
        "as_of": parse_date(doc.get("dDate")),
        "basis": "fund",
        "nav_total": to_float(doc.get("pcf_FundNav")),
        "fund_units": to_float(doc.get("pcf_FundQissue")),
        "unit_size": None,
        "holdings": holdings,
        "source": "fhtrust.com.tw / 基金資產明細",
    }
