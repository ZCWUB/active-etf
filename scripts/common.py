"""共用工具：HTTP session、重試、日期、JSON 讀寫。"""
from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
import random
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import ssl
from requests.adapters import HTTPAdapter

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TPE = timezone(timedelta(hours=8))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def now_tpe() -> datetime:
    return datetime.now(TPE)


def today_tpe() -> date:
    return now_tpe().date()


class _RelaxedTLSAdapter(HTTPAdapter):
    """關掉 VERIFY_X509_STRICT，但仍驗證憑證鏈。

    部分投信官網的憑證缺少 Subject Key Identifier，瀏覽器接受，
    但 Python 3.13 起預設開啟嚴格檢查會直接拒絕連線。
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def session(referer: str | None = None) -> requests.Session:
    s = requests.Session()
    s.mount("https://", _RelaxedTLSAdapter())
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    })
    if referer:
        s.headers["Referer"] = referer
    return s


def retry(fn, tries: int = 4, base: float = 1.5, label: str = ""):
    """指數退避重試，投信官網偶爾會 5xx 或連線逾時。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 想吞掉所有網路層例外
            last = exc
            if i == tries - 1:
                break
            time.sleep(base ** i + random.random())
    raise RuntimeError(f"{label or 'request'} failed after {tries} tries: {last}") from last


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def to_float(v, default=None):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in {"", "-", "--", "N/A", "n/a"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


CURRENCY_MARKET = {
    "NTD": "TW", "TWD": "TW", "USD": "US", "JPY": "JP", "KRW": "KR",
    "HKD": "HK", "CNY": "CN", "EUR": "EU", "GBP": "GB", "SGD": "SG",
}
# 彭博代碼尾碼 → 市場
SUFFIX_MARKET = {
    "TT": "TW", "US": "US", "UN": "US", "UW": "US", "UQ": "US", "JP": "JP",
    "JT": "JP", "KS": "KR", "HK": "HK", "CH": "CN", "C1": "CN", "SP": "SG",
}


def split_symbol(raw: str) -> tuple[str, str | None]:
    """拆出代號與市場：'2330 TT' -> ('2330','TW')、'002371 CH' -> ('002371','CN')。

    沒有尾碼就回 (代號, None)，由呼叫端用幣別等其他線索判斷市場。
    """
    s = str(raw or "").strip().upper().replace("　", " ")
    if "." in s and " " not in s:  # 2330.TW
        head, _, tail = s.partition(".")
        return head.strip(), SUFFIX_MARKET.get(tail.strip(), None)
    parts = s.split()
    if len(parts) >= 2:
        return parts[0], SUFFIX_MARKET.get(parts[-1], parts[-1])
    return s, None


def norm_symbol(raw: str) -> str:
    return split_symbol(raw)[0]


SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,11}$")
# 4 碼股票（含 2887B 這類特別股）與 00 開頭的 ETF。
# 權證有一萬多檔且與本專案無關，全部濾掉，否則每天多存好幾百 KB，一年就把 repo 撐爆。
TW_SECURITY_RE = re.compile(r"^(?:\d{4}[A-Z]?|00\d{2,4}[A-Z]?)$")


def is_symbol_like(sym: str) -> bool:
    """擋掉解析表格時混進來的「股票合計」「總計」之類的小計列。"""
    return bool(SYMBOL_RE.match(str(sym or "").strip()))


def uid(symbol: str, market: str | None) -> str:
    """跨市場唯一鍵：台股維持純代號，海外加市場前綴，避免日股 6981 撞台股 6981。"""
    return symbol if (market or "TW") == "TW" else f"{market}:{symbol}"


def parse_date(v) -> str:
    """把各家投信五花八門的日期格式收斂成 YYYY-MM-DD。

    支援 ISO、ASP.NET /Date(ms)/、'2026/9/9 上午 12:00:00'、民國 '115/09/09'。
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    m = re.match(r"^/?Date\((-?\d+)([+-]\d{4})?\)/?$", s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, TPE).date().isoformat()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)  # 20260904
    if m:
        return "-".join(m.groups())
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)  # 09/09/2026（美式）
    if m:
        mo, d, y = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"^(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})", s)  # 民國年
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return f"{y + 1911:04d}-{mo:02d}-{d:02d}"
    return ""


class _TableParser(HTMLParser):
    """把 HTML 的 <table> 拆成 (表頭, 資料列) —— 給那些沒有 JSON API、
    只有伺服器端算好表格的投信網站用。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._rows = None
        self._cells = None
        self._buf = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._buf is not None:
            self._cells.append(" ".join("".join(self._buf).split()))
            self._buf = None
        elif tag == "tr" and self._cells is not None:
            if self._cells:
                self._rows.append(self._cells)
            self._cells = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)


def html_tables(html: str) -> list[list[list[str]]]:
    p = _TableParser()
    p.feed(html)
    return p.tables


def text_of(html: str) -> str:
    """去標籤後的純文字，用來撈「資料日期：2026/09/08」這種散落的欄位。"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def twse_isin(code: str) -> str:
    """台股 ETF 的 ISIN：TW + 000 + 六位代號 + Luhn 檢查碼。

    有些投信的網址／API 用 ISIN 當識別碼（例如聯博），從代號直接算比去查對照表省事。
    """
    body = "TW000" + str(code).strip().upper()
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in body)
    total, double = 0, True
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return body + str((10 - total % 10) % 10)


# 申購買回清單頁面上通常有兩個日期：公告日（下一營業日）與持股基準日。
# 基準日會標在「每基數實際申購總價金／差異額」這類欄位前面。
_BASIS_DATE_RE = re.compile(
    r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})\s*每基數(?:實際申購總價金|申購總價金差[異額]?額?)")
_ANY_DATE_RE = re.compile(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}")


def pcf_basis_date(flat_text: str) -> str:
    """從申購買回清單的純文字裡取出「持股基準日」。

    別直接拿頁面標題的日期：那多半是公告日，會比持股基準日晚一天，
    整檔基金就會跟其他家差一天，落在統計視窗外而被靜默漏掉。
    """
    m = _BASIS_DATE_RE.search(flat_text)
    if m:
        return parse_date(m.group(1))
    found = sorted(parse_date(x) for x in _ANY_DATE_RE.findall(flat_text))
    found = [d for d in found if d]
    return found[0] if found else ""  # 取最早的：公告日一定是較晚的那個
