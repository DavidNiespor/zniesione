"""Magazyn jaj w sztukach: ogłoszenie, rezerwacja, sprzedaż z puli; zamówienia cykliczne; wydatki; wyposażenie."""
import sqlite3
from datetime import date, timedelta

from zniesione import create_app


def collect(c, n, dmg=0):
    return c.post("/api/my/eggs", {"kind": "collect", "eggs": n, "damaged": dmg, "sorted": True}).get_json()["stock"]


def pools(c):
    return c.get("/api/my/eggs?days=1").get_json()["stock"]


def client(c, name="Zofia", **kw):
    return c.post("/api/my/clients", {"name": name, **kw}).get_json()["id"]


def test_allocation_offer_and_reserve_limited_by_warehouse(app, farmer, anon):
    c, fid = farmer
    c.put("/api/my/farm", {"price10": 12, "stock": 0})
    collect(c, 105, 5)                                                                     # 100 dobrych
    r = c.post("/api/my/eggs/allocation", {"offer_packs": 8, "reserved": 30})
    assert r.status_code == 409 and "najwyżej 100 szt." in r.get_json()["error"]
    p = c.post("/api/my/eggs/allocation", {"offer_packs": 5, "reserved": 30}).get_json()["stock"]
    assert (p["eggs"], p["offer_packs"], p["reserved"], p["free"]) == (100, 5, 30, 20)
    assert anon.get(f"/api/farms/{fid}").get_json()["stock"] == 5                         # sklep widzi ogłoszone opakowania
    oid = anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "600111222", "qty": 2}).get_json()["id"]
    c.post(f"/api/my/orders/{oid}/confirm")
    p = pools(c)
    assert (p["offer_packs"], p["committed"], p["free"]) == (3, 20, 20)
    r = c.post("/api/my/eggs/allocation", {"offer_packs": 6, "reserved": 30})               # 60+30+20 > 100
    assert r.status_code == 409 and "20 szt. czeka na wydanie" in r.get_json()["error"]
    assert c.post("/api/my/sales", {"order_id": oid, "method": "cash"}).get_json()["pools"]["eggs"] == 80
    for bad in ({"offer_packs": -1, "reserved": 0}, {"offer_packs": 1}, {"offer_packs": 1, "reserved": "5"}):
        assert c.post("/api/my/eggs/allocation", bad).status_code == 400


def test_sale_sources_free_reserve_offer(app, farmer):
    c, _ = farmer
    c.put("/api/my/farm", {"price10": 12, "stock": 0})
    collect(c, 100)
    c.post("/api/my/eggs/allocation", {"offer_packs": 3, "reserved": 40})                  # wolne: 30
    cid = client(c)
    r = c.post("/api/my/sales", {"client_id": cid, "eggs": 15, "method": "later"}).get_json()   # 15 szt. luzem
    assert (r["total"], r["pools"]["free"], r["pools"]["eggs"]) == (18, 15, 85)
    r = c.post("/api/my/sales", {"client_id": cid, "eggs": 16, "method": "cash"})
    assert r.status_code == 409 and "Wolnych jaj jest tylko 15" in r.get_json()["error"]
    r = c.post("/api/my/sales", {"client_id": cid, "eggs": 30, "method": "cash", "source": "reserve"}).get_json()
    assert (r["pools"]["reserved"], r["pools"]["free"]) == (10, 15)
    assert c.post("/api/my/sales", {"eggs": 15, "method": "cash", "source": "offer"}).status_code == 400   # nie całe opakowania
    r = c.post("/api/my/sales", {"eggs": 20, "method": "blik", "source": "offer"}).get_json()
    assert (r["pools"]["offer_packs"], r["total"]) == (1, 24)
    assert c.post("/api/my/sales", {"eggs": 20, "method": "cash", "source": "reserve"}).status_code == 409
    assert c.post("/api/my/sales", {"eggs": 5, "method": "cash", "source": "gdzieś"}).status_code == 400
    sid = c.get("/api/my/sales").get_json()[1]["id"]                                       # sprzedaż z rezerwy
    c.delete(f"/api/my/sales/{sid}")
    p = pools(c)
    assert (p["reserved"], p["eggs"]) == (40, 65)                                          # rezerwa wróciła


