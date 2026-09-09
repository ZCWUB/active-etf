"""把每日快照算成網站要吃的 JSON。

輸出到 web/data/：
  meta.json          建置時間、涵蓋度、資料來源
  funds.json         ETF 列表：規模、折溢價、當日淨買賣超、異動檔數
  funds/<代號>.json  單一 ETF 的完整持股與當日增減
  stocks.json        個股反查：被幾家主動 ETF 持有、持有市值、1/3/5 日淨買賣，
                     以及每一家的庫存均價與報酬率
  signals.json       今日訊號：ETF 淨買超／賣超 TOP3、個股排行
  sectors.json       板塊輪動：各產業今日與近 5 日的加減碼

庫存均價用平均成本法推算：每天的持股增量 × 當日成交均價累積成本，減碼不動成本。
這不是投信揭露的數字，是從公開的每日持股變動反推出來的。
"""
from __future__ import annotations

import re
import shutil
from collections import defaultdict

from common import DATA, ROOT, now_tpe, read_json, uid, write_json

WEB_DATA = ROOT / "web" / "data"
TRADABLE = {"stock", "etf"}  # 納入個股統計的類別（期貨、現金、債券不列入）
CJK_RE = re.compile(r"[一-鿿]")


# ---------------------------------------------------------------- 讀檔

def snapshots(code: str) -> list[dict]:
    d = DATA / "pcf" / code
    if not d.exists():
        return []
    snaps = [read_json(p) for p in sorted(d.glob("*.json"))]
    return [s for s in snaps if s and s.get("holdings")]


def latest_file(folder: str) -> dict:
    d = DATA / folder
    files = sorted(d.glob("*.json")) if d.exists() else []
    return read_json(files[-1]) if files else {}


def load_prices() -> dict[str, dict[str, list]]:
    """{日期: {代號: [收盤, 成交均價, 漲跌%]}}"""
    d = DATA / "prices"
    out = {}
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        doc = read_json(p) or {}
        if doc.get("date"):
            out[doc["date"]] = doc.get("prices") or {}
    return out


class Prices:
    """查某天某檔的價格；那天沒開盤或沒成交就往前找最近的一天。"""

    def __init__(self, by_day: dict[str, dict[str, list]]):
        self.by_day = by_day
        self.days = sorted(by_day)
        self._cache: dict[tuple, float | None] = {}

    def get(self, day: str, symbol: str, idx: int):
        key = (day, symbol, idx)
        if key in self._cache:
            return self._cache[key]
        value = None
        for d in reversed([d for d in self.days if d <= day][-12:]):
            row = self.by_day[d].get(symbol)
            if row and len(row) > idx and row[idx] is not None:
                value = row[idx]
                break
        self._cache[key] = value
        return value


# ---------------------------------------------------------------- 持股處理

