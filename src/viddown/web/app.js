'use strict';
/* VidDown – webové GUI (varianta B: postranní panel a přehled) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let LANG = 'cs';
const T = (cs, en) => (LANG === 'en' && en !== undefined ? en : cs);

const ICONS = {
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

const App = { view: 'queue', session: null, st: null, settings: null, engines: null, hist: { items: [], q: '', status: '', days: 30, offset: 0 },
  expanded: new Set(), drag: null, es: null, timer: null, wizardShown: false };

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
const pct = p => p == null ? '' : Math.floor(p * 100) + ' %';
const srcIcon = s => ({ telegram: ic('send', 12), cli: ic('terminal', 12) }[s] || ic('download', 12));
const srcName = s => ({ telegram: 'Telegram', cli: 'CLI' }[s] || 'GUI');
const methodBadge = m => m ? `<span class="badge ${m === 'sniffer' ? 'b-sn' : 'b-yt'}">${m === 'ytdlp' ? 'yt-dlp' : m}</span>` : '<span class="badge b-n">—</span>';
function applyTheme(theme) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
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
  App.view = (location.hash || '#queue').slice(1);
  $('#app').innerHTML = '<div class="layout"><aside class="side" id="side"></aside><main class="main" id="mainwrap"><div class="main-in" id="main"></div></main></div>';
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
  if (App.view === 'queue' && !App.drag) renderQueueDyn();
}
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== App.view) { App.view = v; render(); } });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => App.settings && applyTheme(App.settings.values.theme));
function go(v) { location.hash = v; }

function render() {
  clearInterval(App.timer); App.timer = null;
  renderSide();
  const freshSettings = async () => { const r = await act(() => api('/api/settings')); if (r) App.settings = r; if (App.view === 'settings') renderSettings(); };
  const views = { queue: renderQueue, history: renderHistory, settings: freshSettings, engines: renderEngines, help: renderHelp };
  (views[App.view] || renderQueue)();
  $('#mainwrap').scrollTop = 0;
}

/* ------------------------------------------------------------ postranní panel */
function renderSide() {
  const st = App.st; const side = $('#side'); if (!side) return;
  const n = st ? st.queue.filter(j => j.kind === 'video' && j.status !== 'running' || j.status === 'running').length : 0;
  const nav = [['queue', 'list', T('Fronta', 'Queue'), n], ['history', 'history', T('Historie', 'History')], ['settings', 'settings', T('Nastavení', 'Settings')],
    ['engines', 'cpu', T('Enginy', 'Engines')], ['help', 'help', T('Nápověda', 'Help')]];
  const tg = st ? st.telegram : { state: 'off' };
  const tgTxt = { ok: T('Telegram bot připojen', 'Telegram bot connected'), off: T('Telegram vypnutý', 'Telegram off'),
    error: T('Telegram: chyba spojení', 'Telegram: connection error'), nochat: T('Telegram: chybí chat ID', 'Telegram: chat ID missing') }[tg.state] || tg.state;
  const disk = st ? st.disk : null;
  const dark = document.documentElement.dataset.theme === 'dark';
  side.innerHTML = `<div class="logo"><div class="mk">${ic('download', 16)}</div>VidDown</div>
  <div class="col gap4 navs">${nav.map(([v, i, l, c]) => `<button class="nav ${App.view === v ? 'on' : ''}" data-go="${v}">${ic(i, 17)}${l}${c ? `<span class="n">${c}</span>` : ''}</button>`).join('')}</div>
  <div class="grow"></div>
  <div class="sfoot col gap8">
   ${disk ? `<div class="card" style="padding:12px;background:var(--surface2)">${disk.same_disk
      ? `<div class="row fs12 t2" style="justify-content:space-between"><span class="row gap6">${ic('hdd', 14)} ${T('Disk', 'Disk')}</span><span><b style="color:var(--text)">${fmtBytes(disk.target_free)}</b> ${T('volno', 'free')}</span></div>`
      : `<div class="row fs12 t2" style="justify-content:space-between" title="${esc(disk.dir)}"><span class="row gap6">${ic('folder', 14)} ${T('Cíl', 'Target')}</span>${disk.target_reliable ? `<span><b style="color:var(--text)">${fmtBytes(disk.target_free)}</b> ${T('volno', 'free')}</span>` : `<span class="muted" title="${T('Docker Desktop na macOS u složek z /Volumes (síťové disky) hlásí místo interního disku Macu, proto se nezobrazuje.', 'Docker Desktop on macOS reports the Mac disk for folders from /Volumes (network shares), so it is not shown.')}">${T('nelze zjistit', 'unknown')} ⓘ</span>`}</div>
       <div class="row fs12 t2" style="justify-content:space-between;margin-top:4px" title="${T('Rozpracovaná stahování', 'Downloads in progress')}: ${esc(disk.temp_dir)}"><span class="row gap6">${ic('hdd', 14)} ${T('Dočasná', 'Temp')}</span><span><b style="color:var(--text)">${fmtBytes(disk.temp_free)}</b> ${T('volno', 'free')}</span></div>`}
   <div class="fs11 muted ell" style="margin-top:6px" title="${esc(disk.dir)}">${esc(disk.dir)}</div></div>` : ''}
   <div class="row gap8 fs12 t2" style="padding:6px 6px 0"><span class="dot ${tg.state === 'ok' ? 'g' : tg.state === 'error' ? 'r' : ''}"></span>${tgTxt}</div>
   <div class="row gap8 fs12 t2" style="padding:2px 6px"><span class="row gap6">${ic('moon', 14)} ${T('Tmavý režim', 'Dark mode')}</span><span class="grow"></span><button class="toggle ${dark ? 'on' : ''}" id="darkt" aria-label="dark mode"></button></div>
   <div class="row fs11 muted" style="padding:2px 6px;justify-content:space-between"><span>VidDown ${esc(st ? st.version : '')}</span>
   <span class="row gap4"><button class="btn ghost sm" style="height:22px;padding:0 6px" data-lang="cs">CS</button><button class="btn ghost sm" style="height:22px;padding:0 6px" data-lang="en">EN</button></span></div>
  </div>`;
  $$('[data-go]', side).forEach(b => b.onclick = () => go(b.dataset.go));
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
  return `<div class="qr${pz}${child ? ' child' : ''}" data-row="${j.id}" ${child ? '' : 'draggable="true"'}>
   <span class="grip">${child ? '' : ic('grip', 15)}</span><span class="pos">${pos ?? ''}</span>
   <div class="fade">${thumbHtml(j, child ? 72 : 96, child ? 40 : 54, { cls: isGroup ? 'stack' : '' })}</div>
   <div style="min-width:0"><div class="b6 ell fade" title="${esc(title)}">${esc(title)}</div><div class="mm">${meta}</div></div>
   <div class="fade hide-s">${methodBadge(j.method)}</div><div class="t2 fs12 fade hide-s">${right}</div>
   <div class="acts">${toggle}${acts}<button class="ibtn" title="${T('Odstranit z fronty', 'Remove from queue')}" data-a="cancel" data-id="${j.id}">${ic('x', 15)}</button></div></div>`;
}

