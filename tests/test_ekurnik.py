"""Import z e-kurnika na sztucznej bazie o tym samym układzie tabel (bez prawdziwych danych)."""
import sqlite3

from conftest import Client, make

SCHEMA = """
CREATE TABLE gospodarstwa(id INTEGER PRIMARY KEY, nazwa TEXT);
CREATE TABLE ustawienia(klucz TEXT, wartosc TEXT, gospodarstwo_id INTEGER);
CREATE TABLE klienci(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, nazwa TEXT, telefon TEXT, email TEXT, adres TEXT, uwagi TEXT,
  cena_indyw REAL, stale_zamowienie INTEGER);
CREATE TABLE konta_saldo(klient_id INTEGER PRIMARY KEY, saldo_pln REAL, saldo_jaj INTEGER, ostatnia_zmiana TEXT);
CREATE TABLE konta_transakcje(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, klient_id INTEGER, data TEXT, typ TEXT, kwota REAL,
  jaj INTEGER, opis TEXT, zamowienie_id INTEGER, saldo_po REAL);
CREATE TABLE sprzedaz_szczegol(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, data TEXT, klient_id INTEGER, zamowienie_id INTEGER,
  ilosc INTEGER, cena_szt REAL, wartosc REAL, typ TEXT, uwagi TEXT);
CREATE TABLE produkcja(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, data TEXT, jaja_zebrane INTEGER, jaja_sprzedane INTEGER);
CREATE TABLE jaja_straty(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, data TEXT, ilosc INTEGER, powod TEXT, uwagi TEXT);
CREATE TABLE inwentaryzacje(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, data TEXT, stan INTEGER, uwagi TEXT);
CREATE TABLE stado(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, nazwa TEXT, gatunek TEXT, liczba INTEGER, data_dodania TEXT,
  data_urodzenia TEXT, rasa TEXT, uwagi TEXT, aktywne INTEGER);
CREATE TABLE wydatki(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, data TEXT, kategoria TEXT, nazwa TEXT, ilosc REAL, jednostka TEXT,
  cena_jednostkowa REAL, wartosc_total REAL, dostawca TEXT, uwagi TEXT);
CREATE TABLE wyposazenie(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, nazwa TEXT, kategoria TEXT, data_zakupu TEXT, cena REAL,
  stan TEXT, nastepny_przeglad TEXT, uwagi TEXT);
CREATE TABLE zamowienia(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, klient_id INTEGER, data_zlozenia TEXT, data_dostawy TEXT,
  ilosc INTEGER, cena_za_szt REAL, status TEXT, platnosc_typ TEXT, uwagi TEXT, cykl_dni INTEGER, cykl_aktywne INTEGER);
INSERT INTO gospodarstwa VALUES (1,'Kurnik'),(2,'Pusty');
INSERT INTO ustawienia VALUES ('cena_jajka','1.30',1);
INSERT INTO klienci VALUES (1,1,'Pani Ola','600 100 200','','Wiejska 1','płaci w piątki',1.1,1),(2,1,'Pan Jan','600200300','','','',0,0),
  (3,1,'Sklep','','','','',0.01,0);
INSERT INTO konta_saldo VALUES (1,26,0,''),(2,-5,0,''),(3,7,0,'');
INSERT INTO konta_transakcje VALUES (1,1,1,'2026-09-01 10:00:00','sprzedaz',33,0,'30 szt.',NULL,33),
  (2,1,1,'2026-09-05T10:00:00','wplata',-10,0,'Przelew',NULL,23),(3,1,2,'2026-09-06T10:00:00','wplata',-5,0,'Gotówka',NULL,-5);
INSERT INTO sprzedaz_szczegol VALUES (1,1,'2026-09-01',1,NULL,30,1.1,33,'nastepnym_razem',''),(2,1,'2026-09-02',NULL,NULL,12,1.3,15.6,'gotowka','sąsiad'),
  (3,1,'2026-09-03',2,NULL,10,1.3,13,'przelew','');
INSERT INTO produkcja(gospodarstwo_id,data,jaja_zebrane,jaja_sprzedane) VALUES (1,'2026-09-01',40,30),(1,'2026-09-02',38,0),(1,'2026-09-04',41,0);
INSERT INTO jaja_straty VALUES (1,1,'2026-09-02',3,'stluczone','');
INSERT INTO inwentaryzacje VALUES (1,1,'2026-08-31',20,'');
INSERT INTO stado VALUES (1,1,'Nioski','nioski',25,'2026-03-01',NULL,'Zielononóżka','',1),(2,1,'Kogut','kogut',1,NULL,NULL,NULL,NULL,1),
  (3,1,'Stare','nioski',5,NULL,NULL,NULL,NULL,0);
INSERT INTO wydatki VALUES (1,1,'2026-09-03','Zboże/pasza','Pszenica',100,'kg',1.1,110,'GS',''),(2,1,'2026-09-04','Weterynarz','Wizyta',1,'import',0,80,'','');
INSERT INTO wyposazenie VALUES (1,1,'Poidło','Poidło','2026-03-01',60,'sprawne','',''),(2,1,'Lampa','Oświetlenie',NULL,40,'do naprawy','2026-11-01','');
CREATE TABLE stan_magazynu(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, kategoria TEXT, nazwa TEXT, jednostka TEXT, stan REAL,
  min_zapas REAL, cena_aktualna REAL);
CREATE TABLE skladniki_baza(id INTEGER PRIMARY KEY, nazwa TEXT, kategoria TEXT, cena_pln_t REAL, bialko_pct REAL, energia_me REAL, wapn_g_kg REAL);
CREATE TABLE receptura(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, nazwa TEXT, sezon TEXT, aktywna INTEGER);
CREATE TABLE receptura_skladnik(id INTEGER PRIMARY KEY, receptura_id INTEGER, magazyn_id INTEGER, procent REAL);
CREATE TABLE mieszania(id INTEGER PRIMARY KEY, gospodarstwo_id INTEGER, data TEXT, receptura_id INTEGER, ilosc_kg REAL, uwagi TEXT);
INSERT INTO stan_magazynu VALUES (1,1,'Zboże/pasza','Pszenica','kg',300,100,0),(2,1,'Zboże/pasza','Śruta sojowa','kg',40,20,2.4),(3,1,'Witaminy/suplementy','Witaminy','kg',2,0,0);
INSERT INTO skladniki_baza VALUES (1,'pszenica','zboze',1100,11.5,2900,0.5),(2,'Śruta sojowa','bialkowe',2200,46,2400,3);
INSERT INTO receptura VALUES (1,1,'Nioski','caly_rok',1);
INSERT INTO receptura_skladnik VALUES (1,1,1,0.8),(2,1,2,0.2);
INSERT INTO mieszania VALUES (1,1,'2026-09-10T08:00:00',1,50,'');
INSERT INTO zamowienia VALUES (1,1,1,'2026-09-01','2026-10-30',30,1.1,'nowe','gotowka','',7,1),(2,1,2,'2026-09-01','2026-09-08',10,1.3,'dostarczone','gotowka','',7,1);
"""


