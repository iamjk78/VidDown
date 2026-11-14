'use strict';
/* VidDown – webové GUI (varianta B: postranní panel a přehled) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let LANG = 'cs';
const T = (cs, en) => (LANG === 'en' && en !== undefined ? en : cs);

const ICONS = {
  external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  rss: '<path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.2"/>',
  play: '<path d="M7 4v16l13-8z"/>', pause: '<path d="M8 5v14M16 5v14"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  grip: '<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" stroke-width="3"/>',
  down: '<path d="M6 9l6 6 6-6"/>', right: '<path d="M9 6l6 6-6 6"/>', up: '<path d="M6 15l6-6 6 6"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  settings: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 3"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>', download: '<path d="M12 4v12M7 11l5 5 5-5M5 20h14"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/>', check: '<path d="M5 12l5 5L20 7"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  send: '<path d="M21 3L3 10.5l7 2.5 2.5 7z"/><path d="M10 13l4-4"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  undo: '<path d="M4 4v5h5"/><path d="M4.5 13A8 8 0 1 0 6 7L4 9"/>', plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>',
  bolt: '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>', hdd: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13l2-8h10l2 8M7 16.5h.01"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>', terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  cookie: '<path d="M12 3a9 9 0 1 0 9 9 4 4 0 0 1-4-4 4 4 0 0 1-5-5z"/><path d="M8.5 13.5h.01M12 17h.01M15.5 13h.01"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.2-1.7-.4-1.1.3-2.3 1.5-2.3H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10z"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8z"/><path d="M7.5 7.5h.01"/>', help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>', external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>', globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
};
const ic = (n, s = 16) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[n] || ''}</svg>`;

const App = { qsel: new Set(), qshown: [], view: 'queue', session: null, st: null, settings: null, engines: null, hist: { items: [], q: '', status: '', days: 30, offset: 0 },
  expanded: new Set(), drag: null, es: null, timer: null, wizardShown: false, args: [], subFilter: null, subReady: false };
function parseHash() { const h = (location.hash || '#queue').slice(1).split('/'); App.view = h[0] || 'queue'; App.args = h.slice(1); }

/* ------------------------------------------------------------ pomocné */
async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: {} };
  if (opts.body instanceof FormData) o.body = opts.body;
  else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, o);
  if (r.status === 401 && !path.startsWith('/api/login')) { renderLogin(); throw new Error('auth'); }
  let data = null; try { data = await r.json(); } catch (e) { /* bez těla */ }
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || r.statusText);
  return data;
}
function toast(msg, err = false) {
  const el = document.createElement('div'); el.className = 'toast' + (err ? ' err' : ''); el.textContent = msg;
  $('#toasts').appendChild(el); setTimeout(() => el.remove(), err ? 6000 : 2500);
}
async function act(fn, okMsg) { try { const r = await fn(); if (okMsg) toast(okMsg); return r; } catch (e) { if (e.message !== 'auth') toast(e.message, true); } }
function fmtBytes(n) { if (!n) return '—'; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return (i < 2 ? Math.round(n) : n.toFixed(n >= 100 ? 0 : 1)).toString().replace('.', LANG === 'cs' ? ',' : '.') + ' ' + u[i]; }
const fmtSpeed = b => b ? fmtBytes(b) + '/s' : '—';
function fmtDur(s) { if (s == null) return ''; s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`; }
function fmtDate(ts) {
  if (!ts) return '—'; const d = new Date(ts * 1000), now = new Date();
  const hm = d.toLocaleTimeString(LANG === 'cs' ? 'cs-CZ' : 'en-GB', { hour: '2-digit', minute: '2-digit' });
  const day = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  if (day === 0) return T('dnes ', 'today ') + hm; if (day === 1) return T('včera ', 'yesterday ') + hm;
  return d.toLocaleDateString(LANG === 'cs' ? 'cs-CZ' : 'en-GB');
}
function fmtPub(ts) {                                                         // datum zveřejnění videa: datum a (u čerstvých) stáří
  if (!ts) return ''; const d = new Date(ts * 1000), days = Math.floor((Date.now() - d.getTime()) / 864e5);
  const abs = d.toLocaleDateString(LANG === 'cs' ? 'cs-CZ' : 'en-GB');
  if (days < 0 || days > 60) return abs;
  return abs + ' · ' + (days === 0 ? T('dnes', 'today') : days === 1 ? T('včera', 'yesterday') : T(`před ${days} dny`, `${days} days ago`));
}
const pct = p => p == null ? '' : Math.floor(p * 100) + ' %';
const srcIcon = s => ({ telegram: ic('send', 12), cli: ic('terminal', 12), subscription: ic('rss', 12) }[s] || ic('download', 12));
const srcName = s => ({ telegram: 'Telegram', cli: 'CLI', subscription: T('Odběr', 'Subscription') }[s] || 'GUI');
const methodBadge = m => m ? `<span class="badge ${m === 'sniffer' ? 'b-sn' : 'b-yt'}">${m === 'ytdlp' ? 'yt-dlp' : m}</span>` : '<span class="badge b-n">—</span>';
function applyTheme(theme) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
/* zobrazení miniatur ve frontě (jen v tomto prohlížeči) */
function thumbsOn() { try { return localStorage.getItem('vd_thumbs') !== '0'; } catch (e) { return true; } }
function setThumbs(on) { try { localStorage.setItem('vd_thumbs', on ? '1' : '0'); } catch (e) { /* bez úložiště */ } }
function thumbHtml(j, w, h, opts = {}) {
  const busy = j.status === 'new' || j.status === 'probing';
  const inner = busy ? '<div class="spin"></div>' : ic('film', 20);
  const img = j.has_thumb ? `<img src="/api/thumb/${j.id}" loading="lazy" alt="" style="position:absolute;inset:0" onerror="this.remove()">` : '';
  const dur = j.duration && !opts.noDur ? `<span class="dur">${fmtDur(j.duration)}</span>` : '';
  const res = opts.res && j.height ? `<span class="res">${j.height}p</span>` : '';
  return `<div class="th ${busy || !j.has_thumb ? 'ph' : ''} ${opts.cls || ''}" style="width:${w}px;height:${h}px">${inner}${img}${res}${dur}</div>`;
}

/* ------------------------------------------------------------ start */
async function boot() {
  try { App.session = await api('/api/session'); } catch (e) { $('#app').innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  LANG = App.session.language || 'cs'; document.documentElement.lang = LANG; applyTheme(App.session.theme || 'system');
  if (App.session.auth_required && !App.session.authed) return renderLogin();
  start();
}
async function start() {
  parseHash();
  $('#app').innerHTML = '<div class="layout"><aside class="side" id="side"></aside><main class="main" id="mainwrap"><div class="main-in" id="appbn" style="display:none;margin-bottom:18px"></div><div class="main-in" id="main"></div></main></div>';
  try { App.settings = await api('/api/settings'); } catch (e) { return; }
  connectSSE(); render();
}
function connectSSE() {
  if (App.es) App.es.close();
  const es = new EventSource('/api/events');
  es.onmessage = e => { App.st = JSON.parse(e.data); onState(); };
  App.es = es;
}
function onState() {
  if (!App.st.onboarded && !App.wizardShown) { App.wizardShown = true; openWizard(); }
  renderSide();
  renderAppBanner();
  if ($('#schstat')) renderSchedStatus();
  if (App.view === 'catalog') catPaintBanner();
  if (App.view === 'queue' && !App.drag) renderQueueDyn();
  if (App.view === 'subs' && !App.args.length) renderSubsDyn();
  if (App.view === 'sub') {
    if (!App.subReady) renderSub();
    else { updateSubHead(); if (App.subFilter && !App.drag) renderQueueDyn(); }
  }
}
window.addEventListener('hashchange', () => { parseHash(); render(); });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => App.settings && applyTheme(App.settings.values.theme));
function go(v) { if (/^settings\//.test(v)) App.setQ = ''; location.hash = v; }

function render() {
  clearInterval(App.timer); App.timer = null;
  App.subFilter = null; App.subReady = false;
  renderSide();
  const freshSettings = async () => { const r = await act(() => api('/api/settings')); if (r) App.settings = r; if (App.view === 'settings') renderSettings(); };
  const views = { queue: renderQueue, history: () => renderHistory(), subs: () => (App.args[0] === 'new' ? renderSubNew() : renderSubs()), sub: renderSub, stats: renderStats,
    settings: freshSettings, engines: renderEngines, help: renderHelp, catalog: renderCatalog };
  const wide = App.view === 'catalog';                                      // Katalog využije celou šířku okna (ostatní obrazovky zůstávají vystředěné)
  $('#main').classList.toggle('wide', wide); $('#appbn').classList.toggle('wide', wide);
  (views[App.view] || renderQueue)();
  $('#mainwrap').scrollTop = 0;
}

/* ------------------------------------------------------------ postranní panel */
function renderSide() {
  const st = App.st; const side = $('#side'); if (!side) return;
  const n = st ? st.queue.filter(j => j.kind === 'video' && j.status !== 'running' || j.status === 'running').length : 0;
  const subs = subList(), subN = subs.reduce((a, x) => a + x.queued + x.running, 0);
  const nav = [['queue', 'list', T('Fronta', 'Queue'), n], ['history', 'history', T('Historie', 'History')], ['subs', 'rss', T('Odběry', 'Subscriptions'), subN], ['catalog', 'film', T('Katalog', 'Catalog')], ['stats', 'chart', T('Statistiky', 'Statistics')],
    ['settings', 'settings', T('Nastavení', 'Settings')], ['engines', 'cpu', T('Enginy', 'Engines')], ['help', 'help', T('Nápověda', 'Help')]];
  const subNav = subs.length ? `<div class="subnav">${subs.map(x => `<button class="nav sub ${App.view === 'sub' && +App.args[0] === x.id ? 'on' : ''}" data-go="sub/${x.id}" title="${esc(x.title || x.url)}">
    <span class="dot ${x.last_error ? 'r' : x.pending ? 'y' : x.enabled ? 'g' : ''}"></span><span class="ell">${esc(x.title || x.url)}</span>${x.queued + x.running ? `<span class="n">${x.queued + x.running}</span>` : ''}</button>`).join('')}</div>` : '';
  const setNav = `<div class="subnav setnav">${SET_GROUPS().map(x => `<button class="nav sub ${App.view === 'settings' && !(App.setQ || '').trim() && setGroup() === x.id ? 'on' : ''}" data-go="settings/${x.id}">${ic(x.icon, 14)}<span class="ell">${x.title}</span></button>`).join('')}</div>`;
  const keepScroll = $('.subnav', side) ? $('.subnav', side).scrollTop : 0;
  const tg = st ? st.telegram : { state: 'off' };
  const tgTxt = { ok: T('Telegram bot připojen', 'Telegram bot connected'), off: T('Telegram vypnutý', 'Telegram off'),
    error: T('Telegram: chyba spojení', 'Telegram: connection error'), nochat: T('Telegram: chybí chat ID', 'Telegram: chat ID missing') }[tg.state] || tg.state;
  const disk = st ? st.disk : null;
  const dark = document.documentElement.dataset.theme === 'dark';
  const sideHtml = `<div class="logo"><div class="mk">${ic('download', 16)}</div>VidDown</div>
  <div class="col gap4 navs">${nav.map(([v, i, l, c]) => `<button class="nav ${App.view === v ? 'on' : ''}" data-go="${v}">${ic(i, 17)}${l}${c ? `<span class="n">${c}</span>` : ''}</button>${v === 'settings' && App.view === 'settings' ? setNav : ''}${v === 'subs' && (App.view === 'subs' || App.view === 'sub') ? subNav : ''}`).join('')}</div>
  <div class="grow"></div>
  <div class="sfoot col gap8">
   ${disk ? `<div class="card" style="padding:12px;background:var(--surface2)">${disk.same_disk
      ? `<div class="row fs12 t2" style="justify-content:space-between"><span class="row gap6">${ic('hdd', 14)} ${T('Disk', 'Disk')}</span><span><b style="color:var(--text)">${fmtBytes(disk.target_free)}</b> ${T('volno', 'free')}</span></div>`
      : `<div class="row fs12 t2" style="justify-content:space-between" title="${esc(disk.dir)}"><span class="row gap6">${ic('folder', 14)} ${T('Cíl', 'Target')}</span>${disk.target_reliable ? `<span><b style="color:var(--text)">${fmtBytes(disk.target_free)}</b> ${T('volno', 'free')}</span>` : `<span class="muted" title="${T('Docker Desktop na macOS u složek z /Volumes (síťové disky) hlásí místo interního disku Macu, proto se nezobrazuje.', 'Docker Desktop on macOS reports the Mac disk for folders from /Volumes (network shares), so it is not shown.')}">${T('nelze zjistit', 'unknown')} ⓘ</span>`}</div>
       <div class="row fs12 t2" style="justify-content:space-between;margin-top:4px" title="${T('Rozpracovaná stahování', 'Downloads in progress')}: ${esc(disk.temp_dir)}"><span class="row gap6">${ic('hdd', 14)} ${T('Dočasná', 'Temp')}</span><span><b style="color:var(--text)">${fmtBytes(disk.temp_free)}</b> ${T('volno', 'free')}</span></div>`}
   ${disk.temp_used ? `<div class="row fs12 t2" style="justify-content:space-between;margin-top:4px" title="${T('Velikost rozpracovaných stahování v dočasné složce', 'Size of downloads in progress in the temp folder')}"><span>${T('Rozpracováno', 'In progress')}</span><b style="color:var(--text)">${fmtBytes(disk.temp_used)}</b></div>` : ''}
   ${st.stats.need ? (() => { const bad = disk.target_reliable && disk.target_free != null && st.stats.need > disk.target_free * 0.9; return `<div class="row fs12" style="justify-content:space-between;margin-top:4px;${bad ? 'color:var(--err)' : ''}" title="${T('Odhad místa, které ještě zabere fronta (podle odhadu velikostí videí)', 'Estimated space the queue will still need (based on video size estimates)')}"><span class="${bad ? '' : 't2'}">${T('Fronta zabere', 'Queue needs')}</span><b style="${bad ? '' : 'color:var(--text)'}">~${fmtBytes(st.stats.need)}${bad ? ' ⚠' : ''}</b></div>`; })() : ''}
   <div class="fs11 muted ell" style="margin-top:6px" title="${esc(disk.dir)}">${esc(disk.dir)}</div></div>` : ''}
   ${cpuBox(st)}
   <div class="row gap8 fs12 t2" style="padding:6px 6px 0"><span class="dot ${tg.state === 'ok' ? 'g' : tg.state === 'error' ? 'r' : ''}"></span>${tgTxt}</div>
   <div class="row gap8 fs12 t2" style="padding:2px 6px"><span class="row gap6">${ic('moon', 14)} ${T('Tmavý režim', 'Dark mode')}</span><span class="grow"></span><button class="toggle ${dark ? 'on' : ''}" id="darkt" aria-label="dark mode"></button></div>
   <div class="row fs11 muted" style="padding:2px 6px;justify-content:space-between"><span>VidDown ${esc(st ? st.version : '')}</span>
   <span class="row gap4"><button class="btn ghost sm" style="height:22px;padding:0 6px" data-lang="cs">CS</button><button class="btn ghost sm" style="height:22px;padding:0 6px" data-lang="en">EN</button><button class="btn ghost sm" style="height:22px;padding:0 6px" id="srestart" title="${T('Restartovat aplikaci', 'Restart app')}">${ic('refresh', 12)}</button></span></div>
  </div>`;
  morphHtml(side, sideHtml);
  $$('[data-go]', side).forEach(b => b.onclick = () => go(b.dataset.go));
  if (keepScroll && $('.subnav', side)) $('.subnav', side).scrollTop = keepScroll;
  $$('[data-perf]', side).forEach(b => b.onclick = async () => { await saveSetting('perf_mode', b.dataset.perf, () => {}); if (App.st && App.st.cpu) App.st.cpu.mode = b.dataset.perf; renderSide(); });
  $('#srestart', side).onclick = restartApp;
  $('#darkt', side).onclick = () => saveSetting('theme', dark ? 'light' : 'dark');
  $$('[data-lang]', side).forEach(b => { b.style.fontWeight = b.dataset.lang === LANG ? '700' : '400'; b.onclick = () => saveSetting('language', b.dataset.lang); });
}

/* ------------------------------------------------------------ fronta */
function renderQueue() {
  $('#main').innerHTML = `
  <div class="row gap16 wrap"><div><h1>${T('Fronta', 'Queue')}</h1><div class="t2" style="margin-top:3px">${T('Stahuje se postupně v pořadí přidání', 'Downloads run in the order they were added')}</div></div><div class="grow"></div>
   <form id="addf" class="row gap8" style="width:min(620px,100%)"><div class="inwrap grow">${ic('link', 16)}<input id="addurl" placeholder="${T('Vložte URL videa, playlistu nebo kanálu…', 'Paste a video, playlist or channel URL…')}" autocomplete="off"></div>
   <button class="btn primary lg" type="submit">${ic('plus', 15)} ${T('Přidat', 'Add')}</button></form></div>
  <div id="qdyn" class="col gap16"></div>`;
  $('#addf').onsubmit = async e => {
    e.preventDefault(); const v = $('#addurl').value.trim(); if (!v) return;
    const r = await act(() => api('/api/jobs', { method: 'POST', body: { urls: v } }));
    if (r) { $('#addurl').value = ''; const dup = r.jobs.filter(j => !j.new).length; toast(dup ? T('Některé URL už ve frontě jsou', 'Some URLs are already queued') : T('Přidáno do fronty', 'Added to queue')); }
  };
  $('#addurl').addEventListener('paste', () => setTimeout(() => { const v = $('#addurl').value; if (/\s/.test(v.trim())) $('#addf').requestSubmit(); }, 0));
  renderQueueDyn();
}

function statusLine(j) {
  const now = Date.now() / 1000;
  if (j.status === 'new') return `<span class="muted">${T('Čeká na kontrolu URL', 'Waiting for URL check')}</span>`;
  if (j.status === 'probing') return `<span class="spin" style="width:11px;height:11px"></span> ${T('Kontroluji URL…', 'Checking URL…')}`;
  if (j.paused) return `<span class="badge b-warn">${ic('pause', 11)} ${T('Pozastaveno · přeskakuje se', 'Paused · skipped')}</span>`;
  if (j.status === 'queued' && j.not_before && j.not_before > now)
    return `<span class="err ell">${ic('refresh', 12)} ${T('Opakuji za', 'Retrying in')} ${fmtDur(j.not_before - now)} · ${esc(j.error || '')}</span>`;
  const parts = [j.channel, j.kind === 'video' ? null : null].filter(Boolean).map(esc);
  return `<span class="ell">${parts.join(' · ')}${parts.length ? ' · ' : ''}</span>${srcIcon(j.source)} ${srcName(j.source)}`;
}

function rowHtml(j, pos, child = false) {
  const pz = j.paused ? ' pz' : '';
  const title = j.title || j.url;
  const isGroup = j.kind !== 'video';
  const acts = j.paused
    ? `<button class="btn sm" data-a="resume" data-id="${j.id}">${ic('play', 12)} ${T('Povolit', 'Resume')}</button>`
    : `<button class="ibtn" title="${T('Pozastavit', 'Pause')}" data-a="pause" data-id="${j.id}">${ic('pause', 15)}</button>`;
  let meta;
  if (isGroup) {
    const kids = App.st.queue.filter(c => c.parent_id === j.id);
    meta = `<span class="badge b-n" style="height:18px">${j.kind === 'channel' ? T('Kanál', 'Channel') : 'Playlist'} · ${j.count ?? kids.length} ${T('videí', 'videos')}</span> ${T('zbývá', 'left')} ${kids.length} · ${srcIcon(j.source)} ${srcName(j.source)}`;
  } else meta = statusLine(j);
  const right = isGroup ? '' : `${j.size_est ? '~' + fmtBytes(j.size_est) : ''}${j.size_est && j.height ? ' · ' : ''}${j.height ? j.height + 'p' : ''}${j.approx ? ' ' + T('(odhad)', '(est.)') : ''}`;
  const toggle = isGroup ? `<button class="ibtn" data-a="expand" data-id="${j.id}" title="${T('Rozbalit', 'Expand')}">${ic(App.expanded.has(j.id) ? 'up' : 'down', 15)}</button>` : '';
  const selOn = App.qsel.has(j.id);
  return `<div class="qr${pz}${child ? ' child' : ''}${selOn ? ' qon' : ''}" data-row="${j.id}" ${child ? '' : 'draggable="true"'}>
   <span class="qck"><input type="checkbox" class="qsel" data-id="${j.id}" ${selOn ? 'checked' : ''} title="${T('Vybrat k odstranění', 'Select for removal')}"></span>
   <span class="grip">${child ? '' : ic('grip', 15)}</span><span class="pos">${pos ?? ''}</span>
   <div class="fade">${thumbsOn() ? thumbHtml(j, child ? 72 : 96, child ? 40 : 54, { cls: isGroup ? 'stack' : '' }) : ''}</div>
   <div style="min-width:0"><div class="b6 ell fade" title="${esc(title)}">${esc(title)}</div><div class="mm">${meta}</div></div>
   <div class="fade hide-s">${methodBadge(j.method)}</div><div class="t2 fs12 fade hide-s">${right}</div>
   <div class="acts">${toggle}${acts}<button class="ibtn" title="${T('Odstranit z fronty', 'Remove from queue')}" data-a="cancel" data-id="${j.id}">${ic('x', 15)}</button></div></div>`;
}

function runHtml(j) {
  const p = j.progress; const sn = j.method === 'sniffer';
  return `<div class="card run">${thumbsOn() ? thumbHtml(j, 176, 99, { res: true }) : ''}
  <div class="grow"><div class="row gap8"><span class="b6 fs15 ell">${esc(j.title || j.url)}</span>${methodBadge(j.method)}</div>
  <div class="t2 fs12 row gap6" style="margin-top:4px">${esc(j.channel || '')}${j.channel ? ' · ' : ''}${j.height ? j.height + 'p · ' : ''}${T('přidáno přes', 'added via')} ${srcName(j.source)}</div>
  <div class="bar thick ${sn ? 'sn' : ''} ${p == null ? 'ind' : ''}" style="margin-top:14px"><i style="width:${p == null ? 35 : Math.max(1, p * 100)}%"></i></div>
  <div class="row fs12 t2 wrap" style="margin-top:8px;gap:18px"><span><b style="color:var(--text);font-size:13px">${j.stage === 'post' ? T('Zpracovávám (ffmpeg: metadata, miniatura)…', 'Processing (ffmpeg: metadata, thumbnail)…') : j.stage === 'move' ? T('Přesouvám do cílové složky…', 'Moving to the target folder…') : p != null ? pct(p) : j.downloaded ? T('Stahuji…', 'Downloading…') : T('Načítám informace o videu…', 'Fetching video info…')}</b></span>
   <span>${fmtBytes(j.downloaded)}${j.total ? ' ' + T('z', 'of') + ' ' + fmtBytes(j.total) : ''}</span>
   <span class="row gap4">${ic('bolt', 13)} ${fmtSpeed(j.speed)}</span><span class="row gap4">${ic('clock', 13)} ${T('zbývá', 'left')} ${j.eta != null ? fmtDur(j.eta) : '—'}</span></div></div>
  <div class="row gap6" style="align-self:flex-start"><button class="ibtn b" title="${T('Pozastavit', 'Pause')}" data-a="pause" data-id="${j.id}">${ic('pause', 15)}</button><button class="ibtn b" title="${T('Zrušit', 'Cancel')}" data-a="cancel" data-id="${j.id}">${ic('x', 15)}</button></div></div>`;
}

/* Překreslení bez blikání: nové HTML se „vlije“ do stávajícího DOM, takže se mění jen to, co se opravdu změnilo
   (text, atributy, nové řádky). Obrázky a prvky, které zůstávají, se nevytvářejí znovu. Řádky se párují podle data-row / id. */
function morphHtml(host, html) {
  const tmp = document.createElement('div'); tmp.innerHTML = html;
  morphKids(host, tmp);
}
function morphKids(a, b) {
  const keyOf = n => n.nodeType === 1 ? (n.dataset.row || n.id || '') : '';
  const keyed = new Map(), loose = [];
  for (const n of a.childNodes) { const k = keyOf(n); if (k) keyed.set(k, n); else loose.push(n); }
  let li = 0; const out = [];
  for (const nb of [...b.childNodes]) {
    const k = keyOf(nb); let na = null;
    if (k) { na = keyed.get(k) || null; if (na) keyed.delete(k); }
    else if (li < loose.length) { const c = loose[li]; if (c.nodeType === nb.nodeType && (c.nodeType !== 1 || c.tagName === nb.tagName)) { na = c; li++; } }
    if (na && !(na.nodeType === 1 && na.tagName !== nb.tagName)) { morphNode(na, nb); out.push(na); } else out.push(nb);
  }
  out.forEach((n, i) => { if (a.childNodes[i] !== n) a.insertBefore(n, a.childNodes[i] || null); });
  while (a.childNodes.length > out.length) a.removeChild(a.lastChild);
}
function morphNode(a, b) {
  if (a.nodeType !== 1) { if (a.data !== b.data) a.data = b.data; return; }
  for (const at of [...a.attributes]) if (!b.hasAttribute(at.name)) a.removeAttribute(at.name);
  for (const at of b.attributes) if (a.getAttribute(at.name) !== at.value) a.setAttribute(at.name, at.value);
  if (a.tagName === 'INPUT') {
    if (a.type === 'checkbox' || a.type === 'radio') a.checked = b.hasAttribute('checked');
    else if (a !== document.activeElement) a.value = b.getAttribute('value') || '';
    return;
  }
  morphKids(a, b);
}

/* hromadný výběr ve frontě: výběr se drží po videích; playlist je vybraný, jen když jsou vybraná všechna jeho videa */
function qNormalize(q) {
  const ids = new Set(q.map(j => j.id));
  for (const id of [...App.qsel]) if (!ids.has(id)) App.qsel.delete(id);
  for (const j of q) {
    if (j.kind === 'video' || j.parent_id) continue;
    const kids = q.filter(c => c.parent_id === j.id);
    if (!kids.length) continue;   // playlist bez rozbalených položek se vybírá sám
    if (kids.every(c => App.qsel.has(c.id))) App.qsel.add(j.id); else App.qsel.delete(j.id);
  }
}
function qWaitingKids(q, j) { return q.filter(c => c.parent_id === j.id && c.status !== 'running'); }
function qSelectShown(q) {
  for (const id of App.qshown) {
    const j = q.find(x => x.id === id); if (!j) continue;
    App.qsel.add(id);
    if (j.kind !== 'video' && !j.parent_id) qWaitingKids(q, j).forEach(c => App.qsel.add(c.id));
  }
  qNormalize(q);
}
function qToggle(q, id, on) {
  const j = q.find(x => x.id === id); if (!j) return;
  const group = j.kind !== 'video' && !j.parent_id;
  if (on) { App.qsel.add(id); if (group) qWaitingKids(q, j).forEach(c => App.qsel.add(c.id)); }
  else { App.qsel.delete(id); if (group) q.filter(c => c.parent_id === id).forEach(c => App.qsel.delete(c.id)); }
  qNormalize(q);
}
function qCount(q) {
  const vids = q.filter(j => App.qsel.has(j.id) && j.kind === 'video').length;
  return vids || q.filter(j => App.qsel.has(j.id)).length;
}
async function qRemoveSelected(q) {
  const ids = q.filter(j => App.qsel.has(j.id) && !(j.parent_id && App.qsel.has(j.parent_id))).map(j => j.id);   // vybraný playlist = jeden příkaz
  const n = qCount(q), lists = q.filter(j => App.qsel.has(j.id) && j.kind !== 'video' && !j.parent_id).length;
  if (!ids.length) return;
  if (!confirm(T(`Odebrat z fronty ${n} ${n === 1 ? 'video' : n < 5 ? 'videa' : 'videí'}${lists ? ` (včetně ${lists} celých playlistů)` : ''}? Stažené soubory se nemění.`,
    `Remove ${n} item(s) from the queue${lists ? ` (including ${lists} whole playlist(s))` : ''}? Downloaded files are not affected.`))) return;
  if (await act(() => api('/api/jobs/bulk-cancel', { method: 'POST', body: { ids } }), T('Odebráno z fronty', 'Removed from the queue'))) App.qsel.clear();
  renderQueueDyn();
}
document.addEventListener('change', e => {
  const cb = e.target; if (!cb.classList || !cb.classList.contains('qsel') || !App.st) return;
  const q = App.subFilter ? App.st.queue.filter(j => j.sub_id === App.subFilter) : App.st.queue;
  qToggle(q, +cb.dataset.id, cb.checked); renderQueueDyn();
});
function renderQueueDyn() {
  const box = $('#qdyn'); const st = App.st; if (!box || !st) return;
  const q = App.subFilter ? st.queue.filter(j => j.sub_id === App.subFilter) : st.queue, s = st.stats;
  const top = q.filter(j => !j.parent_id);
  const running = q.filter(j => j.status === 'running');
  const confirm = top.filter(j => j.status === 'confirm');
  const waitingAll = top.filter(j => j.status !== 'running' && j.status !== 'confirm');
  // filtr podle názvu (i podle kanálu a URL); playlist se ukáže, když vyhovuje on nebo některá jeho položka
  const f = (App.qf || '').trim().toLowerCase();
  const hit = j => !f || [j.title, j.url, j.channel].some(x => x && String(x).toLowerCase().includes(f));
  const kidsOf = j => q.filter(c => c.parent_id === j.id && c.status !== 'running');
  const waiting = f ? waitingAll.filter(j => hit(j) || (j.kind !== 'video' && kidsOf(j).some(hit))) : waitingAll;
  let html = '';
  if (st.queue_paused) {
    const disk = st.pause_reason === 'disk';
    const target = st.pause_reason === 'target', cook = st.pause_reason === 'cookies';
    if (cook) html += `<div class="banner">${ic('cookie', 18)}<span class="grow">${T('Fronta je pozastavená: cookies nejdou načíst', 'Queue paused: cookies cannot be loaded')} – ${esc((st.cookies_error || '').slice(0, 200))}</span>
      <button class="btn sm" data-go="settings">${T('Nastavení', 'Settings')}</button><button class="btn sm" data-q="resume">${ic('play', 12)} ${T('Pokračovat', 'Resume')}</button></div>`;
    else
    html += `<div class="banner">${ic(disk ? 'hdd' : target ? 'folder' : 'pause', 18)}<span class="grow">${disk ? (st.disk.low_kind === 'temp' ? T('Fronta je pozastavená: v dočasné složce je málo místa', 'Queue paused: low space in the temp folder') + ` (${fmtBytes(st.disk.temp_free)}, ${esc(st.disk.temp_dir)}, min. ${st.disk.min_gb} GB)` : T('Fronta je pozastavená: v cílové složce je málo místa', 'Queue paused: low space in the download folder') + ` (${fmtBytes(st.disk.target_free)}, min. ${st.disk.min_gb} GB)`)
      : target ? T('Fronta je pozastavená: cílová složka není dostupná', 'Queue paused: download folder is not available') + ` – ${esc(st.target_error || st.disk.dir)}`
      : st.pause_hard ? T('Vše je pozastaveno: rozpracovaná stahování byla přerušena', 'Everything is paused: downloads in progress were interrupted') : running.length ? T('Fronta je pozastavená: rozpracovaná stahování se dokončí, nová nezačnou', 'The queue is paused: downloads in progress will finish, new ones will not start') : T('Fronta je pozastavená', 'The queue is paused')}</span>${target ? `<button class="btn sm" data-go="settings">${T('Nastavení', 'Settings')}</button>` : ''}
    <button class="btn sm" data-q="resume">${ic('play', 12)} ${T('Pokračovat', 'Resume')}</button></div>`;
  } else {
    html += scheduleBanner(st, 'queue', T('Stahování čeká na časové okno.', 'Downloads are waiting for the time window.'));
  }
  if (!App.subFilter) html += `<div class="stats">
   <div class="card stat"><div class="k">${ic('download', 14)} ${T('Probíhá', 'Running')}</div><div class="v">${s.running} <small>/ ${s.concurrency}</small></div><div class="s">${T('souběžná stahování', 'parallel downloads')}</div></div>
   <div class="card stat"><div class="k">${ic('list', 14)} ${T('Ve frontě', 'Queued')}</div><div class="v">${s.waiting}</div><div class="s">${s.size_est ? '~ ' + fmtBytes(s.size_est) + ' · ' : ''}${s.paused} ${T('pozastaveno', 'paused')}</div></div>
   <div class="card stat"><div class="k">${ic('bolt', 14)} ${T('Rychlost', 'Speed')}</div><div class="v">${s.speed ? fmtBytes(s.speed).replace(/ (\w+)$/, ' <small>$1/s</small>') : '0 <small>B/s</small>'}</div><div class="s">${s.rate_limit ? T('limit', 'limit') + ' ' + s.rate_limit + ' MB/s' : T('bez limitu', 'no limit')}</div></div>
   <div class="card stat"><div class="k">${ic('check', 14)} ${T('Dnes staženo', 'Today')}</div><div class="v">${s.today.done}</div><div class="s">${s.today.failed} ${T(s.today.failed === 1 ? 'chyba' : 'chyb', 'failed')} · ${fmtBytes(s.today.bytes)}</div></div></div>`;
  for (const j of confirm) {
    const big = j.kind !== 'video';
    html += `<div class="card confirm">${thumbHtml(j, 96, 54, { cls: big ? 'stack' : '' })}<div class="grow"><div class="b6 ell">${esc(j.title || j.url)}</div>
    <div class="fs12 t2" style="margin-top:3px">${big ? T(`Obsahuje ${j.count} videí. Stáhnout všechna?`, `Contains ${j.count} videos. Download all?`) : T('Stáhnout toto video?', 'Download this video?')}${j.height ? ' · ' + T('první v', 'first in') + ' ' + j.height + 'p' : ''}</div></div>
    <button class="btn primary" data-a="confirm" data-id="${j.id}">${ic('download', 14)} ${T('Stáhnout', 'Download')}</button><button class="btn" data-a="reject" data-id="${j.id}">${T('Zrušit', 'Cancel')}</button></div>`;
  }
  html += `<div class="sec"><h2>${T('Právě se stahuje', 'Downloading now')}</h2><span class="grow"></span>
   ${st.queue_paused ? `<button class="btn sm" data-q="resume">${ic('play', 13)} ${T('Pokračovat', 'Resume queue')}</button>` : `<button class="btn sm" data-q="pause" title="${T('Nezačne další stahování z fronty, rozpracovaná se dokončí (včetně ffmpeg a přesunu).', 'No new downloads start; those in progress finish (including ffmpeg and the move).')}">${ic('pause', 13)} ${T('Pozastavit frontu', 'Pause queue')}</button>`}
   ${!st.pause_hard && running.length ? `<button class="btn sm" data-q="pause_all" title="${T('Přeruší i rozpracovaná stahování. Stahování z internetu po obnovení naváže, zpracování ffmpeg začne znovu od začátku.', 'Interrupts downloads in progress too. Downloading resumes, ffmpeg processing restarts from the beginning.')}">${ic('pause', 13)} ${T('Pozastavit vše', 'Pause all')}</button>` : ''}</div>`;
  html += running.length ? `<div class="col gap10">${running.map(runHtml).join('')}</div>`
    : `<div class="card empty" style="padding:22px">${T('Nic se právě nestahuje.', 'Nothing is downloading right now.')}</div>`;
  html += `<div class="sec"><h2>${T('Čeká ve frontě', 'Waiting')}</h2><span class="chip"><b>${f ? waiting.length + ' / ' + waitingAll.length : waiting.length}</b></span><span class="grow"></span><button class="btn sm ${thumbsOn() ? '' : 'ghost'}" id="qth" title="${T('Zobrazit nebo skrýt miniatury ve frontě', 'Show or hide thumbnails in the queue')}">${ic('film', 13)} ${T('Miniatury', 'Thumbnails')}: ${thumbsOn() ? T('zap', 'on') : T('vyp', 'off')}</button>${waitingAll.length > 1 || f ? `<div class="inwrap" style="height:30px;width:240px">${ic('search', 14)}<input id="qf" placeholder="${T('Filtrovat podle názvu…', 'Filter by name…')}" value="${esc(App.qf || '')}" autocomplete="off">${App.qf ? `<button class="ibtn" id="qfx" type="button" title="${T('Smazat filtr (Esc)', 'Clear filter (Esc)')}" style="width:22px;height:22px">${ic('x', 13)}</button>` : ''}</div>` : ''}<span class="t2 fs12 row gap6">${ic('grip', 14)} ${T('Přetažením změníte pořadí', 'Drag to reorder')}</span></div>`;
  if (f && !waiting.length && waitingAll.length) {
    html += `<div class="card empty" style="padding:22px">${T('Filtru neodpovídá žádná čekající položka.', 'No waiting item matches the filter.')}</div>`;
  } else if (!waiting.length && !running.length && !confirm.length) {
    html += App.subFilter
      ? `<div class="card empty">${ic('rss', 32)}<h3>${T('Fronta odběru je prázdná', 'This subscription has nothing queued')}</h3><p>${T('Nová videa se zařadí sama při příští kontrole. Můžete ji spustit tlačítkem nahoře.', 'New videos are queued automatically at the next check. You can start one with the button above.')}</p></div>`
      : `<div class="card empty">${ic('download', 32)}<h3>${T('Fronta je prázdná', 'The queue is empty')}</h3><p>${T('Vložte odkaz na video, playlist nebo kanál do pole nahoře, nebo ho pošlete Telegram botovi.', 'Paste a link to a video, playlist or channel above, or send it to the Telegram bot.')}</p></div>`;
  } else if (waiting.length) {
    qNormalize(q);
    let rows = '', n = 0;
    const shown = [];   // co obsahuje „Vybrat zobrazené“: rozbalený playlist = jeho zobrazené položky, sbalený = celý playlist
    for (const j of waiting) {
      rows += rowHtml(j, ++n);
      if (j.kind !== 'video' && (App.expanded.has(j.id) || f)) {
        const kids = kidsOf(j).filter(c => !f || hit(j) || hit(c));
        shown.push(...kids.map(c => c.id));
        kids.slice(0, 200).forEach((c, i) => { rows += rowHtml(c, `${n}.${i + 1}`, true); });
        if (kids.length > 200) rows += `<div class="qr child"><span></span><span></span><span></span><span></span><span class="fs12 t2">+ ${kids.length - 200}</span></div>`;
      } else shown.push(j.id);
    }
    App.qshown = shown;
    const cnt = qCount(q);
    const bulk = `<div class="row gap8 wrap" style="padding:10px 16px;border-bottom:1px solid var(--border)"><button class="btn sm" id="qsa" title="${T('Vybere zobrazená videa. Playlist se vybere celý jen tehdy, když jsou vybraná všechna jeho videa.', 'Selects the displayed videos. A playlist is selected as a whole only when all its videos are selected.')}">${T('Vybrat zobrazené', 'Select shown')}</button>
      ${App.qsel.size ? `<button class="btn sm" id="qsn">${T('Zrušit výběr', 'Clear selection')}</button><span class="grow"></span><b class="fs12">${T('Vybráno', 'Selected')}: ${cnt}</b><button class="btn sm danger" id="qdel">${ic('trash', 13)} ${T('Odebrat vybrané', 'Remove selected')} (${cnt})</button>` : ''}</div>`;
    html += `<div class="card qlist" id="qlist">${bulk}${rows}</div>`;
  }
  const wasFocused = document.activeElement && document.activeElement.id === 'qf', caret = wasFocused ? document.activeElement.selectionStart : 0;
  morphHtml(box, html);
  box.classList.toggle('nothumb', !thumbsOn());
  $$('.qsel', box).forEach(cb => {   // playlist s částí vybraných videí = „neurčitý“ stav
    const j = q.find(x => x.id === +cb.dataset.id);
    if (j && j.kind !== 'video' && !cb.checked) cb.indeterminate = q.some(c => c.parent_id === j.id && App.qsel.has(c.id));
  });
  const qsa = $('#qsa', box), qsn = $('#qsn', box), qdel = $('#qdel', box);
  if (qsa) qsa.onclick = () => { qSelectShown(q); renderQueueDyn(); };
  if (qsn) qsn.onclick = () => { App.qsel.clear(); renderQueueDyn(); };
  if (qdel) qdel.onclick = () => qRemoveSelected(q);
  const qth = $('#qth', box); if (qth) qth.onclick = () => { setThumbs(!thumbsOn()); renderQueueDyn(); };
  const qf = $('#qf', box);
  if (qf) {
    qf.oninput = e => { App.qf = e.target.value; renderQueueDyn(); };
    const clearQf = () => { App.qf = ''; renderQueueDyn(); const n = $('#qf'); if (n) n.focus(); };
    qf.onkeydown = e => { if (e.key === 'Escape' && App.qf) { e.preventDefault(); clearQf(); } };
    const x = $('#qfx', box); if (x) x.onclick = clearQf;
    if (wasFocused) { qf.focus(); qf.setSelectionRange(caret, caret); }
  }
}

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-sa],[data-a],[data-q],[data-go],[data-sov]'); if (!b || !$('#main').contains(b)) return;
  if (b.dataset.sov) return schOverride(b.dataset.sov);
  if (b.dataset.sa) return subAction(b);
  if (b.dataset.go) return go(b.dataset.go);
  if (b.dataset.q) return act(() => api('/api/queue/' + b.dataset.q, { method: 'POST' }));
  const id = +b.dataset.id, a = b.dataset.a;
  if (a === 'expand') { App.expanded.has(id) ? App.expanded.delete(id) : App.expanded.add(id); return renderQueueDyn(); }
  if (a === 'cancel') {
    const j = App.st && App.st.queue.find(x => x.id === id);
    if (j && j.kind !== 'video' && !confirm(T('Odstranit celý playlist z fronty?', 'Remove the whole playlist from the queue?'))) return;
  }
  if (['pause', 'resume', 'cancel', 'confirm', 'reject'].includes(a)) return act(() => api(`/api/jobs/${id}/${a}`, { method: 'POST' }));
});

/* přetahování (změna pořadí) */
document.addEventListener('dragstart', e => { const r = e.target.closest && e.target.closest('.qr[draggable]'); if (!r) return; App.drag = +r.dataset.row; r.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', r.dataset.row); });
document.addEventListener('dragover', e => { if (!App.drag) return; const r = e.target.closest('.qr[draggable]'); if (!r) return; e.preventDefault(); $$('.drop-before').forEach(x => x.classList.remove('drop-before')); r.classList.add('drop-before'); });
document.addEventListener('dragend', () => { $$('.drop-before,.dragging').forEach(x => x.classList.remove('drop-before', 'dragging')); App.drag = null; renderQueueDyn(); });
document.addEventListener('drop', async e => {
  if (!App.drag) return; e.preventDefault(); const r = e.target.closest('.qr[draggable]'); const id = App.drag; App.drag = null;
  if (r && +r.dataset.row !== id) await act(() => api(`/api/jobs/${id}/move`, { method: 'POST', body: { before_id: +r.dataset.row } }));
  renderQueueDyn();
});

/* ------------------------------------------------------------ odběry */
const subList = () => (App.st && App.st.subs) || [];
const subById = id => subList().find(s => s.id === id);
const subKind = s => s.kind === 'playlist' ? 'Playlist' : s.kind === 'page' ? T('Stránka', 'Page') : T('Kanál', 'Channel');
const sinceTxt = s => s.since ? T('od ', 'since ') + new Date(s.since + 'T00:00:00').toLocaleDateString(LANG === 'cs' ? 'cs-CZ' : 'en-GB') : T('všechna videa', 'all videos');
function subThumb(s, size = 48) {
  const img = s.thumb_url ? `<img src="${esc(s.thumb_url)}" referrerpolicy="no-referrer" loading="lazy" alt="" onerror="this.remove()">` : '';
  return `<div class="sth" style="width:${size}px;height:${size}px">${ic('rss', Math.round(size / 2.4))}${img}</div>`;
}
function subStatus(s) {
  if (s.pending) return `<span class="badge b-warn">${T('Čeká na potvrzení', 'Needs confirmation')}</span>`;
  if (s.last_error) return `<span class="badge b-err" title="${esc(s.last_error)}">${ic('alert', 11)} ${T('Chyba kontroly', 'Check failed')}</span>`;
  if (!s.enabled) return `<span class="badge b-n">${ic('pause', 11)} ${T('Pozastaveno', 'Paused')}</span>`;
  if (!s.last_check) return `<span class="badge b-n"><span class="spin" style="width:10px;height:10px"></span> ${T('Kontroluje se…', 'Checking…')}</span>`;
  return `<span class="badge b-ok">${ic('check', 11)} ${T('Aktivní', 'Active')}</span>`;
}
function subPending(s) {
  return `<div class="banner">${ic('alert', 18)}<span class="grow">${T(`Při první kontrole bylo nalezeno ${s.pending} videí. Stáhnout všechna?`, `The first check found ${s.pending} videos. Download them all?`)}</span>
    <button class="btn sm primary" data-sa="confirm" data-id="${s.id}">${ic('download', 12)} ${T('Stáhnout', 'Download')}</button><button class="btn sm" data-sa="reject" data-id="${s.id}">${T('Zahodit', 'Discard')}</button></div>`;
}
function subCounts(s) {
  return `<span><b>${s.queued + s.running}</b> ${T('ve frontě', 'queued')}</span><span><b>${s.done}</b> ${T('staženo', 'downloaded')}</span><span>${fmtBytes(s.bytes)}</span>${s.failed ? `<span class="err">${s.failed} ${T('chyb', 'failed')}</span>` : ''}`;
}
function subCard(s) {
  return `<div class="card scard" data-go="sub/${s.id}">
   <div class="row gap12">${subThumb(s, 52)}<div class="grow" style="min-width:0"><div class="b6 fs15 ell" title="${esc(s.title || s.url)}">${esc(s.title || s.url)}</div><div class="fs12 t2 ell">${subKind(s)} · ${sinceTxt(s)}</div></div>${subStatus(s)}</div>
   <div class="fs12 t2 ell row gap6" title="${esc(s.folder)}">${ic('folder', 13)}<span class="ell">${esc(s.folder)}</span></div>
   <div class="row gap16 fs12 t2 wrap">${subCounts(s)}<span class="grow"></span><span>${T('kontrola', 'checked')}: ${s.last_check ? fmtDate(s.last_check) : '—'}</span></div>
   ${s.pending ? subPending(s) : ''}${s.last_error ? `<div class="mm err" style="white-space:normal">${ic('alert', 12)} ${esc(s.last_error)}</div>` : ''}</div>`;
}
function renderSubs() {
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Odběry', 'Subscriptions')}</h1><div class="t2" style="margin-top:3px">${T('Nová videa z kanálů a playlistů se stahují automaticky', 'New videos from channels and playlists are downloaded automatically')}</div></div><div class="grow"></div>
   <button class="btn primary lg" data-go="subs/new">${ic('plus', 15)} ${T('Přidat odběr', 'Add subscription')}</button></div><div id="subsdyn" class="col gap16"></div>`;
  renderSubsDyn();
}
function renderSubsDyn() {
  const box = $('#subsdyn'); if (!box) return;
  if (!App.st) { box.innerHTML = '<div class="empty"><div class="spin" style="margin:auto"></div></div>'; return; }
  const list = subList();
  const sbn = scheduleBanner(App.st, 'subscriptions', T('Kontroly odběrů čekají na časové okno.', 'Subscription checks are waiting for the time window.'));
  box.innerHTML = sbn + (list.length ? `<div class="subgrid">${list.map(subCard).join('')}</div>`
    : `<div class="card empty">${ic('rss', 32)}<h3>${T('Zatím žádné odběry', 'No subscriptions yet')}</h3><p>${T('Odběr sleduje kanál nebo playlist a sám stáhne nová videa do vybrané složky. Můžete zvolit, od kterého data se mají stahovat.', 'A subscription watches a channel or playlist and downloads new videos into a folder you choose, starting from a date you choose.')}</p>
      <div style="margin-top:14px"><button class="btn primary" data-go="subs/new">${ic('plus', 14)} ${T('Přidat první odběr', 'Add your first subscription')}</button></div></div>`);
}