function runHtml(j) {
  const p = j.progress; const sn = j.method === 'sniffer';
  return `<div class="card run">${thumbHtml(j, 176, 99, { res: true })}
  <div class="grow"><div class="row gap8"><span class="b6 fs15 ell">${esc(j.title || j.url)}</span>${methodBadge(j.method)}</div>
  <div class="t2 fs12 row gap6" style="margin-top:4px">${esc(j.channel || '')}${j.channel ? ' · ' : ''}${j.height ? j.height + 'p · ' : ''}${T('přidáno přes', 'added via')} ${srcName(j.source)}</div>
  <div class="bar thick ${sn ? 'sn' : ''} ${p == null ? 'ind' : ''}" style="margin-top:14px"><i style="width:${p == null ? 35 : Math.max(1, p * 100)}%"></i></div>
  <div class="row fs12 t2 wrap" style="margin-top:8px;gap:18px"><span><b style="color:var(--text);font-size:13px">${p != null ? pct(p) : j.downloaded ? T('Stahuji…', 'Downloading…') : T('Načítám informace o videu…', 'Fetching video info…')}</b></span>
   <span>${fmtBytes(j.downloaded)}${j.total ? ' ' + T('z', 'of') + ' ' + fmtBytes(j.total) : ''}</span>
   <span class="row gap4">${ic('bolt', 13)} ${fmtSpeed(j.speed)}</span><span class="row gap4">${ic('clock', 13)} ${T('zbývá', 'left')} ${j.eta != null ? fmtDur(j.eta) : '—'}</span></div></div>
  <div class="row gap6" style="align-self:flex-start"><button class="ibtn b" title="${T('Pozastavit', 'Pause')}" data-a="pause" data-id="${j.id}">${ic('pause', 15)}</button><button class="ibtn b" title="${T('Zrušit', 'Cancel')}" data-a="cancel" data-id="${j.id}">${ic('x', 15)}</button></div></div>`;
}

