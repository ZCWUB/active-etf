"""抓每檔主動式 ETF 的績效與配息紀錄。

來源：證交所 ETF e添富的個別商品頁（伺服器端算好的 HTML），
一檔一個請求，內容包含績效走勢（一日／一週／一個月…五年）與收益分配紀錄。

輸出：data/fundinfo.json
"""
from __future__ import annotations

import re

from common import DATA, html_tables, now_tpe, parse_date, read_json, retry, session, to_float, write_json

URL = "https://www.twse.com.tw/zh/ETFortune/etfInfo/{code}"
REFERER = "https://www.twse.com.tw/zh/ETFortune/products"

PERIODS = ["一日", "一週", "一個月", "三個月", "六個月", "一年", "三年", "五年"]
KEYS = ["d1", "w1", "m1", "m3", "m6", "y1", "y3", "y5"]

MANAGER_RE = re.compile(r"基金經理人\s*([^\s]{1,20}?)\s*標的指數")
AUM_RE = re.compile(r"資產規模\(億元\)\s*([\d,.]+)")
HOLDERS_RE = re.compile(r"受益人次\(萬人\)\s*([\d,.]+)")


def _flat(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " "))


def fetch_one(sess, code: str) -> dict:
    def call():
        r = sess.get(URL.format(code=code), timeout=45, headers={"Referer": REFERER})
        r.raise_for_status()
        return r.text

    html = retry(call, label=f"etfinfo {code}")
    flat = _flat(html)

    performance, dividends = {}, []
    for table in html_tables(html):
        head = [c.strip() for c in table[0]]
        if head[:3] == PERIODS[:3] and len(table) > 1:
            for key, cell in zip(KEYS, table[1]):
                performance[key] = to_float(cell)
        elif any("發放日" in c for c in head):
            for row in table[1:]:
                day, amount = parse_date(row[0]), to_float(row[1] if len(row) > 1 else None)
                if day and amount is not None:
                    dividends.append({"date": day, "amount": amount})

    m_manager = MANAGER_RE.search(flat)
    m_aum = AUM_RE.search(flat)
    m_holders = HOLDERS_RE.search(flat)
    return {
        "manager": m_manager.group(1) if m_manager else None,
        "aum_100m": to_float(m_aum.group(1)) if m_aum else None,
        "holders_10k": to_float(m_holders.group(1)) if m_holders else None,
        "performance": performance,
        "dividends": dividends,
    }


def main() -> int:
    universe = read_json(DATA / "universe.json") or {}
    codes = [f["code"] for f in universe.get("funds") or []]
    if not codes:
        print("universe.json is empty — run fetch_universe.py first")
        return 1

    sess = session(REFERER)
    out, failed = {}, []
    for code in codes:
        try:
            out[code] = fetch_one(sess, code)
        except Exception as exc:  # noqa: BLE001 - 剛掛牌的基金頁面可能還沒建好
            failed.append(f"{code}: {type(exc).__name__}")

    write_json(DATA / "fundinfo.json", {
        "updated_at": now_tpe().isoformat(timespec="seconds"),
        "source": "TWSE ETF e添富商品頁（績效來源：全曜財經資訊）",
        "funds": out,
    })
    print(f"fundinfo: {len(out)} 檔"
          + (f"，{len(failed)} 檔失敗：{'、'.join(failed)}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
