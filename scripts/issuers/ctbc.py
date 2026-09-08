"""中國信託投信。

API 要先換 token：
    POST /API/home/AuthToken?token=www.ctbcinvestments.com  → Data.token
    POST /API/etf/ETFList        取得 ETF_ID ↔ FID 對照
    POST /API/etf/ETFHoldingWeight  {token, FID, StartDate}  取得投資組合
StartDate 是 ISO 時間字串，帶過去的日期即可回補。
"""
from __future__ import annotations

from datetime import datetime, timezone

from common import now_tpe, parse_date, retry, split_symbol, to_float

ISSUER = "中國信託"
SUPPORTS_BACKFILL = True
BASE = "https://www.ctbcinvestments.com.tw/API"
REFERER = "https://www.ctbcinvestments.com.tw/"

INVTP_KIND = {"STOCK": "stock", "ETF": "etf", "BOND": "bond", "FUTURE": "future"}


def _token(sess) -> str:
    def call():
        r = sess.post(f"{BASE}/home/AuthToken", params={"token": "www.ctbcinvestments.com"},
                      json={}, timeout=40, headers={"Referer": REFERER})
        r.raise_for_status()
        return r.json()

    return retry(call, label="ctbc token")["Data"]["token"]


def _post(sess, path: str, body: dict, token: str):
    def call():
        r = sess.post(f"{BASE}/{path}", params={"token": token}, json={**body, "token": token},
                      timeout=45, headers={"Referer": REFERER})
        r.raise_for_status()
        return r.json()

    j = retry(call, label=f"ctbc {path}")
    if j.get("ResultCode") != 0:
        raise RuntimeError(f"{path}: {j.get('ResultMsg')}")
    return j.get("Data")


def discover(sess, codes) -> dict[str, str]:
    token = _token(sess)
    rows = _post(sess, "etf/ETFList", {}, token)["Data"]
    sess.headers["X-CTBC-Token"] = token  # 讓 fetch 沿用同一顆 token
    return {(r.get("ETF_ID") or "").strip().upper(): r.get("FID")
            for r in rows if r.get("ETF_ID") and r.get("FID")}


def fetch(sess, code: str, internal_id: str, on_date=None) -> dict:
    token = sess.headers.get("X-CTBC-Token") or _token(sess)
    when = datetime.combine(on_date or now_tpe().date(), datetime.min.time()) \
        .replace(tzinfo=timezone.utc) if on_date else datetime.now(timezone.utc)
    data = _post(sess, "etf/ETFHoldingWeight",
                 {"FID": internal_id, "StartDate": when.strftime("%Y-%m-%dT%H:%M:%S.000Z")}, token)

    fund = (data.get("Fund") or [{}])[0]
    assets = (data.get("FundAssets") or [{}])[0]

    holdings = []
    for group in data.get("FundAssetsDetail") or []:
        kind = INVTP_KIND.get((group.get("Code") or "").strip().upper())
        if not kind:
            continue  # 現金、保證金、選擇權不列入持股統計
        for row in group.get("Data") or []:
            sym, suffix = split_symbol(row.get("code_"))
            if not sym:
                continue
            currency = (row.get("cur_") or "TWD").strip().upper()
            is_tw = currency in {"TWD", "NTD"}
            holdings.append({
                "symbol": sym,
                "name": (row.get("name_") or "").strip(),
                "market": suffix or ("TW" if is_tw else currency[:2]),
                "shares": to_float(row.get("qty_")),
                "weight": to_float(row.get("weights_")),
                "market_value": to_float(row.get("amount_")) if is_tw and kind == "stock" else None,
                "kind": kind,
            })

    # 這支 API 的中文欄位名就是資料鍵，直接取值
    return {
        "code": code,
        "issuer": ISSUER,
        "fund_name": (fund.get("FundName") or "").strip(),
        "as_of": parse_date(assets.get("NAV_DT") or assets.get("資料日期")),
        "basis": "fund",
        "nav_total": to_float(assets.get("基金淨資產")),
        "fund_units": to_float(assets.get("基金在外流通單位數")),
        "unit_size": None,
        "holdings": holdings,
        "source": "ctbcinvestments.com.tw / 投資組合",
    }
