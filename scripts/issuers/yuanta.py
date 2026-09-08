"""元大投信。網站是 Nuxt SSR，但底層有乾淨的 JSON 閘道 API，且可指定公告日。

    GET https://etfapi.yuantaetfs.com/ectranslation/api/bridge
        ?APIType=ETFAPI&FuncId=PCF/Daily&ticker=<代號>&date=<YYYYMMDD>&...

回傳 PCF（淨資產、受益權單位數、基準日）與 FundWeights（股票／ETF／債券／期貨權重）。
揭露的張數是全基金持股，不是每一申購基數的籃子。
"""
from __future__ import annotations

import uuid

from common import parse_date, retry, split_symbol, to_float

ISSUER = "元大"
SUPPORTS_BACKFILL = True
API = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"

WEIGHT_KIND = {
    "StockWeights": "stock",
    "ETFWeights": "etf",
    "BondWeights": "bond",
    "FutureWeights": "future",
    "FuturesWeights": "future",
}


# 這家的網址就是代號，沒有基金清單可查，所以不能拿來認領「不知道是誰家」的新基金
IDENTITY = True


def discover(sess, codes) -> dict[str, str]:
    return {c: c for c in codes}


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    params = {
        "APIType": "ETFAPI",
        "CompanyName": "YUANTAFUNDS",
        "PageName": f"/tradeInfo/pcf/{code}",
        "DeviceId": str(uuid.uuid4()),
        "FuncId": "PCF/Daily",
        "AppName": "ETF",
        "Device": "3",
        "Platform": "ETF",
        "ticker": code,
    }
    if on_date:
        params["date"] = on_date.strftime("%Y%m%d")

    def call():
        r = sess.get(API, params=params, timeout=45,
                     headers={"Referer": f"https://www.yuantaetfs.com/tradeInfo/pcf/{code}"})
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"yuanta {code}")
    pcf = j.get("PCF") or {}

    holdings = []
    for key, rows in (j.get("FundWeights") or {}).items():
        kind = WEIGHT_KIND.get(key)
        if not kind or not isinstance(rows, list):
            continue
        for row in rows:
            sym, suffix = split_symbol(row.get("code"))
            if not sym:
                continue
            holdings.append({
                "symbol": sym,
                "name": (row.get("name") or "").strip(),
                "market": suffix or "TW",
                "shares": to_float(row.get("qty")),
                "weight": to_float(row.get("weights")),
                "market_value": None,
                "kind": kind,
            })

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": (pcf.get("fundname") or "").strip(),
        "as_of": parse_date(pcf.get("trandate")),
        "basis": "fund",
        "nav_total": to_float(pcf.get("totalav")),
        "fund_units": to_float(pcf.get("osunit")),
        "unit_size": to_float(pcf.get("baseunit")),
        "holdings": holdings,
        "source": "yuantaetfs.com / 申購買回清單 API",
    }