def ekurnik_db(tmp_path):
    p = tmp_path / "ferma.db"
    con = sqlite3.connect(p)
    con.executescript(SCHEMA)
    con.commit(), con.close()
    return str(p)


def test_import_from_ekurnik(app, farmer, tmp_path):
    c, fid = farmer
    path = ekurnik_db(tmp_path)
    run = app.test_cli_runner().invoke
    assert "nie ma konta" in run(args=["import-ekurnik", path, "--email", "nikt@x.pl"]).output.lower()
    r = run(args=["import-ekurnik", path, "--email", "a@x.pl"])
    assert r.exit_code == 0, r.output                                     # jedno gospodarstwo z danymi: wybrane samo
    assert "klienci: 3" in r.output and "sprzedaz: 3" in r.output
    cl = {x["name"]: x for x in c.get("/api/my/clients").get_json()}
    assert {k: v["balance"] for k, v in cl.items()} == {"Pani Ola": 26, "Pan Jan": -5, "Sklep": 7}   # salda jak w e-kurniku
    assert cl["Pani Ola"]["price10"] == 11 and cl["Sklep"]["price10"] is None                      # 0,01 zł/szt. pominięte
    card = c.get(f"/api/my/clients/{cl['Pani Ola']['id']}").get_json()
    assert [h["kind"] for h in card["history"]] == ["correction", "payment", "sale"] and card["history"][1]["method"] == "transfer"
    assert card["stats"]["purchases"] == 1 and card["sales"][0]["eggs"] == 30
    e = c.get("/api/my/eggs?days=365").get_json()
    assert (e["collected"], e["sold"], e["lost"]) == (119, 52, 3)
    assert e["stock"]["eggs"] == 20 + 119 - 52 - 3                       # inwentaryzacja + zebrane - sprzedane - straty
    assert c.get("/api/my/farm").get_json()["price10"] == 13              # cena jajka 1,30 zł/szt., farma nie miała ceny
    fl = c.get("/api/my/flocks").get_json()
    assert [(f["name"], f["birds"]) for f in fl] == [("Nioski", 25), ("Kogut", 1)]
    ex = c.get("/api/my/expenses?days=3650").get_json()
    assert ex["by_category"] == {"Pasza i zboże": 110, "Weterynarz": 80}
    eq = {x["name"]: x["state"] for x in c.get("/api/my/equipment").get_json()}
    assert eq == {"Poidło": "ok", "Lampa": "repair"}
    s = c.get("/api/my/subscriptions").get_json()
    assert [(x["client_name"], x["eggs"], x["every_days"], x["next_date"], x["method"]) for x in s] == [("Pani Ola", 30, 7, "2026-10-30", "cash")]
    feed = c.get("/api/my/feed").get_json()
    it = {i["name"]: i for i in feed["items"]}
    assert (it["Pszenica"]["stock"], it["Pszenica"]["price"], it["Pszenica"]["protein"], it["Pszenica"]["category"]) == (300, 1.1, 11.5, "grain")
    assert it["Śruta sojowa"]["category"] == "protein" and it["Witaminy"]["category"] == "additive"
    rec = feed["recipes"][0]
    assert (rec["name"], rec["active"], rec["total_percent"], rec["season"]) == ("Nioski", True, 100, "all")
    assert feed["mixes"][0]["kg"] == 50
    assert "już zaimportowane" in run(args=["import-ekurnik", path, "--email", "a@x.pl"]).output


