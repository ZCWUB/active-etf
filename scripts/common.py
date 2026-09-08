"""共用工具：HTTP session、重試、日期、JSON 讀寫。"""
from __future__ import annotations

import json
import os
import re
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
    m = re.match(r"^(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})", s)  # 民國年
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return f"{y + 1911:04d}-{mo:02d}-{d:02d}"
    return ""
