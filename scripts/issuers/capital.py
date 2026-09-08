"""群益投信。申購買回清單公告的張數已是全基金持股（實測隱含權重與公告權重一致）。"""
from __future__ import annotations

from common import parse_date, retry, split_symbol, to_float

ISSUER = "群益"
BASE = "https://www.capitalfund.com.tw"
ITEMS_URL = f"{BASE}/CFWeb/api/etf/items"
PCF_URL = f"{BASE}/CFWeb/api/etf/buyback"


def discover(sess, codes) -> dict[str, str]:
    def call():
        r = sess.post(ITEMS_URL, json={}, timeout=30)
        r.raise_for_status()
        return r.json()

    j = retry(call, label="capital items")
    out = {}
    for row in _walk_items(j.get("data")):
        code = str(row.get("secfundid") or row.get("stockNo") or "").strip().upper()
        fid = row.get("fundNo") or row.get("fundId") or row.get("fundid") or row.get("id")
        if code and fid:
            out[code] = str(fid)
    return out


def _walk_items(node):
    """items 回傳結構可能是 list 或 {group: [...]}, 一律攤平成 dict 序列。"""
    if isinstance(node, list):
        for x in node:
            yield from _walk_items(x)
    elif isinstance(node, dict):
        if any(k in node for k in ("secfundid", "stockNo")):
            yield node
        else:
            for v in node.values():
                yield from _walk_items(v)


def fetch(sess, code: str, internal_id: str) -> dict:
    def call():
        r = sess.post(PCF_URL, json={"fundId": str(internal_id)}, timeout=40)
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"capital {code}")
    data = j.get("data") or {}
    pcf = data.get("pcf") or {}

    holdings = []
    for s in data.get("stocks") or []:
        sym, suffix = split_symbol(s.get("stocNo"))
        holdings.append({
            "symbol": sym,
            "name": (s.get("stocName") or "").strip(),
            "market": suffix or "TW",
            "shares": to_float(s.get("share")),
            "weight": to_float(s.get("weight")),
            "market_value": None,
            "kind": "stock",
        })

    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": (pcf.get("fundName") or "").strip(),
        # date2 是資料基準日，date1 是公告生效日
        "as_of": parse_date(pcf.get("date2") or pcf.get("date1")),
        "basis": "fund",
        "nav_total": to_float(pcf.get("nav")),
        "fund_units": to_float(pcf.get("totUnit")),
        "unit_size": to_float(pcf.get("tUnit")),
        "holdings": holdings,
        "source": "capitalfund.com.tw / 申購買回清單",
    }
