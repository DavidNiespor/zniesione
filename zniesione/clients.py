"""Kartoteka klientów (jak w e-kurniku): zakupy, wpłaty, sposób płatności, dług i nadpłata.

Saldo klienta to suma wpisów w tabeli ledger: sprzedaż zwiększa saldo, wpłata zmniejsza. Saldo > 0 to dług
(klient ma zapłacić), saldo < 0 to nadpłata (klient ma zapas na kolejne zakupy albo do zwrotu). Saldo nie jest
przechowywane osobno, więc po usunięciu sprzedaży zawsze się zgadza."""
import re
from datetime import datetime, timedelta

from flask import g, jsonify, request

from . import db as dbm
from . import farmbook

METHODS = ("cash", "transfer", "blik", "later", "balance")   # gotówka, przelew, BLIK, następnym razem, z nadpłaty
PAID_NOW = ("cash", "transfer", "blik")
CLIENT = dict(name="", phone="", email="", address="", notes="", price10=None)


def money(v, lo=0, hi=100000):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def phone_key(phone):
    return re.sub(r"\D", "", phone or "")[-9:]


def now():
    return datetime.now().isoformat(timespec="seconds")


def ensure_client(db, farm_id, name, phone):
    """Klient z zamówienia w sklepie: ten sam numer telefonu = ten sam klient w kartotece."""
    key = phone_key(phone)
    r = db.execute("SELECT id FROM clients WHERE farm_id=? AND phone_key=? AND phone_key!=''", (farm_id, key)).fetchone()
    if r:
        return r["id"]
    return db.execute("INSERT INTO clients(farm_id,name,phone,phone_key,created) VALUES(?,?,?,?,?)",
                      (farm_id, name.strip()[:100], phone.strip(), key, now())).lastrowid


def backfill(db):
    """Zamówienia sprzed kartoteki: dopisz klientów (raz, przy starcie)."""
    for o in db.execute("SELECT id, farm_id, name, phone FROM orders WHERE client_id IS NULL").fetchall():
        db.execute("UPDATE orders SET client_id=? WHERE id=?", (ensure_client(db, o["farm_id"], o["name"], o["phone"]), o["id"]))
    db.commit()