function sinceControl(prefix, cur, withPresets) {
  const opts = withPresets
    ? [['now', T('Jen nové od teď', 'Only new from now')], ['month', T('Od minulého měsíce', 'Since last month')], ['date', T('Od data…', 'Since date…')], ['all', T('Všechna videa', 'All videos')]]
    : [['date', T('Od data…', 'Since date…')], ['all', T('Všechna videa', 'All videos')]];
  return `<div class="col gap6"><span class="seg" id="${prefix}seg">${opts.map(([v, l]) => `<button type="button" data-v="${v}" class="${cur.mode === v ? 'on' : ''}">${l}</button>`).join('')}</span>
    <input class="input" type="date" id="${prefix}date" value="${esc(cur.date || '')}" style="width:190px;${cur.mode === 'date' ? '' : 'display:none'}"></div>`;
}
function bindSince(prefix, cur) {
  $$(`#${prefix}seg button`).forEach(b => b.onclick = () => { cur.mode = b.dataset.v; $$(`#${prefix}seg button`).forEach(x => x.classList.toggle('on', x === b)); $(`#${prefix}date`).style.display = cur.mode === 'date' ? '' : 'none'; });
  $(`#${prefix}date`).onchange = e => { cur.date = e.target.value; };
}
function sinceValue(cur) {
  if (cur.mode === 'date') { if (!cur.date) throw new Error(T('Vyberte datum, od kterého se mají videa stahovat.', 'Pick the date to download from.')); return cur.date; }
  return cur.mode;
}
const CHECK_OPTS = () => [[3, T('3 hodiny', '3 hours')], [6, T('6 hodin', '6 hours')], [12, T('12 hodin', '12 hours')], [24, T('1 den', '1 day')], [72, T('3 dny', '3 days')], [168, T('1 týden', '1 week')], [720, T('1 měsíc', '1 month')]];
function intervalControl(prefix, cur) {
  const g = (App.settings && App.settings.values.subscription_check_hours) || 0;
  return `<div class="col gap6"><span class="fs12 b6">${T('Kontrola nového obsahu', 'Check for new content')}</span>
   <select class="input" id="${prefix}chk" style="max-width:260px"><option value="">${T('Výchozí', 'Default')} (${g ? T('každých', 'every') + ' ' + g + ' h' : T('vypnuto', 'off')})</option>${CHECK_OPTS().map(([v, l]) => `<option value="${v}" ${+cur === v ? 'selected' : ''}>${T('každé', 'every')} ${l}</option>`).join('')}</select>
   <span class="fs12 muted">${T('Jak často se na zdroji hledají nová videa. Výchozí hodnota je v Nastavení › Stahování.', 'How often the source is checked for new videos. The default is in Settings › Downloads.')}</span></div>`;
}
function tabsControl(prefix, tabs) {
  const all = [['videos', T('Videa', 'Videos')], ['shorts', 'Shorts'], ['streams', T('Živé přenosy', 'Live streams')]];
  return `<div class="row gap8 wrap" id="${prefix}tabs">${all.map(([v, l]) => `<button type="button" class="chip ${tabs.includes(v) ? 'on' : ''}" data-v="${v}">${l}</button>`).join('')}</div>`;
}
function bindTabs(prefix, tabs) { $$(`#${prefix}tabs .chip`).forEach(b => b.onclick = () => { const v = b.dataset.v, i = tabs.indexOf(v); if (i >= 0) tabs.splice(i, 1); else tabs.push(v); b.classList.toggle('on', i < 0); }); }
function tabsValue(tabs) {
  const glob = (App.settings.values.channel_tabs || ['videos']).slice().sort().join();
  return tabs.slice().sort().join() === glob ? null : tabs.slice();
}

function renderSubNew() {
  const since = { mode: 'now', date: '' }, tabs = (App.settings.values.channel_tabs || ['videos']).slice();
  $('#main').innerHTML = `<div class="row gap10"><button class="btn ghost sm" data-go="subs">${ic('right', 12).replace('M9 6l6 6-6 6', 'M15 6l-6 6 6 6')} ${T('Odběry', 'Subscriptions')}</button></div>
   <div><h1>${T('Přidat odběr', 'Add subscription')}</h1></div>
   <div class="card col gap16" style="padding:20px;max-width:720px">
    <div class="col gap6"><span class="fs12 b6">${T('Zdroj', 'Source')}</span>
     <span class="seg" id="samode" style="align-self:flex-start"><button data-v="feed" class="on">${T('Kanál nebo playlist', 'Channel or playlist')}</button><button data-v="page">${T('Stránka s videi', 'Page with videos')}</button></span>
     <span class="fs12 muted" id="samodehint">${T('YouTube a další weby, které yt-dlp umí vypsat jako kanál nebo playlist.', 'YouTube and other sites yt-dlp can list as a channel or playlist.')}</span></div>
    <label class="col gap6"><span class="fs12 b6" id="saulab">${T('URL kanálu nebo playlistu', 'Channel or playlist URL')}</span><input class="input" id="sau" placeholder="https://www.youtube.com/@kanal" autocomplete="off"></label>
    <div id="sapage" class="col gap10" style="display:none">
     <div class="row gap8"><button class="btn" id="sapv">${ic('search', 14)} ${T('Zkontrolovat stránku', 'Check the page')}</button><span class="fs12 muted">${T('Najde na stránce seznam videí a jejich data.', 'Finds the list of videos and their dates on the page.')}</span></div>
     <div id="sapvbox"></div></div>
    <label class="col gap6"><span class="fs12 b6">${T('Název (nepovinné)', 'Name (optional)')}</span><input class="input" id="sat" placeholder="${T('Zobrazí se v menu. Prázdné = název zdroje', 'Shown in the menu. Empty = source name')}" autocomplete="off"></label>
    <div class="col gap6"><span class="fs12 b6">${T('Složka pro videa tohoto odběru', 'Folder for this subscription')}</span>
     <div class="row gap8"><input class="input grow mono fs12" id="saf" placeholder="${T('Nevyplněno = cílová složka / název kanálu', 'Empty = download folder / channel name')}"><button class="btn" id="sabr">${ic('folder', 14)} ${T('Vybrat…', 'Browse…')}</button></div>
     <span class="fs12 muted">${T('Při uložení se ověří, že do složky jde zapisovat.', 'Write access is checked when you save.')}</span></div>
    <div class="col gap6"><span class="fs12 b6">${T('Stahovat videa', 'Download videos')}</span>${sinceControl('sa', since, true)}
     <span class="fs12 muted">${T('Starší videa se nestáhnou. Nová videa po tomto datu ano, i v budoucnu.', 'Older videos are not downloaded. New ones after this date are, also in the future.')}</span></div>
    ${intervalControl('sa', null)}
    <div class="col gap6" id="satabs"><span class="fs12 b6">${T('Z kanálu YouTube stahovat', 'From a YouTube channel download')}</span>${tabsControl('sa', tabs)}</div>
    <div class="banner" id="saerr" style="display:none"></div>
    <div class="row gap8"><button class="btn primary lg" id="saok">${ic('plus', 14)} ${T('Přidat odběr', 'Add subscription')}</button><button class="btn lg" data-go="subs">${T('Zrušit', 'Cancel')}</button></div></div>`;
  bindSince('sa', since); bindTabs('sa', tabs);
  $('#sabr').onclick = () => openDirPicker($('#saf').value || App.settings.values.download_dir, p => { $('#saf').value = p; });
  let mode = 'feed', det = null;
  $$('#samode button').forEach(b => b.onclick = () => {
    mode = b.dataset.v; det = null; $('#sapvbox').innerHTML = '';
    $$('#samode button').forEach(x => x.classList.toggle('on', x === b));
    $('#sapage').style.display = mode === 'page' ? 'flex' : 'none'; $('#satabs').style.display = mode === 'page' ? 'none' : '';
    $('#saulab').textContent = mode === 'page' ? T('URL stránky se seznamem videí', 'URL of the page listing the videos') : T('URL kanálu nebo playlistu', 'Channel or playlist URL');
    $('#sau').placeholder = mode === 'page' ? 'https://www.example.com/tv-show' : 'https://www.youtube.com/@kanal';
    $('#samodehint').textContent = mode === 'page' ? T('Web bez kanálu: seznam dílů s podstránkami, každý díl má vlastní stránku s videem.', 'A site without a channel: a list of episodes with sub-pages, each with its own video page.') : T('YouTube a další weby, které yt-dlp umí vypsat jako kanál nebo playlist.', 'YouTube and other sites yt-dlp can list as a channel or playlist.');
  });
  $('#sapv').onclick = async () => {
    const url = $('#sau').value.trim(), box = $('#sapvbox'); if (!url) return toast(T('Zadejte URL stránky.', 'Enter the page URL.'));
    box.innerHTML = `<div class="row gap8 t2 fs12"><span class="spin" style="width:13px;height:13px"></span> ${T('Načítám stránku…', 'Loading the page…')}</div>`;
    try {
      det = await api('/api/subscriptions/preview-page', { method: 'POST', body: { url } });
      if (!$('#sat').value.trim() && det.title) $('#sat').placeholder = det.title;
      box.innerHTML = `<div class="card" style="padding:12px 14px;background:var(--surface2)"><div class="fs12 b6" style="margin-bottom:6px">${T('Nalezeno', 'Found')}: ${det.items.length}${det.items.length >= 12 ? '+' : ''} ${T('videí (první stránka)', 'videos (first page)')} · ${det.page_param ? T('stránkování', 'paging') + ' ' + esc(det.page_param) : T('bez stránkování', 'no paging')}</div>
        ${det.items.map(i => `<div class="row gap8 fs12" style="justify-content:space-between"><span class="ell">${esc(i.title || i.url)}</span><span class="t2" style="white-space:nowrap">${i.date ? esc(i.date) : T('bez data', 'no date')}</span></div>`).join('')}</div>
        <details class="fs12"><summary class="t2" style="cursor:pointer">${T('Upřesnit (vzor odkazů, stránkování)', 'Advanced (link pattern, paging)')}</summary><div class="col gap8" style="margin-top:8px">
         <label class="col gap4"><span class="b6">${T('Vzor odkazů na videa (regulární výraz)', 'Video link pattern (regular expression)')}</span><input class="input mono fs12" id="sare" value="${esc(det.item_regex)}"></label>
         <label class="col gap4"><span class="b6">${T('Adresa další stránky ({n} = číslo)', 'Next-page URL ({n} = number)')}</span><input class="input mono fs12" id="sapt" value="${esc(det.page_template || '')}"></label></div></details>`;
    } catch (e) { if (e.message !== 'auth') box.innerHTML = `<div class="banner">${ic('alert', 18)}<span class="grow">${esc(e.message)}</span></div>`; }
  };
  const submit = async () => {
    const err = $('#saerr'); err.style.display = 'none';
    const btn = $('#saok'); const url = $('#sau').value.trim();
    try {
      if (!url) throw new Error(T('Zadejte URL kanálu nebo playlistu.', 'Enter a channel or playlist URL.'));
      const body = { url, folder: $('#saf').value.trim(), since: sinceValue(since), tabs: tabsValue(tabs), title: $('#sat').value.trim(), check_hours: $('#sachk').value };
      if (mode === 'page') { body.kind = 'page'; if (det && $('#sare')) { body.item_regex = $('#sare').value.trim(); body.page_template = $('#sapt').value.trim(); } }
      btn.disabled = true; btn.innerHTML = `<span class="spin" style="width:13px;height:13px"></span> ${T('Kontroluji URL…', 'Checking URL…')}`;
      const r = await api('/api/subscriptions', { method: 'POST', body });
      toast(T('Odběr přidán', 'Subscription added')); if (App.st && App.st.subs && !subById(r.id)) App.st.subs.push(r); go(`sub/${r.id}`);
    } catch (e) {
      if (e.message === 'auth') return;
      const hint = mode === 'feed' && e.message.includes('Stránka s videi');
      err.innerHTML = `${ic('alert', 18)}<span class="grow">${esc(e.message)}</span>${hint ? `<button class="btn sm" id="saswitch">${T('Přepnout na Stránku s videi', 'Switch to Page with videos')}</button>` : ''}`; err.style.display = 'flex';
      if (hint) $('#saswitch').onclick = () => { err.style.display = 'none'; $('#samode [data-v="page"]').click(); $('#sapv').click(); };
      btn.disabled = false; btn.innerHTML = `${ic('plus', 14)} ${T('Přidat odběr', 'Add subscription')}`;
    }
  };
  $('#saok').onclick = submit;
  $('#sau').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  $('#sau').focus();
}

function renderSub() {
  const sid = +App.args[0], tab = ['queue', 'history', 'settings'].includes(App.args[1]) ? App.args[1] : 'queue';
  App.subFilter = tab === 'queue' ? sid : null;
  $('#main').innerHTML = `<div class="row gap10"><button class="btn ghost sm" data-go="subs">${ic('right', 12).replace('M9 6l6 6-6 6', 'M15 6l-6 6 6 6')} ${T('Odběry', 'Subscriptions')}</button></div>
   <div id="subhead"></div>
   <span class="seg" id="subtabs" style="align-self:flex-start">${[['queue', T('Fronta', 'Queue')], ['history', T('Historie', 'History')], ['settings', T('Nastavení', 'Settings')]]
      .map(([v, l]) => `<button class="${tab === v ? 'on' : ''}" data-go="sub/${sid}/${v}">${l}</button>`).join('')}</span>
   <div id="subbody" class="col gap16"></div>`;
  updateSubHead();
  if (!App.st) { $('#subbody').innerHTML = '<div class="empty"><div class="spin" style="margin:auto"></div></div>'; return; }
  const s = subById(sid);
  App.subReady = !!s;   // dokud odběr není ve stavu (právě založený), zkusí se znovu při další aktualizaci
  if (!s) { $('#subtabs').style.display = 'none'; return; }
  if (tab === 'queue') { $('#subbody').innerHTML = '<div id="qdyn" class="col gap16"></div>'; renderQueueDyn(); }
  else if (tab === 'history') renderHistory($('#subbody'), sid);
  else renderSubSettings(s);
}
function updateSubHead() {
  const el = $('#subhead'); if (!el) return;
  const sid = +App.args[0];
  if (!App.st) { el.innerHTML = ''; return; }
  const s = subById(sid);
  if (!s) { el.innerHTML = `<div class="card empty"><h3>${T('Odběr neexistuje', 'Subscription not found')}</h3><button class="btn" data-go="subs">${T('Zpět na odběry', 'Back to subscriptions')}</button></div>`; return; }
  el.innerHTML = `<div class="row gap16 wrap">${subThumb(s, 56)}<div class="grow" style="min-width:0"><div class="row gap10"><h1 class="ell">${esc(s.title || s.url)}</h1>${subStatus(s)}</div>
    <div class="t2 fs12 row gap12 wrap" style="margin-top:4px"><span>${subKind(s)} · ${sinceTxt(s)}</span><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" class="row gap4">${ic('link', 12)} ${T('Otevřít zdroj', 'Open source')}</a>
     <span class="row gap4" title="${esc(s.folder)}">${ic('folder', 12)} <span class="ell" style="max-width:340px">${esc(s.folder)}</span></span></div>
    <div class="row gap16 fs12 t2 wrap" style="margin-top:6px">${subCounts(s)}<span>${T('kontrola', 'checked')}: ${s.last_check ? fmtDate(s.last_check) : '—'}</span></div></div>
    <div class="row gap10"><button class="btn" data-sa="check" data-id="${s.id}">${ic('refresh', 13)} ${T('Zkontrolovat teď', 'Check now')}</button>
     <label class="row gap8 fs12 t2" title="${T('Zapnout / pozastavit odběr', 'Enable / pause the subscription')}">${s.enabled ? T('Zapnuto', 'On') : T('Pozastaveno', 'Paused')}<button class="toggle ${s.enabled ? 'on' : ''}" data-sa="toggle" data-id="${s.id}" aria-label="enabled"></button></label></div></div>
   ${s.pending ? subPending(s) : ''}${s.last_error ? `<div class="banner">${ic('alert', 18)}<span class="grow">${T('Poslední kontrola selhala', 'The last check failed')}: ${esc(s.last_error)}</span></div>` : ''}`;
}