function renderQueueDyn() {
  const box = $('#qdyn'); const st = App.st; if (!box || !st) return;
  const q = st.queue, s = st.stats;
  const top = q.filter(j => !j.parent_id);
  const running = q.filter(j => j.status === 'running');
  const confirm = top.filter(j => j.status === 'confirm');
  const waiting = top.filter(j => j.status !== 'running' && j.status !== 'confirm');
  let html = '';
  if (st.queue_paused) {
    const disk = st.pause_reason === 'disk';
    const target = st.pause_reason === 'target', cook = st.pause_reason === 'cookies';
    if (cook) html += `<div class="banner">${ic('cookie', 18)}<span class="grow">${T('Fronta je pozastavená: cookies nejdou načíst', 'Queue paused: cookies cannot be loaded')} – ${esc((st.cookies_error || '').slice(0, 200))}</span>
      <button class="btn sm" data-go="settings">${T('Nastavení', 'Settings')}</button><button class="btn sm" data-q="resume">${ic('play', 12)} ${T('Pokračovat', 'Resume')}</button></div>`;
    else
    html += `<div class="banner">${ic(disk ? 'hdd' : target ? 'folder' : 'pause', 18)}<span class="grow">${disk ? (st.disk.low_kind === 'temp' ? T('Fronta je pozastavená: v dočasné složce je málo místa', 'Queue paused: low space in the temp folder') + ` (${fmtBytes(st.disk.temp_free)}, ${esc(st.disk.temp_dir)}, min. ${st.disk.min_gb} GB)` : T('Fronta je pozastavená: v cílové složce je málo místa', 'Queue paused: low space in the download folder') + ` (${fmtBytes(st.disk.target_free)}, min. ${st.disk.min_gb} GB)`)
      : target ? T('Fronta je pozastavená: cílová složka není dostupná', 'Queue paused: download folder is not available') + ` – ${esc(st.target_error || st.disk.dir)}`
      : T('Fronta je pozastavená', 'The queue is paused')}</span>${target ? `<button class="btn sm" data-go="settings">${T('Nastavení', 'Settings')}</button>` : ''}
    <button class="btn sm" data-q="resume">${ic('play', 12)} ${T('Pokračovat', 'Resume')}</button></div>`;
  } else if (st.schedule.enabled && !st.in_window) {
    html += `<div class="banner info">${ic('clock', 18)}<span class="grow">${T('Stahuje se jen v časovém okně', 'Downloads only run in the time window')} ${st.schedule.start}–${st.schedule.end}. ${T('Fronta čeká.', 'The queue is waiting.')}</span><button class="btn sm" data-go="settings">${T('Upravit', 'Edit')}</button></div>`;
  }
  html += `<div class="stats">
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
   <button class="btn sm" data-q="${st.queue_paused ? 'resume' : 'pause'}">${ic(st.queue_paused ? 'play' : 'pause', 13)} ${st.queue_paused ? T('Pokračovat', 'Resume queue') : T('Pozastavit frontu', 'Pause queue')}</button></div>`;
  html += running.length ? `<div class="col gap10">${running.map(runHtml).join('')}</div>`
    : `<div class="card empty" style="padding:22px">${T('Nic se právě nestahuje.', 'Nothing is downloading right now.')}</div>`;
  html += `<div class="sec"><h2>${T('Čeká ve frontě', 'Waiting')}</h2><span class="chip"><b>${waiting.length}</b></span><span class="grow"></span><span class="t2 fs12 row gap6">${ic('grip', 14)} ${T('Přetažením změníte pořadí', 'Drag to reorder')}</span></div>`;
  if (!waiting.length && !running.length && !confirm.length) {
    html += `<div class="card empty">${ic('download', 32)}<h3>${T('Fronta je prázdná', 'The queue is empty')}</h3><p>${T('Vložte odkaz na video, playlist nebo kanál do pole nahoře, nebo ho pošlete Telegram botovi.', 'Paste a link to a video, playlist or channel above, or send it to the Telegram bot.')}</p></div>`;
  } else if (waiting.length) {
    let rows = '', n = 0;
    for (const j of waiting) {
      rows += rowHtml(j, ++n);
      if (j.kind !== 'video' && App.expanded.has(j.id)) {
        const kids = q.filter(c => c.parent_id === j.id && c.status !== 'running');
        kids.slice(0, 200).forEach((c, i) => { rows += rowHtml(c, `${n}.${i + 1}`, true); });
        if (kids.length > 200) rows += `<div class="qr child"><span></span><span></span><span></span><span class="fs12 t2">+ ${kids.length - 200}</span></div>`;
      }
    }
    html += `<div class="card qlist" id="qlist">${rows}</div>`;
  }
  box.innerHTML = html;
}

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-a],[data-q],[data-go]'); if (!b || !$('#main').contains(b)) return;
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

