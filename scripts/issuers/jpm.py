"""摩根投信（J.P. Morgan Asset Management 台灣）。

    GET /FundsMarketingHandler/product-data?cusip=<ISIN>&country=tw&role=twetf&language=zh
持股在 fundData.holdings 底下，依資產類別分成 pcfEquityHoldings / pcfBondHoldings / … 幾組。
"""
from __future__ import annotations

from common import is_symbol_like, parse_date, retry, split_symbol, to_float, twse_isin

ISSUER = "摩根"
IDENTITY = True
API = "https://am.jpmorgan.com/FundsMarketingHandler/product-data"
REFERER = "https://am.jpmorgan.com/tw/zh/asset-management/twetf/"

SECTION_KIND = {
    "pcfEquityHoldings": "stock",
    "pcfBondHoldings": "bond",
    "pcfFutureHoldings": "future",
}


def discover(sess, codes) -> dict[str, str]:
    return {c: twse_isin(c) for c in codes}


def fetch(sess, code: str, internal_id: str) -> dict:
    params = {"cusip": internal_id, "country": "tw", "role": "twetf",
              "language": "zh", "userLoggedIn": "false"}

    def call():
        r = sess.get(API, params=params, timeout=45, headers={"Referer": REFERER})
        r.raise_for_status()
        return r.json()

    fund_data = (retry(call, label=f"jpm {code}").get("fundData") or {})
    sections = fund_data.get("holdings") or {}

    holdings, as_of = [], ""
    for key, kind in SECTION_KIND.items():
        section = sections.get(key)
        if not isinstance(section, dict):
            continue
        as_of = as_of or parse_date(section.get("effectiveDate"))
        for h in section.get("data") or []:
            sym, suffix = split_symbol(h.get("securityTicker"))
            if not is_symbol_like(sym):
                continue
            holdings.append({
                "symbol": sym,
                "name": (h.get("securityDescription") or "").strip(),
                "market": suffix or "TW",
                "shares": to_float(h.get("shares")),
                "weight": to_float(h.get("marketValuePercent")),
                "market_value": to_float(h.get("marketValueBase")),
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
        "source": "am.jpmorgan.com / 申購買回清單",
    }
