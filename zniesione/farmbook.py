"""Gospodarka jak w e-kurniku: magazyn jaj w sztukach, ogłoszenie i rezerwacja, zamówienia cykliczne stałych klientów,
wydatki i wyposażenie.

Magazyn farmy (farms.eggs) to dobre jaja w sztukach. Z niego rolnik przydziela:
- ogłoszone w sklepie: farms.stock (opakowania po 10 szt.), z nich klienci składają zamówienia,
- zarezerwowane dla stałych klientów: farms.reserved (szt.),
- potwierdzone zamówienia czekające na wydanie (orders.status = 'confirmed').
Wolne = magazyn - ogłoszone*10 - zarezerwowane - potwierdzone*10. Brudne i uszkodzone jaja nie trafiają do magazynu."""
import re
from datetime import date, datetime, timedelta

from flask import g, jsonify, request

PACK = 10
EXPENSE_CATEGORIES = ("Pasza i zboże", "Weterynarz", "Witaminy i suplementy", "Ściółka", "Prąd", "Woda", "Opakowania",
                      "Wyposażenie", "Zakup kur", "Inne")
EQUIPMENT_STATES = ("ok", "repair", "broken", "retired")  # sprawne, do naprawy, zepsute, wycofane


def now():
    return datetime.now().isoformat(timespec="seconds")


def committed_sql():
    return f"(SELECT COALESCE(SUM(qty),0)*{PACK} FROM orders o WHERE o.farm_id=farms.id AND o.status='confirmed')"


def pools(q, fid):
    f = q(f"SELECT eggs, stock, reserved, unsorted, {committed_sql()} AS committed FROM farms WHERE id=?", fid).fetchone()
    free = f["eggs"] - f["stock"] * PACK - f["reserved"] - f["committed"]
    return dict(unsorted=f["unsorted"], eggs=f["eggs"], offer_packs=f["stock"], reserved=f["reserved"], committed=f["committed"],
                free=max(0, free))


def free_sql():
    return f"eggs-stock*{PACK}-reserved-{committed_sql()}"


def valid_date(s):
    try:
        return isinstance(s, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)) and datetime.strptime(s, "%Y-%m-%d") is not None
    except ValueError:
        return False


def num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def text(b, k, n, required=False):
    v = b.get(k, "")
    if not isinstance(v, str) or len(v) > n or (required and not v.strip()):
        return None
    return v.strip()


def subscription_from_order(db, order):
    """Zamówienie co tydzień / co 2 tygodnie ze sklepu staje się zamówieniem cyklicznym klienta po potwierdzeniu."""
    every = {"weekly": 7, "biweekly": 14}.get(order["mode"])
    if not every or not order["client_id"]:
        return None
    if db.execute("SELECT 1 FROM subscriptions WHERE client_id=? AND active=1", (order["client_id"],)).fetchone():
        return None
    return db.execute("INSERT INTO subscriptions(farm_id,client_id,eggs,every_days,next_date,method,notes,created) VALUES(?,?,?,?,?,?,?,?)",
                      (order["farm_id"], order["client_id"], order["qty"] * PACK, every, (date.today() + timedelta(days=every)).isoformat(),
                       "later", "Z zamówienia w sklepie", now())).lastrowid