function renderSubSettings(s) {
  const since = { mode: s.since ? 'date' : 'all', date: s.since || '' };
  const tabs = (s.tabs || App.settings.values.channel_tabs || ['videos']).slice();
  $('#subbody').innerHTML = `<div class="card col gap16" style="padding:20px;max-width:720px">
    <label class="col gap6"><span class="fs12 b6">${T('Název', 'Name')}</span><input class="input" id="ssn" value="${esc(s.title || '')}"></label>
    <div class="col gap6"><span class="fs12 b6">URL</span><div class="mono fs12 t2" style="word-break:break-all">${esc(s.url)}</div></div>
    <div class="col gap6"><span class="fs12 b6">${T('Složka pro videa', 'Folder for videos')}</span><div class="row gap8"><input class="input grow mono fs12" id="ssf" value="${esc(s.folder)}"><button class="btn" id="ssbr">${ic('folder', 14)} ${T('Vybrat…', 'Browse…')}</button></div>
     <span class="fs12 muted">${T('Platí i pro videa, která už čekají ve frontě. Už stažené soubory se nepřesouvají.', 'Also applies to videos already waiting in the queue. Files already downloaded are not moved.')}</span></div>
    <div class="col gap6"><span class="fs12 b6">${T('Stahovat videa', 'Download videos')}</span>${sinceControl('ss', since, false)}</div>
    ${intervalControl('ss', s.check_hours)}
    ${s.kind === 'channel' ? `<div class="col gap6"><span class="fs12 b6">${T('Z kanálu YouTube stahovat', 'From a YouTube channel download')}</span>${tabsControl('ss', tabs)}</div>` : ''}
    <div class="row gap8"><button class="btn primary" id="ssok">${T('Uložit změny', 'Save changes')}</button></div></div>
   <div class="card col gap10" style="padding:20px;max-width:720px"><h3>${T('Smazat odběr', 'Delete subscription')}</h3>
    <p class="t2 fs12">${T('Odběr přestane stahovat nová videa a čekající videa se zruší. Stažené soubory na disku zůstanou.', 'The subscription stops downloading and queued videos are cancelled. Downloaded files stay on disk.')}</p>
    <div><button class="btn danger" id="ssdel">${ic('trash', 13)} ${T('Smazat odběr…', 'Delete subscription…')}</button></div></div>`;
  bindSince('ss', since); if (s.kind === 'channel') bindTabs('ss', tabs);
  $('#ssbr').onclick = () => openDirPicker($('#ssf').value, p => { $('#ssf').value = p; });
  $('#ssok').onclick = async () => {
    let body;
    try { body = { title: $('#ssn').value.trim(), folder: $('#ssf').value.trim(), since: sinceValue(since), check_hours: $('#sschk').value }; } catch (e) { return toast(e.message, true); }
    if (s.kind === 'channel') body.tabs = tabsValue(tabs);
    if (since.mode === 'all') body.since = 'all';
    const r = await act(() => api(`/api/subscriptions/${s.id}`, { method: 'PUT', body }), T('Uloženo', 'Saved'));
    if (r) { const cur = subById(s.id); if (cur) Object.assign(cur, r); updateSubHead(); }
  };
  $('#ssdel').onclick = () => openDeleteSub(s);
}
function openDeleteSub(s) {
  const m = modal(`<div class="mh">${ic('trash', 18)}<h2>${T('Smazat odběr', 'Delete subscription')} „${esc(s.title || s.url)}“</h2></div><div class="mb col gap10">
    <label class="row gap8" style="align-items:flex-start"><input type="radio" name="kh" value="1" checked style="margin-top:3px"><span><b>${T('Zachovat záznamy v historii', 'Keep records in history')}</b><br><span class="fs12 t2">${T('Hotová stahování zůstanou v celkové historii, jen bez vazby na odběr.', 'Finished downloads stay in the overall history, just without a link to the subscription.')}</span></span></label>
    <label class="row gap8" style="align-items:flex-start"><input type="radio" name="kh" value="0" style="margin-top:3px"><span><b>${T('Odstranit i záznamy z historie', 'Also delete the history records')}</b><br><span class="fs12 t2">${T('Soubory na disku zůstanou, smažou se jen záznamy o nich.', 'Files stay on disk, only their records are deleted.')}</span></span></label></div>
   <div class="mf"><button class="btn" id="sdc">${T('Zrušit', 'Cancel')}</button><button class="btn danger" id="sdok">${T('Smazat odběr', 'Delete subscription')}</button></div>`);
  $('#sdc').onclick = m.close;
  $('#sdok').onclick = async () => {
    const keep = $('input[name=kh]:checked', m.el).value === '1';
    const r = await act(() => api(`/api/subscriptions/${s.id}?keep_history=${keep}`, { method: 'DELETE' }), T('Odběr smazán', 'Subscription deleted'));
    if (r) { m.close(); go('subs'); }
  };
}
async function subAction(b) {
  const id = +b.dataset.id, a = b.dataset.sa;
  if (a === 'confirm') return act(() => api(`/api/subscriptions/${id}/confirm`, { method: 'POST' }), T('Videa zařazena do fronty', 'Videos added to the queue'));
  if (a === 'reject') {
    if (!confirm(T('Zahodit nalezená videa? Už se znovu nenabídnou.', 'Discard the videos found? They will not be offered again.'))) return;
    return act(() => api(`/api/subscriptions/${id}/reject`, { method: 'POST' }), T('Videa zahozena', 'Videos discarded'));
  }
  if (a === 'check') return act(() => api(`/api/subscriptions/${id}/check`, { method: 'POST' }), T('Kontrola spuštěna', 'Check started'));
  if (a === 'toggle') { const s = subById(id); if (s) { s.enabled = s.enabled ? 0 : 1; updateSubHead(); } return act(() => api(`/api/subscriptions/${id}`, { method: 'PUT', body: { enabled: s ? !!s.enabled : true } })); }
}

/* ------------------------------------------------------------ vytížení procesoru */
const PERF_MODES = () => [['full', T('Plný', 'Full'), T('Plný výkon – bez omezení', 'Full performance – no limits')],
  ['balanced', T('Vyvážený', 'Balanced'), T('Nižší priorita podprocesů, ffmpeg na 2 vlákna', 'Lower subprocess priority, ffmpeg limited to 2 threads')],
  ['eco', T('Šetrný', 'Eco'), T('Nejnižší priorita, 1 vlákno ffmpeg, nejvýše 1 souběžné stahování', 'Lowest priority, 1 ffmpeg thread, at most 1 parallel download')]];
function cpuBox(st) {
  const c = st && st.cpu; if (!c) return '';
  const rt = c.rates || {};
  const pc = c.percent, col = pc == null ? 'var(--muted)' : pc >= 85 ? 'var(--err)' : pc >= 60 ? 'var(--warn)' : 'var(--ok)';
  return `<div class="card" style="padding:12px;background:var(--surface2)" title="${T('Vytížení procesoru touto aplikací (100 % = všechna jádra)', 'CPU load of this app (100% = all cores)')}">
   <div class="row fs12 t2" style="justify-content:space-between"><span class="row gap6">${ic('cpu', 14)} ${T('Procesor', 'CPU')}</span><b style="color:var(--text)">${pc == null ? '—' : Math.round(pc) + ' %'}</b></div>
   <div class="bar" style="margin-top:6px"><i style="width:${pc || 0}%;background:${col}"></i></div>
   ${c.mem ? (() => { const mp = c.mem.total ? c.mem.used / c.mem.total * 100 : 0, mc = mp >= 90 ? 'var(--err)' : mp >= 75 ? 'var(--warn)' : 'var(--ok)'; return `<div class="row fs12 t2" style="justify-content:space-between;margin-top:10px" title="${T('Paměť používaná touto aplikací a jejími procesy z celkové paměti', 'Memory used by this app and its processes out of total memory')}"><span class="row gap6">${ic('hdd', 14)} RAM</span><span><b style="color:var(--text)">${fmtBytes(c.mem.used)}</b> / ${fmtBytes(c.mem.total)}</span></div><div class="bar" style="margin-top:6px"><i style="width:${Math.max(1, mp)}%;background:${mc}"></i></div>`; })() : ''}
   <div class="row fs12 t2" style="justify-content:space-between;margin-top:10px" title="${T('Veškerý provoz sítě kontejneru (internet i místní síť dohromady): přijato (hlavně stahovaná videa) / odesláno (požadavky, Telegram). Zápis na připojený disk NAS sem nepatří.', 'All network traffic of the container (internet and local network combined): received (mostly downloaded videos) / sent (requests, Telegram). Writes to a mounted NAS drive are not included.')}"><span class="row gap6">${ic('globe', 14)} ${T('Síť', 'Net')}</span><span><b style="color:var(--text)">↓ ${fmtRate(rt.net_in)}</b> ↑ ${fmtRate(rt.net_out)}</span></div>
   ${rt.io_w != null ? `<div class="row fs12 t2" style="justify-content:space-between;margin-top:4px" title="${T('Zápis a čtení souborů procesy aplikace (zápis zahrnuje i připojený disk NAS)', 'File writes and reads by the app processes (writes include a mounted NAS drive)')}"><span class="row gap6">${ic('hdd', 14)} Disk</span><span><b style="color:var(--text)">${T('Z', 'W')} ${fmtRate(rt.io_w)}</b> ${T('Č', 'R')} ${fmtRate(rt.io_r)}</span></div>` : ''}
   <span class="seg" style="display:flex;margin-top:10px">${PERF_MODES().map(([v, l, d]) => `<button style="flex:1;padding:4px 0" class="${c.mode === v ? 'on' : ''}" data-perf="${v}" title="${esc(d)}">${l}</button>`).join('')}</span></div>`;
}
const fmtRate = n => n == null ? '—' : n ? fmtBytes(n) + '/s' : '0 B/s';
function lineChart(title, now, series, max, unit) {
  const W = 450, H = 64, n = Math.max(...series.map(x => x.v.length), 2);
  const top = max || Math.max(1, ...series.flatMap(x => x.v)) * 1.1;
  const pts = v => v.map((y, i) => `${(W * (n - v.length + i) / (n - 1)).toFixed(1)},${(H - 2 - Math.min(1, y / top) * (H - 4)).toFixed(1)}`).join(' ');
  const body = series.map(x => x.v.length > 1 ? `<polygon points="0,${H} ${pts(x.v)} ${W},${H}" fill="${x.c}" opacity=".12"/><polyline points="${pts(x.v)}" fill="none" stroke="${x.c}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>` : '').join('');
  return `<div><div class="row gap8 fs12" style="justify-content:space-between"><b>${title}</b><span class="t2">${now}</span></div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%;height:64px;margin-top:6px;background:var(--surface2);border-radius:8px">${body}</svg>
    <div class="row gap10 fs11 muted" style="margin-top:3px">${series.map(x => `<span class="row gap4"><i style="width:8px;height:8px;border-radius:2px;background:${x.c};display:inline-block"></i>${x.l}</span>`).join('')}<span class="grow"></span><span>${unit || ''}</span></div></div>`;
}
async function drawCpuChart() {
  const box = $('#cpuchart'); if (!box) return;
  const r = await api('/api/cpu').catch(() => null); if (!r || !$('#cpuchart')) return;
  const h = r.history.slice(-450), mh = (r.mem_history || []).slice(-450), rh = r.rate_history || {}, tl = k => (rh[k] || []).slice(-450);
  const ac = 'var(--accent)', ok = 'var(--ok)', wn = 'var(--warn)';
  const mem = r.mem, rt = r.rates || {};
  box.innerHTML = h.length ? `<div class="sysgrid">
    ${lineChart(T('Procesor', 'CPU'), r.percent == null ? '—' : Math.round(r.percent) + ' %', [{ v: h, c: ac, l: T('vytížení', 'load') }], 100, '0–100 %')}
    ${lineChart('RAM', mem ? fmtBytes(mem.used) + ' / ' + fmtBytes(mem.total) : '—', [{ v: mh, c: ok, l: T('využití', 'usage') }], 100, '0–100 %')}
    ${lineChart(T('Síť', 'Network'), `↓ ${fmtRate(rt.net_in)} · ↑ ${fmtRate(rt.net_out)}`, [{ v: tl('net_in'), c: ac, l: T('přijato (stahování)', 'received (download)') }, { v: tl('net_out'), c: wn, l: T('odesláno (požadavky, Telegram)', 'sent (requests, Telegram)') }])}
    ${lineChart(T('Disk', 'Disk'), `${T('zápis', 'write')} ${fmtRate(rt.io_w)} · ${T('čtení', 'read')} ${fmtRate(rt.io_r)}`, [{ v: tl('io_w'), c: ac, l: T('zápis souborů', 'file writes') }, { v: tl('io_r'), c: wn, l: T('čtení z disku', 'disk reads') }])}
  </div><div class="t2 fs11" style="margin-top:8px">${T('Posledních', 'Last')} ${Math.round(h.length * r.step / 60)} min</div>`
    : `<div class="t2 fs12" style="padding:8px 0">${T('Měření se právě rozbíhá…', 'Measurement is starting…')}</div>`;
  clearTimeout(App.cpuTmr); App.cpuTmr = setTimeout(drawCpuChart, 4000);
}