def test_subscriptions_reserve_deliver_and_skip(app, farmer, farmer2):
    c, _ = farmer
    c.put("/api/my/farm", {"price10": 12, "stock": 0})
    collect(c, 100)
    cid = client(c, price10=11)
    today = date.today().isoformat()
    for bad in ({"client_id": cid, "eggs": 0}, {"client_id": cid, "eggs": 30, "every_days": 0}, {"client_id": 999, "eggs": 30},
                {"client_id": cid, "eggs": 30, "next_date": "jutro"}, {"client_id": cid, "eggs": 30, "method": "karta"}):
        assert c.post("/api/my/subscriptions", bad).status_code == 400, bad
    s = c.post("/api/my/subscriptions", {"client_id": cid, "eggs": 30, "every_days": 7, "next_date": today}).get_json()
    assert s["due"] and s["client_name"] == "Zofia" and s["method"] == "later"
    assert c.get("/api/my/eggs").get_json()["reserve_needed_7d"] == 30
    c.post("/api/my/eggs/allocation", {"offer_packs": 0, "reserved": 30})
    r = c.post("/api/my/sales", {"subscription_id": s["id"], "method": "later"}).get_json()     # domyślnie z rezerwy, cena klienta
    assert (r["eggs"], r["total"], r["pools"]["reserved"], r["balance"]) == (30, 33, 0, 33)
    s2 = c.get(f"/api/my/subscriptions?client_id={cid}").get_json()[0]
    assert s2["next_date"] == (date.today() + timedelta(days=7)).isoformat() and not s2["due"]
    assert c.post(f"/api/my/subscriptions/{s['id']}/skip").get_json()["next_date"] == (date.today() + timedelta(days=14)).isoformat()
    assert c.patch(f"/api/my/subscriptions/{s['id']}", {"active": False, "eggs": 20}).get_json()["active"] is False
    assert farmer2[0].patch(f"/api/my/subscriptions/{s['id']}", {"eggs": 1}).status_code == 404
    assert farmer2[0].post("/api/my/sales", {"subscription_id": s["id"], "method": "cash"}).status_code == 404
    assert farmer2[0].get("/api/my/subscriptions").get_json() == []
    assert c.delete(f"/api/my/subscriptions/{s['id']}").status_code == 200


def test_weekly_shop_order_becomes_subscription(app, farmer, anon):
    c, fid = farmer
    c.put("/api/my/farm", {"price10": 12, "stock": 5})
    oid = anon.post(f"/api/farms/{fid}/orders", {"name": "Ewa", "phone": "600555666", "qty": 2, "mode": "biweekly"}).get_json()["id"]
    sid = c.post(f"/api/my/orders/{oid}/confirm").get_json()["subscription_id"]
    s = c.get("/api/my/subscriptions").get_json()
    assert [(x["id"], x["eggs"], x["every_days"], x["client_name"]) for x in s] == [(sid, 20, 14, "Ewa")]


def test_inventory_sets_warehouse(app, farmer):
    c, _ = farmer
    collect(c, 50)
    c.post("/api/my/eggs/allocation", {"offer_packs": 2, "reserved": 10})
    r = c.post("/api/my/eggs", {"kind": "inventory", "eggs": 25})
    assert r.status_code == 409 and "(30 szt.)" in r.get_json()["error"]
    assert c.post("/api/my/eggs", {"kind": "inventory", "eggs": 44, "note": "policzone w piątek"}).get_json()["stock"]["free"] == 14
    e = c.get("/api/my/eggs").get_json()["entries"][0]
    assert (e["kind"], e["eggs"], e["note"]) == ("inventory", -6, "policzone w piątek")


def test_expenses_crud_summary_and_validation(app, farmer, farmer2):
    c, _ = farmer
    for bad in ({"name": "", "total": 5}, {"name": "X"}, {"name": "X", "total": -1}, {"name": "X", "total": 5, "date": "2026-13-01"},
                {"name": "X", "qty": "2", "unit_price": 1}, {"name": "X", "total": 5, "category": ""}):
        assert c.post("/api/my/expenses", bad).status_code == 400, bad
    a = c.post("/api/my/expenses", {"category": "Pasza i zboże", "name": "Pszenica", "qty": 100, "unit": "kg", "unit_price": 1.15,
                                    "supplier": "GS Lipowa"}).get_json()
    assert a["total"] == 115
    c.post("/api/my/expenses", {"category": "Weterynarz", "name": "Wizyta", "total": 150})
    old = (date.today() - timedelta(days=60)).isoformat()
    c.post("/api/my/expenses", {"category": "Weterynarz", "name": "Szczepienie", "total": 90, "date": old})
    r = c.get("/api/my/expenses?days=30").get_json()
    assert (r["total"], r["by_category"]) == (265, {"Pasza i zboże": 115, "Weterynarz": 150})
    assert "Ściółka" in r["categories"] and c.get("/api/my/expenses?days=365").get_json()["total"] == 355
    assert c.patch(f"/api/my/expenses/{a['id']}", {"qty": 200}).get_json()["total"] == 230      # przelicza wartość
    assert farmer2[0].patch(f"/api/my/expenses/{a['id']}", {"total": 1}).status_code == 404
    assert farmer2[0].get("/api/my/expenses").get_json()["entries"] == []
    assert c.delete(f"/api/my/expenses/{a['id']}").status_code == 200


