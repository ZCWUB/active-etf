"""永豐投信。伺服器直接把持股算進 HTML，網址就是代號。

    https://sitc.sinopac.com/SinopacEtfs/Etfs/SinglePcf/<代號>
表頭：證券代碼 / 證券名稱 / 股數 / 佔基金淨資產價值之權重(%)
"""
from __future__ import annotations

import re

from common import (html_tables, is_symbol_like, pcf_basis_date, retry, split_symbol,
                    text_of, to_float)

ISSUER = "永豐"
IDENTITY = True
URL = "https://sitc.sinopac.com/SinopacEtfs/Etfs/SinglePcf/{code}"

NAV_RE = re.compile(r"基金淨資產價值\(?元?\)?\s*(?:NT\$)?\s*([\d,]+)")
UNITS_RE = re.compile(r"已發行受益權單位總數\s*([\d,]+)")


def discover(sess, codes) -> dict[str, str]:
    return {c: c for c in codes}


def fetch(sess, code: str, internal_id: str) -> dict:
    def call():
        r = sess.get(URL.format(code=code), timeout=45)
        r.raise_for_status()
        return r.text

    html = retry(call, label=f"sinopac {code}")
    flat = text_of(html)

    holdings = []
    for table in html_tables(html):
        if len(table) < 2:
            continue
        head = table[0]
        if not any("代碼" in c or "代號" in c for c in head):
            continue
        idx = {"symbol": 0}
        for i, col in enumerate(head):
            if "名稱" in col:
                idx["name"] = i
            elif any(k in col for k in ("股數", "口數", "面額")):
                idx["shares"] = i
            elif "權重" in col or "比重" in col:
                idx["weight"] = i
        if "weight" not in idx:
            continue
        kind = "future" if any("期貨" in c for c in head) else (
            "bond" if any("債" in c for c in head) else "stock")
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
                "market_value": None,
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
        "source": "sitc.sinopac.com / 現金申購買回清單",
    }
