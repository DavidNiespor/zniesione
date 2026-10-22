'use strict';
// Interfejs zniesione.pl: sklep, panel rolnika (telefon jako pierwszy) i panel administratora. Bez frameworka.
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const nf = (v, d = 1) => v == null ? '–' : Number(v).toLocaleString('pl-PL', {maximumFractionDigits: d});
const zl = v => Number(v).toLocaleString('pl-PL', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' zł';
const hm = iso => new Date(iso).toLocaleTimeString('pl-PL', {hour: '2-digit', minute: '2-digit'});
const day = iso => new Date(iso).toLocaleDateString('pl-PL', {day: 'numeric', month: 'short'});
const today = iso => new Date(iso).toDateString() === new Date().toDateString();

// rodzaje kanałów: w API kody, rolnik widzi polskie nazwy (nadpisywane z /api/kinds)
const KIND = {light: ['💡', 'Światło'], door_open: ['🚪', 'Drzwi: otwórz'], door_close: ['🚪', 'Drzwi: zamknij'], vent: ['🌀', 'Wentylacja'],
  heater: ['🔥', 'Ogrzewanie'], water_heater: ['♨️', 'Grzałka wody'], valve: ['💧', 'Elektrozawór'], pump: ['🚰', 'Pompa'],
  feeder: ['🌾', 'Karmnik'], other: ['🔌', 'Inne']};
const COOL = ['vent'], HEAT = ['heater', 'water_heater'], DOORS = ['door_open', 'door_close'];
const SRC = {manual: 'ręcznie', schedule: 'harmonogram', thermostat: 'termostat', timer: 'automatyczne wyłączenie', auto: 'automatyka'};
const DAYS = [['a', 'Codziennie'], ['w', 'Od poniedziałku do piątku'], ['e', 'W weekendy']];
const STAGES = ['Zamówione', 'Konfiguracja gotowa', 'Wysłane', 'Połączone'];
const MAIN = [['start', '🏠', 'Start'], ['jaja', '🥚', 'Jaja'], ['sterowanie', '🎛️', 'Sterowanie'], ['zamowienia', '📋', 'Zamówienia']];
const MORE = [['klienci', '👥', 'Klienci', 'Kto kupuje i jak się skontaktować'], ['oferta', '🏷️', 'Oferta', 'Cena, opis i położenie gospodarstwa'],
  ['stado', '🐔', 'Stado', 'Kury i notatki o stadzie'], ['sterowniki', '🔌', 'Sterowniki', 'Zamów sterownik, sprawdź dostawę'],
  ['raporty', '📊', 'Raporty', 'Sprzedaż w liczbach'], ['ustawienia', '⚙️', 'Ustawienia', 'Wygląd, konto, wylogowanie']];
const THEMES = {auto: 'automatyczny', light: 'jasny', dark: 'czarny'};

let me = null, current = '', seq = 0, liveN = 0, shopQ = '', hasSun = false;
const DEV = {}, SCH = {}, CHART = {};

// ---------- komunikacja ----------
async function api(m, u, b, h) {
  try {
    const r = await fetch(u, {method: m, headers: {'X-Requested-With': 'zniesione', ...(b !== undefined ? {'Content-Type': 'application/json'} : {}), ...h},
      body: b !== undefined ? JSON.stringify(b) : undefined});
    const t = await r.text(); let d; try { d = JSON.parse(t) } catch (e) { d = t }
    return {ok: r.ok, status: r.status, data: d};
  } catch (e) { return {ok: false, status: 0, data: {error: 'Brak połączenia z internetem. Sprawdź sieć i spróbuj ponownie.'}} }
}
const errMsg = r => r.status === 502 ? 'Kurnik nie odpowiada. Sprawdź zasilanie i internet w kurniku, potem spróbuj ponownie.'
  : (r.data && r.data.error) || 'Coś poszło nie tak (błąd ' + r.status + '). Spróbuj ponownie.';
async function load(u) {
  const r = await api('GET', u);
  if (r.status === 401) { me = null; location.hash = '#/logowanie'; }
  if (!r.ok) throw new Error(errMsg(r));
  return r.data;
}
let toastT;
function toast(t, bad) { const e = $('#toast'); e.textContent = t; e.className = bad ? 'bad s' : 's'; clearTimeout(toastT); toastT = setTimeout(() => e.className = '', 4000) }
function done(r, okMsg) { if (r.ok) { if (okMsg) toast(okMsg); return true } toast(errMsg(r), true); return false }

// ---------- motyw ----------
function theme() { try { return localStorage.getItem('zn-theme') || 'auto' } catch (e) { return 'auto' } }
function setTheme(t) {
  try { localStorage.setItem('zn-theme', t) } catch (e) {}
  if (t === 'auto') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t);
  paintNav(current.split('/')[0]);
  $$('[data-act=settheme]').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === t));
}

