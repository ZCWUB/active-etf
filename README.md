# 主動ETF底牌

台灣主動式 ETF 的每日持股追蹤：把各投信每天公告的持股存成快照，比較出**經理人昨天買了什麼、賣了什麼**，
再算出跨基金共同持股與折溢價。

純靜態網站 + GitHub Actions 排程，**不需要自己開電腦或養伺服器**，手機開網址就能看，連結可以直接分享。

## 它會回答什麼

| 頁面 | 內容 |
| --- | --- |
| ETF | 每檔主動式 ETF 的規模、折溢價、當日淨申購／買回金額、持股檔數、當日加減碼張數 |
| 今日動作 | 全市場當日最大的加碼／減碼／新進／出清，含估算金額 |
| 共同持股 | 哪一檔個股被最多主動式 ETF 持有、合計張數與市值、當日淨買賣 |
| 個股反查 | 輸入 2330，看哪些主動 ETF 持有它、各自權重與當日增減 |
| 自選 | 追蹤的 ETF 與個股（存在瀏覽器本機，不上傳） |

## 資料從哪來

全部是公開資訊，直接取自第一手來源：

- **持股明細**：各投信官網每日公告的「申購買回清單／投資組合明細」。主動式 ETF 依規定須每日揭露完整持股。
- **ETF 清單**：證交所 ETF e添富投資篩選器，再用 MIS 即時報價補上剛掛牌、篩選器還沒收錄的基金。
- **淨值、市價、折溢價、受益權單位數**：證交所 MIS `all_etf`。單位數的日增減就是當日淨申購／買回，也就是資金流。
- **個股收盤價**：TWSE 與 TPEx 的每日收盤行情，用來把張數換算成市值。

## 目前接了哪幾家投信

`scripts/issuers/` 一家投信一個檔案。已接入：

| 投信 | 取得方式 | 可回補歷史 |
| --- | --- | --- |
| 統一 | `ezmoney.com.tw` GetPCF（投資組合明細） | 是 |
| 群益 | `capitalfund.com.tw` 申購買回清單 API | 否（只給最新一日） |
| 元大 | `etfapi.yuantaetfs.com` PCF/Daily | 是 |
| 復華 | `fhtrust.com.tw` 基金資產明細 | 是 |
| 國泰 | `cwapi.cathaysite.com.tw` 持股權重 | 是 |

尚未接入的投信會顯示在網站頁尾與 `web/data/meta.json` 的 `issuers_without_adapter`。

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
python scripts/fetch_universe.py   # ETF 清單
python scripts/fetch_quotes.py     # 淨值、折溢價、受益權單位數
python scripts/fetch_stocks.py     # 個股收盤價
python scripts/fetch_pcf.py        # 各投信持股 → data/pcf/<代號>/<日期>.json
python scripts/build_site.py       # 算出加減碼與共同持股 → web/data/
```

回補歷史（第一次架站時很有用，可以立刻看到加減碼，不必等隔天）：

```bash
python scripts/backfill.py --days 30
```

本機預覽：

```bash
python -m http.server 8791 --directory web
```

## 部署到 GitHub Pages

1. 建一個 repo，把這個資料夾推上去。
2. Settings → Pages → Source 選 **GitHub Actions**。
3. Actions 分頁跑一次 `每日更新主動式 ETF 持股`（可在 `backfill_days` 填 30 先補歷史）。

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
