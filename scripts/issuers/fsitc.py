"""第一金投信。

持股在一支 ASP.NET ScriptService：
    POST /WebAPI.aspx/Get_hd  {"pStrFundID": "182", "pStrDate": "YYYY-MM-DD"}
回傳 A=代號 B=名稱 C=權重 D=股數，pStrDate 留空就是最新一日，帶日期可回補。

內部代號（cNo）與證券代號的對照沒有現成清單，但基金頁面內嵌了一份所有基金的
JSON，裡面 cETFStockCode 前面最近的 cNo 就是該檔的內部代號。
"""
from __future__ import annotations

import html as html_lib
import json
import re

from common import is_symbol_like, parse_date, retry, split_symbol, to_float

ISSUER = "第一金"
SUPPORTS_BACKFILL = True
BASE = "https://www.fsitc.com.tw"
SEED_URL = f"{BASE}/FundDetail.aspx?ID=182"
API = f"{BASE}/WebAPI.aspx/Get_hd"

CODE_RE = re.compile(r'"cETFStockCode":\s*"(00\d{3}[A-Z])"')
NO_RE = re.compile(r'"cNo":\s*"(\d+)"')


def discover(sess, codes) -> dict[str, str]:
    def call():
        r = sess.get(SEED_URL, timeout=60)
        r.raise_for_status()
        return r.text

    text = html_lib.unescape(html_lib.unescape(retry(call, label="fsitc page")))
    out = {}
    for m in CODE_RE.finditer(text):
        before = text[max(0, m.start() - 9000):m.start()]
        nos = NO_RE.findall(before)
        if nos:
            out[m.group(1)] = nos[-1]
    return out


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    body = {"pStrFundID": str(internal_id),
            "pStrDate": on_date.strftime("%Y-%m-%d") if on_date else ""}

    def call():
        r = sess.post(API, json=body, timeout=45,
                      headers={"Content-Type": "application/json; charset=utf-8",
                               "Referer": f"{BASE}/FundDetail.aspx?ID={internal_id}"})
        r.raise_for_status()
        return r.json()

    payload = retry(call, label=f"fsitc {code}")
    rows = payload.get("d")
    rows = json.loads(rows) if isinstance(rows, str) else (rows or [])

    holdings, as_of = [], ""
    for row in rows:
        sym, suffix = split_symbol(row.get("A"))
        if not is_symbol_like(sym):
            continue
        as_of = as_of or parse_date(row.get("sdate"))
        holdings.append({
            "symbol": sym,
            "name": (row.get("B") or "").strip(),
            "market": suffix or "TW",
            "shares": to_float(row.get("D")),
            "weight": to_float(row.get("C")),
            "market_value": None,
            "kind": "stock",
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
        "source": "fsitc.com.tw / 投資組合",
    }