def test_import_requires_gid_when_many_farms_and_merges_by_phone(app, tmp_path):
    c, fid = make(app, "z@x.pl", "Farma Z")
    c.put("/api/my/farm", {"stock": 0})
    c.post("/api/my/clients", {"name": "Ola ze sklepu", "phone": "+48 600100200"})
    path = ekurnik_db(tmp_path)
    con = sqlite3.connect(path)
    con.execute("INSERT INTO produkcja(gospodarstwo_id,data,jaja_zebrane,jaja_sprzedane) VALUES (2,'2026-09-01',5,0)")
    con.commit(), con.close()
    r = app.test_cli_runner().invoke(args=["import-ekurnik", path, "--email", "z@x.pl"])
    assert r.exit_code != 0 and "--gid 1" in r.output and "--gid 2" in r.output
    assert app.test_cli_runner().invoke(args=["import-ekurnik", path, "--email", "z@x.pl", "--gid", "9"]).exit_code != 0
    assert app.test_cli_runner().invoke(args=["import-ekurnik", path, "--email", "z@x.pl", "--gid", "1"]).exit_code == 0
    names = [x["name"] for x in c.get("/api/my/clients").get_json()]
    assert "Ola ze sklepu" in names and "Pani Ola" not in names        # ten sam telefon: dopisane do istniejącego klienta
    assert c.get("/api/my/farm").get_json()["price10"] == 13          # cena jajka 1,30 zł/szt. (farma nie miała ceny)