def register(app, need, q, commit, body, err, integer):
    def days_arg(default="30", hi=366):
        d = request.args.get("days", default)
        return int(d) if d.isdigit() and 1 <= int(d) <= hi else None

    # ---------- jaja: zbiór, sortowanie, rozdane, straty, inwentaryzacja, ogłoszenie i rezerwacja ----------
    @app.route("/api/my/eggs", methods=["GET", "POST"])
    @need("farmer")
    def eggs():
        fid = g.user["farm_id"]
        if request.method == "GET":
            days = days_arg("30", 365)
            if not days:
                return err("Parametr days od 1 do 365")
            rows = q("SELECT id,kind,eggs,damaged,dirty,who,note,at,sale_id FROM eggs WHERE farm_id=? AND at>=? ORDER BY at DESC, id DESC", fid,
                     (datetime.now() - timedelta(days=days)).isoformat()).fetchall()
            by = lambda k, col="eggs": sum(r[col] for r in rows if r["kind"] == k)
            soon = (date.today() + timedelta(days=7)).isoformat()
            need7 = q("SELECT COALESCE(SUM(eggs),0) FROM subscriptions WHERE farm_id=? AND active=1 AND next_date<=?", fid, soon).fetchone()[0]
            gifts = {}
            for r in rows:
                if r["kind"] == "gift":
                    gifts[r["who"]] = gifts.get(r["who"], 0) + r["eggs"]
            today_n = q("SELECT COALESCE(SUM(eggs),0) FROM eggs WHERE farm_id=? AND kind='collect' AND at>=?", fid, date.today().isoformat()).fetchone()[0]
            hour = q("SELECT remind_on, remind_hour FROM farms WHERE id=?", fid).fetchone()
            return jsonify(days=days, collected=by("collect"), good=by("sort"), dirty=by("sort", "dirty"), damaged=by("sort", "damaged"),
                           sold=by("sale"), lost=by("loss"), given=by("gift"), given_to=gifts, entries=[dict(r) for r in rows[:200]],
                           stock=pools(q, fid), reserve_needed_7d=need7, collected_today=today_n,
                           reminder_due=bool(hour["remind_on"]) and datetime.now().hour >= hour["remind_hour"] and not today_n,
                           recipients=[r[0] for r in q("SELECT who FROM eggs WHERE farm_id=? AND kind='gift' AND who!='' GROUP BY who "
                                                       "ORDER BY MAX(id) DESC LIMIT 20", fid)])
        b = body()
        kind, n = b.get("kind"), b.get("eggs")
        note = text(b, "note", 200)
        if note is None:
            return err("Opis do 200 znaków")
        if kind == "collect":  # zebrane trafiają do sortowania; sorted=true: od razu posortowane (dobre do magazynu)
            if not integer(n, 1, 100000):
                return err("Liczba zebranych jaj od 1 do 100 000")
            at = now()
            q("INSERT INTO eggs(farm_id,kind,eggs,note,at) VALUES(?,?,?,?,?)", fid, "collect", n, note, at)
            if b.get("sorted") is True:
                dmg, dirty = b.get("damaged", 0), b.get("dirty", 0)
                if not integer(dmg, 0, n) or not integer(dirty, 0, n - dmg):
                    return err("Brudnych i uszkodzonych nie może być więcej niż zebranych")
                q("UPDATE farms SET eggs=eggs+? WHERE id=?", n - dmg - dirty, fid)
                q("INSERT INTO eggs(farm_id,kind,eggs,damaged,dirty,packs,at) VALUES(?,?,?,?,?,?,?)", fid, "sort", n - dmg - dirty, dmg, dirty,
                  (n - dmg - dirty) // PACK, at)
            else:
                q("UPDATE farms SET unsorted=unsorted+? WHERE id=?", n, fid)
        elif kind == "sort":  # sortowanie: dobre do magazynu, brudne i uszkodzone nie idą do sprzedaży
            good, dirty, dmg = b.get("good", 0), b.get("dirty", 0), b.get("damaged", 0)
            if not all(integer(x, 0, 100000) for x in (good, dirty, dmg)) or good + dirty + dmg < 1:
                return err("Podaj liczbę dobrych, brudnych i uszkodzonych jaj (razem co najmniej 1)")
            total = good + dirty + dmg
            if not q("UPDATE farms SET unsorted=unsorted-?, eggs=eggs+? WHERE id=? AND unsorted>=?", total, good, fid, total).rowcount:
                return err(f"Do sortowania jest tylko {pools(q, fid)['unsorted']} szt.", 409)
            q("INSERT INTO eggs(farm_id,kind,eggs,damaged,dirty,packs,note,at) VALUES(?,?,?,?,?,?,?,?)", fid, "sort", good, dmg, dirty, good // PACK, note, now())
        elif kind in ("loss", "gift"):  # strata (np. stłuczone) albo rozdane (np. mamie): z wolnych jaj
            who = text(b, "who", 60, required=kind == "gift")
            if who is None:
                return err("Wpisz, komu rozdano jaja (np. mama)")
            if not integer(n, 1, 100000):
                return err("Liczba jaj od 1 do 100 000")
            if not q(f"UPDATE farms SET eggs=eggs-? WHERE id=? AND {free_sql()}>=?", n, fid, n).rowcount:
                return err(f"Wolnych jaj jest tylko {pools(q, fid)['free']} szt. (reszta ogłoszona lub zarezerwowana)", 409)
            q("INSERT INTO eggs(farm_id,kind,eggs,who,note,at) VALUES(?,?,?,?,?,?)", fid, kind, n, who, note or ("Strata" if kind == "loss" else ""), now())
        elif kind == "inventory":  # „policzyłem jaja”: magazyn = policzona liczba
            if not integer(n, 0, 100000):
                return err("Policzona liczba jaj od 0 do 100 000")
            p = pools(q, fid)
            held = p["offer_packs"] * PACK + p["reserved"] + p["committed"]
            if n < held:
                return err(f"Policzono mniej, niż jest ogłoszone, zarezerwowane i do wydania ({held} szt.). Najpierw zmniejsz ogłoszenie lub rezerwację.", 409)
            q("UPDATE farms SET eggs=? WHERE id=?", n, fid)
            q("INSERT INTO eggs(farm_id,kind,eggs,note,at) VALUES(?,?,?,?,?)", fid, "inventory", n - p["eggs"], note or "Inwentaryzacja", now())
        else:
            return err("Rodzaj wpisu: collect (zbiór), sort (sortowanie), gift (rozdane), loss (strata) albo inventory (inwentaryzacja)")
        commit()
        return jsonify(stock=pools(q, fid)), 201

    @app.post("/api/my/eggs/allocation")
    @need("farmer")
    def allocation():
        """Ile opakowań ogłaszam w sklepie i ile sztuk rezerwuję dla stałych klientów (wartości docelowe)."""
        fid, b = g.user["farm_id"], body()
        offer, res = b.get("offer_packs"), b.get("reserved")
        if not integer(offer, 0, 10000) or not integer(res, 0, 100000):
            return err("Ogłoszenie od 0 opakowań, rezerwacja od 0 sztuk")
        p = pools(q, fid)
        if offer * PACK + res + p["committed"] > p["eggs"]:
            return err(f"W magazynie jest {p['eggs']} szt., z czego {p['committed']} szt. czeka na wydanie zamówień. "
                       f"Możesz ogłosić i zarezerwować razem najwyżej {p['eggs'] - p['committed']} szt.", 409)
        q("UPDATE farms SET stock=?, reserved=? WHERE id=?", offer, res, fid)
        commit()
        return jsonify(stock=pools(q, fid))

    # ---------- zamówienia cykliczne stałych klientów ----------
    def sub_check(b, old):
        s = {**(dict(old) if old else dict(client_id=None, eggs=None, every_days=7, next_date=date.today().isoformat(),
                                            method="later", active=1, notes="")),
             **{k: b[k] for k in ("client_id", "eggs", "every_days", "next_date", "method", "active", "notes") if k in b}}
        if not integer(s["client_id"], 1, 10 ** 9) or not q("SELECT 1 FROM clients WHERE id=? AND farm_id=?", s["client_id"], g.user["farm_id"]).fetchone():
            return None, "Wybierz klienta z kartoteki"
        if not integer(s["eggs"], 1, 5000):
            return None, "Liczba jaj od 1 do 5000"
        if not integer(s["every_days"], 1, 90):
            return None, "Co ile dni: od 1 do 90"
        if not valid_date(s["next_date"]):
            return None, "Najbliższa dostawa w formacie RRRR-MM-DD"
        if s["method"] not in ("cash", "transfer", "blik", "later", "balance"):
            return None, "Niepoprawny sposób płatności"
        if not isinstance(s["active"], (bool, int)):
            return None, "Pole active musi być true lub false"
        if not isinstance(s["notes"], str) or len(s["notes"]) > 200:
            return None, "Uwagi do 200 znaków"
        return s, None

    def sub_json(r):
        return dict(r, active=bool(r["active"]), due=bool(r["active"]) and r["next_date"] <= date.today().isoformat())

    SUB_SQL = ("SELECT s.*, c.name AS client_name, c.price10 AS client_price10 FROM subscriptions s JOIN clients c ON c.id=s.client_id "
               "WHERE s.farm_id=?")

    @app.route("/api/my/subscriptions", methods=["GET", "POST"])
    @need("farmer")
    def subscriptions():
        fid = g.user["farm_id"]
        if request.method == "POST":
            s, msg = sub_check(body(), None)
            if msg:
                return err(msg)
            sid = q("INSERT INTO subscriptions(farm_id,client_id,eggs,every_days,next_date,method,active,notes,created) VALUES(?,?,?,?,?,?,?,?,?)",
                    fid, s["client_id"], s["eggs"], s["every_days"], s["next_date"], s["method"], int(bool(s["active"])), s["notes"].strip(), now()).lastrowid
            commit()
            return jsonify(sub_json(q(SUB_SQL + " AND s.id=?", fid, sid).fetchone())), 201
        cid = request.args.get("client_id", "")
        rows = q(SUB_SQL + (" AND s.client_id=?" if cid.isdigit() else "") + " ORDER BY s.active DESC, s.next_date, c.name",
                 fid, *([int(cid)] if cid.isdigit() else []))
        return jsonify([sub_json(r) for r in rows])

    @app.route("/api/my/subscriptions/<int:sid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def subscription(sid):
        fid = g.user["farm_id"]
        old = q("SELECT * FROM subscriptions WHERE id=? AND farm_id=?", sid, fid).fetchone()
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            q("DELETE FROM subscriptions WHERE id=?", sid)
            commit()
            return jsonify(ok=True)
        s, msg = sub_check(body(), old)
        if msg:
            return err(msg)
        q("UPDATE subscriptions SET client_id=?,eggs=?,every_days=?,next_date=?,method=?,active=?,notes=? WHERE id=?",
          s["client_id"], s["eggs"], s["every_days"], s["next_date"], s["method"], int(bool(s["active"])), s["notes"].strip(), sid)
        commit()
        return jsonify(sub_json(q(SUB_SQL + " AND s.id=?", fid, sid).fetchone()))

    @app.post("/api/my/subscriptions/<int:sid>/skip")
    @need("farmer")
    def subscription_skip(sid):
        fid = g.user["farm_id"]
        s = q("SELECT * FROM subscriptions WHERE id=? AND farm_id=?", sid, fid).fetchone()
        if not s:
            return err("Nie znaleziono", 404)
        nxt = (max(date.fromisoformat(s["next_date"]), date.today()) + timedelta(days=s["every_days"])).isoformat()
        q("UPDATE subscriptions SET next_date=? WHERE id=?", nxt, sid)
        commit()
        return jsonify(sub_json(q(SUB_SQL + " AND s.id=?", fid, sid).fetchone()))

    # ---------- wydatki ----------
    def expense_check(b, old):
        e = {**(dict(old) if old else dict(date=date.today().isoformat(), category="Inne", name="", qty=1, unit="szt",
                                            unit_price=None, total=None, supplier="", notes="")),
             **{k: b[k] for k in ("date", "category", "name", "qty", "unit", "unit_price", "total", "supplier", "notes") if k in b}}
        if not valid_date(e["date"]):
            return None, "Data w formacie RRRR-MM-DD"
        for k, n, req in (("category", 60, True), ("name", 120, True), ("unit", 10, True), ("supplier", 120, False), ("notes", 500, False)):
            if not isinstance(e[k], str) or len(e[k]) > n or (req and not e[k].strip()):
                return None, f"Pole {k}: {'wymagane, ' if req else ''}do {n} znaków"
            e[k] = e[k].strip()
        if not num(e["qty"], 0, 1000000):
            return None, "Ilość od 0 do 1 000 000"
        if e["unit_price"] is not None and not num(e["unit_price"], 0, 1000000):
            return None, "Cena jednostkowa od 0"
        if e["total"] is None:  # wartość z ilości i ceny, jak w e-kurniku
            if e["unit_price"] is None:
                return None, "Podaj wartość albo cenę jednostkową"
            e["total"] = round(e["qty"] * e["unit_price"], 2)
        if not num(e["total"], 0, 10000000):
            return None, "Wartość od 0 do 10 000 000 zł"
        e["unit_price"] = e["unit_price"] if e["unit_price"] is not None else (round(e["total"] / e["qty"], 2) if e["qty"] else 0)
        return e, None

    COLS_E = ("date", "category", "name", "qty", "unit", "unit_price", "total", "supplier", "notes")

    @app.route("/api/my/expenses", methods=["GET", "POST"])
    @need("farmer")
    def expenses():
        fid = g.user["farm_id"]
        if request.method == "POST":
            e, msg = expense_check(body(), None)
            if msg:
                return err(msg)
            eid = q(f"INSERT INTO expenses(farm_id,{','.join(COLS_E)}) VALUES(?,{','.join('?' * len(COLS_E))})", fid, *[e[k] for k in COLS_E]).lastrowid
            commit()
            return jsonify(dict(q("SELECT * FROM expenses WHERE id=?", eid).fetchone())), 201
        days = days_arg("30", 3660)
        if not days:
            return err("Parametr days od 1 do 3660")
        rows = [dict(r) for r in q("SELECT * FROM expenses WHERE farm_id=? AND date>=? ORDER BY date DESC, id DESC", fid,
                                   (date.today() - timedelta(days=days - 1)).isoformat())]
        cats = {}
        for r in rows:
            cats[r["category"]] = round(cats.get(r["category"], 0) + r["total"], 2)
        return jsonify(days=days, total=round(sum(r["total"] for r in rows), 2), by_category=cats, entries=rows,
                       categories=sorted(set(EXPENSE_CATEGORIES) | {r[0] for r in q("SELECT DISTINCT category FROM expenses WHERE farm_id=?", fid)}))

    @app.route("/api/my/expenses/<int:eid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def expense(eid):
        old = q("SELECT * FROM expenses WHERE id=? AND farm_id=?", eid, g.user["farm_id"]).fetchone()
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            q("DELETE FROM expenses WHERE id=?", eid)
            commit()
            return jsonify(ok=True)
        b = body()
        if ("qty" in b or "unit_price" in b) and "total" not in b:
            b["total"] = None  # przelicz wartość z nowej ilości lub ceny
        e, msg = expense_check(b, old)
        if msg:
            return err(msg)
        q(f"UPDATE expenses SET {','.join(k + '=?' for k in COLS_E)} WHERE id=?", *[e[k] for k in COLS_E], eid)
        commit()
        return jsonify(dict(q("SELECT * FROM expenses WHERE id=?", eid).fetchone()))

    # ---------- wyposażenie ----------
    COLS_Q = ("name", "category", "bought", "price", "state", "next_check", "notes")

    def equip_check(b, old):
        e = {**(dict(old) if old else dict(name="", category="", bought="", price=0, state="ok", next_check="", notes="")),
             **{k: b[k] for k in COLS_Q if k in b}}
        for k, n, req in (("name", 120, True), ("category", 60, False), ("notes", 500, False)):
            if not isinstance(e[k], str) or len(e[k]) > n or (req and not e[k].strip()):
                return None, f"Pole {k}: {'wymagane, ' if req else ''}do {n} znaków"
            e[k] = e[k].strip()
        for k in ("bought", "next_check"):
            if not isinstance(e[k], str) or (e[k] and not valid_date(e[k])):
                return None, "Daty w formacie RRRR-MM-DD"
        if not num(e["price"], 0, 10000000):
            return None, "Cena od 0"
        if e["state"] not in EQUIPMENT_STATES:
            return None, "Stan: ok, repair (do naprawy), broken (zepsute) albo retired (wycofane)"
        return e, None

    def equip_json(r):
        soon = (date.today() + timedelta(days=14)).isoformat()
        return dict(r, check_due=bool(r["next_check"]) and r["next_check"] <= soon and r["state"] != "retired")

    @app.route("/api/my/equipment", methods=["GET", "POST"])
    @need("farmer")
    def equipment():
        fid = g.user["farm_id"]
        if request.method == "POST":
            e, msg = equip_check(body(), None)
            if msg:
                return err(msg)
            eid = q(f"INSERT INTO equipment(farm_id,{','.join(COLS_Q)}) VALUES(?,{','.join('?' * len(COLS_Q))})", fid, *[e[k] for k in COLS_Q]).lastrowid
            commit()
            return jsonify(equip_json(q("SELECT * FROM equipment WHERE id=?", eid).fetchone())), 201
        return jsonify([equip_json(r) for r in q("SELECT * FROM equipment WHERE farm_id=? ORDER BY state='retired', name", fid)])

    @app.route("/api/my/equipment/<int:eid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def equipment_one(eid):
        old = q("SELECT * FROM equipment WHERE id=? AND farm_id=?", eid, g.user["farm_id"]).fetchone()
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            q("DELETE FROM equipment WHERE id=?", eid)
            commit()
            return jsonify(ok=True)
        e, msg = equip_check(body(), old)
        if msg:
            return err(msg)
        q(f"UPDATE equipment SET {','.join(k + '=?' for k in COLS_Q)} WHERE id=?", *[e[k] for k in COLS_Q], eid)
        commit()
        return jsonify(equip_json(q("SELECT * FROM equipment WHERE id=?", eid).fetchone()))
