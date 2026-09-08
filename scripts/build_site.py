"""把每日快照算成網站要吃的 JSON：加減碼、共同持股、折溢價。

輸出到 web/data/：
  meta.json          建置時間、涵蓋度、資料來源
  funds.json         每檔 ETF 摘要（規模、折溢價、資料日期、當日異動檔數）
  funds/<代號>.json  單一 ETF 的完整持股＋與前一交易日的差異＋折溢價走勢
  stocks.json        個股反查：哪些主動 ETF 持有它、合計估算張數／市值
  moves.json         全市場當日最大加碼／減碼／新進／出清
"""
from __future__ import annotations

import shutil
from collections import defaultdict

from common import DATA, ROOT, now_tpe, read_json, uid, write_json

WEB_DATA = ROOT / "web" / "data"
TRADABLE = {"stock", "etf"}  # 納入個股統計的類別（期貨、現金、債券不列入）


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


def scale_of(snap: dict, mis_units: float | None) -> float:
    """實物申贖清單是「每一申購買回基數」的籃子，要放大成全基金估計持股。"""
    if snap.get("basis") != "basket":
        return 1.0
    unit_size = snap.get("unit_size")
    if not unit_size:
        return 1.0
    units = snap.get("fund_units") or mis_units
    if not units:
        return 1.0
    return units / unit_size


