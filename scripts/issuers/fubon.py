"""富邦投信。

沒有 JSON API，但「基金資產」是伺服器端算好的靜態表格，直接解析：
    https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId=<代號>&ddate=<YYYYMMDD>
表頭形如 股票代碼 / 股票名稱 / 股數 / 金額 / 權重(%)，債券型基金換成債券欄位。
"""
from __future__ import annotations

import re

from common import html_tables, is_symbol_like, parse_date, retry, split_symbol, text_of, to_float

ISSUER = "富邦"
SUPPORTS_BACKFILL = True
IDENTITY = True
URL = "https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx"

DATE_RE = re.compile(r"資料日期[：: ]\s*(\d{4}/\d{1,2}/\d{1,2})")
NAV_RE = re.compile(r"基金淨資產\(?[^)]*\)?\s*([\d,]+)")
UNITS_RE = re.compile(r"基金在外流通單位總數\(?[^)]*\)?\s*([\d,]+)|基金在外流通單位數\(?[^)]*\)?\s*([\d,]+)")

# 表頭關鍵字 → 我們的欄位
COL_HINTS = {
    "symbol": ("代碼", "代號"),
    "name": ("名稱",),
    "shares": ("股數", "數量", "張數", "面額"),
    "value": ("金額", "市值"),
    "weight": ("權重", "比重", "比例"),
}


def discover(sess, codes) -> dict[str, str]:
    return {c: c for c in codes}


def _pick_columns(head: list[str]) -> dict[str, int]:
    out = {}
    for field, hints in COL_HINTS.items():
        for i, col in enumerate(head):
            if any(h in col for h in hints) and field not in out:
                out[field] = i
    return out


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    params = {"stkId": code}
    if on_date:
        params["ddate"] = on_date.strftime("%Y%m%d")

    def call():
        r = sess.get(URL, params=params, timeout=45)
        r.raise_for_status()
        return r.text

    html = retry(call, label=f"fubon {code}")
    flat = text_of(html)

    holdings = []
    for table in html_tables(html):
        if len(table) < 2:
            continue
        cols = _pick_columns(table[0])
        if "symbol" not in cols or "weight" not in cols:
            continue
        kind = "bond" if any("債" in c for c in table[0]) else "stock"
        for row in table[1:]:
            if len(row) <= max(cols.values()):
                continue
            sym, suffix = split_symbol(row[cols["symbol"]])
            if not is_symbol_like(sym):
                continue  # 小計列
            holdings.append({
                "symbol": sym,
                "name": row[cols["name"]].strip() if "name" in cols else "",
                "market": suffix or "TW",
                "shares": to_float(row[cols["shares"]]) if "shares" in cols else None,
                "weight": to_float(row[cols["weight"]]),
                "market_value": to_float(row[cols["value"]]) if "value" in cols else None,
                "kind": kind,
            })

    m_date = DATE_RE.search(flat)
    m_nav = NAV_RE.search(flat)
    m_units = UNITS_RE.search(flat)
    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": "",
        "as_of": parse_date(m_date.group(1)) if m_date else "",
        "basis": "fund",
        "nav_total": to_float(m_nav.group(1)) if m_nav else None,
        "fund_units": to_float(next((g for g in m_units.groups() if g), None)) if m_units else None,
        "unit_size": None,
        "holdings": holdings,
        "source": "websys.fsit.com.tw / 基金資產",
    }
