// Test funkcjonalny interfejsu: prawdziwy serwer + atrapa urządzenia + jsdom.
// Uruchomienie: patrz tests/e2e/run.sh
const { JSDOM } = require("jsdom");
const BASE = process.env.BASE || "http://127.0.0.1:8765", DEV = process.env.DEV || "http://127.0.0.1:9000";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };

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
  const dom = new JSDOM(html, { url: BASE + "/", runScripts: "dangerously", pretendToBeVisual: true, beforeParse(w) { w.fetch = cfetch; } });
  const w = dom.window, d = w.document;
  const wait = async (fn, ms = 4000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) {} await sleep(50); } return false; };
  const $ = (s) => d.querySelector(s), $$ = (s) => [...d.querySelectorAll(s)];
  const click = (el) => el.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  const submit = (f) => f.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  const setv = (root, name, v) => { const el = root.querySelector(`[name=${name}]`); el.value = v; };
  const text = () => d.body.textContent.replace(/\s+/g, " ");
  const btn = (t) => $$("button").find((b) => b.textContent.trim().includes(t));
  const clickBtn = async (t) => { await wait(() => btn(t)); click(btn(t)); };
  return { w, d, wait, $, $$, click, submit, setv, text, btn, clickBtn };
}

(async () => {
  // ---- klient ----
  let p = await page();
  ok(await p.wait(() => p.$$("[data-farm]").length === 3), "sklep pokazuje 3 farmy demo");
  const q = p.$("#q"); q.value = "46"; q.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  ok(await p.wait(() => p.$$("[data-farm]").length === 1 && /Sowa/.test(p.text())), "wyszukiwanie po kodzie pocztowym");
  p.click(p.$("[data-act=order]"));
  ok(await p.wait(() => p.$("form[data-f=order]")), "formularz zamówienia się otwiera");
  const of = p.$("form[data-f=order]");
  p.setv(of, "name", "Jan Kowalski"); p.setv(of, "phone", "600100200"); p.setv(of, "qty", "2"); p.setv(of, "mode", "weekly");
  p.submit(of);
  ok(await p.wait(() => /Zamówienie wysłane/.test(p.$("#toast").textContent)), "klient składa zamówienie cykliczne");
  q.value = ""; // zamówienie dla farmy 1 (rolnik demo)
  p = await page();
  await p.wait(() => p.$$("[data-farm]").length === 3);
  p.click(p.$("[data-farm='1'] [data-act=order]"));
  await p.wait(() => p.$("form[data-f=order]"));
  const f2 = p.$("form[data-f=order]"); p.setv(f2, "name", "Anna Nowak"); p.setv(f2, "phone", "600300400"); p.setv(f2, "qty", "3"); p.submit(f2);
  ok(await p.wait(() => /Zamówienie wysłane/.test(p.$("#toast").textContent)), "zamówienie do farmy rolnika demo");

  // ---- rolnik ----
  p = await page();
  await p.clickBtn("Zaloguj");
  await p.wait(() => p.$("form[data-f=login]"));
  const lf = p.$("form[data-f=login]"); p.setv(lf, "email", "rolnik@zniesione.test"); p.setv(lf, "password", "ZleHaslo1!"); p.submit(lf);
  ok(await p.wait(() => /Błędny e-mail lub hasło/.test(p.$("#toast").textContent)), "błędne hasło jest odrzucone");
  p.setv(lf, "password", "Rolnik12345!"); p.submit(lf);
  ok(await p.wait(() => /Panel rolnika/.test(p.text()) && p.$("[data-order]")), "rolnik loguje się i widzi zamówienia");
  const o = p.$("[data-order] [data-act=confirm]");
  p.click(o);
  ok(await p.wait(() => /Potwierdzone/.test(p.text())), "rolnik potwierdza zamówienie");
  await p.clickBtn("Oferta");
  await p.wait(() => p.$("form[data-f=offer]"));
  const off = p.$("form[data-f=offer]"); p.setv(off, "price10", "15"); p.setv(off, "stock", "20"); p.submit(off);
  ok(await p.wait(() => /Zapisano ofertę/.test(p.$("#toast").textContent)), "rolnik zmienia cenę i stan");

  // ---- sterowanie ----
  await p.clickBtn("Sterowniki");
  ok(await p.wait(() => p.$("[data-dev] .temp") && /21.5/.test(p.$(".temp").textContent)), "odczyt temperatury widoczny");
  const tog = () => p.$("[data-dev] tr[data-ch=ch1] [data-act=toggle]");
  ok(await p.wait(() => tog() && !tog().disabled), "kanały aktywne dla urządzenia online");
  p.click(tog());
  ok(await p.wait(async () => true) && await p.wait(() => /Wyłącz/.test(tog().textContent)), "przełącznik światła zmienia stan w UI");
  const st = await (await fetch(DEV + "/state")).json();
  ok(st.ch1 === true, "polecenie dotarło do atrapy urządzenia (ch1 włączony)");
  const sf = p.$("form[data-f=sched]"); p.setv(sf, "ch", "ch1"); p.setv(sf, "t_on", "00:00"); p.setv(sf, "t_off", "23:59"); p.submit(sf);
  ok(await p.wait(() => /Harmonogram dodany/.test(p.$("#toast").textContent)), "dodanie harmonogramu");
  ok(await p.wait(() => p.$$("[data-act=delsch]").length === 1), "harmonogram widoczny na liście");
  const rf = p.$("form[data-f=rule][data-k=ch4]"); p.setv(rf, "threshold", "25"); p.submit(rf);
  ok(await p.wait(() => /Termostat zapisany/.test(p.$("#toast").textContent)), "termostat dla wentylatora zapisany");
  p.click(p.$("[data-act=yaml]"));
  ok(await p.wait(() => /esphome:/.test(p.$("pre").textContent) && /sn74hc595/.test(p.$("pre").textContent)), "podgląd YAML ESPHome");
  const df = p.$("form[data-f=devorder]"); p.setv(df, "model", "own"); 
  ok(![...df.querySelector("[name=model]").options].some((x) => x.value === "own"), "w katalogu nie ma własnych sterowników");
  p.setv(df, "model", "tr4"); p.setv(df, "tunnel", "ts"); p.setv(df, "addr", "hala 2"); p.submit(df);
  ok(await p.wait(() => /nie obsługuje wybranego połączenia/.test(p.$("#toast").textContent)), "T-Relay z Tailscale odrzucony");
  p.setv(df, "tunnel", ""); p.submit(df);
  ok(await p.wait(() => p.$$("[data-dev]").length === 2), "zamówienie sterownika T-Relay");

  // ---- admin ----
  await p.clickBtn("Wyloguj");
  await p.wait(() => /Konto rolnika|Jaja prosto/.test(p.text()));
  await p.clickBtn("Zaloguj");
  await p.wait(() => p.$("form[data-f=login]"));
  const af = p.$("form[data-f=login]"); p.setv(af, "email", "admin@zniesione.test"); p.setv(af, "password", "Admin12345!"); p.submit(af);
  ok(await p.wait(() => /Administrator/.test(p.text()) && p.$$("[data-dev]").length === 2), "admin widzi wszystkie sterowniki");
  const newDev = p.$$("[data-dev]")[1];
  const sel = newDev.querySelector(".fm"); sel.value = [...sel.options].find((x) => /Wierzba/.test(x.textContent)).value;
  p.click(newDev.querySelector("[data-act=assign]"));
  ok(await p.wait(() => /Przypisano/.test(p.$("#toast").textContent)), "admin przypisuje sterownik do innej farmy");
  const key = p.$$("[data-dev]")[0].querySelector("code").textContent;
  const rd = p.$$("form[data-f=reading]")[0]; p.setv(rd, "t", "28"); p.setv(rd, "h", "55"); p.submit(rd);
  ok(await p.wait(() => /Odczyt wysłany/.test(p.$("#toast").textContent)), "symulowany odczyt 28 °C wysłany");
  await p.clickBtn("Narzędzia"); await p.wait(() => p.$("[data-act=tick]"));
  p.click(p.$("[data-act=tick]"));
  ok(await p.wait(() => !p.$("#tickout").hidden && /ch4/.test(p.$("#tickout").textContent)), "silnik włącza wentylator po przekroczeniu progu");
  const st2 = await (await fetch(DEV + "/state")).json();
  ok(st2.ch4 === true, "wentylator włączony w atrapie urządzenia");
  await p.clickBtn("Konfiguracja"); await p.wait(() => p.$("form[data-f=cfg]"));
  const cf = p.$("form[data-f=cfg]"); p.setv(cf, "net", "bad"); p.submit(cf);
  ok(await p.wait(() => /Niepoprawne pole net/.test(p.$("#toast").textContent)), "walidacja konfiguracji");
  console.log(fails ? `\n${fails} NIEPOWODZEŃ` : "\nWSZYSTKO OK");
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
