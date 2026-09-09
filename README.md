# 主動ETF底牌

台灣主動式 ETF 的每日持股追蹤：把各投信每天公告的持股存成快照，比較出**經理人昨天買了什麼、賣了什麼**，
再算出跨基金共同持股與折溢價。

純靜態網站 + GitHub Actions 排程，**不需要自己開電腦或養伺服器**，手機開網址就能看，連結可以直接分享。

## 四個畫面

| 分頁 | 內容 |
| --- | --- |
| ETF 列表 | 每檔主動式 ETF 的規模、折溢價、持股檔數、當日淨買賣超金額與最大貢獻個股 |
| 個股反查 | 全部個股依「被幾家主動 ETF 持有」排序，可改用持有市值或漲跌排序；點進去看 1／3／5 日淨買賣超、被哪幾家持有，以及**每一家的庫存均價與報酬率** |
| 今日訊號 | ETF 淨買超／賣超 TOP 3；個股排行可切淨買超／淨賣超／連續買超，並依新增、刪除、加碼、減碼篩選，或只看與外資同向的 |
| 板塊輪動 | 今日與近 5 日的板塊加減碼對照與完整排行 |

### 庫存均價是怎麼算出來的

投信只公告「今天持有多少股」，不公告成本。這裡用**平均成本法**回推：
每天的持股增量 × 當天的成交均價累加成本，減碼不動成本，最後與最新收盤價比較得出報酬率。

有兩個限制必須講清楚，介面上也會標示：

- 這是推估值，不是投信揭露的數字，也不是實際成交價。
- 本站開始記錄之前就已經在的部位，建倉成本無從得知，只能以起算日當天的均價當起點。
  這種部位會標明「自 X 月 X 日起算」，數字只能參考；之後才新建的部位才是真的知道買進價。

## 目前接了哪幾家投信

17 家全部接入，涵蓋 38 檔主動式 ETF。`scripts/issuers/` 一家一個檔案。

| 投信 | 取得方式 | 可回補歷史 |
| --- | --- | --- |
| 統一 | `ezmoney.com.tw` GetPCF（投資組合明細） | 是 |
| 群益 | `capitalfund.com.tw` 申購買回清單 API | 否 |
| 元大 | `etfapi.yuantaetfs.com` PCF/Daily | 是 |
| 復華 | `fhtrust.com.tw` 基金資產明細 | 是 |
| 國泰 | `cwapi.cathaysite.com.tw` 持股權重 | 是 |
| 中國信託 | `ctbcinvestments.com.tw` ETFHoldingWeight（需先換 token） | 是 |
| 富邦 | `websys.fsit.com.tw` 基金資產（解析 HTML 表格） | 是 |
| 凱基 | `kgifund.com.tw` RedemptionVC（HTML 片段） | 是 |
| 野村 | `nomurafunds.com.tw` GetFundAssets | 否 |
| 聯博 | `webapi.alliancebernstein.com` holdings（ISIN 由代號直接算） | 是 |
| 摩根 | `am.jpmorgan.com` product-data | 否 |
| 永豐 | `sitc.sinopac.com` 現金申購買回清單（HTML） | 否 |
| 兆豐國際 | `megafunds.com.tw`（ASP.NET WebForms 兩段 postback） | 否 |
| 台新 | `tsit.com.tw` Pcf（POST 表單） | 是 |
| 第一金 | `fsitc.com.tw` WebAPI.aspx/Get_hd | 是 |
| 安聯 | `etf.allianzgi.com.tw`，**需無頭瀏覽器** | 否 |

安聯的 webapi 對任何非瀏覽器發出的請求一律回 400——偽裝 TLS 指紋、補齊瀏覽器標頭、
甚至在無頭瀏覽器裡自己 `fetch` 都沒用，只有頁面上的 Angular 自己發的那一次會成功。
所以那一家改成開無頭瀏覽器、攔截頁面自己打出去的回應。沒安裝 Playwright 時
該 adapter 會安靜略過，其他 16 家照常運作。

### 新增一家投信

在 `scripts/issuers/` 加一個模組，提供三樣東西：

```python
ISSUER = "某某"                      # 要和 universe.json 的 issuer 一致
def discover(sess, codes) -> dict:   # {ETF代號: 該投信內部代號}
def fetch(sess, code, internal_id, on_date=None) -> dict
```

`fetch` 回傳的 snapshot 至少要有 `as_of`（持股基準日）與 `holdings`
（`symbol`／`name`／`market`／`shares`／`weight`／`kind`）。
若該投信可查歷史日期，加上 `SUPPORTS_BACKFILL = True`，`backfill.py` 就會自動補歷史。
最後把模組加進 `scripts/issuers/__init__.py` 的 `ADAPTERS`。

**接完務必看 `web/data/funds.json` 的 `value_coverage`**：那是「台股持股市值 ÷（規模 × 台股權重）」，
正常會落在 1.0 附近。明顯偏離代表該投信公告的是「每一申購買回基數的籃子」而不是全基金持股，
這時要把 `basis` 設成 `"basket"` 並填 `fund_units` / `unit_size`，程式會自動放大估算。

## 每日怎麼跑

```bash
pip install -r requirements.txt
python -m playwright install chromium   # 只有安聯那家需要

python scripts/fetch_universe.py     # ETF 清單
python scripts/fetch_quotes.py       # 淨值、折溢價、受益權單位數
python scripts/fetch_prices.py       # 收盤價與成交均價
python scripts/fetch_institutions.py # 三大法人買賣超
python scripts/fetch_industries.py   # 產業別
python scripts/fetch_pcf.py          # 各投信持股 → data/pcf/<代號>/<日期>.json
python scripts/build_site.py         # 算出四個畫面要的資料 → web/data/
```

回補歷史（第一次架站時很有用，可以立刻看到加減碼與均價，不必等隔天）：

```bash
python scripts/backfill.py --days 30
```

```bash
python scripts/fetch_prices.py --backfill 30
```

本機預覽：

```bash
python -m http.server 8791 --directory web
```

## 部署到 GitHub Pages

1. 建一個 repo，把這個資料夾推上去。
2. Settings → Pages → Source 選 **GitHub Actions**。
3. Actions 分頁跑一次 `每日更新主動式 ETF 持股`（可在 `backfill_days` 填 30 先補歷史）。

推程式碼上去也會自動重新建置發佈（忽略 data/，避免工作流程自己觸發自己）。
之後每個交易日台灣時間 18:10 與 21:40 會自動更新：抓資料 → 算結果 → 把當日快照 commit 回 repo → 重新發佈網站。
資料留在 git 裡，所以歷史會愈積愈完整，也不會因為某天抓失敗就消失。

## 幾個實作上的坑

- **權重跌不等於減碼。** 股價漲跌會改變權重。判斷加減碼一律以張數為準，只有在該投信沒揭露張數時才退回看權重。
- **海外持股不能跟台股混算。** 日股村田代號 6981 會撞台股 6981，所以個股一律用 `市場:代號` 當唯一鍵，
  台股維持純代號。海外部位的金額是當地幣別，不換算成台幣市值。
- **部分投信憑證缺 Subject Key Identifier**，Python 3.13 起的嚴格檢查會直接拒連；
  `common.session()` 關掉 `VERIFY_X509_STRICT` 但保留憑證鏈驗證。
- **海外型基金當天常常還沒公告**，`fetch_pcf.py` 會自動往回找最近 7 個營業日。

## 免責

本專案只整理公開資訊，僅供參考，不構成投資建議。實際持股與淨值請以各基金公司公告為準。
