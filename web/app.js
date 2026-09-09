'use strict';

/* ---------------- 資料 ---------------- */
const cache = new Map();
async function load(name) {
  if (!cache.has(name)) {
    cache.set(name, fetch('data/' + name, { cache: 'no-cache' }).then(r => {
      if (!r.ok) throw new Error(name + ' ' + r.status);
      return r.json();
    }));
  }
  return cache.get(name);
}

/* ---------------- 格式 ---------------- */
const esc = s => String(s == null ? '' : s)
  .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const n0 = v => Math.round(v).toLocaleString('zh-TW');

/** 金額：億 / 萬 兩段，跟 App 一樣 */
function money(v, signed = true) {
  if (v == null || !isFinite(v) || v === 0) return signed ? '0' : '—';
  const sign = signed && v > 0 ? '+' : (v < 0 ? '-' : '');
  const a = Math.abs(v);
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(1)}億`;
  if (a >= 1e4) return `${sign}${n0(a / 1e4)}萬`;
  return `${sign}${n0(a)}`;
}
const lots = v => (v == null || !isFinite(v)) ? '—' : n0(v / 1000);
const signedLots = v => {
  // null 代表「沒有可比的前一日」，跟「比較過、沒有變動」是兩件事，不能都寫成 0
  if (v == null || !isFinite(v)) return '—';
  if (Math.round(v / 1000) === 0) return '0';
  return (v > 0 ? '+' : '−') + n0(Math.abs(v) / 1000);
};
const pct = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : v.toFixed(d) + '%';
const signedPct = (v, d = 2) => (v == null || !isFinite(v)) ? '—'
  : (v > 0 ? '+' : '') + v.toFixed(d) + '%';
const dir = v => (v == null || !isFinite(v) || Math.abs(v) < 1e-9) ? 'flat' : (v > 0 ? 'up' : 'down');
const mmdd = s => s ? s.slice(5).replace('-', '/') : '';

const STATUS = { add: '加碼', trim: '減碼', new: '新增', exit: '刪除', hold: '持平' };

/* ---------------- 共用片段 ---------------- */
const head = (title, right = '') => `
  <div class="page-head"><h1>${title}</h1><div class="spacer"></div>${right}</div>`;

function bar(value, max, cls) {
  const w = max ? Math.max(6, Math.min(100, Math.abs(value) / max * 100)) : 0;
  return `<div class="bar ${cls}" style="width:${w}%"></div>`;
}

function changeChips(c, prevDate) {
  if (prevDate == null) return '<span class="badge">首日資料</span>';
  const out = [];
  if (c.add) out.push(`<span class="badge add">加 ${c.add}</span>`);
  if (c.trim) out.push(`<span class="badge trim">減 ${c.trim}</span>`);
  if (c.new) out.push(`<span class="badge new">新 ${c.new}</span>`);
  if (c.exit) out.push(`<span class="badge exit">清 ${c.exit}</span>`);
  return out.join(' ') || '<span class="badge">無異動</span>';
}

/* ================================================================ ETF 列表 */
let fundTab = 'quote';
const fundSort = { key: 'aum', asc: false };

// 這一頁的名稱不重複「主動」兩個字，列表已經全是主動式 ETF
const shortName = s => String(s || '').replace(/^主動/, '');

const FUND_COLS = {
  quote: [
    ['price', '股價', f => f.price == null ? '—' : f.price.toFixed(2), 'plain'],
    ['change_pct', '漲跌幅', f => signedPct(f.change_pct), 'pill'],
    ['premium_pct', '折溢價', f => signedPct(f.premium_pct), 'tint'],
  ],
  perf: [
    ['perf_w1', '一週', f => signedPct(f.performance?.w1), 'tint'],
    ['perf_m1', '一個月', f => signedPct(f.performance?.m1), 'tint'],
    ['perf_y1', '一年', f => signedPct(f.performance?.y1), 'tint'],
  ],
  dividend: [
    ['div_sum', '近一年配息', f => f.dividend?.sum_12m != null ? f.dividend.sum_12m.toFixed(2) : '—', 'plain'],
    ['div_yield', '年化配息率', f => f.dividend?.yield_12m != null ? f.dividend.yield_12m.toFixed(2) + '%' : '—', 'tint-up'],
    ['div_last', '最近除息', f => f.dividend?.last_date ? mmdd(f.dividend.last_date) : '—', 'plain'],
  ],
};

const fundValue = (f, key) => ({
  aum: f.aum, price: f.price, change_pct: f.change_pct, premium_pct: f.premium_pct,
  perf_w1: f.performance?.w1, perf_m1: f.performance?.m1, perf_y1: f.performance?.y1,
  div_sum: f.dividend?.sum_12m, div_yield: f.dividend?.yield_12m,
  div_last: f.dividend?.last_date,
}[key]);

function fundCell(f, [key, , render, style]) {
  const v = fundValue(f, key);
  const text = render(f);
  if (style === 'pill') {
    return `<td><span class="pct-pill ${dir(v)}">${text}</span></td>`;
  }
  if (style === 'tint') return `<td class="${dir(v)}">${text}</td>`;
  if (style === 'tint-up') return `<td class="${v ? 'up' : 'flat'}">${text}</td>`;
  return `<td>${text}</td>`;
}

async function viewFunds() {
  const [funds, meta] = await Promise.all([load('funds.json'), load('meta.json')]);
  const cols = FUND_COLS[fundTab];
  const k = fundSort.key;
  const list = funds.slice().sort((a, b) => {
    const va = fundValue(a, k), vb = fundValue(b, k);
    const na = va == null ? -Infinity : va, nb = vb == null ? -Infinity : vb;
    if (na === nb) return (b.aum || 0) - (a.aum || 0);
    return (na > nb ? 1 : -1) * (fundSort.asc ? 1 : -1);
  });
  const arrow = key => k === key ? (fundSort.asc ? ' ▴' : ' ▾') : ' ⇅';

  return `
  <div class="page-head"><h1>主動式 ETF</h1></div>
  <div class="head-sub">
    <span class="live">● 資料已更新 · ${mmdd(meta.trade_date)} 收盤</span>
    <div class="spacer"></div>
    <span>持股 ${meta.covered_count} 檔已入庫</span>
  </div>
  <div class="texttabs" style="padding-left:20px;padding-right:20px">
    <button data-fundtab="quote" class="${fundTab === 'quote' ? 'on' : ''}">行情</button>
    <button data-fundtab="perf" class="${fundTab === 'perf' ? 'on' : ''}">報酬</button>
    <button data-fundtab="dividend" class="${fundTab === 'dividend' ? 'on' : ''}">股利</button>
  </div>
  <div class="block" style="padding-top:0;border-top:0">
    <div class="tablewrap"><table>
      <thead><tr>
        <th class="sortable ${k === 'aum' ? 'on' : ''}" data-fundsort="aum">市值${arrow('aum')}</th>
        ${cols.map(([key, label]) =>
          `<th class="sortable ${k === key ? 'on' : ''}" data-fundsort="${key}">${label}${arrow(key)}</th>`).join('')}
      </tr></thead>
      <tbody>${list.map(f => `
        <tr onclick="location.hash='#/fund/${f.code}'">
          <td><div class="sym-name">${f.code}</div>
              <div class="sym-code">${esc(shortName(f.name))}</div></td>
          ${cols.map(c => fundCell(f, c)).join('')}
        </tr>`).join('')}</tbody>
    </table></div>
  </div>
  <div class="note-text">依市值排序，點欄位標題可換排序依據。
    ${fundTab === 'perf' ? '績效資料來源：證交所 ETF e添富（全曜財經資訊）。'
      : fundTab === 'dividend' ? '年化配息率 ＝ 近一年配息合計 ÷ 最新股價。'
      : '折溢價 ＝ 市價相對淨值的偏離，資料來自證交所 MIS。'}</div>`;
}

/* ================================================================ 個股反查 */
const stockSort = { key: 'fund_count', asc: false };
let stockQuery = '';

async function viewStocks() {
  const [stocks, meta] = await Promise.all([load('stocks.json'), load('meta.json')]);
  const q = stockQuery.trim().toLowerCase();
  let list = stocks;
  if (q) list = list.filter(s => (s.symbol + s.name).toLowerCase().includes(q));

  const k = stockSort.key;
  list = list.slice().sort((a, b) => {
    const va = a[k] == null ? -Infinity : a[k];
    const vb = b[k] == null ? -Infinity : b[k];
    if (va === vb) return b.total_value - a.total_value;
    return (va > vb ? 1 : -1) * (stockSort.asc ? 1 : -1);
  });

  const th = (key, label) =>
    `<th class="sortable ${k === key ? 'on' : ''}" data-sort="${key}">${label}${
      k === key ? (stockSort.asc ? ' ▲' : ' ▼') : ' ⇅'}</th>`;

  return head('個股反查', `<button class="icon-btn" id="toggle-search" aria-label="搜尋">
      <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg></button>`) + `
  <div class="head-sub">共 ${stocks.length} 檔 · 依「${SORT_LABEL[k]}」排序
    <div class="spacer"></div>${meta.trade_date} 收盤</div>
  <div class="searchbar" ${stockQuery ? '' : 'hidden'} id="searchbar">
    <input id="stock-q" type="search" placeholder="輸入代號或名稱，例如 2330、台積電"
      value="${esc(stockQuery)}" autocomplete="off"></div>
  <div class="block" style="padding-top:0">
    <div class="tablewrap"><table>
      <thead><tr><th>個股</th>${th('change_pct', '漲跌')}${th('total_value', '持有市值')}${th('fund_count', '檔數')}</tr></thead>
      <tbody>${list.slice(0, 400).map(s => `
        <tr onclick="location.hash='#/stock/${encodeURIComponent(s.uid)}'">
          <td><div class="sym-name">${esc(s.name)}</div><div class="sym-code">${s.symbol}</div></td>
          <td class="${dir(s.change_pct)}">${signedPct(s.change_pct)}</td>
          <td><div>${money(s.total_value, false)}</div>
              <div class="sym-code">${lots(s.total_shares)} 張</div></td>
          <td><span class="count-badge">${s.fund_count}</span></td>
        </tr>`).join('')}</tbody>
    </table></div>
    ${list.length ? '' : '<div class="empty">找不到符合的個股</div>'}
  </div>`;
}
const SORT_LABEL = {
  fund_count: '被幾家主動 ETF 持有', total_value: '持有市值', change_pct: '漲跌',
};

/* ================================================================ 個股詳情 */
async function viewStock(raw) {
  const uid = decodeURIComponent(raw);
  const [stocks, meta] = await Promise.all([load('stocks.json'), load('meta.json')]);
  const s = stocks.find(x => x.uid === uid);
  if (!s) return `<div class="empty">目前沒有主動式 ETF 持有 ${esc(uid)}</div>`;

  const holders = s.funds.filter(f => f.status !== 'exit');
  const dropped = s.funds.filter(f => f.status === 'exit');
  const firstDay = holders.filter(f => f.first_day).length;
  const win = [['d1', meta.trade_date ? mmdd(meta.trade_date) : '今日'],
               ['d3', '近 3 日'], ['d5', '近 5 日']];
  const maxAbs = Math.max(...win.map(([k]) => Math.abs(s[k + '_shares'] || 0)), 1);

  return `
  <div class="page-head">
    <a class="back-btn" href="#/stocks" aria-label="返回">
      <svg viewBox="0 0 24 24"><path d="m14.5 5-7 7 7 7"/></svg></a>
    <div class="spacer"></div><h1 style="font-size:20px">${esc(s.name)}</h1>
    <div class="spacer"></div><div style="width:42px"></div>
  </div>

  <div class="card"><div class="card-pad hero">
    <div>
      <div class="big">${esc(s.name)}</div>
      <div class="code">${s.symbol}</div>
      <span class="tag">${esc(s.industry || '—')}</span>
    </div>
    <div class="right">
      <div class="price ${dir(s.change_pct)}">${s.close != null ? s.close : '—'}</div>
      <div class="${dir(s.change_pct)}">${s.change_pct > 0 ? '▲' : s.change_pct < 0 ? '▼' : ''} ${signedPct(s.change_pct)}</div>
      <div class="sym-code">${mmdd(meta.trade_date)} 盤後更新</div>
    </div>
  </div></div>

  <div class="card">
    <div class="stat-row">${win.map(([k, label]) => `
      <div class="stat">
        <span style="margin:0 0 4px">${label}</span>
        <b class="${dir(s[k + '_shares'])}">${signedLots(s[k + '_shares'])} 張</b>
        <div class="sub ${dir(s[k + '_value'])}">${money(s[k + '_value'])}</div>
        ${s[k + '_shares'] ? `<div class="bar ${s[k + '_shares'] > 0 ? 'bg-up' : 'bg-down'}"
          style="width:${Math.max(8, Math.abs(s[k + '_shares']) / maxAbs * 100)}%"></div>` : ''}
      </div>`).join('')}</div>
    <div class="note-text" style="padding-top:0">主動 ETF 淨買賣超${
      s.streak > 1 ? ` · 已連續買超 ${s.streak} 天` : ''}${
      s.foreign_net_shares != null
        ? ` · 外資今日 ${signedLots(s.foreign_net_shares)} 張${s.foreign_aligned ? '（同向）' : ''}` : ''}
      ${firstDay ? `<br>其中 ${firstDay} 家今天才開始記錄，還沒有前一日可比，當日變動尚未計入。` : ''}</div>
  </div>

  <div class="block">
    <div class="block-head"><h2>被 ${s.fund_count} 家主動 ETF 持有</h2></div>
    <div class="tablewrap"><table>
      <thead><tr><th>ETF</th><th>${mmdd(meta.trade_date)}<br>變動</th>
        <th>庫存均價<br>報酬率</th><th>權重<br>張數</th></tr></thead>
      <tbody>${holders.map(f => `
        <tr onclick="location.hash='#/fund/${f.code}'">
          <td><div class="sym-name">${esc(f.name)}</div><div class="sym-code">${f.code}</div></td>
          <td><div class="${dir(f.shares_delta)}">${signedLots(f.shares_delta)}${
              f.shares_delta == null ? '' : ' 張'}</div>
            ${f.first_day
              ? '<div class="badge" style="margin-top:4px">首日</div>'
              : (f.status && f.status !== 'hold'
                ? `<div class="badge ${f.status}" style="margin-top:4px">${STATUS[f.status]}</div>` : '')}</td>
          <td><div>${f.avg_cost != null ? n0(f.avg_cost) : '—'}</div>
            <div class="${dir(f.return_pct)}">${signedPct(f.return_pct)}</div></td>
          <td><div>${pct(f.weight)}</div><div class="sym-code">${lots(f.shares)} 張</div></td>
        </tr>`).join('')}
        ${dropped.map(f => `
        <tr onclick="location.hash='#/fund/${f.code}'">
          <td><div class="sym-name">${esc(f.name)}</div><div class="sym-code">${f.code}</div></td>
          <td><div class="down">${signedLots(f.shares_delta)} 張</div>
            <div class="badge exit" style="margin-top:4px">刪除</div></td>
          <td>—</td><td>—</td>
        </tr>`).join('')}</tbody>
    </table></div>
    <p class="disclaimer" style="margin-top:18px">
      庫存均價由本站依每日持股變動與當日成交均價、以平均成本法推算，非投信揭露亦非實際成交價。
      報酬率為該均價與最新收盤價之比較，只涵蓋目前仍持有的部位，不含已實現損益。
      ${holders.some(f => f.cost_estimated)
        ? `其中標示成本起算日的部位在本站開始記錄前就已存在，建倉成本無從得知，
           以起算日當天的成交均價為起點，數字僅供參考。` : ''}
      ${holders.filter(f => f.cost_from).map(f => `${f.code} 自 ${mmdd(f.cost_from)} 起算`).join('、')}。
    </p>
  </div>`;
}

/* ================================================================ 今日訊號 */
let rankTab = 'buy';
let rankChip = 'all';
let foreignOnly = false;

async function viewSignals() {
  const sig = await load('signals.json');
  const top = (list, cls) => list.length ? list.map(f => `
    <a class="row" href="#/fund/${f.code}" style="padding-left:0;padding-right:0">
      <div class="main">
        <div class="title">${esc(f.name)}</div>
        <div class="sub">${f.code}${f.top_move ? ' ' + esc(f.top_move.name) + ' ' + money(f.top_move.value) : ''}</div>
      </div>
      <div class="right"><div class="amount ${cls}">${money(f.net_value)}</div></div>
    </a>`).join('') : '<div class="empty" style="padding:24px">今日沒有資料</div>';

  let list = sig.ranking.slice();
  if (rankTab === 'buy') list = list.filter(s => s.d1_value > 0).sort((a, b) => b.d1_value - a.d1_value);
  else if (rankTab === 'sell') list = list.filter(s => s.d1_value < 0).sort((a, b) => a.d1_value - b.d1_value);
  else list = list.filter(s => s.streak > 1).sort((a, b) => b.streak - a.streak || b.d1_value - a.d1_value);
  if (rankChip !== 'all') list = list.filter(s => s.status === rankChip);
  if (foreignOnly) list = list.filter(s => s.foreign_aligned);

  const counts = { new: 0, exit: 0, add: 0, trim: 0 };
  sig.ranking.forEach(s => { if (counts[s.status] != null) counts[s.status]++; });

  return head('今日訊號') + `
  <div class="block">
    <div class="rail up">ETF 淨買超 TOP 3</div>
    <div class="rows" style="margin:0">${top(sig.top_buy, 'up')}</div>
  </div>
  <div class="block">
    <div class="rail down">ETF 淨賣超 TOP 3</div>
    <div class="rows" style="margin:0">${top(sig.top_sell, 'down')}</div>
    <p class="disclaimer" style="margin-top:12px">依成分股當日淨變動金額計算，僅計入有收盤價的成分股。</p>
  </div>
  <div class="block">
    <div class="block-head"><h2>排行</h2><span class="note">共 ${sig.ranking.length} 檔</span></div>
    <div class="texttabs">
      <button data-rank="buy" class="${rankTab === 'buy' ? 'on' : ''}">淨買超</button>
      <button data-rank="sell" class="${rankTab === 'sell' ? 'on' : ''}">淨賣超</button>
      <button data-rank="streak" class="${rankTab === 'streak' ? 'on' : ''}">連續買超</button>
      <div class="spacer"></div>
      <button class="toggle-pill ${foreignOnly ? 'on' : ''}" data-foreign="1">外資同向</button>
    </div>
    <div class="pills small">
      <button data-chip="all" class="${rankChip === 'all' ? 'on' : ''}">全部 ${sig.ranking.length}</button>
      <button data-chip="new" class="${rankChip === 'new' ? 'on' : ''}">新增 ${counts.new}</button>
      <button data-chip="exit" class="${rankChip === 'exit' ? 'on' : ''}">刪除 ${counts.exit}</button>
      <button data-chip="add" class="${rankChip === 'add' ? 'on' : ''}">加碼 ${counts.add}</button>
      <button data-chip="trim" class="${rankChip === 'trim' ? 'on' : ''}">減碼 ${counts.trim}</button>
    </div>
    <p class="disclaimer">外資同向 ＝ 當日外資買賣超與主動 ETF 的動作方向一致。</p>
    <div class="rows">${list.length ? list.slice(0, 200).map(s => `
      <a class="row" href="#/stock/${encodeURIComponent(s.uid)}">
        <div class="main">
          <div class="title">${esc(s.name)}
            ${s.foreign_aligned ? '<span class="badge outline">外資</span>' : ''}
            ${s.streak > 1 ? `<span class="badge outline">連 ${s.streak} 天</span>` : ''}</div>
          <div class="sub">${s.symbol} · ${esc(s.industry)}</div>
        </div>
        <div class="right">
          <div>${s.close != null ? n0(s.close) : '—'}</div>
          <div class="${dir(s.change_pct)}">${s.change_pct > 0 ? '▲' : s.change_pct < 0 ? '▼' : ''} ${signedPct(s.change_pct)}</div>
        </div>
        <div class="right" style="min-width:92px">
          <div class="amount ${dir(s.d1_shares)}">${signedLots(s.d1_shares)} 張</div>
          <div class="sub ${dir(s.d1_value)}">${money(s.d1_value)}</div>
        </div>
      </a>`).join('') : '<div class="empty">沒有符合條件的個股</div>'}</div>
  </div>`;
}

/* ================================================================ 板塊輪動 */
let sectorRange = 'd1';
let sectorFilter = 'buy';

async function viewSectors() {
  const [sec, meta] = await Promise.all([load('sectors.json'), load('meta.json')]);
  const vk = sectorRange + '_value';
  const list = (sectorRange === 'd1' ? sec.today : sec.five_day)
    .slice().sort((a, b) => b[vk] - a[vk]);
  const buys = list.filter(e => e[vk] > 0);
  const sells = list.filter(e => e[vk] < 0).sort((a, b) => a[vk] - b[vk]);
  const shown = sectorFilter === 'buy' ? buys : sectorFilter === 'sell' ? sells : list;
  const maxAbs = Math.max(...list.map(e => Math.abs(e[vk])), 1);

  const topBuy = sectorRange === 'd1' ? sec.top_buy : sec.top_buy_5d;
  const topSell = sectorRange === 'd1' ? sec.top_sell : sec.top_sell_5d;
  const cmpMax = Math.max(...[...topBuy, ...topSell].map(e => Math.abs(e[vk])), 1);
  const column = (items, cls) => `<ol>${items.length ? items.map((e, i) => `
    <li>
      <div class="cmp-name"><span class="rank">${i + 1}</span>${esc(e.industry)}</div>
      <div class="cmp-val ${cls}">${money(e[vk])}<small>· ${e.changed} 檔</small></div>
      ${bar(e[vk], cmpMax, cls === 'up' ? 'bg-up' : 'bg-down')}
    </li>`).join('') : '<li class="flat">今日無</li>'}</ol>`;

  return head('板塊輪動') + `
  <div class="segmented">
    <button data-range="d1" class="${sectorRange === 'd1' ? 'on' : ''}">今日</button>
    <button data-range="d5" class="${sectorRange === 'd5' ? 'on' : ''}">近 5 日</button>
  </div>
  <div class="block">
    <div class="block-head"><h2>${mmdd(meta.trade_date)} 加減碼對照</h2>
      <span class="note">金額為推估</span></div>
    <div class="compare">
      <div><div class="rail up">主要加碼</div>${column(topBuy, 'up')}</div>
      <div><div class="rail down">主要減碼</div>${column(topSell, 'down')}</div>
    </div>
  </div>
  <div class="block">
    <div class="block-head"><h2>全部板塊</h2><span class="note">共 ${list.length} 個</span></div>
    <div class="pills">
      <button data-sector="buy" class="${sectorFilter === 'buy' ? 'on' : ''}">加碼 ${buys.length}</button>
      <button data-sector="sell" class="${sectorFilter === 'sell' ? 'on' : ''}">減碼 ${sells.length}</button>
      <button data-sector="all" class="${sectorFilter === 'all' ? 'on' : ''}">全部 ${list.length}</button>
    </div>
    <div class="rows">${shown.length ? shown.map((e, i) => `
      <div class="row">
        <span class="rank">${i + 1}</span>
        <div class="main">
          <div class="title">${esc(e.industry)}</div>
          <div class="sub">${e.holdings} 檔持股 · ${e.changed} 檔有異動</div>
          <div class="sub">${sectorRange === 'd1' ? '近 5 日 ' + money(e.d5_value) : '今日 ' + money(e.d1_value)}</div>
        </div>
        <div class="right">
          <div class="amount ${dir(e[vk])}">${money(e[vk])}</div>
          ${bar(e[vk], maxAbs, e[vk] >= 0 ? 'bg-up' : 'bg-down')}
        </div>
      </div>`).join('') : '<div class="empty">沒有符合條件的板塊</div>'}</div>
    <p class="disclaimer" style="margin-top:16px">
      板塊採主管機關公告的官方產業別（上市／上櫃公司基本資料）。金額為各成分股張數變動 × 當日成交均價的推估值。</p>
  </div>`;
}

/* ================================================================ ETF 詳情 */
let holdSort = { key: 'weight', asc: false };

async function viewFund(code) {
  let d;
  try { d = await load('funds/' + code + '.json'); }
  catch { return `<div class="empty">找不到 ${esc(code)} 的持股資料</div>`; }

  const flow = (d.units_change != null && d.nav != null) ? d.units_change * d.nav : null;
  const cols = [['name', '個股'], ['weight', '權重'], ['shares_delta', '張數增減'],
                ['shares', '張數'], ['avg_cost', '均價／報酬'], ['market_value', '市值']];
  const k = holdSort.key;
  const rows = d.holdings.slice().sort((a, b) => {
    const va = k === 'name' ? a.symbol : (a[k] == null ? -Infinity : a[k]);
    const vb = k === 'name' ? b.symbol : (b[k] == null ? -Infinity : b[k]);
    if (va === vb) return 0;
    return (va > vb ? 1 : -1) * (holdSort.asc ? 1 : -1);
  });

  return `
  <div class="page-head">
    <a class="back-btn" href="#/funds" aria-label="返回">
      <svg viewBox="0 0 24 24"><path d="m14.5 5-7 7 7 7"/></svg></a>
    <div class="spacer"></div><h1 style="font-size:20px">${esc(d.name)}</h1>
    <div class="spacer"></div><div style="width:42px"></div>
  </div>

  <div class="card"><div class="card-pad hero">
    <div>
      <div class="big">${esc(d.name)}</div>
      <div class="code">${d.code} · ${esc(d.issuer)}投信</div>
      <span class="tag">持股基準日 ${d.as_of}</span>
    </div>
    <div class="right">
      <div class="price ${dir(d.net_value)}">${money(d.net_value)}</div>
      <div class="sym-code">當日淨買賣超</div>
    </div>
  </div></div>

  <div class="card"><div class="stat-row">
    <div class="stat"><b>${money(d.aum, false)}</b><span>規模</span></div>
    <div class="stat"><b>${d.nav != null ? d.nav.toFixed(2) : '—'}</b><span>淨值</span></div>
    <div class="stat"><b class="${dir(d.premium_pct)}">${signedPct(d.premium_pct)}</b><span>折溢價</span></div>
    <div class="stat"><b>${d.holding_count}</b><span>持股檔數</span></div>
    <div class="stat"><b class="${dir(flow)}">${money(flow)}</b><span>當日資金流</span></div>
    <div class="stat"><b>${pct(d.stock_weight, 1)}</b><span>持股水位</span></div>
  </div></div>

  <div class="block">
    <div class="block-head"><h2>完整持股</h2><span class="note">${changeChips(d.changes || {}, d.prev_as_of)}</span></div>
    <div class="tablewrap"><table>
      <thead><tr>${cols.map(([key, label]) =>
        `<th class="sortable ${k === key ? 'on' : ''}" data-hold="${key}">${label}${
          k === key ? (holdSort.asc ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(h => `
        <tr onclick="location.hash='#/stock/${encodeURIComponent(h.uid)}'">
          <td><div class="sym-name">${esc(h.name)}
            ${h.status && h.status !== 'hold' ? `<span class="badge ${h.status}">${STATUS[h.status]}</span>` : ''}</div>
            <div class="sym-code">${h.symbol}${h.market !== 'TW' ? ' · ' + h.market : ''}</div></td>
          <td>${pct(h.weight)}</td>
          <td class="${dir(h.shares_delta)}">${h.shares_delta == null ? '—' : signedLots(h.shares_delta)}</td>
          <td>${lots(h.shares)}</td>
          <td><div>${h.avg_cost != null ? n0(h.avg_cost) : '—'}</div>
              <div class="${dir(h.return_pct)}">${signedPct(h.return_pct)}</div></td>
          <td>${money(h.market_value, false)}</td>
        </tr>`).join('')}</tbody>
    </table></div>
  </div>

  ${d.exited.length ? `<div class="block">
    <div class="block-head"><h2>已出清</h2></div>
    <div class="rows">${d.exited.map(h => `
      <a class="row" href="#/stock/${encodeURIComponent(h.uid)}">
        <div class="main"><div class="title">${esc(h.name)}</div>
          <div class="sub">${h.symbol} · 前一日權重 ${pct(h.weight_prev)}</div></div>
        <div class="right"><div class="amount down">${signedLots(h.shares_delta)} 張</div>
          <div class="sub down">${money(h.value_delta)}</div></div>
      </a>`).join('')}</div>
  </div>` : ''}

  <div class="note-text">資料來源：${esc(d.source || '')}。已累積 ${d.history.length} 天持股快照。
    均價為本站依每日持股變動推算，非投信揭露值。</div>`;
}

/* ================================================================ 路由 */
const view = document.getElementById('view');

async function render() {
  const hash = location.hash.replace(/^#\/?/, '') || 'funds';
  const route = hash.split('/')[0];
  const arg = hash.split('/').slice(1).join('/');

  document.querySelectorAll('#tabbar a').forEach(a => {
    const t = a.dataset.tab;
    a.classList.toggle('on', t === route ||
      (route === 'fund' && t === 'funds') || (route === 'stock' && t === 'stocks'));
  });

  view.innerHTML = '<div class="loading">載入中…</div>';
  try {
    let html;
    if (route === 'fund') html = await viewFund(arg);
    else if (route === 'stock') html = await viewStock(arg);
    else if (route === 'stocks') html = await viewStocks();
    else if (route === 'signals') html = await viewSignals();
    else if (route === 'sectors') html = await viewSectors();
    else html = await viewFunds();
    view.innerHTML = html;
    if (route === 'fund' || route === 'stock') window.scrollTo(0, 0);
    const q = document.getElementById('stock-q');
    if (q && stockQuery) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  } catch (err) {
    view.innerHTML = `<div class="empty">資料載入失敗：${esc(err.message)}</div>`;
  }
}

/* ---------------- 互動 ---------------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-sort],[data-hold],[data-rank],[data-chip],[data-foreign],[data-sector],[data-range],[data-fundtab],[data-fundsort],#toggle-search');
  if (!t) return;
  if (t.id === 'toggle-search') {
    const bar = document.getElementById('searchbar');
    bar.hidden = !bar.hidden;
    if (!bar.hidden) bar.querySelector('input').focus();
    return;
  }
  if (t.dataset.sort) {
    const key = t.dataset.sort;
    holdSortReset();
    stockSort.asc = stockSort.key === key ? !stockSort.asc : false;
    stockSort.key = key;
  } else if (t.dataset.hold) {
    const key = t.dataset.hold;
    holdSort.asc = holdSort.key === key ? !holdSort.asc : false;
    holdSort.key = key;
  } else if (t.dataset.rank) rankTab = t.dataset.rank;
  else if (t.dataset.chip) rankChip = t.dataset.chip;
  else if (t.dataset.foreign) foreignOnly = !foreignOnly;
  else if (t.dataset.sector) sectorFilter = t.dataset.sector;
  else if (t.dataset.range) sectorRange = t.dataset.range;
  else if (t.dataset.fundtab) {
    fundTab = t.dataset.fundtab;
    // 換分頁時把排序拉回市值，否則會用一個當下看不到的欄位在排
    fundSort.key = 'aum';
    fundSort.asc = false;
  } else if (t.dataset.fundsort) {
    const key = t.dataset.fundsort;
    fundSort.asc = fundSort.key === key ? !fundSort.asc : false;
    fundSort.key = key;
  }
  render();
});
function holdSortReset() { /* 兩張表的排序狀態各自獨立，這裡只是語意佔位 */ }

let qTimer;
document.addEventListener('input', e => {
  if (e.target.id !== 'stock-q') return;
  stockQuery = e.target.value;
  clearTimeout(qTimer);
  qTimer = setTimeout(render, 180);
});

window.addEventListener('hashchange', render);
render();
