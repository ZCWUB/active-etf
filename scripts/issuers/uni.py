"""統一投信（ezmoney）。現金申贖制，直接公告全基金投資組合明細。"""
from __future__ import annotations

import re

from common import CURRENCY_MARKET, now_tpe, parse_date, retry, split_symbol, to_float

ISSUER = "統一"
BASE = "https://www.ezmoney.com.tw"
LIST_URL = f"{BASE}/ETF/Fund/Index"
PCF_URL = f"{BASE}/ETF/Transaction/GetPCF"

# 資產類別 → 我們的分類
ASSET_KIND = {"ST": "stock", "GD": "future", "BD": "bond", "ETF": "etf", "CA": "cash"}


def _roc(d) -> str:
    return f"{d.year - 1911:03d}/{d.month:02d}/{d.day:02d}"


def discover(sess, codes) -> dict[str, str]:
    r = retry(lambda: sess.get(LIST_URL, timeout=30), label="uni list")
    r.raise_for_status()
    # <a href="/ETF/Fund/Info?fundCode=49YTW">00981A主動統一台股增長</a>
    pairs = re.findall(r'fundCode=([0-9A-Z]+)"[^>]*>\s*(00\d{3}[A-Z])', r.text)
    return {code: fund for fund, code in pairs}


SUPPORTS_BACKFILL = True  # 帶 specificDate 可回查歷史公告日


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    """on_date 是「公告日」，回傳的持股基準日通常是前一個營業日。"""
    payload = {
        "fundCode": internal_id,
        "date": _roc(on_date or now_tpe().date()),
        "specificDate": bool(on_date),
    }

    def call():
        r = sess.post(PCF_URL, json=payload, timeout=40)
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"uni {code}")

    meta = {row.get("PCFCode"): to_float(row.get("Amount")) for row in j.get("pcf") or []}
    tran = None
    holdings = []
    for group in j.get("asset") or []:
        kind = ASSET_KIND.get(group.get("AssetCode"), "other")
        for d in group.get("Details") or []:
            tran = tran or d.get("TranDate")
            sym, suffix = split_symbol(d.get("DetailCode"))
            currency = (d.get("MoneyType") or group.get("MoneyType") or "NTD").strip().upper()
            market = suffix or CURRENCY_MARKET.get(currency, "TW")
            amount = to_float(d.get("Amount"))
            holdings.append({
                "symbol": sym,
                "name": (d.get("DetailName") or "").strip(),
                "market": market,
                "currency": currency,
                "shares": to_float(d.get("Share")),
                "weight": to_float(d.get("NavRate")),
                # Amount 是以標的當地幣別計價，只有台股可以直接當台幣市值用
                "market_value": amount if market == "TW" else None,
                "kind": kind,
            })

    fund = j.get("fund") or {}
    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": (fund.get("sFundName") or "").strip(),
        "as_of": parse_date(tran),
        "basis": "fund",
        "nav_total": meta.get("NAV"),
        "fund_units": meta.get("UNIT") or meta.get("TOTAL_UNIT"),
        "unit_size": None,
        "holdings": holdings,
        "source": "ezmoney.com.tw / 申購買回清單+投資組合明細",
    }
