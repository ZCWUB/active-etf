"""國泰投信。

網站是 Angular，資料都打 cwapi.cathaysite.com.tw：
    /api/Fund/GetFundList              代號對照（fundCode ↔ stockCode）
    /api/ETF/GetETFDetail{Stock,Bond,Future,ETF}List?FundCode=&SearchDate=
    /api/ETF/GetETFAssets              基金淨資產、流通單位數
帶 SearchDate 即可回補歷史。
"""
from __future__ import annotations

from common import now_tpe, parse_date, retry, split_symbol, to_float

ISSUER = "國泰"
SUPPORTS_BACKFILL = True
API = "https://cwapi.cathaysite.com.tw/api"
REFERER = "https://www.cathaysite.com.tw/"

DETAIL_LISTS = {
    "GetETFDetailStockList": "stock",
    "GetETFDetailBondList": "bond",
    "GetETFDetailFutureList": "future",
    "GetETFDetailETFList": "etf",
}


def _get(sess, path: str, params: dict):
    def call():
        r = sess.get(f"{API}/{path}", params=params, timeout=40, headers={"Referer": REFERER})
        r.raise_for_status()
        return r.json()

    return retry(call, label=f"cathay {path}")


def discover(sess, codes) -> dict[str, str]:
    j = _get(sess, "Fund/GetFundList", {"CurrentPage": 1, "PerPageCount": 300, "status": 1})
    out = {}
    for r in j.get("result") or []:
        code = (r.get("stockCode") or "").strip().upper()
        if code and r.get("fundCode"):
            out[code] = r["fundCode"]
    return out


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    date = (on_date or now_tpe().date()).strftime("%Y-%m-%d")
    params = {"FundCode": internal_id, "SearchDate": date, "status": 1}

    holdings = []
    for path, kind in DETAIL_LISTS.items():
        rows = _get(sess, f"ETF/{path}", params).get("result") or []
        for r in rows:
            sym, suffix = split_symbol(r.get("stockCode") or r.get("bondCode") or r.get("code"))
            if not sym:
                continue
            holdings.append({
                "symbol": sym,
                "name": (r.get("stockName") or r.get("bondName") or r.get("name") or "").strip(),
                "market": suffix or "TW",
                "shares": to_float(r.get("volumn") or r.get("volume")),
                "weight": to_float(r.get("weights") or r.get("weight")),
                "market_value": None,
                "kind": kind,
            })

    assets = _get(sess, "ETF/GetETFAssets", params).get("result") or {}
    if isinstance(assets, list):
        assets = assets[0] if assets else {}

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": "",
        "as_of": parse_date(assets.get("preDate")) or date,
        "basis": "fund",
        "nav_total": to_float(assets.get("fundNav")),
        "fund_units": to_float(assets.get("fundOutstandingShares")),
        "unit_size": None,
        "holdings": holdings,
        "source": "cathaysite.com.tw / 持股權重",
    }