def register(app, need, q, commit, body, err, integer):
    def client_row(cid):
        return q("SELECT * FROM clients WHERE id=? AND farm_id=?", cid, g.user["farm_id"]).fetchone()

    def balance(cid):
        return round(q("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE client_id=?", cid).fetchone()[0], 2)

    def client_json(c, extra=None):
        return dict(id=c["id"], name=c["name"], phone=c["phone"], email=c["email"], address=c["address"],
                    notes=c["notes"], price10=c["price10"], created=c["created"], **(extra or {}))

    def client_check(b, old):
        c = {**CLIENT, **({k: old[k] for k in CLIENT} if old else {}), **{k: b[k] for k in CLIENT if k in b}}
        for k, n in (("name", 100), ("phone", 20), ("email", 120), ("address", 200), ("notes", 1000)):
            if not isinstance(c[k], str) or len(c[k]) > n:
                return None, f"Pole {k} może mieć do {n} znaków"
            c[k] = c[k].strip()
        if not c["name"]:
            return None, "Podaj imię i nazwisko lub nazwę klienta"
        if c["phone"] and not re.fullmatch(r"\+?[0-9 ]{7,15}", c["phone"]):
            return None, "Niepoprawny telefon"
        if c["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c["email"]):
            return None, "Niepoprawny e-mail"
        if c["price10"] is not None and not money(c["price10"], 0, 1000):
            return None, "Cena za 10 szt. od 0 do 1000 zł albo puste pole (cena z oferty)"
        dup = q("SELECT id FROM clients WHERE farm_id=? AND phone_key=? AND phone_key!='' AND id!=?",
                g.user["farm_id"], phone_key(c["phone"]), old["id"] if old else 0).fetchone()
        if dup:
            return None, "Klient z tym numerem telefonu jest już w kartotece"
        return c, None

    @app.route("/api/my/clients", methods=["GET", "POST"])
    @need("farmer")
    def clients():
        fid = g.user["farm_id"]
        if request.method == "POST":
            c, msg = client_check(body(), None)
            if msg:
                return err(msg, 409 if "już" in msg else 400)
            cid = q("INSERT INTO clients(farm_id,name,phone,phone_key,email,address,notes,price10,created) VALUES(?,?,?,?,?,?,?,?,?)",
                    fid, c["name"], c["phone"], phone_key(c["phone"]), c["email"], c["address"], c["notes"], c["price10"], now()).lastrowid
            commit()
            return jsonify(client_json(client_row(cid), {"balance": 0})), 201
        s = request.args.get("q", "").strip().casefold()
        rows = q("""SELECT c.*, COALESCE((SELECT SUM(amount) FROM ledger l WHERE l.client_id=c.id),0) AS bal,
                      (SELECT COUNT(*) FROM sales s WHERE s.client_id=c.id) AS n,
                      (SELECT COALESCE(SUM(packs),0) FROM sales s WHERE s.client_id=c.id) AS packs,
                      (SELECT COALESCE(SUM(total),0) FROM sales s WHERE s.client_id=c.id) AS value,
                      (SELECT MAX(at) FROM sales s WHERE s.client_id=c.id) AS last_sale,
                      (SELECT COUNT(*) FROM orders o WHERE o.client_id=c.id AND o.mode!='once') AS regular
                    FROM clients c WHERE c.farm_id=? ORDER BY c.name""", fid).fetchall()
        rows = [r for r in rows if not s or s in f"{r['name']} {r['phone']} {r['email']}".casefold()]
        return jsonify([client_json(r, dict(balance=round(r["bal"], 2), purchases=r["n"], packs=r["packs"],
                                            value=round(r["value"], 2), last_sale=r["last_sale"], regular=bool(r["regular"])))
                        for r in rows])

    @app.route("/api/my/clients/<int:cid>", methods=["GET", "PATCH", "DELETE"])
    @need("farmer")
    def client(cid):
        old = client_row(cid)
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "PATCH":
            c, msg = client_check(body(), old)
            if msg:
                return err(msg, 409 if "już" in msg else 400)
            q("UPDATE clients SET name=?,phone=?,phone_key=?,email=?,address=?,notes=?,price10=? WHERE id=?",
              c["name"], c["phone"], phone_key(c["phone"]), c["email"], c["address"], c["notes"], c["price10"], cid)
            commit()
            return jsonify(client_json(client_row(cid), {"balance": balance(cid)}))
        if request.method == "DELETE":
            if q("SELECT 1 FROM sales WHERE client_id=? UNION SELECT 1 FROM ledger WHERE client_id=?", cid, cid).fetchone():
                return err("Klient ma historię zakupów lub wpłat, więc nie można go usunąć", 409)
            q("UPDATE orders SET client_id=NULL WHERE client_id=?", cid)
            q("DELETE FROM clients WHERE id=?", cid)
            commit()
            return jsonify(ok=True)
        led = q(f"SELECT *, {dbm.by_sql('ledger')} FROM ledger WHERE client_id=? ORDER BY at, id", cid).fetchall()
        run, history = 0.0, []
        for r in led:  # saldo po każdym wpisie liczone na bieżąco
            run = round(run + r["amount"], 2)
            history.append(dict(id=r["id"], at=r["at"], kind=r["kind"], amount=round(r["amount"], 2), method=r["method"],
                                sale_id=r["sale_id"], note=r["note"], balance_after=run, by_name=r["by_name"]))
        sales = [dict(r) for r in q("SELECT * FROM sales WHERE client_id=? ORDER BY at DESC, id DESC LIMIT 100", cid)]
        orders = [dict(r) for r in q("SELECT * FROM orders WHERE client_id=? AND status IN ('pending','confirmed') ORDER BY id", cid)]
        paid = -sum(r["amount"] for r in led if r["kind"] == "payment") - sum(r["amount"] for r in led if r["kind"] == "refund")
        stats = dict(purchases=len(sales), packs=sum(s["packs"] for s in sales), eggs=sum(s["eggs"] for s in sales), value=round(sum(s["total"] for s in sales), 2),
                     paid=round(paid, 2), last_sale=sales[0]["at"] if sales else None)
        return jsonify(client_json(old, dict(balance=run, stats=stats, history=history[::-1][:200], sales=sales, orders=orders)))

    @app.post("/api/my/clients/<int:cid>/payments")
    @need("farmer")
    def payment(cid):
        if not client_row(cid):
            return err("Nie znaleziono", 404)
        b, bal = body(), balance(cid)
        kind, method = b.get("kind", "payment"), b.get("method", "cash")
        if kind not in ("payment", "refund"):
            return err("Rodzaj: payment (wpłata) albo refund (zwrot nadpłaty)")
        if method not in PAID_NOW:
            return err("Sposób płatności: cash, transfer albo blik")
        note = b.get("note", "")
        if not isinstance(note, str) or len(note) > 200:
            return err("Opis do 200 znaków")
        amount = b.get("amount")
        if b.get("settle") is True:  # „rozlicz do zera”: wpłata równa długowi
            if bal <= 0:
                return err("Klient nie ma długu do rozliczenia", 409)
            amount, kind = bal, "payment"
        if not money(amount, 0.01, 100000):
            return err("Kwota od 0,01 do 100 000 zł")
        if kind == "refund" and amount > round(-bal, 2) + 0.005:
            return err(f"Nadpłata klienta to tylko {max(0, -bal):.2f} zł", 409)
        q("INSERT INTO ledger(farm_id,client_id,at,kind,amount,method,note) VALUES(?,?,?,?,?,?,?)", g.user["farm_id"], cid, now(),
          kind, round(-amount if kind == "payment" else amount, 2), method, note.strip() or ("Wpłata" if kind == "payment" else "Zwrot nadpłaty"))
        commit()
        return jsonify(balance=balance(cid)), 201

    @app.post("/api/my/clients/<int:cid>/correction")
    @need("farmer")
    def correction(cid):
        if not client_row(cid):
            return err("Nie znaleziono", 404)
        b = body()
        if not money(b.get("balance"), -100000, 100000):
            return err("Nowe saldo od -100 000 do 100 000 zł (minus to nadpłata)")
        note = b.get("note", "")
        if not isinstance(note, str) or not note.strip() or len(note) > 200:
            return err("Podaj powód korekty (do 200 znaków)")
        diff = round(b["balance"] - balance(cid), 2)
        if diff:
            q("INSERT INTO ledger(farm_id,client_id,at,kind,amount,note) VALUES(?,?,?,?,?,?)", g.user["farm_id"], cid, now(),
              "correction", diff, note.strip())
            commit()
        return jsonify(balance=balance(cid))

    @app.route("/api/my/sales", methods=["GET", "POST"])
    @need("farmer")
    def sales():
        fid = g.user["farm_id"]
        if request.method == "GET":
            days = request.args.get("days", "30")
            if not days.isdigit() or not 1 <= int(days) <= 366:
                return err("Parametr days od 1 do 366")
            since = (datetime.now() - timedelta(days=int(days))).isoformat()
            rows = q(f"SELECT s.*, c.name AS client_name, {dbm.by_sql('s')} FROM sales s LEFT JOIN clients c ON c.id=s.client_id "
                     "WHERE s.farm_id=? AND s.at>=? ORDER BY s.at DESC, s.id DESC", fid, since)
            return jsonify([dict(r) for r in rows])
        b = body()
        method = b.get("method", "cash")
        if method not in METHODS:
            return err("Sposób płatności: cash, transfer, blik, later (następnym razem) albo balance (z nadpłaty)")
        c, o, sub = None, None, None
        if b.get("order_id") is not None:  # wydanie potwierdzonego zamówienia ze sklepu
            o = q("SELECT * FROM orders WHERE id=? AND farm_id=?", b["order_id"], fid).fetchone() if integer(b["order_id"], 1, 10 ** 9) else None
            if not o:
                return err("Nie znaleziono zamówienia", 404)
            if o["status"] != "confirmed":
                return err("Wydać można tylko potwierdzone zamówienie, które nie zostało jeszcze wydane", 409)
            c = client_row(o["client_id"]) if o["client_id"] else None
            eggs, price10, discount, total, source = o["qty"] * 10, round(o["total"] / o["qty"], 2), 0, round(o["total"], 2), "order"
        else:
            if b.get("subscription_id") is not None:  # dostawa dla stałego klienta (zamówienie cykliczne)
                sub = q("SELECT * FROM subscriptions WHERE id=? AND farm_id=?", b["subscription_id"], fid).fetchone() \
                    if integer(b["subscription_id"], 1, 10 ** 9) else None
                if not sub:
                    return err("Nie znaleziono zamówienia cyklicznego", 404)
                c, eggs = client_row(sub["client_id"]), b.get("eggs", sub["eggs"])
            else:
                if b.get("client_id") is not None:
                    c = client_row(b["client_id"]) if integer(b["client_id"], 1, 10 ** 9) else None
                    if not c:
                        return err("Nieznany klient")
                eggs = b.get("eggs", b["packs"] * 10 if integer(b.get("packs"), 1, 500) else None)
            if not integer(eggs, 1, 5000):
                return err("Liczba jaj od 1 do 5000 szt. (albo opakowań od 1 do 500)")
            farm = q("SELECT price10, reserved FROM farms WHERE id=?", fid).fetchone()
            price10 = b.get("price10", c["price10"] if c and c["price10"] is not None else farm["price10"])
            discount = b.get("discount", 0)
            if not money(price10, 0, 1000):
                return err("Cena za 10 szt. od 0 do 1000 zł")
            if not money(discount, 0, 100000):
                return err("Rabat nie może być ujemny")
            total = round(eggs * price10 / 10 - discount, 2)
            if total < 0:
                return err("Rabat jest większy niż wartość sprzedaży")
            # skąd jaja: wolne z magazynu, z rezerwy stałych klientów albo z ogłoszonych w sklepie (opakowania)
            default = "reserve" if sub and farm["reserved"] >= eggs else "offer" if "packs" in b and "eggs" not in b else "free"
            source = b.get("source", default)
            if source not in ("free", "reserve", "offer"):
                return err("Źródło jaj: free (wolne), reserve (rezerwa) albo offer (ogłoszone w sklepie)")
            if source == "offer" and eggs % 10:
                return err("Z ogłoszonych w sklepie sprzedaje się całe opakowania po 10 szt.")
        if method in ("later", "balance") and not c:
            return err("Sprzedaż na dług lub z nadpłaty wymaga klienta z kartoteki")
        paid = b.get("paid", total if method in PAID_NOW else 0)
        if not money(paid, 0, 100000):
            return err("Zapłacona kwota od 0 do 100 000 zł")
        if method not in PAID_NOW and paid:
            return err("Przy sprzedaży na dług lub z nadpłaty nie podaje się wpłaty; wybierz gotówkę, przelew albo BLIK")
        if not c and abs(paid - total) > 0.005:
            return err("Klient spoza kartoteki musi zapłacić całość; dodaj go do kartoteki, żeby zapisać dług lub nadpłatę")
        notes = b.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 200:
            return err("Uwagi do 200 znaków")
        # pule jaj zmieniane jednym zapytaniem z warunkiem: dwa kliknięcia naraz nie zejdą poniżej zera
        if source == "order":
            if not q("UPDATE orders SET status='delivered' WHERE id=? AND status='confirmed'", o["id"]).rowcount:
                return err("Zamówienie zostało już wydane", 409)
            q("UPDATE farms SET eggs=MAX(0, eggs-?) WHERE id=?", eggs, fid)
        elif source == "offer":
            if not q("UPDATE farms SET stock=stock-?, eggs=MAX(0, eggs-?) WHERE id=? AND stock>=?", eggs // 10, eggs, fid, eggs // 10).rowcount:
                return err(f"Na stanie jest tylko {q('SELECT stock FROM farms WHERE id=?', fid).fetchone()['stock']} opak.", 409)
        elif source == "reserve":
            if not q("UPDATE farms SET reserved=reserved-?, eggs=eggs-? WHERE id=? AND reserved>=?", eggs, eggs, fid, eggs).rowcount:
                return err(f"Zarezerwowanych jest tylko {q('SELECT reserved FROM farms WHERE id=?', fid).fetchone()['reserved']} szt.", 409)
        elif not q(f"UPDATE farms SET eggs=eggs-? WHERE id=? AND {farmbook.free_sql()}>=?", eggs, fid, eggs).rowcount:
            return err(f"Wolnych jaj jest tylko {farmbook.pools(q, fid)['free']} szt. (reszta ogłoszona w sklepie lub zarezerwowana)", 409)
        at = now()
        sid = q("INSERT INTO sales(farm_id,client_id,order_id,subscription_id,at,eggs,packs,price10,discount,total,method,paid,notes,source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fid, c["id"] if c else None, o["id"] if o else None, sub["id"] if sub else None,
                at, eggs, eggs // 10, price10, discount, total, method, round(paid, 2), notes.strip(), source).lastrowid
        q("INSERT INTO eggs(farm_id,kind,eggs,packs,at,sale_id) VALUES(?,?,?,?,?,?)", fid, "sale", eggs, eggs // 10, at, sid)
        if sub:  # następna dostawa liczona od dziś
            q("UPDATE subscriptions SET next_date=? WHERE id=?", (datetime.now().date() + timedelta(days=sub["every_days"])).isoformat(), sub["id"])
        if c:
            q("INSERT INTO ledger(farm_id,client_id,at,kind,amount,sale_id,note) VALUES(?,?,?,?,?,?,?)", fid, c["id"], at, "sale",
              total, sid, f"{eggs} szt. × {price10 / 10:.2f} zł" + (f", rabat {discount:.2f} zł" if discount else "")
              + (f", zamówienie nr {o['id']}" if o else ", stały klient" if sub else ""))
            if paid:
                q("INSERT INTO ledger(farm_id,client_id,at,kind,amount,method,sale_id,note) VALUES(?,?,?,?,?,?,?,?)", fid, c["id"], at,
                  "payment", round(-paid, 2), method, sid, "Wpłata przy sprzedaży")
        commit()
        p = farmbook.pools(q, fid)
        return jsonify(id=sid, eggs=eggs, total=total, paid=round(paid, 2), stock=p["offer_packs"], pools=p,
                       balance=balance(c["id"]) if c else None), 201

    @app.delete("/api/my/sales/<int:sid>")
    @need("farmer")
    def sale_delete(sid):
        fid = g.user["farm_id"]
        s = q("SELECT * FROM sales WHERE id=? AND farm_id=?", sid, fid).fetchone()
        if not s:
            return err("Nie znaleziono", 404)
        if s["order_id"]:
            q("UPDATE orders SET status='confirmed' WHERE id=?", s["order_id"])
        q("UPDATE farms SET eggs=eggs+?, stock=stock+?, reserved=reserved+? WHERE id=?", s["eggs"],
          s["eggs"] // 10 if s["source"] == "offer" else 0, s["eggs"] if s["source"] == "reserve" else 0, fid)
        q("DELETE FROM eggs WHERE sale_id=?", sid)
        q("DELETE FROM ledger WHERE sale_id=?", sid)
        q("DELETE FROM sales WHERE id=?", sid)
        commit()
        return jsonify(ok=True, balance=balance(s["client_id"]) if s["client_id"] else None)

    @app.get("/api/my/finance")
    @need("farmer")
    def finance():
        fid = g.user["farm_id"]
        days = request.args.get("days", "30")
        if not days.isdigit() or not 1 <= int(days) <= 366:
            return err("Parametr days od 1 do 366")
        since = (datetime.now() - timedelta(days=int(days))).isoformat()
        got = {m: 0.0 for m in PAID_NOW}
        for r in q("SELECT kind, method, amount FROM ledger WHERE farm_id=? AND at>=? AND kind IN ('payment','refund')", fid, since):
            got[r["method"]] = got.get(r["method"], 0) - r["amount"]
        for r in q("SELECT method, paid FROM sales WHERE farm_id=? AND at>=? AND client_id IS NULL", fid, since):
            got[r["method"]] = got.get(r["method"], 0) + r["paid"]
        bals = [r[0] for r in q("SELECT SUM(amount) FROM ledger WHERE farm_id=? GROUP BY client_id", fid)]
        sv = q("SELECT COALESCE(SUM(total),0), COALESCE(SUM(eggs),0), COUNT(*) FROM sales WHERE farm_id=? AND at>=?", fid, since).fetchone()
        exp = q("SELECT COALESCE(SUM(total),0) FROM expenses WHERE farm_id=? AND date>=?", fid, since[:10]).fetchone()[0]
        return jsonify(days=int(days), received={k: round(v, 2) for k, v in got.items()}, received_total=round(sum(got.values()), 2),
                       sales_value=round(sv[0], 2), sales_eggs=sv[1], sales_count=sv[2], expenses=round(exp, 2),
                       profit=round(sv[0] - exp, 2),
                       debts=round(sum(b for b in bals if b > 0.005), 2), debtors=sum(1 for b in bals if b > 0.005),
                       overpaid=round(-sum(b for b in bals if b < -0.005), 2))
