"""Kartoteka klienta (jak w e-kurniku): sprzedaż, sposób płatności, dług, nadpłata, wpłaty, korekty, uprawnienia."""
from zniesione import create_app


def setup(farmer, stock=50, price=14):
    c, fid = farmer
    c.put("/api/my/farm", {"stock": stock, "price10": price})
    return c, fid


def card(c, cid):
    return c.get(f"/api/my/clients/{cid}").get_json()


def test_shop_order_creates_client_once_per_phone(app, farmer, farmer2, anon):
    c, fid = setup(farmer)
    for name in ("Anna Nowak", "Ania N."):
        anon.post(f"/api/farms/{fid}/orders", {"name": name, "phone": "600 300 400", "qty": 1})
    anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "+48600111222", "qty": 1})
    cl = c.get("/api/my/clients").get_json()
    assert sorted(x["name"] for x in cl) == ["Anna Nowak", "Jan"]                 # ten sam telefon = ten sam klient
    assert all(o["client_id"] for o in c.get("/api/my/orders").get_json())
    assert farmer2[0].get("/api/my/clients").get_json() == []


def test_debt_partial_payment_settle_and_overpayment(app, farmer):
    c, _ = setup(farmer)
    cid = c.post("/api/my/clients", {"name": "Pani Zofia", "phone": "601202303"}).get_json()["id"]
    r = c.post("/api/my/sales", {"client_id": cid, "packs": 3, "method": "later"}).get_json()   # 3 × 14 zł na dług
    assert (r["total"], r["paid"], r["balance"], r["stock"]) == (42, 0, 42, 47)
    assert c.post(f"/api/my/clients/{cid}/payments", {"amount": 20, "method": "cash"}).get_json()["balance"] == 22
    assert c.post(f"/api/my/clients/{cid}/payments", {"settle": True, "method": "transfer"}).get_json()["balance"] == 0
    assert c.post(f"/api/my/clients/{cid}/payments", {"settle": True}).status_code == 409        # nie ma już długu
    assert c.post(f"/api/my/clients/{cid}/payments", {"amount": 50, "method": "blik"}).get_json()["balance"] == -50  # nadpłata
    r = c.post("/api/my/sales", {"client_id": cid, "packs": 2, "method": "balance"}).get_json()  # płaci z nadpłaty
    assert r["balance"] == -22
    assert c.post(f"/api/my/clients/{cid}/payments", {"kind": "refund", "amount": 30}).status_code == 409
    assert c.post(f"/api/my/clients/{cid}/payments", {"kind": "refund", "amount": 22, "method": "cash"}).get_json()["balance"] == 0
    k = card(c, cid)
    assert [h["kind"] for h in k["history"]] == ["refund", "sale", "payment", "payment", "payment", "sale"]
    assert [h["balance_after"] for h in k["history"]] == [0, -22, -50, 0, 22, 42]
    assert k["stats"] == {"purchases": 2, "packs": 5, "value": 70, "paid": 70, "last_sale": k["sales"][0]["at"]}


def test_payment_at_sale_less_or_more_than_total(app, farmer):
    c, _ = setup(farmer)
    cid = c.post("/api/my/clients", {"name": "Jan"}).get_json()["id"]
    assert c.post("/api/my/sales", {"client_id": cid, "packs": 3, "method": "cash", "paid": 40}).get_json()["balance"] == 2   # brakuje 2 zł
    assert c.post("/api/my/sales", {"client_id": cid, "packs": 1, "method": "cash", "paid": 20}).get_json()["balance"] == -4  # zostawił resztę
    assert c.post("/api/my/sales", {"client_id": cid, "packs": 1, "method": "transfer"}).get_json()["balance"] == -4          # całość przelewem
    k = card(c, cid)
    assert {h["method"] for h in k["history"] if h["kind"] == "payment"} == {"cash", "transfer"}


