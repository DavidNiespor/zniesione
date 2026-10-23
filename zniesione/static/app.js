'use strict';
// Interfejs zniesione.pl: sklep, panel rolnika (telefon jako pierwszy) i panel administratora. Bez frameworka.
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const nf = (v, d = 1) => v == null ? '–' : Number(v).toLocaleString('pl-PL', {maximumFractionDigits: d});
const zl = v => Number(v).toLocaleString('pl-PL', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' zł';
const hm = iso => new Date(iso).toLocaleTimeString('pl-PL', {hour: '2-digit', minute: '2-digit'});
const day = iso => new Date(iso).toLocaleDateString('pl-PL', {day: 'numeric', month: 'short'});
const today = iso => new Date(iso).toDateString() === new Date().toDateString();
const stat = (l, v, s) => `<div class="num"><span>${l}</span><b>${v}</b>${s ? `<span>${s}</span>` : ''}</div>`;

// rodzaje kanałów: w API kody, rolnik widzi polskie nazwy (nadpisywane z /api/kinds)
const KIND = {light: ['💡', 'Światło'], door_open: ['🚪', 'Drzwi: otwórz'], door_close: ['🚪', 'Drzwi: zamknij'], vent: ['🌀', 'Wentylacja'],
  heater: ['🔥', 'Ogrzewanie'], water_heater: ['♨️', 'Grzałka wody'], valve: ['💧', 'Elektrozawór'], pump: ['🚰', 'Pompa'],
  feeder: ['🌾', 'Karmnik'], other: ['🔌', 'Inne']};
const COOL = ['vent'], HEAT = ['heater', 'water_heater'], DOORS = ['door_open', 'door_close'];
const SRC = {manual: 'ręcznie', schedule: 'harmonogram', thermostat: 'termostat', timer: 'automatyczne wyłączenie', auto: 'automatyka'};
const DAYS = [['a', 'Codziennie'], ['w', 'Od poniedziałku do piątku'], ['e', 'W weekendy']];
const STAGES = ['Zamówione', 'Konfiguracja gotowa', 'Wysłane', 'Połączone'];
const MAIN = [['start', '🏠', 'Start'], ['jaja', '🥚', 'Jaja'], ['sterowanie', '🎛️', 'Sterowanie'], ['zamowienia', '📋', 'Zamówienia']];
const MORE = [['sprzedaz', '🧺', 'Sprzedaż', 'Zapisz sprzedaż i sposób płatności'], ['klienci', '👥', 'Klienci', 'Kartoteka: zakupy, wpłaty, długi i nadpłaty'], ['oferta', '🏷️', 'Oferta', 'Cena, opis i położenie gospodarstwa'],
  ['stado', '🐔', 'Stado', 'Kury i notatki o stadzie'], ['sterowniki', '🔌', 'Sterowniki', 'Zamów sterownik, sprawdź dostawę'],
  ['raporty', '📊', 'Raporty', 'Sprzedaż i jaja w liczbach'], ['pasza', '🌾', 'Pasza i mieszalnia', 'Magazyn zboża, receptury, mieszanie'], ['wydatki', '🧾', 'Wydatki', 'Pasza, weterynarz, ściółka i inne koszty'], ['wyposazenie', '🧰', 'Wyposażenie', 'Poidła, karmidła, lampy i przeglądy'],
  ['wiedza', '📚', 'Baza wiedzy', 'Porady i instrukcje krok po kroku'],
  ['ustawienia', '⚙️', 'Ustawienia', 'Wygląd, konto, wylogowanie']];
const THEMES = {auto: 'automatyczny', light: 'jasny', dark: 'czarny'};

let me = null, current = '', seq = 0, liveN = 0, shopQ = '', hasSun = false, kbQ = '', kbCat = '';
const DEV = {}, SCH = {}, CHART = {};
let installEvt = null;
const standalone = () => (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
const dismissed = k => { try { return localStorage.getItem('zn-hide-' + k) === '1' } catch (e) { return false } };
addEventListener('beforeinstallprompt', e => { e.preventDefault(); installEvt = e });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});

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
  if (!farmer) { $('#side').innerHTML = $('#bottom').innerHTML = ''; return }
  const cur = k => k === name || (k === 'wiecej' && MORE.some(m => m[0] === name)) ? ' aria-current="page"' : '';
  const b = ([k, i, t]) => `<button data-act="go" data-v="${k}"${cur(k)}><span class="i" aria-hidden="true">${i}</span>${t}</button>`;
  $('#bottom').innerHTML = [...MAIN, ['wiecej', '☰', 'Więcej']].map(b).join('');
  $('#side').innerHTML = [...MAIN, ...MORE].map(b).join('');
}

