"""Pasza jak w e-kurniku: magazyn zboża i dodatków, przyjęcie zakupu (z wydatkiem), receptury i mieszalnia.

Składnik ma stan (kg), minimalny zapas, cenę za kg i opcjonalnie wartości odżywcze (białko %, energia kcal/kg,
wapń g/kg). Receptura to udziały procentowe składników (razem 100%). Mieszanie odejmuje składniki z magazynu."""
from datetime import date, datetime

from flask import g, jsonify, request

CATEGORIES = ("grain", "protein", "mineral", "premix", "additive", "other")  # zboże, białkowe, mineralne, premiks, dodatek, inne
SEASONS = ("all", "summer", "winter", "spring", "autumn")


def now():
    return datetime.now().isoformat(timespec="seconds")


def num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def nutrition(parts):
    """Wartości mieszanki z udziałów: [(procent, składnik)]. Składnik bez danych liczy się jako 0 (np. kreda nie ma białka);
    *_share mówi, jaka część mieszanki ma wpisane dane."""
    out = {}
    for k in ("protein", "energy", "calcium", "price"):
        known = [(p, it[k]) for p, it in parts if it[k] is not None and (k != "price" or it[k] > 0)]
        share = sum(p for p, _ in known)
        out[k] = round(sum(p * v for p, v in known) / 100, 2) if share else None
        out[k + "_share"] = round(share, 1)
    return out