def index_holdings(snap: dict, scale: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for h in snap.get("holdings") or []:
        sym = h.get("symbol")
        if not sym:
            continue
        row = dict(h)
        row.setdefault("market", "TW")
        key = uid(sym, row["market"])
        row["est_shares"] = (h.get("shares") or 0) * scale if h.get("shares") else None
        prev = out.get(key)
        if prev:  # 同一標的分列多筆（例如現股＋零股），合併
            for k in ("shares", "est_shares", "weight", "market_value"):
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
    if cur.get("est_shares") is not None and prev.get("est_shares") is not None:
        ds = cur["est_shares"] - prev["est_shares"]
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


def _coverage(rows: list[dict], aum: float | None) -> float | None:
    if not aum:
        return None
    tw = [r for r in rows if r["kind"] in TRADABLE and r["market"] == "TW"]
    weight = sum(r["weight"] or 0 for r in tw)
    value = sum(r["market_value"] or 0 for r in tw)
    if weight < 5 or not value:
        return None
    return round(value / (aum * weight / 100), 3)


def build_fund(fund: dict, quote: dict, closes: dict, premium_hist: list[dict]) -> dict | None:
    snaps = snapshots(fund["code"])
    if not snaps:
        return None
    cur = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None
    mis_units = quote.get("units")
    cur_idx = index_holdings(cur, scale_of(cur, mis_units))
    prev_idx = index_holdings(prev, scale_of(prev, mis_units)) if prev else {}

    rows = []
    for key, h in cur_idx.items():
        p = prev_idx.get(key)
        close = (closes.get(h["symbol"]) or {}).get("close") if h.get("market") == "TW" else None
        est = h.get("est_shares")
        rows.append({
            "uid": key,
            "symbol": h["symbol"],
            "name": h.get("name"),
            "market": h.get("market", "TW"),
            "kind": h.get("kind"),
            "weight": h.get("weight"),
            "weight_delta": None if not p else round((h.get("weight") or 0) - (p.get("weight") or 0), 4),
            "shares": h.get("shares"),
            "est_shares": est,
            "est_shares_delta": None if not p else (est or 0) - (p.get("est_shares") or 0),
            "market_value": h.get("market_value") or ((est * close) if est and close else None),
            "close": close,
            "status": classify(h, p) if prev else "hold",
        })
    rows.sort(key=lambda r: -(r.get("weight") or 0))

    exited = []
    for key, p in prev_idx.items():
        if key in cur_idx:
            continue
        close = (closes.get(p["symbol"]) or {}).get("close") if p.get("market") == "TW" else None
        est = p.get("est_shares")
        exited.append({
            "uid": key,
            "symbol": p["symbol"],
            "name": p.get("name"),
            "market": p.get("market", "TW"),
            "kind": p.get("kind"),
            "weight_prev": p.get("weight"),
            "est_shares": est,
            "market_value": (est * close) if est and close else None,
            "status": "exit",
        })
    exited.sort(key=lambda r: -(r.get("weight_prev") or 0))

    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    counts["exit"] = len(exited)

    return {
        "code": fund["code"],
        "name": fund["name"],
        "issuer": fund["issuer"],
        "fund_name": cur.get("fund_name"),
        "basis": cur.get("basis"),
        "as_of": cur.get("as_of"),
        "prev_as_of": prev.get("as_of") if prev else None,
        "fetched_at": cur.get("fetched_at"),
        "source": cur.get("source"),
        "nav": quote.get("nav"),
        "price": quote.get("price"),
        "premium_pct": quote.get("premium_pct"),
        "units": quote.get("units"),
        "units_change": quote.get("units_change"),
        "aum": quote.get("aum"),
        "holding_count": len(rows),
        "changes": dict(counts),
        "stock_weight": round(sum(r["weight"] or 0 for r in rows if r["kind"] in TRADABLE), 2),
        "tw_weight": round(sum(r["weight"] or 0 for r in rows
                               if r["kind"] in TRADABLE and r["market"] == "TW"), 2),
        # 台股持股市值 ÷（規模×台股權重）：正常接近 1，偏離代表某家投信的張數單位解讀有誤
        "value_coverage": _coverage(rows, quote.get("aum")),
        "holdings": rows,
        "exited": exited,
        "history": [s.get("as_of") for s in snaps],
        "premium_series": premium_hist,
    }


def main() -> int:
    universe = read_json(DATA / "universe.json") or {}
    quotes_doc = latest_file("quotes")
    quotes = quotes_doc.get("quotes") or {}
    closes = (latest_file("stocks") or {}).get("stocks") or {}

    premium_hist: dict[str, list] = defaultdict(list)
    qdir = DATA / "quotes"
    for p in sorted(qdir.glob("*.json")) if qdir.exists() else []:
        doc = read_json(p) or {}
        for code, q in (doc.get("quotes") or {}).items():
            premium_hist[code].append({
                "date": doc.get("date"),
                "nav": q.get("nav"),
                "price": q.get("price"),
                "premium_pct": q.get("premium_pct"),
                "units": q.get("units"),
                "units_change": q.get("units_change"),
            })

    if WEB_DATA.exists():
        shutil.rmtree(WEB_DATA)
    (WEB_DATA / "funds").mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    details: dict[str, dict] = {}
    for fund in universe.get("funds") or []:
        code = fund["code"]
        detail = build_fund(fund, quotes.get(code, {}), closes, premium_hist.get(code, []))
        if not detail:
            continue
        details[code] = detail
        write_json(WEB_DATA / "funds" / f"{code}.json", detail)
        summary = {k: detail[k] for k in (
            "code", "name", "issuer", "basis", "as_of", "prev_as_of", "nav", "price",
            "premium_pct", "units_change", "aum", "holding_count", "changes", "stock_weight",
            "tw_weight", "value_coverage")}
        summary["top"] = [{"symbol": h["symbol"], "name": h["name"], "weight": h["weight"]}
                          for h in detail["holdings"][:5]]
        summaries.append(summary)
    summaries.sort(key=lambda f: -(f.get("aum") or 0))

    # 個股反查：哪些主動 ETF 持有它
    idx: dict[str, dict] = {}
    for code, d in details.items():
        for h in d["holdings"] + d["exited"]:
            if h.get("kind") not in TRADABLE:
                continue
            key = h["uid"]
            e = idx.setdefault(key, {
                "uid": key,
                "symbol": h["symbol"],
                "name": h.get("name"),
                "market": h.get("market", "TW"),
                "close": h.get("close"),
                "funds": [],
                "total_est_shares": 0.0,
                "total_est_value": 0.0,
                "net_est_shares_delta": 0.0,
                "added_by": [], "trimmed_by": [], "new_by": [], "exited_by": [],
            })
            if h.get("status") == "exit":
                e["exited_by"].append(code)
                e["net_est_shares_delta"] -= h.get("est_shares") or 0
                continue
            e["funds"].append({
                "code": code,
                "name": d["name"],
                "weight": h.get("weight"),
                "est_shares": h.get("est_shares"),
                "status": h.get("status"),
                "est_shares_delta": h.get("est_shares_delta"),
            })
            e["total_est_shares"] += h.get("est_shares") or 0
            e["total_est_value"] += h.get("market_value") or 0
            e["net_est_shares_delta"] += h.get("est_shares_delta") or 0
            if h.get("status") == "add":
                e["added_by"].append(code)
            elif h.get("status") == "trim":
                e["trimmed_by"].append(code)
            elif h.get("status") == "new":
                e["new_by"].append(code)

    stocks = sorted(idx.values(), key=lambda e: (-len(e["funds"]), -e["total_est_value"]))
    for e in stocks:
        e["fund_count"] = len(e["funds"])
        e["funds"].sort(key=lambda f: -(f.get("weight") or 0))

    # 當日全市場動作
    moves = []
    for code, d in details.items():
        if not d.get("prev_as_of"):
            continue
        for h in d["holdings"] + d["exited"]:
            if h.get("status") in {"hold", None} or h.get("kind") not in TRADABLE:
                continue
            delta_shares = h.get("est_shares_delta")
            if delta_shares is None:
                delta_shares = -(h.get("est_shares") or 0) if h.get("status") == "exit" else 0
            close = h.get("close")
            moves.append({
                "code": code,
                "fund": d["name"],
                "uid": h["uid"],
                "symbol": h["symbol"],
                "market": h.get("market", "TW"),
                "name": h.get("name"),
                "status": h["status"],
                "weight": h.get("weight") or h.get("weight_prev"),
                "weight_delta": h.get("weight_delta"),
                "est_shares_delta": delta_shares,
                "est_value_delta": (delta_shares * close) if close else None,
                "as_of": d["as_of"],
            })
    moves.sort(key=lambda m: -abs(m.get("est_value_delta") or 0))

    report = read_json(DATA / "fetch_report.json") or {}
    meta = {
        "built_at": now_tpe().isoformat(timespec="seconds"),
        "trade_date": quotes_doc.get("date"),
        "universe_count": len(universe.get("funds") or []),
        "covered_count": len(details),
        "covered_aum": round(sum(s.get("aum") or 0 for s in summaries) / 1e8),
        "universe_aum": round(sum((f.get("aum_100m") or 0) for f in universe.get("funds") or [])),
        "missing": [f["code"] for f in universe.get("funds") or [] if f["code"] not in details],
        "issuers_without_adapter": report.get("issuers_without_adapter", []),
        "failures": report.get("failed", []),
        "sources": ["各投信官網申購買回清單／投資組合明細", "TWSE ETF e添富",
                    "TWSE MIS 淨值折溢價", "TWSE/TPEx 每日收盤價"],
    }

    write_json(WEB_DATA / "meta.json", meta)
    write_json(WEB_DATA / "funds.json", summaries)
    write_json(WEB_DATA / "stocks.json", stocks)
    write_json(WEB_DATA / "moves.json", moves[:300])

    print(f"built {len(details)} funds / {len(stocks)} stocks / {len(moves)} moves "
          f"({meta['covered_aum']:,} 億 of {meta['universe_aum']:,} 億)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
