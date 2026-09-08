"""野村投信（也用同一套平台的其他投信可共用這支 adapter）。

    POST /API/ETFAPI/api/Fund/GetFundAssets  {"FundID": "<代號>"}
回傳 Entries.Data.FundAsset（規模、單位數、淨值日）與 Table[]，
每個 Table 有 Columns（欄位名）與 Rows（純陣列），依表頭判斷是股票／期貨／債券。
沒有日期參數，所以只能拿最新一日。
"""
from __future__ import annotations

from common import is_symbol_like, parse_date, retry, split_symbol, to_float

ISSUER = "野村"
IDENTITY = True
BASE = "https://www.nomurafunds.com.tw"
API = f"{BASE}/API/ETFAPI/api/Fund/GetFundAssets"
REFERER = f"{BASE}/ETFWEB/product-description"

TITLE_KIND = {"股票": "stock", "債券": "bond", "期貨": "future", "ETF": "etf"}


def discover(sess, codes) -> dict[str, str]:
    return {c: c for c in codes}


def _columns(cols: list[dict]) -> dict[str, int]:
    idx = {}
    for i, c in enumerate(cols):
        name = c.get("Name") or ""
        if ("代號" in name or "代碼" in name) and "symbol" not in idx:
            idx["symbol"] = i
        elif "名稱" in name and "name" not in idx:
            idx["name"] = i
        elif any(k in name for k in ("股數", "口數", "面額", "數量")) and "shares" not in idx:
            idx["shares"] = i
        elif "權重" in name and "weight" not in idx:
            idx["weight"] = i
    return idx


def fetch(sess, code: str, internal_id: str) -> dict:
    def call():
        r = sess.post(API, json={"FundID": code}, timeout=45, headers={"Referer": REFERER})
        r.raise_for_status()
        return r.json()

    data = (retry(call, label=f"nomura {code}").get("Entries") or {}).get("Data") or {}
    asset = data.get("FundAsset") or {}

    holdings = []
    for table in data.get("Table") or []:
        title = (table.get("TableTitle") or "").strip()
        kind = TITLE_KIND.get(title)
        if not kind:
            continue
        idx = _columns(table.get("Columns") or [])
        if "symbol" not in idx or "weight" not in idx:
            continue
        for row in table.get("Rows") or []:
            if len(row) <= max(idx.values()):
                continue
            sym, suffix = split_symbol(row[idx["symbol"]])
            if not is_symbol_like(sym):
                continue
            holdings.append({
                "symbol": sym,
                "name": str(row[idx["name"]]).strip() if "name" in idx else "",
                "market": suffix or "TW",
                "shares": to_float(row[idx["shares"]]) if "shares" in idx else None,
                "weight": to_float(row[idx["weight"]]),
                "market_value": None,
                "kind": kind,
            })

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": "",
        "as_of": parse_date(asset.get("NavDate")),
        "basis": "fund",
        "nav_total": to_float(asset.get("Aum")),
        "fund_units": to_float(asset.get("Units")),
        "unit_size": None,
        "holdings": holdings,
        "source": "nomurafunds.com.tw / 持股比重",
    }
