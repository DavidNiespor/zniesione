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
  // wydanie zamówienia na dług (następnym razem)
  await p.wait(() => p.btn("Wydaj i rozlicz")); p.click(p.btn("Wydaj i rozlicz"));
  ok(await p.wait(() => p.$("form[data-f=sale][data-order]") && /Wydanie zamówienia ze sklepu: Anna Nowak/.test(p.text())), "Wydaj i rozlicz: formularz z zamówieniem");
  const pickPay = (f, m) => { const r = f.querySelector(`[name=method][value=${m}]`); r.checked = true; p.change(r); };
  let sf2 = p.$("form[data-f=sale]"); pickPay(sf2, "later"); p.submit(sf2);
  ok(await p.wait(() => /Zapisano: 42,00 zł · saldo klienta: Dług: 42,00 zł/.test(p.toast()) && /Wydane/.test(p.text())), "zamówienie wydane na dług trafia do kartoteki");
  await p.nav("jaja");
  await p.wait(() => p.$("#f-zbior"));
  // magazyn demo: 180 szt. (12 opak. w sklepie, 30 szt. rezerwy) i 24 szt. do sortowania; zamówienie Anny (3 opak.) wydane -> 150 szt.
  p.setv(p.$("#f-zbior"), "eggs", "50"); p.submit(p.$("#f-zbior"));
  ok(await p.wait(() => /Zapisano zbiór: 50 szt\. Do sortowania: 74 szt\./.test(p.toast())), "zbiór na sztuki trafia do sortowania");
  let so = p.$("form[data-f=sort]");
  ok(so.elements.good.value === "74" && /Do sortowania:\s*74 szt\./.test(so.textContent), "sortowanie: wszystkie do posortowania podpowiedziane jako dobre");
  p.setv(so, "good", "70"); p.setv(so, "dirty", "3"); p.setv(so, "damaged", "1"); so.elements.good.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  ok(/Razem 74 z 74 szt\./.test(so.textContent), "podgląd sortowania");
  p.submit(so);
  ok(await p.wait(() => /Posortowano: 70 dobrych do magazynu, 3 brudnych, 1 uszkodzonych\. W magazynie: 220 szt\./.test(p.toast())),
    "sortowanie: brudne i uszkodzone nie idą do magazynu");
  ok(await p.wait(() => /Sortowanie: 70 dobrych, 3 brudnych, 1 uszkodzonych/.test(p.$("[data-egglog]").textContent) && /Wolne\s*100 szt\./.test(p.$("[data-pools]").textContent)),
    "dziennik i stan magazynu: wolne 100 szt.");
  let al = p.$("form[data-f=alloc]");
  p.setv(al, "offer_packs", "20"); al.elements.offer_packs.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  ok(/Za mało jaj: brakuje 10 szt\./.test(al.textContent), "podgląd przydziału ostrzega przed brakiem jaj");
  p.submit(al);
  ok(await p.wait(() => /najwyżej 220 szt\./.test(p.toast())), "nie da się ogłosić więcej, niż jest w magazynie");
  p.setv(al, "offer_packs", "9"); p.setv(al, "reserved", "40"); p.submit(al);
  ok(await p.wait(() => /W sklepie: 9 opak\., rezerwa: 40 szt\., wolne: 90 szt\./.test(p.toast())), "ogłoszenie w sklepie i rezerwa dla stałych klientów");
  const gf = p.$("form[data-f=gift]"); p.setv(gf, "eggs", "10"); p.setv(gf, "who", "Mama"); p.submit(gf);
  ok(await p.wait(() => /Zapisano: 10 szt\. dla: Mama\. Wolne: 80 szt\./.test(p.toast()) && /Rozdane: 10 szt\. · Mama/.test(p.$("[data-egglog]").textContent)),
    "rozdane: 10 szt. dla mamy");
  ok(/Brudne\s*3 szt\./.test(p.$("[data-pools]").textContent), "brudne jaja z sortowania jako osobna pula");
  let gf2 = p.$("form[data-f=gift]"); p.setv(gf2, "eggs", "2"); p.setv(gf2, "who", "Sąsiad"); p.setv(gf2, "pool", "dirty"); p.submit(gf2);
  ok(await p.wait(() => /Zapisano: 2 szt\. brudnych dla: Sąsiad\. Wolne: 80 szt\./.test(p.toast()) && /Brudne\s*1 szt\./.test(p.$("[data-pools]").textContent)),
    "rozdanie brudnych nie zmniejsza wolnych dobrych");
  gf2 = p.$("form[data-f=gift]"); p.setv(gf2, "eggs", "5"); p.setv(gf2, "who", "Ciocia"); p.submit(gf2);
  await p.wait(() => /Wolne: 75 szt\./.test(p.toast()) && p.$$("[data-egglog] li").some((li) => /Ciocia/.test(li.textContent)));
  p.click(p.$$("[data-egglog] li").find((li) => /Ciocia/.test(li.textContent)).querySelector("[data-act=eggedit]"));
  await p.wait(() => p.$("form[data-f=eggedit]"));
  const ee = p.$("form[data-f=eggedit]"); p.setv(ee, "eggs", "3"); p.submit(ee);
  ok(await p.wait(() => /Wpis poprawiony/.test(p.toast()) && /Wolne\s*77 szt\./.test(p.$("[data-pools]").textContent)), "poprawka wpisu (5 → 3 szt.) oddaje różnicę do wolnych");
  p.click(p.$$("[data-egglog] li").find((li) => /Ciocia/.test(li.textContent)).querySelector("[data-act=eggedit]"));
  await p.wait(() => p.$("form[data-f=eggedit] [data-act=eggdel]"));
  p.click(p.$("[data-act=eggdel]")); p.click(p.$("[data-act=eggdel]"));
  ok(await p.wait(() => /Wpis usunięty/.test(p.toast()) && /Wolne\s*80 szt\./.test(p.$("[data-pools]").textContent)), "usunięcie wpisu cofa stan jaj");
  // sprzedaż z kartoteki: klient z długiem płaci więcej, powstaje nadpłata
  await p.nav("sprzedaz");
  await p.wait(() => p.$("form[data-f=sale]"));
  sf2 = p.$("form[data-f=sale]");
  const zofia = [...sf2.querySelector("[name=client_id]").options].find((o) => /Pani Zofia/.test(o.textContent));
  ok(zofia && /Dług 18,00 zł/.test(zofia.textContent), "lista klientów w sprzedaży pokazuje dług");
  p.setv(sf2, "client_id", zofia.value);
  ok(sf2.elements.price1.value === "1.40" && /Saldo klienta teraz: Dług: 18,00 zł/.test(sf2.textContent), "wybór klienta: cena za sztukę i saldo");
  const typ = (f, n, v) => { const el = f.elements[n]; el.value = v; el.dispatchEvent(new p.w.Event("input", { bubbles: true })); };
  typ(sf2, "eggs", "20"); typ(sf2, "paid", "50");
  ok(/Do zapłaty: 28,00 zł/.test(sf2.textContent) && /Saldo po sprzedaży: Nadpłata: 4,00 zł/.test(sf2.textContent), "podgląd: do zapłaty i saldo po sprzedaży");
  p.submit(sf2);
  ok(await p.wait(() => /saldo klienta: Nadpłata: 4,00 zł/.test(p.toast()) && p.$("[data-poolinfo]") && /Wolne: 60 szt./.test(p.$("[data-poolinfo]").textContent)),
    "sprzedaż 20 szt. gotówką z nadpłatą, wolne 60 szt.");
  sf2 = p.$("form[data-f=sale]"); p.setv(sf2, "client_id", "");
  ok(sf2.querySelector("[name=method][value=later]").disabled, "klient spoza kartoteki nie może kupić na dług");
  typ(sf2, "eggs", "99"); p.submit(sf2);
  ok(await p.wait(() => /Wolnych jaj jest tylko 60 szt\./.test(p.toast())), "sprzedaż ponad wolne jaja jest odrzucona");
  // stały klient: wydanie z rezerwy
  await p.nav("zamowienia");
  ok(await p.wait(() => p.$("[data-subs]") && /Pani Zofia \(sąsiadka\) · 30 szt\. co tydzień/.test(p.$("[data-subs]").textContent) && /do wydania/.test(p.$("[data-subs]").textContent)),
    "zamówienia cykliczne: stała klientka do wydania dziś");
  p.click(p.$("[data-subs] [data-act=go]"));
  ok(await p.wait(() => p.$("form[data-f=sale][data-sub]") && p.$("form[data-f=sale]").elements.source.value === "reserve"
    && p.$("form[data-f=sale]").elements.eggs.value === "30"), "wydanie stałego klienta: 30 szt. z rezerwy, na dług");
  p.submit(p.$("form[data-f=sale]"));
  ok(await p.wait(() => /Zapisano: 42,00 zł · saldo klienta: Dług: 38,00 zł/.test(p.toast()) && p.$("[data-subs]") && /następna dostawa/.test(p.$("[data-subs]").textContent)
    && !/do wydania/.test(p.$("[data-subs]").textContent)), "po wydaniu: dług w kartotece, następna dostawa za tydzień");
  ok(p.$("[data-calendar] .cal") && p.$$("[data-calendar] .cd[data-v]").length >= 28 && /stały klient/.test(p.$("[data-calendar]").textContent),
    "Zamówienia: kalendarz miesiąca z dostawami stałych klientów");
  await p.nav("wiecej");
  const MORE = ["Sprzedaż", "Klienci", "Oferta", "Stado", "Sterowniki", "Raporty", "Analityka", "Pasza i mieszalnia", "Wydatki", "Wyposażenie", "Baza wiedzy", "Ustawienia"];
  ok(await p.wait(() => p.$$(".mtile").length === 12) && MORE.every((t) => p.btn(t)), "Więcej: 12 dużych kafelków (w tym Analityka, Pasza, Wydatki, Wyposażenie)");
  await p.nav("pasza");
  ok(await p.wait(() => p.$("form[data-f=mix]") && /Pszenica: 25 kg/.test(p.$("[data-mixneed]").textContent)), "mieszalnia: ile czego potrzeba na 50 kg");
  const mf = p.$("form[data-f=mix]"); p.setv(mf, "kg", "40"); mf.elements.kg.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  ok(/Śruta sojowa: 7,2 kg/.test(p.$("[data-mixneed]").textContent), "podgląd mieszania po zmianie ilości");
  p.submit(mf);
  ok(await p.wait(() => /Wymieszano 40 kg/.test(p.toast()) && /Pszenica · 280 kg/.test(p.$("[data-feeditems]").textContent)), "mieszanie odejmuje składniki z magazynu");
  ok(/białko 16,3%/.test(p.text()), "receptura pokazuje zawartość białka");
  const rcf = p.$$("form[data-f=recipe]").find((f) => f.dataset.id);
  ok(rcf && rcf.querySelectorAll("[data-ritem]").length === 4, "edycja receptury: formularz z obecnymi składnikami");
  p.setv(rcf, "name", "Nioski cały rok v2"); p.submit(rcf);
  ok(await p.wait(() => /Receptura zmieniona/.test(p.toast()) && /Nioski cały rok v2/.test(p.text())), "zapis zmienionej receptury");
  await p.nav("wydatki");
  await p.wait(() => p.$("form[data-f=expense]"));
  const ef = p.$("form[data-f=expense]"); p.setv(ef, "name", "Pszenica"); p.setv(ef, "qty", "100"); p.setv(ef, "unit", "kg"); p.setv(ef, "unit_price", "1.15"); p.submit(ef);
  ok(await p.wait(() => /Zapisano wydatek: 115,00 zł/.test(p.toast()) && /Pszenica · 115,00 zł/.test(p.$("[data-expenses]").textContent)), "wydatek: wartość z ilości i ceny");
  await p.nav("wyposazenie");
  ok(await p.wait(() => /Lampa grzewcza/.test(p.text()) && /Do naprawy/.test(p.text()) && /⚠️ Przegląd/.test(p.text())), "wyposażenie: stan i przypomnienie o przeglądzie");
  const qf = p.$("form[data-f=equip][data-id='']"); p.setv(qf, "name", "Gniazdo 6-stanowiskowe"); p.setv(qf, "price", "149"); p.submit(qf);
  ok(await p.wait(() => /Dodano wyposażenie/.test(p.toast()) && /Gniazdo 6-stanowiskowe/.test(p.text())), "dodanie wyposażenia");
  await p.nav("analityka");
  ok(await p.wait(() => p.$(".chart svg") && /Przychody i wydatki/.test(p.text()) && /Formy płatności/.test(p.text()) && /Kto co robił/.test(p.text())),
    "Analityka: wykresy zbiorów i pieniędzy, kto co robił");
  // kartoteka klienta: wpłata i rozliczenie do zera
  await p.nav("klienci");
  ok(await p.wait(() => /Anna Nowak/.test(p.text()) && /Dług 42,00 zł/.test(p.$("[data-client]").textContent) && p.$("a[href^='tel:']")), "Klienci: dłużnicy na górze, z numerem do zadzwonienia");
  p.click(p.$$("[data-client] a").find((a) => /Anna Nowak/.test(a.textContent)));
  ok(await p.wait(() => p.$("form[data-f=payment]") && /Dług: 42,00 zł/.test(p.$("[data-balance]").textContent)), "karta klienta: saldo i formularz wpłaty");
  const pf = p.$("form[data-f=payment]"); typ(pf, "amount", "20");
  ok(/Po wpłacie: Dług: 22,00 zł/.test(pf.textContent), "podgląd salda po wpłacie");
  p.submit(pf);
  ok(await p.wait(() => /Wpłata zapisana. Dług: 22,00 zł/.test(p.toast()) && /Wpłata · Gotówka/.test(p.$("[data-history]").textContent)), "wpłata częściowa w historii");
  await p.wait(() => p.$("[data-act=settle]")); p.click(p.$("[data-act=settle]"));
  ok(await p.wait(() => /Rozliczony/.test(p.$("[data-balance]").textContent)), "rozlicz do zera");
  await p.nav("start");
  ok(await p.wait(() => /Do zrobienia/.test(p.text()) && /Lampa grzewcza/.test(p.text())), "Start: przypomnienie o przeglądzie wyposażenia");
  await p.nav("stado");
  ok(await p.wait(() => /Stado główne/.test(p.text()) && /48 kur/.test(p.text())), "Stado: stado z danych demo");
  const nf = p.$("form[data-f=flock][data-id='']"); p.setv(nf, "name", "Młode"); p.setv(nf, "birds", "20"); p.submit(nf);
  ok(await p.wait(() => /Dodano stado/.test(p.toast()) && p.$$("[data-flock]").length === 2 && /Kury razem\s*68/.test(p.text())), "Stado: dodanie stada, suma kur 68");
  ok(/Nieśność/.test(p.text()) && /\d+ %/.test(p.$(".stats").textContent), "Stado: szacunkowa nieśność ze zbiorów");
  await p.nav("wiedza");
  ok(await p.wait(() => p.$$("[data-kb]").length === 3 && !/szkic/i.test(p.$("#kblist").textContent)), "Baza wiedzy: 3 opublikowane artykuły, bez szkiców");
  const kq = p.$("#kbq"); kq.value = "silnika"; kq.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  ok(await p.wait(() => p.$$("[data-kb]").length === 1 && /Drzwi kurnika/.test(p.$("#kblist").textContent)), "Baza wiedzy: wyszukiwanie");
  p.click(p.$("[data-act=kbcat][data-v='']")); kq.value = ""; kq.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  await p.wait(() => p.$$("[data-kb]").length === 3);
  p.click(p.$$("[data-kb]").find((a) => /Pierwsze uruchomienie/.test(a.textContent)));
  ok(await p.wait(() => p.$("article.prose h1") && /Pierwsze uruchomienie/.test(p.$("article.prose h1").textContent)
    && p.$("article.prose ol li") && p.$("article.prose strong") && p.$("article.prose blockquote")), "Baza wiedzy: artykuł z formatowaniem (lista, pogrubienie, ramka)");
  await p.nav("wiecej"); await p.wait(() => p.$$(".mtile").length === 11);
  p.click(p.$(".mtile[data-v=oferta]"));
  await p.wait(() => p.$("form[data-f=offer]"));
  const off = p.$("form[data-f=offer]"); p.setv(off, "price10", "15"); p.submit(off);
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
  await p.nav("ustawienia");
  await p.wait(() => p.$("form[data-f=settings]"));
  const stf = p.$("form[data-f=settings]");
  ok(stf.elements.remind_hour.value === "19" && stf.elements.remind_on.checked, "ustawienia: przypomnienie o zbiorze domyślnie o 19:00");
  p.setv(stf, "remind_hour", "20"); p.submit(stf);
  ok(await p.wait(() => /Przypomnienie o 20:00/.test(p.toast())), "zmiana godziny przypomnienia");
  ok(p.btn("Dodaj jako aplikację"), "ustawienia: przycisk instalacji aplikacji");
  const tm = p.$("form[data-f=member]"); p.setv(tm, "name", "Ola"); p.setv(tm, "email", "ola@zniesione.test"); p.setv(tm, "password", "Ola123456!"); p.submit(tm);
  ok(await p.wait(() => /Dodano: Ola/.test(p.toast()) && p.$("[data-team]") && /ola@zniesione\.test/.test(p.$("[data-team]").textContent)), "zespół: właściciel dodaje osobę z osobnym loginem");
  ok(p.$("a[href='/api/my/export.zip']"), "ustawienia: pobranie kopii danych farmy");
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
  await p.wait(() => p.$("[data-act=secrets]"));
  p.click(p.$("[data-act=secrets]"));
  ok(await p.wait(() => /wg_privkey: "[A-Za-z0-9+/]{43}="/.test(p.$("[data-yaml^='s']").textContent) && /wg_server_pubkey/.test(p.$("[data-yaml^='s']").textContent)), "admin pobiera secrets.yaml z kluczami WireGuard");
  const fwf = p.$("form[data-f=fwset]");
  ok(fwf && /Firmware ESPHome \(ESP32-S3\)/.test(p.$("[data-fw]").textContent), "firmware: ustawienia w karcie sterownika");
  p.setv(fwf, "wifi_ssid", "Kurnik"); p.setv(fwf, "wifi_password", "haslo1234"); p.setv(fwf, "sensor", "sht3x");
  ok(!fwf.querySelector("[data-pin=sda]").hidden && fwf.querySelector("[data-pin=pin]").hidden, "czujnik SHT3x: pola SDA i SCL");
  p.setv(fwf, "sda", "8"); p.setv(fwf, "scl", "9"); p.submit(fwf);
  ok(await p.wait(() => /Zapisano ustawienia firmware/.test(p.toast())), "zapis Wi-Fi i czujnika");
  p.click(p.$("[data-act=fw][data-v=compile]"));
  ok(await p.wait(() => /nie jest skonfigurowane/.test(p.toast())), "bez kontenera budującego: czytelny komunikat");
  await p.clickBtn("Import z e-kurnika");
  ok(await p.wait(() => p.$("form[data-f=ekupload]")), "zakładka importu z e-kurnika");
  await p.clickBtn("Sterowniki"); await p.wait(() => p.$$("[data-dev]").length === 2);
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

  // ---- admin: baza wiedzy ----
  await p.clickBtn("Baza wiedzy");
  ok(await p.wait(() => p.$$("[data-kb]").length === 4 && /Szkic/.test(p.text())), "admin widzi wszystkie artykuły, także szkic");
  await p.clickBtn("Nowy artykuł"); await p.wait(() => p.$("form[data-f=kb]"));
  const kf = p.$("form[data-f=kb]"), body = kf.querySelector("[name=body]");
  p.setv(kf, "title", "Pojenie zimą"); p.setv(kf, "category", "Porady");
  body.value = "## Grzałka\nUstaw **2 °C**.\n<img src=x onerror=alert(1)>\n- punkt"; body.dispatchEvent(new p.w.Event("input", { bubbles: true }));
  const pv = p.$("[data-kbpreview]");
  ok(pv.querySelector("h2") && pv.querySelector("strong") && !pv.querySelector("img") && /<img src=x/.test(pv.textContent), "podgląd na żywo, HTML z treści nie jest wykonywany");
  kf.querySelector("[name=published]").checked = true; p.submit(kf);
  ok(await p.wait(() => /opublikowany/.test(p.toast()) && p.$("form[data-f=kb]") && p.$("form[data-f=kb]").dataset.id), "admin publikuje artykuł");
  const fr = await page();
  await fr.cfetch("/api/auth/login", { method: "POST", headers: { "X-Requested-With": "zniesione", "Content-Type": "application/json" }, body: JSON.stringify({ email: "rolnik@zniesione.test", password: "Rolnik12345!" }) });
  ok((await (await fr.cfetch("/api/kb?q=pojenie")).json()).some((a) => a.title === "Pojenie zimą"), "rolnik widzi nowy artykuł");
  p.click(p.$("[data-act=kbdel]"));
  ok(await p.wait(() => /Artykuł usunięty/.test(p.toast()) && p.$$("[data-kb]").length === 4), "admin usuwa artykuł");
  console.log(fails ? `\n${fails} NIEPOWODZEŃ na ${n}` : `\nWSZYSTKO OK (${n} kroków)`);
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
