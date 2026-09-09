"""安聯投信。

這是唯一一家沒辦法用一般 HTTP 客戶端抓的：webapi 對任何非瀏覽器發出的請求
一律回 400（連空 body 的 GetFooterContent 也是），偽裝 TLS 指紋、補齊瀏覽器
標頭、甚至在無頭瀏覽器裡自己 fetch 都沒用——只有 Angular 自己發的那一次會成功。
所以這裡用無頭瀏覽器開頁面，攔截它自己發出的 GetFundAssets 回應。

Playwright 沒安裝時整包 adapter 會安靜略過，其他投信照常運作。
"""
from __future__ import annotations

import atexit
import json

from common import is_symbol_like, parse_date, split_symbol, to_float

ISSUER = "安聯"
BASE = "https://etf.allianzgi.com.tw"

TITLE_KIND = {"股票": "stock", "債券": "bond", "期貨": "future", "ETF": "etf"}

_browser = None
_playwright = None


def _page():
    """整輪抓取共用同一個瀏覽器，不要每檔基金都開一次。"""
    global _browser, _playwright
    if _browser is None:
        from playwright.sync_api import sync_playwright  # 沒裝就讓 ImportError 往上拋
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
        atexit.register(_close)
    return _browser.new_page()


def _close():
    global _browser, _playwright
    if _browser:
        try:
            _browser.close()
        finally:
            _browser = None
    if _playwright:
        try:
            _playwright.stop()
        finally:
            _playwright = None


def _capture(url: str, match: str, timeout_ms: int = 60000) -> dict | None:
    """開頁面，攔截頁面自己打出去、網址含 match 的那個 JSON 回應。"""
    page = _page()
    grabbed: list[dict] = []

    def on_response(resp):
        if match in resp.url and resp.status == 200:
            try:
                grabbed.append(resp.json())
            except Exception:  # noqa: BLE001 - 不是 JSON 就跳過
                pass

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(3000)
    finally:
        page.close()
    return grabbed[-1] if grabbed else None


def discover(sess, codes) -> dict[str, str]:
    payload = _capture(f"{BASE}/etf-list", "GetFundOverview")
    if not payload:
        return {}
    blob = json.dumps(payload.get("Entries"), ensure_ascii=False)
    out = {}
    for row in json.loads(blob) if isinstance(json.loads(blob), list) else []:
        code = str(row.get("CSecuritiesCode") or "").strip().upper()
        fund_no = row.get("CFundNo")
        if code and fund_no:
            out[code] = fund_no
    return out


def fetch(sess, code: str, internal_id: str) -> dict:
    payload = _capture(f"{BASE}/etf-info/{internal_id}?tab=1", "GetFundAssets")
    if not payload:
        raise RuntimeError("browser did not capture GetFundAssets")
    data = (payload.get("Entries") or {}).get("Data") or {}
    asset = data.get("FundAsset") or {}

    holdings = []
    for table in data.get("Table") or []:
        title = (table.get("TableTitle") or "").split("(")[0].strip()
        kind = TITLE_KIND.get(title)
        if not kind:
            continue
        cols = [(c.get("Name") or "").strip() for c in table.get("Columns") or []]
        idx = {}
        for i, name in enumerate(cols):
            if "代號" in name or "代碼" in name:
                idx["symbol"] = i
            elif "名稱" in name:
                idx["name"] = i
            elif any(k in name for k in ("股數", "口數", "面額")):
                idx["shares"] = i
            elif "權重" in name:
                idx["weight"] = i
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
        "source": "etf.allianzgi.com.tw / 基金資產",
    }
