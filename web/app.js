'use strict';

/* ---------------- 資料載入 ---------------- */
const DATA = 'data/';
const cache = new Map();

async function load(name) {
  if (!cache.has(name)) {
    cache.set(name, fetch(DATA + name, { cache: 'no-cache' }).then(r => {
      if (!r.ok) throw new Error(name + ' ' + r.status);
      return r.json();
    }));
  }
  return cache.get(name);
}

/* ---------------- 格式化 ---------------- */
const fmt = {
  yi(v, digits = 1) {                       // 元 → 億元
    if (v == null || !isFinite(v)) return '—';
    return (v / 1e8).toLocaleString('zh-TW', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  lots(v, digits = 0) {                     // 股 → 張
    if (v == null || !isFinite(v)) return '—';
    return (v / 1000).toLocaleString('zh-TW', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  pct(v, digits = 2) {
    if (v == null || !isFinite(v)) return '—';
    return v.toFixed(digits) + '%';
  },
  signed(v, digits = 2) {
    if (v == null || !isFinite(v)) return '—';
    return (v > 0 ? '+' : '') + v.toFixed(digits);
  },
  num(v, digits = 0) {
    if (v == null || !isFinite(v)) return '—';
    return v.toLocaleString('zh-TW', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  date(s) { return s ? s.slice(5).replace('-', '/') : '—'; },
};

const dirClass = v => (v == null || !isFinite(v) || Math.abs(v) < 1e-9) ? 'flat' : (v > 0 ? 'up' : 'down');
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const STATUS = { add: '加碼', trim: '減碼', new: '新進', exit: '出清', hold: '持平' };

/* ---------------- 自選（存在瀏覽器本機） ---------------- */
const watch = {
  key: 'active-etf-watch',
  get() { try { return JSON.parse(localStorage.getItem(this.key)) || []; } catch { return []; } },
  has(id) { return this.get().includes(id); },
  toggle(id) {
    const list = this.get();
    const i = list.indexOf(id);
    if (i >= 0) list.splice(i, 1); else list.push(id);
    try { localStorage.setItem(this.key, JSON.stringify(list)); } catch { /* 無痕模式忽略 */ }
    return i < 0;
  },
};

function starButton(id) {
  return `<button class="star ${watch.has(id) ? 'on' : ''}" data-star="${esc(id)}"
    aria-label="加入自選" title="加入自選">${watch.has(id) ? '★' : '☆'}</button>`;
}

/* ---------------- 小工具 ---------------- */
function sparkline(series, key) {
  const pts = series.filter(p => p[key] != null);
  if (pts.length < 2) return '';
  const vs = pts.map(p => p[key]);
  const min = Math.min(0, ...vs), max = Math.max(0, ...vs);
  const span = (max - min) || 1;
  const w = 300, h = 56, pad = 4;
  const x = i => pad + i * (w - 2 * pad) / (pts.length - 1);
  const y = v => h - pad - (v - min) / span * (h - 2 * pad);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ');
  const zero = (min <= 0 && max >= 0) ? `<line x1="${pad}" x2="${w - pad}" y1="${y(0).toFixed(1)}"
      y2="${y(0).toFixed(1)}" stroke="currentColor" stroke-opacity=".25" stroke-dasharray="3 3"/>` : '';
  const last = pts[pts.length - 1][key];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img"
    aria-label="折溢價走勢，最新 ${last.toFixed(2)}%" style="color:var(--ink-3)">
    ${zero}<path d="${d}" fill="none" stroke="${last >= 0 ? 'var(--up)' : 'var(--down)'}" stroke-width="1.8"/></svg>`;
}

function changeBadges(c, prevDate) {
  // 沒有前一日快照就不能說「無異動」——那是還沒得比，不是經理人沒動作
  if (prevDate === null || prevDate === undefined) {
    return '<span class="badge">首日資料，明天起可比對</span>';
  }
  const parts = [];
  if (c.add) parts.push(`<span class="badge add">加 ${c.add}</span>`);
  if (c.trim) parts.push(`<span class="badge trim">減 ${c.trim}</span>`);
  if (c.new) parts.push(`<span class="badge new">新 ${c.new}</span>`);
  if (c.exit) parts.push(`<span class="badge exit">清 ${c.exit}</span>`);
  return parts.join(' ') || '<span class="badge">無異動</span>';
}

/* ---------------- 視圖：ETF 總覽 ---------------- */
async function viewFunds(q) {
  const funds = await load('funds.json');
  const list = funds.filter(f => match(q, [f.code, f.name, f.issuer]));
  if (!list.length) return `<div class="empty">找不到符合「${esc(q)}」的 ETF</div>`;
  return `<div class="card">${list.map(f => {
    const flow = (f.units_change != null && f.nav != null) ? f.units_change * f.nav : null;
    return `<a class="row" href="#/fund/${f.code}">
      <div class="row-head">
        <span class="code">${f.code}</span>
        <span class="rname">${esc(f.name)}</span>
        <span class="issuer">${esc(f.issuer)}</span>
      </div>
      <div class="row-sub">
        <span>規模 ${fmt.yi(f.aum, 0)} 億</span>
        <span>折溢價 <b class="${dirClass(f.premium_pct)}">${fmt.signed(f.premium_pct)}%</b></span>
        <span>持股 ${f.holding_count} 檔</span>
        ${flow != null ? `<span>資金流 <b class="${dirClass(flow)}">${fmt.signed(flow / 1e8, 1)} 億</b></span>` : ''}
      </div>
      <div class="row-sub">${changeBadges(f.changes || {}, f.prev_as_of)}
        <span class="flat">持股日 ${fmt.date(f.as_of)}</span></div>
    </a>`;
  }).join('')}</div>`;
}

/* ---------------- 視圖：今日動作 ---------------- */
let moveFilter = 'all';
async function viewMoves(q) {
  const moves = await load('moves.json');
  const pills = [['all', '全部'], ['add', '加碼'], ['trim', '減碼'], ['new', '新進'], ['exit', '出清']];
  const list = moves
    .filter(m => moveFilter === 'all' || m.status === moveFilter)
    .filter(m => match(q, [m.symbol, m.name, m.fund, m.code]));

  const head = `<div class="pill-row">${pills.map(([k, label]) =>
    `<button class="pill ${moveFilter === k ? 'on' : ''}" data-move="${k}">${label}</button>`).join('')}</div>`;

  if (!moves.length) {
    return head + `<div class="empty">還沒有可比較的前一日持股。<br>明天收盤後就會出現加減碼。</div>`;
  }
  if (!list.length) return head + `<div class="empty">沒有符合條件的動作</div>`;

  return head + `<div class="card"><div class="scroll"><table>
    <thead><tr><th class="name">ETF ／ 個股</th><th>張數</th><th>估算金額</th><th>權重</th></tr></thead>
    <tbody>${list.slice(0, 200).map(m => `<tr>
      <td class="name">
        <a href="#/stock/${encodeURIComponent(m.uid)}"><span class="sym">${m.symbol}</span> ${esc(m.name || '')}</a>
        <span class="badge ${m.status}">${STATUS[m.status] || m.status}</span>
        <div class="flat" style="font-size:11px">
          <a href="#/fund/${m.code}">${esc(m.fund)}</a></div>
      </td>
      <td class="${dirClass(m.est_shares_delta)}">${fmt.signed(m.est_shares_delta / 1000, 0)}</td>
      <td class="${dirClass(m.est_value_delta)}">${m.est_value_delta == null ? '—'
        : fmt.signed(m.est_value_delta / 1e8, 2) + ' 億'}</td>
      <td>${fmt.pct(m.weight)}</td>
    </tr>`).join('')}</tbody></table></div></div>`;
}

/* ---------------- 視圖：共同持股 ---------------- */
let stockFilter = 'all';
async function viewStocks(q) {
  const stocks = await load('stocks.json');
  const pills = [['all', '全部'], ['multi', '2 檔以上'], ['bought', '今日淨買'], ['sold', '今日淨賣']];
  let list = stocks.filter(s => match(q, [s.symbol, s.name]));
  if (stockFilter === 'multi') list = list.filter(s => s.fund_count > 1);
  if (stockFilter === 'bought') list = list.filter(s => (s.net_est_shares_delta || 0) > 0)
    .sort((a, b) => b.net_est_shares_delta - a.net_est_shares_delta);
  if (stockFilter === 'sold') list = list.filter(s => (s.net_est_shares_delta || 0) < 0)
    .sort((a, b) => a.net_est_shares_delta - b.net_est_shares_delta);

  const head = `<div class="pill-row">${pills.map(([k, label]) =>
    `<button class="pill ${stockFilter === k ? 'on' : ''}" data-stock="${k}">${label}</button>`).join('')}</div>`;
  if (!list.length) return head + `<div class="empty">沒有符合條件的個股</div>`;

  return head + `<div class="card"><div class="scroll"><table>
    <thead><tr><th class="name">個股</th><th>幾檔持有</th><th>合計張數</th><th>合計市值</th><th>今日淨買賣</th></tr></thead>
    <tbody>${list.slice(0, 300).map(s => `<tr>
      <td class="name"><a href="#/stock/${encodeURIComponent(s.uid)}">
        <span class="sym">${s.symbol}</span>${s.market !== 'TW' ? `<span class="mkt">${s.market}</span>` : ''}
        ${esc(s.name || '')}</a></td>
      <td><b>${s.fund_count}</b></td>
      <td>${fmt.lots(s.total_est_shares)}</td>
      <td>${s.total_est_value ? fmt.yi(s.total_est_value) + ' 億' : '—'}</td>
      <td class="${dirClass(s.net_est_shares_delta)}">${s.net_est_shares_delta
        ? fmt.signed(s.net_est_shares_delta / 1000, 0) : '—'}</td>
    </tr>`).join('')}</tbody></table></div></div>`;
}

/* ---------------- 視圖：自選 ---------------- */
async function viewWatch() {
  const ids = watch.get();
  if (!ids.length) {
    return `<div class="empty">還沒有自選。<br>在 ETF 或個股頁面點 ☆ 就會加進來。<br>
      <span class="fine">（自選只存在這台裝置的瀏覽器裡）</span></div>`;
  }
  const [funds, stocks] = await Promise.all([load('funds.json'), load('stocks.json')]);
  const myFunds = funds.filter(f => ids.includes(f.code));
  const myStocks = stocks.filter(s => ids.includes(s.uid));
  let html = '';
  if (myFunds.length) {
    html += `<div class="section-title">自選 ETF</div><div class="card">${myFunds.map(f => `
      <a class="row" href="#/fund/${f.code}">
        <div class="row-head"><span class="code">${f.code}</span>
          <span class="rname">${esc(f.name)}</span></div>
        <div class="row-sub"><span>折溢價 <b class="${dirClass(f.premium_pct)}">${fmt.signed(f.premium_pct)}%</b></span>
          ${changeBadges(f.changes || {}, f.prev_as_of)}</div>
      </a>`).join('')}</div>`;
  }
  if (myStocks.length) {
    html += `<div class="section-title">自選個股</div><div class="card">${myStocks.map(s => `
      <a class="row" href="#/stock/${encodeURIComponent(s.uid)}">
        <div class="row-head"><span class="code">${s.symbol}</span>
          <span class="rname">${esc(s.name || '')}</span>
          <span class="issuer">${s.fund_count} 檔持有</span></div>
        <div class="row-sub"><span>合計 ${fmt.lots(s.total_est_shares)} 張</span>
          <span>今日 <b class="${dirClass(s.net_est_shares_delta)}">${s.net_est_shares_delta
            ? fmt.signed(s.net_est_shares_delta / 1000, 0) + ' 張' : '無異動'}</b></span></div>
      </a>`).join('')}</div>`;
  }
  return html;
}

/* ---------------- 視圖：單一 ETF ---------------- */
let holdSort = { key: 'weight', asc: false };
async function viewFund(code) {
  let d;
  try { d = await load('funds/' + code + '.json'); }
  catch { return `<div class="empty">找不到 ${esc(code)} 的持股資料</div>`; }

  const flow = (d.units_change != null && d.nav != null) ? d.units_change * d.nav : null;
  // 手機優先：最重要的「張數增減」放在需要橫捲之前就看得到
  const cols = [
    ['name', '個股', 'name'], ['weight', '權重', ''], ['est_shares_delta', '張數增減', ''],
    ['weight_delta', '權重增減', ''], ['est_shares', '張數', ''], ['market_value', '市值(億)', ''],
  ];
  const rows = d.holdings.slice().sort((a, b) => {
    const k = holdSort.key;
    const va = k === 'name' ? a.symbol : (a[k] == null ? -Infinity : a[k]);
    const vb = k === 'name' ? b.symbol : (b[k] == null ? -Infinity : b[k]);
    if (va === vb) return 0;
    return (va > vb ? 1 : -1) * (holdSort.asc ? 1 : -1);
  });

  return `<a class="back" href="#/funds">← 全部 ETF</a>
  <div class="card">
    <div class="card-pad">
      <div class="row-head">
        <span class="code">${d.code}</span>
        <span class="rname"><b>${esc(d.name)}</b></span>
        ${starButton(d.code)}
      </div>
      <div class="row-sub"><span>${esc(d.issuer)}投信</span>
        <span>持股基準日 ${d.as_of}${d.prev_as_of ? `（對比 ${fmt.date(d.prev_as_of)}）` : ''}</span></div>
    </div>
    <div class="stats">
      <div class="stat"><b>${fmt.yi(d.aum, 0)}</b><span>規模（億）</span></div>
      <div class="stat"><b>${d.nav != null ? d.nav.toFixed(2) : '—'}</b><span>淨值</span></div>
      <div class="stat"><b class="${dirClass(d.premium_pct)}">${fmt.signed(d.premium_pct)}%</b><span>折溢價</span></div>
      <div class="stat"><b>${d.holding_count}</b><span>持股檔數</span></div>
      <div class="stat"><b class="${dirClass(flow)}">${flow == null ? '—' : fmt.signed(flow / 1e8, 1)}</b><span>當日資金流（億）</span></div>
      <div class="stat"><b>${fmt.pct(d.stock_weight, 1)}</b><span>持股水位</span></div>
    </div>
    <div class="card-pad">${changeBadges(d.changes || {}, d.prev_as_of)}</div>
    ${d.premium_series && d.premium_series.length > 1
      ? `<div class="card-pad" style="padding-top:0">
           <div class="section-title" style="margin-top:0">折溢價走勢（近 ${d.premium_series.length} 日）</div>
           ${sparkline(d.premium_series, 'premium_pct')}</div>` : ''}
  </div>

  <div class="section-title">完整持股（${d.holding_count} 檔）</div>
  <div class="card"><div class="scroll"><table>
    <thead><tr>${cols.map(([k, label, cls]) =>
      `<th class="${cls} ${holdSort.key === k ? (holdSort.asc ? 'asc sorted' : 'sorted') : ''}"
        data-sort="${k}">${label}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(h => `<tr>
      <td class="name"><a href="#/stock/${encodeURIComponent(h.uid)}">
        <span class="sym">${h.symbol}</span>${h.market !== 'TW' ? `<span class="mkt">${h.market}</span>` : ''}
        ${esc(h.name || '')}</a>${h.kind !== 'stock' ? ` <span class="badge">${h.kind}</span>` : ''}
        ${h.status && h.status !== 'hold' ? ` <span class="badge ${h.status}">${STATUS[h.status]}</span>` : ''}</td>
      <td>${fmt.pct(h.weight)}</td>
      <td class="${dirClass(h.est_shares_delta)}">${h.est_shares_delta == null ? '—'
        : fmt.signed(h.est_shares_delta / 1000, 0)}</td>
      <td class="${dirClass(h.weight_delta)}">${h.weight_delta == null ? '—' : fmt.signed(h.weight_delta)}</td>
      <td>${fmt.lots(h.est_shares)}</td>
      <td>${h.market_value ? fmt.yi(h.market_value) : '—'}</td>
    </tr>`).join('')}</tbody></table></div></div>

  ${d.exited && d.exited.length ? `<div class="section-title">已出清</div>
    <div class="card"><div class="scroll"><table>
      <thead><tr><th class="name">個股</th><th>前一日權重</th><th>張數</th></tr></thead>
      <tbody>${d.exited.map(h => `<tr>
        <td class="name"><a href="#/stock/${encodeURIComponent(h.uid)}">
          <span class="sym">${h.symbol}</span> ${esc(h.name || '')}</a></td>
        <td>${fmt.pct(h.weight_prev)}</td>
        <td>${fmt.lots(h.est_shares)}</td></tr>`).join('')}</tbody></table></div></div>` : ''}

  <p class="note">揭露基礎：${d.basis === 'fund' ? '投信公告之全基金持股' : '每一申購買回基數之籃子，已依受益權單位數放大估算'}。
  資料來源：${esc(d.source || '')}。已累積 ${d.history.length} 天持股快照。</p>`;
}

/* ---------------- 視圖：個股反查 ---------------- */
async function viewStock(uidRaw) {
  const uid = decodeURIComponent(uidRaw);
  const stocks = await load('stocks.json');
  const s = stocks.find(x => x.uid === uid);
  if (!s) return `<div class="empty">目前沒有主動式 ETF 持有 ${esc(uid)}</div>`;

  return `<a class="back" href="#/stocks">← 共同持股</a>
  <div class="card">
    <div class="card-pad">
      <div class="row-head">
        <span class="code">${s.symbol}</span>
        <span class="rname"><b>${esc(s.name || '')}</b></span>
        ${s.market !== 'TW' ? `<span class="issuer">${s.market}</span>` : ''}
        ${starButton(s.uid)}
      </div>
    </div>
    <div class="stats">
      <div class="stat"><b>${s.fund_count}</b><span>幾檔主動 ETF 持有</span></div>
      <div class="stat"><b>${fmt.lots(s.total_est_shares)}</b><span>合計張數</span></div>
      <div class="stat"><b>${s.total_est_value ? fmt.yi(s.total_est_value) : '—'}</b><span>合計市值（億）</span></div>
      <div class="stat"><b class="${dirClass(s.net_est_shares_delta)}">${s.net_est_shares_delta
        ? fmt.signed(s.net_est_shares_delta / 1000, 0) : '0'}</b><span>今日淨買賣（張）</span></div>
      <div class="stat"><b>${s.close != null ? s.close : '—'}</b><span>收盤價</span></div>
      <div class="stat"><b>${(s.added_by.length + s.new_by.length)} / ${(s.trimmed_by.length + s.exited_by.length)}</b>
        <span>今日買進／賣出檔數</span></div>
    </div>
  </div>

  <div class="section-title">持有它的主動式 ETF</div>
  <div class="card"><div class="scroll"><table>
    <thead><tr><th class="name">ETF</th><th>權重</th><th>張數</th><th>今日增減</th><th>動作</th></tr></thead>
    <tbody>${s.funds.map(f => `<tr>
      <td class="name"><a href="#/fund/${f.code}"><span class="sym">${f.code}</span> ${esc(f.name)}</a></td>
      <td>${fmt.pct(f.weight)}</td>
      <td>${fmt.lots(f.est_shares)}</td>
      <td class="${dirClass(f.est_shares_delta)}">${f.est_shares_delta == null ? '—'
        : fmt.signed(f.est_shares_delta / 1000, 0)}</td>
      <td><span class="badge ${f.status}">${STATUS[f.status] || ''}</span></td>
    </tr>`).join('')}</tbody></table></div></div>
  ${s.exited_by.length ? `<p class="note">今日出清：${s.exited_by.join('、')}</p>` : ''}`;
}

/* ---------------- 路由 ---------------- */
function match(q, fields) {
  if (!q) return true;
  const needle = q.trim().toLowerCase();
  return fields.some(f => String(f || '').toLowerCase().includes(needle));
}

const view = document.getElementById('view');
const searchBox = document.getElementById('search');

async function render() {
  const hash = location.hash.replace(/^#\/?/, '') || 'funds';
  const [route, arg] = [hash.split('/')[0], hash.split('/').slice(1).join('/')];
  const q = searchBox.value.trim();

  document.querySelectorAll('#tabs a').forEach(a => {
    const tab = a.dataset.tab;
    a.classList.toggle('on', tab === route ||
      (route === 'fund' && tab === 'funds') || (route === 'stock' && tab === 'stocks'));
  });
  searchBox.style.display = (route === 'fund' || route === 'stock') ? 'none' : '';

  view.innerHTML = '<div class="loading">載入中…</div>';
  try {
    let html;
    if (route === 'fund') html = await viewFund(arg);
    else if (route === 'stock') html = await viewStock(arg);
    else if (route === 'moves') html = await viewMoves(q);
    else if (route === 'stocks') html = await viewStocks(q);
    else if (route === 'watch') html = await viewWatch();
    else html = await viewFunds(q);
    view.innerHTML = html;
    if (route === 'fund' || route === 'stock') window.scrollTo(0, 0);
  } catch (err) {
    view.innerHTML = `<div class="empty">資料載入失敗：${esc(err.message)}</div>`;
  }
}

async function renderStamp() {
  try {
    const m = await load('meta.json');
    document.getElementById('stamp').textContent =
      `${m.trade_date} 收盤　更新 ${(m.built_at || '').slice(11, 16)}`;
    document.getElementById('coverage').textContent =
      `已涵蓋 ${m.covered_count} / ${m.universe_count} 檔主動式 ETF，約 ${Number(m.covered_aum).toLocaleString('zh-TW')} 億元規模` +
      (m.issuers_without_adapter && m.issuers_without_adapter.length
        ? `。尚未接入：${m.issuers_without_adapter.join('、')}投信。` : '。');
  } catch { document.getElementById('stamp').textContent = '資料尚未產生'; }
}

/* ---------------- 事件 ---------------- */
let searchTimer;
searchBox.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(render, 150);
});

document.addEventListener('click', e => {
  const star = e.target.closest('[data-star]');
  if (star) {
    e.preventDefault();
    const on = watch.toggle(star.dataset.star);
    star.classList.toggle('on', on);
    star.textContent = on ? '★' : '☆';
    return;
  }
  const mv = e.target.closest('[data-move]');
  if (mv) { moveFilter = mv.dataset.move; render(); return; }
  const st = e.target.closest('[data-stock]');
  if (st) { stockFilter = st.dataset.stock; render(); return; }
  const th = e.target.closest('[data-sort]');
  if (th) {
    const k = th.dataset.sort;
    holdSort = { key: k, asc: holdSort.key === k ? !holdSort.asc : false };
    render();
  }
});

window.addEventListener('hashchange', render);
renderStamp();
render();
