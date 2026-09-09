"""凱基投信。

申購買回清單頁本身只有外殼，內容是 jQuery `.load()` 打進來的 HTML 片段：
    POST /Fund/RedemptionVC  {fundID: "J024", queryDate: "YYYY/MM/DD"}
內部代號（J024 之類）寫在頁面的 ClickFund('J024') 裡，但那裡只有基金簡稱，
所以對照表要靠實際抓一次片段、從裡面的「(00407A)」讀出證券代號。
"""
from __future__ import annotations

import re

from common import (html_tables, is_symbol_like, pcf_basis_date, retry, split_symbol,
                    text_of, to_float)

ISSUER = "凱基"
SUPPORTS_BACKFILL = True
BASE = "https://www.kgifund.com.tw"
LIST_URL = f"{BASE}/Fund/RedemptionList"
FRAGMENT_URL = f"{BASE}/Fund/RedemptionVC"

FUND_ID_RE = re.compile(r"ClickFund\('([A-Z]\d{3})'")
CODE_RE = re.compile(r"\((00\d{3}[A-Z])\)")


def _fragment(sess, fund_id: str, query_date: str | None = None) -> str:
    data = {"fundID": fund_id}
    if query_date:
        data["queryDate"] = query_date

    def call():
        r = sess.post(FRAGMENT_URL, data=data, timeout=45,
                      headers={"X-Requested-With": "XMLHttpRequest", "Referer": LIST_URL})
        r.raise_for_status()
        return r.text

    return retry(call, label=f"kgi {fund_id}")


def discover(sess, codes) -> dict[str, str]:
    def call():
        r = sess.get(LIST_URL, timeout=40)
        r.raise_for_status()
        return r.text

    page = retry(call, label="kgi list")
    wanted = set(codes)
    found: dict[str, str] = {}
    for fund_id in dict.fromkeys(FUND_ID_RE.findall(page)):
        m = CODE_RE.search(text_of(_fragment(sess, fund_id)))
        if not m:
            continue
        found[m.group(1)] = fund_id
        if wanted and wanted <= found.keys():
            break  # 需要的都找齊了就不用把整個基金列表都問一遍
    return found


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    html = _fragment(sess, internal_id, on_date.strftime("%Y/%m/%d") if on_date else None)
    flat = text_of(html)

    holdings = []
    for table in html_tables(html):
        if len(table) < 2:
            continue
        head = table[0]
        if not any("代號" in c or "代碼" in c for c in head):
            continue
        kind = "bond" if any("債" in c for c in head) else "stock"
        idx = {"symbol": 0, "name": 1}
        for i, col in enumerate(head):
            if "股數" in col or "數量" in col or "面額" in col:
                idx["shares"] = i
            elif "權重" in col or "比重" in col:
                idx["weight"] = i
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
                "name": row[idx["name"]].strip(),
                "market": suffix or "TW",
                "shares": to_float(row[idx["shares"]]) if "shares" in idx else None,
                "weight": to_float(row[idx["weight"]]),
                "market_value": None,
                "kind": kind,
            })

    def field(label: str):
        m = re.search(re.escape(label) + r"[^0-9\-]{0,20}(-?[\d,]+(?:\.\d+)?)", flat)
        return to_float(m.group(1)) if m else None

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": "",
        "as_of": pcf_basis_date(flat),
        "basis": "fund",
        "nav_total": field("基金淨資產價值(元)"),
        "fund_units": field("已發行受益權單位總數"),
        "unit_size": None,
        "holdings": holdings,
        "source": "kgifund.com.tw / 申購買回清單",
    }