/* ------------------------------------------------------------ historie */
const PAGE_SIZES = [25, 50, 100, 200];
function histLimit() { try { const v = +localStorage.getItem('vd_hist_limit'); return PAGE_SIZES.includes(v) ? v : 50; } catch (e) { return 50; } }
async function renderHistory() {
  const H = App.hist; H.limit = histLimit(); H.offset = 0;
  $('#main').innerHTML = `<div class="row gap10 wrap"><h1>${T('Historie', 'History')}</h1><span class="t2" id="htot" style="margin-left:6px"></span><span class="grow"></span>
   <div class="inwrap" style="height:32px;width:260px">${ic('search', 15)}<input id="hq" placeholder="${T('Hledat v historii…', 'Search history…')}" value="${esc(H.q)}"></div>
   <span class="seg" id="hst">${[['', T('Vše', 'All')], ['done', T('Hotovo', 'Done')], ['failed', T('Chyby', 'Failed')], ['cancelled', T('Zrušeno', 'Cancelled')], ['skipped', T('Přeskočeno', 'Skipped')]].map(([v, l]) => `<button class="${H.status === v ? 'on' : ''}" data-v="${v}">${l}</button>`).join('')}</span>
   <select class="input sm" id="hdays" style="width:170px">${[[1, T('Posledních 24 h', 'Last 24 h')], [7, T('Posledních 7 dní', 'Last 7 days')], [30, T('Posledních 30 dní', 'Last 30 days')], [0, T('Vše', 'All time')]].map(([v, l]) => `<option value="${v}" ${H.days === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
   <button class="btn sm" id="hclear">${ic('trash', 13)} ${T('Vymazat historii', 'Clear history')}</button></div>
   <div id="hbulk"></div>
   <div class="card" style="overflow:hidden" id="hlist"><div class="empty"><div class="spin" style="margin:auto"></div></div></div>
   <div class="row gap10 wrap" id="hpager"></div>`;
  let tmr; $('#hq').oninput = e => { clearTimeout(tmr); tmr = setTimeout(() => { H.q = e.target.value; H.offset = 0; resetSel(); loadHistory(); }, 300); };
  $$('#hst button').forEach(b => b.onclick = () => { H.status = b.dataset.v; H.offset = 0; resetSel(); $$('#hst button').forEach(x => x.classList.toggle('on', x === b)); loadHistory(); });
  $('#hdays').onchange = e => { H.days = +e.target.value; H.offset = 0; resetSel(); loadHistory(); };
  $('#hclear').onclick = async () => { if (confirm(T('Smazat celou historii? Stažené soubory zůstanou na disku.', 'Delete all history? Downloaded files stay on disk.'))) { await act(() => api('/api/history', { method: 'DELETE', body: {} }), T('Historie smazána', 'History cleared')); H.offset = 0; loadHistory(); } };
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
    <button class="btn sm danger" id="bsdel">${ic('trash', 13)} ${T('Odstranit vybrané', 'Delete selected')} (${n})</button></div>`;
  const refresh = () => {
    $$('.hsel', $('#hlist')).forEach(c => { c.checked = H.all || H.sel.has(+c.dataset.id); c.closest('.hr').classList.toggle('sel', c.checked); });
    const a = $('#hall'); if (a) a.checked = H.all || (H.items.length > 0 && H.items.every(x => H.sel.has(x.id)));
    bulkBar(matched);
  };
  const b1 = $('#bsall'); if (b1) b1.onclick = () => { H.all = true; refresh(); };
  $('#bsnone').onclick = () => { resetSel(); refresh(); };
  $('#bsdel').onclick = async () => {
    if (!confirm(T(`Odstranit ${n} záznamů z historie? Stažené soubory zůstanou na disku.`, `Delete ${n} records from history? Downloaded files stay on disk.`))) return;
    const body = H.all ? { filter: { q: H.q, status: H.status, days: H.days } } : { ids: [...H.sel] };
    const ok = await act(() => api('/api/history', { method: 'DELETE', body }), T('Záznamy odstraněny', 'Records deleted'));
    if (ok) { resetSel(); H.offset = 0; loadHistory(); }
  };
}
async function loadHistory() {
  const H = App.hist; if (!H.sel) resetSel();
  const r = await act(() => api(`/api/history?q=${encodeURIComponent(H.q)}&status=${H.status}&days=${H.days}&offset=${H.offset}&limit=${H.limit}`)); if (!r) return;
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
    if (a === 'del') { await act(() => api('/api/history', { method: 'DELETE', body: { ids: [id] } })); loadHistory(); }
  });
}
function openPlayer(h, local) {
  if (!h) return;
  const audio = /\.(mp3|m4a|opus|ogg)$/i.test(h.filepath || '');
  const m = modal(`<div class="mh">${ic('play', 18)}<h2 class="ell grow" title="${esc(h.title || '')}">${esc(h.title || h.url)}</h2><button class="ibtn" id="pclose" title="${T('Zavřít', 'Close')}">${ic('x', 16)}</button></div>
   <div class="mb"><${audio ? 'audio' : 'video'} id="pvid" controls autoplay playsinline preload="metadata" src="/api/stream/${h.id}" style="width:100%;${audio ? '' : 'max-height:70vh;background:#000;border-radius:10px;display:block'}"></${audio ? 'audio' : 'video'}>
   <div id="perr" class="banner" style="display:none;margin-top:12px">${ic('alert', 16)}<span class="grow">${T('Tento prohlížeč formát videa neumí přehrát (např. MKV s kodekem AV1/VP9 v Safari). Soubor si stáhněte, nebo použijte Chrome či Firefox.', 'This browser cannot play the video format (e.g. MKV with AV1/VP9 in Safari). Download the file or use Chrome or Firefox.')}</span></div>
   <div class="row gap8 t2 fs12 wrap" style="margin-top:10px">${esc(h.channel || '')}${h.height ? ' · ' + h.height + 'p' : ''} · ${fmtBytes(h.filesize)} · <span class="mono ell" style="max-width:100%">${esc(h.filepath || '')}</span></div></div>
   <div class="mf">${local ? `<button class="btn" id="pfold">${ic('folder', 14)} ${T('Zobrazit ve složce', 'Show in folder')}</button>` : ''}<a class="btn" href="/api/file/${h.id}">${ic('download', 14)} ${T('Stáhnout soubor', 'Download file')}</a><button class="btn primary" id="pclose2">${T('Zavřít', 'Close')}</button></div>`, 'wide');
  m.el.style.width = '960px';
  const v = $('#pvid', m.el);
  v.addEventListener('error', () => { $('#perr', m.el).style.display = 'flex'; });
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
    { k: 'quality', type: 'seg', opts: [['max', ['Maximální', 'Maximum']], ['compat', ['Kompatibilita', 'Compatibility']]], label: ['Kvalita', 'Quality'], hint: ['Kompatibilita = MP4 / H.264 pro starší přehrávače', 'Compatibility = MP4 / H.264 for older players'] },
    { k: 'audio_only', type: 'toggle', label: ['Stahovat jen zvuk', 'Audio only'] },
    { k: 'audio_format', type: 'seg', opts: [['mp3', 'MP3'], ['m4a', 'M4A']], label: ['Formát zvuku', 'Audio format'] },
    { k: 'channel_tabs', type: 'chips', opts: [['videos', ['Videa', 'Videos']], ['shorts', 'Shorts'], ['streams', ['Živé přenosy', 'Live streams']]], label: ['Z kanálu stahovat', 'From channels download'] },
    { k: 'playlist_confirm_threshold', type: 'number', min: 1, suffix: ['videí', 'videos'], label: ['Potvrdit playlist nad', 'Confirm playlists over'], hint: ['Větší playlist nebo kanál se nejdřív potvrdí', 'Larger playlists ask first'] },
    { k: 'live_from_start', type: 'toggle', label: ['Nahrávat živé přenosy od začátku', 'Record live streams from start'], hint: ['Jinak se probíhající přenos přeskočí', 'Otherwise live streams are skipped'] },
    { k: 'subtitles', type: 'toggle', label: ['Titulky', 'Subtitles'], hint: ['Vloží se do souboru videa', 'Embedded into the video file'] },
    { k: 'subtitle_langs', type: 'text', w: 120, label: ['Jazyky titulků', 'Subtitle languages'] },
    { k: 'auto_subtitles', type: 'toggle', label: ['Včetně automatických titulků', 'Include auto-generated'] },
    { k: 'embed_metadata', type: 'toggle', label: ['Vložit metadata a kapitoly', 'Embed metadata and chapters'] },
  ] },
  { icon: 'clock', title: ['Rychlost a plánování', 'Speed and schedule'], col: 0, fields: [
    { k: 'rate_limit_enabled', type: 'toggle', label: ['Omezit rychlost', 'Limit speed'], hint: ['Celkem pro všechna stahování', 'Total for all downloads'] },
    { k: 'rate_limit_mbps', type: 'number', step: 0.5, min: 0.1, suffix: 'MB/s', label: ['Limit', 'Limit'] },
    { k: 'schedule_enabled', type: 'toggle', label: ['Stahovat jen v časovém okně', 'Download only in a time window'] },
    { k: 'schedule_start', type: 'time', label: ['Začátek okna', 'Window start'] },
    { k: 'schedule_end', type: 'time', label: ['Konec okna', 'Window end'] },
    { k: 'schedule_days', type: 'chips', opts: [[0, ['Po', 'Mo']], [1, ['Út', 'Tu']], [2, ['St', 'We']], [3, ['Čt', 'Th']], [4, ['Pá', 'Fr']], [5, ['So', 'Sa']], [6, ['Ne', 'Su']]], label: ['Dny', 'Days'] },
    { k: 'sleep_min', type: 'number', min: 0, suffix: 's', label: ['Pauza mezi videi playlistu od', 'Pause between playlist videos from'] },
    { k: 'sleep_max', type: 'number', min: 0, suffix: 's', label: ['do', 'to'] },
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
  { icon: 'cpu', title: ['Enginy', 'Engines'], col: 0, fields: [
    { k: 'engine_auto_update', type: 'toggle', label: ['Automatické aktualizace', 'Automatic updates'] },
    { k: 'engine_update_hours', type: 'number', min: 1, suffix: 'h', label: ['Interval kontroly', 'Check interval'] },
    { k: 'keep_engine_versions', type: 'number', min: 1, max: 10, label: ['Uchovat verzí', 'Versions to keep'] },
    { k: 'selftest_url', type: 'text', w: 260, label: ['Testovací URL', 'Test URL'], hint: ['Ověřuje se na ní nová verze yt-dlp', 'Used to test new yt-dlp versions'] },
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
    case 'path': ctrl = `<input class="input sm mono fs12" style="width:240px" data-k="${f.k}" data-t="text" value="${esc(v)}" ${dis}><button class="btn sm" data-pick="${f.k}" ${dis}>${ic('folder', 13)} ${T('Vybrat', 'Browse')}</button>`; break;
    case 'static': ctrl = f.html; break;
    case 'template': return `<div class="fld block">${lab()}<input class="input sm mono" style="margin-top:8px" data-k="${f.k}" data-t="text" value="${esc(v)}" ${dis}>
      <div class="row gap6 wrap" style="margin-top:8px">${['{název}', '{kanál}', '{playlist}', '{datum}', '{rozlišení}', '{id}', '{pořadí}'].map(x => `<button class="chip mono" style="height:22px;font-size:11px" data-ins="${f.k}" data-v="${x}">${x}</button>`).join('')}</div>
      <div class="fs12 t2" style="margin-top:8px">${T('Náhled', 'Preview')}: <span class="mono" style="color:var(--text)">${esc(previewName(v))}.mp4</span></div></div>`;
    case 'cookies': { const cf = S.cookies_file; const mode = S.values.cookies_mode;
      return `<div class="fld"><div class="lab"><div class="b5">Cookies</div><div class="hint">${mode === 'browser' ? T('Čte se z profilu prohlížeče na počítači, kde běží VidDown', 'Read from the browser profile on the computer running VidDown') : S.docker ? T('Exportujte cookies.txt z prohlížeče a nahrajte ho (viz Nápověda)', 'Export cookies.txt from your browser and upload it (see Help)') : T('Pro členský a věkově omezený obsah', 'For members-only and age-restricted content')}</div></div>
      <div class="row gap8 wrap" style="justify-content:flex-end"><span class="seg">${[['none', T('Ne', 'Off')], ['file', 'cookies.txt'], ...(S.docker ? [] : [['browser', T('Z prohlížeče', 'From browser')]])].map(([o, l]) => `<button data-k="cookies_mode" data-t="seg" data-v="${o}" class="${mode === o ? 'on' : ''}">${l}</button>`).join('')}</span>
      ${mode === 'file' ? (cf.exists ? `<span class="badge b-ok">${ic('check', 11)} cookies.txt · ${new Date(cf.mtime * 1000).toLocaleDateString()}</span>` : `<span class="badge b-warn">${T('Soubor nenahrán', 'Not uploaded')}</span>`) + `<label class="btn sm">${T('Nahrát', 'Upload')}<input type="file" id="ckfile" accept=".txt" hidden></label>${cf.exists ? `<button class="ibtn" id="ckdel" title="${T('Smazat', 'Delete')}">${ic('trash', 14)}</button>` : ''}` : ''}
      ${mode === 'browser' ? `<select class="input sm" style="width:120px" data-k="cookies_browser" data-t="text">${['chrome', 'firefox', 'safari', 'edge', 'brave', 'opera', 'chromium', 'vivaldi'].map(b => `<option ${S.values.cookies_browser === b ? 'selected' : ''}>${b}</option>`).join('')}</select>` : ''}</div></div>`; }
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

function renderSettings() {
  const S = App.settings; const secs = SECTIONS();
  const card = s => `<div class="card sect"><div class="sh">${ic(s.icon, 16)}<h2>${L(s.title)}</h2></div>${s.fields.map(f => fieldHtml(f, S)).join('')}</div>`;
  $('#main').innerHTML = `<div class="row gap16 wrap"><div><h1>${T('Nastavení', 'Settings')}</h1><div class="t2" style="margin-top:3px">${T('Změny se ukládají automaticky a platí okamžitě', 'Changes save automatically and apply immediately')}</div></div><div class="grow"></div>
   <a class="btn sm" href="/api/settings/export">${ic('download', 13)} ${T('Exportovat', 'Export')}</a><label class="btn sm">${T('Importovat', 'Import')}<input type="file" id="impf" accept=".json" hidden></label>
   <button class="btn sm" id="wizbtn">${ic('sparkle', 13)} ${T('Průvodce nastavením', 'Setup guide')}</button></div>
   <div class="sgrid"><div class="scol">${secs.filter(s => s.col === 0).map(card).join('')}</div><div class="scol">${secs.filter(s => s.col === 1).map(card).join('')}</div></div>`;
  bindSettings($('#main'));
  $('#impf').onchange = async e => { const fd = new FormData(); fd.append('file', e.target.files[0]); const r = await act(() => api('/api/settings/import', { method: 'POST', body: fd }), T('Nastavení načteno', 'Settings imported')); if (r) { App.settings = r; renderSettings(); } };
  $('#wizbtn').onclick = openWizard;
}

function bindSettings(root, after) {
  const rer = () => (after ? after() : renderSettings());
  $$('[data-t]', root).forEach(el => {
    const k = el.dataset.k, t = el.dataset.t, S = App.settings;
    if (t === 'toggle') el.onclick = () => saveSetting(k, !S.values[k], rer);
    if (t === 'seg') el.onclick = () => saveSetting(k, k === 'methods' ? el.dataset.v.split(',') : el.dataset.v, rer);
    if (t === 'chip') el.onclick = () => { const cur = S.values[k].slice(); const v = typeof cur[0] === 'number' || k === 'schedule_days' ? +el.dataset.v : el.dataset.v;
      const i = cur.indexOf(v); i >= 0 ? cur.splice(i, 1) : cur.push(v); if (k === 'channel_tabs' && !cur.length) return toast(T('Vyberte aspoň jednu možnost', 'Pick at least one'), true); saveSetting(k, cur, rer); };
    if (t === 'step') el.onclick = () => saveSetting(k, Math.max(1, Math.min(16, S.values[k] + +el.dataset.d)), rer);
    if (t === 'num' || t === 'text') el.onchange = () => saveSetting(k, el.value, rer);
  });
  $$('[data-ins]', root).forEach(b => b.onclick = () => { const inp = $(`input[data-k="${b.dataset.ins}"]`, root); inp.value += b.dataset.v; saveSetting(b.dataset.ins, inp.value, rer); });
  $$('[data-pick]', root).forEach(b => b.onclick = () => openDirPicker(App.settings.values[b.dataset.pick], p => saveSetting(b.dataset.pick, p, rer)));
  const ck = $('#ckfile', root); if (ck) ck.onchange = async e => { const fd = new FormData(); fd.append('file', e.target.files[0]); const r = await act(() => api('/api/settings/cookies', { method: 'POST', body: fd }), T('Cookies nahrány', 'Cookies uploaded')); if (r) { App.settings = r; rer(); } };
  const ckd = $('#ckdel', root); if (ckd) ckd.onclick = async () => { const r = await act(() => api('/api/settings/cookies', { method: 'DELETE' })); if (r) { App.settings = r; rer(); } };
  const pw = $('#pwbtn', root); if (pw) pw.onclick = () => openPassword(rer);
  const tg = $('#tgbtn', root); if (tg) tg.onclick = () => openToken(rer);
  const tt = $('#tgtest', root); if (tt) tt.onclick = () => act(() => api('/api/telegram/test', { method: 'POST' }), T('Testovací zpráva odeslána', 'Test message sent'));
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