const VIEWS = {
  sklep: {fn: vShop}, logowanie: {fn: vAuth},
  start: {fn: vStart, role: 'farmer', live: true}, jaja: {fn: vEggs, role: 'farmer'}, sterowanie: {fn: vControl, role: 'farmer', live: true},
  zamowienia: {fn: vOrders, role: 'farmer'}, wiecej: {fn: vMore, role: 'farmer'}, klienci: {fn: vClients, role: 'farmer'}, sprzedaz: {fn: vSale, role: 'farmer'},
  oferta: {fn: vOffer, role: 'farmer'}, stado: {fn: vFlock, role: 'farmer'}, sterowniki: {fn: vDevices, role: 'farmer'},
  raporty: {fn: vReports, role: 'farmer'}, ustawienia: {fn: vSettings, role: 'farmer'}, wiedza: {fn: vKb, role: 'farmer'}, wydatki: {fn: vExpenses, role: 'farmer'}, pasza: {fn: vFeed, role: 'farmer'}, 'admin-import': {fn: vAdminImport, role: 'admin'}, wyposazenie: {fn: vEquipment, role: 'farmer'},
  admin: {fn: () => vAdmin('dev'), role: 'admin'}, 'admin-cfg': {fn: () => vAdmin('cfg'), role: 'admin'}, 'admin-tools': {fn: () => vAdmin('tools'), role: 'admin'},
  'admin-kb': {fn: vAdminKb, role: 'admin'},
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
  const [orders, devs, farm, fin, subs, eq, eg] = await Promise.all([load('/api/my/orders'), load('/api/my/devices'), load('/api/my/farm'),
    load('/api/my/finance?days=1'), load('/api/my/subscriptions'), load('/api/my/equipment'), load('/api/my/eggs?days=1')]);
  const due = subs.filter(x => x.due), checks = eq.filter(x => x.check_due);
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
    <button class="act" data-act="go" data-v="sprzedaz"><span class="i" aria-hidden="true">🧺</span>Sprzedaż</button>
    <button class="act" data-act="go" data-v="zamowienia"><span class="i" aria-hidden="true">📋</span><span>Zamówienia ${pend ? `<span class="count" aria-label="${pend} czeka na potwierdzenie">${pend}</span>` : ''}</span></button>
    <button class="act" data-act="go" data-v="sterowanie"><span class="i" aria-hidden="true">🎛️</span>Sterowanie</button></div></section>
    <section class="card"><div class="dev-h"><h2>🐔 Stan kurnika</h2>${d ? statusBadge(d) : ''}</div>${coop}</section>
    ${due.length || checks.length ? `<section class="card"><h2>🔔 Do zrobienia</h2><ul class="list">${due.map(x => `<li><span class="ti" aria-hidden="true">🔁</span><div class="tb">
      <b>${esc(x.client_name)}: ${x.eggs} szt.</b><span class="mu">stały klient, dostawa do wydania</span></div><button class="pri sm" data-act="go" data-v="sprzedaz/sub-${x.id}">Wydaj</button></li>`).join('')}
      ${checks.map(x => `<li><span class="ti" aria-hidden="true">🧰</span><div class="tb"><b>${esc(x.name)}</b><span class="mu">przegląd ${new Date(x.next_check).toLocaleDateString('pl-PL')}</span></div>
      <button class="sm" data-act="go" data-v="wyposazenie">Pokaż</button></li>`).join('')}</ul></section>` : ''}
    ${eg.reminder_due ? reminderBox() : ''}
    <section class="card"><h2>🥚 Jaja</h2>${poolRows(eg.stock)}<div class="actions"><button data-act="go" data-v="jaja">Zbiór, sortowanie, sklep</button></div></section>
    ${standalone() || dismissed('install') ? '' : `<section class="card" data-installbox><h2>📲 Portal jako aplikacja</h2><p class="mu">Dodaj ikonę na ekran telefonu: portal otworzy się jak zwykła aplikacja.</p>
      <div class="actions"><button class="pri" data-act="install">Dodaj jako aplikację</button><button class="ghost" data-act="dismiss" data-v="install">Nie teraz</button></div>
      <p class="mu" data-installhelp hidden></p></section>`}
    <section class="card"><h2>💰 Kasa i długi</h2><div class="stats">${stat('Dziś wpłynęło', zl(fin.received_total))}
    ${stat('Klienci winni', zl(fin.debts), fin.debtors ? `${fin.debtors} z długiem` : 'nikt nie ma długu')}${fin.overpaid ? stat('Nadpłaty klientów', zl(fin.overpaid)) : ''}</div>
    <div class="actions"><button data-act="go" data-v="klienci">Kartoteka klientów</button></div></section>`;
}

// ---------- Jaja ----------
const EGG = {collect: ['🥚', 'Zbiór'], sort: ['🧽', 'Sortowanie'], sale: ['🧺', 'Sprzedaż'], gift: ['🎁', 'Rozdane'], loss: ['💥', 'Strata'],
  inventory: ['📋', 'Inwentaryzacja']};
function eggText(e) {
  if (e.kind === 'sort') return `${e.eggs} dobrych${e.dirty ? `, ${e.dirty} brudnych` : ''}${e.damaged ? `, ${e.damaged} uszkodzonych` : ''}`;
  if (e.kind === 'inventory') return `${e.eggs > 0 ? '+' : ''}${e.eggs} szt.`;
  return `${e.eggs} szt.${e.kind === 'gift' && e.who ? ' · ' + esc(e.who) : ''}`;
}
const eggLog = es => es.slice(0, 15).map(e => `<li><time datetime="${esc(e.at)}">${today(e.at) ? hm(e.at) : day(e.at)}</time>
  <div class="tb"><b>${EGG[e.kind][0]} ${EGG[e.kind][1]}: ${eggText(e)}</b>${e.note ? `<span class="mu">${esc(e.note)}</span>` : ''}</div></li>`).join('')
  || '<li class="mu">Brak wpisów z ostatnich 30 dni.</li>';
const poolRows = p => `<div class="stats">${p.unsorted ? stat('Do sortowania', p.unsorted + ' szt.', 'zebrane, jeszcze nie posortowane') : ''}
  ${stat('W magazynie (dobre)', p.eggs + ' szt.', '≈ ' + Math.floor(p.eggs / 10) + ' opak.')}
  ${stat('Ogłoszone w sklepie', p.offer_packs + ' opak.', p.offer_packs * 10 + ' szt.')}${stat('Rezerwa stałych klientów', p.reserved + ' szt.')}
  ${p.committed ? stat('Do wydania (zamówienia)', p.committed + ' szt.') : ''}${stat('Wolne', p.free + ' szt.', 'do sprzedaży i rozdania')}</div>`;
const reminderBox = () => `<div class="alert bad" role="status"><b>⏰ Nie wpisano dzisiejszego zbioru</b>Wpisz go teraz, żeby stan jaj się zgadzał.
  <div class="actions" style="margin-top:.5rem"><button class="pri sm" data-act="go" data-v="jaja/zbior">Wpisz zbiór</button></div></div>`;
async function vEggs(arg) {
  const [f, lg] = await Promise.all([load('/api/my/farm'), load('/api/my/eggs?days=30')]), p = lg.stock;
  const gifts = Object.entries(lg.given_to);
  return {html: `<h1>Jaja</h1>${lg.reminder_due ? reminderBox() : ''}<section class="card" data-pools>${poolRows(p)}</section>
    <div class="grid">
    <form class="card" data-f="collect" id="f-zbior"><h2>🥚 Zbiór</h2><p class="mu">Wpisz wszystkie zebrane jaja. Trafią do sortowania.</p>
      <label for="n-zbior">Zebrane jaja (szt.)</label><input id="n-zbior" name="eggs" type="number" min="1" max="100000" required inputmode="numeric">
      <label for="o-zbior">Uwagi</label><input id="o-zbior" name="note" maxlength="200" placeholder="np. kurnik 2">
      <div class="actions"><button class="pri">Zapisz zbiór</button></div></form>
    <form class="card" data-f="sort" id="f-sort"><h2>🧽 Sortowanie</h2><p class="mu">Do sortowania: <b data-unsorted>${p.unsorted} szt.</b>
      Dobre trafią do magazynu. Brudne i uszkodzone nie idą do sprzedaży.</p>
      <div class="row tight"><div><label for="so-g">Dobre</label><input id="so-g" name="good" type="number" min="0" value="${p.unsorted}" inputmode="numeric"></div>
      <div><label for="so-d">Brudne</label><input id="so-d" name="dirty" type="number" min="0" value="0" inputmode="numeric"></div>
      <div><label for="so-u">Uszkodzone</label><input id="so-u" name="damaged" type="number" min="0" value="0" inputmode="numeric"></div></div>
      <p class="mu" data-sortsum aria-live="polite"></p>
      <div class="actions"><button class="pri"${p.unsorted ? '' : ' disabled'}>Zapisz sortowanie</button></div></form>
    <form class="card" data-f="alloc"><h2>🏷️ Sklep i rezerwa</h2><p class="mu">Ile opakowań ogłaszasz w sklepie, a ile sztuk odkładasz dla stałych klientów.</p>
      <div class="row tight"><div><label for="al-o">W sklepie (opak. po 10 szt.)</label><input id="al-o" name="offer_packs" type="number" min="0" value="${p.offer_packs}" required inputmode="numeric"></div>
      <div><label for="al-r">Rezerwa (szt.)</label><input id="al-r" name="reserved" type="number" min="0" value="${p.reserved}" required inputmode="numeric"></div></div>
      ${lg.reserve_needed_7d ? `<p class="mu">Stali klienci w najbliższych 7 dniach: <b>${lg.reserve_needed_7d} szt.</b>
        <button type="button" class="sm" data-act="reserveneed" data-v="${lg.reserve_needed_7d}">Zarezerwuj tyle</button></p>` : ''}
      <p class="mu" data-allocsum aria-live="polite"></p><div class="actions"><button class="pri">Zapisz</button></div></form>
    <form class="card" data-f="gift"><h2>🎁 Rozdane</h2><p class="mu">Jaja dla rodziny i znajomych (np. mama), żeby wiedzieć, ile idzie poza sprzedaż.</p>
      <div class="row tight"><div><label for="gi-n">Ile sztuk</label><input id="gi-n" name="eggs" type="number" min="1" required inputmode="numeric"></div>
      <div><label for="gi-w">Komu</label><input id="gi-w" name="who" list="gi-list" required maxlength="60" placeholder="np. mama"></div></div>
      <datalist id="gi-list">${['Mama', 'Rodzina', ...lg.recipients].filter((x, i, a) => a.indexOf(x) === i).map(w => `<option value="${esc(w)}">`).join('')}</datalist>
      <label for="gi-o">Uwagi</label><input id="gi-o" name="note" maxlength="200">
      ${gifts.length ? `<p class="mu">W 30 dni: ${gifts.map(([w, n]) => `${esc(w)} ${n} szt.`).join(' · ')}</p>` : ''}
      <div class="actions"><button class="pri">Zapisz rozdane</button></div></form></div>
    <div class="card"><h2>🧺 Sprzedaż</h2><p class="mu">Sprzedaż z magazynu, rezerwy albo ogłoszonych opakowań, ze sposobem płatności i kartoteką klienta.</p>
      <div class="actions"><button class="pri" data-act="go" data-v="sprzedaz">Zapisz sprzedaż</button></div>
      <details><summary>💥 Strata (stłuczone, zepsute)</summary><form data-f="loss"><div class="row"><div><label for="ls-n">Ile sztuk</label>
        <input id="ls-n" name="eggs" type="number" min="1" required inputmode="numeric"></div><div><label for="ls-o">Powód</label><input id="ls-o" name="note" maxlength="200" placeholder="np. stłuczone przy pakowaniu"></div></div>
        <div class="actions"><button>Zapisz stratę</button></div></form></details>
      <details><summary>📋 Inwentaryzacja (policzyłem jaja)</summary><p class="mu">Wpisz, ile dobrych jaj naprawdę leży w magazynie. Portal poprawi stan.</p>
        <form data-f="inventory"><div class="row"><div><label for="in-n">Policzone jaja (szt.)</label><input id="in-n" name="eggs" type="number" min="0" value="${p.eggs}" required inputmode="numeric"></div>
        <div><label for="in-o">Uwagi</label><input id="in-o" name="note" maxlength="200"></div></div><div class="actions"><button>Zapisz stan</button></div></form></details></div>
    <section class="card"><h2>Ostatnie wpisy</h2><p class="mu">Z 30 dni: zebrano ${lg.collected} szt. (dobrych ${lg.good}, brudnych ${lg.dirty}, uszkodzonych ${lg.damaged}),
      sprzedano ${lg.sold} szt., rozdano ${lg.given} szt., straty ${lg.lost} szt. Cena w sklepie: ${zl(f.price10)} za 10 szt. (<a href="#/oferta">zmień</a>).</p>
    <ul class="list log" data-egglog>${eggLog(lg.entries)}</ul></section>`,
  after: () => { allocSum($('form[data-f=alloc]'), p); sortSum($('form[data-f=sort]')); const i = arg === 'zbior' && $('#n-zbior'); if (i) i.focus() }};
}
function sortSum(f) {
  const e = f.elements, n = (+e.good.value || 0) + (+e.dirty.value || 0) + (+e.damaged.value || 0), un = POOLS.unsorted || 0;
  $('[data-sortsum]', f).innerHTML = n > un ? `<b class="no">Razem ${n} szt., a do sortowania jest ${un} szt.</b>` : `Razem ${n} z ${un} szt.${un - n ? ` (zostanie ${un - n} do sortowania)` : ''}`;
}
let POOLS = {};
function allocSum(f, p) {
  if (p) POOLS = p;
  const left = POOLS.eggs - POOLS.committed - (+f.elements.offer_packs.value || 0) * 10 - (+f.elements.reserved.value || 0);
  $('[data-allocsum]', f).innerHTML = left < 0 ? `<b class="no">Za mało jaj: brakuje ${-left} szt.</b>` : `Zostanie wolnych: <b>${left} szt.</b>`;
}
async function eggsReload(msg, r) {
  if (!done(r, msg)) return false;
  await refresh();
  return true;
}

// ---------- Zamówienia, Klienci, Raporty ----------
const MODE = {once: 'Jednorazowe', weekly: 'Co tydzień', biweekly: 'Co 2 tygodnie'};
const ORDER_ST = {confirmed: ['ok', 'Potwierdzone, do wydania'], delivered: ['ok', 'Wydane'], rejected: ['no', 'Odrzucone']};
function orderRow(o) {
  const st = ORDER_ST[o.status] || ['', o.status];
  return `<div class="orow" data-order="${o.id}"><div><b>${o.client_id ? `<a href="#/klienci/${o.client_id}">${esc(o.name)}</a>` : esc(o.name)}</b> ·
    <a href="tel:${esc(o.phone.replace(/\s/g, ''))}">${esc(o.phone)}</a><br>
    ${o.qty} opak. · ${zl(o.total)}<br><span class="mu">${MODE[o.mode]} · ${o.pickup === 'pickup' ? 'odbiór osobisty' : 'dowóz'} · ${day(o.created)}</span></div>
    <div class="seg">${o.status === 'pending' ? `<button class="pri" data-act="confirm" data-id="${o.id}">Potwierdź</button><button data-act="reject" data-id="${o.id}">Odrzuć</button>`
    : `<span class="badge ${st[0]}">${st[1]}</span>${o.status === 'confirmed' ? `<button class="pri" data-act="go" data-v="sprzedaz/zam-${o.id}">Wydaj i rozlicz</button>` : ''}`}</div></div>`;
}
const EVERY = n => n === 7 ? 'co tydzień' : n === 14 ? 'co 2 tygodnie' : n === 1 ? 'codziennie' : `co ${n} dni`;
const subRow = x => `<li data-subrow="${x.id}"><span class="ti" aria-hidden="true">🔁</span><div class="tb"><b><a href="#/klienci/${x.client_id}">${esc(x.client_name)}</a> · ${x.eggs} szt. ${EVERY(x.every_days)}</b>
  <span class="mu">${x.active ? (x.due ? '<b class="no">do wydania</b> · ' : '') + 'następna dostawa: ' + new Date(x.next_date).toLocaleDateString('pl-PL') : 'wstrzymane'} · ${PAY[x.method][1]}${x.notes ? ' · ' + esc(x.notes) : ''}</span></div>
  <div class="seg">${x.active && x.due ? `<button class="pri sm" data-act="go" data-v="sprzedaz/sub-${x.id}">Wydaj</button><button class="sm" data-act="subskip" data-id="${x.id}">Pomiń</button>` : ''}
  <button class="sw" data-act="subtoggle" data-id="${x.id}" aria-pressed="${x.active}" aria-label="Aktywne: ${esc(x.client_name)}"></button>
  <button class="sm ghost danger" data-act="subdel" data-id="${x.id}">Usuń</button></div></li>`;
const subForm = (cs, cid) => `<form data-f="sub"><div class="row">${cid ? `<input type="hidden" name="client_id" value="${cid}">` : `<div><label for="sb-c">Klient</label>
  <select id="sb-c" name="client_id" required>${cs.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>`}
  <div><label for="sb-e">Ile jaj (szt.)</label><input id="sb-e" name="eggs" type="number" min="1" max="5000" value="30" required inputmode="numeric"></div>
  <div><label for="sb-d">Co ile dni</label><input id="sb-d" name="every_days" type="number" min="1" max="90" value="7" required inputmode="numeric"></div></div>
  <div class="row"><div><label for="sb-n">Najbliższa dostawa</label><input id="sb-n" name="next_date" type="date" value="${new Date().toISOString().slice(0, 10)}" required></div>
  <div><label for="sb-m">Jak zwykle płaci</label><select id="sb-m" name="method">${Object.entries(PAY).map(([k, [, t]]) => `<option value="${k}"${k === 'later' ? ' selected' : ''}>${t}</option>`).join('')}</select></div></div>
  <label for="sb-u">Uwagi</label><input id="sb-u" name="notes" maxlength="200" placeholder="np. odbiera w sobotę rano">
  <div class="actions"><button class="pri">Dodaj zamówienie cykliczne</button></div></form>`;
async function vOrders() {
  const [os, subs, cs] = await Promise.all([load('/api/my/orders'), load('/api/my/subscriptions'), load('/api/my/clients')]);
  const p = os.filter(o => o.status === 'pending'), c = os.filter(o => o.status === 'confirmed'), due = subs.filter(x => x.due);
  const rest = os.filter(o => !['pending', 'confirmed'].includes(o.status));
  return `<h1>Zamówienia</h1><section class="card"><h2>Czekają na potwierdzenie (${p.length})</h2>${p.map(orderRow).join('')
    || '<p class="mu">Nie ma nowych zamówień. Gdy klient zamówi jaja, zobaczysz je tutaj.</p>'}</section>
    ${c.length ? `<section class="card"><h2>Do wydania (${c.length})</h2><p class="mu">Przy wydaniu wybierasz sposób płatności; dług lub nadpłata trafi do kartoteki klienta.</p>${c.map(orderRow).join('')}</section>` : ''}
    <section class="card"><h2>🔁 Stali klienci: zamówienia cykliczne${due.length ? ` <span class="count">${due.length}</span>` : ''}</h2>
      <p class="mu">Wydanie odejmuje jaja z rezerwy (Jaja → Sklep i rezerwa) i zapisuje płatność w kartotece. Następna dostawa ustawia się sama.</p>
      <ul class="list" data-subs>${subs.map(subRow).join('') || '<li class="mu">Brak zamówień cyklicznych. Dodaj klienta, który bierze jaja regularnie.</li>'}</ul>
      <details${subs.length ? '' : ' open'}><summary>➕ Nowe zamówienie cykliczne</summary>${cs.length ? subForm(cs) : '<p class="mu">Najpierw dodaj klienta w <a href="#/klienci">kartotece</a>.</p>'}</details></section>
    ${rest.length ? `<section class="card"><h2>Rozpatrzone</h2>${rest.map(orderRow).join('')}</section>` : ''}`;
}

// ---------- kartoteka klientów i sprzedaż (jak w e-kurniku) ----------
const PAY = {cash: ['💵', 'Gotówka'], transfer: ['🏦', 'Przelew'], blik: ['📱', 'BLIK'], later: ['⏳', 'Następnym razem (na dług)'], balance: ['📋', 'Z nadpłaty']};
const LEDGER = {sale: 'Zakup', payment: 'Wpłata', refund: 'Zwrot nadpłaty', correction: 'Korekta salda'};
const balInfo = b => b > 0.005 ? {cls: 'no', short: 'Dług ' + zl(b), long: 'Dług: ' + zl(b), sub: 'Klient ma zapłacić'}
  : b < -0.005 ? {cls: 'ok', short: 'Nadpłata ' + zl(-b), long: 'Nadpłata: ' + zl(-b), sub: 'Zapas na kolejne zakupy albo do zwrotu'}
  : {cls: '', short: 'Rozliczony', long: 'Rozliczony', sub: 'Brak długu i nadpłaty'};
const balBadge = b => `<span class="badge ${balInfo(b).cls}">${balInfo(b).short}</span>`;
const clientForm = (c, id) => `<form data-f="client" data-id="${c ? c.id : ''}"><div class="row">
  <div><label for="${id}n">Imię i nazwisko lub nazwa</label><input id="${id}n" name="name" value="${esc(c && c.name)}" required maxlength="100"></div>
  <div><label for="${id}p">Telefon</label><input id="${id}p" name="phone" type="tel" value="${esc(c && c.phone)}" maxlength="20" autocomplete="off"></div></div>
  <div class="row"><div><label for="${id}e">E-mail</label><input id="${id}e" name="email" type="email" value="${esc(c && c.email)}" maxlength="120"></div>
  <div><label for="${id}c">Własna cena za 10 szt. (zł)</label><input id="${id}c" name="price10" type="number" step="0.5" min="0" value="${c && c.price10 != null ? c.price10 : ''}"
  placeholder="cena z oferty" inputmode="decimal"></div></div>
  <label for="${id}a">Adres</label><input id="${id}a" name="address" value="${esc(c && c.address)}" maxlength="200">
  <label for="${id}u">Uwagi</label><textarea id="${id}u" name="notes" rows="2" maxlength="1000">${esc(c && c.notes)}</textarea>
  <div class="actions"><button class="pri">${c ? 'Zapisz dane' : 'Dodaj klienta'}</button>${c ? `<button type="button" class="ghost danger" data-act="delclient" data-id="${c.id}">Usuń klienta</button>` : ''}</div></form>`;
const clientRows = cs => cs.map(c => `<li data-client="${c.id}"><span class="ti" aria-hidden="true">👤</span><div class="tb"><b><a href="#/klienci/${c.id}">${esc(c.name)}</a>
  ${c.regular ? ' <span class="pill">stały klient</span>' : ''}</b><span class="mu">${c.purchases ? `${c.purchases} zakupów · ${c.packs} opak. · ostatnio ${day(c.last_sale)}` : 'bez zakupów'}</span></div>
  ${balBadge(c.balance)}${c.phone ? `<a class="btn" href="tel:${esc(c.phone.replace(/\s/g, ''))}" aria-label="Zadzwoń do: ${esc(c.name)}">📞</a>` : ''}</li>`).join('')
  || '<li class="mu">Nikogo nie znaleziono.</li>';
async function vClients(arg) {
  if (arg) return vClientCard(arg);
  const [cs, fin] = await Promise.all([load('/api/my/clients'), load('/api/my/finance?days=30')]);
  cs.sort((a, b) => (b.balance > 0.005) - (a.balance > 0.005) || b.balance - a.balance || a.name.localeCompare(b.name, 'pl'));
  return `<h1>Klienci</h1><section class="card"><div class="stats">${stat('Klienci winni', zl(fin.debts), fin.debtors ? `${fin.debtors} z długiem` : 'nikt nie ma długu')}
    ${stat('Nadpłaty klientów', zl(fin.overpaid))}${stat('Klientów w kartotece', cs.length)}</div></section>
    <section class="card"><label for="clq">Szukaj klienta</label><input id="clq" type="search" placeholder="imię, telefon lub e-mail">
    <ul class="list" id="cllist" style="margin-top:.6rem">${clientRows(cs)}</ul></section>
    <section class="card"><details${cs.length ? '' : ' open'}><summary>➕ Dodaj klienta do kartoteki</summary>${clientForm(null, 'nc')}</details>
    <p class="mu">Klienci, którzy zamówią jaja w sklepie, dopisują się sami (rozpoznajemy ich po numerze telefonu).</p></section>`;
}
function historyRows(h) {
  return h.map(e => `<li><time datetime="${esc(e.at)}">${day(e.at)}</time><div class="tb"><b>${LEDGER[e.kind]}${e.method ? ' · ' + PAY[e.method][1] : ''}</b>
    <span class="mu">${esc(e.note)}</span><span class="mu">saldo po: ${balInfo(e.balance_after).short}</span></div>
    <b class="${e.amount > 0 ? 'no' : 'ok'}">${e.amount > 0 ? '+' : '−'}${zl(Math.abs(e.amount))}</b></li>`).join('') || '<li class="mu">Brak zakupów i wpłat.</li>';
}
async function vClientCard(id) {
  const [c, subs] = await Promise.all([load('/api/my/clients/' + encodeURIComponent(id)), load('/api/my/subscriptions?client_id=' + encodeURIComponent(id))]);
  const b = balInfo(c.balance), s = c.stats;
  const html = `<p><a class="btn ghost" href="#/klienci">← Wszyscy klienci</a></p><h1>${esc(c.name)}</h1>
    <section class="card"><p class="mu">${[c.phone && `📞 <a href="tel:${esc(c.phone.replace(/\s/g, ''))}">${esc(c.phone)}</a>`, c.email && `✉️ <a href="mailto:${esc(c.email)}">${esc(c.email)}</a>`,
      c.address && `📍 ${esc(c.address)}`, c.price10 != null && `cena ${zl(c.price10)} za 10 szt.`].filter(Boolean).join(' · ') || 'Brak danych kontaktowych'}</p>
    ${c.notes ? `<p>${esc(c.notes)}</p>` : ''}
    <div class="alert ${b.cls === 'no' ? 'bad' : ''}" style="${b.cls === 'ok' ? 'background:var(--okbg);border-color:var(--ok)' : b.cls ? '' : 'background:var(--sf2);border-color:var(--ln)'}"
      data-balance data-value="${c.balance}"><b style="font-size:1.5rem">${b.long}</b>${b.sub}</div>
    <div class="actions"><button class="pri" data-act="go" data-v="sprzedaz/kl-${c.id}">🧺 Nowa sprzedaż</button></div></section>
    <section class="card"><h2>💵 Wpłata od klienta</h2><form data-f="payment" data-id="${c.id}"><div class="row">
      <div><label for="pa">Kwota (zł)</label><input id="pa" name="amount" type="number" step="0.01" min="0.01" value="${c.balance > 0 ? c.balance.toFixed(2) : ''}" inputmode="decimal"></div>
      <div><label for="pm">Sposób</label><select id="pm" name="method">${['cash', 'transfer', 'blik'].map(m => `<option value="${m}">${PAY[m][1]}</option>`).join('')}</select></div></div>
      <label for="pn">Opis</label><input id="pn" name="note" maxlength="200" placeholder="np. za tydzień, przelew z 12.10">
      <p class="mu" data-after>Po wpłacie: …</p>
      <div class="actions"><button class="pri">Zapisz wpłatę</button>${c.balance > 0.005 ? '<button type="button" data-act="settle">Rozlicz do zera</button>' : ''}</div></form>
    ${c.balance < -0.005 ? `<details><summary>Zwrot nadpłaty</summary><form data-f="refund" data-id="${c.id}"><div class="row">
      <div><label for="ra">Kwota zwrotu (zł)</label><input id="ra" name="amount" type="number" step="0.01" min="0.01" max="${(-c.balance).toFixed(2)}" value="${(-c.balance).toFixed(2)}" inputmode="decimal"></div>
      <div><label for="rm">Sposób</label><select id="rm" name="method">${['cash', 'transfer', 'blik'].map(m => `<option value="${m}">${PAY[m][1]}</option>`).join('')}</select></div></div>
      <div class="actions"><button>Zapisz zwrot</button></div></form></details>` : ''}
    <details><summary>Korekta salda</summary><p class="mu">Np. dług z zeszytu sprzed portalu. Wpisz, ile klient ma być winny (minus to nadpłata).</p>
      <form data-f="correction" data-id="${c.id}"><div class="row"><div><label for="ca">Nowe saldo (zł)</label><input id="ca" name="balance" type="number" step="0.01" value="${c.balance.toFixed(2)}" required inputmode="decimal"></div>
      <div><label for="cn">Powód</label><input id="cn" name="note" required maxlength="200" placeholder="np. dług z zeszytu"></div></div>
      <div class="actions"><button>Zapisz korektę</button></div></form></details></section>
    <section class="card"><h2>📊 Zakupy</h2><div class="stats">${stat('Zakupy', s.purchases)}${stat('Jaja', s.eggs + ' szt.')}${stat('Wartość', zl(s.value))}${stat('Zapłacono', zl(s.paid))}</div>
    ${s.last_sale ? `<p class="mu">Ostatni zakup: ${day(s.last_sale)}</p>` : ''}
    ${c.orders.length ? `<h3>Aktywne zamówienia</h3><ul class="list">${c.orders.map(o => `<li><div class="tb"><b>${o.qty} opak. · ${zl(o.total)}</b><span class="mu">${MODE[o.mode]} · ${o.status === 'pending' ? 'czeka na potwierdzenie' : 'do wydania'}</span></div>
      ${o.status === 'confirmed' ? `<button class="pri sm" data-act="go" data-v="sprzedaz/zam-${o.id}">Wydaj i rozlicz</button>` : ''}</li>`).join('')}</ul>` : ''}</section>
    <section class="card"><h2>🔁 Zamówienia cykliczne</h2><ul class="list" data-subs>${subs.map(subRow).join('') || '<li class="mu">Ten klient nie ma stałego zamówienia.</li>'}</ul>
      <details><summary>➕ Dodaj zamówienie cykliczne</summary>${subForm([], c.id)}</details></section>
    <section class="card"><h2>🧾 Historia: zakupy i wpłaty</h2><ul class="list log" data-history>${historyRows(c.history)}</ul></section>
    <section class="card"><details><summary>✏️ Dane klienta</summary>${clientForm(c, 'ec')}</details></section>`;
  return {html, after: () => payPreview($('form[data-f=payment]'))};
}
function saleRows(ss) {
  return ss.slice(0, 30).map(s => `<li data-sale="${s.id}"><time datetime="${esc(s.at)}">${today(s.at) ? hm(s.at) : day(s.at)}</time><div class="tb">
    <b>${s.client_id ? `<a href="#/klienci/${s.client_id}">${esc(s.client_name)}</a>` : 'Bez kartoteki'} · ${s.eggs} szt. · ${zl(s.total)}</b>
    <span class="mu">${PAY[s.method][0]} ${PAY[s.method][1]}${['cash', 'transfer', 'blik'].includes(s.method) && Math.abs(s.paid - s.total) > 0.005 ? ` · zapłacono ${zl(s.paid)}` : ''}${s.order_id ? ' · zamówienie ze sklepu' : s.subscription_id ? ' · stały klient' : ''}${s.notes ? ' · ' + esc(s.notes) : ''}</span></div>
    <button class="sm ghost danger" data-act="delsale" data-id="${s.id}" aria-label="Usuń sprzedaż">Usuń</button></li>`).join('') || '<li class="mu">Brak sprzedaży w ostatnich 30 dniach.</li>';
}
const SOURCE = {free: 'Wolne z magazynu', reserve: 'Z rezerwy stałych klientów', offer: 'Z ogłoszonych w sklepie (całe opakowania)'};
let SALE = {};  // dane formularza sprzedaży: klienci, cena z oferty, zamówienie, zamówienie cykliczne
async function vSale(arg) {
  const [cs, farm, ss, orders, subs, eg] = await Promise.all([load('/api/my/clients'), load('/api/my/farm'), load('/api/my/sales?days=30'),
    load('/api/my/orders'), load('/api/my/subscriptions'), load('/api/my/eggs?days=1')]);
  const order = arg.startsWith('zam-') ? orders.find(o => o.id === +arg.slice(4) && o.status === 'confirmed') : null;
  const sub = arg.startsWith('sub-') ? subs.find(x => x.id === +arg.slice(4)) : null;
  const pre = order ? order.client_id : sub ? sub.client_id : arg.startsWith('kl-') ? +arg.slice(3) : null, p = eg.stock;
  SALE = {clients: Object.fromEntries(cs.map(c => [c.id, c])), price: farm.price10, order, sub, pools: p};
  const opts = `<option value="">— klient spoza kartoteki (płaci od razu) —</option>` + cs.map(c => `<option value="${c.id}"${c.id === pre ? ' selected' : ''}>${esc(c.name)}${Math.abs(c.balance) > 0.005 ? ' · ' + balInfo(c.balance).short : ''}</option>`).join('');
  const src = sub && p.reserved >= sub.eggs ? 'reserve' : 'free', method = sub ? sub.method : 'cash';
  return {html: `<h1>Sprzedaż</h1><form class="card" data-f="sale" data-order="${order ? order.id : ''}" data-sub="${sub ? sub.id : ''}">
    ${order ? `<div class="alert"><b>Wydanie zamówienia ze sklepu: ${esc(order.name)}</b>${order.qty} opak. (${order.qty * 10} szt.) · ${zl(order.total)}</div>`
      : `${sub ? `<div class="alert"><b>Stały klient: ${esc(sub.client_name)}</b>${sub.eggs} szt. co ${sub.every_days} dni</div>` : ''}
      <p class="mu" data-poolinfo>Wolne: <b>${p.free} szt.</b> · rezerwa: <b>${p.reserved} szt.</b> · w sklepie: <b>${p.offer_packs} opak.</b></p>`}
    <label for="sc">Klient</label><select id="sc" name="client_id"${order || sub ? ' disabled' : ''}>${opts}</select>
    <p class="mu" data-sbal></p>
    ${order ? '' : `<div class="row"><div><label for="se">Ile jaj (szt.)</label><input id="se" name="eggs" type="number" min="1" max="5000" value="${sub ? sub.eggs : 10}" required inputmode="numeric">
      <div class="seg" style="margin-top:.3rem">${[10, 30, 60].map(n => `<button type="button" class="sm" data-act="eggsqty" data-v="${n}">${n}</button>`).join('')}</div></div>
      <div><label for="sr">Cena za sztukę (zł)</label><input id="sr" name="price1" type="number" step="0.01" min="0" required inputmode="decimal"></div>
      <div><label for="sd">Rabat (zł)</label><input id="sd" name="discount" type="number" step="0.5" min="0" value="0" inputmode="decimal"></div></div>
      <label for="ss">Skąd jaja</label><select id="ss" name="source">${Object.entries(SOURCE).map(([k, t]) => `<option value="${k}"${k === src ? ' selected' : ''}>${t}</option>`).join('')}</select>`}
    <fieldset><legend>Jak płaci?</legend><div class="chips" role="radiogroup">${Object.entries(PAY).map(([k, [i, t]]) =>
      `<label class="chip"><input type="radio" name="method" value="${k}"${k === method ? ' checked' : ''}> ${i} ${t}</label>`).join('')}</div>
      <div data-paidbox><label for="sa">Ile zapłacił (zł)</label><input id="sa" name="paid" type="number" step="0.01" min="0" inputmode="decimal">
      <div class="seg" style="margin-top:.4rem"><button type="button" class="sm" data-act="paidall">Całość</button><button type="button" class="sm" data-act="paidzero">Całość + stary dług (rozlicz do zera)</button></div>
      <p class="mu">Wpisz, ile zostaje u Ciebie. Mniej niż do zapłaty: różnica idzie na dług. Więcej: nadpłata na kolejne zakupy.</p></div></fieldset>
    <label for="sn">Uwagi</label><input id="sn" name="notes" maxlength="200">
    <div class="alert" style="background:var(--sf2);border-color:var(--ln)" data-ssum aria-live="polite"></div>
    <div class="actions"><button class="pri">${order || sub ? 'Wydaj i zapisz' : 'Zapisz sprzedaż'}</button></div></form>
    <section class="card"><h2>Ostatnie sprzedaże (30 dni)</h2><ul class="list log" data-sales>${saleRows(ss)}</ul></section>`,
  after: () => { const f = $('form[data-f=sale]'); saleSync(f, true) }};
}
function saleSync(f, reset) {
  const e = f.elements, c = SALE.clients[e.client_id.value], o = SALE.order, method = (f.querySelector('[name=method]:checked') || {}).value;
  if (reset && !o) e.price1.value = ((c && c.price10 != null ? c.price10 : SALE.price) / 10).toFixed(2);
  const total = o ? o.total : Math.max(0, Math.round(((+e.eggs.value || 0) * (+e.price1.value || 0) - (+e.discount.value || 0)) * 100) / 100);
  const now = ['cash', 'transfer', 'blik'].includes(method), bal = c ? c.balance : 0;
  f.querySelectorAll('input[name=method][value=later],input[name=method][value=balance]').forEach(r => { r.disabled = !c; if (!c && r.checked) f.querySelector('[name=method][value=cash]').checked = true });
  $('[data-paidbox]', f).hidden = !now || !c;
  if (reset || !c || !now) e.paid.value = total.toFixed(2);
  const paid = now ? (c ? +e.paid.value || 0 : total) : 0, after = Math.round((bal + total - paid) * 100) / 100;
  $('[data-sbal]', f).textContent = c ? 'Saldo klienta teraz: ' + balInfo(bal).long : 'Klient spoza kartoteki płaci całość od razu.';
  $('[data-ssum]', f).innerHTML = `<b>Do zapłaty: ${zl(total)}</b>` + (c ? `Saldo po sprzedaży: <b class="${balInfo(after).cls}">${balInfo(after).long}</b>` : '');
  f.dataset.total = total; f.dataset.debt = Math.max(0, bal);
}
async function vReports() {
  const [os, e7, e30, fin] = await Promise.all([load('/api/my/orders'), load('/api/my/eggs?days=7'), load('/api/my/eggs?days=30'), load('/api/my/finance?days=30')]);
  return `<h1>Raporty</h1><section class="card"><h2>💰 Pieniądze (30 dni)</h2><div class="stats">${stat('Wpłynęło razem', zl(fin.received_total))}
    ${['cash', 'transfer', 'blik'].map(m => stat(PAY[m][0] + ' ' + PAY[m][1], zl(fin.received[m]))).join('')}</div>
    <div class="stats" style="margin-top:.7rem">${stat('Sprzedaż', zl(fin.sales_value), `${fin.sales_eggs} szt. · ${fin.sales_count} sprzedaży`)}
    ${stat('Wydatki', zl(fin.expenses))}${stat('Zysk (sprzedaż − wydatki)', zl(fin.profit))}
    ${stat('Klienci winni', zl(fin.debts), `${fin.debtors} z długiem`)}${stat('Nadpłaty klientów', zl(fin.overpaid))}</div></section>
    <section class="card"><h2>🥚 Jaja</h2><div class="stats">${stat('Zebrane w 7 dni', e7.collected + ' szt.', `${nf(e7.collected / 7, 0)} jaj dziennie`)}
    ${stat('Zebrane w 30 dni', e30.collected + ' szt.', `brudne ${e30.dirty}, uszkodzone ${e30.damaged}`)}${stat('Sprzedane w 30 dni', e30.sold + ' szt.')}
    ${stat('Rozdane w 30 dni', e30.given + ' szt.', Object.entries(e30.given_to).map(([w, n]) => `${esc(w)} ${n}`).join(', '))}${stat('Straty w 30 dni', e30.lost + ' szt.')}</div></section>
    <section class="card"><h2>📋 Zamówienia ze sklepu</h2><div class="stats">${stat('Wszystkie', os.length)}${stat('Czeka na potwierdzenie', os.filter(o => o.status === 'pending').length)}
    ${stat('Do wydania', os.filter(o => o.status === 'confirmed').length)}${stat('Wydane', os.filter(o => o.status === 'delivered').length)}${stat('Odrzucone', os.filter(o => o.status === 'rejected').length)}</div></section>`;
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
    <div><p class="mu" style="margin-top:2.2rem">W sklepie: ${f.stock} opak. Liczbę ogłoszonych opakowań zmienisz w <a href="#/jaja">Jajach</a>.</p></div></div></section>
    <section class="card"><h2>📍 Położenie gospodarstwa</h2><p class="mu">Potrzebne do harmonogramów od wschodu i zachodu słońca. Klienci go nie widzą.</p>
    <div class="row"><div>${fld('Szerokość geograficzna', 'lat', 'number', `step="any" min="-90" max="90" ${v(f.lat)} placeholder="np. 50.67" inputmode="decimal"`)}</div>
    <div>${fld('Długość geograficzna', 'lon', 'number', `step="any" min="-180" max="180" ${v(f.lon)} placeholder="np. 17.93" inputmode="decimal"`)}</div></div>
    <div class="actions"><button type="button" data-act="geo">📍 Użyj mojej lokalizacji</button></div></section>
    <div class="actions"><button class="pri">Zapisz ofertę</button></div></form>`;
}
function flockForm(x) {
  const p = x ? 'fl' + x.id : 'flnew', v = k => `value="${esc(x ? x[k] : '')}"`;
  return `<form data-f="flock" data-id="${x ? x.id : ''}"><div class="row"><div><label for="${p}n">Nazwa stada</label><input id="${p}n" name="name" ${v('name')} required maxlength="60" placeholder="np. Stado główne"></div>
    <div><label for="${p}b">Liczba kur</label><input id="${p}b" name="birds" type="number" min="0" max="100000" value="${x ? x.birds : ''}" required inputmode="numeric"></div></div>
    <div class="row"><div><label for="${p}r">Rasa</label><input id="${p}r" name="breed" ${v('breed')} maxlength="60" placeholder="np. Zielononóżka"></div>
    <div><label for="${p}s">Od kiedy</label><input id="${p}s" name="since" type="date" ${v('since')}></div></div>
    <label for="${p}o">Notatki</label><textarea id="${p}o" name="notes" maxlength="1000" rows="2">${esc(x ? x.notes : '')}</textarea>
    <div class="actions"><button class="pri">${x ? 'Zapisz zmiany' : 'Dodaj stado'}</button>${x ? `<button type="button" class="ghost danger" data-act="delflock" data-id="${x.id}">Usuń stado</button>` : ''}</div></form>`;
}
async function vFlock() {
  const [fl, eg] = await Promise.all([load('/api/my/flocks'), load('/api/my/eggs?days=7')]);
  const birds = fl.reduce((s, x) => s + x.birds, 0), perDay = eg.collected / 7;
  const sum = `<section class="card"><div class="stats">${stat('Kury razem', birds)}${stat('Jaja dziennie', nf(perDay, 0), 'średnio z 7 dni')}
    ${stat('Nieśność', birds ? nf(perDay / birds * 100, 0) + ' %' : '–', 'szacunkowo, ze zbiorów')}</div>
    <p class="mu">Nieśność liczymy z zapisanych zbiorów (Jaja → Zbiór jaj), więc zapisuj je codziennie.</p></section>`;
  return `<h1>Stado</h1>${fl.length ? sum : ''}${fl.map(x => `<section class="card" data-flock="${x.id}"><div class="dev-h"><div><h2>🐔 ${esc(x.name)}</h2>
    <p class="mu">${x.birds} kur${x.breed ? ' · ' + esc(x.breed) : ''}${x.since ? ' · od ' + new Date(x.since).toLocaleDateString('pl-PL') : ''}</p></div></div>
    ${x.notes ? `<p>${esc(x.notes)}</p>` : ''}<details><summary>Zmień dane stada</summary>${flockForm(x)}</details></section>`).join('')}
    <section class="card"><h2>${fl.length ? 'Dodaj kolejne stado' : 'Dodaj pierwsze stado'}</h2>${fl.length ? '' : '<p class="mu">Zapisz, ile masz kur. Portal policzy nieśność ze zbiorów jaj.</p>'}${flockForm(null)}</section>`;
}