// ---------- nawigacja ----------
const route = () => { const p = location.hash.replace(/^#\/?/, '').split('/'); return {name: p[0], arg: p[1] || ''} };
const home = () => !me ? 'sklep' : me.role === 'admin' ? 'admin' : 'start';
function go(name) { const h = '#/' + name; if (location.hash !== h) { current = name; location.hash = h } render(true) }
function paintNav(name) {
  const farmer = me && me.role === 'farmer', th = theme();
  const tb = `<button data-act="theme" aria-label="Motyw: ${THEMES[th]}. Zmień motyw" title="Motyw: ${THEMES[th]}">${th === 'dark' ? '🌙' : th === 'light' ? '☀️' : '◐'}</button>`;
  $('#hnav').innerHTML = !me ? `<button data-act="go" data-v="sklep">Sklep</button><button data-act="go" data-v="logowanie">Zaloguj / Zarejestruj</button>${tb}`
    : `${tb}<button data-act="logout">Wyloguj</button>`;
  document.body.classList.toggle('nav-on', !!farmer);
  $('#side').hidden = $('#bottom').hidden = !farmer;
  if (!farmer) return;
  const cur = k => k === name || (k === 'wiecej' && MORE.some(m => m[0] === name)) ? ' aria-current="page"' : '';
  const b = ([k, i, t]) => `<button data-act="go" data-v="${k}"${cur(k)}><span class="i" aria-hidden="true">${i}</span>${t}</button>`;
  $('#bottom').innerHTML = [...MAIN, ['wiecej', '☰', 'Więcej']].map(b).join('');
  $('#side').innerHTML = [...MAIN, ...MORE].map(b).join('');
}

const VIEWS = {
  sklep: {fn: vShop}, logowanie: {fn: vAuth},
  start: {fn: vStart, role: 'farmer', live: true}, jaja: {fn: vEggs, role: 'farmer'}, sterowanie: {fn: vControl, role: 'farmer', live: true},
  zamowienia: {fn: vOrders, role: 'farmer'}, wiecej: {fn: vMore, role: 'farmer'}, klienci: {fn: vClients, role: 'farmer'},
  oferta: {fn: vOffer, role: 'farmer'}, stado: {fn: vFlock, role: 'farmer'}, sterowniki: {fn: vDevices, role: 'farmer'},
  raporty: {fn: vReports, role: 'farmer'}, ustawienia: {fn: vSettings, role: 'farmer'},
  admin: {fn: () => vAdmin('dev'), role: 'admin'}, 'admin-cfg': {fn: () => vAdmin('cfg'), role: 'admin'}, 'admin-tools': {fn: () => vAdmin('tools'), role: 'admin'},
};

async function render(focus) {
  const r = route();
  let name = r.name || home(), v = VIEWS[name];
  if (!v) { name = home(); v = VIEWS[name] }
  if (v.role && (!me || me.role !== v.role)) { name = me ? home() : 'logowanie'; v = VIEWS[name] }
  current = name + '/' + r.arg;
  paintNav(name);
  const my = ++seq, m = $('#main');
  m.setAttribute('aria-busy', 'true');
  const slow = setTimeout(() => { if (my === seq) m.innerHTML = '<p class="loading" role="status">Ładuję…</p>' }, 150);
  try {
    const out = await v.fn(r.arg);
    if (my !== seq) return;
    clearTimeout(slow);
    m.innerHTML = typeof out === 'string' ? out : out.html;
    if (out.after) out.after();
  } catch (e) {
    if (my !== seq) return;
    clearTimeout(slow);
    m.innerHTML = `<div class="card empty" role="alert"><div class="i" aria-hidden="true">⚠️</div><h2>Nie udało się wczytać danych</h2><p>${esc(e.message)}</p><button class="pri" data-act="retry">Spróbuj ponownie</button></div>`;
  }
  m.removeAttribute('aria-busy');
  if (focus) { document.documentElement.scrollTop = 0; const h = $('#main h1'); if (h) { h.tabIndex = -1; h.focus({preventScroll: true}) } }
}
const refresh = () => render(false);
const empty = (icon, title, text, btn) => `<div class="card empty"><div class="i" aria-hidden="true">${icon}</div><h2>${title}</h2><p>${text}</p>${btn || ''}</div>`;

// ---------- sklep i konto ----------
const fld = (l, n, t = 'text', x = '') => `<label for="f-${n}">${l}</label><input id="f-${n}" name="${n}" type="${t}" ${x}>`;
const sel = (l, n, o, cur) => `<label for="f-${n}">${l}</label><select id="f-${n}" name="${n}">${o.map(([v, t]) => `<option value="${esc(v)}"${v == cur ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
function farmCards(fs) {
  return fs.map(f => `<div class="card" data-farm="${f.id}"><h2>${esc(f.name)}</h2><p class="mu">${esc(f.zip)} ${esc(f.city)}${f.breed ? ' · ' + esc(f.breed) : ''}</p>
    ${f.descr ? `<p>${esc(f.descr)}</p>` : ''}<p class="price">${zl(f.price10)} <span class="mu">za 10 szt.</span></p><p class="mu">Dostępne: ${f.stock} opak.</p>
    <button class="pri" data-act="order" data-id="${f.id}" data-name="${esc(f.name)}" ${f.stock < 1 ? 'disabled' : ''}>${f.stock < 1 ? 'Brak jaj' : 'Zamów'}</button></div>`).join('')
    || '<p class="mu">Brak gospodarstw dla tego wyszukiwania. Spróbuj samego początku kodu, np. 45.</p>';
}
async function vShop() {
  const fs = await load('/api/farms?q=' + encodeURIComponent(shopQ));
  return `<h1>Jaja prosto od rolnika</h1><p class="lead">Wpisz kod pocztowy lub miejscowość, wybierz gospodarstwo i zamów. Rolnik potwierdza zamówienie, płacisz przy odbiorze.</p>
    <label for="q">Kod pocztowy lub miejscowość</label><input id="q" value="${esc(shopQ)}" placeholder="np. 45-120" inputmode="search" autocomplete="postal-code">
    <div class="grid" id="farms" style="margin-top:1rem">${farmCards(fs)}</div><div id="orderbox"></div>`;
}
function orderForm(id, name) {
  $('#orderbox').innerHTML = `<div class="card" style="margin-top:1rem"><h2>Zamówienie: ${esc(name)}</h2><form data-f="order" data-id="${id}">
    ${fld('Imię i nazwisko', 'name', 'text', 'required autocomplete="name"')}${fld('Telefon', 'phone', 'tel', 'required autocomplete="tel"')}
    ${fld('Ilość opakowań (po 10 szt.)', 'qty', 'number', 'min="1" max="50" value="1" required inputmode="numeric"')}
    ${sel('Jak często', 'mode', [['once', 'Jednorazowo'], ['weekly', 'Co tydzień'], ['biweekly', 'Co 2 tygodnie']])}
    ${sel('Odbiór', 'pickup', [['pickup', 'Odbiorę osobiście'], ['delivery', 'Dowóz przez rolnika']])}
    <p class="mu">Zamówienie jest wiążące po potwierdzeniu przez rolnika. Płatność przy odbiorze.</p>
    <div class="actions"><button class="pri">Wyślij zamówienie</button><button type="button" data-act="cancelorder">Anuluj</button></div></form></div>`;
  $('#orderbox').scrollIntoView && $('#orderbox').scrollIntoView({block: 'start'});
  $('#f-name').focus({preventScroll: true});
}
function vAuth() {
  return `<h1>Konto rolnika</h1><div class="grid"><div class="card"><h2>Logowanie</h2><form data-f="login">${fld('E-mail', 'email', 'email', 'required autocomplete="username"')}
    ${fld('Hasło', 'password', 'password', 'required autocomplete="current-password"')}<div class="actions"><button class="pri">Zaloguj</button></div></form></div>
    <div class="card"><h2>Rejestracja gospodarstwa</h2><form data-f="register">${fld('E-mail', 'email', 'email', 'required autocomplete="email"').replace(/f-email/g, 'r-email')}
    ${fld('Hasło (min. 8 znaków)', 'password', 'password', 'required minlength="8" autocomplete="new-password"').replace(/f-password/g, 'r-password')}
    ${fld('Nazwa gospodarstwa', 'farm_name', 'text', 'required')}${fld('Miejscowość', 'city')}${fld('Kod pocztowy', 'zip')}
    <div class="actions"><button class="pri">Załóż konto</button></div></form></div></div>`;
}

// ---------- elementy sterowania wspólne dla Startu i Sterowania ----------
const live = d => d.stage >= 3 && d.online;
const title = d => d.addr ? d.addr.charAt(0).toUpperCase() + d.addr.slice(1) : 'Sterownik';
const kname = k => (KIND[k] || KIND.other)[1], kicon = k => (KIND[k] || KIND.other)[0];
function ago(iso) {
  if (!iso) return 'brak odczytów';
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? 'przed chwilą' : m < 60 ? m + ' min temu' : today(iso) ? 'o ' + hm(iso) : day(iso) + ', ' + hm(iso);
}
function doorText(d) {
  const run = d.channels.find(c => DOORS.includes(c.kind) && c.state && c.off_at && new Date(c.off_at) > new Date());
  if (run) return run.kind === 'door_open' ? 'Otwieranie…' : 'Zamykanie…';
  return d.door === 'open' ? 'Otwarte' : d.door === 'closed' ? 'Zamknięte' : 'Nie wiadomo, czy otwarte';
}
function statusBadge(d) {
  const [c, t] = live(d) ? ['ok', 'Połączony'] : d.stage < 3 ? ['wa', STAGES[d.stage]] : ['no', 'Brak połączenia'];
  return `<span class="badge ${c}" data-online="${d.id}">${t}</span>`;
}
const offlineBox = d => `<div class="alert bad" data-offline="${d.id}" ${live(d) || d.stage < 3 ? 'hidden' : ''} role="status"><b>Brak połączenia z kurnikiem</b>
  Ostatni kontakt: <span data-live="${d.id}:seen2">${ago(d.last_seen)}</span>. Sprawdź zasilanie i internet w kurniku. Przyciski włączą się same, gdy połączenie wróci. Harmonogramy możesz zmieniać.</div>`;
const sw = (d, c) => `<button class="sw" data-act="toggle" data-id="${d.id}" data-k="${esc(c.key)}" data-sw="${d.id}:${esc(c.key)}" data-ctl="${d.id}"
  aria-pressed="${!!c.state}" aria-label="${esc(c.name)}" ${live(d) ? '' : 'disabled'}></button>`;
const stTxt = (d, c) => `<span class="mu" data-st="${d.id}:${esc(c.key)}">${c.state ? 'Włączone' : 'Wyłączone'}</span>`;
const lightTile = (d, c) => `<div class="tile"><span class="ti" aria-hidden="true">${kicon(c.kind)}</span><div class="tb"><b>${esc(c.name)}</b>${stTxt(d, c)}</div>${sw(d, c)}</div>`;
const hasDoor = d => d.channels.some(c => c.kind === 'door_open') && d.channels.some(c => c.kind === 'door_close');
const doorTile = d => `<div class="tile"><span class="ti" aria-hidden="true">🚪</span><div class="tb"><b>Drzwi</b><span class="mu" data-door="${d.id}">${doorText(d)}</span></div>
  <div class="seg"><button class="pri" data-act="door" data-v="open" data-id="${d.id}" data-ctl="${d.id}" ${live(d) ? '' : 'disabled'}>Otwórz</button>
  <button data-act="door" data-v="close" data-id="${d.id}" data-ctl="${d.id}" ${live(d) ? '' : 'disabled'}>Zamknij</button></div></div>`;
const readNums = d => `<div class="big2"><div class="num"><span>🌡️ Temperatura</span><b data-live="${d.id}:t">${d.reading && d.reading.t != null ? nf(d.reading.t) + ' °C' : '–'}</b></div>
  <div class="num"><span>💧 Wilgotność</span><b data-live="${d.id}:h">${d.reading && d.reading.h != null ? nf(d.reading.h, 0) + ' %' : '–'}</b></div></div>
  <p class="mu">Ostatni odczyt: <span data-live="${d.id}:seen">${ago(d.last_seen)}</span> · odświeża się co 10 s</p>`;

function patch(d) {
  DEV[d.id] = d;
  const set = (s, t) => $$(s).forEach(e => { if (e.textContent !== t) e.textContent = t });
  set(`[data-live="${d.id}:t"]`, d.reading && d.reading.t != null ? nf(d.reading.t) + ' °C' : '–');
  set(`[data-live="${d.id}:h"]`, d.reading && d.reading.h != null ? nf(d.reading.h, 0) + ' %' : '–');
  set(`[data-live="${d.id}:seen"]`, ago(d.last_seen)); set(`[data-live="${d.id}:seen2"]`, ago(d.last_seen));
  $$(`[data-online="${d.id}"]`).forEach(e => e.outerHTML = statusBadge(d));
  $$(`[data-offline="${d.id}"]`).forEach(e => e.hidden = live(d) || d.stage < 3);
  $$(`[data-ctl="${d.id}"]`).forEach(e => { if (!e.dataset.busy) e.disabled = !live(d) });
  for (const c of d.channels) {
    $$(`[data-sw="${d.id}:${c.key}"]`).forEach(b => b.setAttribute('aria-pressed', !!c.state));
    set(`[data-st="${d.id}:${c.key}"]`, c.state ? 'Włączone' : 'Wyłączone');
  }
  set(`[data-door="${d.id}"]`, doorText(d));
}
async function refreshDevices() {
  const r = await api('GET', '/api/my/devices');
  if (r.ok) r.data.forEach(patch);
}
async function tickLive() {
  const v = VIEWS[current.split('/')[0]];
  if (document.hidden || !me || me.role !== 'farmer' || !v || !v.live) return;
  await refreshDevices();
  $$('[data-log]').forEach(e => reloadLog(+e.dataset.log));
  if (++liveN % 6 === 0) $$('[data-charts]').forEach(e => reloadCharts(+e.dataset.charts));
}

// ---------- Start ----------
async function vStart() {
  const [orders, devs, farm] = await Promise.all([load('/api/my/orders'), load('/api/my/devices'), load('/api/my/farm')]);
  devs.forEach(d => DEV[d.id] = d);
  const pend = orders.filter(o => o.status === 'pending').length, h = new Date().getHours();
  const hi = h < 5 ? 'Dobrej nocy' : h < 12 ? 'Dzień dobry' : h < 18 ? 'Miłego popołudnia' : 'Dobry wieczór';
  const d = devs.find(x => x.stage >= 3);
  let coop;
  if (!d) coop = devs.length ? `<p>Sterownik jest w drodze: ${esc(STAGES[devs[0].stage])}. Sterowanie pojawi się tutaj, gdy połączy się z portalem.</p>`
    : `<p class="mu">Nie masz jeszcze sterownika. Z nim włączysz światło i otworzysz drzwi z telefonu.</p><button class="pri" data-act="go" data-v="sterowniki">Zamów sterownik</button>`;
  else {
    const light = d.channels.find(c => c.kind === 'light');
    coop = `${offlineBox(d)}${readNums(d)}<div class="tiles" style="margin-top:.7rem">${light ? lightTile(d, light) : ''}${hasDoor(d) ? doorTile(d) : ''}</div>
      <div class="actions"><button data-act="go" data-v="sterowanie">Wszystkie urządzenia i harmonogramy</button></div>`;
  }
  return `<section class="hero"><h1>${hi}</h1><p>${esc(farm.name)} · co dziś robimy?</p><div class="acts">
    <button class="act" data-act="go" data-v="jaja/zbior"><span class="i" aria-hidden="true">🥚</span>Zbiór jaj</button>
    <button class="act" data-act="go" data-v="jaja/sprzedaz"><span class="i" aria-hidden="true">🧺</span>Sprzedaż</button>
    <button class="act" data-act="go" data-v="zamowienia"><span class="i" aria-hidden="true">📋</span><span>Zamówienia ${pend ? `<span class="count" aria-label="${pend} czeka na potwierdzenie">${pend}</span>` : ''}</span></button>
    <button class="act" data-act="go" data-v="sterowanie"><span class="i" aria-hidden="true">🎛️</span>Sterowanie</button></div></section>
    <section class="card"><div class="dev-h"><h2>🐔 Stan kurnika</h2>${d ? statusBadge(d) : ''}</div>${coop}</section>
    <section class="card"><h2>🥚 Jaja na stanie</h2><p><b style="font-size:1.6rem">${farm.stock}</b> opak. po 10 szt. · ${zl(farm.price10)} za opakowanie</p></section>`;
}

// ---------- Jaja ----------
async function vEggs(arg) {
  const f = await load('/api/my/farm');
  const form = (dir, id, icon, h, txt, btn) => `<form class="card" data-f="eggs" data-dir="${dir}" id="f-${id}"><h2>${icon} ${h}</h2><p class="mu">${txt}</p>
    <label for="n-${id}">Liczba opakowań (po 10 jaj)</label><input id="n-${id}" name="n" type="number" min="1" max="500" value="1" required inputmode="numeric">
    <div class="actions"><button class="pri">${btn}</button></div></form>`;
  return {html: `<h1>Jaja</h1><div class="card"><span class="mu">Na stanie</span><b class="hero-num" data-stock>${f.stock}</b><span>opakowań po 10 szt.</span>
    <p class="mu">Cena: ${zl(f.price10)} za opakowanie · <a href="#/oferta">zmień w Ofercie</a></p></div><div class="grid">
    ${form(1, 'zbior', '🥚', 'Zbiór jaj', 'Ile pełnych opakowań dziś zebrano? Dodamy je do stanu w sklepie.', 'Dodaj do stanu')}
    ${form(-1, 'sprzedaz', '🧺', 'Sprzedaż na miejscu', 'Sprzedane bez zamówienia w portalu, np. sąsiadom. Odejmiemy je ze stanu.', 'Odejmij ze stanu')}</div>`,
  after: () => { const i = arg && $(`#n-${arg}`); if (i) { i.focus(); i.select && i.select() } }};
}

// ---------- Zamówienia, Klienci, Raporty ----------
const MODE = {once: 'Jednorazowe', weekly: 'Co tydzień', biweekly: 'Co 2 tygodnie'};
function orderRow(o) {
  return `<div class="orow" data-order="${o.id}"><div><b>${esc(o.name)}</b> · <a href="tel:${esc(o.phone.replace(/\s/g, ''))}">${esc(o.phone)}</a><br>
    ${o.qty} opak. · ${zl(o.total)}<br><span class="mu">${MODE[o.mode]} · ${o.pickup === 'pickup' ? 'odbiór osobisty' : 'dowóz'} · ${day(o.created)}</span></div>
    <div class="seg">${o.status === 'pending' ? `<button class="pri" data-act="confirm" data-id="${o.id}">Potwierdź</button><button data-act="reject" data-id="${o.id}">Odrzuć</button>`
    : `<span class="badge ${o.status === 'confirmed' ? 'ok' : 'no'}">${o.status === 'confirmed' ? 'Potwierdzone' : 'Odrzucone'}</span>`}</div></div>`;
}
async function vOrders() {
  const os = await load('/api/my/orders'), p = os.filter(o => o.status === 'pending'), rest = os.filter(o => o.status !== 'pending');
  return `<h1>Zamówienia</h1><section class="card"><h2>Czekają na potwierdzenie (${p.length})</h2>${p.map(orderRow).join('')
    || '<p class="mu">Nie ma nowych zamówień. Gdy klient zamówi jaja, zobaczysz je tutaj.</p>'}</section>
    ${rest.length ? `<section class="card"><h2>Rozpatrzone</h2>${rest.map(orderRow).join('')}</section>` : ''}`;
}
async function vClients() {
  const os = await load('/api/my/orders'), by = {};
  for (const o of os) {
    const k = o.phone.replace(/\s/g, ''), c = by[k] = by[k] || {name: o.name, phone: o.phone, n: 0, qty: 0, last: o.created, regular: false};
    c.n++; if (o.status === 'confirmed') c.qty += o.qty; if (o.mode !== 'once') c.regular = true; if (o.created > c.last) c.last = o.created;
  }
  const cs = Object.values(by).sort((a, b) => b.last.localeCompare(a.last));
  if (!cs.length) return '<h1>Klienci</h1>' + empty('👥', 'Nie ma jeszcze klientów', 'Klienci pojawią się tutaj po pierwszym zamówieniu. Uzupełnij ofertę, żeby łatwiej Cię znaleźli.',
    '<button class="pri" data-act="go" data-v="oferta">Uzupełnij ofertę</button>');
  return `<h1>Klienci</h1><section class="card"><ul class="list">${cs.map(c => `<li><span class="ti" aria-hidden="true">👤</span><div class="tb"><b>${esc(c.name)}${c.regular ? ' <span class="pill">stały klient</span>' : ''}</b>
    <span class="mu">${c.n} zamówień · odebrane ${c.qty} opak. · ostatnio ${day(c.last)}</span></div><a class="btn" href="tel:${esc(c.phone.replace(/\s/g, ''))}">📞 Zadzwoń</a></li>`).join('')}</ul></section>`;
}
async function vReports() {
  const os = await load('/api/my/orders'), since = Date.now() - 30 * 864e5;
  const ok = os.filter(o => o.status === 'confirmed'), m = ok.filter(o => new Date(o.created) >= since);
  const stat = (l, v, s) => `<div class="num"><span>${l}</span><b>${v}</b>${s ? `<span>${s}</span>` : ''}</div>`;
  return `<h1>Raporty</h1><section class="card"><h2>Ostatnie 30 dni</h2><div class="stats">${stat('Sprzedane opakowania', m.reduce((s, o) => s + o.qty, 0))}
    ${stat('Przychód', zl(m.reduce((s, o) => s + o.total, 0)))}${stat('Potwierdzone zamówienia', m.length)}</div></section>
    <section class="card"><h2>Od początku</h2><div class="stats">${stat('Wszystkie zamówienia', os.length)}${stat('Czeka na potwierdzenie', os.filter(o => o.status === 'pending').length)}
    ${stat('Odrzucone', os.filter(o => o.status === 'rejected').length)}${stat('Przychód', zl(ok.reduce((s, o) => s + o.total, 0)))}</div></section>`;
}

// ---------- Więcej, Oferta, Stado, Ustawienia ----------
function vMore() {
  return `<h1>Więcej</h1><div class="mtiles">${MORE.map(([k, i, t, s]) => `<button class="mtile" data-act="go" data-v="${k}"><span class="i" aria-hidden="true">${i}</span><b>${t}</b><small>${s}</small></button>`).join('')}</div>`;
}
async function vOffer() {
  const f = await load('/api/my/farm'), v = x => `value="${esc(x ?? '')}"`;
  return `<h1>Oferta</h1><form data-f="offer"><section class="card"><h2>Gospodarstwo w sklepie</h2>${fld('Nazwa', 'name', 'text', v(f.name) + ' required')}
    <div class="row"><div>${fld('Miejscowość', 'city', 'text', v(f.city))}</div><div>${fld('Kod pocztowy', 'zip', 'text', v(f.zip))}</div></div>
    ${fld('Rodzaj chowu', 'breed', 'text', v(f.breed) + ' placeholder="np. wolny wybieg"')}${fld('Opis dla klientów', 'descr', 'text', v(f.descr))}
    <div class="row"><div>${fld('Cena za 10 szt. (zł)', 'price10', 'number', `step="0.5" min="0" ${v(f.price10)} inputmode="decimal"`)}</div>
    <div>${fld('Dostępne opakowania', 'stock', 'number', `min="0" ${v(f.stock)} inputmode="numeric"`)}</div></div></section>
    <section class="card"><h2>📍 Położenie gospodarstwa</h2><p class="mu">Potrzebne do harmonogramów od wschodu i zachodu słońca. Klienci go nie widzą.</p>
    <div class="row"><div>${fld('Szerokość geograficzna', 'lat', 'number', `step="any" min="-90" max="90" ${v(f.lat)} placeholder="np. 50.67" inputmode="decimal"`)}</div>
    <div>${fld('Długość geograficzna', 'lon', 'number', `step="any" min="-180" max="180" ${v(f.lon)} placeholder="np. 17.93" inputmode="decimal"`)}</div></div>
    <div class="actions"><button type="button" data-act="geo">📍 Użyj mojej lokalizacji</button></div></section>
    <div class="actions"><button class="pri">Zapisz ofertę</button></div></form>`;
}
function vFlock() {
  return '<h1>Stado</h1>' + empty('🐔', 'Ewidencja stada wkrótce', 'Tu zapiszesz liczbę kur, daty wstawienia i notatki. Na razie możesz prowadzić zbiór jaj i sprzedaż.',
    '<button class="pri" data-act="go" data-v="jaja/zbior">Zapisz zbiór jaj</button>');
}
function vSettings() {
  const t = theme();
  return `<h1>Ustawienia</h1><section class="card"><h2>Wygląd</h2><p class="mu">Automatyczny dopasowuje się do ustawień telefonu.</p><div class="seg" role="group" aria-label="Motyw">
    ${Object.entries(THEMES).map(([k, n]) => `<button data-act="settheme" data-v="${k}" aria-pressed="${k === t}">${n[0].toUpperCase() + n.slice(1)}</button>`).join('')}</div></section>
    <section class="card"><h2>Konto</h2><p>Zalogowano jako <b>${esc(me.email)}</b></p><div class="actions"><button data-act="logout">Wyloguj</button></div></section>`;
}

// ---------- Sterowniki (zamawianie i dostawa) ----------
const steps = s => `<ol class="steps" aria-label="Etap: ${STAGES[s]}">${STAGES.map((t, i) => `<li class="${i <= s ? 'done' : ''}"${i === s ? ' aria-current="step"' : ''}>${t}</li>`).join('')}</ol>`;
const yamlBlock = d => `<details data-yamlbox="${d.id}"><summary data-act="yaml" data-id="${d.id}">Konfiguracja ESPHome</summary><p class="mu">Dla instalatora: wgraj ją do sterownika w ESPHome.</p>
  <pre data-yaml="${d.id}">Ładuję…</pre><button data-act="copy" data-id="${d.id}">📋 Kopiuj</button></details>`;
async function vDevices() {
  const [devs, ct] = await Promise.all([load('/api/my/devices'), load('/api/catalog')]);
  const def = ct.find(m => m.default) || ct[0];
  return `<h1>Sterowniki</h1><section class="card"><h2>Zamów sterownik</h2><p class="mu">Do portalu można podłączyć tylko sterowniki kupione u nas. Przychodzą przygotowane do pracy.</p>
    <form data-f="devorder"><label for="f-model">Model</label><select id="f-model" name="model">${ct.map(m => `<option value="${m.id}"${m === def ? ' selected' : ''}>${esc(m.name)}${m.cheapest ? ' · najtańszy' : ''}</option>`).join('')}</select>
    <p data-cheap ${def && def.cheapest ? '' : 'hidden'}><span class="pill">Najtańszy w ofercie</span></p>
    ${fld('Adres dostawy', 'addr', 'text', 'required autocomplete="street-address"')}
    <details><summary>Ustawienia zaawansowane</summary>${sel('Połączenie z portalem', 'tunnel', [['', 'Domyślne (zalecane)'], ['wg', 'WireGuard'], ['ts', 'Tailscale'], ['mqtt', 'MQTT (Shelly)']])}</details>
    <div class="actions"><button class="pri">Zamów sterownik</button></div></form></section>
    ${devs.map(d => `<section class="card" data-dev="${d.id}"><div class="dev-h"><div><h2>${esc(title(d))}</h2><p class="mu">${esc(d.model_name)} · nr ${esc(d.code)}</p></div>${statusBadge(d)}</div>
    ${steps(d.stage)}${d.stage >= 3 ? '<button data-act="go" data-v="sterowanie">Przejdź do sterowania</button>' : '<p class="mu">Sterowanie włączy się, gdy sterownik połączy się z portalem.</p>'}
    ${d.stage >= 1 ? yamlBlock(d) : ''}</section>`).join('')}`;
}

// ---------- Sterowanie ----------
function when(mode, t, off) {
  if (mode === 'time') return 'o ' + t;
  const [a, b] = mode === 'sunrise' ? ['wschodzie', 'wschodem'] : ['zachodzie', 'zachodem'];
  return off === 0 ? `o ${a} słońca` : off < 0 ? `${-off} min przed ${b} słońca` : `${off} min po ${a} słońca`;
}
function dur(s) {
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return [h && h + ' godz.', m && m + ' min', x && x + ' s'].filter(Boolean).join(' ');
}
function describe(s, door) {
  const a = when(s.mode, s.t_on, s.offset_min);
  if (door) return `Otwórz ${a}, zamknij ${when(s.off_mode, s.t_off, s.off_offset_min)}`;
  return `Włącz ${a}, ` + (s.duration_s ? `wyłącz po ${dur(s.duration_s)}` : `wyłącz ${when(s.off_mode, s.t_off, s.off_offset_min)}`);
}
function schedList(d) {
  const list = SCH[d.id] || [], wd = new Date().getDay(), todayOk = x => x === 'a' || (x === 'w' ? wd >= 1 && wd <= 5 : wd === 0 || wd === 6);
  if (!list.length) return '<p class="mu">Brak harmonogramów. Dodaj pierwszy poniżej, np. światło od wschodu słońca do 07:00.</p>';
  return `<ul class="list">${list.map(s => {
    const c = d.channels.find(x => x.key === s.ch) || {name: '?', kind: 'other'}, door = c.kind === 'door_open';
    const now = !s.enabled ? 'Wstrzymany' : !todayOk(s.days) ? 'Dziś nie działa (inny dzień)' : s.today_on ? `Dziś ${s.today_on}–${s.today_off}` : 'Dziś nie działa';
    return `<li data-sch="${s.id}"><span class="ti" aria-hidden="true">${door ? '🚪' : kicon(c.kind)}</span><div class="tb"><b>${door ? 'Drzwi' : esc(c.name)}</b>
      <span>${describe(s, door)}</span><span class="mu">${DAYS.find(x => x[0] === s.days)[1]} · ${now}</span></div>
      <div class="seg"><button class="sw" data-act="schtoggle" data-id="${d.id}" data-sid="${s.id}" aria-pressed="${s.enabled}" aria-label="Harmonogram aktywny: ${door ? 'Drzwi' : esc(c.name)}"></button>
      <button class="sm" data-act="schedit" data-id="${d.id}" data-sid="${s.id}">Zmień</button><button class="sm ghost danger" data-act="delsch" data-id="${d.id}" data-sid="${s.id}">Usuń</button></div></li>`;
  }).join('')}</ul>`;
}
function schedForm(d) {
  const tg = d.channels.filter(c => c.kind !== 'door_close').map(c => c.kind === 'door_open'
    ? `<option value="${esc(c.key)}" data-door="1">🚪 Drzwi (otwieranie i zamykanie)</option>` : `<option value="${esc(c.key)}">${kicon(c.kind)} ${esc(c.name)}</option>`).join('');
  const modes = '<option value="time">O godzinie</option><option value="sunrise">Względem wschodu słońca</option><option value="sunset">Względem zachodu słońca</option>';
  const i = n => `s${d.id}-${n}`;
  return `<form class="card" style="background:var(--sf2)" data-f="sched" data-id="${d.id}"><h3 style="margin-top:0" data-formtitle>Nowy harmonogram</h3><input type="hidden" name="sid">
    <label for="${i('ch')}">Czym sterować</label><select id="${i('ch')}" name="ch">${tg}</select>
    <fieldset><legend data-leg="on">Kiedy włączyć</legend><label for="${i('mode')}" class="sr-only">Sposób</label><select id="${i('mode')}" name="mode">${modes}</select>
      <div data-show="mode:time"><label for="${i('t_on')}">Godzina</label><input id="${i('t_on')}" name="t_on" type="time" value="06:00"></div>
      <div data-show="mode:sun" hidden><label for="${i('off1')}">Przesunięcie w minutach (minus = wcześniej)</label><input id="${i('off1')}" name="offset_min" type="number" min="-180" max="180" step="5" value="0" inputmode="numeric"></div></fieldset>
    <fieldset><legend data-leg="off">Kiedy wyłączyć</legend><label for="${i('end')}" class="sr-only">Sposób</label><select id="${i('end')}" name="end">${modes}<option value="dur">Po określonym czasie</option></select>
      <div data-show="end:time"><label for="${i('t_off')}">Godzina</label><input id="${i('t_off')}" name="t_off" type="time" value="18:00"></div>
      <div data-show="end:sun" hidden><label for="${i('off2')}">Przesunięcie w minutach (minus = wcześniej)</label><input id="${i('off2')}" name="off_offset_min" type="number" min="-180" max="180" step="5" value="0" inputmode="numeric"></div>
      <div data-show="end:dur" hidden class="row"><div><label for="${i('dur')}">Czas działania</label><input id="${i('dur')}" name="dur" type="number" min="1" value="5" inputmode="numeric"></div>
      <div><label for="${i('unit')}">Jednostka</label><select id="${i('unit')}" name="unit"><option value="60">minut</option><option value="1">sekund</option></select></div></div></fieldset>
    <label for="${i('days')}">W które dni</label><select id="${i('days')}" name="days">${DAYS.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select>
    <p class="alert" data-nosun hidden>Aby użyć wschodu i zachodu słońca, wpisz położenie gospodarstwa. <a href="#/oferta">Przejdź do Oferty</a></p>
    <div class="actions"><button class="pri" data-submit>Dodaj harmonogram</button><button type="button" data-act="schcancel" hidden>Anuluj zmiany</button></div></form>`;
}
function syncSched(f) {
  const e = f.elements, door = e.ch.selectedOptions[0] && e.ch.selectedOptions[0].dataset.door === '1';
  const durOpt = e.end.querySelector('option[value=dur]');
  durOpt.disabled = durOpt.hidden = door;
  if (door && e.end.value === 'dur') e.end.value = 'time';
  const mode = e.mode.value, end = e.end.value, isSun = v => v === 'sunrise' || v === 'sunset';
  $$('[data-show]', f).forEach(el => { const [k, v] = el.dataset.show.split(':'), cur = k === 'mode' ? mode : end; el.hidden = !(v === 'sun' ? isSun(cur) : cur === v) });
  $('[data-leg=on]', f).textContent = door ? 'Kiedy otworzyć drzwi' : 'Kiedy włączyć';
  $('[data-leg=off]', f).textContent = door ? 'Kiedy zamknąć drzwi' : 'Kiedy wyłączyć';
  $('[data-nosun]', f).hidden = hasSun || !(isSun(mode) || isSun(end));
}
function schedBody(f) {
  const e = f.elements, b = {ch: e.ch.value, mode: e.mode.value, days: e.days.value};
  if (b.mode === 'time') b.t_on = e.t_on.value; else b.offset_min = Math.round(+e.offset_min.value || 0);
  if (e.end.value === 'dur') b.duration_s = Math.round((+e.dur.value || 0) * +e.unit.value);
  else { b.duration_s = null; b.off_mode = e.end.value; if (b.off_mode === 'time') b.t_off = e.t_off.value; else b.off_offset_min = Math.round(+e.off_offset_min.value || 0) }
  return b;
}
function schedFill(f, s) {
  const e = f.elements;
  e.sid.value = s ? s.id : ''; e.ch.value = s ? s.ch : e.ch.options[0].value; e.mode.value = s ? s.mode : 'time';
  e.t_on.value = s && s.t_on || '06:00'; e.offset_min.value = s ? s.offset_min : 0; e.end.value = s ? (s.duration_s ? 'dur' : s.off_mode) : 'time';
  e.t_off.value = s && s.t_off || '18:00'; e.off_offset_min.value = s ? s.off_offset_min : 0; e.days.value = s ? s.days : 'a';
  const ds = s && s.duration_s; e.dur.value = ds ? (ds % 60 ? ds : ds / 60) : 5; e.unit.value = ds && ds % 60 ? '1' : '60';
  $('[data-submit]', f).textContent = s ? 'Zapisz zmiany' : 'Dodaj harmonogram';
  $('[data-formtitle]', f).textContent = s ? 'Zmiana harmonogramu' : 'Nowy harmonogram';
  $('[data-act=schcancel]', f).hidden = !s;
  syncSched(f);
}
function ruleForm(d, c) {
  const r = c.rule, on = !!(r && r.enabled), k = `${d.id}-${esc(c.key)}`, word = COOL.includes(c.kind) ? 'powyżej' : 'poniżej';
  return `<p data-rule="${k}"><b>${on ? `Automatyka: włącz ${word} ${nf(r.threshold)} °C` : 'Automatyka wyłączona'}</b></p>
    <p class="mu">${on ? 'Sterownik sam włącza i wyłącza urządzenie według temperatury.' : `Ustaw temperaturę, a urządzenie samo się włączy ${word} niej.`}</p>
    <div class="row"><div><label for="th${k}">Włącz ${word} (°C)</label><input id="th${k}" name="threshold" type="number" step="0.5" min="-20" max="60"
    value="${r ? r.threshold : COOL.includes(c.kind) ? 25 : 5}" required inputmode="decimal"></div>
    <div class="seg"><button class="${on ? '' : 'pri'}">${on ? 'Zapisz próg' : 'Włącz automatykę'}</button>${on ? `<button type="button" data-act="ruleoff" data-id="${d.id}" data-k="${esc(c.key)}">Wyłącz automatykę</button>` : ''}</div></div>`;
}
function otherTile(d, c) {
  const th = COOL.includes(c.kind) || HEAT.includes(c.kind), k = `${d.id}-${esc(c.key)}`;
  return `<div class="tile"><span class="ti" aria-hidden="true">${kicon(c.kind)}</span><div class="tb"><label for="nm${k}" class="sr-only">Nazwa urządzenia</label>
    <input id="nm${k}" class="nm" value="${esc(c.name)}" data-id="${d.id}" data-k="${esc(c.key)}" maxlength="60"><span class="mu">${kname(c.kind)} · ${stTxt(d, c)}</span></div>${sw(d, c)}
    ${th ? `<form class="auto" data-f="rule" data-id="${d.id}" data-k="${esc(c.key)}">${ruleForm(d, c)}</form>` : ''}</div>`;
}
async function saveRule(f, threshold, enabled) {
  const {id, k} = f.dataset;
  if (done(await api('PUT', `/api/my/devices/${id}/rules/${k}`, {threshold, enabled}), enabled ? 'Termostat zapisany' : 'Automatyka wyłączona')) {
    const c = DEV[id].channels.find(x => x.key === k);
    c.rule = {threshold, enabled};
    f.innerHTML = ruleForm(DEV[id], c);
    $('input', f).focus();
  }
}
function logList(items) {
  if (!items.length) return '<li class="mu">Nic się jeszcze nie działo.</li>';
  return items.map(e => {
    const what = e.kind === 'door_open' && e.state ? 'Drzwi: otwieranie' : e.kind === 'door_close' && e.state ? 'Drzwi: zamykanie'
      : DOORS.includes(e.kind) ? 'Drzwi: silnik zatrzymany' : `${e.ch_name}: ${e.state ? 'włączono' : 'wyłączono'}`;
    return `<li><time datetime="${esc(e.at)}">${today(e.at) ? hm(e.at) : day(e.at) + ' ' + hm(e.at)}</time><span>${DOORS.includes(e.kind) ? '🚪' : kicon(e.kind)} ${esc(what)}</span>
      <span class="src">${SRC[e.src] || esc(e.src)}</span>${e.ok ? '' : '<span class="tag-bad">✕ nie udało się</span>'}</li>`;
  }).join('');
}
async function reloadLog(id, limit) {
  const box = $(`[data-log="${id}"]`); if (!box) return;
  const r = await api('GET', `/api/my/devices/${id}/log?limit=${limit || box.dataset.limit || 15}`);
  if (r.ok) { if (limit) box.dataset.limit = limit; const h = logList(r.data); if (box.innerHTML !== h) box.innerHTML = h }
}
async function reloadSchedules(id) {
  const r = await api('GET', `/api/my/devices/${id}/schedules`);
  if (r.ok) { SCH[id] = r.data; $(`[data-sl="${id}"]`).innerHTML = schedList(DEV[id]) }
}
function controlCard(d, log, rd) {
  const head = `<div class="dev-h"><div><h2 id="dh${d.id}">${esc(title(d))}</h2><p class="mu">${esc(d.model_name)} · nr ${esc(d.code)}</p></div>${statusBadge(d)}</div>`;
  if (d.stage < 3) return `<section class="card" data-dev="${d.id}" aria-labelledby="dh${d.id}">${head}${steps(d.stage)}
    <p>Sterowanie będzie dostępne, gdy sterownik połączy się z portalem.</p>${d.stage >= 1 ? yamlBlock(d) : ''}</section>`;
  const lights = d.channels.filter(c => c.kind === 'light'), others = d.channels.filter(c => c.kind !== 'light' && !DOORS.includes(c.kind));
  return `<section class="card" data-dev="${d.id}" aria-labelledby="dh${d.id}">${head}${offlineBox(d)}
    <h3>Odczyty</h3>${readNums(d)}<div class="charts" data-charts="${d.id}">${charts(d.id, rd)}</div>
    <details><summary>Odczyty w tabeli</summary><div class="tw" data-table="${d.id}">${table(rd)}</div></details>
    <h3>Światło i drzwi</h3><p class="mu">Przekaźniki otwierania i zamykania drzwi nigdy nie działają jednocześnie. Silnik drzwi wyłącza się sam.</p>
    <div class="tiles">${lights.map(c => lightTile(d, c)).join('')}${hasDoor(d) ? doorTile(d) : ''}</div>
    ${hasDoor(d) ? `<form data-f="doorrun" data-id="${d.id}" class="row" style="max-width:28rem"><div><label for="dr${d.id}">Czas pracy silnika drzwi (sekundy)</label>
      <input id="dr${d.id}" name="door_run_s" type="number" min="1" max="300" value="${d.door_run_s}" required inputmode="numeric"></div><div><button>Zapisz czas</button></div></form>` : ''}
    ${others.length ? `<h3>Pozostałe urządzenia</h3><div class="tiles">${others.map(c => otherTile(d, c)).join('')}</div>` : ''}
    <h3>Harmonogramy</h3><div data-sl="${d.id}">${schedList(d)}</div>${schedForm(d)}
    <h3>Ostatnie zdarzenia</h3><ul class="list log" data-log="${d.id}">${logList(log)}</ul><button class="sm" data-act="logmore" data-id="${d.id}">Pokaż więcej zdarzeń</button>
    ${yamlBlock(d)}
    <details><summary>Przypisanie przekaźników</summary><p class="mu">Ustaw, co jest podłączone do którego przekaźnika w sterowniku.</p>
      ${d.channels.map((c, n) => `<form data-f="chan" data-id="${d.id}" data-k="${esc(c.key)}" class="row"><div><label for="cn${d.id}-${n}">Przekaźnik ${n + 1}: nazwa</label>
      <input id="cn${d.id}-${n}" name="name" value="${esc(c.name)}" required maxlength="60"></div><div><label for="ck${d.id}-${n}">Rodzaj</label><select id="ck${d.id}-${n}" name="kind">
      ${Object.keys(KIND).map(k => `<option value="${k}"${k === c.kind ? ' selected' : ''}>${kname(k)}</option>`).join('')}</select></div><div><button>Zapisz</button></div></form>`).join('')}</details></section>`;
}
async function vControl() {
  const [devs, farm] = await Promise.all([load('/api/my/devices'), load('/api/my/farm')]);
  hasSun = farm.lat != null && farm.lon != null;
  if (!devs.length) return '<h1>Sterowanie</h1>' + empty('🎛️', 'Nie masz jeszcze sterownika', 'Ze sterownikiem włączysz światło, otworzysz drzwi i ustawisz harmonogramy z telefonu.',
    '<button class="pri" data-act="go" data-v="sterowniki">Zamów sterownik</button>');
  const extra = await Promise.all(devs.map(d => d.stage >= 3 ? Promise.all([load(`/api/my/devices/${d.id}/schedules`),
    load(`/api/my/devices/${d.id}/log?limit=15`), load(`/api/my/devices/${d.id}/readings?hours=24`)]) : [[], [], []]));
  devs.forEach((d, i) => { DEV[d.id] = d; SCH[d.id] = extra[i][0] });
  return {html: '<h1>Sterowanie</h1>' + devs.map((d, i) => controlCard(d, extra[i][1], extra[i][2])).join(''),
    after: () => $$('form[data-f=sched]').forEach(syncSched)};
}

// ---------- wykresy: osobno temperatura i wilgotność (bez dwóch osi), kreska i dymek po najechaniu ----------
function chart(id, pts, key, unit, cls, label) {
  const v = pts.filter(p => p[key] != null);
  if (v.length < 2) return `<figure><figcaption>${label}</figcaption><p class="mu">Za mało odczytów, aby narysować wykres. Sprawdź, czy czujnik jest podłączony.</p></figure>`;
  const W = 320, H = 130, L = 30, R = 40, T = 10, B = 20, t0 = +new Date(v[0].at), t1 = +new Date(v[v.length - 1].at);
  let lo = Math.min(...v.map(p => p[key])), hi = Math.max(...v.map(p => p[key]));
  const pad = Math.max(1, (hi - lo) * .15); lo = Math.floor(lo - pad); hi = Math.ceil(hi + pad);
  const x = t => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R), y = val => T + (hi - val) / (hi - lo) * (H - T - B);
  const xy = v.map(p => [x(+new Date(p.at)), y(p[key])]), last = v[v.length - 1], cid = id + ':' + key;
  CHART[cid] = {v, xy, key, unit, W};
  const grid = [lo, (lo + hi) / 2, hi].map(g => `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}"/><text x="${L - 4}" y="${y(g) + 3}" text-anchor="end">${nf(g, 0)}</text>`).join('');
  const [lx, ly] = xy[xy.length - 1];
  return `<figure><figcaption>${label}</figcaption><div class="chart" data-cid="${cid}"><svg viewBox="0 0 ${W} ${H}" role="img"
    aria-label="${label}: od ${nf(Math.min(...v.map(p => p[key])))} do ${nf(Math.max(...v.map(p => p[key])))}${unit}, teraz ${nf(last[key])}${unit}">${grid}
    <text x="${L}" y="${H - 4}">${hm(v[0].at)}</text><text x="${W - R}" y="${H - 4}" text-anchor="end">teraz</text>
    <polyline class="ln ${cls}" points="${xy.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ')}"/>
    <circle class="dot ${cls}" cx="${lx}" cy="${ly}" r="4"/><text class="lv" x="${lx + 6}" y="${ly + 4}">${nf(last[key])}${unit}</text>
    <line class="cross" data-cross y1="${T}" y2="${H - B}" x1="0" x2="0" visibility="hidden"/><circle class="dot ${cls}" data-hdot r="4" cx="0" cy="0" visibility="hidden"/></svg>
    <div class="tip" hidden></div></div></figure>`;
}
const charts = (id, rd) => chart(id, rd, 't', ' °C', 't', 'Temperatura, ostatnie 24 h') + chart(id, rd, 'h', ' %', 'h', 'Wilgotność, ostatnie 24 h');
function table(rd) {
  const rows = [], seen = new Set();
  for (const p of rd.slice().reverse()) { const k = new Date(p.at).getHours(); if (!seen.has(k)) { seen.add(k); rows.push(p) } }
  return rows.length ? `<table><thead><tr><th>Godzina</th><th>Temperatura</th><th>Wilgotność</th></tr></thead><tbody>${rows.map(p =>
    `<tr><td>${hm(p.at)}</td><td>${nf(p.t)} °C</td><td>${nf(p.h, 0)} %</td></tr>`).join('')}</tbody></table>` : '<p class="mu">Brak odczytów z ostatniej doby.</p>';
}
async function reloadCharts(id) {
  const r = await api('GET', `/api/my/devices/${id}/readings?hours=24`);
  if (!r.ok) return;
  const box = $(`[data-charts="${id}"]`), tb = $(`[data-table="${id}"]`);
  if (box) box.innerHTML = charts(id, r.data);
  if (tb) tb.innerHTML = table(r.data);
}
function hover(e) {
  const box = e.target.closest && e.target.closest('.chart'); if (!box) return;
  const c = CHART[box.dataset.cid], svg = $('svg', box); if (!c || !svg.getBoundingClientRect) return;
  const rect = svg.getBoundingClientRect(); if (!rect.width) return;
  const px = (e.clientX - rect.left) / rect.width * c.W;
  let i = 0; c.xy.forEach((p, n) => { if (Math.abs(p[0] - px) < Math.abs(c.xy[i][0] - px)) i = n });
  const [cx, cy] = c.xy[i], cr = $('[data-cross]', box), dot = $('[data-hdot]', box), tip = $('.tip', box);
  cr.setAttribute('x1', cx); cr.setAttribute('x2', cx); cr.setAttribute('visibility', 'visible');
  dot.setAttribute('cx', cx); dot.setAttribute('cy', cy); dot.setAttribute('visibility', 'visible');
  tip.replaceChildren(Object.assign(document.createElement('b'), {textContent: nf(c.v[i][c.key]) + c.unit}), document.createTextNode(' · ' + hm(c.v[i].at)));
  tip.style.left = Math.min(85, Math.max(15, cx / c.W * 100)) + '%'; tip.hidden = false;
}
function unhover(e) {
  const box = e.target.closest && e.target.closest('.chart'); if (!box || box.contains(e.relatedTarget)) return;
  $$('[data-cross],[data-hdot]', box).forEach(el => el.setAttribute('visibility', 'hidden')); $('.tip', box).hidden = true;
}

// ---------- administrator ----------
async function vAdmin(tab) {
  const tabs = `<div class="tabs" role="navigation" aria-label="Sekcje administratora">${[['admin', 'Sterowniki'], ['admin-cfg', 'Konfiguracja'], ['admin-tools', 'Narzędzia']].map(([k, t]) =>
    `<button data-act="go" data-v="${k}"${k === (tab === 'dev' ? 'admin' : 'admin-' + tab) ? ' aria-current="page"' : ''}>${t}</button>`).join('')}</div>`;
  let h = '<h1>Administrator</h1>' + tabs;
  if (tab === 'dev') {
    const [dv, fm, ct] = await Promise.all([load('/api/admin/devices'), load('/api/farms'), load('/api/catalog')]);
    const fo = fm.map(f => [f.id, f.name]), fname = id => (fm.find(f => f.id === id) || {}).name || 'bez farmy';
    h += `<section class="card"><h2>Dodaj sterownik do farmy</h2><form data-f="adddev"><div class="row"><div>${sel('Model', 'model', ct.map(m => [m.id, m.name + (m.cheapest ? ' · najtańszy' : '')]), (ct.find(m => m.default) || {}).id)}</div>
      <div>${sel('Farma', 'farm_id', fo)}</div><div>${fld('Adres lub opis', 'addr')}</div></div><div class="actions"><button class="pri">Dodaj</button></div></form></section>`;
    h += dv.map(d => `<section class="card" data-dev="${d.id}"><div class="dev-h"><div><h2>${esc(d.code)}</h2><p class="mu">${esc(d.model_name)} · ${esc(fname(d.farm_id))}</p></div>
      <span class="badge ${d.online ? 'ok' : 'no'}">${d.online ? 'online' : 'offline'}</span></div>${steps(d.stage)}
      <div class="row"><div><label for="fm${d.id}">Przypisana farma</label><select id="fm${d.id}" class="fm">${fo.map(([v, t]) => `<option value="${v}"${v === d.farm_id ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
      <div><button data-act="assign" data-id="${d.id}">Przypisz do farmy</button></div></div>
      <div class="actions"><button class="pri" data-act="stage" data-id="${d.id}" data-s="${d.stage}" ${d.stage >= 3 ? 'disabled' : ''}>${d.stage >= 3 ? 'Wszystkie etapy zakończone'
      : 'Następny etap: ' + STAGES[d.stage + 1]}</button></div>
      <details><summary>Dane techniczne</summary><p>Połączenie: ${esc(d.tunnel)} · adres VPN: ${esc(d.ip)} · dostawa: ${esc(d.addr)}</p><p>Klucz API: <code>${esc(d.api_key)}</code></p></details>
      <details><summary>Odczyt testowy</summary><form data-f="reading" data-key="${esc(d.api_key)}"><div class="row"><div>${fld('Temperatura (°C)', 't', 'number', 'step="0.1" value="21"').replace(/f-t"/g, `rt${d.id}"`)}</div>
      <div>${fld('Wilgotność (%)', 'h', 'number', 'value="60"').replace(/f-h"/g, `rh${d.id}"`)}</div><div><button>Wyślij odczyt</button></div></div></form></details></section>`).join('');
  } else if (tab === 'cfg') {
    const c = await load('/api/admin/config');
    h += `<section class="card"><h2>Tunel WireGuard</h2><form data-f="cfg">${fld('Adres serwera', 'wg_endpoint', 'text', `value="${esc(c.wg_endpoint)}"`)}${fld('Port', 'wg_port', 'text', `value="${esc(c.wg_port)}"`)}
      ${fld('Podsieć (3 oktety)', 'net', 'text', `value="${esc(c.net)}"`)}<div class="actions"><button class="pri">Zapisz</button></div></form></section>`;
  } else h += `<section class="card"><h2>Silnik harmonogramów i termostatu</h2><p class="mu">Uruchamia jeden obieg: zaplanowane wyłączenia, harmonogramy, drzwi i termostat. Wysyła tylko różnice.</p>
    <button class="pri" data-act="tick">Uruchom silnik teraz</button><pre id="tickout" hidden></pre></section>`;
  return h;
}

// ---------- zdarzenia ----------
const ACT = {
  go: b => go(b.dataset.v), retry: () => refresh(),
  theme: () => setTheme({auto: 'light', light: 'dark', dark: 'auto'}[theme()]), settheme: b => setTheme(b.dataset.v),
  async logout() { await api('POST', '/api/auth/logout'); me = null; go('sklep') },
  order: b => orderForm(b.dataset.id, b.dataset.name), cancelorder: () => { $('#orderbox').innerHTML = '' },
  async confirm(b) { if (done(await api('POST', `/api/my/orders/${b.dataset.id}/confirm`), 'Zamówienie potwierdzone')) await refresh() },
  async reject(b) { if (done(await api('POST', `/api/my/orders/${b.dataset.id}/reject`), 'Zamówienie odrzucone')) await refresh() },
  async toggle(b) {
    const {id, k} = b.dataset, on = b.getAttribute('aria-pressed') !== 'true', c = DEV[id] && DEV[id].channels.find(x => x.key === k);
    b.dataset.busy = 1; b.disabled = true;
    done(await api('POST', `/api/my/devices/${id}/channels/${k}`, {state: on}), `${c ? c.name : 'Urządzenie'}: ${on ? 'włączone' : 'wyłączone'}`);
    delete b.dataset.busy; await refreshDevices(); reloadLog(+id);
  },
  async door(b) {
    const {id, v} = b.dataset, d = DEV[id], bs = $$(`[data-act=door][data-id="${id}"]`);
    bs.forEach(x => { x.dataset.busy = 1; x.disabled = true });
    done(await api('POST', `/api/my/devices/${id}/door`, {action: v}), `Drzwi: ${v === 'open' ? 'otwieranie' : 'zamykanie'} (${d ? d.door_run_s : 20} s)`);
    bs.forEach(x => delete x.dataset.busy); await refreshDevices(); reloadLog(+id);
  },
  async schtoggle(b) { const {id, sid} = b.dataset; if (done(await api('PATCH', `/api/my/devices/${id}/schedules/${sid}`, {enabled: b.getAttribute('aria-pressed') !== 'true'}), 'Harmonogram zmieniony')) await reloadSchedules(id) },
  async delsch(b) { const {id, sid} = b.dataset; if (done(await api('DELETE', `/api/my/devices/${id}/schedules/${sid}`), 'Harmonogram usunięty')) await reloadSchedules(id) },
  schedit(b) { const f = $(`form[data-f=sched][data-id="${b.dataset.id}"]`); schedFill(f, SCH[b.dataset.id].find(s => s.id == b.dataset.sid)); f.scrollIntoView && f.scrollIntoView({block: 'center'}); f.elements.ch.focus() },
  schcancel: b => schedFill(b.closest('form'), null),
  ruleoff: b => saveRule(b.closest('form'), +b.closest('form').elements.threshold.value, false),
  logmore(b) { reloadLog(+b.dataset.id, 100); b.hidden = true },
  async yaml(b) {
    const pre = $(`[data-yaml="${b.dataset.id}"]`); if (pre.dataset.loaded) return;
    const r = await api('GET', `/api/my/devices/${b.dataset.id}/yaml`);
    pre.textContent = typeof r.data === 'string' ? r.data : errMsg(r); if (r.ok) pre.dataset.loaded = 1;
  },
  async copy(b) {
    const t = $(`[data-yaml="${b.dataset.id}"]`).textContent;
    try { await navigator.clipboard.writeText(t); toast('Skopiowano konfigurację') } catch (e) {
      const s = getSelection(), r = document.createRange(); r.selectNodeContents($(`[data-yaml="${b.dataset.id}"]`)); s.removeAllRanges(); s.addRange(r);
      toast('Zaznaczono konfigurację. Skopiuj ją przytrzymując palec lub Ctrl+C.');
    }
  },
  geo() {
    if (!navigator.geolocation) return toast('Ta przeglądarka nie udostępnia lokalizacji. Wpisz ją ręcznie.', true);
    navigator.geolocation.getCurrentPosition(p => { const f = $('form[data-f=offer]'); f.elements.lat.value = p.coords.latitude.toFixed(4); f.elements.lon.value = p.coords.longitude.toFixed(4); toast('Wpisano położenie. Zapisz ofertę.') },
      () => toast('Nie udało się pobrać lokalizacji. Wpisz ją ręcznie.', true), {timeout: 10000});
  },
  async assign(b) { if (done(await api('PATCH', `/api/admin/devices/${b.dataset.id}`, {farm_id: +b.closest('.card').querySelector('.fm').value}), 'Przypisano')) await refresh() },
  async stage(b) { if (done(await api('PATCH', `/api/admin/devices/${b.dataset.id}`, {stage: +b.dataset.s + 1}), 'Etap zwiększony')) await refresh() },
  async tick() {
    const r = await api('POST', '/api/admin/tick');
    if (done(r, 'Silnik uruchomiony')) { const p = $('#tickout'); p.textContent = r.data.sent.length ? r.data.sent.map(([c, k, s, ok]) => `${c} · ${k} → ${s ? 'włącz' : 'wyłącz'} · ${ok ? 'OK' : 'błąd'}`).join('\n') : 'Brak zmian do wysłania.'; p.hidden = false }
  },
};
const num = v => v === '' || v == null ? null : +v;
const FORMS = {
  async order(f, v) {
    if (done(await api('POST', `/api/farms/${f.dataset.id}/orders`, {...v, qty: +v.qty}))) {
      toast('Zamówienie wysłane. Czeka na potwierdzenie rolnika.'); $('#orderbox').innerHTML = '';
      $('#farms').innerHTML = farmCards(await load('/api/farms?q=' + encodeURIComponent(shopQ)));
    }
  },
  login: auth, register: auth,
  async eggs(f, v) {
    const cur = (await load('/api/my/farm')).stock, n = Math.round(+v.n), dir = +f.dataset.dir, next = cur + dir * n;
    if (!(n > 0)) return toast('Podaj liczbę opakowań większą od zera.', true);
    if (next < 0) return toast(`Na stanie jest tylko ${cur} opak.`, true);
    if (done(await api('PUT', '/api/my/farm', {stock: next}), dir > 0 ? `Dodano ${n} opak. Na stanie: ${next}` : `Odjęto ${n} opak. Na stanie: ${next}`)) {
      $('[data-stock]').textContent = next; f.reset();
    }
  },
  async offer(f, v) {
    const b = {...v, price10: +v.price10, stock: +v.stock, lat: num(v.lat), lon: num(v.lon)};
    if (done(await api('PUT', '/api/my/farm', b), 'Zapisano ofertę')) hasSun = b.lat != null && b.lon != null;
  },
  async devorder(f, v) { if (done(await api('POST', '/api/my/device-orders', {model: v.model, tunnel: v.tunnel || undefined, addr: v.addr}), 'Zamówienie sterownika złożone')) await refresh() },
  async sched(f) {
    const id = f.dataset.id, sid = f.elements.sid.value, b = schedBody(f);
    const r = await api(sid ? 'PATCH' : 'POST', `/api/my/devices/${id}/schedules${sid ? '/' + sid : ''}`, b);
    if (done(r, sid ? 'Harmonogram zmieniony' : 'Harmonogram dodany')) { schedFill(f, null); await reloadSchedules(id) }
  },
  rule: (f, v) => saveRule(f, +v.threshold, true),
  async doorrun(f, v) { if (done(await api('PATCH', `/api/my/devices/${f.dataset.id}`, {door_run_s: Math.round(+v.door_run_s)}), 'Zapisano czas pracy silnika drzwi')) await refreshDevices() },
  async chan(f, v) { if (done(await api('PATCH', `/api/my/devices/${f.dataset.id}/channels/${f.dataset.k}`, v), 'Zapisano przekaźnik')) await refresh() },
  async adddev(f, v) { if (done(await api('POST', '/api/admin/devices', {model: v.model, farm_id: +v.farm_id, addr: v.addr}), 'Sterownik dodany')) await refresh() },
  async cfg(f, v) { if (done(await api('PUT', '/api/admin/config', v), 'Zapisano konfigurację')) await refresh() },
  async reading(f, v) { if (done(await api('POST', '/api/device/readings', {t: +v.t, h: +v.h}, {'X-Api-Key': f.dataset.key}), 'Odczyt wysłany')) await refresh() },
};
async function auth(f, v) {
  const r = await api('POST', '/api/auth/' + f.dataset.f, v);
  if (done(r)) { me = await load('/api/me'); go(home()) }
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-act]');
  if (!b || b.disabled || !ACT[b.dataset.act]) return;
  if (b.tagName !== 'SUMMARY') e.preventDefault();
  await ACT[b.dataset.act](b);
});
document.addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target, h = FORMS[f.dataset.f], btn = f.querySelector('button:not([type=button])');
  if (!h || (btn && btn.disabled)) return;
  if (btn) btn.disabled = true;
  try { await h(f, Object.fromEntries(new FormData(f))) } finally { if (btn && btn.isConnected) btn.disabled = false }
});
document.addEventListener('input', async e => {
  if (e.target.id !== 'q') return;
  shopQ = e.target.value; const q = shopQ, r = await api('GET', '/api/farms?q=' + encodeURIComponent(q));
  if (r.ok && q === shopQ && $('#farms')) $('#farms').innerHTML = farmCards(r.data);
});
document.addEventListener('change', async e => {
  const t = e.target, f = t.form;
  if (f && f.dataset.f === 'sched') syncSched(f);
  if (f && f.dataset.f === 'devorder' && t.name === 'model') $('[data-cheap]', f).hidden = !/najtańszy/.test(t.selectedOptions[0] ? t.selectedOptions[0].textContent : '');
  if (t.classList.contains('nm')) {
    const {id, k} = t.dataset;
    if (!t.value.trim()) { t.value = DEV[id].channels.find(x => x.key === k).name; return toast('Nazwa nie może być pusta.', true) }
    if (done(await api('PATCH', `/api/my/devices/${id}/channels/${k}`, {name: t.value}), 'Zapisano nazwę')) DEV[id].channels.find(x => x.key === k).name = t.value.trim();
  }
});
document.addEventListener('pointermove', hover);
document.addEventListener('pointerout', unhover);
addEventListener('hashchange', () => { const r = route(); if ((r.name || home()) + '/' + r.arg !== current) render(true) });
setInterval(tickLive, 10000);
(async () => {
  const [r, k] = await Promise.all([api('GET', '/api/me'), api('GET', '/api/kinds')]);
  if (r.ok) me = r.data;
  if (k.ok) k.data.forEach(x => { if (KIND[x.id]) KIND[x.id][1] = x.name });
  await render(false);
})();