def register(app, need, q, commit, body, err):
    def item_row(iid):
        return q("SELECT * FROM feed_items WHERE id=? AND farm_id=?", iid, g.user["farm_id"]).fetchone()

    def item_json(r):
        return dict(r, low=r["stock"] <= r["min_stock"] and r["min_stock"] > 0)

    def recipe_json(r):
        parts = q("SELECT ri.percent, fi.* FROM recipe_items ri JOIN feed_items fi ON fi.id=ri.item_id WHERE ri.recipe_id=? ORDER BY ri.percent DESC", r["id"]).fetchall()
        return dict(r, active=bool(r["active"]), total_percent=round(sum(p["percent"] for p in parts), 2),
                    items=[dict(item_id=p["id"], name=p["name"], percent=p["percent"], stock=p["stock"]) for p in parts],
                    nutrition=nutrition([(p["percent"], p) for p in parts]))

    ITEM = dict(name="", category="grain", unit="kg", min_stock=0, price=0, protein=None, energy=None, calcium=None, notes="")

    def item_check(b, old):
        it = {**ITEM, **({k: old[k] for k in ITEM} if old else {}), **{k: b[k] for k in ITEM if k in b}}
        if not isinstance(it["name"], str) or not it["name"].strip() or len(it["name"]) > 80:
            return None, "Nazwa składnika do 80 znaków"
        if it["category"] not in CATEGORIES:
            return None, "Rodzaj: grain, protein, mineral, premix, additive albo other"
        if not isinstance(it["unit"], str) or not it["unit"].strip() or len(it["unit"]) > 10:
            return None, "Jednostka do 10 znaków"
        if not num(it["min_stock"], 0, 1e7) or not num(it["price"], 0, 1e5):
            return None, "Minimalny zapas i cena nie mogą być ujemne"
        for k, hi in (("protein", 100), ("energy", 10000), ("calcium", 1000)):
            if it[k] is not None and not num(it[k], 0, hi):
                return None, f"Pole {k} poza zakresem"
        if not isinstance(it["notes"], str) or len(it["notes"]) > 500:
            return None, "Uwagi do 500 znaków"
        return it, None

    @app.route("/api/my/feed", methods=["GET"])
    @need("farmer")
    def feed():
        fid = g.user["farm_id"]
        items = [item_json(r) for r in q("SELECT * FROM feed_items WHERE farm_id=? ORDER BY category, name", fid)]
        recipes = [recipe_json(r) for r in q("SELECT * FROM recipes WHERE farm_id=? ORDER BY active DESC, name", fid)]
        moves = [dict(r) for r in q("SELECT m.*, fi.name FROM feed_moves m JOIN feed_items fi ON fi.id=m.item_id WHERE m.farm_id=? "
                                    "ORDER BY m.at DESC, m.id DESC LIMIT 50", fid)]
        mixes = [dict(r) for r in q("SELECT x.*, r.name AS recipe FROM mixes x LEFT JOIN recipes r ON r.id=x.recipe_id WHERE x.farm_id=? "
                                    "ORDER BY x.at DESC LIMIT 30", fid)]
        return jsonify(items=items, recipes=recipes, moves=moves, mixes=mixes,
                       value=round(sum(i["stock"] * i["price"] for i in items), 2), low=sum(1 for i in items if i["low"]))

    @app.post("/api/my/feed/items")
    @need("farmer")
    def feed_item_add():
        b = body()
        it, msg = item_check(b, None)
        if msg:
            return err(msg)
        stock = b.get("stock", 0)
        if not num(stock, 0, 1e7):
            return err("Stan początkowy nie może być ujemny")
        iid = q("INSERT INTO feed_items(farm_id,name,category,unit,stock,min_stock,price,protein,energy,calcium,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                g.user["farm_id"], it["name"].strip(), it["category"], it["unit"].strip(), stock, it["min_stock"], it["price"],
                it["protein"], it["energy"], it["calcium"], it["notes"].strip()).lastrowid
        if stock:
            q("INSERT INTO feed_moves(farm_id,item_id,at,kind,qty,note) VALUES(?,?,?,?,?,?)", g.user["farm_id"], iid, now(), "adjust", stock, "Stan początkowy")
        commit()
        return jsonify(item_json(item_row(iid))), 201

    @app.route("/api/my/feed/items/<int:iid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def feed_item(iid):
        old = item_row(iid)
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            if q("SELECT 1 FROM recipe_items WHERE item_id=?", iid).fetchone():
                return err("Składnik jest w recepturze. Najpierw usuń go z receptur.", 409)
            q("DELETE FROM feed_moves WHERE item_id=?", iid)
            q("DELETE FROM feed_items WHERE id=?", iid)
            commit()
            return jsonify(ok=True)
        it, msg = item_check(body(), old)
        if msg:
            return err(msg)
        q("UPDATE feed_items SET name=?,category=?,unit=?,min_stock=?,price=?,protein=?,energy=?,calcium=?,notes=? WHERE id=?",
          it["name"].strip(), it["category"], it["unit"].strip(), it["min_stock"], it["price"], it["protein"], it["energy"], it["calcium"],
          it["notes"].strip(), iid)
        commit()
        return jsonify(item_json(item_row(iid)))

    @app.post("/api/my/feed/items/<int:iid>/purchase")
    @need("farmer")
    def feed_purchase(iid):
        """Przyjęcie zakupu: stan rośnie, cena składnika się aktualizuje, wydatek zapisuje się sam (chyba że expense=false)."""
        it, b = item_row(iid), body()
        if not it:
            return err("Nie znaleziono", 404)
        qty, price = b.get("qty"), b.get("price")
        if not num(qty, 0.001, 1e7):
            return err("Ilość większa od zera")
        if not num(price, 0, 1e5):
            return err("Cena za jednostkę nie może być ujemna")
        day = b.get("date", date.today().isoformat())
        try:
            date.fromisoformat(day)
        except (TypeError, ValueError):
            return err("Data w formacie RRRR-MM-DD")
        supplier = b.get("supplier", "")
        if not isinstance(supplier, str) or len(supplier) > 120:
            return err("Dostawca do 120 znaków")
        eid = None
        if b.get("expense", True) is not False:
            eid = q("INSERT INTO expenses(farm_id,date,category,name,qty,unit,unit_price,total,supplier) VALUES(?,?,?,?,?,?,?,?,?)",
                    g.user["farm_id"], day, "Pasza i zboże", it["name"], qty, it["unit"], price, round(qty * price, 2), supplier.strip()).lastrowid
        q("UPDATE feed_items SET stock=stock+?, price=CASE WHEN ?>0 THEN ? ELSE price END WHERE id=?", qty, price, price, iid)
        q("INSERT INTO feed_moves(farm_id,item_id,at,kind,qty,price,expense_id,note) VALUES(?,?,?,?,?,?,?,?)", g.user["farm_id"], iid,
          day + now()[10:], "purchase", qty, price, eid, supplier.strip())
        commit()
        return jsonify(item=item_json(item_row(iid)), expense_id=eid), 201

    @app.post("/api/my/feed/items/<int:iid>/adjust")
    @need("farmer")
    def feed_adjust(iid):
        """Spis z natury albo zużycie poza mieszalnią: nowy stan magazynu."""
        it, b = item_row(iid), body()
        if not it:
            return err("Nie znaleziono", 404)
        if not num(b.get("stock"), 0, 1e7):
            return err("Stan nie może być ujemny")
        note = b.get("note", "")
        if not isinstance(note, str) or len(note) > 200:
            return err("Uwagi do 200 znaków")
        diff = round(b["stock"] - it["stock"], 3)
        q("UPDATE feed_items SET stock=? WHERE id=?", b["stock"], iid)
        q("INSERT INTO feed_moves(farm_id,item_id,at,kind,qty,note) VALUES(?,?,?,?,?,?)", g.user["farm_id"], iid, now(), "adjust", diff,
          note.strip() or "Spis z natury")
        commit()
        return jsonify(item_json(item_row(iid)))

    def recipe_check(b, old):
        r = {"name": old["name"] if old else "", "season": old["season"] if old else "all", "notes": old["notes"] if old else "",
             **{k: b[k] for k in ("name", "season", "notes") if k in b}}
        if not isinstance(r["name"], str) or not r["name"].strip() or len(r["name"]) > 80:
            return None, "Nazwa receptury do 80 znaków"
        if r["season"] not in SEASONS:
            return None, "Sezon: all, summer, winter, spring albo autumn"
        if not isinstance(r["notes"], str) or len(r["notes"]) > 500:
            return None, "Uwagi do 500 znaków"
        if "items" in b or not old:
            items = b.get("items")
            if not isinstance(items, list) or not items:
                return None, "Dodaj składniki receptury"
            seen = set()
            for p in items:
                if not isinstance(p, dict) or not item_row(p.get("item_id")) or not num(p.get("percent"), 0.01, 100) or p["item_id"] in seen:
                    return None, "Każdy składnik z magazynu raz, z udziałem od 0,01 do 100%"
                seen.add(p["item_id"])
            total = sum(p["percent"] for p in items)
            if abs(total - 100) > 0.5:
                return None, f"Udziały muszą dać razem 100% (teraz {total:.1f}%)"
            r["items"] = items
        return r, None

    @app.route("/api/my/feed/recipes", methods=["POST"])
    @need("farmer")
    def recipe_add():
        r, msg = recipe_check(body(), None)
        if msg:
            return err(msg)
        rid = q("INSERT INTO recipes(farm_id,name,season,notes) VALUES(?,?,?,?)", g.user["farm_id"], r["name"].strip(), r["season"], r["notes"].strip()).lastrowid
        for p in r["items"]:
            q("INSERT INTO recipe_items(recipe_id,item_id,percent) VALUES(?,?,?)", rid, p["item_id"], p["percent"])
        commit()
        return jsonify(recipe_json(q("SELECT * FROM recipes WHERE id=?", rid).fetchone())), 201

    @app.route("/api/my/feed/recipes/<int:rid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def recipe(rid):
        old = q("SELECT * FROM recipes WHERE id=? AND farm_id=?", rid, g.user["farm_id"]).fetchone()
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            q("DELETE FROM recipe_items WHERE recipe_id=?", rid)
            q("DELETE FROM recipes WHERE id=?", rid)
            commit()
            return jsonify(ok=True)
        b = body()
        r, msg = recipe_check(b, old)
        if msg:
            return err(msg)
        q("UPDATE recipes SET name=?,season=?,notes=? WHERE id=?", r["name"].strip(), r["season"], r["notes"].strip(), rid)
        if "items" in r:
            q("DELETE FROM recipe_items WHERE recipe_id=?", rid)
            for p in r["items"]:
                q("INSERT INTO recipe_items(recipe_id,item_id,percent) VALUES(?,?,?)", rid, p["item_id"], p["percent"])
        if b.get("active") is True:  # jedna receptura w użyciu
            q("UPDATE recipes SET active=(id=?) WHERE farm_id=?", rid, g.user["farm_id"])
        commit()
        return jsonify(recipe_json(q("SELECT * FROM recipes WHERE id=?", rid).fetchone()))

    @app.post("/api/my/feed/mix")
    @need("farmer")
    def mix():
        """Mieszalnia: z receptury i ilości kg odejmuje składniki z magazynu. Przy braku składników odmawia i podaje braki."""
        fid, b = g.user["farm_id"], body()
        r = q("SELECT * FROM recipes WHERE id=? AND farm_id=?", b.get("recipe_id"), fid).fetchone()
        if not r:
            return err("Wybierz recepturę", 404)
        kg = b.get("kg")
        if not num(kg, 0.1, 100000):
            return err("Ilość mieszanki od 0,1 kg")
        parts = q("SELECT ri.percent, fi.* FROM recipe_items ri JOIN feed_items fi ON fi.id=ri.item_id WHERE ri.recipe_id=?", r["id"]).fetchall()
        need_kg = [(p, round(kg * p["percent"] / 100, 3)) for p in parts]
        short = [f"{p['name']}: potrzeba {n:g} {p['unit']}, jest {p['stock']:g}" for p, n in need_kg if n > p["stock"] + 1e-9]
        if short:
            return err("Za mało w magazynie: " + "; ".join(short), 409)
        notes = b.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 200:
            return err("Uwagi do 200 znaków")
        at = now()
        mid = q("INSERT INTO mixes(farm_id,at,recipe_id,kg,notes) VALUES(?,?,?,?,?)", fid, at, r["id"], kg, notes.strip()).lastrowid
        for p, n in need_kg:
            q("UPDATE feed_items SET stock=stock-? WHERE id=?", n, p["id"])
            q("INSERT INTO feed_moves(farm_id,item_id,at,kind,qty,mix_id,note) VALUES(?,?,?,?,?,?,?)", fid, p["id"], at, "mix", -n, mid, r["name"])
        commit()
        cost = round(sum(n * p["price"] for p, n in need_kg), 2)
        return jsonify(id=mid, kg=kg, cost=cost, used=[dict(name=p["name"], kg=n) for p, n in need_kg]), 201
