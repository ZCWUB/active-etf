"""聯博投信（AllianceBernstein）。

    GET https://webapi.alliancebernstein.com/v2/funds/tw/zh-tw/investor/<ISIN>/holdings?date=YYYY-MM-DD

ISIN 由代號直接算（TW000 + 代號 + 檢查碼），不必另外查對照表。
回傳 domesticHoldings[]，每組是一個資產類別（股票／期貨／選擇權），組裡才是持股。
"""
from __future__ import annotations

from common import is_symbol_like, parse_date, retry, split_symbol, to_float, twse_isin

ISSUER = "聯博"
SUPPORTS_BACKFILL = True
IDENTITY = True
API = "https://webapi.alliancebernstein.com/v2/funds/tw/zh-tw/investor/{isin}/holdings"
REFERER = "https://www.abfunds.com.tw/"

CATEGORY_KIND = {
    "holdings-section-equity": "stock",
    "holdings-section-fixedincome": "bond",
    "holdings-section-bond": "bond",
    "holdings-section-etf": "etf",
    "holdings-section-futures": "future",
    "holdings-section-options": "option",
}


def discover(sess, codes) -> dict[str, str]:
    return {c: twse_isin(c) for c in codes}


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    params = {"date": on_date.strftime("%Y-%m-%d")} if on_date else None

    def call():
        r = sess.get(API.format(isin=internal_id), params=params, timeout=45,
                     headers={"Referer": REFERER})
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"ab {code}")

    holdings, as_of = [], ""
    for group in j.get("domesticHoldings") or []:
        kind = CATEGORY_KIND.get(group.get("holdingCategory"))
        as_of = as_of or parse_date(group.get("asOfDate"))
        if kind in (None, "option"):
            continue  # 選擇權沒有證券代號，不列入持股統計
        for h in group.get("holdings") or []:
            sym, suffix = split_symbol(h.get("holdingCode"))
            if not is_symbol_like(sym):
                continue
            holdings.append({
                "symbol": sym,
                "name": (h.get("holding") or "").strip(),
                "market": suffix or "TW",
                "shares": to_float(h.get("holdingShares")),
                "weight": to_float(h.get("holdingPerc")),
                "market_value": to_float(h.get("holdingValue")),
                "kind": kind,
            })

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": "",
        "as_of": as_of,
        "basis": "fund",
        "nav_total": None,
        "fund_units": None,
        "unit_size": None,
        "holdings": holdings,
        "source": "abfunds.com.tw / 申購買回清單",
    }
