"""抓上市／上櫃公司的產業別，供板塊輪動統計用。

來源：TWSE 與 TPEx 的公開資料（公司基本資料，欄位「產業別」是代碼）。
輸出：data/industries.json  {symbol: 產業名稱}

註：這是主管機關的官方分類（約 30 類）。市面上的 App 常自建更細的板塊
（例如把半導體再拆成晶圓代工／設備／IC 設計），那是各家自訂的分類，
沒有公開來源可以照抄，所以這裡採官方產業別。
"""
from __future__ import annotations

from common import DATA, now_tpe, retry, session, write_json

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維", "05": "電機機械",
    "06": "電器電纜", "07": "化學生技醫療", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵",
    "11": "橡膠", "12": "汽車", "13": "電子", "14": "建材營造", "15": "航運",
    "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療", "23": "油電燃氣", "24": "半導體",
    "25": "電腦及週邊設備", "26": "光電", "27": "通信網路", "28": "電子零組件",
    "29": "電子通路", "30": "資訊服務", "31": "其他電子", "32": "文化創意",
    "33": "農業科技", "34": "電子商務", "35": "綠能環保", "36": "數位雲端",
    "37": "運動休閒", "38": "居家生活", "80": "管理股票",
}


def _get(sess, url: str, label: str) -> list:
    def call():
        r = sess.get(url, timeout=45)
        r.raise_for_status()
        return r.json()

    return retry(call, label=label)


def main() -> int:
    sess = session()
    out: dict[str, str] = {}

    for row in _get(sess, TWSE_URL, "twse industries"):
        code = str(row.get("公司代號") or "").strip()
        name = INDUSTRY.get(str(row.get("產業別") or "").strip())
        if code and name:
            out[code] = name

    for row in _get(sess, TPEX_URL, "tpex industries"):
        code = str(row.get("SecuritiesCompanyCode") or "").strip()
        name = INDUSTRY.get(str(row.get("SecuritiesIndustryCode") or "").strip())
        if code and name:
            out.setdefault(code, name)

    write_json(DATA / "industries.json", {
        "updated_at": now_tpe().isoformat(timespec="seconds"),
        "source": "TWSE／TPEx 公司基本資料的官方產業別",
        "industries": dict(sorted(out.items())),
    })
    print(f"industries: {len(out)} 檔股票、{len(set(out.values()))} 個產業")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