// ---------- pasza: magazyn, receptury, mieszalnia ----------
const FCAT = {grain: 'Zboże', protein: 'Białkowe', mineral: 'Mineralne', premix: 'Premiks', additive: 'Dodatek', other: 'Inne'};
const SEASONS = {all: 'Cały rok', summer: 'Lato', winter: 'Zima', spring: 'Wiosna', autumn: 'Jesień'};
let FEED = {};
const kg = v => nf(v, 2) + ' kg';
function recipeRow(i) {
  return `<div class="row" data-ritem><div><label>Składnik</label><select name="item">${FEED.items.map(x => `<option value="${x.id}"${x.id === i ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
    <div><label>Udział (%)</label><input name="pct" type="number" step="0.1" min="0.1" max="100" required inputmode="decimal"></div>
    <div><button type="button" class="sm ghost danger" data-act="ritemdel" aria-label="Usuń składnik">Usuń</button></div></div>`;
}
async function vFeed() {
  const f = FEED = await load('/api/my/feed');
  const nut = n => [n.protein != null && `białko ${nf(n.protein, 1)}%`, n.energy != null && `energia ${nf(n.energy, 0)} kcal/kg`,
    n.calcium != null && `wapń ${nf(n.calcium, 1)} g/kg`, n.price != null && `${zl(n.price)}/kg`].filter(Boolean).join(' · ');
  const active = f.recipes.find(r => r.active);
  setTimeout(() => { const m = $('form[data-f=mix]'); if (m) mixNeed(m); const r = $('form[data-f=recipe]'); if (r) recipeSum(r) });
  return `<h1>Pasza i mieszalnia</h1><section class="card"><div class="stats">${stat('Składniki w magazynie', f.items.length)}${stat('Wartość zapasu', zl(f.value))}
    ${stat('Poniżej minimum', f.low, f.low ? 'trzeba dokupić' : 'zapasy w porządku')}</div></section>
    <section class="card"><h2>⚖️ Mieszalnia</h2>${f.recipes.length ? `<form data-f="mix"><div class="row">
      <div><label for="mx-r">Receptura</label><select id="mx-r" name="recipe_id">${f.recipes.map(r => `<option value="${r.id}"${r === active ? ' selected' : ''}>${esc(r.name)}${r.active ? ' (w użyciu)' : ''}</option>`).join('')}</select></div>
      <div><label for="mx-k">Ile kg mieszanki</label><input id="mx-k" name="kg" type="number" step="0.5" min="0.5" value="50" required inputmode="decimal"></div></div>
      <ul class="list" data-mixneed></ul><label for="mx-n">Uwagi</label><input id="mx-n" name="notes" maxlength="200">
      <div class="actions"><button class="pri">Mieszaj i odejmij z magazynu</button></div></form>` : '<p class="mu">Najpierw dodaj składniki i recepturę poniżej.</p>'}</section>
    <section class="card"><h2>🌾 Magazyn</h2><ul class="list" data-feeditems>${f.items.map(i => `<li data-fitem="${i.id}"><div class="tb">
      <b>${esc(i.name)} · ${nf(i.stock, 1)} ${esc(i.unit)}${i.low ? ' <span class="badge no">poniżej minimum</span>' : ''}</b>
      <span class="mu">${FCAT[i.category]}${i.min_stock ? ` · minimum ${nf(i.min_stock, 0)} ${esc(i.unit)}` : ''}${i.price ? ` · ${zl(i.price)}/${esc(i.unit)}` : ''}${i.protein != null ? ` · białko ${nf(i.protein, 1)}%` : ''}</span></div>
      <details><summary>Przyjęcie / spis</summary><form data-f="purchase" data-id="${i.id}"><div class="row">
        <div><label for="pu-q${i.id}">Przyjęto (${esc(i.unit)})</label><input id="pu-q${i.id}" name="qty" type="number" step="any" min="0.1" required inputmode="decimal"></div>
        <div><label for="pu-p${i.id}">Cena za ${esc(i.unit)} (zł)</label><input id="pu-p${i.id}" name="price" type="number" step="0.01" min="0" value="${i.price || ''}" inputmode="decimal"></div></div>
        <label class="chk"><input type="checkbox" name="expense" checked> Zapisz jako wydatek</label><div class="actions"><button class="pri">Przyjmij</button></div></form>
        <form data-f="fadjust" data-id="${i.id}"><div class="row"><div><label for="fa${i.id}">Stan po spisie (${esc(i.unit)})</label><input id="fa${i.id}" name="stock" type="number" step="any" min="0" value="${i.stock}" inputmode="decimal"></div>
        <div><button>Zapisz stan</button></div></div></form></details></li>`).join('') || '<li class="mu">Dodaj zboża i dodatki, z których mieszasz paszę.</li>'}</ul>
      <details><summary>➕ Dodaj składnik</summary><form data-f="fitem"><div class="row"><div><label for="fi-n">Nazwa</label><input id="fi-n" name="name" required maxlength="80" placeholder="np. pszenica"></div>
        <div><label for="fi-c">Rodzaj</label><select id="fi-c" name="category">${Object.entries(FCAT).map(([k, t]) => `<option value="${k}">${t}</option>`).join('')}</select></div></div>
        <div class="row"><div><label for="fi-s">Stan (kg)</label><input id="fi-s" name="stock" type="number" step="any" min="0" value="0" inputmode="decimal"></div>
        <div><label for="fi-m">Minimalny zapas (kg)</label><input id="fi-m" name="min_stock" type="number" step="any" min="0" value="0" inputmode="decimal"></div>
        <div><label for="fi-p">Cena za kg (zł)</label><input id="fi-p" name="price" type="number" step="0.01" min="0" inputmode="decimal"></div></div>
        <div class="row"><div><label for="fi-b">Białko (%)</label><input id="fi-b" name="protein" type="number" step="0.1" min="0" max="100" inputmode="decimal"></div>
        <div><label for="fi-e">Energia (kcal/kg)</label><input id="fi-e" name="energy" type="number" step="1" min="0" inputmode="decimal"></div>
        <div><label for="fi-w">Wapń (g/kg)</label><input id="fi-w" name="calcium" type="number" step="0.1" min="0" inputmode="decimal"></div></div>
        <div class="actions"><button class="pri">Dodaj składnik</button></div></form></details></section>
    <section class="card"><h2>📜 Receptury</h2><ul class="list">${f.recipes.map(r => `<li><div class="tb"><b>${esc(r.name)}${r.active ? ' <span class="pill">w użyciu</span>' : ''}</b>
      <span class="mu">${SEASONS[r.season]} · ${r.items.map(x => `${esc(x.name)} ${nf(x.percent, 1)}%`).join(', ')}</span>
      <span class="mu">${nut(r.nutrition)}</span>${Math.abs(r.total_percent - 100) > 0.5 ? `<span class="no">⚠️ Udziały dają ${nf(r.total_percent, 1)}%, popraw recepturę</span>` : ''}</div>
      <div class="seg">${r.active ? '' : `<button class="sm" data-act="recipeuse" data-id="${r.id}">Używaj</button>`}<button class="sm ghost danger" data-act="recipedel" data-id="${r.id}">Usuń</button></div></li>`).join('')
      || '<li class="mu">Brak receptur.</li>'}</ul>
      ${f.items.length ? `<details><summary>➕ Nowa receptura</summary><form data-f="recipe"><div class="row"><div><label for="re-n">Nazwa</label><input id="re-n" name="name" required maxlength="80" placeholder="np. nioski lato"></div>
        <div><label for="re-s">Sezon</label><select id="re-s" name="season">${Object.entries(SEASONS).map(([k, t]) => `<option value="${k}">${t}</option>`).join('')}</select></div></div>
        <div data-ritems>${recipeRow(f.items[0].id)}</div><div class="actions"><button type="button" class="sm" data-act="ritemadd">+ Składnik</button></div>
        <p class="mu" data-rsum aria-live="polite"></p><div class="actions"><button class="pri">Zapisz recepturę</button></div></form></details>` : ''}</section>
    <section class="card"><h2>🧾 Ruchy w magazynie</h2><ul class="list log">${f.moves.slice(0, 20).map(m => `<li><time datetime="${esc(m.at)}">${day(m.at)}</time>
      <div class="tb"><b>${esc(m.name)}: ${m.qty > 0 ? '+' : ''}${nf(m.qty, 2)}</b><span class="mu">${{purchase: 'przyjęcie', mix: 'mieszanie', adjust: 'spis'}[m.kind] || m.kind}${m.note ? ' · ' + esc(m.note) : ''}</span></div></li>`).join('')
      || '<li class="mu">Brak ruchów.</li>'}</ul></section>`;
}
function mixNeed(f) {
  const r = FEED.recipes.find(x => x.id === +f.elements.recipe_id.value), k = +f.elements.kg.value || 0;
  $('[data-mixneed]', f).innerHTML = r ? r.items.map(x => { const n = k * x.percent / 100, ok = n <= x.stock + 1e-9;
    return `<li><div class="tb"><b>${esc(x.name)}: ${kg(n)}</b><span class="${ok ? 'mu' : 'no'}">w magazynie ${kg(x.stock)}${ok ? '' : ' · za mało'}</span></div></li>` }).join('') : '';
}
function recipeSum(f) {
  const t = $$('[name=pct]', f).reduce((a, x) => a + (+x.value || 0), 0);
  $('[data-rsum]', f).innerHTML = Math.abs(t - 100) > 0.5 ? `<b class="no">Razem ${nf(t, 1)}% (musi być 100%)</b>` : `Razem ${nf(t, 1)}% ✓`;
}

// ---------- wydatki i wyposażenie ----------
let expDays = 30;
async function vExpenses() {
  const r = await load('/api/my/expenses?days=' + expDays), cats = Object.entries(r.by_category).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...cats.map(c => c[1]));
  return `<h1>Wydatki</h1><section class="card"><div class="seg" role="group" aria-label="Okres">${[[30, '30 dni'], [90, '3 miesiące'], [365, 'rok']].map(([d, t]) =>
    `<button data-act="expdays" data-v="${d}" aria-pressed="${d === expDays}">${t}</button>`).join('')}</div>
    <div class="stats" style="margin-top:.8rem">${stat('Razem', zl(r.total), r.entries.length + ' wpisów')}</div>
    ${cats.length ? `<ul class="list" style="margin-top:.6rem">${cats.map(([c, v]) => `<li><div class="tb"><b>${esc(c)}</b>
      <span class="cbar" style="--w:${Math.round(v / max * 100)}%" aria-hidden="true"></span></div><b>${zl(v)}</b></li>`).join('')}</ul>` : ''}</section>
    <section class="card"><h2>➕ Nowy wydatek</h2><form data-f="expense"><div class="row">
      <div><label for="ex-d">Data</label><input id="ex-d" name="date" type="date" value="${new Date().toISOString().slice(0, 10)}" required></div>
      <div><label for="ex-c">Kategoria</label><input id="ex-c" name="category" list="ex-cats" value="Pasza i zboże" required maxlength="60"></div></div>
      <datalist id="ex-cats">${r.categories.map(c => `<option value="${esc(c)}">`).join('')}</datalist>
      <label for="ex-n">Co kupiono</label><input id="ex-n" name="name" required maxlength="120" placeholder="np. pszenica, wizyta weterynarza">
      <div class="row"><div><label for="ex-q">Ilość</label><input id="ex-q" name="qty" type="number" step="any" min="0" value="1" inputmode="decimal"></div>
      <div><label for="ex-u">Jednostka</label><input id="ex-u" name="unit" value="kg" maxlength="10" list="ex-units"></div>
      <div><label for="ex-p">Cena za jednostkę (zł)</label><input id="ex-p" name="unit_price" type="number" step="0.01" min="0" inputmode="decimal"></div></div>
      <datalist id="ex-units"><option value="kg"><option value="t"><option value="szt"><option value="l"><option value="worek"><option value="kostka"><option value="usługa"></datalist>
      <div class="row"><div><label for="ex-t">Wartość (zł)</label><input id="ex-t" name="total" type="number" step="0.01" min="0" inputmode="decimal" placeholder="liczona z ilości i ceny"></div>
      <div><label for="ex-s">Dostawca</label><input id="ex-s" name="supplier" maxlength="120"></div></div>
      <label for="ex-o">Uwagi</label><input id="ex-o" name="notes" maxlength="500">
      <div class="actions"><button class="pri">Zapisz wydatek</button></div></form></section>
    <section class="card"><h2>Lista wydatków</h2><ul class="list" data-expenses>${r.entries.map(e => `<li><time datetime="${e.date}">${new Date(e.date).toLocaleDateString('pl-PL', {day: 'numeric', month: 'short'})}</time>
      <div class="tb"><b>${esc(e.name)} · ${zl(e.total)}</b><span class="mu">${esc(e.category)} · ${nf(e.qty, 2)} ${esc(e.unit)}${e.unit_price ? ' × ' + zl(e.unit_price) : ''}${e.supplier ? ' · ' + esc(e.supplier) : ''}${e.notes ? ' · ' + esc(e.notes) : ''}</span></div>
      <button class="sm ghost danger" data-act="expdel" data-id="${e.id}">Usuń</button></li>`).join('') || '<li class="mu">Brak wydatków w tym okresie.</li>'}</ul></section>`;
}
const EQ_STATE = {ok: ['ok', 'Sprawne'], repair: ['wa', 'Do naprawy'], broken: ['no', 'Zepsute'], retired: ['', 'Wycofane']};
const equipForm = (x, id) => `<form data-f="equip" data-id="${x ? x.id : ''}"><div class="row">
  <div><label for="${id}n">Nazwa</label><input id="${id}n" name="name" value="${esc(x && x.name)}" required maxlength="120" placeholder="np. poidło 10 l"></div>
  <div><label for="${id}c">Rodzaj</label><input id="${id}c" name="category" value="${esc(x && x.category)}" maxlength="60" list="eq-cats"></div></div>
  <datalist id="eq-cats"><option value="Poidło"><option value="Karmidło"><option value="Oświetlenie"><option value="Ogrzewanie"><option value="Narzędzia"><option value="Kurnik"></datalist>
  <div class="row"><div><label for="${id}b">Data zakupu</label><input id="${id}b" name="bought" type="date" value="${esc(x && x.bought)}"></div>
  <div><label for="${id}p">Cena (zł)</label><input id="${id}p" name="price" type="number" step="0.01" min="0" value="${x ? x.price : ''}" inputmode="decimal"></div>
  <div><label for="${id}s">Stan</label><select id="${id}s" name="state">${Object.entries(EQ_STATE).map(([k, [, t]]) => `<option value="${k}"${x && x.state === k ? ' selected' : ''}>${t}</option>`).join('')}</select></div></div>
  <div class="row"><div><label for="${id}k">Następny przegląd / wymiana</label><input id="${id}k" name="next_check" type="date" value="${esc(x && x.next_check)}"></div>
  <div><label for="${id}o">Uwagi</label><input id="${id}o" name="notes" value="${esc(x && x.notes)}" maxlength="500"></div></div>
  <div class="actions"><button class="pri">${x ? 'Zapisz' : 'Dodaj'}</button>${x ? `<button type="button" class="ghost danger" data-act="equipdel" data-id="${x.id}">Usuń</button>` : ''}</div></form>`;
async function vEquipment() {
  const eq = await load('/api/my/equipment'), worth = eq.filter(x => x.state !== 'retired').reduce((a, x) => a + x.price, 0);
  return `<h1>Wyposażenie</h1><section class="card"><div class="stats">${stat('Sprzęt w użyciu', eq.filter(x => x.state !== 'retired').length)}
    ${stat('Wartość zakupu', zl(worth))}${stat('Do naprawy lub przeglądu', eq.filter(x => x.check_due || ['repair', 'broken'].includes(x.state)).length)}</div></section>
    ${eq.map(x => `<section class="card" data-equip="${x.id}"><div class="dev-h"><div><h2>🧰 ${esc(x.name)}</h2><p class="mu">${[x.category && esc(x.category),
      x.bought && 'kupione ' + new Date(x.bought).toLocaleDateString('pl-PL'), x.price && zl(x.price)].filter(Boolean).join(' · ')}</p></div>
      <span class="badge ${EQ_STATE[x.state][0]}">${EQ_STATE[x.state][1]}</span></div>
      ${x.next_check ? `<p class="${x.check_due ? 'no' : 'mu'}">${x.check_due ? '⚠️ ' : ''}Przegląd / wymiana: ${new Date(x.next_check).toLocaleDateString('pl-PL')}</p>` : ''}
      ${x.notes ? `<p>${esc(x.notes)}</p>` : ''}<details><summary>Zmień</summary>${equipForm(x, 'eq' + x.id)}</details></section>`).join('')}
    <section class="card"><h2>➕ Dodaj wyposażenie</h2>${equipForm(null, 'eqn')}</section>`;
}

// ---------- baza wiedzy ----------
function mdInline(s) {
  return esc(s).replace(/!\[([^\]]*)\]\((https:\/\/[^\s)]+)\)/g, '<img src="$2" alt="$1" loading="lazy">')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\[([^\]]+)\]\((#\/[\w\/-]*)\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\*([^*\s][^*]*)\*/g, '<em>$1</em>').replace(/`([^`]+)`/g, '<code>$1</code>');
}
// Prosty Markdown: nagłówki, listy, cytaty, kod, pogrubienie, linki http(s) i obrazy https. Tekst jest najpierw escapowany.
function md(src) {
  const out = [], L = String(src || '').replace(/\r/g, '').split('\n'), LIST = /^\s*([-*]|\d+[.)])\s+/;
  let i = 0;
  while (i < L.length) {
    const l = L[i], h = l.match(/^(#{1,3})\s+(.*)/);
    if (!l.trim()) { i++; continue }
    if (l.startsWith('```')) { const b = []; i++; while (i < L.length && !L[i].startsWith('```')) b.push(L[i++]); i++; out.push(`<pre>${esc(b.join('\n'))}</pre>`); continue }
    if (h) { const n = h[1].length < 3 ? 2 : 3; out.push(`<h${n}>${mdInline(h[2])}</h${n}>`); i++; continue }
    if (LIST.test(l)) {
      const ol = /^\s*\d/.test(l), items = [];
      while (i < L.length && LIST.test(L[i]) && /^\s*\d/.test(L[i]) === ol) {
        let t = L[i++].replace(LIST, '');
        while (i < L.length && /^\s{2,}\S/.test(L[i]) && !LIST.test(L[i])) t += ' ' + L[i++].trim();
        items.push(`<li>${mdInline(t)}</li>`);
      }
      out.push(ol ? `<ol>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`); continue;
    }
    if (l.startsWith('>')) { const b = []; while (i < L.length && L[i].startsWith('>')) b.push(L[i++].replace(/^>\s?/, '')); out.push(`<blockquote>${mdInline(b.join(' '))}</blockquote>`); continue }
    const p = [l]; i++;
    while (i < L.length && L[i].trim() && !/^(#{1,3}\s|```|>)/.test(L[i]) && !LIST.test(L[i])) p.push(L[i++]);
    out.push(`<p>${mdInline(p.join(' '))}</p>`);
  }
  return out.join('');
}
const kbCards = (list, base) => list.map(a => `<a class="card kbcard" href="#/${base}/${a.id}" data-kb="${a.id}">
  <p class="mu">${a.category ? `<span class="pill">${esc(a.category)}</span> ` : ''}${a.published ? '' : '<span class="badge wa">Szkic</span> '}${day(a.updated)}</p>
  <h2>${esc(a.title)}</h2><p class="mu">${esc(a.excerpt)}${a.excerpt.length >= 180 ? '…' : ''}</p></a>`).join('');
async function kbSearch() {
  const key = kbQ + '\u0000' + kbCat, r = await api('GET', `/api/kb?q=${encodeURIComponent(kbQ)}&category=${encodeURIComponent(kbCat)}`), box = $('#kblist');
  if (r.ok && box && key === kbQ + '\u0000' + kbCat) box.innerHTML = kbCards(r.data, 'wiedza') || '<p class="mu">Nic nie znaleziono. Spróbuj innego słowa albo wybierz „Wszystkie”.</p>';
}
async function vKb(arg) {
  if (arg) {
    const a = await load('/api/kb/' + encodeURIComponent(arg));
    return `<p><a class="btn ghost" href="#/wiedza">← Wszystkie porady</a></p><article class="card prose"><p class="mu">${a.category ? `<span class="pill">${esc(a.category)}</span> · ` : ''}
      aktualizacja ${day(a.updated)}</p><h1>${esc(a.title)}</h1>${md(a.body)}</article>`;
  }
  const all = await load('/api/kb'), cats = [...new Set(all.map(a => a.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'pl'));
  if (!cats.includes(kbCat)) kbCat = '';
  if (!all.length) return '<h1>Baza wiedzy</h1>' + empty('📚', 'Baza wiedzy jest jeszcze pusta', 'Wkrótce pojawią się tu porady i instrukcje od zespołu zniesione.pl.');
  return {html: `<h1>Baza wiedzy</h1><p class="lead">Porady i instrukcje krok po kroku od zespołu zniesione.pl.</p>
    <label for="kbq">Szukaj w poradach</label><input id="kbq" type="search" value="${esc(kbQ)}" placeholder="np. drzwi, światło zimą">
    <div class="seg" role="group" aria-label="Kategorie" style="margin:.8rem 0">${['', ...cats].map(c => `<button data-act="kbcat" data-v="${esc(c)}" aria-pressed="${c === kbCat}">${c ? esc(c) : 'Wszystkie'}</button>`).join('')}</div>
    <div id="kblist"></div>`, after: kbSearch};
}
async function vSettings() {
  const t = theme(), st = await load('/api/my/settings');
  return `<h1>Ustawienia</h1><section class="card"><h2>⏰ Przypomnienie o zbiorze</h2>
    <p class="mu">Jeśli do tej godziny nie wpiszesz zbioru, portal przypomni${st.mail_configured ? ` e-mailem na ${esc(st.email)} i` : ''} na ekranie Start.</p>
    <form data-f="settings"><label class="chk"><input type="checkbox" name="remind_on" ${st.remind_on ? 'checked' : ''}> Przypominaj o wpisaniu zbioru</label>
    <label for="st-h">Godzina</label><select id="st-h" name="remind_hour">${Array.from({length: 19}, (_, i) => i + 5).map(h => `<option value="${h}"${h === st.remind_hour ? ' selected' : ''}>${h}:00</option>`).join('')}</select>
    <div class="actions"><button class="pri">Zapisz</button></div></form></section>
    <section class="card"><h2>📲 Aplikacja</h2><p class="mu">${standalone() ? 'Portal jest zainstalowany jako aplikacja.' : 'Dodaj portal na ekran telefonu lub komputera: otworzy się jak zwykła aplikacja, bez paska przeglądarki.'}</p>
    ${standalone() ? '' : '<div class="actions"><button class="pri" data-act="install">Dodaj jako aplikację</button></div><p class="mu" data-installhelp hidden></p>'}</section>
    <section class="card"><h2>Wygląd</h2><p class="mu">Automatyczny dopasowuje się do ustawień telefonu.</p><div class="seg" role="group" aria-label="Motyw">
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
    return `<li><time datetime="${esc(e.at)}">${today(e.at) ? hm(e.at) : day(e.at)}</time><div class="tb"><span>${DOORS.includes(e.kind) ? '🚪' : kicon(e.kind)} ${esc(what)}</span>
      <span class="src">${SRC[e.src] || esc(e.src)}${e.ok ? '' : ' · <span class="tag-bad">✕ nie udało się</span>'}</span></div></li>`;
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
      <input id="dr${d.id}" name="door_run_s" type="number" min="1" max="300" value="${d.door_run_s}" required inputmode="numeric"></div><div><button>Zapisz czas</button></div></form>
      <p class="mu">Ten sam czas jest zapisany w sterowniku jako zabezpieczenie na wypadek braku internetu. Po zmianie wgraj ponownie konfigurację ESPHome.</p>` : ''}
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
const adminTabs = cur => `<div class="tabs" role="navigation" aria-label="Sekcje administratora">${[['admin', 'Sterowniki'], ['admin-kb', 'Baza wiedzy'], ['admin-import', 'Import z e-kurnika'],
  ['admin-cfg', 'Konfiguracja'], ['admin-tools', 'Narzędzia']].map(([k, t]) => `<button data-act="go" data-v="${k}"${k === cur ? ' aria-current="page"' : ''}>${t}</button>`).join('')}</div>`;
const MD_HELP = `<details><summary>Jak formatować tekst</summary><pre>## Nagłówek        ### Mniejszy nagłówek
**pogrubienie**    *kursywa*    \`kod\`
- punkt listy      1. lista numerowana
> ramka z uwagą
[tekst linku](https://adres.pl)     [link w portalu](#/sterowanie)
![opis obrazka](https://adres.pl/obraz.jpg)</pre></details>`;
const SENS = {'': 'Brak czujnika', sht3x: 'SHT3x (temperatura i wilgotność, I²C)', dht22: 'DHT22 (temperatura i wilgotność)', ds18b20: 'DS18B20 (temperatura)'};
function fwBox(d) {
  const p = d.sensor_pins || {}, pin = (n, l) => `<div data-pin="${n}"><label for="fp${n}${d.id}">${l}</label><input id="fp${n}${d.id}" name="${n}" type="number" min="0" max="48" value="${p[n] ?? ''}" inputmode="numeric"></div>`;
  return `<details data-fw="${d.id}"><summary>🛠️ Firmware ESPHome (${d.chip})</summary>
    <form data-f="fwset" data-id="${d.id}"><div class="row"><div><label for="fws${d.id}">Wi-Fi w kurniku: nazwa</label><input id="fws${d.id}" name="wifi_ssid" value="${esc(d.wifi_ssid)}" maxlength="32"></div>
      <div><label for="fwp${d.id}">Wi-Fi: hasło</label><input id="fwp${d.id}" name="wifi_password" type="password" maxlength="63" autocomplete="new-password" placeholder="${d.wifi_set ? 'zapisane, wpisz aby zmienić' : ''}"></div></div>
      <div class="row"><div><label for="fwc${d.id}">Czujnik</label><select id="fwc${d.id}" name="sensor">${Object.entries(SENS).map(([k, t]) => `<option value="${k}"${k === d.sensor ? ' selected' : ''}>${t}</option>`).join('')}</select></div>
      ${pin('sda', 'SDA (GPIO)')}${pin('scl', 'SCL (GPIO)')}${pin('pin', 'Pin danych (GPIO)')}</div>
      <div class="actions"><button>Zapisz ustawienia</button></div></form>
    <div class="actions"><button class="pri" data-act="fw" data-v="compile" data-id="${d.id}">Kompiluj firmware</button>
      <button data-act="fw" data-v="upload" data-id="${d.id}"${d.online && d.tunnel === 'wg' ? '' : ' disabled title="Sterownik musi być połączony przez WireGuard"'}>Wgraj przez sieć (OTA)</button></div>
    <div data-fwusb="${d.id}"></div><p class="mu" data-fwstate="${d.id}">${d.fw_job ? 'Sprawdzam ostatnią kompilację…' : 'Pierwsze wgranie: przez USB z komputera (Chrome lub Edge). Kolejne: przez sieć.'}</p>
    <pre data-fwlog="${d.id}" hidden></pre></details>`;
}
function fwPins(f) {
  const s = f.elements.sensor.value;
  $$('[data-pin]', f).forEach(x => { x.hidden = !(s === 'sht3x' ? ['sda', 'scl'] : s ? ['pin'] : []).includes(x.dataset.pin) });
}
let ewt = null;
async function fwPoll(id, again) {
  const r = await api('GET', `/api/admin/devices/${id}/firmware`), st = $(`[data-fwstate="${id}"]`), log = $(`[data-fwlog="${id}"]`), usb = $(`[data-fwusb="${id}"]`);
  if (!st) return;
  if (!r.ok) { st.textContent = errMsg(r); return }
  const s = r.data;
  if (s.status === 'none') return;
  st.textContent = {queued: '⏳ W kolejce…', running: '⏳ Kompilacja trwa (pierwsza nawet 10 minut)…', ok: s.action === 'upload' ? '✅ Wgrano przez sieć' : '✅ Firmware gotowe',
    error: '❌ Błąd: zobacz log poniżej'}[s.status] || s.status;
  if (s.log) { log.textContent = s.log; log.hidden = false; log.scrollTop = log.scrollHeight }
  if (s.status === 'ok' && s.binary && !usb.innerHTML) {
    ewt = ewt || import('https://unpkg.com/esp-web-tools@10.4.0/dist/web/install-button.js?module').catch(() => null);
    usb.innerHTML = `<div class="actions"><esp-web-install-button manifest="/api/admin/devices/${id}/manifest.json"><button slot="activate" class="pri">🔌 Wgraj przez USB</button>
      <span slot="unsupported" class="mu">Wgrywanie przez USB działa w Chrome lub Edge na komputerze.</span></esp-web-install-button>
      <a class="btn" href="/api/admin/devices/${id}/firmware.bin" download>Pobierz plik .bin</a></div>`;
  }
  if (again && ['queued', 'running'].includes(s.status)) setTimeout(() => fwPoll(id, true), 2000);
}
async function vAdminImport() {
  return '<h1>Administrator</h1>' + adminTabs('admin-import') + `<section class="card"><h2>📥 Import z e-kurnika</h2>
    <p class="mu">Wgraj kopię bazy e-kurnika (plik .db z kopii zapasowej). Dane trafią na wybrane konto rolnika: klienci z saldami, sprzedaż, zbiory,
    stada, wydatki, wyposażenie, pasza i receptury. Jeśli konta nie ma, zostanie założone.</p>
    <form data-f="ekupload"><label for="ek-f">Plik kopii (.db)</label><input id="ek-f" name="file" type="file" accept=".db,.sqlite,application/octet-stream" required>
    <div class="actions"><button class="pri">Wgraj i sprawdź</button></div></form><div data-ekstep></div></section>`;
}
async function vAdminKb(arg) {
  let h = '<h1>Administrator</h1>' + adminTabs('admin-kb');
  if (!arg) {
    const all = await load('/api/kb');
    return h + `<div class="actions" style="margin:0 0 1rem"><button class="pri" data-act="go" data-v="admin-kb/nowy">＋ Nowy artykuł</button></div>`
      + (all.length ? kbCards(all, 'admin-kb') : empty('📚', 'Brak artykułów', 'Dodaj pierwszą poradę dla rolników.'));
  }
  const [a, all] = await Promise.all([arg === 'nowy' ? {title: '', category: '', body: '', published: false} : load('/api/kb/' + encodeURIComponent(arg)), load('/api/kb')]);
  const cats = [...new Set(all.map(x => x.category).filter(Boolean))];
  return h + `<p><a class="btn ghost" href="#/admin-kb">← Lista artykułów</a></p><form class="card" data-f="kb" data-id="${a.id || ''}">
    <h2>${a.id ? 'Edycja artykułu' : 'Nowy artykuł'}</h2>
    <label for="kb-t">Tytuł</label><input id="kb-t" name="title" value="${esc(a.title)}" required minlength="3" maxlength="150">
    <label for="kb-c">Kategoria</label><input id="kb-c" name="category" value="${esc(a.category)}" maxlength="60" list="kb-cats" placeholder="np. Drzwi, Harmonogramy, Porady">
    <datalist id="kb-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>
    <label for="kb-b">Treść</label><textarea id="kb-b" name="body" rows="16" required maxlength="50000">${esc(a.body)}</textarea>${MD_HELP}
    <label class="chk"><input type="checkbox" name="published" ${a.published ? 'checked' : ''}> Opublikowany (widoczny dla rolników)</label>
    <div class="actions"><button class="pri">Zapisz artykuł</button>${a.id ? `<button type="button" class="ghost danger" data-act="kbdel" data-id="${a.id}">Usuń artykuł</button>` : ''}</div></form>
    <h2>Podgląd</h2><article class="card prose" data-kbpreview><h1>${esc(a.title) || 'Tytuł'}</h1>${md(a.body)}</article>`;
}
async function vAdmin(tab) {
  let h = '<h1>Administrator</h1>' + adminTabs(tab === 'dev' ? 'admin' : 'admin-' + tab);
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
      ${d.firmware ? fwBox(d) : `<p class="mu">Firmware: ${d.model === 'shp' ? 'Shelly ma własny firmware (ustawienia MQTT w konfiguracji).' : 'Waveshare: uzupełnij piny Ethernet w konfiguracji, potem wgraj ręcznie.'}</p>`}
      <details><summary>Dane techniczne</summary><p>Połączenie: ${esc(d.tunnel)} · adres VPN: ${esc(d.ip)} · dostawa: ${esc(d.addr)}</p><p>Klucz API: <code>${esc(d.api_key)}</code></p>
      <p class="mu">Instalacja ESPHome potrzebuje konfiguracji (widzi ją też rolnik) i pliku secrets.yaml z kluczami WireGuard (tylko tutaj).
      Hasło API i OTA są losowane przy każdym pobraniu: wgraj oba pliki razem.</p>
      <div class="actions"><button data-act="secrets" data-id="${d.id}">Pobierz secrets.yaml</button><button data-act="copy" data-id="s${d.id}">📋 Kopiuj</button></div>
      <pre data-yaml="s${d.id}" hidden></pre></details>
      <details><summary>Odczyt testowy</summary><form data-f="reading" data-key="${esc(d.api_key)}"><div class="row"><div>${fld('Temperatura (°C)', 't', 'number', 'step="0.1" value="21"').replace(/f-t"/g, `rt${d.id}"`)}</div>
      <div>${fld('Wilgotność (%)', 'h', 'number', 'value="60"').replace(/f-h"/g, `rh${d.id}"`)}</div><div><button>Wyślij odczyt</button></div></div></form></details></section>`).join('');
  } else if (tab === 'cfg') {
    const c = await load('/api/admin/config');
    h += `<section class="card"><h2>Tunel WireGuard</h2><form data-f="cfg">${fld('Adres serwera', 'wg_endpoint', 'text', `value="${esc(c.wg_endpoint)}"`)}${fld('Port', 'wg_port', 'text', `value="${esc(c.wg_port)}"`)}
      ${fld('Podsieć (3 oktety)', 'net', 'text', `value="${esc(c.net)}"`)}<div class="actions"><button class="pri">Zapisz</button></div></form></section>`;
  } else h += `<section class="card"><h2>Silnik harmonogramów i termostatu</h2><p class="mu">Uruchamia jeden obieg: zaplanowane wyłączenia, harmonogramy, drzwi i termostat. Wysyła tylko różnice.</p>
    <button class="pri" data-act="tick">Uruchom silnik teraz</button><pre id="tickout" hidden></pre></section>`;
  return {html: h, after: () => { $$('form[data-f=fwset]').forEach(fwPins); $$('[data-fw]').forEach(x => fwPoll(x.dataset.fw, true)) }};
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
  reserveneed(b) { const f = b.closest('form'); f.elements.reserved.value = b.dataset.v; allocSum(f) },
  async secrets(b) {
    const r = await api('GET', `/api/admin/devices/${b.dataset.id}/secrets`), pre = $(`[data-yaml="s${b.dataset.id}"]`);
    pre.textContent = typeof r.data === 'string' && r.ok ? r.data : errMsg(r); pre.hidden = false;
  },
  async install(b) {
    if (installEvt) { installEvt.prompt(); const c = await installEvt.userChoice; installEvt = null; if (c.outcome === 'accepted') toast('Dodano aplikację'); return }
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent), help = b.closest('section').querySelector('[data-installhelp]');
    help.textContent = ios ? 'iPhone / iPad: w Safari stuknij „Udostępnij” (kwadrat ze strzałką), potem „Do ekranu początkowego”.'
      : 'W menu przeglądarki (⋮) wybierz „Zainstaluj aplikację” albo „Dodaj do ekranu głównego”.';
    help.hidden = false;
  },
  dismiss(b) { try { localStorage.setItem('zn-hide-' + b.dataset.v, '1') } catch (e) {} b.closest('section').remove() },
  async delclient(b) { if (done(await api('DELETE', `/api/my/clients/${b.dataset.id}`), 'Klient usunięty z kartoteki')) go('klienci') },
  async settle(b) {
    const f = b.closest('form'), r = await api('POST', `/api/my/clients/${f.dataset.id}/payments`, {settle: true, method: f.elements.method.value, note: f.elements.note.value});
    if (done(r, 'Rozliczono do zera')) await refresh();
  },
  eggsqty(b) { const f = b.closest('form'); f.elements.eggs.value = b.dataset.v; saleSync(f) },
  paidall(b) { const f = b.closest('form'); f.elements.paid.value = (+f.dataset.total).toFixed(2); saleSync(f) },
  paidzero(b) { const f = b.closest('form'); f.elements.paid.value = (+f.dataset.total + +f.dataset.debt).toFixed(2); saleSync(f) },
  ritemadd(b) { const box = b.closest('form').querySelector('[data-ritems]'); box.insertAdjacentHTML('beforeend', recipeRow(FEED.items[0].id)); recipeSum(b.closest('form')) },
  ritemdel(b) { const f = b.closest('form'); if ($$('[data-ritem]', f).length > 1) b.closest('[data-ritem]').remove(); recipeSum(f) },
  async recipeuse(b) { if (done(await api('PATCH', `/api/my/feed/recipes/${b.dataset.id}`, {active: true}), 'Receptura w użyciu')) await refresh() },
  async recipedel(b) { if (done(await api('DELETE', `/api/my/feed/recipes/${b.dataset.id}`), 'Usunięto recepturę')) await refresh() },
  async subskip(b) { if (done(await api('POST', `/api/my/subscriptions/${b.dataset.id}/skip`), 'Pominięto, przesunięto na kolejny termin')) await refresh() },
  async subtoggle(b) { if (done(await api('PATCH', `/api/my/subscriptions/${b.dataset.id}`, {active: b.getAttribute('aria-pressed') !== 'true'}), 'Zapisano')) await refresh() },
  async subdel(b) { if (done(await api('DELETE', `/api/my/subscriptions/${b.dataset.id}`), 'Usunięto zamówienie cykliczne')) await refresh() },
  async expdays(b) { expDays = +b.dataset.v; await refresh() },
  async expdel(b) { if (done(await api('DELETE', `/api/my/expenses/${b.dataset.id}`), 'Usunięto wydatek')) await refresh() },
  async fw(b) {
    const r = await api('POST', `/api/admin/devices/${b.dataset.id}/firmware`, {action: b.dataset.v});
    if (!done(r, b.dataset.v === 'upload' ? 'Kompilacja i wgranie przez sieć ruszyły' : 'Kompilacja ruszyła')) return;
    $(`[data-fwusb="${b.dataset.id}"]`).innerHTML = '';
    fwPoll(b.dataset.id, true);
  },
  async equipdel(b) { if (done(await api('DELETE', `/api/my/equipment/${b.dataset.id}`), 'Usunięto')) await refresh() },
  async delsale(b) {
    if (!done(await api('DELETE', `/api/my/sales/${b.dataset.id}`), 'Sprzedaż usunięta: stan jaj i saldo klienta cofnięte')) return;
    await refresh();
  },
  async delflock(b) { if (done(await api('DELETE', `/api/my/flocks/${b.dataset.id}`), 'Stado usunięte')) await refresh() },
  kbcat(b) { kbCat = b.dataset.v; $$('[data-act=kbcat]').forEach(x => x.setAttribute('aria-pressed', x === b)); kbSearch() },
  async kbdel(b) { if (done(await api('DELETE', `/api/admin/kb/${b.dataset.id}`), 'Artykuł usunięty')) go('admin-kb') },
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
  async collect(f, v) {
    const n = num(v.eggs), r = await api('POST', '/api/my/eggs', {kind: 'collect', eggs: n, note: v.note});
    await eggsReload(r.data && r.data.stock && `Zapisano zbiór: ${n} szt. Do sortowania: ${r.data.stock.unsorted} szt.`, r);
  },
  async sort(f, v) {
    const b = {kind: 'sort', good: num(v.good) || 0, dirty: num(v.dirty) || 0, damaged: num(v.damaged) || 0}, r = await api('POST', '/api/my/eggs', b);
    await eggsReload(r.data && r.data.stock && `Posortowano: ${b.good} dobrych do magazynu${b.dirty ? `, ${b.dirty} brudnych` : ''}${b.damaged ? `, ${b.damaged} uszkodzonych` : ''}. W magazynie: ${r.data.stock.eggs} szt.`, r);
  },
  async gift(f, v) {
    const r = await api('POST', '/api/my/eggs', {kind: 'gift', eggs: num(v.eggs), who: v.who, note: v.note});
    await eggsReload(r.data && r.data.stock && `Zapisano: ${v.eggs} szt. dla: ${v.who}. Wolne: ${r.data.stock.free} szt.`, r);
  },
  async settings(f, v) {
    const r = await api('PUT', '/api/my/settings', {remind_on: 'remind_on' in v, remind_hour: num(v.remind_hour)});
    done(r, r.data && (r.data.remind_on ? `Przypomnienie o ${r.data.remind_hour}:00` : 'Przypomnienie wyłączone'));
  },
  async alloc(f, v) {
    const r = await api('POST', '/api/my/eggs/allocation', {offer_packs: num(v.offer_packs), reserved: num(v.reserved)});
    await eggsReload(r.data && r.data.stock && `W sklepie: ${r.data.stock.offer_packs} opak., rezerwa: ${r.data.stock.reserved} szt., wolne: ${r.data.stock.free} szt.`, r);
  },
  async loss(f, v) { const r = await api('POST', '/api/my/eggs', {kind: 'loss', eggs: num(v.eggs), note: v.note}); await eggsReload(r.data && r.data.stock && `Zapisano stratę. W magazynie: ${r.data.stock.eggs} szt.`, r) },
  async inventory(f, v) { const r = await api('POST', '/api/my/eggs', {kind: 'inventory', eggs: num(v.eggs), note: v.note}); await eggsReload(r.data && r.data.stock && `Stan magazynu: ${r.data.stock.eggs} szt.`, r) },
  async client(f, v) {
    const id = f.dataset.id, r = await api(id ? 'PATCH' : 'POST', `/api/my/clients${id ? '/' + id : ''}`, {...v, price10: num(v.price10)});
    if (done(r, id ? 'Zapisano dane klienta' : 'Dodano klienta do kartoteki')) id ? await refresh() : go('klienci/' + r.data.id);
  },
  async payment(f, v) {
    const r = await api('POST', `/api/my/clients/${f.dataset.id}/payments`, {amount: num(v.amount), method: v.method, note: v.note});
    if (done(r, r.data && `Wpłata zapisana. ${balInfo(r.data.balance).long}`)) await refresh();
  },
  async refund(f, v) {
    const r = await api('POST', `/api/my/clients/${f.dataset.id}/payments`, {kind: 'refund', amount: num(v.amount), method: v.method});
    if (done(r, r.data && `Zwrot zapisany. ${balInfo(r.data.balance).long}`)) await refresh();
  },
  async correction(f, v) {
    const r = await api('POST', `/api/my/clients/${f.dataset.id}/correction`, {balance: num(v.balance), note: v.note});
    if (done(r, r.data && `Saldo po korekcie: ${balInfo(r.data.balance).long}`)) await refresh();
  },
  async sale(f, v) {
    const order = f.dataset.order, sub = f.dataset.sub, cid = order ? SALE.order.client_id : sub ? SALE.sub.client_id : num(v.client_id);
    const b = order ? {order_id: +order, method: v.method}
      : {...(sub ? {subscription_id: +sub} : {client_id: cid}), eggs: Math.round(+v.eggs), price10: Math.round(+v.price1 * 1000) / 100,
        discount: num(v.discount) || 0, method: v.method, source: v.source};
    if (['cash', 'transfer', 'blik'].includes(v.method) && cid) b.paid = num(v.paid);
    if (v.notes) b.notes = v.notes;
    const r = await api('POST', '/api/my/sales', b);
    if (!done(r, r.data && `Zapisano: ${zl(r.data.total)}` + (r.data.balance != null ? ` · saldo klienta: ${balInfo(r.data.balance).long}` : ''))) return;
    order || sub ? go('zamowienia') : await refresh();
  },
  async mix(f, v) {
    const r = await api('POST', '/api/my/feed/mix', {recipe_id: num(v.recipe_id), kg: num(v.kg), notes: v.notes});
    if (done(r, r.data && `Wymieszano ${nf(r.data.kg, 1)} kg (koszt składników ${zl(r.data.cost)})`)) await refresh();
  },
  async purchase(f, v) {
    const r = await api('POST', `/api/my/feed/items/${f.dataset.id}/purchase`, {qty: num(v.qty), price: num(v.price) || 0, expense: 'expense' in v});
    if (done(r, 'Przyjęto do magazynu' + ('expense' in v ? ' i zapisano wydatek' : ''))) await refresh();
  },
  async fadjust(f, v) { if (done(await api('POST', `/api/my/feed/items/${f.dataset.id}/adjust`, {stock: num(v.stock)}), 'Zapisano stan po spisie')) await refresh() },
  async fitem(f, v) {
    const b = {name: v.name, category: v.category, stock: num(v.stock) || 0, min_stock: num(v.min_stock) || 0, price: num(v.price) || 0,
      protein: num(v.protein), energy: num(v.energy), calcium: num(v.calcium)};
    if (done(await api('POST', '/api/my/feed/items', b), 'Dodano składnik')) await refresh();
  },
  async recipe(f, v) {
    const items = $$('[data-ritem]', f).map(r => ({item_id: +r.querySelector('[name=item]').value, percent: num(r.querySelector('[name=pct]').value)}));
    if (done(await api('POST', '/api/my/feed/recipes', {name: v.name, season: v.season, items}), 'Zapisano recepturę')) await refresh();
  },
  async sub(f, v) {
    const r = await api('POST', '/api/my/subscriptions', {client_id: num(v.client_id), eggs: num(v.eggs), every_days: num(v.every_days), next_date: v.next_date, method: v.method, notes: v.notes});
    if (done(r, 'Dodano zamówienie cykliczne')) await refresh();
  },
  async expense(f, v) {
    const b = {date: v.date, category: v.category, name: v.name, qty: num(v.qty) ?? 1, unit: v.unit || 'szt', supplier: v.supplier, notes: v.notes};
    if (v.unit_price !== '') b.unit_price = num(v.unit_price);
    if (v.total !== '') b.total = num(v.total);
    const r = await api('POST', '/api/my/expenses', b);
    if (done(r, r.data && `Zapisano wydatek: ${zl(r.data.total)}`)) await refresh();
  },
  async fwset(f, v) {
    const b = {wifi_ssid: v.wifi_ssid, sensor: v.sensor, sensor_pins: {sda: num(v.sda), scl: num(v.scl), pin: num(v.pin)}};
    if (v.wifi_password) b.wifi_password = v.wifi_password;
    if (done(await api('PATCH', `/api/admin/devices/${f.dataset.id}`, b), 'Zapisano ustawienia firmware')) f.elements.wifi_password.value = '';
  },
  async ekupload(f) {
    const fd = new FormData(f);
    const r = await fetch('/api/admin/ekurnik/upload', {method: 'POST', headers: {'X-Requested-With': 'zniesione'}, body: fd});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return toast(d.error || 'Nie udało się wgrać pliku', true);
    const box = $('[data-ekstep]'), best = d.farms.slice().sort((a, b) => b.clients - a.clients || b.days - a.days)[0];
    box.innerHTML = `<form data-f="ekimport" data-token="${d.token}"><fieldset><legend>Które gospodarstwo z e-kurnika?</legend>${d.farms.map(x =>
      `<label class="chk"><input type="radio" name="gid" value="${x.gid}"${x === best ? ' checked' : ''}> ${esc(x.name)} · klientów: ${x.clients}, dni zbiorów: ${x.days}</label>`).join('')}</fieldset>
      <div class="row"><div><label for="ek-e">E-mail konta rolnika</label><input id="ek-e" name="email" type="email" required placeholder="np. rolnik@gmail.com"></div>
      <div><label for="ek-p">Hasło (tylko dla nowego konta)</label><input id="ek-p" name="password" type="password" minlength="8" autocomplete="new-password"></div></div>
      <div class="actions"><button class="pri">Importuj</button></div></form>`;
    toast('Plik sprawdzony: wybierz gospodarstwo');
  },
  async ekimport(f, v) {
    const b = {token: f.dataset.token, gid: num(v.gid), email: v.email};
    if (v.password) b.password = v.password;
    const r = await api('POST', '/api/admin/ekurnik/import', b);
    if (!done(r, r.data && r.data.counts && `Zaimportowano na konto ${r.data.email}${r.data.created ? ' (nowe konto)' : ''}`)) return;
    $('[data-ekstep]').innerHTML = `<div class="alert" style="background:var(--okbg);border-color:var(--ok)"><b>✅ Gotowe: ${esc(r.data.email)}${r.data.created ? ' (konto założone)' : ''}</b>
      ${Object.entries(r.data.counts).map(([k, n]) => `${esc(k)}: ${n}`).join(' · ')}</div>`;
  },
  async equip(f, v) {
    const id = f.dataset.id, r = await api(id ? 'PATCH' : 'POST', `/api/my/equipment${id ? '/' + id : ''}`, {...v, price: num(v.price) || 0});
    if (done(r, id ? 'Zapisano' : 'Dodano wyposażenie')) await refresh();
  },
  async flock(f, v) {
    const id = f.dataset.id, b = {...v, birds: Math.round(+v.birds)};
    if (done(await api(id ? 'PATCH' : 'POST', `/api/my/flocks${id ? '/' + id : ''}`, b), id ? 'Zapisano stado' : 'Dodano stado')) await refresh();
  },
  async kb(f, v) {
    const id = f.dataset.id, r = await api(id ? 'PUT' : 'POST', `/api/admin/kb${id ? '/' + id : ''}`, {...v, published: 'published' in v});
    if (done(r, r.data && r.data.published ? 'Artykuł zapisany i opublikowany' : 'Artykuł zapisany jako szkic') && !id) go('admin-kb/' + r.data.id);
  },
  async offer(f, v) {
    const b = {...v, price10: +v.price10, lat: num(v.lat), lon: num(v.lon)};
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
  const t = e.target;
  if (t.id === 'kbq') { kbQ = t.value; clearTimeout(t._d); t._d = setTimeout(kbSearch, 250); return }
  if (t.form && t.form.dataset.f === 'kb' && (t.name === 'body' || t.name === 'title')) {
    const pv = $('[data-kbpreview]'); if (pv) pv.innerHTML = `<h1>${esc(t.form.elements.title.value) || 'Tytuł'}</h1>${md(t.form.elements.body.value)}`;
    return;
  }
  if (t.form && t.form.dataset.f === 'sale') return saleSync(t.form);
  if (t.form && t.form.dataset.f === 'alloc') return allocSum(t.form);
  if (t.form && t.form.dataset.f === 'sort') return sortSum(t.form);
  if (t.form && t.form.dataset.f === 'mix') return mixNeed(t.form);
  if (t.form && t.form.dataset.f === 'recipe') return recipeSum(t.form);
  if (t.form && t.form.dataset.f === 'payment' && t.name === 'amount') return payPreview(t.form);
  if (t.id === 'clq') {
    const q = t.value, r = await api('GET', '/api/my/clients?q=' + encodeURIComponent(q));
    if (r.ok && q === t.value && $('#cllist')) $('#cllist').innerHTML = clientRows(r.data);
    return;
  }
  if (t.id !== 'q') return;
  shopQ = e.target.value; const q = shopQ, r = await api('GET', '/api/farms?q=' + encodeURIComponent(q));
  if (r.ok && q === shopQ && $('#farms')) $('#farms').innerHTML = farmCards(r.data);
});
function payPreview(f) {
  const box = $('[data-after]', f), bal = +($('[data-balance]') || {}).dataset?.value;
  if (box && !isNaN(bal)) box.textContent = 'Po wpłacie: ' + balInfo(Math.round((bal - (+f.elements.amount.value || 0)) * 100) / 100).long;
}
document.addEventListener('change', async e => {
  const t = e.target, f = t.form;
  if (f && f.dataset.f === 'sched') syncSched(f);
  if (f && f.dataset.f === 'mix') mixNeed(f);
  if (f && f.dataset.f === 'fwset') fwPins(f);
  if (f && f.dataset.f === 'sale') saleSync(f, t.name === 'client_id');
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
