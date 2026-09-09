"""兆豐國際投信。

ASP.NET WebForms，換基金要走 postback：先把分類切到「主動式ETF」，
再選 fund_id，兩次都得帶回上一頁的 __VIEWSTATE。
內部代號（下拉的 value）對不到證券代號，所以要實際 post 一次、從頁面讀出「股票代號：00996A」。
"""
from __future__ import annotations

import re

from common import html_tables, is_symbol_like, parse_date, retry, split_symbol, text_of, to_float

ISSUER = "兆豐國際"
URL = "https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx"
CATEGORY_SELECT = "ctl00$ContentPlaceHolder1$category_id"
FUND_SELECT = "ctl00$ContentPlaceHolder1$fund_id"
ACTIVE_CATEGORY = "16"  # 主動式ETF

CODE_RE = re.compile(r"股票代號[：: ]\s*(00\d{3}[A-Z])")
DATE_RE = re.compile(r"查詢日期[^0-9]{0,10}(\d{4}/\d{1,2}/\d{1,2})")
NAV_RE = re.compile(r"基金淨資產價值\(?元?\)?\s*(?:TWD\$)?\s*([\d,]+)")
UNITS_RE = re.compile(r"已發行受益權單位總數\s*([\d,]+)")


def _hidden(name: str, html: str) -> str:
    m = re.search(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _post(sess, html: str, target: str, fields: dict) -> str:
    data = {
        "__EVENTTARGET": target,
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": _hidden("__VIEWSTATE", html),
        "__VIEWSTATEGENERATOR": _hidden("__VIEWSTATEGENERATOR", html),
    }
    data.update(fields)

    def call():
        r = sess.post(URL, data=data, timeout=45)
        r.raise_for_status()
        return r.text

    return retry(call, label="mega postback")


def _fund_options(html: str) -> list[tuple[str, str]]:
    """抓 fund_id 下拉的 (value, 基金名稱)。

    頁面上還有別的下拉，要限定 name；而且只有第一次 GET 的頁面帶著完整清單，
    切分類的 postback 回應裡反而沒有這個 select。
    """
    m = re.search(r'<select[^>]*name="' + re.escape(FUND_SELECT) + r'"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return []
    return re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]*)', m.group(1))


def _active_page(sess, fund_id: str) -> str:
    def call():
        r = sess.get(URL, timeout=45)
        r.raise_for_status()
        return r.text

    first = retry(call, label="mega page")
    second = _post(sess, first, CATEGORY_SELECT, {CATEGORY_SELECT: ACTIVE_CATEGORY})
    return _post(sess, second, FUND_SELECT,
                 {CATEGORY_SELECT: ACTIVE_CATEGORY, FUND_SELECT: fund_id})


def discover(sess, codes) -> dict[str, str]:
    def call():
        r = sess.get(URL, timeout=45)
        r.raise_for_status()
        return r.text

    first = retry(call, label="mega page")
    listing = _post(sess, first, CATEGORY_SELECT, {CATEGORY_SELECT: ACTIVE_CATEGORY})
    wanted, found = set(codes), {}
    # 只問名稱帶「主動」的，其餘被動式 ETF 不必浪費一次 postback
    for fund_id, name in _fund_options(first):
        if "主動" not in name:
            continue
        page = _post(sess, listing, FUND_SELECT,
                     {CATEGORY_SELECT: ACTIVE_CATEGORY, FUND_SELECT: fund_id})
        m = CODE_RE.search(text_of(page))
        if not m:
            continue
        found[m.group(1)] = fund_id
        if wanted and wanted <= found.keys():
            break
    return found


def fetch(sess, code: str, internal_id: str) -> dict:
    html = _active_page(sess, internal_id)
    flat = text_of(html)

    holdings = []
    for table in html_tables(html):
        if len(table) < 2:
            continue
        head = table[0]
        if not any("代號" in c or "代碼" in c for c in head):
            continue
        kind = "future" if any("期貨" in c for c in head) else (
            "bond" if any("債" in c for c in head) else "stock")
        idx = {"symbol": 0}
        for i, col in enumerate(head):
            if "名稱" in col:
                idx["name"] = i
            elif any(k in col for k in ("股數", "口數", "面額")):
                idx["shares"] = i
            elif "權重" in col:
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
                "name": row[idx["name"]].strip() if "name" in idx else "",
                "market": suffix or "TW",
                "shares": to_float(row[idx["shares"]]) if "shares" in idx else None,
                "weight": to_float(row[idx["weight"]]),
                "market_value": None,
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
        "fund_units": to_float(m_units.group(1)) if m_units else None,
        "unit_size": None,
        "holdings": holdings,
        "source": "megafunds.com.tw / 申購買回清單",
    }