def test_equipment_crud_and_service_reminder(app, farmer, farmer2):
    c, _ = farmer
    for bad in ({"name": ""}, {"name": "X", "state": "nowe"}, {"name": "X", "price": -5}, {"name": "X", "next_check": "kiedyś"}):
        assert c.post("/api/my/equipment", bad).status_code == 400, bad
    soon = (date.today() + timedelta(days=3)).isoformat()
    a = c.post("/api/my/equipment", {"name": "Poidło 10 l", "category": "Poidło", "price": 89, "bought": "2026-03-15"}).get_json()
    b = c.post("/api/my/equipment", {"name": "Lampa", "state": "repair", "next_check": soon}).get_json()
    assert not a["check_due"] and b["check_due"]
    assert c.patch(f"/api/my/equipment/{b['id']}", {"state": "retired"}).get_json()["check_due"] is False
    assert [x["name"] for x in c.get("/api/my/equipment").get_json()] == ["Poidło 10 l", "Lampa"]   # wycofane na końcu
    assert farmer2[0].delete(f"/api/my/equipment/{a['id']}").status_code == 404
    assert c.delete(f"/api/my/equipment/{a['id']}").status_code == 200


def test_old_egg_log_is_migrated_to_pieces(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("""CREATE TABLE farms(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT DEFAULT '', zip TEXT DEFAULT '',
      breed TEXT DEFAULT '', descr TEXT DEFAULT '', price10 REAL DEFAULT 0, stock INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
      CREATE TABLE eggs(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN('collect','sale')),
      packs INTEGER NOT NULL, at TEXT NOT NULL);
      INSERT INTO farms(name,stock) VALUES('F',7); INSERT INTO eggs(farm_id,kind,packs,at) VALUES(1,'collect',4,'2026-10-01');""")
    con.commit(), con.close()
    create_app({"DATABASE": str(p), "TESTING": True})
    con = sqlite3.connect(p)
    assert con.execute("SELECT kind, eggs, packs FROM eggs").fetchone() == ("collect", 40, 4)
    assert con.execute("SELECT eggs FROM farms").fetchone() == (70,)                        # 7 opakowań w sklepie = 70 szt.
    con.execute("INSERT INTO eggs(farm_id,kind,eggs,at) VALUES(1,'loss',2,'2026-10-02')")   # stare ograniczenie usunięte


def test_collect_goes_to_sorting_then_warehouse(app, farmer, farmer2):
    c, _ = farmer
    st = c.post("/api/my/eggs", {"kind": "collect", "eggs": 40}).get_json()["stock"]
    assert (st["unsorted"], st["eggs"]) == (40, 0)                                       # najpierw sortowanie
    assert c.get("/api/my/eggs").get_json()["collected_today"] == 40
    for bad in ({"kind": "sort"}, {"kind": "sort", "good": -1}, {"kind": "sort", "good": "5"}):
        assert c.post("/api/my/eggs", bad).status_code == 400, bad
    r = c.post("/api/my/eggs", {"kind": "sort", "good": 38, "dirty": 2, "damaged": 1})
    assert r.status_code == 409 and "tylko 40" in r.get_json()["error"]
    st = c.post("/api/my/eggs", {"kind": "sort", "good": 36, "dirty": 3, "damaged": 1}).get_json()["stock"]
    assert (st["unsorted"], st["eggs"], st["free"]) == (0, 36, 36)
    e = c.get("/api/my/eggs").get_json()
    assert (e["collected"], e["good"], e["dirty"], e["damaged"]) == (40, 36, 3, 1)
    assert farmer2[0].post("/api/my/eggs", {"kind": "sort", "good": 1}).status_code == 409


def test_gifts_are_tracked_by_recipient(app, farmer):
    c, _ = farmer
    collect(c, 50)
    c.post("/api/my/eggs/allocation", {"offer_packs": 2, "reserved": 10})                  # wolne: 20
    assert c.post("/api/my/eggs", {"kind": "gift", "eggs": 10}).status_code == 400         # komu?
    assert c.post("/api/my/eggs", {"kind": "gift", "eggs": 21, "who": "Mama"}).status_code == 409
    c.post("/api/my/eggs", {"kind": "gift", "eggs": 10, "who": "Mama"})
    c.post("/api/my/eggs", {"kind": "gift", "eggs": 6, "who": "Sąsiad Jan", "note": "za pomoc przy płocie"})
    c.post("/api/my/eggs", {"kind": "gift", "eggs": 4, "who": "Mama"})
    e = c.get("/api/my/eggs").get_json()
    assert e["given"] == 20 and e["given_to"] == {"Mama": 14, "Sąsiad Jan": 6} and e["stock"]["free"] == 0
    assert e["recipients"][0] == "Mama"
