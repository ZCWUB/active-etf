"""台新投信。

申購買回清單是伺服器端算好的表格，換基金與換日期都靠 POST 表單：
    POST /ETF/Home/Pcf  {ETF_ID: "00987A", DATA_DATE: "YYYY-MM-DD", FUND_TYPE: "ALL"}
DATA_DATE 可帶過去的日期，所以支援回補。
"""
from __future__ import annotations

import re

from common import (html_tables, is_symbol_like, now_tpe, pcf_basis_date, retry,
                    split_symbol, text_of, to_float)

ISSUER = "台新"
SUPPORTS_BACKFILL = True
IDENTITY = True
URL = "https://www.tsit.com.tw/ETF/Home/Pcf"

NAV_RE = re.compile(r"基金淨資產價值\(?元?\)?\s*(?:TWD)?\s*([\d,]+)")
UNITS_RE = re.compile(r"已發行受益權單位總數\s*([\d,]+)")


def discover(sess, codes) -> dict[str, str]:
    return {c: c for c in codes}


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    day = (on_date or now_tpe().date()).strftime("%Y-%m-%d")
    data = {"ETF_ID": code, "DATA_DATE": day, "MAX_DATE": day, "FUND_TYPE": "ALL"}

    def call():
        r = sess.post(URL, data=data, timeout=45, headers={"Referer": URL})
        r.raise_for_status()
        return r.text

    html = retry(call, label=f"tsit {code}")
    flat = text_of(html)

    holdings = []
    for table in html_tables(html):
        if len(table) < 2:
            continue
        head = table[0]
        if not any("代號" in c or "代碼" in c for c in head):
            continue
        kind = "bond" if any("債" in c for c in head) else "stock"
        idx = {"symbol": 0}
        for i, col in enumerate(head):
            if "名稱" in col:
                idx["name"] = i
            elif any(k in col for k in ("股數", "面額", "口數")):
                idx["shares"] = i
            elif "權重" in col:
                idx["weight"] = i
            elif "市值" in col:
                idx["value"] = i
        if "weight" not in idx:
            continue
        for row in table[1:]:
            if len(row) <= max(idx.values()):
                continue
            sym, suffix = split_symbol(row[idx["symbol"]])
            if not is_symbol_like(sym):
                continue
            holdings.append({
                "symbol": sym,
                "name": row[idx["name"]].strip() if "name" in idx else "",
                "market": suffix or "TW",
                "shares": to_float(row[idx["shares"]]) if "shares" in idx else None,
                "weight": to_float(row[idx["weight"]]),
                "market_value": to_float(row[idx["value"]]) if "value" in idx else None,
                "kind": kind,
            })

    m_nav = NAV_RE.search(flat)
    m_units = UNITS_RE.search(flat)
    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": "",
        "as_of": pcf_basis_date(flat),
        "basis": "fund",
        "nav_total": to_float(m_nav.group(1)) if m_nav else None,
        "fund_units": to_float(m_units.group(1)) if m_units else None,
        "unit_size": None,
        "holdings": holdings,
        "source": "tsit.com.tw / 申購買回清單",
    }