/* ------------------------------------------------------------ statistiky */
const STATS = { p: '30d', from: '', to: '', metric: 'n' };
function statsRange() {
  const now = Date.now() / 1000, d = 86400;
  if (STATS.p === 'custom') {
    const a = STATS.from ? new Date(STATS.from + 'T00:00:00').getTime() / 1000 : 0, b = STATS.to ? new Date(STATS.to + 'T00:00:00').getTime() / 1000 + d : 0;
    return [a, b];
  }
  const span = { '24h': d, '7d': 7 * d, '30d': 30 * d, '12m': 365 * d }[STATS.p];
  return [span ? now - span : 0, 0];
}
function renderStats() {
  const periods = [['24h', T('24 hodin', '24 hours')], ['7d', T('7 dní', '7 days')], ['30d', T('30 dní', '30 days')], ['12m', T('12 měsíců', '12 months')], ['all', T('Vše', 'All time')], ['custom', T('Vlastní', 'Custom')]];
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Statistiky', 'Statistics')}</h1><div class="t2" style="margin-top:3px">${T('Počty a objemy stahování. Nezávisí na historii – mazání historie statistiky nemění.', 'Download counts and volumes. Independent of history – clearing history does not change them.')}</div></div><span class="grow"></span>
    <span class="seg" id="stp">${periods.map(([v, l]) => `<button data-v="${v}" class="${STATS.p === v ? 'on' : ''}">${l}</button>`).join('')}</span></div>
    <div class="row gap8 wrap" id="stcustom" style="margin-top:10px;${STATS.p === 'custom' ? '' : 'display:none'}"><span class="t2 fs12">${T('Od', 'From')}</span><input type="date" class="input sm" id="stfrom" value="${STATS.from}" style="width:150px"><span class="t2 fs12">${T('do (včetně)', 'to (inclusive)')}</span><input type="date" class="input sm" id="stto" value="${STATS.to}" style="width:150px"></div>
    <div class="card" style="padding:16px 18px;margin-top:14px"><div class="row gap10"><b>${T('Systém: procesor, paměť, síť a disk', 'System: CPU, memory, network and disk')}</b><span class="grow"></span><span class="t2 fs12" id="cpunow"></span></div><div id="cpuchart"></div></div>
    <div id="stbody" style="margin-top:16px"><div class="empty"><div class="spin" style="margin:auto"></div></div></div>`;
  $$('#stp button').forEach(b => b.onclick = () => { STATS.p = b.dataset.v; $$('#stp button').forEach(x => x.classList.toggle('on', x === b)); $('#stcustom').style.display = STATS.p === 'custom' ? '' : 'none'; loadStats(); });
  $('#stfrom').onchange = e => { STATS.from = e.target.value; loadStats(); };
  $('#stto').onchange = e => { STATS.to = e.target.value; loadStats(); };
  drawCpuChart();
  loadStats();
}
async function loadStats() {
  const [t0, t1] = statsRange();
  const r = await act(() => api(`/api/stats?t0=${t0}&t1=${t1}&tz=${-new Date().getTimezoneOffset()}`)); const box = $('#stbody'); if (!r || !box) return;
  const total = r.done + r.failed, rate = total ? Math.round(r.done / total * 100) : null;
  const days = Math.max(1, ((r.t1 - r.t0) / 86400)), perDay = r.done / days;
  const kpi = (l, v, sub = '') => `<div class="card kpi"><div class="t2 fs12">${l}</div><div class="kv">${v}</div><div class="t2 fs12">${sub || '&nbsp;'}</div></div>`;
  const nf = n => Number(n).toLocaleString(LANG === 'cs' ? 'cs-CZ' : 'en-US');
  const lab = b => r.fmt === '%Y-%m' ? b : r.fmt === '%Y-%m-%d' ? b.slice(5).replace('-', '. ') + '.' : b.slice(11, 13);
  const val = x => x[STATS.metric === 'n' ? 'n' : 'bytes'];
  const mx = Math.max(1, ...r.series.map(val));
  const every = Math.ceil(r.series.length / 12);
  const chart = r.series.length ? `<div class="bars">${r.series.map((x, i) => `<div class="bcol" title="${esc(x.b)}: ${nf(x.n)} ${T('videí', 'videos')}, ${fmtBytes(x.bytes)}${x.failed ? `, ${x.failed} ${T('chyb', 'failed')}` : ''}"><i style="height:${val(x) ? Math.max(2, val(x) / mx * 100) : 0}%"></i><span>${i % every === 0 ? lab(x.b) : ''}</span></div>`).join('')}</div>` : '';
  const top = (rows, nameFn, linkFn) => {
    if (!rows.length) return `<div class="t2 fs12" style="padding:6px 0">${T('Zatím nic', 'Nothing yet')}</div>`;
    const m = Math.max(1, ...rows.map(val));
    return rows.map(x => `<div class="trow ${linkFn ? 'lnk' : ''}" ${linkFn ? `data-l="${esc(linkFn(x))}"` : ''}><div class="row gap8" style="justify-content:space-between"><span class="ell">${esc(nameFn(x))}</span><span class="t2 fs12" style="white-space:nowrap">${nf(x.n)} · ${fmtBytes(x.bytes)}</span></div><div class="bar"><i style="width:${val(x) / m * 100}%"></i></div></div>`).join('');
  };
  const chLink = x => (x.sub_id && subById(x.sub_id)) ? 'sub/' + x.sub_id : 'q:' + x.name;
  box.innerHTML = `<div class="kpis">
    ${kpi(T('Staženo videí', 'Videos downloaded'), nf(r.done), `${perDay >= 10 ? Math.round(perDay) : perDay.toFixed(1).replace('.', LANG === 'cs' ? ',' : '.')} ${T('za den', 'per day')}`)}
    ${kpi(T('Objem dat', 'Data volume'), fmtBytes(r.bytes), r.done ? `Ø ${fmtBytes(r.bytes / r.done)} ${T('na video', 'per video')}` : '')}
    ${kpi(T('Úspěšnost', 'Success rate'), rate == null ? '—' : rate + ' %', `${nf(r.failed)} ${T('chyb', 'failed')}`)}
    ${kpi(T('Čas stahování', 'Download time'), r.secs ? fmtDur(r.secs) : '—', r.secs && r.bytes ? `Ø ${fmtBytes(r.bytes / r.secs)}/s` : '')}</div>
    <div class="card" style="padding:16px 18px;margin-top:14px"><div class="row gap10"><b>${r.fmt === '%Y-%m' ? T('Po měsících', 'By month') : r.fmt === '%Y-%m-%d' ? T('Po dnech', 'By day') : T('Po hodinách', 'By hour')}</b><span class="grow"></span>
      <span class="seg" id="stm">${[['n', T('Počet', 'Count')], ['b', T('Objem', 'Volume')]].map(([v, l]) => `<button data-v="${v}" class="${STATS.metric === v ? 'on' : ''}">${l}</button>`).join('')}</span></div>${chart}</div>
    ${r.phases && r.phases.n ? (() => { const ph = r.phases, tot = ph.dl + ph.post + ph.move || 1, seg = [[ph.dl, T('Stahování', 'Download'), 'var(--accent)'], [ph.post, T('Zpracování (ffmpeg)', 'Processing (ffmpeg)'), 'var(--warn)'], [ph.move, T('Přesun do cílové složky', 'Move to target'), 'var(--ok)']];
      return `<div class="card" style="padding:16px 18px;margin-top:14px"><div class="row gap10"><b>${T('Čas podle fáze', 'Time by phase')}</b><span class="grow"></span><span class="t2 fs12">${ph.n} ${T('videí', 'videos')} · Ø ${fmtDur(tot / ph.n)} ${T('na video', 'per video')}</span></div>
        <div class="row" style="height:14px;border-radius:99px;overflow:hidden;margin-top:12px;background:var(--track)">${seg.map(([v, , c]) => `<i style="width:${v / tot * 100}%;background:${c};display:block"></i>`).join('')}</div>
        <div class="row gap16 wrap fs12" style="margin-top:10px">${seg.map(([v, l, c]) => `<span class="row gap6"><i style="width:9px;height:9px;border-radius:2px;background:${c};display:inline-block"></i>${l}: <b>${Math.round(v / tot * 100)} %</b> <span class="t2">(Ø ${fmtDur(v / ph.n)})</span></span>`).join('')}</div>
        <div class="t2 fs11" style="margin-top:8px">${T('Měří se od nasazení této funkce; starší stažení se nezapočítávají.', 'Measured since this feature was added; older downloads are not counted.')}</div></div>`; })() : ''}
    <div class="sgrid" style="margin-top:14px">
      <div class="card" style="padding:16px 18px"><b>${T('Podle zdroje', 'By source')}</b><div class="col gap10" style="margin-top:10px">${top(r.sources, x => srcName(x.name))}</div></div>
      <div class="card" style="padding:16px 18px"><b>${T('Podle metody', 'By method')}</b><div class="col gap10" style="margin-top:10px">${top(r.methods, x => x.name)}</div></div>
      <div class="card" style="padding:16px 18px"><b>${T('Podle webu', 'By site')}</b><div class="col gap10" style="margin-top:10px">${top(r.sites, x => x.name)}</div></div>
      <div class="card" style="padding:16px 18px"><b>${T('Podle kanálu', 'By channel')}</b><div class="col gap10" style="margin-top:10px">${top(r.channels.slice(0, 10), x => x.name, chLink)}</div></div></div>
    ${r.channels.length > 10 ? `<div class="card" style="margin-top:14px;overflow:hidden"><div style="padding:14px 18px"><b>${T('Všechny kanály', 'All channels')}</b></div><table class="stt"><tr><th>${T('Kanál', 'Channel')}</th><th>${T('Videí', 'Videos')}</th><th>${T('Objem', 'Volume')}</th></tr>${r.channels.map(x => `<tr class="lnk" data-l="${esc(chLink(x))}"><td>${esc(x.name)}</td><td>${nf(x.n)}</td><td>${fmtBytes(x.bytes)}</td></tr>`).join('')}</table></div>` : ''}
    <div class="row" style="margin-top:18px"><span class="t2 fs12">${r.first ? T('Záznamy od', 'Records since') + ' ' + new Date(r.first * 1000).toLocaleDateString() : ''}</span><span class="grow"></span><button class="btn sm danger" id="strst">${ic('trash', 13)} ${T('Vynulovat statistiky', 'Reset statistics')}</button></div>`;
  $$('#stm button').forEach(b => b.onclick = () => { STATS.metric = b.dataset.v; loadStats(); });
  $$('[data-l]', box).forEach(el => el.onclick = () => { const l = el.dataset.l; if (l.startsWith('q:')) { App.hist.q = l.slice(2); App.hist.sub = null; go('history'); } else go(l); });
  $('#strst').onclick = async () => { if (confirm(T('Vynulovat všechny statistiky? Historie ani soubory se nemění a statistiky se začnou sbírat znovu od nuly.', 'Reset all statistics? History and files are untouched; collection starts again from zero.'))) { if (await act(() => api('/api/stats', { method: 'DELETE' }), T('Statistiky vynulovány', 'Statistics reset'))) loadStats(); } };
}

/* ------------------------------------------------------------ historie */
const PAGE_SIZES = [25, 50, 100, 200];
function histLimit() { try { const v = +localStorage.getItem('vd_hist_limit'); return PAGE_SIZES.includes(v) ? v : 50; } catch (e) { return 50; } }
async function renderHistory(host, sub = null) {
  const H = App.hist; H.limit = histLimit(); H.offset = 0;
  if ((H.sub || null) !== sub) { H.q = ''; H.status = ''; resetSel(); }
  H.sub = sub;
  (host || $('#main')).innerHTML = `<div class="row gap10 wrap">${sub ? '' : `<h1>${T('Historie', 'History')}</h1>`}<span class="t2" id="htot" style="margin-left:6px"></span><span class="grow"></span>
   <div class="inwrap" style="height:32px;width:260px">${ic('search', 15)}<input id="hq" placeholder="${T('Hledat v historii…', 'Search history…')}" value="${esc(H.q)}"><button class="ibtn" id="hqx" type="button" title="${T('Smazat hledání (Esc)', 'Clear search (Esc)')}" style="width:22px;height:22px;${H.q ? '' : 'display:none'}">${ic('x', 13)}</button></div>
   <span class="seg" id="hst">${[['', T('Vše', 'All')], ['done', T('Hotovo', 'Done')], ['failed', T('Chyby', 'Failed')], ['cancelled', T('Zrušeno', 'Cancelled')], ['skipped', T('Přeskočeno', 'Skipped')]].map(([v, l]) => `<button class="${H.status === v ? 'on' : ''}" data-v="${v}">${l}</button>`).join('')}</span>
   <select class="input sm" id="hdays" style="width:170px">${[[1, T('Posledních 24 h', 'Last 24 h')], [7, T('Posledních 7 dní', 'Last 7 days')], [30, T('Posledních 30 dní', 'Last 30 days')], [0, T('Vše', 'All time')]].map(([v, l]) => `<option value="${v}" ${H.days === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
   ${(sub || (App.st.subs || []).length) ? `<label class="row gap6 fs12" style="cursor:pointer" title="${sub ? T('Záznam zůstane jinak v celkové historii.', 'Otherwise the record stays in the global history.') : T('Záznamy z odběrů zůstanou jinak v historii příslušného odběru.', 'Otherwise records from subscriptions stay in that subscription\'s history.')}"><input type="checkbox" id="hboth" ${H.both ? 'checked' : ''}>${sub ? T('i z celkové historie', 'also from global history') : T('i z historie odběrů', 'also from subscription histories')}</label>` : ''}
   <button class="btn sm" id="hclear">${ic('trash', 13)} ${T('Vymazat historii', 'Clear history')}</button></div>
   <div id="hbulk"></div>
   <div class="card" style="overflow:hidden" id="hlist"><div class="empty"><div class="spin" style="margin:auto"></div></div></div>
   <div class="row gap10 wrap" id="hpager"></div>`;
  const hqx = $('#hqx'), hqClear = () => { const el = $('#hq'); el.value = ''; hqx.style.display = 'none'; H.q = ''; H.offset = 0; resetSel(); loadHistory(); el.focus(); };
  hqx.onclick = hqClear; $('#hq').onkeydown = e => { if (e.key === 'Escape' && $('#hq').value) { e.preventDefault(); hqClear(); } };
  let tmr; $('#hq').oninput = e => { hqx.style.display = e.target.value ? '' : 'none'; clearTimeout(tmr); tmr = setTimeout(() => { H.q = e.target.value; H.offset = 0; resetSel(); loadHistory(); }, 300); };
  $$('#hst button').forEach(b => b.onclick = () => { H.status = b.dataset.v; H.offset = 0; resetSel(); $$('#hst button').forEach(x => x.classList.toggle('on', x === b)); loadHistory(); });
  $('#hdays').onchange = e => { H.days = +e.target.value; H.offset = 0; resetSel(); loadHistory(); };
  const hb = $('#hboth'); if (hb) hb.onchange = e => { H.both = e.target.checked; };
  $('#hclear').onclick = async () => { if (confirm(T('Smazat celou historii' + (H.sub ? ' tohoto odběru' : '') + '? Stažené soubory zůstanou na disku.', 'Delete all history' + (H.sub ? ' of this subscription' : '') + '? Downloaded files stay on disk.'))) { await act(() => api('/api/history', { method: 'DELETE', body: { filter: { sub: H.sub || 0 }, scope: H.both ? 'both' : 'here' } }), T('Historie smazána', 'History cleared')); H.offset = 0; loadHistory(); } };
  loadHistory();
}
function pagerHtml(matched, offset, limit) {
  const pages = Math.max(1, Math.ceil(matched / limit)), cur = Math.floor(offset / limit) + 1;
  const nums = [];
  for (let p = 1; p <= pages; p++) if (p === 1 || p === pages || Math.abs(p - cur) <= 2) nums.push(p); else if (nums[nums.length - 1] !== '…') nums.push('…');
  const btn = (p, label, dis) => `<button class="btn sm ${p === cur && !label ? 'primary' : ''}" ${dis ? 'disabled' : ''} data-page="${p}">${label || p}</button>`;
  const from = matched ? offset + 1 : 0, to = Math.min(offset + limit, matched);
  return `<span class="t2 fs12">${T('Zobrazeno', 'Showing')} ${from}–${to} ${T('z', 'of')} ${matched}</span><span class="grow"></span>
    ${pages > 1 ? `<span class="row gap4">${btn(cur - 1, ic('right', 12).replace('M9 6l6 6-6 6', 'M15 6l-6 6 6 6'), cur <= 1)}${nums.map(p => p === '…' ? '<span class="t2">…</span>' : btn(p)).join('')}${btn(cur + 1, ic('right', 12), cur >= pages)}</span>` : ''}
    <label class="row gap6 t2 fs12">${T('Na stránku', 'Per page')}<select class="input sm" id="hlimit" style="width:76px">${PAGE_SIZES.map(n => `<option ${n === limit ? 'selected' : ''}>${n}</option>`).join('')}</select></label>`;
}
function resetSel() { const H = App.hist; H.sel = new Set(); H.all = false; }
function bulkBar(matched) {
  const H = App.hist, el = $('#hbulk'); if (!el) return;
  const n = H.all ? matched : H.sel.size;
  if (!n) { el.innerHTML = ''; return; }
  const allPage = H.items.length > 0 && H.items.every(x => H.sel.has(x.id));
  el.innerHTML = `<div class="card row gap10 wrap" style="padding:10px 16px;margin-bottom:12px"><b>${T('Vybráno', 'Selected')}: ${n}</b>
    ${!H.all && allPage && matched > H.sel.size ? `<button class="btn sm" id="bsall">${T(`Vybrat všech ${matched} odpovídajících filtru`, `Select all ${matched} matching the filter`)}</button>` : ''}
    <button class="btn sm" id="bsnone">${T('Zrušit výběr', 'Clear selection')}</button><span class="grow"></span>
    <label class="row gap6 fs12" style="cursor:pointer" title="${T('Hotová a přeskočená videa se vyřadí z archivu stažených, takže půjdou stáhnout znovu. U chyb se nic neděje, ty v archivu nejsou.', 'Done and skipped videos are removed from the download archive so they can be downloaded again. Failed items are not in the archive.')}"><input type="checkbox" id="bsarch" ${H.forget ? 'checked' : ''}>${T('Odstranit i z archivu stažených', 'Also remove from the download archive')}</label>
    <button class="btn sm danger" id="bsdel">${ic('trash', 13)} ${T('Odstranit vybrané', 'Delete selected')} (${n})</button></div>`;
  const refresh = () => {
    $$('.hsel', $('#hlist')).forEach(c => { c.checked = H.all || H.sel.has(+c.dataset.id); c.closest('.hr').classList.toggle('sel', c.checked); });
    const a = $('#hall'); if (a) a.checked = H.all || (H.items.length > 0 && H.items.every(x => H.sel.has(x.id)));
    bulkBar(matched);
  };
  const b1 = $('#bsall'); if (b1) b1.onclick = () => { H.all = true; refresh(); };
  $('#bsnone').onclick = () => { resetSel(); refresh(); };
  $('#bsarch').onchange = e => { H.forget = e.target.checked; };
  $('#bsdel').onclick = async () => {
    const f = !!H.forget;
    if (!confirm(T(`Odstranit ${n} záznamů z historie${f ? ' a hotová videa i z archivu stažených (půjdou stáhnout znovu)' : ''}? Stažené soubory zůstanou na disku.`,
      `Delete ${n} records from history${f ? ' and remove done videos from the download archive (they can be downloaded again)' : ''}? Downloaded files stay on disk.`))) return;
    const body = H.all ? { filter: { q: H.q, status: H.status, days: H.days, sub: H.sub || 0 }, forget_archive: f, scope: H.both ? 'both' : 'here' } : { ids: [...H.sel], view: H.sub || 0, forget_archive: f, scope: H.both ? 'both' : 'here' };
    const ok = await act(() => api('/api/history', { method: 'DELETE', body }), T('Záznamy odstraněny', 'Records deleted'));
    if (ok) { resetSel(); H.offset = 0; loadHistory(); }
  };
}
async function loadHistory() {
  const H = App.hist; if (!H.sel) resetSel();
  const r = await act(() => api(`/api/history?q=${encodeURIComponent(H.q)}&status=${H.status}&days=${H.days}&offset=${H.offset}&limit=${H.limit}&sub=${H.sub || 0}`)); if (!r) return;
  if (!r.items.length && r.matched && H.offset >= r.matched) { H.offset = Math.max(0, Math.floor((r.matched - 1) / H.limit) * H.limit); return loadHistory(); }
  H.items = r.items;
  $('#htot').textContent = `${r.total_done} ${T('stažených videí', 'downloaded videos')} · ${fmtBytes(r.total_bytes)}`;
  const local = App.st && !App.st.docker && ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  const badge = { done: `<span class="badge b-ok">${ic('check', 11)} ${T('Hotovo', 'Done')}</span>`, failed: `<span class="badge b-err">${ic('alert', 11)} ${T('Chyba', 'Failed')}</span>`,
    cancelled: `<span class="badge b-n">${ic('x', 11)} ${T('Zrušeno', 'Cancelled')}</span>`, skipped: `<span class="badge b-warn">${T('Přeskočeno', 'Skipped')}</span>` };
  const rows = r.items.map(h => {
    const gone = h.status === 'done' && h.file_exists === false;
    const playable = h.status === 'done' && !gone;
    const sub = gone ? `<div class="mm"><span class="ell">${T('Soubor už na úložišti není', 'The file is no longer on the storage')} · ${esc(h.filepath || '')}</span></div>`
      : h.status === 'done' ? `<div class="mm"><span class="ell">${esc(h.channel || '')}${h.height ? ' · ' + h.height + 'p' : ''} · </span>${srcIcon(h.source)} ${srcName(h.source)}</div>`
      : `<div class="mm ${h.status === 'failed' ? 'err' : ''}" style="white-space:normal">${h.status === 'failed' ? ic('alert', 12) : ''} ${esc(h.error || '')}</div>`;
    const acts = gone ? `<button class="btn sm" data-h="retry" data-id="${h.id}" title="${T('Vyřadí video z archivu stažených a zařadí ho do fronty', 'Removes the video from the download archive and queues it')}">${ic('download', 12)} ${T('Stáhnout znovu', 'Download again')}</button>`
      : playable
      ? `<button class="ibtn" title="${T('Přehrát', 'Play')}" data-h="play" data-id="${h.id}">${ic('play', 15)}</button>` +
        (local ? `<button class="ibtn" title="${T('Zobrazit ve složce', 'Show in folder')}" data-h="open" data-id="${h.id}">${ic('folder', 15)}</button>` : '') +
        `<a class="ibtn" title="${T('Stáhnout soubor', 'Download file')}" href="/api/file/${h.id}">${ic('download', 15)}</a>`
      : `<button class="btn sm" data-h="retry" data-id="${h.id}">${ic('refresh', 12)} ${T('Znovu', 'Retry')}</button>`;
    const on = H.all || H.sel.has(h.id);
    return `<div class="hr ${on ? 'sel' : ''}"><div><input type="checkbox" class="hsel" data-id="${h.id}" ${on ? 'checked' : ''}></div><div ${playable ? `data-h="play" data-id="${h.id}" style="cursor:pointer" title="${T('Přehrát', 'Play')}"` : ''}>${thumbHtml(h, 104, 58)}</div><div style="min-width:0"><div class="b6 fs14 ell" title="${esc(h.filepath || h.url)}">${esc(h.title || h.url)}</div>${sub}</div>
     <div>${gone ? `<span class="badge b-warn">${ic('trash', 11)} ${T('Soubor smazán', 'File deleted')}</span>` : badge[h.status] || ''}</div><div class="hide-s">${methodBadge(h.method)}</div><div class="b5 hide-s">${h.status === 'done' && !gone ? fmtBytes(h.filesize) : '—'}</div><div class="t2">${fmtDate(h.finished_at)}</div>
     <div class="acts">${acts}<a class="ibtn" title="${esc(h.url)}" href="${esc(h.url)}" target="_blank" rel="noopener noreferrer">${ic('link', 15)}</a><button class="ibtn" title="${T('Smazat záznam', 'Delete record')}" data-h="del" data-id="${h.id}">${ic('trash', 14)}</button></div></div>`;
  }).join('');
  $('#hlist').innerHTML = r.items.length ? `<div class="hr h"><span><input type="checkbox" id="hall" title="${T('Vybrat vše na stránce', 'Select all on page')}"></span><span></span><span>Video</span><span>${T('Stav', 'Status')}</span><span class="hide-s">${T('Metoda', 'Method')}</span><span class="hide-s">${T('Velikost', 'Size')}</span><span>${T('Dokončeno', 'Finished')}</span><span></span></div>${rows}`
    : `<div class="empty">${ic('history', 30)}<h3>${T('Historie je prázdná', 'History is empty')}</h3><p>${T('Dokončená a neúspěšná stahování se zobrazí tady.', 'Finished and failed downloads show up here.')}</p></div>`;
  const markRows = () => $$('.hsel', $('#hlist')).forEach(c => c.closest('.hr').classList.toggle('sel', c.checked));
  $$('.hsel', $('#hlist')).forEach(c => c.onchange = () => {
    const id = +c.dataset.id;
    if (H.all) { H.all = false; H.items.forEach(x => H.sel.add(x.id)); }  // ruční zásah ruší „vše dle filtru“
    if (c.checked) H.sel.add(id); else H.sel.delete(id);
    markRows(); const a = $('#hall'); if (a) a.checked = H.items.every(x => H.sel.has(x.id));
    bulkBar(r.matched);
  });
  const ha = $('#hall');
  if (ha) {
    ha.checked = H.all || (H.items.length > 0 && H.items.every(x => H.sel.has(x.id)));
    ha.onchange = () => { H.all = false; H.items.forEach(x => { if (ha.checked) H.sel.add(x.id); else H.sel.delete(x.id); }); $$('.hsel', $('#hlist')).forEach(c => { c.checked = ha.checked; }); markRows(); bulkBar(r.matched); };
  }
  bulkBar(r.matched);
  $('#hpager').innerHTML = r.matched ? pagerHtml(r.matched, r.offset, r.limit) : '';
  $$('[data-page]', $('#hpager')).forEach(b => b.onclick = () => { H.offset = (+b.dataset.page - 1) * H.limit; loadHistory(); $('#mainwrap').scrollTop = 0; });
  const sel = $('#hlimit'); if (sel) sel.onchange = e => { H.limit = +e.target.value; try { localStorage.setItem('vd_hist_limit', H.limit); } catch (er) { /* bez úložiště */ } H.offset = 0; loadHistory(); };
  $$('[data-h]', $('#hlist')).forEach(b => b.onclick = async () => {
    const id = +b.dataset.id, a = b.dataset.h;
    if (a === 'play') return openPlayer(H.items.find(x => x.id === id), local);
    if (a === 'open') act(() => api(`/api/jobs/${id}/open`, { method: 'POST' }));
    if (a === 'retry') { const ok = await act(() => api(`/api/jobs/${id}/retry`, { method: 'POST' }), T('Přidáno znovu do fronty', 'Added to the queue again')); if (ok) loadHistory(); }
    if (a === 'del') { await act(() => api('/api/history', { method: 'DELETE', body: { ids: [id], view: H.sub || 0, scope: H.both ? 'both' : 'here' } })); loadHistory(); }
  });
}
function openPlayer(h, local) {
  if (!h) return;
  const audio = /\.(mp3|m4a|opus|ogg)$/i.test(h.filepath || '');
  const m = modal(`<div class="mh">${ic('play', 18)}<h2 class="ell grow" title="${esc(h.title || '')}">${esc(h.title || h.url)}</h2><button class="ibtn" id="pclose" title="${T('Zavřít', 'Close')}">${ic('x', 16)}</button></div>
   <div class="mb"><${audio ? 'audio' : 'video'} id="pvid" controls autoplay playsinline preload="metadata" src="/api/stream/${h.id}" style="width:100%;${audio ? '' : 'max-height:70vh;background:#000;border-radius:10px;display:block'}"></${audio ? 'audio' : 'video'}>
   <div id="perr" class="banner" style="display:none;margin-top:12px">${ic('alert', 16)}<span class="grow"><span id="perrmsg">${T('Tento prohlížeč video nepřehraje: Safari neumí kontejner MKV (a některé kodeky), Chrome a Edge ho obvykle přehrají. Soubor si můžete stáhnout nebo otevřít v jiném přehrávači (např. VLC). Aplikace videa nekóduje ani nepřebaluje; chcete-li příště soubory přehratelné všude, nastavte v Nastavení › Stahování Kvalitu na Kompatibilitu (MP4 s H.264, u některých webů nejvýš 1080p).', 'This browser cannot play the video: Safari cannot open the MKV container (and some codecs), Chrome and Edge usually can. Download the file or open it in another player (e.g. VLC). The app never re-encodes or repackages video; to get files that play everywhere next time, set Quality to Compatibility in Settings › Downloading (MP4 with H.264, up to 1080p on some sites).')}</span>${audio ? '' : `<button class="btn sm" id="ptc">${ic('play', 12)} ${T('Přehrát přebalenou verzi', 'Play repackaged version')}</button>`}</div>
   <div class="row gap8 t2 fs12 wrap" style="margin-top:10px">${esc(h.channel || '')}${h.height ? ' · ' + h.height + 'p' : ''} · ${fmtBytes(h.filesize)} · <span class="mono ell" style="max-width:100%">${esc(h.filepath || '')}</span></div></div>
   <div class="mf">${local ? `<button class="btn" id="pfold">${ic('folder', 14)} ${T('Zobrazit ve složce', 'Show in folder')}</button>` : ''}<a class="btn" href="/api/file/${h.id}">${ic('download', 14)} ${T('Stáhnout soubor', 'Download file')}</a><button class="btn primary" id="pclose2">${T('Zavřít', 'Close')}</button></div>`, 'wide');
  m.el.style.width = '960px';
  const v = $('#pvid', m.el);
  const perr = $('#perr', m.el);
  const fail = () => { perr.style.display = 'flex'; };
  v.addEventListener('error', fail);
  if (!audio) {                                                                // prohlížeč nemusí poslat chybu: video bez obrazu nebo se nerozjede
    v.addEventListener('loadedmetadata', () => { if (v.videoWidth === 0) fail(); });
    const guard = setTimeout(() => { if (v.readyState < 2 || v.videoWidth === 0) fail(); }, 8000);
    v.addEventListener('playing', () => clearTimeout(guard), { once: true });
  }
  const close = () => { try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) { /* nic */ } m.close(); document.removeEventListener('keydown', esc_); };
  const esc_ = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', esc_);
  $('#pclose', m.el).onclick = close; $('#pclose2', m.el).onclick = close;
  const f = $('#pfold', m.el); if (f) f.onclick = () => act(() => api(`/api/jobs/${h.id}/open`, { method: 'POST' }));
  $('.overlay').addEventListener('mousedown', e => { if (e.target.classList.contains('overlay')) close(); });
}

/* ------------------------------------------------------------ nastavení */
const L = x => Array.isArray(x) ? T(x[0], x[1]) : x;
const SECTIONS = () => [
  { icon: 'download', title: ['Stahování', 'Downloading'], col: 0, fields: [
    { k: 'download_dir', type: 'path', label: ['Cílová složka', 'Download folder'] },
    { k: 'concurrency', type: 'stepper', min: 1, max: 16, label: ['Souběžná stahování', 'Parallel downloads'], hint: ['Platí okamžitě', 'Applies immediately'] },
    { k: 'perf_mode', type: 'seg', opts: [['full', T('Plný', 'Full')], ['balanced', T('Vyvážený', 'Balanced')], ['eco', T('Šetrný', 'Eco')]], label: ['Výkon', 'Performance'],
      hint: ['Šetrný snižuje prioritu procesů, vlákna ffmpeg a souběžnost (max. 1). Zpět na Plný platí pro nově spuštěná stahování.', 'Eco lowers process priority, ffmpeg threads and concurrency (max 1). Switching back to Full applies to newly started downloads.'] },
    { k: 'quality', type: 'seg', opts: [['max', ['Maximální', 'Maximum']], ['compat', ['Kompatibilita', 'Compatibility']]], label: ['Kvalita', 'Quality'], hint: ['Kompatibilita = MP4 / H.264 pro starší přehrávače', 'Compatibility = MP4 / H.264 for older players'] },
    { k: 'audio_only', type: 'toggle', label: ['Stahovat jen zvuk', 'Audio only'] },
    { k: 'audio_format', type: 'seg', opts: [['mp3', 'MP3'], ['m4a', 'M4A']], label: ['Formát zvuku', 'Audio format'] },
    { k: 'channel_tabs', type: 'chips', opts: [['videos', ['Videa', 'Videos']], ['shorts', 'Shorts'], ['streams', ['Živé přenosy', 'Live streams']]], label: ['Z kanálu stahovat', 'From channels download'] },
    { k: 'playlist_confirm_threshold', type: 'number', min: 1, suffix: ['videí', 'videos'], label: ['Potvrdit playlist nad', 'Confirm playlists over'], hint: ['Větší playlist nebo kanál se nejdřív potvrdí', 'Larger playlists ask first'] },
    { k: 'subscription_check_hours', type: 'number', min: 0, suffix: 'h', label: ['Kontrola odběrů po', 'Check subscriptions every'], hint: ['Jak často se hledají nová videa v odběrech; 0 = vypnuto', 'How often subscriptions look for new videos; 0 = off'] },
    { k: 'live_from_start', type: 'toggle', label: ['Nahrávat živé přenosy od začátku', 'Record live streams from start'], hint: ['Jinak se probíhající přenos přeskočí', 'Otherwise live streams are skipped'] },
    { k: 'queue_previews', type: 'toggle', label: ['Náhledy a názvy ve frontě', 'Previews and titles in the queue'], hint: ['Na pozadí doplní miniaturu a název čekajícím videím (po jednom, s odstupem). V režimu Šetrný se nenačítá.', 'Fills in the thumbnail and title of waiting videos in the background (one at a time). Off in Eco mode.'] },
    { k: 'subtitles', type: 'toggle', label: ['Titulky', 'Subtitles'], hint: ['Vloží se do souboru videa', 'Embedded into the video file'] },
    { k: 'subtitle_langs', type: 'text', w: 120, label: ['Jazyky titulků', 'Subtitle languages'] },
    { k: 'auto_subtitles', type: 'toggle', label: ['Včetně automatických titulků', 'Include auto-generated'] },
    { k: 'mkv_to_mp4', type: 'toggle', label: ['Po stažení přebalit MKV do MP4', 'Repackage MKV to MP4 after download'], hint: ['Jen změna kontejneru (obraz, zvuk i titulky se zkopírují, nic se nekóduje, trvá sekundy). Safari MKV nepřehraje, MP4 ano. Selže-li přebalení, zůstane MKV.', 'Container change only (video, audio and subtitles are copied, nothing is re-encoded, takes seconds). Safari cannot play MKV but plays MP4. If it fails, the MKV stays.'] },
    { k: 'embed_metadata', type: 'toggle', label: ['Vložit metadata a kapitoly', 'Embed metadata and chapters'] },
  ] },
  { icon: 'clock', title: ['Rychlost', 'Speed'], col: 0, fields: [
    { k: 'rate_limit_enabled', type: 'toggle', label: ['Omezit rychlost', 'Limit speed'], hint: ['Celkem pro všechna stahování', 'Total for all downloads'] },
    { k: 'rate_limit_mbps', type: 'number', step: 0.5, min: 0.1, suffix: 'MB/s', label: ['Limit', 'Limit'] },
    { k: 'sleep_min', type: 'number', min: 0, suffix: 's', label: ['Pauza mezi videi playlistu od', 'Pause between playlist videos from'] },
    { k: 'sleep_max', type: 'number', min: 0, suffix: 's', label: ['do', 'to'] },
  ] },
  { icon: 'clock', title: ['Časový rozvrh', 'Schedule'], col: 0, fields: [
    { k: 'schedule_enabled', type: 'toggle', label: ['Pracovat jen v časových oknech', 'Work only in time windows'], hint: ['Mimo okna aplikace nezačne novou automatickou práci', 'Outside the windows the app starts no new automatic work'] },
    { k: 'schedule_scope', type: 'chips', opts: [['queue', ['Stahování fronty', 'Queue downloads']], ['subscriptions', ['Kontroly odběrů', 'Subscription checks']], ['catalog', ['Zjišťování katalogu', 'Catalog scanning']]], label: ['Co se rozvrhem řídí', 'What it controls'], hint: ['Ruční akce (Zkontrolovat teď, Obnovit zdroj) se rozvrhem neřídí', 'Manual actions (Check now, Refresh source) ignore the schedule'] },
    { type: 'schedule' },
    { k: 'schedule_finish_running', type: 'seg', opts: [['false', ['Přerušit', 'Interrupt']], ['true', ['Nechat doběhnout', 'Let finish']]], label: ['Po skončení okna', 'At the end of a window'], hint: ['Týká se rozpracovaných stahování', 'Applies to downloads in progress'] },
    { type: 'schstatus' },
  ] },
  { icon: 'tag', title: ['Pojmenování a složky', 'Naming and folders'], col: 1, fields: [
    { k: 'name_template', type: 'template', label: ['Šablona názvu souboru', 'File name template'] },
    { k: 'channel_name_template', type: 'template', label: ['Šablona názvu u kanálu', 'Template for channels'] },
    { k: 'playlist_folder', type: 'toggle', label: ['Samostatná složka pro playlist', 'Separate folder per playlist'], hint: ['Pojmenovaná podle playlistu', 'Named after the playlist'] },
    { k: 'channel_folder', type: 'toggle', label: ['Samostatná složka pro kanál', 'Separate folder per channel'], hint: ['Pojmenovaná podle kanálu', 'Named after the channel'] },
    { type: 'static', label: ['Miniatura JPG vedle videa', 'JPG thumbnail next to the video'], html: `<span class="badge b-n">${ic('lock', 11)} ${T('Vždy', 'Always')}</span>` },
  ] },
  { icon: 'cookie', title: ['Přístup a síť', 'Access and network'], col: 1, fields: [
    { type: 'cookies' },
    { k: 'proxy', type: 'text', w: 220, placeholder: 'socks5://127.0.0.1:1080', label: ['Proxy', 'Proxy'] },
    { type: 'password' },
    { k: 'network_access', type: 'toggle', label: ['Přístup ze sítě', 'Network access'], hint: ['Vyžaduje heslo. Projeví se po restartu aplikace.', 'Requires a password. Applies after restart.'] },
    { k: 'port', type: 'number', min: 1024, max: 65535, w: 90, label: ['Port', 'Port'], hint: ['Projeví se po restartu', 'Applies after restart'] },
  ] },
  { icon: 'send', title: ['Telegram', 'Telegram'], col: 0, fields: [
    { type: 'tgtoken' },
    { k: 'telegram_chat_id', type: 'text', w: 160, label: ['Povolené chat ID', 'Allowed chat ID'], hint: ['Bot odpovídá jen tomuto chatu', 'The bot answers only this chat'] },
    { k: 'telegram_after_probe', type: 'seg', opts: [['download', ['Stáhnout hned', 'Download now']], ['ask', ['Zeptat se', 'Ask']]], label: ['Po kontrole URL', 'After URL check'] },
    { k: 'telegram_notify', type: 'seg', opts: [['errors', ['Jen chyby', 'Errors only']], ['all', ['Vše', 'All']]], label: ['Oznámení', 'Notifications'] },
  ] },
  { icon: 'palette', title: ['Vzhled a jazyk', 'Appearance and language'], col: 1, fields: [
    { k: 'language', type: 'seg', opts: [['cs', 'Čeština'], ['en', 'English']], label: ['Jazyk', 'Language'] },
    { k: 'theme', type: 'seg', opts: [['light', ['Světlý', 'Light']], ['dark', ['Tmavý', 'Dark']], ['system', ['Podle systému', 'System']]], label: ['Motiv', 'Theme'] },
  ] },
  { icon: 'refresh', title: ['Aktualizace aplikace', 'App updates'], col: 0, fields: [
    { type: 'appstatus' },
    { k: 'app_update_mode', type: 'seg', opts: [['off', ['Vypnuto', 'Off']], ['notify', ['Jen oznámit', 'Notify only']], ['auto', ['Automaticky', 'Automatic']]], label: ['Režim', 'Mode'], hint: ['Automaticky = stáhne, otestuje a po doběhnutí stahování restartuje. Při potížích se nová verze sama vrátí.', 'Automatic = downloads, tests and restarts once downloads finish. A bad version rolls back by itself.'] },
    { k: 'app_update_hours', type: 'seg', opts: [[6, '6 h'], [12, '12 h'], [24, ['1 den', '1 day']], [72, ['3 dny', '3 days']], [168, ['1 týden', '1 week']]], label: ['Jak často kontrolovat', 'How often to check'] },
    { k: 'app_update_repo', type: 'text', w: 220, label: ['GitHub repozitář', 'GitHub repository'], hint: ['Ve tvaru vlastník/název', 'Format owner/name'] },
  ] },
  { icon: 'film', title: ['Katalog', 'Catalog'], col: 0, fields: [
    { k: 'catalog_thumbs_dir', type: 'path', label: ['Složka miniatur', 'Thumbnails folder'], hint: ['Prázdné = složka catalog/thumbs v datové složce. V Dockeru musí být připojená jako svazek. Odhad: 150 až 300 kB na video.', 'Empty = the catalog/thumbs folder in the data folder. In Docker it must be a mounted volume. About 150–300 kB per video.'] },
    { k: 'catalog_slow_browser', type: 'toggle', label: ['Pomalé weby zjišťovat prohlížečem', 'Check unsupported sites with the browser'], hint: ['U webů, které yt-dlp nezná: seznam videí se v případě potřeby vykreslí v Chromiu a podrobnosti videí se zjišťují až nakonec, po jednom. Je to pomalejší a náročnější.', 'For sites yt-dlp does not know: the video list is rendered in Chromium when needed and video details are checked last, one at a time. Slower and heavier.'] },
    { k: 'catalog_anim', type: 'toggle', label: ['Stahovat animované náhledy', 'Download animated previews'], hint: ['Když web nabízí krátkou animaci (GIF, WebP, MP4), uloží se vedle miniatury. Zabírá víc místa než obrázek.', 'When a site offers a short animation (GIF, WebP, MP4) it is saved next to the thumbnail. Uses more space than an image.'] },
    { k: 'catalog_anim_pages', type: 'toggle', label: ['Hledat animaci i na stránce videa', 'Also look for animations on the video page'], hint: ['U videí, ke kterým yt-dlp animaci nenabídl, se jednou stáhne stránka videa a zkusí se na ní najít náhledový klip (pomalu, po jednom videu na web). Znamená jeden dotaz navíc na video.', 'For videos where yt-dlp offered no animation, the video page is fetched once and searched for a preview clip (slowly, one video per site). Costs one extra request per video.'] },
    { k: 'catalog_anim_max_mb', type: 'number', min: 1, max: 20, suffix: 'MB', label: ['Největší velikost animace', 'Largest animation size'], hint: ['Větší animace se nestáhne a zůstane statická miniatura (výchozí 5 MB).', 'A larger animation is not downloaded and the static thumbnail stays (default 5 MB).'] },
    { type: 'catdisk' },
    { k: 'catalog_gap', type: 'number', min: 0, max: 60, suffix: 's', label: ['Pauza mezi dotazy na stejný web', 'Pause between requests to the same site'], hint: ['Při zjišťování podrobností videí; režim výkonu ji prodlužuje (Vyvážený 2×, Šetrný 4×)', 'While checking video details; the performance mode lengthens it (Balanced 2×, Eco 4×)'] },
  ] },
  { icon: 'cpu', title: ['Enginy', 'Engines'], col: 0, fields: [
    { k: 'engine_auto_update', type: 'toggle', label: ['Automatické aktualizace', 'Automatic updates'] },
    { k: 'engine_update_hours', type: 'number', min: 1, suffix: 'h', label: ['Interval kontroly', 'Check interval'] },
    { k: 'keep_engine_versions', type: 'number', min: 1, max: 10, label: ['Uchovat verzí', 'Versions to keep'] },
    { k: 'selftest_url', type: 'text', w: 260, label: ['Testovací URL', 'Test URL'], hint: ['Ověřuje se na ní nová verze yt-dlp', 'Used to test new yt-dlp versions'] },
  ] },
  { icon: 'download', title: ['Záloha a obnova', 'Backup and restore'], col: 0, fields: [
    { type: 'backup' },
    { k: 'auto_backup', type: 'toggle', label: ['Automatické zálohy', 'Automatic backups'], hint: ['Šifrované soubory .dtb se vytvářejí podle rozvrhu', 'Encrypted .dtb files are created on a schedule'] },
    { k: 'auto_backup_hours', type: 'seg', opts: [[6, '6 h'], [12, '12 h'], [24, ['1 den', '1 day']], [72, ['3 dny', '3 days']], [168, ['1 týden', '1 week']]], label: ['Jak často', 'How often'] },
    { k: 'auto_backup_dir', type: 'path', label: ['Složka pro zálohy', 'Backup folder'], hint: ['Prázdné = složka backups v datové složce. Proti ztrátě disku zvolte jiné místo (např. jinou síťovou složku). V Dockeru musí být připojená jako svazek.', 'Empty = the backups folder in the data folder. To survive a disk loss pick another place (e.g. another network folder). In Docker it must be a mounted volume.'] },
    { k: 'auto_backup_keep', type: 'number', min: 1, max: 100, label: ['Kolik záloh uchovat', 'Backups to keep'], hint: ['Po úspěšné záloze se nejstarší nad tento počet smažou', 'After a successful backup the oldest ones above this number are deleted'] },
    { type: 'abstatus' },
  ] },
  { icon: 'sliders', title: ['Pokročilé', 'Advanced'], col: 1, fields: [
    { k: 'methods', type: 'seg', opts: [['ytdlp,sniffer', 'yt-dlp → sniffer'], ['sniffer,ytdlp', 'sniffer → yt-dlp'], ['ytdlp', ['jen yt-dlp', 'yt-dlp only']], ['sniffer', ['jen sniffer', 'sniffer only']]], label: ['Pořadí metod', 'Method order'] },
    { k: 'sniff_timeout', type: 'number', min: 10, suffix: 's', label: ['Čekání snifferu na video', 'Sniffer timeout'] },
    { k: 'probe_concurrency', type: 'number', min: 1, max: 8, label: ['Souběžné kontroly URL', 'Parallel URL checks'] },
    { k: 'retries', type: 'number', min: 0, label: ['Opakování síťových chyb', 'Network retries'] },
    { k: 'auto_retry_attempts', type: 'number', min: 0, max: 5, label: ['Automatické opakování úlohy', 'Automatic job retries'] },
    { k: 'min_free_gb', type: 'number', min: 0, step: 0.5, suffix: 'GB', label: ['Minimum volného místa', 'Minimum free space'], hint: ['Hlídá dočasnou i cílovou složku', 'Checks temp and download folder'] },
    { k: 'temp_dir', type: 'path', label: ['Dočasná složka', 'Temporary folder'], hint: ['Prázdné = datová složka aplikace', 'Empty = app data folder'] },
    { k: 'history_days', type: 'number', min: 0, suffix: [ 'dní', 'days'], label: ['Uchovávat historii', 'Keep history'], hint: ['0 = neomezeně', '0 = forever'] },
    { k: 'log_level', type: 'seg', opts: [['DEBUG', 'Debug'], ['INFO', 'Info'], ['WARNING', T('Varování', 'Warning')], ['ERROR', T('Chyby', 'Errors')]], label: ['Úroveň logů', 'Log level'] },
  ] },
];

function fieldHtml(f, S) {
  if (S.docker && f.type === 'path' && f.k === 'download_dir' && !f.hint)
    f = Object.assign({}, f, { hint: ['V Dockeru jen složky připojené do kontejneru (např. /downloads, /nas). Při uložení se ověří zápis.', 'In Docker only folders mounted into the container (e.g. /downloads, /nas). Write access is checked on save.'] });
  else if (f.type === 'path' && f.k === 'download_dir' && !f.hint)
    f = Object.assign({}, f, { hint: ['Může být i síťová složka. Při uložení se ověří zápis.', 'Network folders work too. Write access is checked on save.'] });
  if (S.docker && (f.k === 'network_access' || f.k === 'port'))
    return `<div class="fld"><div class="lab"><div class="b5">${L(f.label)}</div><div class="hint">${T('V Dockeru se řídí mapováním portů v docker-compose', 'In Docker this is set by the port mapping in docker-compose')}</div></div><span class="badge b-n">${ic('lock', 11)} Docker</span></div>`;
  const v = f.k ? S.values[f.k] : null; const lock = f.k && S.locked[f.k];
  const dis = lock ? 'disabled' : '';
  const lab = (extra = '') => `<div class="lab"><div class="b5">${L(f.label)}${lock ? ` <span class="lock" title="${T('Nastaveno proměnnou prostředí', 'Set by environment variable')} ${esc(lock)}">${ic('lock', 12)}</span>` : ''}</div>${f.hint ? `<div class="hint">${L(f.hint)}</div>` : ''}${extra}</div>`;
  let ctrl = '';
  switch (f.type) {
    case 'toggle': ctrl = `<button class="toggle ${v ? 'on' : ''}" data-k="${f.k}" data-t="toggle" ${dis}></button>`; break;
    case 'seg': { const cur = Array.isArray(v) ? v.join(',') : String(v);
      ctrl = `<span class="seg">${f.opts.map(([o, l]) => `<button data-k="${f.k}" data-t="seg" data-v="${o}" class="${String(o) === cur ? 'on' : ''}" ${dis}>${L(l)}</button>`).join('')}</span>`; break; }
    case 'chips': ctrl = `<span class="row gap4 wrap">${f.opts.map(([o, l]) => `<button class="chip ${v.includes(o) ? 'on' : ''}" data-k="${f.k}" data-t="chip" data-v="${o}" ${dis}>${L(l)}</button>`).join('')}</span>`; break;
    case 'number': ctrl = `<input class="input sm" type="number" style="width:${f.w || 80}px" data-k="${f.k}" data-t="num" value="${esc(v)}" ${f.min != null ? `min="${f.min}"` : ''} ${f.max != null ? `max="${f.max}"` : ''} step="${f.step || 1}" ${dis}>${f.suffix ? `<span class="t2">${L(f.suffix)}</span>` : ''}`; break;
    case 'stepper': ctrl = `<button class="ibtn b" data-k="${f.k}" data-t="step" data-d="-1" ${dis}>${ic('minus', 14)}</button><span class="b6 fs15" style="width:24px;text-align:center">${v}</span><button class="ibtn b" data-k="${f.k}" data-t="step" data-d="1" ${dis}>${ic('plus', 14)}</button>`; break;
    case 'text': ctrl = `<input class="input sm" style="width:${f.w || 200}px" data-k="${f.k}" data-t="text" value="${esc(v)}" placeholder="${esc(f.placeholder || '')}" ${dis}>`; break;
    case 'time': ctrl = `<input class="input sm mono" type="time" style="width:110px" data-k="${f.k}" data-t="text" value="${esc(v)}" ${dis}>`; break;
    case 'path': return `<div class="fld block">${lab()}<div class="row gap8" style="margin-top:8px"><input class="input sm mono fs12" style="flex:1;min-width:0" data-k="${f.k}" data-t="text" value="${esc(v)}" ${dis}><button class="btn sm" data-pick="${f.k}" ${dis}>${ic('folder', 13)} ${T('Vybrat', 'Browse')}</button></div></div>`;
    case 'static': ctrl = f.html; break;
    case 'template': return `<div class="fld block">${lab()}<input class="input sm mono" style="margin-top:8px" data-k="${f.k}" data-t="text" value="${esc(v)}" ${dis}>
      <div class="row gap6 wrap" style="margin-top:8px">${['{název}', '{kanál}', '{playlist}', '{datum}', '{rozlišení}', '{id}', '{pořadí}'].map(x => `<button class="chip mono" style="height:22px;font-size:11px" data-ins="${f.k}" data-v="${x}">${x}</button>`).join('')}</div>
      <div class="fs12 t2" style="margin-top:8px">${T('Náhled', 'Preview')}: <span class="mono" style="color:var(--text)">${esc(previewName(v))}.mp4</span></div></div>`;
    case 'cookies': { const cf = S.cookies_file; const mode = S.values.cookies_mode;
      return `<div class="fld"><div class="lab"><div class="b5">Cookies</div><div class="hint">${mode === 'browser' ? T('Čte se z profilu prohlížeče na počítači, kde běží VidDown', 'Read from the browser profile on the computer running VidDown') : S.docker ? T('Exportujte cookies.txt z prohlížeče a nahrajte ho (viz Nápověda)', 'Export cookies.txt from your browser and upload it (see Help)') : T('Pro členský a věkově omezený obsah', 'For members-only and age-restricted content')}</div></div>
      <div class="row gap8 wrap" style="justify-content:flex-end"><span class="seg">${[['none', T('Ne', 'Off')], ['file', 'cookies.txt'], ...(S.docker ? [] : [['browser', T('Z prohlížeče', 'From browser')]])].map(([o, l]) => `<button data-k="cookies_mode" data-t="seg" data-v="${o}" class="${mode === o ? 'on' : ''}">${l}</button>`).join('')}</span>
      ${mode === 'file' ? (cf.exists ? `<span class="badge b-ok">${ic('check', 11)} cookies.txt · ${new Date(cf.mtime * 1000).toLocaleDateString()}</span>` : `<span class="badge b-warn">${T('Soubor nenahrán', 'Not uploaded')}</span>`) + `<label class="btn sm">${T('Nahrát', 'Upload')}<input type="file" id="ckfile" accept=".txt" hidden></label>${cf.exists ? `<button class="ibtn" id="ckdel" title="${T('Smazat', 'Delete')}">${ic('trash', 14)}</button>` : ''}` : ''}
      ${mode === 'browser' ? `<select class="input sm" style="width:120px" data-k="cookies_browser" data-t="text">${['chrome', 'firefox', 'safari', 'edge', 'brave', 'opera', 'chromium', 'vivaldi'].map(b => `<option ${S.values.cookies_browser === b ? 'selected' : ''}>${b}</option>`).join('')}</select>` : ''}</div></div>`; }
    case 'backup': return `<div class="fld"><div class="lab"><div class="b5">${T('Záloha (export)', 'Backup (export)')}</div><div class="hint">${T('Databáze (fronta, historie, odběry, statistiky), nastavení, heslo, token bota, cookies a archiv stažených videí. Soubor .dtb je šifrovaný klíčem aplikace: otevře ho jen VidDown, na jakémkoli stroji, bez hesla.', 'Database (queue, history, subscriptions, statistics), settings, password, bot token, cookies and the downloaded-videos archive. The .dtb file is encrypted with the app key: only VidDown can open it, on any machine, no password.')}</div></div>
      <div class="row gap8 wrap" style="justify-content:flex-end"><label class="row gap4 t2" style="font-size:12.5px"><input type="checkbox" id="bkthumbs"> ${T('s náhledy', 'with thumbnails')}</label><label class="row gap4 t2" style="font-size:12.5px" title="${T('Obyčejný ZIP, otevře se i bez VidDown, ale je čitelný pro každého', 'Plain ZIP, opens without VidDown but readable by anyone')}"><input type="checkbox" id="bkplain"> ${T('bez šifrování (ZIP)', 'unencrypted (ZIP)')}</label><a class="btn sm" id="bkdl" href="/api/backup">${ic('download', 13)} ${T('Stáhnout zálohu', 'Download backup')}</a></div></div>
      <div class="fld"><div class="lab"><div class="b5">${T('Obnova (import)', 'Restore (import)')}</div><div class="hint">${T('Nahradí současná data daty ze zálohy a restartuje aplikaci. Dosavadní stav se uloží do složky restore/ v datové složce.', 'Replaces the current data with the backup and restarts the app. The previous state is kept in the restore/ folder of the data folder.')}</div></div>
      <div class="row gap8" style="justify-content:flex-end"><label class="btn sm">${T('Vybrat zálohu…', 'Choose backup…')}<input type="file" id="rsf" accept=".dtb,.zip" hidden></label></div></div>
      <div id="rsbox"></div>`;
    case 'abstatus': return `<div id="abbox"></div>`;
    case 'catdisk': return `<div id="cdbox"></div>`;
    case 'schedule': return schedHtml();
    case 'schstatus': return `<div class="fld"><div class="lab"><div class="b5">${T('Stav', 'Status')}</div><div class="hint">${T('Místní čas serveru', 'Server local time')}</div></div><div id="schstat" class="col gap8" style="align-items:flex-end;text-align:right"></div></div>`;
    case 'appstatus': return `<div id="apbox"></div>`;
    case 'password': return `<div class="fld"><div class="lab"><div class="b5">${T('Heslo do GUI', 'GUI password')}</div><div class="hint">${S.has_password ? T('Nastaveno – GUI vyžaduje přihlášení', 'Set – the GUI requires sign-in') : T('Nenastaveno – GUI je přístupné bez hesla', 'Not set – the GUI opens without a password')}</div></div>
      <div class="row gap8">${S.has_password ? '<span class="mono t2">••••••••</span>' : ''}<button class="btn sm" id="pwbtn">${S.has_password ? T('Změnit', 'Change') : T('Nastavit', 'Set')}</button></div></div>`;
    case 'tgtoken': { const st = App.st ? App.st.telegram : {};
      return `<div class="fld"><div class="lab"><div class="b5">Bot</div><div class="hint">${S.telegram_token_set ? (st.username ? '@' + esc(st.username) : T('Token uložen', 'Token saved')) : T('Token od @BotFather (viz Nápověda)', 'Token from @BotFather (see Help)')}</div></div>
      <div class="row gap8">${st.state === 'ok' ? '<span class="dot g"></span>' : ''}<button class="btn sm" id="tgbtn">${S.telegram_token_set ? T('Změnit token', 'Change token') : T('Zadat token', 'Set token')}</button>${S.telegram_token_set ? `<button class="btn sm" id="tgtest">${T('Test', 'Test')}</button>` : ''}</div></div>`; }
  }
  return `<div class="fld">${lab()}<div class="row gap8">${ctrl}</div></div>`;
}
function previewName(tpl) {
  const sample = { 'název': T('Islandské fjordy z dronu – 4K', 'Iceland fjords by drone – 4K'), 'title': 'Iceland fjords', 'kanál': 'Nordic Drone Films', 'channel': 'Nordic Drone Films',
    'playlist': T('Cestování', 'Travel'), 'datum': '2026-11-05', 'date': '2026-11-05', 'rozlišení': '2160p', 'resolution': '2160p', 'id': 'dQw4w9WgXcQ', 'pořadí': '001', 'index': '001' };
  return (tpl || '').replace(/\{([^}]+)\}/g, (m, k) => sample[k.toLowerCase()] ?? '').replace(/[<>:"/\\|?*]/g, ' ') || 'video';
}

/* Nastavení: karty jsou ve skupinách (podmenu v bočním panelu a pruh nad kartami na úzké obrazovce) */
const SET_GROUPS = () => [
  { id: 'dl', icon: 'download', title: T('Stahování', 'Downloading'), cards: ['Stahování', 'Rychlost', 'Časový rozvrh', 'Pojmenování a složky'] },
  { id: 'cat', icon: 'film', title: T('Katalog', 'Catalog'), cards: ['Katalog'] },
  { id: 'net', icon: 'send', title: T('Telegram a síť', 'Telegram and network'), cards: ['Telegram', 'Přístup a síť'] },
  { id: 'app', icon: 'palette', title: T('Aplikace', 'Application'), cards: ['Vzhled a jazyk', 'Aktualizace aplikace', 'Enginy'] },
  { id: 'data', icon: 'refresh', title: T('Data', 'Data'), cards: ['Záloha a obnova'] },
  { id: 'adv', icon: 'sliders', title: T('Pokročilé', 'Advanced'), cards: ['Pokročilé'] },
];
function setGroup() {
  const g = SET_GROUPS(), want = App.view === 'settings' ? App.args[0] : null;
  if (want && g.some(x => x.id === want)) { try { localStorage.setItem('vd_set_group', want); } catch (e) { /* bez úložiště */ } return want; }
  try { const v = localStorage.getItem('vd_set_group'); if (g.some(x => x.id === v)) return v; } catch (e) { /* bez úložiště */ }
  return g[0].id;
}
/* Rozdělí karty do dvou sloupců podle skutečné výšky: prvních k karet vlevo, zbytek vpravo (pořadí zůstává i na úzké obrazovce);
   volí se k s nejnižším delším sloupcem. Karty se nejdřív vykreslí do prvního sloupce, aby šly změřit. */
function balanceCols(root) {
  const [a, b] = $$('.scol', root), cards = $$('.sect', a);
  if (cards.length < 2) return;
  const h = cards.map(c => c.offsetHeight + 14);
  let best = 0, bestMax = Infinity;
  for (let k = 1; k <= cards.length; k++) {
    const m = Math.max(h.slice(0, k).reduce((x, y) => x + y, 0), h.slice(k).reduce((x, y) => x + y, 0));
    if (m < bestMax) { bestMax = m; best = k; }
  }
  cards.slice(best).forEach(c => b.appendChild(c));
}
function setMatches(s, q) {
  const text = [L(s.title), ...s.fields.map(f => `${f.label ? L(f.label) : ''} ${f.hint ? L(f.hint) : ''}`)].join(' ').toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(t => text.includes(t));
}

function renderSettings() {
  const S = App.settings; const all = SECTIONS(), groups = SET_GROUPS(), gid = setGroup(), q = (App.setQ || '').trim();
  const grp = groups.find(x => x.id === gid);
  const secs = q ? all.filter(x => setMatches(x, q)) : grp.cards.map(t => all.find(x => x.title[0] === t)).filter(Boolean);
  const groupOf = s => (groups.find(x => x.cards.includes(s.title[0])) || {}).title || '';
  const card = s => `<div class="card sect"><div class="sh">${ic(s.icon, 16)}<h2>${L(s.title)}</h2>${q ? `<span class="t2 fs12" style="margin-left:auto">${esc(groupOf(s))}</span>` : ''}</div>${s.fields.map(f => fieldHtml(f, S)).join('')}</div>`;
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Nastavení', 'Settings')}</h1><div class="t2" style="margin-top:3px">${T('Změny se ukládají automaticky a platí okamžitě', 'Changes save automatically and apply immediately')}</div></div><div class="grow"></div>
   <a class="btn sm" href="/api/settings/export">${ic('download', 13)} ${T('Exportovat', 'Export')}</a><label class="btn sm">${T('Importovat', 'Import')}<input type="file" id="impf" accept=".json" hidden></label>
   <button class="btn sm" id="wizbtn">${ic('sparkle', 13)} ${T('Průvodce nastavením', 'Setup guide')}</button>
   <button class="btn sm" id="restartbtn" title="${T('Řádně ukončí a znovu spustí celou aplikaci', 'Cleanly stops and starts the whole app again')}">${ic('refresh', 13)} ${T('Restartovat aplikaci', 'Restart app')}</button></div>
   <div class="row gap8 wrap" style="margin:12px 0 4px"><div class="inwrap" style="height:32px;width:300px">${ic('search', 14)}<input id="setq" placeholder="${T('Hledat v nastavení…', 'Search settings…')}" value="${esc(App.setQ || '')}" autocomplete="off"><button class="ibtn" id="setqx" type="button" title="${T('Smazat (Esc)', 'Clear (Esc)')}" ${q ? '' : 'hidden'}>${ic('x', 12)}</button></div></div>
   <div class="setgroups">${groups.map(x => `<button class="btn sm ${!q && x.id === gid ? 'primary' : ''}" data-go="settings/${x.id}">${ic(x.icon, 13)} ${x.title}</button>`).join('')}</div>
   ${q && !secs.length ? `<div class="card empty">${ic('search', 28)}<h3>${T('V nastavení nic takového není', 'Nothing like that in the settings')}</h3></div>` : ''}
   <div class="sgrid"><div class="scol">${secs.map(card).join('')}</div><div class="scol"></div></div>`;
  bindSettings($('#main'));
  balanceCols($('#main'));
  const sq = $('#setq');
  const setQuery = v => { App.setQ = v; const keep = sq.selectionStart; renderSettings(); const n = $('#setq'); n.focus(); n.setSelectionRange(keep, keep); };
  sq.oninput = () => { clearTimeout(App.setQt); App.setQt = setTimeout(() => setQuery(sq.value), 200); };
  sq.onkeydown = e => { if (e.key === 'Escape' && sq.value) { sq.value = ''; setQuery(''); } };
  $('#setqx').onclick = () => { App.setQ = ''; renderSettings(); };
  $('#impf').onchange = async e => { const fd = new FormData(); fd.append('file', e.target.files[0]); const r = await act(() => api('/api/settings/import', { method: 'POST', body: fd }), T('Nastavení načteno', 'Settings imported')); if (r) { App.settings = r; renderSettings(); } };
  $('#wizbtn').onclick = openWizard;
  $('#restartbtn').onclick = restartApp;
}

function bindSettings(root, after) {
  const rer = () => (after ? after() : renderSettings());
  $$('[data-t]', root).forEach(el => {
    const k = el.dataset.k, t = el.dataset.t, S = App.settings;
    if (t === 'toggle') el.onclick = () => saveSetting(k, !S.values[k], rer);
    if (t === 'seg') el.onclick = () => saveSetting(k, k === 'methods' ? el.dataset.v.split(',') : el.dataset.v, rer);
    if (t === 'chip') el.onclick = () => { const cur = S.values[k].slice(); const v = typeof cur[0] === 'number' || k === 'schedule_days' ? +el.dataset.v : el.dataset.v;
      const i = cur.indexOf(v); i >= 0 ? cur.splice(i, 1) : cur.push(v); if ((k === 'channel_tabs' || k === 'schedule_scope') && !cur.length) return toast(T('Vyberte aspoň jednu možnost', 'Pick at least one'), true); saveSetting(k, cur, rer); };
    if (t === 'step') el.onclick = () => saveSetting(k, Math.max(1, Math.min(16, S.values[k] + +el.dataset.d)), rer);
    if (t === 'num' || t === 'text') el.onchange = () => saveSetting(k, el.value, rer);
  });
  $$('[data-ins]', root).forEach(b => b.onclick = () => { const inp = $(`input[data-k="${b.dataset.ins}"]`, root); inp.value += b.dataset.v; saveSetting(b.dataset.ins, inp.value, rer); });
  $$('[data-pick]', root).forEach(b => b.onclick = () => openDirPicker(App.settings.values[b.dataset.pick], p => saveSetting(b.dataset.pick, p, rer)));
  const ck = $('#ckfile', root); if (ck) ck.onchange = async e => { const fd = new FormData(); fd.append('file', e.target.files[0]); const r = await act(() => api('/api/settings/cookies', { method: 'POST', body: fd }), T('Cookies nahrány', 'Cookies uploaded')); if (r) { App.settings = r; rer(); } };
  const ckd = $('#ckdel', root); if (ckd) ckd.onclick = async () => { const r = await act(() => api('/api/settings/cookies', { method: 'DELETE' })); if (r) { App.settings = r; rer(); } };
  const bt = $('#bkthumbs', root), bp = $('#bkplain', root);
  const bkHref = () => { $('#bkdl', root).href = `/api/backup?thumbs=${bt.checked ? 1 : 0}&plain=${bp.checked ? 1 : 0}`; };
  if (bt) bt.onchange = bkHref; if (bp) bp.onchange = bkHref;
  const rf = $('#rsf', root); if (rf) rf.onchange = async e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f);
    const r = await act(() => api('/api/restore', { method: 'POST', body: fd }), T('Záloha ověřena', 'Backup verified')); e.target.value = ''; if (r) loadRestore($('#rsbox', root)); };
  const rb = $('#rsbox', root); if (rb) loadRestore(rb);
  const ab = $('#abbox', root); if (ab) loadAutoBackup(ab);
  const cdb = $('#cdbox', root); if (cdb) loadCatDisk(cdb);
  const ap = $('#apbox', root); if (ap) loadAppStatus(ap);
  if ($('#schrules', root)) { bindSchedule(root); renderSchedStatus(); }
  const pw = $('#pwbtn', root); if (pw) pw.onclick = () => openPassword(rer);
  const tg = $('#tgbtn', root); if (tg) tg.onclick = () => openToken(rer);
  const tt = $('#tgtest', root); if (tt) tt.onclick = () => act(() => api('/api/telegram/test', { method: 'POST' }), T('Testovací zpráva odeslána', 'Test message sent'));
}

async function loadCatDisk(box) {
  const d = await api('/api/catalog/disk').catch(() => null); if (!d || !box.isConnected) return;
  const sz = b => (b ? fmtBytes(b) : '0 B');
  box.innerHTML = `<div class="fld"><div class="lab"><div class="b5">${T('Místo na disku', 'Disk space')}</div><div class="hint">${T('Miniatury a animace katalogu (animace jsou jen mezipaměť, do zálohy se nepřidávají a jdou znovu získat tlačítkem Doplnit animace).', 'Catalog thumbnails and animations (animations are only a cache, not included in backups and can be fetched again with Fill in animations).')}</div></div>
    <div class="row gap10 wrap" style="justify-content:flex-end"><span class="t2">${T('Miniatury', 'Thumbnails')}: <b>${sz(d.thumbs.bytes)}</b> (${d.thumbs.count})</span><span class="t2">${T('Animace', 'Animations')}: <b>${sz(d.anims.bytes)}</b> (${d.anims.count})</span>
    <button class="btn sm danger" id="cdanimdel" ${d.anims.count ? '' : 'disabled'}>${ic('trash', 12)} ${T('Smazat animace', 'Delete animations')}</button></div></div>`;
  $('#cdanimdel', box).onclick = async () => {
    const on = App.settings.values.catalog_anim;
    if (!confirm(T(`Smazat ${d.anims.count} animací (${sz(d.anims.bytes)})? Statické miniatury zůstanou.${on ? ' Stahování animací je zapnuté, takže se stáhnou znovu; chcete-li to zabránit, nejdřív ho vypněte.' : ''}`,
      `Delete ${d.anims.count} animations (${sz(d.anims.bytes)})? Static thumbnails stay.${on ? ' Animation downloads are on, so they will be downloaded again; turn them off first to prevent that.' : ''}`))) return;
    const r = await act(() => api('/api/catalog/anim/delete', { method: 'POST' }), T('Animace smazány', 'Animations deleted'));
    if (r) loadCatDisk(box);
  };
}
async function restartApp() {
    if (!confirm(T('Restartovat celou aplikaci? Rozpracovaná stahování se přeruší a po startu začnou znovu od začátku; fronta zůstane zachována.', 'Restart the whole app? Downloads in progress are interrupted and restart from the beginning; the queue is kept.'))) return;
    if (!await act(() => api('/api/restart', { method: 'POST' }))) return;
    await waitForRestart();
  }
async function waitForRestart() {
    document.body.insertAdjacentHTML('beforeend', `<div id="rsov" style="position:fixed;inset:0;z-index:9999;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px"><div class="spin"></div><div>${T('Restartuji aplikaci…', 'Restarting the app…')}</div></div>`);
    if (App.es) App.es.close();
    await new Promise(r => setTimeout(r, 2500));
    for (let i = 0; i < 90; i++) { try { const r = await fetch('/api/state', { cache: 'no-store' }); if (r.ok || r.status === 401) break; } catch (e) { /* server ještě neběží */ } await new Promise(r => setTimeout(r, 1000)); }
    location.reload();
  }
/* ------------------------------------------------------------ katalog */
const CAT_RES = () => [['2160', '2160p'], ['1440', '1440p'], ['1080', '1080p'], ['720', '720p'], ['480', '480p'], ['360', '≤360p'], ['unknown', T('neznámé', 'unknown')]];
const CAT_STATES = () => [['new', T('nové', 'new')], ['queued', T('ve frontě', 'queued')], ['downloaded', T('staženo dříve', 'downloaded before')],
  ['rejected', T('dříve odmítnuté', 'rejected before')], ['gone', T('nedostupné', 'unavailable')]];
const CAT_SORTS = () => [['pos', T('pořadí ve zdroji', 'order in source')], ['source', T('zdroj', 'source')], ['height', T('rozlišení', 'resolution')],
  ['size', T('velikost', 'size')], ['duration', T('délka', 'duration')], ['published', T('datum zveřejnění', 'publication date')], ['added', T('přidáno do katalogu', 'added to catalog')]];
const CAT_AGES = () => [['week', T('týden', 'week')], ['month', T('měsíc', 'month')], ['year', T('rok', 'year')]];
const CAT_WIDTH = { S: 180, M: 280, L: 420 };
const CAT_LIMITS = [25, 50, 100, 200, 500];
function catPref(k, def, allowed) { try { const v = localStorage.getItem('vd_cat_' + k); return v != null && (!allowed || allowed.map(String).includes(v)) ? v : def; } catch (e) { return def; } }
function catSetPref(k, v) { try { localStorage.setItem('vd_cat_' + k, v); } catch (e) { /* bez úložiště */ } }
const CAT = { q: '', source: 0, res: [], state: [], anim: [], age: '', done: new Set(), offset: 0, sel: new Set(), selAll: null, exclude: new Set(), data: null, ov: null, sig: '', seq: 0, qt: null,
  sort: catPref('sort', 'pos', CAT_SORTS().map(x => x[0])), dir: catPref('dir', 'asc', ['asc', 'desc']), limit: +catPref('limit', 100, CAT_LIMITS), thumb: catPref('thumb', 'M', ['S', 'M', 'L']) };

function catFilter() { return { source: CAT.source || null, q: CAT.q, res: CAT.res.slice(), state: CAT.state.slice(), anim: CAT.anim.slice(), age: CAT.age }; }
function catQuery() {
  const p = new URLSearchParams({ sort: CAT.sort, dir: CAT.dir, limit: CAT.limit, offset: CAT.offset });
  if (CAT.source) p.set('source', CAT.source);
  if (CAT.q) p.set('q', CAT.q);
  if (CAT.res.length) p.set('res', CAT.res.join(','));
  if (CAT.state.length) p.set('state', CAT.state.join(','));
  if (CAT.anim.length) p.set('anim', CAT.anim.join(','));
  if (CAT.age) p.set('age', CAT.age);
  return p.toString();
}
const catTotal = () => (CAT.data ? CAT.data.total : 0);
const catSelCount = () => (CAT.selAll ? Math.max(0, catTotal() - CAT.exclude.size) : CAT.sel.size);
const catIsSel = id => (CAT.selAll ? !CAT.exclude.has(id) : CAT.sel.has(id));
function catClearSel() { CAT.sel.clear(); CAT.exclude.clear(); CAT.selAll = null; }

function renderCatalog() {
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Katalog', 'Catalog')}</h1><div class="t2" style="margin-top:3px">${T('Videa ze zdrojů k výběru: nic se nestahuje, dokud se nerozhodnete', 'Videos from your sources to pick from: nothing downloads until you decide')}</div></div>
    <div class="grow"></div><span class="row gap6 fs13" id="catauto"></span><button class="btn" id="cataf" title="${T('Znovu zjistí podrobnosti videí bez animace a zkusí znovu stáhnout ty, které byly nad limitem. Zapněte před tím stahování animací v Nastavení › Katalog.', 'Re-checks videos without an animation and retries those that were over the limit. Turn on animation downloads in Settings › Catalog first.')}">${ic('play', 14)} ${T('Doplnit animace', 'Fill in animations')}</button><button class="btn" id="catdf" title="${T('Znovu zjistí podrobnosti videí, u kterých chybí datum zveřejnění (kvůli řazení podle stáří). Web, který datum nenabízí, se neopakuje.', 'Re-checks videos without a publication date (for sorting by age). Sites that do not offer a date are not retried.')}">${ic('clock', 14)} ${T('Doplnit data', 'Fill in dates')}</button><button class="btn" id="catpause"></button><button class="btn primary lg" id="catadd">${ic('plus', 15)} ${T('Přidat zdroje', 'Add sources')}</button></div>
    <div id="catbanner" class="col gap8"></div><div id="catinfo"></div>
    <div class="catlayout"><aside class="catside" id="catside"><div class="catsidehd">${T('Zdroje', 'Sources')}</div><div id="catsrctools" class="catsrctools"></div><div id="catsrcinfo"></div><div id="catsrc" class="catbadges"></div></aside>
    <div class="catmain"><div class="card cattools"><div class="row gap8 wrap">
      <div class="inwrap" style="height:32px;width:280px">${ic('search', 14)}<input id="catq" placeholder="${T('Hledat v názvu videa a kanálu…', 'Search video and channel names…')}" value="${esc(CAT.q)}" autocomplete="off"><button class="ibtn" id="catqx" type="button" title="${T('Smazat (Esc)', 'Clear (Esc)')}" ${CAT.q ? '' : 'hidden'}>${ic('x', 12)}</button></div>
      <select class="input sm" id="catsrcsel"></select>
      <select class="input sm" id="catsort">${CAT_SORTS().map(([v, l]) => `<option value="${v}" ${CAT.sort === v ? 'selected' : ''}>${T('Řadit', 'Sort')}: ${l}</option>`).join('')}</select>
      <button class="btn sm" id="catdir" title="${T('Směr řazení: ↑ vzestupně (u data od nejstaršího), ↓ sestupně (u data od nejnovějšího)', 'Sort direction: ↑ ascending (oldest first for dates), ↓ descending (newest first for dates)')}">${CAT.dir === 'desc' ? '↓' : '↑'}</button>
      <select class="input sm" id="catlimit">${CAT_LIMITS.map(n => `<option value="${n}" ${CAT.limit === n ? 'selected' : ''}>${T('Na stránku', 'Per page')}: ${n}</option>`).join('')}</select>
      <span class="seg" id="catsize" title="${T('Velikost miniatur', 'Thumbnail size')}">${['S', 'M', 'L'].map(s => `<button data-size="${s}" class="${CAT.thumb === s ? 'on' : ''}">${s}</button>`).join('')}</span></div>
      <div class="row gap6 wrap" style="margin-top:8px"><span class="t2 fs12">${T('Rozlišení', 'Resolution')}:</span><span id="catres" class="row gap4 wrap"></span>
        <span class="t2 fs12" style="margin-left:10px">${T('Stav', 'State')}:</span><span id="catstate" class="row gap4 wrap"></span>
        <span class="t2 fs12" style="margin-left:10px">${T('Animace', 'Animation')}:</span><span id="catanimf" class="row gap4 wrap"></span>
        <span class="t2 fs12" style="margin-left:10px">${T('Zveřejněno za poslední', 'Published in the last')}:</span><span id="catagef" class="row gap4 wrap"></span></div></div>
    <div class="card catsel" id="catsel"></div><div id="catgrid" class="catgrid"></div><div id="catpager" class="row gap8 wrap" style="justify-content:center"></div></div></div><div id="cattip" class="cattip" hidden></div>`;
  const reload = fn => { fn(); CAT.offset = 0; catClearSel(); catLoad(); };
  const q = $('#catq');
  q.oninput = () => { clearTimeout(CAT.qt); $('#catqx').hidden = !q.value; CAT.qt = setTimeout(() => reload(() => { CAT.q = q.value.trim(); }), 280); };
  q.onkeydown = e => { if (e.key === 'Escape' && q.value) { q.value = ''; q.oninput(); } };
  $('#catqx').onclick = () => { q.value = ''; q.oninput(); q.focus(); };
  $('#catsrcsel').onchange = e => reload(() => { CAT.source = +e.target.value; });
  $('#catsort').onchange = e => {
    CAT.sort = e.target.value; catSetPref('sort', CAT.sort);
    if (CAT.sort === 'published' && CAT.dir !== 'desc') { CAT.dir = 'desc'; catSetPref('dir', 'desc'); $('#catdir').textContent = '↓'; }       // datum: nejdřív nejnovější
    reload(() => {});
  };
  $('#catdir').onclick = () => { CAT.dir = CAT.dir === 'asc' ? 'desc' : 'asc'; catSetPref('dir', CAT.dir); $('#catdir').textContent = CAT.dir === 'desc' ? '↓' : '↑'; reload(() => {}); };
  $('#catlimit').onchange = e => { CAT.limit = +e.target.value; catSetPref('limit', CAT.limit); reload(() => {}); };
  $$('#catsize [data-size]').forEach(b => b.onclick = () => { CAT.thumb = b.dataset.size; catSetPref('thumb', CAT.thumb); $$('#catsize [data-size]').forEach(x => x.classList.toggle('on', x === b)); catPaintGrid(); });
  $('#catres').onclick = e => { const b = e.target.closest('[data-res]'); if (b) reload(() => { const v = b.dataset.res, i = CAT.res.indexOf(v); i >= 0 ? CAT.res.splice(i, 1) : CAT.res.push(v); }); };
  $('#catagef').onclick = e => { const b = e.target.closest('[data-age]'); if (b) reload(() => { CAT.age = CAT.age === b.dataset.age ? '' : b.dataset.age; }); };
  $('#catanimf').onclick = e => { const b = e.target.closest('[data-an]'); if (b) reload(() => { const v = b.dataset.an, i = CAT.anim.indexOf(v); i >= 0 ? CAT.anim.splice(i, 1) : CAT.anim.push(v); }); };
  $('#catstate').onclick = e => { const b = e.target.closest('[data-st]'); if (b) reload(() => { const v = b.dataset.st, i = CAT.state.indexOf(v); i >= 0 ? CAT.state.splice(i, 1) : CAT.state.push(v); }); };
  $('#catadd').onclick = openCatAdd;
  $('#cataf').onclick = async () => {
    if (!App.settings.values.catalog_anim) return toast(T('Nejdřív zapněte stahování animací v Nastavení › Katalog', 'First turn on animation downloads in Settings › Catalog'), true);
    const r = await act(() => api('/api/catalog/anim/refill', { method: 'POST', body: CAT.source ? { source: CAT.source } : {} }));
    if (!r) return;
    CAT.ov = r.overview; catPaintSources();
    toast(r.details || r.retry || r.pages ? T(`Doplňuji animace: znovu zjistím ${r.details} videí, další pokus u ${r.retry}, stránky videí znovu u ${r.pages}`, `Filling in animations: re-checking ${r.details} videos, retrying ${r.retry}, video pages again for ${r.pages}`) : T('Není co doplnit', 'Nothing to fill in'));
  };
  $('#catdf').onclick = async () => {
    const r = await act(() => api('/api/catalog/dates/refill', { method: 'POST', body: CAT.source ? { source: CAT.source } : {} }));
    if (!r) return;
    CAT.ov = r.overview; catPaintSources();
    toast(r.details ? T(`Doplňuji data: znovu zjistím ${r.details} videí`, `Filling in dates: re-checking ${r.details} videos`) : T('Není co doplnit', 'Nothing to fill in'));
  };
  catPaintAuto();
  $('#catpause').onclick = async () => { const paused = CAT.ov && CAT.ov.details.paused; const r = await act(() => api('/api/catalog/pause', { method: 'POST', body: { paused: !paused } })); if (r) { CAT.ov = r; catPaintSources(); } };
  $('#catside').onclick = catSrcClick;
  $('#catsrc').onmouseover = catTipShow; $('#catsrc').onmouseout = catTipHide; $('#catsrc').onfocusin = catTipShow; $('#catsrc').onfocusout = catTipHide;
  $('#catgrid').onclick = catGridClick;
  catAnimTrack();
  $('#catgrid').onmouseover = catAnimHover; $('#catgrid').onmouseout = catAnimHover;
  $('#catgrid').onchange = e => { const c = e.target.closest('[data-csel]'); if (c) catToggle(+c.dataset.csel, c.checked); };
  $('#catsel').onclick = catSelClick;
  $('#catpager').onclick = e => { const b = e.target.closest('[data-page]'); if (b && !b.disabled) { CAT.offset = (+b.dataset.page - 1) * CAT.limit; catLoad(); $('#mainwrap').scrollTop = 0; } };
  catPaintTools(); catPaintBanner();
  catLoad();
  App.timer = setInterval(catPoll, 3000);
}
const CAT_AUTO_HOURS = [6, 12, 24, 72, 168];
function catPaintAuto() {
  const box = $('#catauto'); if (!box) return;
  const v = App.settings.values || {}, on = !!v.catalog_auto, h = v.catalog_auto_hours || 24;
  box.innerHTML = `<label class="row gap6" title="${T('Zdroje se samy po zvolené době znovu prohlédnou a nabídnou jen dosud nenabídnutá videa. Řídí se časovým rozvrhem.', 'Sources are re-checked on their own after the chosen time and offer only videos not offered yet. Follows the schedule.')}"><input type="checkbox" id="catautoon" ${on ? 'checked' : ''}> ${T('Hledat nová videa automaticky', 'Look for new videos automatically')}</label>
    <select class="input sm" id="catautoh" style="width:auto" ${on ? '' : 'disabled'}>${CAT_AUTO_HOURS.map(x => `<option value="${x}" ${x === h ? 'selected' : ''}>${x < 72 ? T(`každých ${x} h`, `every ${x} h`) : x === 72 ? T('každé 3 dny', 'every 3 days') : T('každý týden', 'every week')}</option>`).join('')}</select>`;
  const save = async body => { const r = await act(() => api('/api/settings', { method: 'PUT', body })); if (r) { App.settings = r; catPaintAuto(); } else catPaintAuto(); };
  $('#catautoon').onchange = e => save({ catalog_auto: e.target.checked });
  $('#catautoh').onchange = e => save({ catalog_auto_hours: +e.target.value });
}
async function catLoad() {
  const seq = ++CAT.seq;
  try {
    const [ov, data] = await Promise.all([api('/api/catalog'), api('/api/catalog/items?' + catQuery())]);
    if (seq !== CAT.seq || App.view !== 'catalog') return;
    CAT.ov = ov; CAT.data = data; CAT.sig = JSON.stringify(data);
    if (data.total && !data.items.length && CAT.offset > 0) { CAT.offset = Math.max(0, (Math.ceil(data.total / CAT.limit) - 1) * CAT.limit); return catLoad(); }
    catPaintAll(); catDonePrompt();
  } catch (e) { if (e.message !== 'auth') toast(e.message, true); }
}
async function catPoll() {
  if (App.view !== 'catalog' || document.hidden || CAT.busy) return;
  const seq = CAT.seq;
  try {
    const [ov, data] = await Promise.all([api('/api/catalog'), api('/api/catalog/items?' + catQuery())]);
    if (seq !== CAT.seq || App.view !== 'catalog') return;
    CAT.ov = ov; catPaintSources(); catPaintTools(); catDonePrompt();
    const sig = JSON.stringify(data);
    if (sig !== CAT.sig) { CAT.sig = sig; CAT.data = data; catPaintGrid(); catPaintSel(); catPaintPager(); }
  } catch (e) { /* další průchod to zkusí znovu */ }
}
function catPaintAll() { catPaintSources(); catPaintTools(); catPaintGrid(); catPaintSel(); catPaintPager(); }
function catPaintBanner() {
  const b = $('#catbanner'); if (b) b.innerHTML = scheduleBanner(App.st, 'catalog', T('Zjišťování katalogu čeká na časové okno.', 'Catalog scanning is waiting for the time window.'));
}
function catPaintTools() {
  const ov = CAT.ov; if (!$('#catres')) return;
  $('#catres').innerHTML = CAT_RES().map(([v, l]) => `<button class="chip ${CAT.res.includes(v) ? 'on' : ''}" data-res="${v}">${l}</button>`).join('');
  $('#catagef').innerHTML = CAT_AGES().map(([v, l]) => `<button class="chip ${CAT.age === v ? 'on' : ''}" data-age="${v}">${l}</button>`).join('');
  $('#catanimf').innerHTML = [['yes', T('s animací', 'with animation')], ['no', T('bez animace', 'without animation')]].map(([v, l]) => `<button class="chip ${CAT.anim.includes(v) ? 'on' : ''}" data-an="${v}">${l}</button>`).join('');
  $('#catstate').innerHTML = CAT_STATES().map(([v, l]) => `<button class="chip ${CAT.state.includes(v) ? 'on' : ''}" data-st="${v}">${l}</button>`).join('');
  const sel = $('#catsrcsel');
  const opts = `<option value="0">${T('Všechny zdroje', 'All sources')}</option>` + (ov ? ov.sources.map(s => `<option value="${s.id}" ${CAT.source === s.id ? 'selected' : ''}>${esc(s.title || s.url)}</option>`).join('') + (ov.detached || []).map(s => `<option value="${s.id}" ${CAT.source === s.id ? 'selected' : ''}>${esc(s.title)} (${T('odebraný zdroj', 'removed source')})</option>`).join('') : '');
  if (sel.dataset.sig !== opts) { sel.dataset.sig = opts; sel.innerHTML = opts; }
  const p = $('#catpause'); if (p && ov) p.innerHTML = ov.details.paused ? `${ic('play', 14)} ${T('Pokračovat ve zjišťování', 'Resume scanning')}` : `${ic('pause', 14)} ${T('Pozastavit zjišťování', 'Pause scanning')}`;
}
const CAT_ROUND_FROM = 16;                                                  // od tolika zdrojů se odznáčky zmenší na kulaté
const catStatusDot = s => (s.status === 'error' ? 'r' : s.status === 'queued' || s.status === 'scanning' ? 'y' : 'g');
function catBadge(s, round) {
  const name = s.title || s.url, initial = ([...name.replace(/^https?:\/\/(www\.)?/, '')][0] || '?').toUpperCase();
  const hue = Math.round((([...name].reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7) >>> 0) % 997) * 137.508) % 360;      // zlatý úhel: i podobné názvy dostanou různé barvy
  return `<button type="button" class="srcb ${round ? 'round' : ''} ${CAT.source === s.id ? 'on' : ''}" data-csrc="${s.id}" ${round ? `style="--hue:${hue}"` : ''} aria-label="${esc(name)}">
    <span class="dot ${catStatusDot(s)}"></span>${round ? `<span class="srcl">${esc(initial)}</span>` : `<span class="ell grow">${esc(name)}</span><span class="srcn">${s.items}</span>`}</button>`;
}
function catSourceDetail(s) {
  const st = { queued: T('čeká ve frontě', 'waiting'), scanning: T('zjišťuje se…', 'scanning…'), error: T('chyba', 'error'), done: '' }[s.status] || '';
  const kind = { channel: T('kanál', 'channel'), playlist: 'playlist', video: T('video', 'video'), page: T('stránka', 'page') }[s.kind] || '';
  const pct = s.items ? Math.round(100 * s.details_done / s.items) : 0;
  const when = s.last_scan ? new Date(s.last_scan * 1000).toLocaleString(LANG === 'cs' ? 'cs-CZ' : 'en-GB') : '—';
  return `<div class="row gap6"><b class="ell grow">${esc(s.title || s.url)}</b>${st ? `<span class="badge ${s.status === 'error' ? 'b-err' : 'b-warn'}">${st}</span>` : ''}</div>
    <div class="fs12 t2 ell" title="${esc(s.url)}">${esc(s.url)}</div>
    <div class="fs12 t2">${kind ? kind + ' · ' : ''}${s.items} ${T('videí', 'videos')}${s.queued ? ` · ${s.queued}× ${T('ve frontě', 'queued')}` : ''}${s.downloaded_before ? ` · ${s.downloaded_before}× ${T('staženo dříve', 'downloaded before')}` : ''}${s.rejected_before ? ` · ${s.rejected_before}× ${T('dříve odmítnuto', 'rejected before')}` : ''}${s.gone ? ` · ${s.gone}× ${T('nedostupné', 'unavailable')}` : ''}</div>
    ${s.items ? `<div class="fs12 t2">${T('Podrobnosti', 'Details')} ${s.details_done}/${s.items}</div><div class="pbar"><i style="width:${pct}%"></i></div>` : ''}
    <div class="fs12 t2">${T('Naposledy zjištěno', 'Last scanned')}: ${when}</div>${s.error ? `<div class="fs12" style="color:var(--err)">${esc(s.error)}</div>` : ''}`;
}
function catTipShow(e) {
  const b = e.target.closest && e.target.closest('.srcb'); const tip = $('#cattip'); if (!b || !tip || !CAT.ov) return;
  const s = CAT.ov.sources.find(x => x.id === +b.dataset.csrc); if (!s) return;
  tip.innerHTML = catSourceDetail(s); tip.hidden = false;
  const r = b.getBoundingClientRect(), h = tip.offsetHeight, w = tip.offsetWidth;
  const left = r.right + 10 + w < innerWidth ? r.right + 10 : Math.max(8, r.left - w - 10);
  tip.style.left = left + 'px'; tip.style.top = Math.max(8, Math.min(r.top, innerHeight - h - 8)) + 'px';
}
function catTipHide() { const tip = $('#cattip'); if (tip) tip.hidden = true; }
function catPaintSrcTools() {
  const box = $('#catsrctools'), ov = CAT.ov; if (!box || !ov) return;
  const sel = ov.sources.find(x => x.id === CAT.source), none = !sel;
  box.innerHTML = `<button class="btn sm" data-csa="${none ? 'refreshall:0' : 'refresh:' + sel.id}" ${ov.sources.length ? '' : 'disabled'} title="${none ? T('Najde nová videa ve všech zdrojích', 'Finds new videos in all sources') : T('Najde jen nová videa ve zvoleném zdroji', 'Finds only new videos in the selected source')}">${ic('refresh', 12)} ${none ? T('Obnovit všechny', 'Refresh all') : T('Obnovit', 'Refresh')}</button>
    <button class="btn sm" data-csa="reload:${sel ? sel.id : 0}" ${none ? 'disabled' : ''} title="${T('Nabídne znovu i odmítnutá a stažená videa zvoleného zdroje', 'Offers rejected and downloaded videos of the selected source again')}">${T('Načíst znovu vše', 'Reload all')}</button>
    <button class="btn sm" data-csa="del:${sel ? sel.id : 0}" ${none ? 'disabled' : ''} title="${T('Odebere zvolený zdroj', 'Removes the selected source')}">${ic('trash', 12)} ${T('Odebrat', 'Remove')}</button>`;
  $('#catsrcinfo').innerHTML = sel ? `<div class="catsrcsel">${catSourceDetail(sel)}</div>` : '';
}
function catPaintSources() {
  const box = $('#catsrc'), ov = CAT.ov; if (!box || !ov) return;
  const d = ov.details;
  const round = ov.sources.length >= CAT_ROUND_FROM;
  box.classList.toggle('rounds', round);
  box.innerHTML = ov.sources.map(x => catBadge(x, round)).join('') || `<div class="t2 fs13" style="padding:6px 2px">${T('Zatím žádný zdroj. Přidejte kanály, playlisty nebo stránky tlačítkem Přidat zdroje.', 'No sources yet. Add channels, playlists or pages with the Add sources button.')}</div>`;
  catPaintSrcTools();
  const bits = [];
  if (d.paused) bits.push(`<span class="badge b-warn">${T('pozastaveno', 'paused')}</span>`);
  else if (d.waiting_for_lists) bits.push(`<span class="t2">${T('Nejdřív se dokončí seznamy všech zdrojů…', 'Finishing the lists of all sources first…')}</span>`);
  if (d.slow) bits.push(`<span class="t2" title="${T('Weby, které yt-dlp nezná: podrobnosti se zjišťují prohlížečem až po rychlé práci, po jednom videu.', 'Sites yt-dlp does not know: details are checked with the browser after the fast work, one video at a time.')}">${T('Pomalé (prohlížečem)', 'Slow (browser)')}: ${T('čeká', 'waiting')} ${d.slow}</span>`);
  if (d.pending || d.done || d.failed) bits.push(`<span class="t2">${T('Podrobnosti', 'Details')}: ${T('hotovo', 'done')} ${d.done} · ${T('čeká', 'waiting')} ${d.pending}${d.failed ? ` · ${T('chyb', 'failed')} ${d.failed}` : ''}</span>`);
  if (App.settings.values.catalog_anim && (d.anim_pending || d.anim_have || d.anim_failed || d.anim_scan)) bits.push(`<span class="t2" title="${T('Animace, které web nabízí; stahují se po miniaturách', 'Animations the site offers; downloaded after the thumbnails')}">${T('Animace', 'Animations')}: ${T('staženo', 'downloaded')} ${d.anim_have}${d.anim_pending ? ` · ${T('čeká', 'waiting')} ${d.anim_pending}` : ''}${d.anim_scan && App.settings.values.catalog_anim_pages ? ` · ${T('hledám na stránkách videí', 'searching video pages')} ${d.anim_scan}` : ''}${d.anim_failed ? ` · ${T('nad limit nebo nedostupné', 'over the limit or unavailable')} ${d.anim_failed}` : ''}</span>`);
  if (d.thumbs_pending) bits.push(`<span class="t2">${T('Miniatury', 'Thumbnails')}: ${T('čeká', 'waiting')} ${d.thumbs_pending}</span>`);
  (d.backoff || []).forEach(b => bits.push(`<span class="badge b-warn" title="${esc(b.reason)}">${esc(b.host)}: ${T('odloženo o', 'delayed by')} ${Math.max(1, Math.round(b.seconds / 60))} min</span>`));
  if (d.thumbs_failed) bits.push(`<span class="badge b-warn" title="${T('Web miniaturu neposlal (často chybí oprávnění nebo ji dočasně odmítl). Tlačítko vpravo zkusí načíst chybějící znovu.', 'The site did not send the thumbnail. The button on the right tries the missing ones again.')}">${T('Miniatury nenačteny', 'Thumbnails missing')}: ${d.thumbs_failed}</span>`);
  if (d.failed || d.thumbs_failed) bits.push(`<button class="btn sm" data-csa="retry:0" title="${T('Znovu zjistí podrobnosti a načte miniatury u videí, kterým se to nepodařilo', 'Retries details and thumbnails for videos where it failed')}">${ic('refresh', 12)} ${T('Zkusit znovu neúspěšné', 'Retry failed')}${d.failed || d.thumbs_failed ? ` (${(d.failed || 0) + (d.thumbs_failed || 0)})` : ''}</button>`);
  $('#catinfo').innerHTML = bits.length ? `<div class="row gap10 wrap fs12" style="padding:2px 4px">${bits.join('')}</div>` : '';
  $('#catinfo').onclick = catSrcClick;
}
/* Vyřízený zdroj (nezbylo v něm žádné video k vybrání ani ve frontě): zeptá se, jestli ho odebrat, nebo ponechat pro budoucí videa */
function catDonePrompt() {
  if (App.view !== 'catalog' || CAT.busy || $('#modal-root .overlay') || !CAT.ov) return;
  const src = CAT.ov.sources.find(x => x.exhausted && !CAT.done.has(x.id)); if (!src) return;
  CAT.done.add(src.id);                                                                  // v této relaci se na zdroj zeptá jen jednou
  const m = modal(`<div class="mh">${ic('check', 18)}<h2>${T('Zdroj je zpracován', 'Source finished')}</h2></div>
    <div class="mb col gap10"><div class="fs13"><b>${esc(src.title || src.url)}</b></div>
      <div class="fs13">${T('Ve zdroji už nezbývá žádné video k výběru ani ve frontě stahování. Má se zdroj odebrat, nebo ho ponechat a dál z něj získávat budoucí videa?', 'No video is left to choose from or waiting in the download queue. Remove the source, or keep it to get future videos?')}</div></div>
    <div class="mf"><button class="btn danger" id="catdone-rm">${T('Odebrat zdroj…', 'Remove source…')}</button><button class="btn primary" id="catdone-keep">${T('Ponechat zdroj', 'Keep the source')}</button></div>`);
  $('#catdone-keep', m.el).onclick = async () => { m.close(); const r = await act(() => api(`/api/catalog/sources/${src.id}/keep`, { method: 'POST' }), T('Zdroj zůstává, nová videa se budou přidávat', 'Source kept, new videos will be added')); if (r) { CAT.ov = r; catPaintSources(); } };
  $('#catdone-rm', m.el).onclick = () => { m.close(); catRemoveDialog(src.id); };
}
function catRemoveDialog(sid) {
  const src = CAT.ov && CAT.ov.sources.find(x => x.id === sid); if (!src) return;
  const m = modal(`<div class="mh">${ic('trash', 18)}<h2>${T('Odebrat zdroj', 'Remove source')}</h2></div>
    <div class="mb col gap10"><div class="fs13"><b>${esc(src.title || src.url)}</b> · ${src.items} ${T('videí', 'videos')}</div>
      <div class="fs13 t2">${T('Fronta stahování i už stažená videa se nezmění v žádném případě.', 'The download queue and already downloaded videos are not affected either way.')}</div>
      <button class="btn" id="catdkeep" style="justify-content:flex-start;text-align:left;height:auto;padding:10px 12px"><span class="col gap4"><b>${T('Odebrat jen zdroj', 'Remove the source only')}</b><span class="t2 fs12" style="font-weight:400">${T('Videa z něj zůstanou v katalogu (ve filtru Zdroj jako „odebraný zdroj“). Zdroj se přestane zjišťovat; znovupřidání stejné adresy ho připojí zpět.', 'Its videos stay in the catalog (in the Source filter as “removed source”). The source stops being scanned; adding the same address again reconnects it.')}</span></span></button>
      <button class="btn danger" id="catdall" style="justify-content:flex-start;text-align:left;height:auto;padding:10px 12px"><span class="col gap4"><b>${T('Odebrat zdroj i jeho videa z katalogu', 'Remove the source and its videos from the catalog')}</b><span class="t2 fs12" style="font-weight:400">${T('Smaže se i paměť o odmítnutých a stažených videích z tohoto zdroje a jejich miniatury a animace.', 'The memory of rejected and downloaded videos from this source and their thumbnails and animations are deleted too.')}</span></span></button></div>
    <div class="mf"><button class="btn" id="catdno">${T('Zrušit', 'Cancel')}</button></div>`);
  const go = async keep => {
    m.close();
    const r = await act(() => api(`/api/catalog/sources/${sid}?keep_items=${keep ? 1 : 0}`, { method: 'DELETE' }), keep ? T('Zdroj odebrán, videa zůstala v katalogu', 'Source removed, videos kept in the catalog') : T('Zdroj i jeho videa odebrány', 'Source and its videos removed'));
    if (r) { CAT.source = 0; $('#catsrcsel').value = '0'; catClearSel(); catLoad(); }
  };
  $('#catdkeep', m.el).onclick = () => go(true); $('#catdall', m.el).onclick = () => go(false); $('#catdno', m.el).onclick = m.close;
}
async function catSrcClick(e) {
  const a = e.target.closest('[data-csa]');
  if (a) {
    e.stopPropagation();
    if (a.disabled) return;
    const [what, id] = a.dataset.csa.split(':'), sid = +id;
    if (what === 'del') return catRemoveDialog(sid);
    if (what === 'reload' && !confirm(T('Načíst zdroj znovu celý? Znovu se nabídnou i dříve odmítnutá a stažená videa (s odznaky).', 'Reload the whole source? Rejected and downloaded videos are offered again (with badges).'))) return;
    const call = { refresh: () => api(`/api/catalog/sources/${sid}/refresh`, { method: 'POST' }), reload: () => api(`/api/catalog/sources/${sid}/reload`, { method: 'POST' }),
      refreshall: () => api('/api/catalog/sources/refresh', { method: 'POST' }), retry: () => api('/api/catalog/retry', { method: 'POST', body: {} }) }[what];
    const r = await act(call, { refresh: T('Zdroj je ve frontě zjišťování', 'Source queued'), reload: T('Zdroj se načte znovu', 'Source will be reloaded'),
      refreshall: T('Všechny zdroje jsou ve frontě zjišťování', 'All sources queued'), retry: T('Zařazeno znovu', 'Queued again') }[what]);
    if (r) { catClearSel(); catLoad(); }
    return;
  }
  const c = e.target.closest('[data-csrc]');
  if (c) { const id = +c.dataset.csrc; CAT.source = CAT.source === id ? 0 : id; CAT.offset = 0; catClearSel(); $('#catsrcsel').value = String(CAT.source); catTipHide(); catLoad(); }
}
function catCard(it) {
  const sel = catIsSel(it.id), h = it.height ? `${it.height}p` : '';
  const badges = [it.state === 'queued' ? `<span class="vbd q">${T('ve frontě', 'queued')}</span>` : '', it.downloaded_before ? `<span class="vbd d">${T('Staženo dříve', 'Downloaded before')}</span>` : '',
    it.rejected_before ? `<span class="vbd r">${T('Dříve odmítnuté', 'Rejected before')}</span>` : '', it.state === 'gone' ? `<span class="vbd g">${T('Nedostupné', 'Unavailable')}</span>` : '',
    it.download_error ? `<span class="vbd g" title="${esc(it.download_error)}">${T('stahování selhalo', 'download failed')}</span>` : '',
    it.detail_state === 'failed' && it.state !== 'gone' ? `<span class="vbd g" title="${esc(it.detail_error || '')}">${T('podrobnosti nezjištěny', 'details unavailable')}</span>` : ''].join('');
  const meta = it.size ? fmtBytes(it.size) : (it.detail_state === 'pending' ? T('zjišťuji…', 'checking…') : '—');
  return `<div class="vcard ${sel ? 'on' : ''}" data-cid="${it.id}"><div class="vth ${it.anim ? 'has-anim' : ''}">${it.thumb ? `<img loading="lazy" src="${esc(it.thumb)}" alt="" onerror="this.remove()">` : ''}<div class="vph">${ic('film', 28)}</div>
    ${it.anim ? (it.anim_kind === 'video' ? `<video class="vanim" muted loop playsinline preload="none" data-asrc="${esc(it.anim)}"></video>` : `<img class="vanim" alt="" data-asrc="${esc(it.anim)}">`) : ''}
    ${it.anim ? `<span class="vb3" title="${T('Najetím myší (na dotyku klepnutím) se přehraje animace', 'Hover (tap on touch screens) to play the animation')}">${ic('play', 10)} ${T('animace', 'animation')}</span>` : ''}
    ${h ? `<span class="vb1">${h}</span>` : ''}<label class="vck"><input type="checkbox" data-csel="${it.id}" ${sel ? 'checked' : ''}></label>${it.duration ? `<span class="vb2">${fmtDur(it.duration)}</span>` : ''}</div>
    <div class="vt"><a href="${esc(it.url)}" target="_blank" rel="noopener" title="${esc(it.title || it.url)}">${esc(it.title || it.url)}</a></div>
    <div class="vm ell" title="${esc(it.source_title || '')}">${esc(it.source_title || '')}${it.channel && it.channel !== it.source_title ? ' · ' + esc(it.channel) : ''}</div>
    <div class="vm2"><span>${meta}</span>${it.published ? `<span class="t2" title="${T('Datum zveřejnění videa', 'Video publication date')}">${fmtPub(it.published)}</span>` : ''}${badges}</div>
    <div class="vact"><a class="btn sm ib" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer" data-cact="open" title="${T('Otevřít stránku videa na webu', 'Open the video page on the site')}">${ic('external', 14)}</a>
      <button class="btn sm ib" data-cact="copy" data-url="${esc(it.url)}" title="${T('Zkopírovat adresu stránky videa', 'Copy the video page address')}">${ic('copy', 14)}</button>
      <button class="btn sm primary" data-cact="download" data-id="${it.id}" data-dl="${it.downloaded_before ? 1 : 0}" ${it.state === 'new' ? '' : 'disabled'}>${ic('download', 13)} ${T('Stáhnout', 'Download')}</button>
      <button class="btn sm" data-cact="remove" data-id="${it.id}" ${it.state === 'queued' ? 'disabled' : ''} title="${T('Odstranit z katalogu', 'Remove from the catalog')}">${ic('trash', 13)} ${T('Odstranit', 'Remove')}</button></div></div>`;
}
function catPaintGrid() {
  const g = $('#catgrid'), d = CAT.data; if (!g || !d) return;
  g.style.setProperty('--cw', CAT_WIDTH[CAT.thumb] + 'px');
  morphHtml(g, d.items.length ? d.items.map(catCard).join('')
    : `<div class="card empty" style="grid-column:1/-1">${ic('search', 28)}<h3>${CAT.ov && CAT.ov.items ? T('Nic nevyhovuje filtru', 'Nothing matches the filter') : T('Zatím tu nejsou žádná videa', 'No videos yet')}</h3></div>`);
  catAnimSync();
}
function catPaintSel() {
  const box = $('#catsel'), d = CAT.data; if (!box || !d) return;
  const n = catSelCount(), shown = d.items.length;
  box.innerHTML = `<div class="row gap8 wrap"><button class="btn sm" data-cs="page">${ic('check', 13)} ${T('Vybrat zobrazené', 'Select shown')} (${shown})</button>
    ${d.total > shown ? `<button class="btn sm" data-cs="all">${T('Vybrat všech vyhovujících', 'Select all matching')} (${d.total})</button>` : ''}
    <button class="btn sm ghost" data-cs="none" ${n ? '' : 'disabled'}>${T('Zrušit výběr', 'Clear selection')}</button>
    <span class="t2 fs12">${T('Vybráno', 'Selected')}: <b>${n}</b> · ${T('Zobrazeno', 'Showing')} ${d.total ? CAT.offset + 1 : 0}–${CAT.offset + shown} ${T('z', 'of')} ${d.total}</span><span class="grow"></span>
    <button class="btn sm primary" data-cs="download" ${n ? '' : 'disabled'}>${ic('download', 13)} ${T('Stáhnout vybrané', 'Download selected')}</button>
    <button class="btn sm" data-cs="remove" ${n ? '' : 'disabled'}>${ic('trash', 13)} ${T('Odstranit vybrané', 'Remove selected')}</button></div>`;
}
function catPaintPager() {
  const box = $('#catpager'), d = CAT.data; if (!box || !d) return;
  const pages = Math.max(1, Math.ceil(d.total / CAT.limit)), cur = Math.floor(CAT.offset / CAT.limit) + 1;
  if (pages < 2) { box.innerHTML = ''; return; }
  const nums = [...new Set([1, 2, cur - 1, cur, cur + 1, pages - 1, pages].filter(p => p >= 1 && p <= pages))].sort((a, b) => a - b);
  let html = `<button class="btn sm" data-page="${cur - 1}" ${cur < 2 ? 'disabled' : ''}>‹</button>`, last = 0;
  for (const p of nums) { if (p - last > 1) html += '<span class="t2">…</span>'; html += `<button class="btn sm ${p === cur ? 'primary' : ''}" data-page="${p}">${p}</button>`; last = p; }
  box.innerHTML = html + `<button class="btn sm" data-page="${cur + 1}" ${cur >= pages ? 'disabled' : ''}>›</button>`;
}
function catToggle(id, on) {
  if (CAT.selAll) { on ? CAT.exclude.delete(id) : CAT.exclude.add(id); } else { on ? CAT.sel.add(id) : CAT.sel.delete(id); }
  const card = $(`[data-cid="${id}"]`); if (card) card.classList.toggle('on', on);
  catPaintSel();
}
async function catDownload(spec, force) {
  if (CAT.busy) return;
  CAT.busy = true;
  const r = await act(() => api('/api/catalog/items/action', { method: 'POST', body: { action: 'download', ...spec, ...(force ? { force: true } : {}) } }));
  CAT.busy = false;
  if (!r) return;
  const parts = [];
  if (r.queued) parts.push(T(`do fronty přidáno ${r.queued}`, `queued ${r.queued}`));
  if (r.linked) parts.push(T(`už ve frontě ${r.linked}`, `already in the queue ${r.linked}`));
  if (r.skipped_downloaded) parts.push(T(`přeskočeno „staženo dříve“ ${r.skipped_downloaded}`, `skipped “downloaded before” ${r.skipped_downloaded}`));
  if (r.skipped_state) parts.push(T(`přeskočeno ${r.skipped_state} (ve frontě nebo odstraněno)`, `skipped ${r.skipped_state} (queued or removed)`));
  toast(parts.join(', ') || T('Nic k zařazení', 'Nothing to queue'));
  catClearSel(); catLoad();
}
function catDownloadAsk(spec, n) {
  const m = modal(`<div class="mh">${ic('download', 18)}<h2>${T('Stáhnout z katalogu', 'Download from the catalog')}</h2></div>
    <div class="mb"><div class="fs13">${T(`Zařadit do fronty ${n} videí. Každé se uloží do složky podle názvu svého zdroje a po úspěšném stažení zmizí z katalogu.`, `Queue ${n} videos. Each is saved in a folder named after its source and disappears from the catalog after a successful download.`)}</div>
      <label class="row gap8 fs13" style="margin-top:10px"><input type="checkbox" id="catforce"> ${T('I videa označená „Staženo dříve“ stáhnout znovu', 'Also download videos marked “Downloaded before” again')}</label></div>
    <div class="mf"><button class="btn" id="catdlno">${T('Zrušit', 'Cancel')}</button><button class="btn primary" id="catdlgo">${T('Zařadit do fronty', 'Add to queue')}</button></div>`);
  $('#catdlno', m.el).onclick = m.close;
  $('#catdlgo', m.el).onclick = () => { const f = $('#catforce', m.el).checked; m.close(); catDownload(spec, f); };
}
async function catRemove(spec, count) {
  if (CAT.busy) return;
  CAT.busy = true;
  const r = await act(() => api('/api/catalog/items/action', { method: 'POST', body: { action: 'remove', ...spec } }),
    count > 1 ? T(`Odstraněno: ${count}`, `Removed: ${count}`) : null);
  CAT.busy = false;
  if (r) { if (r.skipped) toast(T(`Přeskočeno ${r.skipped} (ve frontě nebo už odstraněno)`, `Skipped ${r.skipped} (queued or already removed)`)); catClearSel(); catLoad(); }
}
/* Animace v kartě: načte se a přehraje až při najetí myší na kartu (dotyk: klepnutí na náhled), jinak se nic nestahuje ani nepřehrává */
function catAnimOn(th, on) {
  const el = $('.vanim', th); if (!el) return;
  if (on) {
    th.dataset.want = '1';
    // animace překryje miniaturu až když skutečně hraje / se načetla; při chybě (nepodporovaný formát) zůstane miniatura
    const video = el.tagName === 'VIDEO', ev = video ? 'playing' : 'load';
    const shown = () => { if (th.dataset.want === '1') th.classList.add('anim-on'); };
    el.addEventListener(ev, shown, { once: true });
    el.addEventListener('error', () => { th.classList.remove('anim-on'); }, { once: true });
    if (el.getAttribute('src') !== el.dataset.asrc) el.src = el.dataset.asrc;            // i když si karta po překreslení nechala cizí zdroj
    if (video) { const p = el.play(); if (p && p.catch) p.catch(() => {}); if (!el.paused && el.readyState >= 3) shown(); }
    else if (el.complete && el.naturalWidth) shown();
  } else {
    th.dataset.want = '0';
    th.classList.remove('anim-on');
    if (el.tagName === 'VIDEO') el.pause(); else el.removeAttribute('src');            // obrázek: odpojením se animace zastaví a uvolní paměť
  }
}
/* Po překreslení mřížky (odstranění videa, nové pořadí, obnova) se pod nehybným kurzorem objeví jiná karta a prohlížeč o tom neposílá
   žádnou událost myši: stav animací se proto srovná podle skutečné karty pod posledním známým místem kurzoru. */
function catAnimSync() {
  if (App.view !== 'catalog' || CAT.mx == null || matchMedia('(hover: none)').matches) return;
  const under = document.elementFromPoint(CAT.mx, CAT.my), card = under && under.closest ? under.closest('#catgrid .vcard') : null;
  $$('#catgrid .vth.has-anim').forEach(th => { if (th.dataset.want === '1' && th.closest('.vcard') !== card) catAnimOn(th, false); });
  const th = card && $('.vth.has-anim', card);
  if (th && (th.dataset.want !== '1' || !th.classList.contains('anim-on'))) catAnimOn(th, true);
}
function catAnimTrack() {
  if (CAT.tracking) return; CAT.tracking = true;
  let raf = 0;
  document.addEventListener('mousemove', e => { CAT.mx = e.clientX; CAT.my = e.clientY; }, { passive: true });
  document.documentElement.addEventListener('mouseleave', () => { CAT.mx = null; });
  window.addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; catAnimSync(); }); }, { passive: true });
}
function catAnimHover(e) {
  if (matchMedia('(hover: none)').matches) return;                                    // dotyk: přepíná jen klepnutí (jinak by emulované najetí animaci hned vypnulo)
  const card = e.target.closest && e.target.closest('.vcard'); if (!card) return;     // animace běží, dokud je kurzor kdekoli v rámečku karty
  const th = $('.vth.has-anim', card); if (!th) return;
  const inside = card.contains(e.relatedTarget);
  if (e.type === 'mouseover' && !inside) catAnimOn(th, true);
  if (e.type === 'mouseout' && !inside) catAnimOn(th, false);
}
function catGridClick(e) {
  const th = e.target.closest('.vth.has-anim');
  if (th && !e.target.closest('.vck, a, button') && matchMedia('(hover: none)').matches) { catAnimOn(th, th.dataset.want !== '1'); return; }
  const b = e.target.closest('[data-cact]');
  if (!b || b.disabled) return;
  if (b.dataset.cact === 'copy') { copyText(b.dataset.url).then(ok => toast(ok ? T('Adresa zkopírována', 'Address copied') : T('Kopírování se nepodařilo', 'Copy failed'), !ok)); return; }
  if (b.dataset.cact === 'open') return;                                  // běžný odkaz, otevře se sám v nové záložce
  if (b.dataset.cact === 'remove') catRemove({ ids: [+b.dataset.id] }, 1);
  else if (b.dataset.cact === 'download') {
    const again = b.dataset.dl === '1';
    if (again && !confirm(T('Toto video už bylo staženo dříve. Stáhnout ho znovu?', 'This video was downloaded before. Download it again?'))) return;
    catDownload({ ids: [+b.dataset.id] }, again);
  }
}
function catSelClick(e) {
  const b = e.target.closest('[data-cs]'); if (!b || b.disabled) return;
  const w = b.dataset.cs, d = CAT.data;
  if (w === 'page') { CAT.selAll = null; CAT.exclude.clear(); d.items.forEach(i => CAT.sel.add(i.id)); }
  else if (w === 'all') { CAT.selAll = catFilter(); CAT.sel.clear(); CAT.exclude.clear(); }
  else if (w === 'none') catClearSel();
  else if (w === 'download') {
    const n = catSelCount();
    return n ? catDownloadAsk(CAT.selAll ? { filter: CAT.selAll, exclude: [...CAT.exclude] } : { ids: [...CAT.sel] }, n) : undefined;
  }
  else if (w === 'remove') {
    const n = catSelCount();
    if (!n || !confirm(T(`Odstranit z katalogu ${n} videí? Zdroj si je zapamatuje a při „Načíst znovu vše“ je nabídne s odznakem „Dříve odmítnuté“.`, `Remove ${n} videos from the catalog? The source remembers them and offers them again with the “Rejected before” badge on “Reload all”.`))) return;
    return catRemove(CAT.selAll ? { filter: CAT.selAll, exclude: [...CAT.exclude] } : { ids: [...CAT.sel] }, n);
  }
  $$('#catgrid [data-csel]').forEach(c => { c.checked = catIsSel(+c.dataset.csel); c.closest('.vcard').classList.toggle('on', c.checked); });
  catPaintSel();
}
function openCatAdd() {
  const m = modal(`<h2 style="margin:0 0 4px">${T('Přidat zdroje do katalogu', 'Add sources to the catalog')}</h2>
    <div class="t2 fs13" style="margin-bottom:10px">${T('Adresy kanálů, playlistů, stránek nebo videí, jedna na řádek (řádky začínající # se přeskočí). Aplikace je jen prozkoumá, nic nestáhne.', 'Channel, playlist, page or video URLs, one per line (lines starting with # are skipped). The app only explores them and downloads nothing.')}</div>
    <textarea class="input mono" id="caturls" rows="9" style="width:100%;resize:vertical" placeholder="https://…\nhttps://…"></textarea>
    <div class="row gap8 wrap" style="margin-top:10px"><label class="btn sm">${ic('download', 13)} ${T('Načíst ze souboru .txt…', 'Load from a .txt file…')}<input type="file" id="catfile" accept=".txt,.csv,text/plain" hidden></label>
      <span class="t2 fs12" id="catcount"></span><span class="grow"></span><button class="btn" id="catcancel">${T('Zavřít', 'Close')}</button><button class="btn primary" id="catgo">${T('Přidat', 'Add')}</button></div>
    <div id="catres2" class="fs13" style="margin-top:10px"></div>`);
  const ta = $('#caturls', m.el), count = () => { const n = ta.value.split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length; $('#catcount', m.el).textContent = n ? `${n} ${T('řádků', 'lines')}` : ''; };
  ta.oninput = count; ta.focus();
  $('#catfile', m.el).onchange = async e => { const f = e.target.files[0]; if (!f) return; ta.value = (ta.value.trim() ? ta.value.trim() + '\n' : '') + await f.text(); e.target.value = ''; count(); };
  $('#catcancel', m.el).onclick = m.close;
  $('#catgo', m.el).onclick = async () => {
    if (!ta.value.trim()) return;
    const r = await act(() => api('/api/catalog/sources', { method: 'POST', body: { text: ta.value } }));
    if (!r) return;
    CAT.ov = r.overview;
    const parts = [r.added.length && `${T('Přidáno', 'Added')}: ${r.added.length}`, r.reloaded.length && `${T('Načte se znovu', 'Reloading')}: ${r.reloaded.length}`,
      r.skipped.length && `${T('Přeskočeno', 'Skipped')}: ${r.skipped.length}`, r.invalid_count && `${T('Neplatných řádků', 'Invalid lines')}: ${r.invalid_count}`].filter(Boolean);
    const detail = [...r.skipped.map(s => `${esc(s.url)} – ${esc(s.reason)}`), ...r.invalid.map(l => `${esc(l)} – ${T('není platná adresa', 'not a valid URL')}`)];
    if (!detail.length) { toast(parts.join(' · ')); m.close(); catLoad(); return; }
    $('#catres2', m.el).innerHTML = `<b>${parts.join(' · ')}</b><div class="mono fs12 t2" style="max-height:140px;overflow:auto;margin-top:6px;white-space:pre-wrap">${detail.slice(0, 60).join('\n')}</div>`;
    catLoad();
  };
}