def test_client_price_discount_and_anonymous_sale(app, farmer):
    c, _ = setup(farmer, price=14)
    cid = c.post("/api/my/clients", {"name": "Sklep", "price10": 12.5}).get_json()["id"]
    assert c.post("/api/my/sales", {"client_id": cid, "packs": 4, "method": "cash", "discount": 5}).get_json()["total"] == 45
    assert c.post("/api/my/sales", {"packs": 2, "method": "blik"}).get_json()["total"] == 28       # bez kartoteki, cena z oferty
    for bad in ({"packs": 2, "method": "later"}, {"packs": 2, "method": "cash", "paid": 10}, {"packs": 2, "method": "gold"},
                {"packs": 0}, {"packs": 501}, {"packs": "2"}, {"packs": 2, "price10": -1}, {"packs": 1, "discount": 20},
                {"client_id": cid, "packs": 1, "method": "later", "paid": 5}, {"client_id": 999, "packs": 1}):
        assert c.post("/api/my/sales", bad).status_code == 400, bad
    r = c.post("/api/my/sales", {"packs": 500, "method": "cash"})
    assert r.status_code == 409 and "Na stanie jest tylko 44" in r.get_json()["error"]
    assert c.get("/api/my/eggs?days=1").get_json()["sold"] == 60                                 # dziennik jaj (w sztukach) widzi sprzedaż


def test_deliver_confirmed_order_and_undo(app, farmer, anon):
    c, fid = setup(farmer, stock=10)
    oid = anon.post(f"/api/farms/{fid}/orders", {"name": "Anna", "phone": "600300400", "qty": 3}).get_json()["id"]
    assert c.post("/api/my/sales", {"order_id": oid, "method": "later"}).status_code == 409       # niepotwierdzone
    c.post(f"/api/my/orders/{oid}/confirm")                                                     # stan 10 -> 7
    r = c.post("/api/my/sales", {"order_id": oid, "method": "later"}).get_json()
    assert (r["total"], r["stock"], r["balance"]) == (42, 7, 42)                                # wydanie nie odejmuje drugi raz
    assert c.post("/api/my/sales", {"order_id": oid, "method": "cash"}).status_code == 409
    assert [o["status"] for o in c.get("/api/my/orders").get_json()] == ["delivered"]
    cid = c.get("/api/my/orders").get_json()[0]["client_id"]
    assert card(c, cid)["orders"] == []                                                         # wydane nie jest już aktywne
    assert c.delete(f"/api/my/sales/{r['id']}").get_json()["balance"] == 0
    assert [o["status"] for o in c.get("/api/my/orders").get_json()] == ["confirmed"]
    s = c.post("/api/my/sales", {"packs": 2, "method": "cash"}).get_json()
    assert s["stock"] == 5 and c.delete(f"/api/my/sales/{s['id']}").status_code == 200
    assert c.get(f"/api/farms/{fid}").get_json()["stock"] == 7 and c.get("/api/my/eggs?days=1").get_json()["sold"] == 0


def test_client_crud_validation_correction_and_delete(app, farmer):
    c, _ = setup(farmer)
    for bad in ({"name": ""}, {"name": "A", "phone": "abc"}, {"name": "A", "email": "x@"}, {"name": "A", "price10": -1},
                {"name": "A", "notes": "x" * 1001}, {"name": 5}):
        assert c.post("/api/my/clients", bad).status_code == 400, bad
    a = c.post("/api/my/clients", {"name": "Ala", "phone": "600 100 200", "email": "ala@x.pl", "address": "Lipowa 3"}).get_json()
    assert c.post("/api/my/clients", {"name": "Inna", "phone": "+48600100200"}).status_code == 409   # ten sam numer
    assert c.patch(f"/api/my/clients/{a['id']}", {"notes": "płaci w piątki", "price10": None}).get_json()["notes"] == "płaci w piątki"
    assert c.post(f"/api/my/clients/{a['id']}/correction", {"balance": 15}).status_code == 400        # brak powodu
    assert c.post(f"/api/my/clients/{a['id']}/correction", {"balance": 15, "note": "dług z zeszytu"}).get_json()["balance"] == 15
    assert c.delete(f"/api/my/clients/{a['id']}").status_code == 409                                  # ma historię
    b = c.post("/api/my/clients", {"name": "Bez historii"}).get_json()
    assert c.delete(f"/api/my/clients/{b['id']}").status_code == 200
    assert [x["name"] for x in c.get("/api/my/clients?q=ALA").get_json()] == ["Ala"]