def index_holdings(snap: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for h in snap.get("holdings") or []:
        sym = h.get("symbol")
        if not sym:
            continue
        row = dict(h)
        row.setdefault("market", "TW")
        key = uid(sym, row["market"])
        prev = out.get(key)
        if prev:  # 同一標的分列多筆（例如現股＋零股），合併
            for k in ("shares", "weight", "market_value"):
                if row.get(k) is not None or prev.get(k) is not None:
                    row[k] = (row.get(k) or 0) + (prev.get(k) or 0)
        out[key] = row
    return out


def classify(cur: dict, prev: dict | None) -> str:
    """判斷經理人動作。

    有張數就只看張數：權重會因為股價漲跌而變動，張數沒動就不是加減碼。
    只有在該投信沒揭露張數時，才退而用權重變化判斷。
    """
    if not prev:
        return "new"
    if cur.get("shares") is not None and prev.get("shares") is not None:
        ds = cur["shares"] - prev["shares"]
        if ds > 0.5:
            return "add"
        if ds < -0.5:
            return "trim"
        return "hold"
    dw = (cur.get("weight") or 0) - (prev.get("weight") or 0)
    if dw > 0.01:
        return "add"
    if dw < -0.01:
        return "trim"
    return "hold"


def build_name_map(universe: dict, names: dict) -> dict[str, str]:
    """決定每檔標的的顯示名稱。

    各投信對同一檔股票的叫法不一致（緯穎／緯穎科技、AMD／超微半導體公司），
    不統一的話同一檔個股在列表上會看起來像兩檔。
    台股用證交所／櫃買的官方簡稱；海外標的沒有官方中文簡稱，就挑有中文的那個。
    """
    out: dict[str, str] = {}
    for fund in universe.get("funds") or []:
        for snap in snapshots(fund["code"])[-1:]:
            for h in snap.get("holdings") or []:
                sym, market = h.get("symbol"), h.get("market", "TW")
                if not sym:
                    continue
                key = uid(sym, market)
                if market == "TW" and names.get(sym):
                    out[key] = names[sym][0]
                    continue
                cur, new = out.get(key), (h.get("name") or "").strip()
                if not new:
                    continue
                if not cur or (CJK_RE.search(new) and not CJK_RE.search(cur)):
                    out[key] = new
    return out


def track_positions(snaps: list[dict], prices: Prices) -> dict[str, dict]:
    """走過每日快照，累積出每檔標的的庫存均價與逐日張數變化。

    第一次看到的部位沒有更早的資料可追，只能用當天均價當成本起點，
    所以 cost_from 會記下那一天，介面上要標明是從那天起算的推估。
    """
    state: dict[str, dict] = {}
    prev_idx: dict[str, dict] = {}
    for snap in snaps:
        day = snap.get("as_of") or ""
        cur_idx = index_holdings(snap)
        for key, h in cur_idx.items():
            shares = h.get("shares")
            if shares is None:
                continue
            st = state.setdefault(key, {
                "shares": 0.0, "cost": None, "cost_from": day, "history": [],
                # 第一份快照就已經在的部位，建倉成本無從得知，只能拿當天均價當起點；
                # 之後才新進的部位才是真的知道買進價。
                "cost_estimated": not prev_idx,
            })
            delta = shares - (prev_idx.get(key, {}).get("shares") or 0)
            vwap = prices.get(day, h["symbol"], 1) if h.get("market") == "TW" else None
            if delta > 0 and vwap:
                base = (st["cost"] or vwap) * st["shares"]
                st["cost"] = (base + delta * vwap) / (st["shares"] + delta)
            elif st["cost"] is None and vwap:
                st["cost"] = vwap
            st["shares"] = shares
            if delta and prev_idx:
                st["history"].append([day, delta])
        for key in list(prev_idx):
            if key not in cur_idx and key in state:
                st = state[key]
                if st["shares"]:
                    st["history"].append([day, -st["shares"]])
                st["shares"] = 0.0
                st["cost"] = None
        prev_idx = cur_idx
    return state


# ---------------------------------------------------------------- 各檔 ETF

def build_fund(fund: dict, quote: dict, prices: Prices, names: dict, industries: dict,
               positions: dict) -> dict | None:
    snaps = snapshots(fund["code"])
    if not snaps:
        return None
    cur = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None
    cur_idx = index_holdings(cur)
    prev_idx = index_holdings(prev) if prev else {}
    day = cur.get("as_of") or ""

    rows, net_value = [], 0.0
    for key, h in cur_idx.items():
        p = prev_idx.get(key)
        is_tw = h.get("market") == "TW"
        close = prices.get(day, h["symbol"], 0) if is_tw else None
        vwap = prices.get(day, h["symbol"], 1) if is_tw else None
        shares = h.get("shares")
        # 有前一日快照時，前一日沒有這檔就是整筆新建倉，要算成買進全部張數，
        # 不是「沒有變動」；只有在完全沒有前一日可比時才留空。
        delta = None if not prev else (shares or 0) - ((p or {}).get("shares") or 0)
        value_delta = round(delta * vwap) if (delta and vwap) else None
        if value_delta:
            net_value += value_delta
        pos = positions.get(key) or {}
        cost = pos.get("cost")
        rows.append({
            "uid": key,
            "symbol": h["symbol"],
            "name": names.get(key) or h.get("name"),
            "market": h.get("market", "TW"),
            "kind": h.get("kind"),
            "industry": (industries.get(h["symbol"]) or "其他") if is_tw else "海外",
            "weight": h.get("weight"),
            "weight_delta": None if not p else round((h.get("weight") or 0) - (p.get("weight") or 0), 4),
            "shares": shares,
            "shares_delta": delta,
            "value_delta": value_delta,
            "close": close,
            "market_value": h.get("market_value") or (round(shares * close) if shares and close else None),
            "avg_cost": round(cost, 2) if cost else None,
            "cost_from": pos.get("cost_from") if cost else None,
            "cost_estimated": pos.get("cost_estimated") if cost else None,
            "return_pct": round((close / cost - 1) * 100, 2) if (cost and close) else None,
            "status": classify(h, p) if prev else "hold",
        })
    rows.sort(key=lambda r: -(r.get("weight") or 0))

    exited = []
    for key, p in prev_idx.items():
        if key in cur_idx:
            continue
        is_tw = p.get("market") == "TW"
        vwap = prices.get(day, p["symbol"], 1) if is_tw else None
        shares = p.get("shares") or 0
        value_delta = round(-shares * vwap) if (shares and vwap) else None
        if value_delta:
            net_value += value_delta
        exited.append({
            "uid": key,
            "symbol": p["symbol"],
            "name": names.get(key) or p.get("name"),
            "market": p.get("market", "TW"),
            "kind": p.get("kind"),
            "industry": (industries.get(p["symbol"]) or "其他") if is_tw else "海外",
            "weight_prev": p.get("weight"),
            "shares": 0,
            "shares_delta": -shares,
            "value_delta": value_delta,
            "status": "exit",
        })
    exited.sort(key=lambda r: -(r.get("weight_prev") or 0))

    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    counts["exit"] = len(exited)

    # 最大貢獻要跟當日淨買賣同方向，否則買超榜上會出現一檔賣最多的股票，看起來很怪
    movers = [r for r in rows + exited if r.get("value_delta")]
    same_way = [r for r in movers if (r["value_delta"] > 0) == (net_value >= 0)]
    top = max(same_way or movers, key=lambda r: abs(r["value_delta"]), default=None)

    tw_rows = [r for r in rows if r["kind"] in TRADABLE and r["market"] == "TW"]
    tw_weight = sum(r["weight"] or 0 for r in tw_rows)
    tw_value = sum(r["market_value"] or 0 for r in tw_rows)
    aum = quote.get("aum")

    return {
        "code": fund["code"],
        "name": fund["name"],
        "issuer": fund["issuer"],
        "fund_name": cur.get("fund_name"),
        "as_of": day,
        "prev_as_of": prev.get("as_of") if prev else None,
        "fetched_at": cur.get("fetched_at"),
        "source": cur.get("source"),
        "nav": quote.get("nav"),
        "price": quote.get("price"),
        "premium_pct": quote.get("premium_pct"),
        "units": quote.get("units"),
        "units_change": quote.get("units_change"),
        "aum": aum,
        "holding_count": len(rows),
        "changes": dict(counts),
        "stock_weight": round(sum(r["weight"] or 0 for r in rows if r["kind"] in TRADABLE), 2),
        "tw_weight": round(tw_weight, 2),
        # 台股持股市值 ÷（規模×台股權重）：正常接近 1，偏離代表某家投信的張數單位解讀有誤
        "value_coverage": (round(tw_value / (aum * tw_weight / 100), 3)
                           if (aum and tw_weight >= 5 and tw_value) else None),
        "net_value": round(net_value),
        "top_move": ({"symbol": top["symbol"], "name": top["name"],
                      "value": top["value_delta"]} if top else None),
        "holdings": rows,
        "exited": exited,
        "history": [s.get("as_of") for s in snaps],
    }


# ---------------------------------------------------------------- 個股反查

def build_stocks(details: dict, series: dict, prices: Prices, names: dict,
                 industries: dict, foreign: dict, trade_date: str) -> list[dict]:
    idx: dict[str, dict] = {}

    for code, d in details.items():
        positions = series[code]
        for row in d["holdings"] + d["exited"]:
            if row.get("kind") not in TRADABLE:
                continue
            key = row["uid"]
            is_tw = row.get("market") == "TW"
            e = idx.setdefault(key, {
                "uid": key, "symbol": row["symbol"],
                "name": names.get(key) or row.get("name"),
                "market": row.get("market", "TW"),
                "industry": row.get("industry") or "其他",
                "close": prices.get(trade_date, row["symbol"], 0) if is_tw else None,
                "change_pct": prices.get(trade_date, row["symbol"], 2) if is_tw else None,
                "funds": [], "total_shares": 0.0, "total_value": 0.0,
                "d1_shares": 0.0, "d1_value": 0.0,
                "d3_shares": 0.0, "d3_value": 0.0,
                "d5_shares": 0.0, "d5_value": 0.0,
                "streak": 0,
            })
            exited = row.get("status") == "exit"
            e["funds"].append({
                "code": code, "name": d["name"],
                "weight": row.get("weight"),
                "shares": 0 if exited else row.get("shares"),
                "shares_delta": row.get("shares_delta"),
                "avg_cost": row.get("avg_cost"),
                "cost_from": row.get("cost_from"),
                "cost_estimated": row.get("cost_estimated"),
                "return_pct": row.get("return_pct"),
                "status": row.get("status"),
            })
            if not exited:
                e["total_shares"] += row.get("shares") or 0
                e["total_value"] += row.get("market_value") or 0

            hist = (positions.get(key) or {}).get("history") or []
            vwap = prices.get(trade_date, row["symbol"], 1) if is_tw else None
            days = sorted({day for day, _ in hist})
            fund_days = d["history"]
            for window, field in ((1, "d1"), (3, "d3"), (5, "d5")):
                recent = set(fund_days[-window:])
                moved = sum(delta for day, delta in hist if day in recent)
                if moved:
                    e[f"{field}_shares"] += moved
                    if vwap:
                        e[f"{field}_value"] += moved * vwap
            del days

    # 連續買超天數：全部 ETF 合計，從最近一天往回數
    all_days = sorted({d for detail in details.values() for d in detail["history"]})
    daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for code, positions in series.items():
        for key, st in positions.items():
            for day, delta in st["history"]:
                daily[key][day] += delta

    stocks = list(idx.values())
    for e in stocks:
        moves = daily.get(e["uid"], {})
        streak = 0
        for day in reversed(all_days):
            net = moves.get(day, 0)
            if net > 0:
                streak += 1
            elif net < 0:
                break
        e["streak"] = streak
        e["fund_count"] = sum(1 for f in e["funds"] if f["status"] != "exit")
        e["funds"].sort(key=lambda f: -(f.get("weight") or 0))
        fnet = foreign.get(e["symbol"]) if e["market"] == "TW" else None
        e["foreign_net_shares"] = fnet
        e["foreign_aligned"] = bool(fnet is not None and e["d1_shares"]
                                    and (fnet > 0) == (e["d1_shares"] > 0))
        for f in ("total_value", "d1_value", "d3_value", "d5_value"):
            e[f] = round(e[f])
        e["status"] = ("new" if any(f["status"] == "new" for f in e["funds"])
                       else "exit" if all(f["status"] == "exit" for f in e["funds"])
                       else "add" if e["d1_shares"] > 0
                       else "trim" if e["d1_shares"] < 0 else "hold")
    stocks.sort(key=lambda e: (-e["fund_count"], -e["total_value"]))
    return stocks


def build_sectors(stocks: list[dict]) -> dict:
    """板塊輪動：把個股的加減碼金額依產業別加總。"""
    agg: dict[str, dict] = {}
    for s in stocks:
        if s["market"] != "TW":
            continue
        e = agg.setdefault(s["industry"], {
            "industry": s["industry"], "d1_value": 0, "d5_value": 0,
            "changed": 0, "holdings": 0,
        })
        e["d1_value"] += s["d1_value"]
        e["d5_value"] += s["d5_value"]
        e["holdings"] += 1
        if s["d1_shares"]:
            e["changed"] += 1

    today = sorted(agg.values(), key=lambda e: -e["d1_value"])
    five = sorted(agg.values(), key=lambda e: -e["d5_value"])
    return {
        "today": today,
        "five_day": five,
        "top_buy": [e for e in today if e["d1_value"] > 0][:3],
        "top_sell": sorted([e for e in today if e["d1_value"] < 0],
                           key=lambda e: e["d1_value"])[:3],
        "top_buy_5d": [e for e in five if e["d5_value"] > 0][:3],
        "top_sell_5d": sorted([e for e in five if e["d5_value"] < 0],
                              key=lambda e: e["d5_value"])[:3],
    }


# ---------------------------------------------------------------- 主流程

def main() -> int:
    universe = read_json(DATA / "universe.json") or {}
    quotes_doc = latest_file("quotes")
    quotes = quotes_doc.get("quotes") or {}
    prices = Prices(load_prices())
    names_raw = read_json(DATA / "names.json") or {}
    industries = (read_json(DATA / "industries.json") or {}).get("industries") or {}
    foreign = (latest_file("inst") or {}).get("foreign_net_shares") or {}
    trade_date = prices.days[-1] if prices.days else quotes_doc.get("date")

    names = build_name_map(universe, names_raw)

    if WEB_DATA.exists():
        shutil.rmtree(WEB_DATA)
    (WEB_DATA / "funds").mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    details: dict[str, dict] = {}
    series: dict[str, dict] = {}
    for fund in universe.get("funds") or []:
        code = fund["code"]
        snaps = snapshots(code)
        if not snaps:
            continue
        series[code] = track_positions(snaps, prices)
        detail = build_fund(fund, quotes.get(code, {}), prices, names, industries, series[code])
        if not detail:
            continue
        details[code] = detail
        write_json(WEB_DATA / "funds" / f"{code}.json", detail)
        summaries.append({k: detail[k] for k in (
            "code", "name", "issuer", "as_of", "prev_as_of", "nav", "price", "premium_pct",
            "units_change", "aum", "holding_count", "changes", "stock_weight", "tw_weight",
            "value_coverage", "net_value", "top_move")})
    summaries.sort(key=lambda f: -(f.get("aum") or 0))

    stocks = build_stocks(details, series, prices, names, industries, foreign, trade_date)

    ranking = [s for s in stocks if s.get("d1_shares")]
    ranking.sort(key=lambda s: -abs(s.get("d1_value") or 0))
    signals = {
        "trade_date": trade_date,
        "top_buy": sorted([s for s in summaries if (s.get("net_value") or 0) > 0],
                          key=lambda s: -(s["net_value"] or 0))[:3],
        "top_sell": sorted([s for s in summaries if (s.get("net_value") or 0) < 0],
                           key=lambda s: (s["net_value"] or 0))[:3],
        "ranking": ranking,
    }

    sectors = build_sectors(stocks)

    report = read_json(DATA / "fetch_report.json") or {}
    meta = {
        "built_at": now_tpe().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "universe_count": len(universe.get("funds") or []),
        "covered_count": len(details),
        "covered_aum": round(sum(s.get("aum") or 0 for s in summaries) / 1e8),
        "universe_aum": round(sum((f.get("aum_100m") or 0) for f in universe.get("funds") or [])),
        "stock_count": len(stocks),
        "price_days": len(prices.days),
        "issuers_without_adapter": report.get("issuers_without_adapter", []),
        "failures": report.get("failed", []),
        "sources": ["各投信官網申購買回清單／投資組合明細", "TWSE ETF e添富",
                    "TWSE MIS 淨值折溢價", "TWSE/TPEx 每日收盤行情與成交均價",
                    "TWSE/TPEx 三大法人買賣超", "TWSE/TPEx 公司產業別"],
    }

    write_json(WEB_DATA / "meta.json", meta)
    write_json(WEB_DATA / "funds.json", summaries)
    write_json(WEB_DATA / "stocks.json", stocks)
    write_json(WEB_DATA / "signals.json", signals)
    write_json(WEB_DATA / "sectors.json", sectors)

    print(f"built {len(details)} funds / {len(stocks)} stocks / "
          f"{len(sectors['today'])} sectors / {len(ranking)} moves "
          f"({meta['covered_aum']:,} 億 of {meta['universe_aum']:,} 億)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