/* ------------------------------------------------------------ časový rozvrh */
const DAY_NAMES = () => (LANG === 'cs' ? ['Po', 'Út', 'St', 'Čt', 'Pá', 'So', 'Ne'] : ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']);
function fmtWhen(ts) {
  const d = new Date(ts * 1000), now = new Date(), loc = LANG === 'cs' ? 'cs-CZ' : 'en-GB';
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  const hm = d.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit' });
  if (days === 0) return `${T('dnes', 'today')} ${hm}`;
  if (days === 1) return `${T('zítra', 'tomorrow')} ${hm}`;
  return `${d.toLocaleDateString(loc, { weekday: 'short', day: 'numeric', month: 'numeric' })} ${hm}`;
}
/* Banner „čeká na časové okno“ s tlačítky dočasné výjimky; `scope`: queue | subscriptions | catalog */
function scheduleBanner(st, scope, what) {
  const sc = st && st.schedule;
  if (!sc || !sc.enabled || !(sc.scope || []).includes(scope)) return '';
  if (sc.override_until) return `<div class="banner info">${ic('clock', 18)}<span class="grow">${T('Časový rozvrh je dočasně obejit do', 'The schedule is bypassed until')} ${fmtWhen(sc.override_until)}.</span><button class="btn sm" data-sov="clear">${T('Zrušit výjimku', 'Cancel exception')}</button></div>`;
  if (sc.allowed && sc.allowed[scope]) return '';
  return `<div class="banner info">${ic('clock', 18)}<span class="grow">${what} ${sc.next_open ? `${T('Další okno:', 'Next window:')} ${fmtWhen(sc.next_open)}.` : T('Žádné okno není nastavené.', 'No window is set.')}</span>
    <span class="row gap4"><button class="btn sm" data-sov="1">${T('Povolit na 1 h', 'Allow for 1 h')}</button><button class="btn sm" data-sov="3">3 h</button><button class="btn sm" data-sov="6">6 h</button></span><button class="btn sm" data-go="settings">${T('Upravit', 'Edit')}</button></div>`;
}
async function schOverride(v) {
  if (v === 'clear') await act(() => api('/api/schedule/override', { method: 'DELETE' }), T('Výjimka zrušena', 'Exception cancelled'));
  else await act(() => api('/api/schedule/override', { method: 'POST', body: { hours: +v } }), T('Rozvrh je dočasně obejit', 'Schedule bypassed'));
}
function schedRules() {
  const V = App.settings.values;
  if (V.schedule_rules && V.schedule_rules.length) return JSON.parse(JSON.stringify(V.schedule_rules));
  // dřívější nastavení jednoho okna (dokud nevzniknou pravidla) – stejně jako na serveru
  return V.schedule_start && V.schedule_end ? [{ days: (V.schedule_days || []).slice(), windows: [[V.schedule_start, V.schedule_end]] }] : [];
}
function schedHtml() {
  const rules = schedRules(), D = DAY_NAMES();
  const rule = (r, i) => `<div class="schrule">
    <div class="row gap4 wrap">${D.map((n, d) => `<button class="chip ${r.days.includes(d) ? 'on' : ''}" data-rd="${i}:${d}">${n}</button>`).join('')}<button class="btn sm" data-rall="${i}">${T('Každý den', 'Every day')}</button></div>
    <div class="row gap8 wrap" style="margin-top:8px">${r.windows.map((w, k) => `<span class="schwin"><input class="input sm mono" type="time" value="${w[0]}" data-rw="${i}:${k}:0"> – <input class="input sm mono" type="time" value="${w[1]}" data-rw="${i}:${k}:1"><button class="x" data-rwdel="${i}:${k}" ${r.windows.length < 2 ? 'disabled' : ''} title="${T('Odebrat okno', 'Remove window')}">✕</button></span>`).join('')}
      <button class="btn sm" data-rwadd="${i}" ${r.windows.length >= 8 ? 'disabled' : ''}>+ ${T('okno', 'window')}</button>
      <button class="btn sm ghost" data-rdel="${i}" ${rules.length < 2 ? 'disabled' : ''}>${T('Odebrat pravidlo', 'Remove rule')} ✕</button></div></div>`;
  return `<div class="fld block" id="schrules"><div class="lab"><div class="b5">${T('Pravidla', 'Rules')}</div><div class="hint">${T('Každé pravidlo má dny a jedno či více oken; pravidla se sčítají. Okno přes půlnoc (22:00–06:00) platí podle dne začátku, stejný začátek a konec znamená celý den.', 'Each rule has days and one or more windows; rules add up. A window across midnight (22:00–06:00) counts by the day it starts; equal start and end means the whole day.')}</div></div>
    ${rules.length ? rules.map(rule).join('') : `<div class="hint" style="color:var(--warn)">${T('Žádné pravidlo: při zapnutém rozvrhu by aplikace nikdy nezačala práci.', 'No rule: with the schedule on, the app would never start work.')}</div>`}
    <div style="margin-top:6px"><button class="btn sm" data-radd ${rules.length >= 20 ? 'disabled' : ''}>+ ${T('Přidat pravidlo', 'Add rule')}</button></div></div>`;
}
async function schSave(rules) {
  const r = await act(() => api('/api/settings', { method: 'PUT', body: { schedule_rules: rules } }));
  if (r) { App.settings = r; toast(T('Uloženo', 'Saved')); }
  if (App.view === 'settings') renderSettings();
}
function bindSchedule(root) {
  const edit = (sel, fn) => $$(sel, root).forEach(el => { el[el.tagName === 'INPUT' ? 'onchange' : 'onclick'] = () => { const r = schedRules(); if (fn(r, el) !== false) schSave(r); }; });
  edit('[data-rd]', (r, el) => {
    const [i, d] = el.dataset.rd.split(':').map(Number), days = r[i].days, k = days.indexOf(d);
    if (k >= 0) { if (days.length === 1) { toast(T('Vyberte aspoň jeden den', 'Pick at least one day'), true); return false; } days.splice(k, 1); } else { days.push(d); days.sort(); }
  });
  edit('[data-rall]', (r, el) => { r[+el.dataset.rall].days = [0, 1, 2, 3, 4, 5, 6]; });
  edit('[data-rw]', (r, el) => {
    const [i, k, w] = el.dataset.rw.split(':').map(Number);
    if (!/^\d\d:\d\d$/.test(el.value)) { toast(T('Zadejte čas', 'Enter a time'), true); renderSettings(); return false; }
    r[i].windows[k][w] = el.value;
  });
  edit('[data-rwadd]', (r, el) => { r[+el.dataset.rwadd].windows.push(['08:00', '17:00']); });
  edit('[data-rwdel]', (r, el) => { const [i, k] = el.dataset.rwdel.split(':').map(Number); r[i].windows.splice(k, 1); });
  edit('[data-radd]', r => { r.push({ days: [0, 1, 2, 3, 4], windows: [['19:00', '23:00']] }); });
  edit('[data-rdel]', (r, el) => { r.splice(+el.dataset.rdel, 1); });
}
function renderSchedStatus() {
  const box = $('#schstat'), sc = App.st && App.st.schedule; if (!box || !sc) return;
  const sov = `<span class="row gap4"><button class="btn sm" data-ssov="1">${T('Povolit na 1 h', 'Allow for 1 h')}</button><button class="btn sm" data-ssov="3">3 h</button><button class="btn sm" data-ssov="6">6 h</button></span>`;
  let h;
  if (!sc.enabled) h = `<span class="t2">${T('Rozvrh je vypnutý: aplikace pracuje kdykoli.', 'The schedule is off: the app works at any time.')}</span>`;
  else {
    h = sc.open ? `<span>${T('Teď: <b>v okně</b>', 'Now: <b>inside a window</b>')} · ${T('zavře se', 'closes')} <b>${fmtWhen(sc.closes)}</b></span>`
      : `<span>${T('Teď: <b>mimo okno</b>', 'Now: <b>outside a window</b>')} · ${sc.next_open ? `${T('další okno', 'next window')} <b>${fmtWhen(sc.next_open)}</b>` : T('žádné okno není nastavené', 'no window is set')}</span>`;
    if (sc.override_until) h += `<span>${T('Dočasná výjimka do', 'Temporary exception until')} <b>${fmtWhen(sc.override_until)}</b> <button class="btn sm" data-ssov="clear">${T('Zrušit', 'Cancel')}</button></span>`;
    else if (!sc.open) h += sov;
  }
  box.innerHTML = h;
  $$('[data-ssov]', box).forEach(b => b.onclick = () => schOverride(b.dataset.ssov));
}

function renderAppBanner() {
  const box = $('#appbn'); if (!box) return;
  const b = App.st && App.st.app, key = JSON.stringify(b || null);
  if (box.dataset.k === key) return;
  box.dataset.k = key;
  if (!b) { box.style.display = 'none'; box.innerHTML = ''; return; }
  const v = esc(b.version || '');
  let h;
  if (b.kind === 'available') h = `<div class="banner info">${ic('download', 18)}<span class="grow">${T(`Je k dispozici nová verze aplikace ${v}.`, `A new app version ${v} is available.`)}</span><button class="btn sm" data-ap="update">${T('Aktualizovat', 'Update')}</button><button class="btn sm" data-go="settings">${T('Podrobnosti', 'Details')}</button></div>`;
  else if (b.kind === 'prepared') h = `<div class="banner info">${ic('refresh', 18)}<span class="grow">${T(`Verze ${v} je nainstalovaná a otestovaná. Projeví se po restartu aplikace.`, `Version ${v} is installed and tested. It takes effect after the app restarts.`)}</span><button class="btn sm" data-ap="apply">${T('Restartovat po doběhnutí stahování', 'Restart when downloads finish')}</button><button class="btn sm" data-ap="restart">${T('Restartovat hned', 'Restart now')}</button></div>`;
  else if (b.kind === 'applying') h = `<div class="banner info">${ic('clock', 18)}<span class="grow">${T(`Čekám na doběhnutí stahování, pak se aplikace restartuje a přepne na verzi ${v}. Nová stahování se nezačínají.`, `Waiting for downloads to finish, then the app restarts and switches to version ${v}. No new downloads start.`)}</span></div>`;
  else h = `<div class="banner">${ic('alert', 18)}<span class="grow">${T(`Verze ${v} nenaběhla zdravě a aplikace se vrátila na předchozí.`, `Version ${v} did not start healthy, so the app went back to the previous one.`)} ${esc(b.msg || '')}</span><button class="btn sm" data-ap="dismiss" data-t="${b.t}">${T('Zavřít', 'Dismiss')}</button></div>`;
  box.innerHTML = h; box.style.display = '';
  $$('[data-ap]', box).forEach(el => el.onclick = () => appAction(el));
  $$('[data-go]', box).forEach(el => el.onclick = () => go(el.dataset.go));
}
async function appAction(el, done) {
  const what = el.dataset.ap;
  if (what === 'restart') return restartApp();
  if (what === 'rollback' && !confirm(T('Vrátit se na předchozí verzi aplikace? Změna se projeví po restartu.', 'Go back to the previous app version? The change takes effect after a restart.'))) return;
  const calls = {
    update: () => [api('/api/app/update', { method: 'POST', body: {} }), T('Nová verze je připravená', 'The new version is ready')],
    check: () => [api('/api/app/check', { method: 'POST' }), T('Zkontrolováno', 'Checked')],
    apply: () => [api('/api/app/apply', { method: 'POST' }), T('Po doběhnutí stahování se aplikace restartuje', 'The app restarts once downloads finish')],
    rollback: () => [api('/api/app/rollback', { method: 'POST', body: {} }), T('Vráceno, projeví se po restartu', 'Rolled back, takes effect after a restart')],
    dismiss: () => [api('/api/app/dismiss', { method: 'POST', body: { t: +el.dataset.t } }), null],
    unskip: () => [api('/api/app/unskip', { method: 'POST', body: { version: el.dataset.v } }), T('Přeskočení zrušeno', 'Skip cleared')],
  };
  const [p, msg] = calls[what]();
  const label = el.textContent; el.disabled = true;
  if (what === 'update' || what === 'check') el.textContent = what === 'update' ? T('Aktualizuji…', 'Updating…') : T('Kontroluji…', 'Checking…');
  const r = await act(() => p, msg);
  el.disabled = false; el.textContent = label;
  if (done) done(r);
}
async function loadAppStatus(box) {
  let s; try { s = await api('/api/app'); } catch (e) { return; }
  if (!box.isConnected) return;
  const chk = s.check || {};
  const label = { available: T('k dispozici nová verze', 'new version available'), up_to_date: T('máte nejnovější verzi', 'up to date'), skipped: T('nová verze byla přeskočena', 'new version was skipped'),
    needs_image: T('vyžaduje novější obraz (pull)', 'needs a newer image (pull)'), error: T('kontrola selhala', 'check failed') }[chk.status] || '';
  const rows = [[T('Verze v obraze', 'Image version'), esc(s.baseline)], [T('Běží', 'Running'), esc(s.running) + (s.running !== s.baseline ? T(' (aktualizace)', ' (update)') : '')]];
  if (s.prepared) rows.push([T('Připravená po restartu', 'Ready after restart'), esc(s.current)]);
  rows.push([T('Poslední kontrola', 'Last check'), chk.at ? `${fmtDT(chk.at)} – ${label}${chk.version && chk.status !== 'error' ? ' ' + esc(chk.version) : ''}` : T('zatím neproběhla', 'not yet')]);
  const skipped = Object.entries(s.skipped || {}).map(([v, d]) => `<div class="row gap8" style="padding:5px 0;border-top:1px solid var(--border)"><span class="grow t2" style="font-size:13px;min-width:0">${esc(v)} – ${esc(d.reason)}</span><button class="btn sm" data-ap="unskip" data-v="${esc(v)}">${T('Zkusit znovu', 'Try again')}</button></div>`).join('');
  const events = (s.events || []).slice().reverse().slice(0, 5).map(e => `<div class="t2" style="font-size:12px">${fmtDT(e.t)} · ${esc(e.kind)} ${esc(e.version || '')} ${esc(e.msg || '')}</div>`).join('');
  box.innerHTML = `<div style="margin:6px 0 4px">${rows.map(([k, v]) => `<div class="row gap8" style="font-size:13px;padding:2px 0"><span class="t2" style="width:170px;flex:none">${k}</span><span class="mono">${v}</span></div>`).join('')}
    ${chk.error ? `<div class="hint" style="margin-top:4px"><span class="badge b-err">${T('Chyba', 'Error')}</span> ${esc(chk.error)}</div>` : ''}
    <div class="row gap8 wrap" style="margin:10px 0">
      <button class="btn sm" data-ap="check">${ic('refresh', 13)} ${T('Zkontrolovat teď', 'Check now')}</button>
      ${chk.status === 'available' && !s.prepared ? `<button class="btn sm primary" data-ap="update">${T('Aktualizovat na', 'Update to')} ${esc(chk.version)}</button>` : ''}
      ${s.prepared && !s.applying ? `<button class="btn sm primary" data-ap="apply">${T('Restartovat po doběhnutí stahování', 'Restart when downloads finish')}</button><button class="btn sm" data-ap="restart">${T('Restartovat hned', 'Restart now')}</button>` : ''}
      ${s.current ? `<button class="btn sm" data-ap="rollback">${T('Vrátit na předchozí verzi', 'Back to the previous version')}</button>` : ''}</div>
    ${skipped ? `<div class="hint" style="margin-bottom:4px">${T('Přeskočené verze (nezkouší se znovu)', 'Skipped versions (not retried)')}</div>${skipped}` : ''}
    ${events ? `<details style="margin-top:6px"><summary class="t2" style="font-size:12px;cursor:pointer">${T('Poslední události', 'Recent events')}</summary>${events}</details>` : ''}
    <div style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px"><div class="b5">${T('GitHub token pro čtení vydání', 'GitHub token for reading releases')} <span class="badge ${s.token_set ? 'b-ok' : 'b-warn'}">${s.token_set ? T('uložen', 'saved') : T('nenastaven', 'not set')}</span></div>
      <div class="hint">${T('Soukromý repozitář vyžaduje token jen pro čtení (Contents: read). Ukládá se do secrets.json a nikdy se nezobrazuje.', 'A private repository needs a read-only token (Contents: read). It is stored in secrets.json and never shown.')}</div>
      <div class="row gap8" style="margin-top:6px"><input class="input sm mono" id="aptok" type="password" autocomplete="off" placeholder="github_pat_…" style="flex:1;min-width:0"><button class="btn sm" id="aptoksave">${T('Uložit', 'Save')}</button>${s.token_set ? `<button class="btn sm" id="aptokdel">${T('Smazat', 'Delete')}</button>` : ''}</div></div></div>`;
  $$('[data-ap]', box).forEach(el => el.onclick = () => appAction(el, () => loadAppStatus(box)));
  const sv = $('#aptoksave', box); if (sv) sv.onclick = async () => { const t = $('#aptok', box).value.trim(); if (!t) return;
    if (await act(() => api('/api/app/token', { method: 'POST', body: { token: t } }), T('Token uložen', 'Token saved'))) loadAppStatus(box); };
  const dl = $('#aptokdel', box); if (dl) dl.onclick = async () => { if (await act(() => api('/api/app/token', { method: 'POST', body: { token: '' } }), T('Token smazán', 'Token deleted'))) loadAppStatus(box); };
}
async function loadAutoBackup(box) {
  let d; try { d = await api('/api/autobackup'); } catch (e) { return; }
  if (!box.isConnected) return;
  const s = d.state || {}, now = Date.now() / 1000;
  const line = s.last_ok ? `${T('Poslední záloha', 'Last backup')}: ${fmtDT(s.last_ok)} · ${fmtBytes(s.size)}` : T('Zatím žádná automatická záloha', 'No automatic backup yet');
  const nxt = d.enabled && d.next ? `${T('Další záloha', 'Next backup')}: ${d.next <= now ? T('co nejdříve', 'as soon as possible') : fmtDT(d.next)}` : T('Automatické zálohy jsou vypnuté', 'Automatic backups are off');
  const err = s.error ? `<div class="hint" style="margin-top:4px"><span class="badge b-err">${T('Poslední pokus selhal', 'Last attempt failed')} ${fmtDT(s.last_try)}</span> ${esc(s.error)}</div>` : '';
  const rows = (d.backups || []).map(b => `<div class="row gap8" style="padding:6px 0;border-top:1px solid var(--border)"><span class="mono fs12" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis" title="${esc(b.name)}">${esc(b.name)}</span><span class="t2 fs12">${fmtBytes(b.size)}</span><button class="btn sm" data-abr="${esc(b.name)}">${T('Obnovit', 'Restore')}</button></div>`).join('');
  box.innerHTML = `<div style="margin:8px 0 6px"><div class="t2" style="font-size:13px">${line}</div><div class="t2" style="font-size:13px">${nxt}</div>${err}
    <div class="row gap8 wrap" style="margin:10px 0"><button class="btn sm" id="abnow">${ic('refresh', 13)} ${T('Zálohovat teď', 'Back up now')}</button><span class="t2 fs12 mono" style="min-width:0;overflow:hidden;text-overflow:ellipsis">${esc(d.dir)}</span></div>
    ${rows ? `<div class="hint" style="margin-bottom:4px">${T('Zálohy ve složce', 'Backups in the folder')}</div>${rows}` : ''}</div>`;
  const nw = $('#abnow', box); if (nw) nw.onclick = async () => { nw.disabled = true; nw.textContent = T('Zálohuji…', 'Backing up…');
    await act(() => api('/api/autobackup/run', { method: 'POST' }), T('Záloha vytvořena', 'Backup created')); loadAutoBackup(box); };
  $$('[data-abr]', box).forEach(b => b.onclick = async () => {
    if (!await act(() => api('/api/autobackup/restore', { method: 'POST', body: { name: b.dataset.abr } }), T('Záloha ověřena', 'Backup verified'))) return;
    const rs = $('#rsbox'); if (rs) { await loadRestore(rs); rs.scrollIntoView({ block: 'center' }); } });
}
function fmtDT(ts) { return new Date(ts * 1000).toLocaleString(LANG === 'cs' ? 'cs-CZ' : 'en-GB'); }
async function loadRestore(box) {
  let st; try { st = await api('/api/restore'); } catch (e) { return; }
  if (!box.isConnected) return;
  const p = st.pending, l = st.last; let h = '';
  const desc = m => T(`záloha z ${fmtDT(m.created)}, verze ${esc(m.app_version)}: ${m.done} stažených, ${m.jobs} úloh, ${m.subscriptions} odběrů`,
    `backup from ${fmtDT(m.created)}, version ${esc(m.app_version)}: ${m.done} downloaded, ${m.jobs} jobs, ${m.subscriptions} subscriptions`);
  if (p && p.manifest) {
    const m = p.manifest;
    h += `<div style="margin:6px 0 12px;padding:12px 14px;border:1px solid var(--border2);border-radius:10px;background:var(--surface2)">
      <div class="b5">${T('Připraveno k obnovení', 'Ready to restore')}</div>
      <div class="t2" style="margin:3px 0 10px;font-size:13px">${desc(m)}</div>
      <div class="hint" style="margin-bottom:6px">${T('Jen při přesunu na jiný stroj: přepsat začátek cest stažených souborů', 'Only when moving to another machine: rewrite the start of downloaded file paths')}</div>
      <div class="row gap8 wrap"><input class="input sm" id="rsold" style="width:200px" placeholder="${esc(m.download_dir || m.path_hint || T('/stará/cesta', '/old/path'))}"><span class="t2">→</span><input class="input sm" id="rsnew" style="width:200px" placeholder="/downloads"></div>
      <div class="row gap8" style="margin-top:12px;justify-content:flex-end"><button class="btn sm" id="rscancel">${T('Zrušit', 'Cancel')}</button><button class="btn sm primary" id="rsapply">${T('Obnovit a restartovat', 'Restore and restart')}</button></div></div>`;
  }
  if (l) h += l.ok
    ? `<div class="hint"><span class="badge b-ok">${ic('check', 11)} ${T('Poslední obnova', 'Last restore')} ${fmtDT(l.at)}</span></div>`
    : `<div class="hint"><span class="badge b-err">${T('Poslední obnova selhala', 'Last restore failed')} ${fmtDT(l.at)}</span> ${esc(l.error || '')}</div>`;
  box.innerHTML = h;
  const c = $('#rscancel', box); if (c) c.onclick = async () => { if (await act(() => api('/api/restore', { method: 'DELETE' }))) loadRestore(box); };
  const a = $('#rsapply', box); if (a) a.onclick = async () => {
    if (!confirm(T('Nahradit současná data daty ze zálohy? Aplikace se restartuje a rozpracovaná stahování se přeruší. Dosavadní stav se uloží do složky restore/ v datové složce.', 'Replace the current data with the backup? The app restarts and downloads in progress are interrupted. The previous state is kept in the restore/ folder of the data folder.'))) return;
    if (!await act(() => api('/api/restore/apply', { method: 'POST', body: { remap_old: $('#rsold').value, remap_new: $('#rsnew').value } }))) return;
    await waitForRestart();
  };
}
async function saveSetting(k, v, after) {
  const r = await act(() => api('/api/settings', { method: 'PUT', body: { [k]: v } }));
  if (!r) { // odmítnuto (např. neplatná složka) – vrátit pole na uloženou hodnotu
    if (after) after(); else if (App.view === 'settings') renderSettings();
    return;
  }
  App.settings = r;
  if (k === 'language') { LANG = v; document.documentElement.lang = v; return render(); }
  if (k === 'theme') { applyTheme(v); renderSide(); }
  toast(T('Uloženo', 'Saved'));
  if (after) after(); else if (App.view === 'settings') renderSettings();
}

/* ------------------------------------------------------------ modální okna */
function modal(html, cls = '') {
  const root = $('#modal-root'); root.innerHTML = `<div class="overlay"><div class="modal ${cls}">${html}</div></div>`;
  const close = () => { root.innerHTML = ''; };
  $('.overlay', root).addEventListener('mousedown', e => { if (e.target.classList.contains('overlay') && !cls.includes('nodismiss')) close(); });
  return { el: $('.modal', root), close };
}
async function openDirPicker(start, cb) {
  const m = modal(`<div class="mh">${ic('folder', 18)}<h2>${T('Vyberte složku', 'Choose a folder')}</h2></div><div class="mb"><input class="input sm mono fs12" id="dpath"><div class="dirs" id="dlist"></div></div>
   <div class="mf"><button class="btn" id="dcancel">${T('Zrušit', 'Cancel')}</button><button class="btn primary" id="dok">${T('Vybrat tuto složku', 'Use this folder')}</button></div>`);
  const load = async p => { const r = await act(() => api('/api/fs?path=' + encodeURIComponent(p || ''))); if (!r) return; $('#dpath').value = r.path;
    $('#dlist').innerHTML = (r.parent ? `<button data-p="${esc(r.parent)}">${ic('up', 14)} ..</button>` : '') + r.dirs.map(d => `<button data-p="${esc(r.path.replace(/[\\/]$/, '') + (r.path.includes('\\') ? '\\' : '/') + d)}">${ic('folder', 14)} ${esc(d)}</button>`).join('');
    $$('#dlist button').forEach(b => b.onclick = () => load(b.dataset.p)); };
  $('#dpath').onchange = e => load(e.target.value);
  $('#dcancel').onclick = m.close; $('#dok').onclick = () => { cb($('#dpath').value); m.close(); };
  load(start);
}
function openPassword(after) {
  const has = App.settings.has_password;
  const m = modal(`<div class="mh">${ic('lock', 18)}<h2>${T('Heslo do GUI', 'GUI password')}</h2></div><div class="mb col gap10"><p class="t2">${T('Heslo chrání webové rozhraní. Je povinné, pokud zapnete přístup ze sítě.', 'The password protects the web interface. Required for network access.')}</p>
   <input class="input" type="password" id="pw1" placeholder="${T('Nové heslo (min. 6 znaků)', 'New password (min. 6 chars)')}" autocomplete="new-password"><input class="input" type="password" id="pw2" placeholder="${T('Heslo znovu', 'Repeat password')}" autocomplete="new-password"></div>
   <div class="mf">${has ? `<button class="btn danger" id="pwrm" style="margin-right:auto">${T('Odstranit heslo', 'Remove password')}</button>` : ''}<button class="btn" id="pwc">${T('Zrušit', 'Cancel')}</button><button class="btn primary" id="pws">${T('Uložit', 'Save')}</button></div>`);
  $('#pwc').onclick = m.close;
  $('#pws').onclick = async () => { if ($('#pw1').value !== $('#pw2').value) return toast(T('Hesla se neshodují', "Passwords don't match"), true);
    const r = await act(() => api('/api/settings/password', { method: 'POST', body: { password: $('#pw1').value } }), T('Heslo uloženo', 'Password saved')); if (r) { App.settings = r; m.close(); after && after(); } };
  const rm = $('#pwrm'); if (rm) rm.onclick = async () => { const r = await act(() => api('/api/settings/password', { method: 'POST', body: { password: '' } }), T('Heslo odstraněno', 'Password removed')); if (r) { App.settings = r; m.close(); after && after(); } };
}
function openToken(after) {
  const m = modal(`<div class="mh">${ic('send', 18)}<h2>${T('Token Telegram bota', 'Telegram bot token')}</h2></div><div class="mb col gap10">
   <p class="t2">${T('Token získáte u <b>@BotFather</b> v Telegramu příkazem <code>/newbot</code>. Vypadá jako <code>123456:ABC-DEF…</code>', 'Get the token from <b>@BotFather</b> in Telegram with <code>/newbot</code>. It looks like <code>123456:ABC-DEF…</code>')}</p>
   <input class="input mono" id="tgt" placeholder="123456789:AA…" autocomplete="off"></div>
   <div class="mf"><button class="btn" id="tgc">${T('Zrušit', 'Cancel')}</button><button class="btn primary" id="tgs">${T('Uložit', 'Save')}</button></div>`);
  $('#tgc').onclick = m.close;
  $('#tgs').onclick = async () => { const r = await act(() => api('/api/settings/telegram_token', { method: 'POST', body: { token: $('#tgt').value } }), T('Token uložen', 'Token saved')); if (r) { App.settings = r; m.close(); after && after(); } };
}

/* ------------------------------------------------------------ průvodce prvním spuštěním */
function openWizard() {
  let step = 0; const N = 5;
  const m = modal('', 'wide nodismiss');
  const S = () => App.settings;
  const steps = [
    () => `<div class="mh">${ic('sparkle', 20)}<h2>${T('Vítejte ve VidDown', 'Welcome to VidDown')}</h2></div><div class="mb help">
      <p>${T('VidDown stahuje videa ze stránek, playlistů i celých kanálů do složky ve vašem počítači. Zabere to dvě minuty.', 'VidDown downloads videos from pages, playlists and whole channels to a folder on your computer. Setup takes two minutes.')}</p>
      <ul><li>${T('<b>YouTube a tisíce dalších webů</b> přes yt-dlp, ostatní stránky přes vestavěný HLS sniffer.', '<b>YouTube and thousands of sites</b> via yt-dlp, other pages via the built-in HLS sniffer.')}</li>
      <li>${T('<b>Jedna fronta</b>, stahuje se postupně v pořadí přidání. Pořadí a pauzy měníte tady v GUI.', '<b>One queue</b>, downloads run in order. Reorder and pause here in the GUI.')}</li>
      <li>${T('<b>Telegram:</b> pošlete botovi odkaz a on video stáhne.', '<b>Telegram:</b> send a link to the bot and it downloads the video.')}</li>
      <li>${T('<b>Miniatura</b> se uloží jako JPG vedle každého videa.', 'A <b>JPG thumbnail</b> is saved next to each video.')}</li>
      <li>${T('<b>Enginy</b> (yt-dlp, Deno, ffmpeg) se aktualizují samy a při chybě se vrátí k funkční verzi.', '<b>Engines</b> (yt-dlp, Deno, ffmpeg) update themselves and roll back on failure.')}</li></ul></div>`,
    () => `<div class="mh">${ic('folder', 20)}<h2>${T('Kam ukládat videa', 'Where to save videos')}</h2></div><div class="mb" id="wf">${fieldHtml({ k: 'download_dir', type: 'path', label: ['Cílová složka', 'Download folder'] }, S())}
      ${fieldHtml({ k: 'quality', type: 'seg', opts: [['max', ['Maximální', 'Maximum']], ['compat', ['Kompatibilita', 'Compatibility']]], label: ['Kvalita', 'Quality'], hint: ['Maximální = nejvyšší rozlišení (MKV, když se kodeky nevejdou do MP4)', 'Maximum = highest resolution (MKV when codecs do not fit MP4)'] }, S())}
      ${fieldHtml({ k: 'channel_folder', type: 'toggle', label: ['Kanály do samostatné složky', 'Channels into their own folder'] }, S())}${fieldHtml({ k: 'playlist_folder', type: 'toggle', label: ['Playlisty do samostatné složky', 'Playlists into their own folder'] }, S())}</div>`,
    () => `<div class="mh">${ic('download', 20)}<h2>${T('Jak stahovat', 'How to download')}</h2></div><div class="mb" id="wf">${fieldHtml({ k: 'concurrency', type: 'stepper', label: ['Souběžná stahování', 'Parallel downloads'], hint: ['Kolik videí z čela fronty se stahuje najednou', 'How many videos download at once'] }, S())}
      ${fieldHtml({ k: 'rate_limit_enabled', type: 'toggle', label: ['Omezit rychlost', 'Limit speed'] }, S())}${S().values.rate_limit_enabled ? fieldHtml({ k: 'rate_limit_mbps', type: 'number', step: 0.5, suffix: 'MB/s', label: ['Limit', 'Limit'] }, S()) : ''}
      ${fieldHtml({ k: 'schedule_enabled', type: 'toggle', label: ['Stahovat jen v časovém okně', 'Only in a time window'], hint: ['Např. v noci', 'E.g. at night'] }, S())}
      ${S().values.schedule_enabled ? fieldHtml({ k: 'schedule_start', type: 'time', label: ['Od', 'From'] }, S()) + fieldHtml({ k: 'schedule_end', type: 'time', label: ['Do', 'To'] }, S()) : ''}</div>`,
    () => `<div class="mh">${ic('send', 20)}<h2>${T('Telegram (volitelné)', 'Telegram (optional)')}</h2></div><div class="mb help"><ol>
      <li>${T('V Telegramu otevřete <b>@BotFather</b>, pošlete <code>/newbot</code> a zvolte jméno.', 'In Telegram open <b>@BotFather</b>, send <code>/newbot</code> and pick a name.')}</li>
      <li>${T('Token, který dostanete, vložte níže.', 'Paste the token you get below.')}</li>
      <li>${T('Napište svému botovi cokoli. Odpoví vaším <b>chat ID</b> – vložte ho do pole níže.', 'Message your bot. It replies with your <b>chat ID</b> – paste it below.')}</li></ol>
      <div class="col gap8" style="margin-top:10px"><input class="input mono" id="wtok" placeholder="${S().telegram_token_set ? T('Token je uložen – nový vložte jen pro změnu', 'Token saved – paste only to change') : '123456789:AA…'}">
      <input class="input mono" id="wchat" placeholder="chat ID" value="${esc(S().values.telegram_chat_id)}"></div>
      <p class="fs12 muted">${T('Pomocí bota jde stejně jako v GUI přidávat odkazy. Bot vám napíše, kolik videí našel a v jakém rozlišení, a pak už jen hlásí chyby.', 'The bot adds links like the GUI does. It tells you how many videos it found and in which resolution, then only reports errors.')}</p></div>`,
    () => `<div class="mh">${ic('check', 20)}<h2>${T('Hotovo', 'All set')}</h2></div><div class="mb help">
      <p>${T('Vložte odkaz do pole <b>Fronta › Vložte URL</b> a stiskněte Enter. Můžete vložit i víc odkazů najednou.', 'Paste a link into <b>Queue › Paste URL</b> and press Enter. You can paste several at once.')}</p>
      <ul><li>${T('<b>Fronta</b> – průběh, pořadí (přetažením), pauza a odstranění položek.', '<b>Queue</b> – progress, drag to reorder, pause and remove items.')}</li>
      <li>${T('<b>Historie</b> – hotová a neúspěšná stahování, opakování.', '<b>History</b> – finished and failed downloads, retry.')}</li>
      <li>${T('<b>Nastavení</b> – pojmenování, plánování, cookies, Telegram a další.', '<b>Settings</b> – naming, schedule, cookies, Telegram and more.')}</li>
      <li>${T('<b>Enginy</b> – verze, aktualizace a návrat k předchozí verzi.', '<b>Engines</b> – versions, updates and rollback.')}</li>
      <li>${T('<b>Nápověda</b> – podrobný popis všech funkcí. Průvodce spustíte znovu odtud.', '<b>Help</b> – all features explained. Restart this guide from there.')}</li></ul></div>`,
  ];
  const draw = () => {
    m.el.innerHTML = steps[step]() + `<div class="mf"><div class="steps" style="margin-right:auto">${Array.from({ length: N }, (_, i) => `<i class="${i <= step ? 'on' : ''}"></i>`).join('')}</div>
     ${step === 0 ? `<button class="btn ghost" id="wskip">${T('Přeskočit', 'Skip')}</button>` : `<button class="btn" id="wback">${T('Zpět', 'Back')}</button>`}
     <button class="btn primary" id="wnext">${step === N - 1 ? T('Začít', 'Start') : T('Pokračovat', 'Continue')}</button></div>`;
    const wf = $('#wf', m.el); if (wf) bindSettings(wf, draw);
    const sk = $('#wskip', m.el); if (sk) sk.onclick = finish;
    const bk = $('#wback', m.el); if (bk) bk.onclick = () => { step--; draw(); };
    $('#wnext', m.el).onclick = async () => {
      if (step === 3) {
        const tok = $('#wtok').value.trim(), chat = $('#wchat').value.trim();
        if (tok) { const r = await act(() => api('/api/settings/telegram_token', { method: 'POST', body: { token: tok } })); if (!r) return; App.settings = r; }
        if (chat !== App.settings.values.telegram_chat_id) { const r = await act(() => api('/api/settings', { method: 'PUT', body: { telegram_chat_id: chat } })); if (!r) return; App.settings = r; }
      }
      if (step === N - 1) return finish();
      step++; draw();
    };
  };
  const finish = async () => { await act(() => api('/api/onboarded', { method: 'POST' })); m.close(); if (App.view === 'settings') renderSettings(); };
  draw();
}

/* ------------------------------------------------------------ enginy */
async function renderEngines() {
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Enginy', 'Engines')}</h1><div class="t2" style="margin-top:3px">${T('Každá aktualizace se otestuje. Když nová verze selže, zůstane předchozí funkční.', 'Every update is tested. If the new version fails, the previous working one stays.')}</div></div><div class="grow"></div>
   <span class="row gap8 t2 fs12" id="eauto"></span><button class="btn" id="echeck">${ic('refresh', 14)} ${T('Zkontrolovat aktualizace', 'Check for updates')}</button></div><div id="edyn" class="col gap16"><div class="empty"><div class="spin" style="margin:auto"></div></div></div>`;
  $('#echeck').onclick = () => act(() => api('/api/engines/check', { method: 'POST' }), T('Kontroluji aktualizace…', 'Checking for updates…'));
  await loadEngines();
  App.timer = setInterval(loadEngines, 2500);
}
async function loadEngines() {
  if (App.view !== 'engines') return;
  let r; try { r = await api('/api/engines'); } catch (e) { return; }
  App.engines = r;
  $('#eauto').innerHTML = `${T('Automatické aktualizace', 'Automatic updates')} <button class="toggle ${r.auto ? 'on' : ''}" id="eat"></button> ${T('každých', 'every')} ${r.hours} h`;
  $('#eat').onclick = () => saveSetting('engine_auto_update', !r.auto, loadEngines);
  const desc = { 'yt-dlp': T('YouTube a tisíce dalších webů', 'YouTube and thousands of sites'), deno: T('JavaScript runtime pro YouTube', 'JavaScript runtime for YouTube'), ffmpeg: T('Spojování a převod videa', 'Merging and converting video') };
  const card = e => {
    const curMeta = e.versions.find(v => v.version === e.current);
    const busy = r.busy === e.name;
    const status = busy ? `<span class="badge b-yt"><span class="spin" style="width:10px;height:10px"></span> ${T('Pracuji…', 'Working…')}</span>`
      : !e.path ? `<span class="badge b-err">${T('Chybí', 'Missing')}</span>`
      : curMeta && curMeta.tested_ok === false ? `<span class="badge b-err">${ic('alert', 11)} ${T('Test selhal', 'Test failed')}</span>`
      : `<span class="badge b-ok">${ic('check', 11)} ${T('Funkční', 'Working')}</span>`;
    const ver = e.current || (e.system ? e.system : '—');
    const vnum = v => (String(v || '').match(/\d+/g) || []).slice(0, 4).map(Number);
    const newer = (a, b) => { const x = vnum(a), y = vnum(b); for (let i = 0; i < Math.max(x.length, y.length); i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); } return false; };
    const latest = e.last && e.last.latest && newer(e.last.latest, e.current || e.system) ? `<span class="badge b-yt">${T('K dispozici', 'Available')} ${esc(e.last.latest)}</span>` : '';
    const sub = e.current ? `${T('aktivní verze', 'active version')}${curMeta && curMeta.tested_at ? ' · ' + T('test', 'tested') + ' ' + fmtDate(curMeta.tested_at) : ''}` : e.system ? T('systémová verze (z PATH)', 'system version (from PATH)') : T('není nainstalováno', 'not installed');
    const hist = e.versions.map(v => `<div class="row" style="padding:8px 0;border-top:1px solid var(--border);gap:10px"><span class="mono b5">${esc(v.version)}</span><span class="fs12 muted">${fmtDate(v.installed_at)}</span>
      ${v.tested_ok === false ? `<span class="badge b-err">${T('test selhal', 'failed')}</span>` : ''}<span class="grow"></span>
      ${v.version === e.current ? `<span class="badge b-yt">${T('Aktivní', 'Active')}</span>` : `<button class="btn sm" data-e="rollback" data-n="${e.name}" data-v="${esc(v.version)}">${ic('undo', 12)} ${T('Vrátit', 'Use')}</button><button class="ibtn" data-e="remove" data-n="${e.name}" data-v="${esc(v.version)}">${ic('trash', 13)}</button>`}</div>`).join('');
    return `<div class="card" style="padding:18px"><div class="row gap10"><div style="width:36px;height:36px;border-radius:10px;background:var(--accent-soft);color:var(--accent-text);display:flex;align-items:center;justify-content:center">${ic('cpu', 18)}</div>
      <div class="grow"><div class="b6 fs15">${e.name}</div><div class="fs12 t2">${desc[e.name] || ''}</div></div>${status}</div>
      <div class="row wrap" style="margin-top:16px;align-items:baseline;gap:10px"><span class="mono" style="font-size:22px;font-weight:700">${esc(ver)}</span>${latest}</div>
      <div class="fs12 muted" style="margin-top:2px">${sub}</div>
      <div class="row gap8" style="margin-top:14px"><button class="btn sm primary" data-e="update" data-n="${e.name}" ${r.busy ? 'disabled' : ''}>${ic('refresh', 12)} ${e.current || e.system ? T('Aktualizovat', 'Update') : T('Nainstalovat', 'Install')}</button>
      <button class="btn sm" data-e="test" data-n="${e.name}" ${!e.path ? 'disabled' : ''}>${ic('check', 12)} ${T('Spustit test', 'Run test')}</button></div>
      ${hist ? `<div style="margin-top:14px"><div class="fs11 muted b6" style="text-transform:uppercase;letter-spacing:.04em;padding-bottom:6px">${T('Uchované verze', 'Installed versions')}</div>${hist}</div>` : ''}</div>`;
  };
  const ch = r.chromium;
  const log = r.log.slice().reverse().slice(0, 80).reverse().map(l => {
    const d = new Date(l.t * 1000); const tm = d.toLocaleTimeString(LANG === 'cs' ? 'cs-CZ' : 'en-GB');
    const msg = esc(l.msg).replace(/\bOK\b/g, '<span class="lok">OK</span>').replace(/CHYBA[^<]*/g, m => `<span class="lerr">${m}</span>`);
    return `<div><span class="lt">${tm}</span> <span class="lc">${esc(l.engine).padEnd(8)}</span> ${msg}</div>`;
  }).join('');
  $('#edyn').innerHTML = `<div class="egrid">${r.engines.map(card).join('')}</div>
   <div class="card row gap12 wrap" style="padding:14px 18px">${ic('globe', 18)}<div class="grow"><div class="b6">Chromium (sniffer)</div><div class="fs12 t2">${ch.installed ? T('Playwright', 'Playwright') + ' ' + esc(ch.playwright) + ' · ' + T('aktualizuje se spolu s aplikací', 'updated together with the app') : T('Playwright není k dispozici', 'Playwright not available')}</div></div>
   <button class="btn sm" id="chinst" ${r.chromium_busy ? 'disabled' : ''}>${r.chromium_busy ? '<span class="spin"></span>' : ic('download', 13)} ${T('Nainstalovat / opravit prohlížeč', 'Install / repair browser')}</button></div>
   <div class="card" style="overflow:hidden"><div class="row gap8" style="padding:12px 16px;border-bottom:1px solid var(--border)">${ic('terminal', 15)}<h2>${T('Protokol', 'Log')}</h2></div><div class="log mono">${log || T('Zatím žádné záznamy.', 'No entries yet.')}</div></div>`;
  $$('[data-e]', $('#edyn')).forEach(b => b.onclick = async () => {
    const a = b.dataset.e, n = b.dataset.n, v = b.dataset.v;
    if (a === 'remove' && !confirm(T(`Smazat verzi ${v}?`, `Delete version ${v}?`))) return;
    await act(() => api(`/api/engines/${n}/${a}`, { method: 'POST', body: v ? { version: v } : {} }), { update: T('Aktualizace spuštěna', 'Update started'), test: T('Test spuštěn', 'Test started'), rollback: T('Verze přepnuta', 'Version switched'), remove: T('Smazáno', 'Deleted') }[a]);
    loadEngines();
  });
  $('#chinst').onclick = () => act(() => api('/api/engines/chromium/install', { method: 'POST' }), T('Instaluji Chromium…', 'Installing Chromium…'));
  const lg = $('.log', $('#edyn')); if (lg) lg.scrollTop = lg.scrollHeight;
}

/* ------------------------------------------------------------ nápověda */
function renderHelp() {
  const H = [
    ['about', T('Co VidDown umí', 'What VidDown does'), T(`
      <p>VidDown stahuje videa z webových stránek do složky nastavené v <b>Nastavení › Stahování</b>. Ovládá se třemi způsoby: tímto webovým rozhraním, Telegram botem a příkazy v terminálu.</p>
      <ul><li><b>YouTube a tisíce dalších webů</b> přes engine yt-dlp – videa, playlisty i celé kanály.</li>
      <li><b>Ostatní stránky</b> přes vestavěný HLS sniffer: aplikace otevře stránku v neviditelném prohlížeči, odposlechne video stream (.m3u8, DASH, MP4) a stáhne ho pomocí ffmpeg.</li>
      <li><b>Automatický fallback</b>: když yt-dlp video nenajde, zkusí se sniffer. Pořadí jde změnit v Nastavení › Pokročilé.</li>
      <li><b>Nejvyšší kvalita</b> je výchozí. Miniatura se vždy uloží jako JPG se stejným názvem vedle videa.</li>
      <li><b>Jedna fronta</b>, stahuje se postupně v pořadí přidání.</li></ul>`, `
      <p>VidDown downloads videos from web pages into the folder set in <b>Settings › Downloading</b>. You control it from this web interface, a Telegram bot or terminal commands.</p>
      <ul><li><b>YouTube and thousands of sites</b> via yt-dlp – videos, playlists and whole channels.</li>
      <li><b>Other pages</b> via the built-in HLS sniffer: the app opens the page in a hidden browser, captures the stream (.m3u8, DASH, MP4) and downloads it with ffmpeg.</li>
      <li><b>Automatic fallback</b>: if yt-dlp finds nothing, the sniffer tries. Change the order in Settings › Advanced.</li>
      <li><b>Best quality</b> by default. A JPG thumbnail with the same name is always saved next to the video.</li>
      <li><b>One queue</b>, downloads run in the order they were added.</li></ul>`)],
    ['add', T('Jak přidat video', 'Adding videos'), T(`
      <p><b>V GUI:</b> vložte odkaz do pole nahoře na stránce Fronta a stiskněte Enter. Můžete vložit i víc odkazů najednou (každý na řádek nebo oddělené mezerou).</p>
      <p><b>Telegram:</b> pošlete odkaz svému botovi. Bot odpoví, kolik videí na adrese našel a v jakém rozlišení se první z nich stáhne.</p>
      <p><b>Terminál:</b> <code>viddown add https://…</code></p>
      <p>Po přidání proběhne <b>kontrola URL</b> (počet videí, rozlišení, miniatura). Nezabírá místo ve stahování a běží souběžně.</p>`, `
      <p><b>In the GUI:</b> paste a link into the field at the top of the Queue page and press Enter. Several links at once work too.</p>
      <p><b>Telegram:</b> send a link to your bot. It replies with how many videos it found and the resolution of the first one.</p>
      <p><b>Terminal:</b> <code>viddown add https://…</code></p>
      <p>Each new item gets a <b>URL check</b> (count, resolution, thumbnail). It runs separately from downloads.</p>`)],
    ['queue', T('Fronta', 'The queue'), T(`
      <ul><li>Úlohy se spouštějí v <b>pořadí přidání</b>. <b>Souběžná stahování</b> určují, kolik jich běží najednou.</li>
      <li><b>Změna pořadí</b>: chyťte řádek za úchyt ⋮⋮ a přetáhněte ho.</li>
      <li><b>Pauza položky</b> (tlačítko ⏸): položka zůstane na svém místě a přeskakuje se, dokud ji nepovolíte. Rozpracované stahování naváže.</li>
      <li><b>Odstranění</b> (✕): úloha se zruší, rozpracované soubory se smažou a do historie se zapíše jako zrušená.</li>
      <li><b>Pozastavit frontu</b>: nic nového se nespustí, běžící stahování se přeruší a později naváže.</li>
      <li>Měnit pořadí, pauzovat a odstraňovat jde <b>jen v GUI</b>. Telegram a terminál umí přidávat a zobrazovat.</li>
      <li>Při chybě sítě se úloha <b>automaticky zopakuje</b> (po 1 a 5 minutách). Soukromá nebo smazaná videa se neopakují.</li>
      <li>Při nedostatku místa na disku (méně než nastavené minimum) se fronta pozastaví.</li></ul>`, `
      <ul><li>Jobs start <b>in the order they were added</b>. <b>Parallel downloads</b> sets how many run at once.</li>
      <li><b>Reorder</b>: drag a row by its ⋮⋮ handle.</li>
      <li><b>Pause an item</b> (⏸): it keeps its place and is skipped until you resume it. Partial downloads continue later.</li>
      <li><b>Remove</b> (✕): the job is cancelled, partial files are deleted and history shows it as cancelled.</li>
      <li><b>Pause queue</b>: nothing new starts; running downloads stop and resume later.</li>
      <li>Reordering, pausing and removing work <b>only in the GUI</b>. Telegram and the terminal can add and list.</li>
      <li>Network errors are <b>retried automatically</b> (after 1 and 5 minutes). Private or removed videos are not.</li>
      <li>If free disk space drops below the minimum, the queue pauses.</li></ul>`)],
    ['playlists', T('Playlisty a kanály', 'Playlists and channels'), T(`
      <ul><li>Odkaz na playlist nebo kanál se rozbalí na jednotlivá videa. Ve frontě jsou seskupená pod jednou položkou (šipkou ji rozbalíte).</li>
      <li>U kanálu se stahuje jen záložka <b>Videa</b>. Shorts a živé přenosy zapnete v Nastavení › Stahování.</li>
      <li>Playlist nebo kanál s více videi než nastavený práh (výchozí 50) se nejdřív <b>potvrdí</b>.</li>
      <li>Mezi videi z jednoho playlistu je krátká náhodná pauza (5–15 s), aby web stahování nezablokoval. Platí pro každé souběžné stahování zvlášť, takže souběžnost se tím nesnižuje.</li>
      <li>Už stažená videa se znovu nestahují. Opakované vložení kanálu stáhne jen nová videa – i když jste některá videa mezitím ručně smazali.</li>
      <li><b>Hromadné odstranění záznamů:</b> zaškrtněte políčka u záznamů (nebo horní políčko pro celou stránku). Filtr „Chyby“ nebo hledání podle názvu pak dovolí tlačítkem <b>Vybrat všech … odpovídajících filtru</b> označit i záznamy na dalších stránkách. Odstraní se jen záznamy, soubory na disku zůstanou.</li>
      <li>Když soubor na úložišti ručně smažete, historie ho označí <b>Soubor smazán</b>. Tlačítkem <b>Stáhnout znovu</b> video vyřadíte z archivu stažených a zařadíte do fronty.</li>
      <li>Videa z playlistu/kanálu se ukládají do <b>samostatné složky</b> pojmenované podle playlistu/kanálu (lze vypnout).</li></ul>`, `
      <ul><li>Playlist and channel links expand into individual videos, grouped under one row in the queue (expand it with the arrow).</li>
      <li>Channels download only the <b>Videos</b> tab. Enable Shorts and live streams in Settings › Downloading.</li>
      <li>Playlists larger than the threshold (default 50) ask for <b>confirmation</b> first.</li>
      <li>There's a short random pause (5–15 s) between videos of one playlist so the site doesn't block you. It applies per parallel download, so it doesn't reduce parallelism.</li>
      <li>Already downloaded videos are skipped. Re-adding a channel only fetches new videos – even if you deleted some files meanwhile.</li>
      <li><b>Bulk delete of records:</b> tick the boxes (or the header box for the whole page). With the “Failed” filter or a title search, <b>Select all … matching the filter</b> also covers other pages. Only records are removed; files on disk stay.</li>
      <li>If you delete a file on the storage, history marks it <b>File deleted</b>. <b>Download again</b> removes it from the download archive and queues it.</li>
      <li>Playlist/channel videos go to a <b>separate folder</b> named after it (can be turned off).</li></ul>`)],
    ['subs', T('Odběry', 'Subscriptions'), T(`
      <ul><li><b>Odběr</b> sleduje kanál nebo playlist a sám stáhne nová videa. Založíte ho v menu <b>Odběry › Přidat odběr</b> (jen v tomto rozhraní).</li>
      <li>U odběru nastavíte <b>vlastní složku</b> pro videa a <b>datum, od kterého</b> se stahuje: jen nové od teď, od minulého měsíce, od zvoleného data, nebo všechno. Starší videa se nestáhnou, nová i budoucí ano.</li>
      <li>Kontrola probíhá sama (výchozí každých 6 hodin, jde změnit v Nastavení › Stahování) a ručně tlačítkem <b>Zkontrolovat teď</b>. Nová videa jdou do běžné fronty. Když je fronta pozastavená, odběry se nekontrolují.</li>
      <li>Pokud první kontrola najde víc videí než práh potvrzení (výchozí 50), počká na vaše potvrzení.</li>
      <li>Každý odběr má v bočním panelu vlastní stránku s <b>frontou</b>, <b>historií</b> a <b>nastavením</b>. Stahování z odběru je vidět i v celkové frontě a historii.</li>
      <li>Živá vysílání a premiéry se přeskočí a zkusí se při další kontrole. Videa, která už jsou v archivu stažených, se nestahují znovu.</li></ul>`, `
      <ul><li>A <b>subscription</b> watches a channel or playlist and downloads new videos on its own. Create one under <b>Subscriptions › Add subscription</b> (this interface only).</li>
      <li>Each subscription has its <b>own folder</b> and a <b>start date</b>: only new from now, since last month, since a date, or everything. Older videos are not downloaded, new and future ones are.</li>
      <li>Checks run automatically (every 6 hours by default, change it in Settings › Downloading) and manually with <b>Check now</b>. New videos go to the normal queue. While the queue is paused, subscriptions are not checked.</li>
      <li>If the first check finds more videos than the confirmation threshold (default 50), it waits for your confirmation.</li>
      <li>Each subscription has its own page in the sidebar with its <b>queue</b>, <b>history</b> and <b>settings</b>. Its downloads also show in the overall queue and history.</li>
      <li>Live streams and premieres are skipped and retried at the next check. Videos already in the download archive are not downloaded again.</li></ul>`)],
    ['naming', T('Pojmenování souborů', 'File naming'), T(`
      <p>Šablonu nastavíte v Nastavení › Pojmenování a složky. U kanálů se použije zvláštní šablona (výchozí <code>{kanál}_{název}</code>).</p>
      <table><tr><th>Token</th><th>Význam</th></tr><tr><td><code>{název}</code></td><td>název videa</td></tr><tr><td><code>{kanál}</code></td><td>kanál / autor</td></tr>
      <tr><td><code>{playlist}</code></td><td>název playlistu</td></tr><tr><td><code>{datum}</code></td><td>datum zveřejnění (RRRR-MM-DD)</td></tr>
      <tr><td><code>{rozlišení}</code></td><td>např. 1080p</td></tr><tr><td><code>{id}</code></td><td>ID videa</td></tr><tr><td><code>{pořadí}</code></td><td>pořadí v playlistu (001)</td></tr></table>
      <p>Když soubor se stejným názvem už existuje, přidá se <code>(2)</code>, <code>(3)</code>… Nic se nepřepisuje. Miniatura dostane vždy stejný název jako video.</p>`, `
      <p>Set the template in Settings › Naming and folders. Channels use a separate template (default <code>{kanál}_{název}</code>). English tokens work too: <code>{title} {channel} {playlist} {date} {resolution} {id} {index}</code>.</p>
      <p>If a file with the same name exists, <code>(2)</code>, <code>(3)</code>… is added. Nothing is overwritten. The thumbnail always gets the same name as the video.</p>`)],
    ['schedule', T('Rychlost a plánování', 'Speed and schedule'), T(`
      <ul><li><b>Omezit rychlost</b>: celkový limit se dělí mezi běžící stahování (u snifferu se limit neuplatní).</li>
      <li><b>Časové okno</b>: stahuje se jen v zadaných hodinách a dnech (okno může jít přes půlnoc, např. 22:00–06:00). Po konci okna se stahování pozastaví a příště naváže.</li></ul>`, `
      <ul><li><b>Speed limit</b>: the total limit is split between running downloads (not applied to the sniffer).</li>
      <li><b>Time window</b>: downloads only run in the given hours and days (may cross midnight, e.g. 22:00–06:00). When the window ends, downloads pause and continue next time.</li></ul>`)],
    ['cookies', T('Přihlášení a cookies', 'Login and cookies'), T(`
      <p>Pro členský nebo věkově omezený obsah potřebuje aplikace cookies z prohlížeče, ve kterém jste na webu přihlášení.</p>
      <ol><li>Nainstalujte do prohlížeče rozšíření pro export <code>cookies.txt</code> (formát Netscape) – ve Firefoxu např. „cookies.txt“, v Chrome „Get cookies.txt LOCALLY“.</li>
      <li>Na stránce, kde jste přihlášení, cookies exportujte.</li><li>V Nastavení › Přístup a síť zvolte <b>cookies.txt</b> a soubor nahrajte.</li></ol>
      <p>Cookies časem vyprší (YouTube je navíc průběžně mění) – když se znovu objeví „vyžadováno přihlášení“, soubor exportujte a nahrajte znovu.</p>
      <p>Když VidDown běží přímo na Macu nebo Windows (ne v Dockeru), lze místo souboru zvolit <b>Z prohlížeče</b> – yt-dlp si cookies přečte z profilu prohlížeče <b>na tom počítači, kde VidDown běží</b>. V Dockeru tato volba není.</p>`, `
      <p>Members-only or age-restricted content needs cookies from a browser where you're logged in.</p>
      <ol><li>Install a <code>cookies.txt</code> export extension (Netscape format), e.g. "Get cookies.txt LOCALLY".</li><li>Export cookies on the site where you're logged in.</li>
      <li>In Settings › Access and network choose <b>cookies.txt</b> and upload the file.</li></ol><p>On Mac and Windows you can pick <b>From browser</b> instead (not in Docker).</p>`)],
    ['telegram', T('Telegram bot', 'Telegram bot'), T(`
      <ol><li>V Telegramu otevřete <b>@BotFather</b>, pošlete <code>/newbot</code> a zvolte jméno a uživatelské jméno bota.</li>
      <li>Token vložte v Nastavení › Telegram › Zadat token.</li>
      <li>Napište svému botovi cokoli. Odpoví zprávou s vaším <b>chat ID</b>. To vložte do pole Povolené chat ID.</li></ol>
      <p>Bot pak reaguje <b>jen na vás</b>. Po odeslání odkazu odpoví počtem nalezených videí a rozlišením prvního. Podle nastavení stáhne hned, nebo se zeptá tlačítky. Playlist nad prahem se vždy potvrdí.</p>
      <p>Bot dále hlásí jen <b>chyby</b> (u playlistu jednou souhrnně na konci) a neúspěšné aktualizace enginů.</p>
      <p>Příkazy: <code>/fronta</code> <code>/historie</code> <code>/engine</code> <code>/aktualizovat</code> <code>/pomoc</code></p>
      <p>Použijte <b>samostatného bota</b> – jeden token nemůže číst zprávy ve dvou aplikacích zároveň (např. s ComfyUI).</p>`, `
      <ol><li>In Telegram open <b>@BotFather</b>, send <code>/newbot</code>, pick a name and username.</li><li>Paste the token in Settings › Telegram › Set token.</li>
      <li>Message your bot. It replies with your <b>chat ID</b>. Paste it into Allowed chat ID.</li></ol>
      <p>The bot then answers <b>only you</b>. After a link it replies with the number of videos and the first one's resolution, then downloads right away or asks with buttons (see settings). Playlists over the threshold always ask.</p>
      <p>Afterwards it only reports <b>errors</b> (one summary per playlist) and failed engine updates.</p>
      <p>Commands: <code>/fronta</code> <code>/historie</code> <code>/engine</code> <code>/aktualizovat</code> <code>/pomoc</code></p>
      <p>Use a <b>dedicated bot</b> – one token can't be read by two apps at once.</p>`)],
    ['engines', T('Enginy a aktualizace', 'Engines and updates'), T(`
      <p>VidDown používá tři enginy: <b>yt-dlp</b> (stahování z webů), <b>Deno</b> (JavaScript, který YouTube vyžaduje) a <b>ffmpeg</b> (spojování a převod). Prohlížeč <b>Chromium</b> pro sniffer se aktualizuje spolu s aplikací.</p>
      <ol><li>Nová verze se stáhne vedle staré.</li><li>Otestuje se nová i stará verze (yt-dlp načte metadata testovací URL).</li><li>Aktivní se stane jen tehdy, když nová projde.</li>
      <li>Selžou-li obě, je to síť nebo web a nic se nezmění.</li><li>Uchovává se několik posledních verzí – tlačítkem <b>Vrátit</b> se kdykoli vrátíte.</li></ol>
      <p>Když je v systému novější ffmpeg, použije se systémový, dokud ho v Enginech neaktualizujete.</p>`, `
      <p>VidDown uses <b>yt-dlp</b> (site downloads), <b>Deno</b> (JavaScript YouTube needs) and <b>ffmpeg</b> (merging, converting). <b>Chromium</b> for the sniffer updates with the app.</p>
      <ol><li>The new version downloads next to the old one.</li><li>Both are tested (yt-dlp loads metadata of the test URL).</li><li>It becomes active only if it passes.</li>
      <li>If both fail it's the network or the site and nothing changes.</li><li>Several versions are kept – use <b>Use</b> to roll back anytime.</li></ol>`)],
    ['cli', T('Terminál (CLI)', 'Terminal (CLI)'), `
      <table><tr><td><code>viddown</code></td><td>${T('spustí aplikaci a otevře GUI', 'starts the app and opens the GUI')}</td></tr>
      <tr><td><code>viddown serve</code></td><td>${T('spustí aplikaci bez otevření prohlížeče', 'starts without opening the browser')}</td></tr>
      <tr><td><code>viddown add URL [URL…] [--yes]</code></td><td>${T('přidá do fronty (--yes potvrdí velké playlisty)', 'adds to the queue (--yes confirms big playlists)')}</td></tr>
      <tr><td><code>viddown queue</code> / <code>viddown history</code></td><td>${T('vypíše frontu / historii', 'lists queue / history')}</td></tr>
      <tr><td><code>viddown engine status|update|test|rollback</code></td><td>${T('správa enginů', 'engine management')}</td></tr>
      <tr><td><code>viddown config get|set KLÍČ HODNOTA</code></td><td>${T('nastavení', 'settings')}</td></tr>
      <tr><td><code>viddown password</code></td><td>${T('nastaví heslo do GUI', 'sets the GUI password')}</td></tr>
      <tr><td><code>viddown autostart on|off</code></td><td>${T('spouštění po přihlášení do počítače', 'start at login')}</td></tr>
      <tr><td><code>viddown doctor</code></td><td>${T('kontrola závislostí a nastavení', 'checks dependencies and setup')}</td></tr></table>`],
    ['faq', T('Řešení problémů', 'Troubleshooting'), T(`
      <ul><li><b>„Vyžadováno přihlášení“</b> – nastavte cookies (viz výše).</li>
      <li><b>YouTube hlásí chybu</b> – v Enginech klikněte na Aktualizovat u yt-dlp a Deno. YouTube se často mění.</li>
      <li><b>„Na stránce nebylo nalezeno žádné video“</b> – video se možná spouští až po kliknutí nebo je chráněné. Zkuste prodloužit čekání snifferu v Pokročilých.</li>
      <li><b>DRM</b> (Netflix, Disney+ apod.) stáhnout nelze.</li>
      <li><b>Bot neodpovídá</b> – zkontrolujte token a chat ID a že bot neběží v jiné aplikaci.</li>
      <li><b>Logy</b> jsou v datové složce aplikace v podsložce <code>logs</code>.</li></ul>
      <p>Používejte VidDown jen pro obsah, ke kterému máte práva.</p>`, `
      <ul><li><b>"Login required"</b> – set up cookies (see above).</li><li><b>YouTube errors</b> – update yt-dlp and Deno in Engines. YouTube changes often.</li>
      <li><b>"No video found on the page"</b> – it may need a click or be protected. Try a longer sniffer timeout in Advanced.</li>
      <li><b>DRM</b> content (Netflix, Disney+ …) can't be downloaded.</li><li><b>Bot is silent</b> – check token, chat ID, and that no other app uses the bot.</li>
      <li><b>Logs</b> are in the app data folder under <code>logs</code>.</li></ul><p>Only use VidDown for content you have the rights to.</p>`)],
  ];
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Nápověda', 'Help')}</h1><div class="t2" style="margin-top:3px">${T('Jak VidDown používat a co umí', 'How to use VidDown and what it can do')}</div></div><div class="grow"></div>
   <button class="btn primary" id="hwiz">${ic('sparkle', 14)} ${T('Spustit průvodce', 'Run setup guide')}</button></div>
   <div style="display:grid;grid-template-columns:200px minmax(0,1fr);gap:20px;align-items:start"><nav class="toc card" style="padding:8px">${H.map(([id, t]) => `<a href="#help" data-sc="${id}">${t}</a>`).join('')}</nav>
   <div class="col gap14" style="gap:14px">${H.map(([id, t, body]) => `<section class="card help" style="padding:18px 22px" id="h-${id}"><h2>${t}</h2>${body}</section>`).join('')}</div></div>`;
  $('#hwiz').onclick = openWizard;
  $$('[data-sc]').forEach(a => a.onclick = e => { e.preventDefault(); $('#h-' + a.dataset.sc).scrollIntoView({ behavior: 'smooth', block: 'start' }); });
}

/* ------------------------------------------------------------ přihlášení */
function renderLogin() {
  if (App.es) App.es.close();
  $('#app').innerHTML = `<div class="card login"><div class="logo" style="padding:0 0 18px"><div class="mk">${ic('download', 16)}</div>VidDown</div>
   <h2 style="margin-bottom:12px">${T('Přihlášení', 'Sign in')}</h2><form id="lf" class="col gap10"><input class="input" type="password" id="lp" placeholder="${T('Heslo', 'Password')}" autofocus autocomplete="current-password">
   <button class="btn primary lg" type="submit">${T('Přihlásit', 'Sign in')}</button><div id="lerr" class="err fs12"></div></form></div>`;
  $('#lf').onsubmit = async e => { e.preventDefault();
    try { await api('/api/login', { method: 'POST', body: { password: $('#lp').value } }); location.reload(); } catch (er) { $('#lerr').textContent = er.message === 'wrong password' ? T('Nesprávné heslo', 'Wrong password') : er.message; } };
}

boot();