def test_kartoteka_is_private_to_farm(app, farmer, farmer2):
    c, _ = setup(farmer)
    cid = c.post("/api/my/clients", {"name": "Ala"}).get_json()["id"]
    sid = c.post("/api/my/sales", {"client_id": cid, "packs": 1, "method": "later"}).get_json()["id"]
    o = farmer2[0]
    assert o.get(f"/api/my/clients/{cid}").status_code == 404
    assert o.patch(f"/api/my/clients/{cid}", {"name": "X"}).status_code == 404
    assert o.post(f"/api/my/clients/{cid}/payments", {"amount": 5}).status_code == 404
    assert o.post(f"/api/my/clients/{cid}/correction", {"balance": 0, "note": "x"}).status_code == 404
    assert o.post("/api/my/sales", {"client_id": cid, "packs": 1, "method": "later"}).status_code == 400
    assert o.delete(f"/api/my/sales/{sid}").status_code == 404
    assert o.get("/api/my/sales").get_json() == [] and o.get("/api/my/finance").get_json()["debts"] == 0


def test_finance_summary(app, farmer):
    c, _ = setup(farmer)
    a = c.post("/api/my/clients", {"name": "A"}).get_json()["id"]
    b = c.post("/api/my/clients", {"name": "B"}).get_json()["id"]
    c.post("/api/my/sales", {"client_id": a, "packs": 2, "method": "later"})                # dług 28
    c.post("/api/my/sales", {"client_id": b, "packs": 1, "method": "transfer", "paid": 20})  # nadpłata 6
    c.post("/api/my/sales", {"packs": 1, "method": "cash"})                                 # 14 gotówką, bez kartoteki
    f = c.get("/api/my/finance?days=30").get_json()
    assert f["received"] == {"cash": 14, "transfer": 20, "blik": 0} and f["received_total"] == 34
    assert (f["sales_value"], f["sales_eggs"], f["debts"], f["debtors"], f["overpaid"]) == (56, 40, 28, 1, 6)
    c.post("/api/my/expenses", {"category": "Pasza i zboże", "name": "Pszenica", "qty": 10, "unit": "kg", "unit_price": 1.5})
    f = c.get("/api/my/finance?days=30").get_json()
    assert (f["expenses"], f["profit"]) == (15, 41)
    assert c.get("/api/my/finance?days=0").status_code == 400


def test_old_orders_get_clients_on_start(tmp_path):
    import sqlite3
    p = tmp_path / "o.db"
    create_app({"DATABASE": str(p), "TESTING": True})
    con = sqlite3.connect(p)
    con.execute("INSERT INTO farms(name) VALUES('F')")
    con.execute("INSERT INTO orders(farm_id,name,phone,qty,mode,pickup,total,created) VALUES(1,'Stary','600999888',1,'once','pickup',14,'2026-01-01')")
    con.commit(), con.close()
    create_app({"DATABASE": str(p), "TESTING": True})
    con = sqlite3.connect(p)
    assert con.execute("SELECT c.name FROM orders o JOIN clients c ON c.id=o.client_id").fetchone() == ("Stary",)


def test_seed_kartoteka_has_debt_and_overpayment(tmp_path):
    from conftest import Client
    a = create_app({"DATABASE": str(tmp_path / "s.db"), "TESTING": True})
    assert a.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
    c = Client(a)
    c.post("/api/auth/login", {"email": "rolnik@zniesione.test", "password": "Rolnik12345!"})
    bal = {x["name"]: x["balance"] for x in c.get("/api/my/clients").get_json()}
    assert bal == {"Pani Zofia (sąsiadka)": 18, "Pan Marek": -10, "Sklep „Lipka”": 0}
    assert c.get(f"/api/farms/1").get_json()["stock"] == 12                     # historia nie zmienia stanu jaj
