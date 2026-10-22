// Test funkcjonalny interfejsu: prawdziwy serwer + atrapa urządzenia + jsdom.
// Uruchomienie: node tests/e2e/run.js (uruchamia serwer i atrapę), patrz README.
const { JSDOM } = require("jsdom");
const BASE = process.env.BASE || "http://127.0.0.1:8765", DEV = process.env.DEV || "http://127.0.0.1:9123";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0, n = 0;
const ok = (c, m) => { n++; console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
const devState = async () => (await fetch(DEV + "/state")).json();

async function page() {
  const jar = {};
  const cfetch = async (u, o = {}) => {
    const url = new URL(u, BASE);
    const headers = { ...(o.headers || {}), Cookie: Object.entries(jar).map(([k, v]) => `${k}=${v}`).join("; ") };
    const r = await fetch(url, { ...o, headers });
    for (const c of r.headers.getSetCookie()) { const [kv] = c.split(";"); const i = kv.indexOf("="); jar[kv.slice(0, i)] = kv.slice(i + 1); }
    return r;
  };
  const html = await (await fetch(BASE + "/")).text();
  const dom = new JSDOM(html, { url: BASE + "/", runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse(w) { w.fetch = cfetch; } });
  const w = dom.window, d = w.document;
  const wait = async (fn, ms = 5000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await fn()) return true; } catch (e) {} await sleep(50); } return false; };
  const $ = (s) => d.querySelector(s), $$ = (s) => [...d.querySelectorAll(s)];
  const click = (el) => el.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  const submit = (f) => f.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  const change = (el) => el.dispatchEvent(new w.Event("change", { bubbles: true }));
  const setv = (root, name, v) => { const el = root.querySelector(`[name=${name}]`); el.value = v; change(el); };
  const text = () => d.body.textContent.replace(/\s+/g, " ");
  const toast = () => $("#toast").textContent;
  const btn = (t) => $$("button").find((b) => b.textContent.trim().includes(t));
  const clickBtn = async (t) => { await wait(() => btn(t)); click(btn(t)); };
  const nav = async (v) => { await wait(() => $(`[data-act=go][data-v="${v}"]`)); click($(`[data-act=go][data-v="${v}"]`)); };
  return { w, d, wait, $, $$, click, submit, change, setv, text, toast, btn, clickBtn, nav, cfetch };
}

(async () => {
  // ---- klient ----
  let p = await page();
  ok(await p.wait(() => p.$$("[data-farm]").length === 3), "sklep pokazuje 3 farmy demo");
  const q = p.$("#q"); q.value = "46"; q.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  ok(await p.wait(() => p.$$("[data-farm]").length === 1 && /Sowa/.test(p.text())), "wyszukiwanie po kodzie pocztowym");
  ok(p.d.activeElement === q || p.$("#q") === q, "pole wyszukiwania nie jest przebudowywane podczas pisania");
  p.click(p.$("[data-act=order]"));
  ok(await p.wait(() => p.$("form[data-f=order]")), "formularz zamówienia się otwiera");
  const of = p.$("form[data-f=order]");
  p.setv(of, "name", "Jan Kowalski"); p.setv(of, "phone", "600100200"); p.setv(of, "qty", "2"); p.setv(of, "mode", "weekly");
  p.submit(of);
  ok(await p.wait(() => /Zamówienie wysłane/.test(p.toast())), "klient składa zamówienie cykliczne");
  p = await page();
  await p.wait(() => p.$$("[data-farm]").length === 3);
  p.click(p.$("[data-farm='1'] [data-act=order]"));
  await p.wait(() => p.$("form[data-f=order]"));
  const f2 = p.$("form[data-f=order]"); p.setv(f2, "name", "Anna Nowak"); p.setv(f2, "phone", "600300400"); p.setv(f2, "qty", "3"); p.submit(f2);
  ok(await p.wait(() => /Zamówienie wysłane/.test(p.toast())), "zamówienie do farmy rolnika demo");

  // ---- rolnik: Start, Zamówienia, Jaja, Więcej, Oferta ----
  p = await page();
  await p.clickBtn("Zaloguj");
  await p.wait(() => p.$("form[data-f=login]"));
  const lf = p.$("form[data-f=login]"); p.setv(lf, "email", "rolnik@zniesione.test"); p.setv(lf, "password", "ZleHaslo1!"); p.submit(lf);
  ok(await p.wait(() => /Błędny e-mail lub hasło/.test(p.toast())), "błędne hasło jest odrzucone");
  p.setv(lf, "password", "Rolnik12345!"); p.submit(lf);
  ok(await p.wait(() => /Dzień dobry|Miłego popołudnia|Dobry wieczór|Dobrej nocy/.test(p.text()) && /Stan kurnika/.test(p.text())), "rolnik widzi Start z powitaniem i stanem kurnika");
  ok(await p.wait(() => /21,5 °C/.test(p.$("[data-live$=':t']").textContent)), "Start: temperatura z kurnika");
  ok(["Start", "Jaja", "Sterowanie", "Zamówienia", "Więcej"].every((t, i) => p.$$("#bottom button")[i].textContent.includes(t)), "dolne menu: Start, Jaja, Sterowanie, Zamówienia, Więcej");
  ok(p.$$("#bottom button")[0].getAttribute("aria-current") === "page", "dolne menu zaznacza bieżący ekran");
  ok(p.$(".hero .count") && p.$(".hero .count").textContent === "1", "skrót Zamówienia pokazuje 1 oczekujące");
  ok(p.$("[data-act=door][data-v=open]") && p.$("[data-sw$=':ch1']"), "Start: szybkie sterowanie światłem i drzwiami");
  await p.nav("zamowienia");
  ok(await p.wait(() => p.$("[data-order] [data-act=confirm]")), "rolnik widzi zamówienia do potwierdzenia");
  p.click(p.$("[data-order] [data-act=confirm]"));
  ok(await p.wait(() => /Potwierdzone/.test(p.text())), "rolnik potwierdza zamówienie");
  await p.nav("jaja");
  await p.wait(() => p.$("#f-zbior"));
  p.setv(p.$("#f-zbior"), "n", "5"); p.submit(p.$("#f-zbior"));
  ok(await p.wait(() => /Dodano 5 opak. Na stanie: 14/.test(p.toast()) && p.$("[data-stock]").textContent === "14"), "zbiór jaj dodaje opakowania do stanu");
  p.setv(p.$("#f-sprzedaz"), "n", "99"); p.submit(p.$("#f-sprzedaz"));
  ok(await p.wait(() => /Na stanie jest tylko 14/.test(p.toast())), "sprzedaż ponad stan jest odrzucona");
  await p.nav("wiecej");
  ok(await p.wait(() => p.$$(".mtile").length === 6) && ["Klienci", "Oferta", "Stado", "Sterowniki", "Raporty", "Ustawienia"].every((t) => p.btn(t)), "Więcej: 6 dużych kafelków");
  await p.nav("klienci");
  ok(await p.wait(() => /Anna Nowak/.test(p.text()) && p.$("a[href^='tel:']")), "Klienci: lista z numerem do zadzwonienia");
  await p.nav("wiecej"); await p.wait(() => p.$$(".mtile").length === 6);
  p.click(p.$(".mtile[data-v=oferta]"));
  await p.wait(() => p.$("form[data-f=offer]"));
  const off = p.$("form[data-f=offer]"); p.setv(off, "price10", "15"); p.setv(off, "stock", "20"); p.submit(off);
  ok(await p.wait(() => /Zapisano ofertę/.test(p.toast())), "rolnik zmienia cenę i stan");

  // ---- sterowanie ----
  await p.nav("sterowanie");
  ok(await p.wait(() => p.$("[data-dev] [data-live$=':t']") && /21,5/.test(p.$("[data-dev] [data-live$=':t']").textContent)), "Sterowanie: duże odczyty temperatury");
  ok(p.$$("[data-dev] .chart svg").length === 2, "wykresy 24 h: temperatura i wilgotność osobno");
  const visible = () => { const m = p.$("#main").cloneNode(true); m.querySelectorAll("pre").forEach((x) => x.remove()); return m.textContent; };
  ok(!/\bch\d+\b/.test(visible()), "rolnik nie widzi surowych kluczy kanałów (ch1…)");
  ok(/Wentylacja/.test(visible()) && /Grzałka wody/.test(visible()), "rodzaje kanałów po polsku");
  const tog = () => p.$("[data-dev] [data-sw$=':ch1']");
  ok(await p.wait(() => tog() && !tog().disabled), "kafelek światła aktywny dla urządzenia online");
  p.click(tog());
  ok(await p.wait(() => tog().getAttribute("aria-pressed") === "true" && /Światło: włączone/.test(p.toast())), "przełącznik światła zmienia stan (aria-pressed)");
  ok((await devState()).ch1 === true, "polecenie dotarło do atrapy urządzenia (światło włączone)");
  const dr = p.$("form[data-f=doorrun]"); p.setv(dr, "door_run_s", "1"); p.submit(dr);
  ok(await p.wait(() => /Zapisano czas pracy silnika/.test(p.toast())), "czas pracy silnika drzwi zapisany (1 s)");
  const doorBtn = (v) => p.$(`[data-dev] [data-act=door][data-v=${v}]`);
  p.click(doorBtn("open"));
  ok(await p.wait(async () => /otwieranie/.test(p.toast()) && (await devState()).ch2 === true), "Otwórz: przekaźnik otwierania włączony");
  await p.wait(() => !doorBtn("close").disabled);
  p.click(doorBtn("close"));
  ok(await p.wait(async () => { const s = await devState(); return s.ch2 === false && s.ch3 === true; }), "Zamknij: najpierw wyłącza otwieranie, potem włącza zamykanie");
  ok(await p.wait(() => /Zamykanie|Zamknięte/.test(p.$("[data-dev] [data-door]").textContent)), "kafelek drzwi pokazuje stan");

  const sf = () => p.$("form[data-f=sched]");
  p.setv(sf(), "ch", "ch1"); p.setv(sf(), "t_on", "00:00"); p.setv(sf(), "t_off", "23:59"); p.submit(sf());
  ok(await p.wait(() => /Harmonogram dodany/.test(p.toast()) && p.$$("[data-sch]").length === 1), "harmonogram godzinowy dodany i widoczny");
  p.setv(sf(), "ch", "ch1"); p.setv(sf(), "mode", "sunrise");
  ok(!sf().querySelector("[data-show='mode:sun']").hidden && sf().querySelector("[data-show='mode:time']").hidden, "wybór Wschód pokazuje pole przesunięcia");
  p.setv(sf(), "offset_min", "-30"); p.setv(sf(), "end", "time"); p.setv(sf(), "t_off", "07:00"); p.submit(sf());
  ok(await p.wait(() => p.$$("[data-sch]").length === 2 && /Włącz 30 min przed wschodem słońca, wyłącz o 07:00/.test(p.text())), "harmonogram: światło od wschodu −30 min do 07:00");
  p.setv(sf(), "ch", "ch2");
  ok(sf().querySelector("[data-leg=on]").textContent === "Kiedy otworzyć drzwi" && sf().querySelector("option[value=dur]").disabled, "formularz dla drzwi: otwórz/zamknij, bez czasu trwania");
  p.setv(sf(), "mode", "sunrise"); p.setv(sf(), "offset_min", "0"); p.setv(sf(), "end", "sunset"); p.setv(sf(), "off_offset_min", "20"); p.submit(sf());
  ok(await p.wait(() => /Otwórz o wschodzie słońca, zamknij 20 min po zachodzie słońca/.test(p.text())), "harmonogram drzwi: od wschodu do zachodu +20 min");
  p.setv(sf(), "ch", "ch6"); p.setv(sf(), "mode", "time"); p.setv(sf(), "t_on", "05:00"); p.setv(sf(), "end", "dur"); p.setv(sf(), "dur", "90"); p.setv(sf(), "unit", "1"); p.submit(sf());
  ok(await p.wait(() => /Włącz o 05:00, wyłącz po 1 min 30 s/.test(p.text())), "harmonogram z czasem działania (auto-wyłączenie)");
  const swS = () => p.$("[data-sch] [data-act=schtoggle]");
  p.click(swS());
  ok(await p.wait(() => swS().getAttribute("aria-pressed") === "false" && /Wstrzymany/.test(p.text())), "przełącznik wyłącza harmonogram");
  p.click(p.$("[data-sch] [data-act=schedit]"));
  ok(await p.wait(() => /Zapisz zmiany/.test(sf().textContent) && sf().elements.t_on.value === "00:00"), "Zmień: formularz wypełniony danymi harmonogramu");
  p.setv(sf(), "t_off", "22:00"); p.submit(sf());
  ok(await p.wait(() => /Harmonogram zmieniony/.test(p.toast()) && /wyłącz o 22:00/.test(p.text()) && p.$$("[data-sch]").length === 4), "zmiana godzin harmonogramu");
  const rf = p.$("form[data-f=rule][data-k=ch4]"); p.setv(rf, "threshold", "25"); p.submit(rf);
  ok(await p.wait(() => /Termostat zapisany/.test(p.toast()) && /włącz powyżej 25 °C/.test(p.$("[data-rule$='-ch4']").textContent)), "termostat wentylatora: włącz powyżej 25 °C");
  const rf5 = p.$("form[data-f=rule][data-k=ch5]"); p.setv(rf5, "threshold", "4"); p.submit(rf5);
  await p.wait(() => p.$("form[data-f=rule][data-k=ch5] [data-act=ruleoff]"));
  p.click(p.$("form[data-f=rule][data-k=ch5] [data-act=ruleoff]"));
  ok(await p.wait(() => /Automatyka wyłączona/.test(p.$("[data-rule$='-ch5']").textContent) && /Włącz automatykę/.test(p.$("form[data-f=rule][data-k=ch5]").textContent)), "automatykę ogrzewania można włączyć i wyłączyć");
  ok(await p.wait(() => /Światło: włączono/.test(p.$("[data-log]").textContent) && /ręcznie/.test(p.$("[data-log]").textContent) && /Drzwi: zamykanie/.test(p.$("[data-log]").textContent)), "dziennik zdarzeń: co, kiedy, skąd");
  p.click(p.$("[data-dev] summary[data-act=yaml]"));
  ok(await p.wait(() => /esphome:/.test(p.$("[data-yaml]").textContent) && /sn74hc595/.test(p.$("[data-yaml]").textContent)), "podgląd YAML ESPHome");

  // odświeżanie na żywo: nowy odczyt bez przeładowania i bez utraty fokusu i wpisanego tekstu
  const adm = await page();
  await adm.cfetch("/api/auth/login", { method: "POST", headers: { "X-Requested-With": "zniesione", "Content-Type": "application/json" }, body: JSON.stringify({ email: "admin@zniesione.test", password: "Admin12345!" }) });
  const apiKey = (await (await adm.cfetch("/api/admin/devices")).json())[0].api_key;
  const typed = sf().elements.t_on; typed.focus(); typed.value = "05:15";
  await fetch(BASE + "/api/device/readings", { method: "POST", headers: { "X-Api-Key": apiKey, "Content-Type": "application/json" }, body: JSON.stringify({ t: 23.4, h: 61 }) });
  ok(await p.wait(() => /23,4/.test(p.$("[data-dev] [data-live$=':t']").textContent), 13000), "odczyty odświeżają się same co 10 s");
  ok(p.d.activeElement === typed && typed.value === "05:15", "odświeżenie nie zabiera fokusu ani wpisanej wartości");

  // ---- motyw, katalog sterowników ----
  p.click(p.$("[data-act=theme]"));
  ok(p.w.localStorage.getItem("zn-theme") === "light" && p.d.documentElement.getAttribute("data-theme") === "light", "przełącznik motywu zapamiętany w localStorage");
  await p.nav("sterowniki");
  await p.wait(() => p.$("form[data-f=devorder]"));
  const df = p.$("form[data-f=devorder]"), ms = df.querySelector("[name=model]");
  ok(ms.value === "tr4" && /najtańszy/.test(ms.selectedOptions[0].textContent) && !df.querySelector("[data-cheap]").hidden, "T-Relay domyślny i oznaczony jako najtańszy");
  p.setv(df, "model", "own");
  ok(![...ms.options].some((x) => x.value === "own"), "w katalogu nie ma własnych sterowników");
  const forged = p.d.createElement("option"); forged.value = "own"; forged.textContent = "Mój ESP32"; ms.append(forged); ms.value = "own";
  p.setv(df, "addr", "hala 2"); p.submit(df);
  ok(await p.wait(() => /tylko sterowniki z katalogu/.test(p.toast())), "podrobiony model spoza katalogu odrzucony przez serwer");
  forged.remove(); ms.value = "tr4";
  p.setv(df, "tunnel", "ts"); p.submit(df);
  ok(await p.wait(() => /nie obsługuje wybranego połączenia/.test(p.toast())), "T-Relay z Tailscale odrzucony");
  p.setv(df, "tunnel", ""); p.submit(df);
  ok(await p.wait(() => p.$$("[data-dev]").length === 2), "zamówienie sterownika T-Relay");

  // ---- admin ----
  await p.clickBtn("Wyloguj");
  await p.wait(() => /Jaja prosto/.test(p.text()));
  await p.clickBtn("Zaloguj");
  await p.wait(() => p.$("form[data-f=login]"));
  const af = p.$("form[data-f=login]"); p.setv(af, "email", "admin@zniesione.test"); p.setv(af, "password", "Admin12345!"); p.submit(af);
  ok(await p.wait(() => /Administrator/.test(p.text()) && p.$$("[data-dev]").length === 2), "admin widzi wszystkie sterowniki");
  ok(p.$("#bottom").hidden, "admin nie ma dolnego menu rolnika");
  const newDev = p.$$("[data-dev]")[1];
  const fsel = newDev.querySelector(".fm"); fsel.value = [...fsel.options].find((x) => /Wierzba/.test(x.textContent)).value;
  p.click(newDev.querySelector("[data-act=assign]"));
  ok(await p.wait(() => /Przypisano/.test(p.toast())), "admin przypisuje sterownik do innej farmy");
  const rd = p.$$("form[data-f=reading]")[0]; p.setv(rd, "t", "28"); p.setv(rd, "h", "55"); p.submit(rd);
  ok(await p.wait(() => /Odczyt wysłany/.test(p.toast())), "symulowany odczyt 28 °C wysłany");
  await p.clickBtn("Narzędzia"); await p.wait(() => p.$("[data-act=tick]"));
  p.click(p.$("[data-act=tick]"));
  ok(await p.wait(() => !p.$("#tickout").hidden && /ch4 → włącz · OK/.test(p.$("#tickout").textContent)), "silnik włącza wentylator po przekroczeniu progu");
  ok(/ch3 → wyłącz · OK/.test(p.$("#tickout").textContent), "silnik wyłącza silnik drzwi po czasie pracy");
  const st2 = await devState();
  ok(st2.ch4 === true && st2.ch3 === false, "atrapa: wentylator włączony, zamykanie drzwi wyłączone");
  await p.clickBtn("Konfiguracja"); await p.wait(() => p.$("form[data-f=cfg]"));
  const cf = p.$("form[data-f=cfg]"); p.setv(cf, "net", "bad"); p.submit(cf);
  ok(await p.wait(() => /Niepoprawne pole net/.test(p.toast())), "walidacja konfiguracji");
  console.log(fails ? `\n${fails} NIEPOWODZEŃ na ${n}` : `\nWSZYSTKO OK (${n} kroków)`);
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
