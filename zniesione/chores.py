"""Codzienne obowiązki na ekranie Start (opcjonalne): pasza uzupełniona, woda uzupełniona, jaja zebrane, kury policzone.
Każde odhaczenie zapisuje godzinę i osobę; przy paszy i wodzie można podać ilość (kg, l), przy kurach liczbę.
„Jaja zebrane” wynika z wpisów zbioru w Jajach, więc nie trzeba odhaczać dwa razy."""
from datetime import date, timedelta

from flask import g, jsonify, request

from . import db as dbm
from .farmbook import entry_at, text, valid_date

KINDS = ("feed", "water", "eggs", "hens")
MANUAL = {"feed": (0, 10000), "water": (0, 100000), "hens": (0, 100000)}  # dopuszczalna ilość: kg, l, sztuk


def register(app, need, q, commit, body, err, integer):
    def enabled(fid):
        f = q("SELECT chores, chores_amounts FROM farms WHERE id=?", fid).fetchone()
        return [k for k in f["chores"].split(",") if k in KINDS], bool(f["chores_amounts"])

    @app.route("/api/my/chores/config", methods=["GET", "PUT"])
    @need("farmer")
    def chores_config():
        fid = g.user["farm_id"]
        if request.method == "PUT":
            b = body()
            ks = b.get("kinds", [])
            if not isinstance(ks, list) or any(k not in KINDS for k in ks):
                return err("Obowiązki: feed, water, eggs, hens")
            if "amounts" in b and not isinstance(b["amounts"], bool):
                return err("Pole amounts musi być true lub false")
            q("UPDATE farms SET chores=? WHERE id=?", ",".join(k for k in KINDS if k in ks), fid)
            if "amounts" in b:
                q("UPDATE farms SET chores_amounts=? WHERE id=?", int(b["amounts"]), fid)
            commit()
        ks, amounts = enabled(fid)
        return jsonify(kinds=ks, amounts=amounts)

    @app.route("/api/my/chores", methods=["GET", "POST"])
    @need("farmer")
    def chores():
        fid = g.user["farm_id"]
        if request.method == "POST":
            b = body()
            k = b.get("kind")
            if k not in MANUAL:
                return err("Odhacz: feed (pasza), water (woda) albo hens (kury); zbiór jaj wpisz w Jajach")
            v = b.get("amount", b.get("count"))
            lo, hi = MANUAL[k]
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or (k == "hens" and not integer(v, lo, hi))):
                return err(f"Ilość od {lo} do {hi}" + (" (liczba całkowita)" if k == "hens" else ""))
            note = text(b, "note", 200)
            if note is None:
                return err("Uwagi do 200 znaków")
            at, msg = entry_at(b.get("date"))
            if msg:
                return err(msg)
            cid = q("INSERT INTO chores(farm_id,day,kind,at,amount,note) VALUES(?,?,?,?,?,?)", fid, at[:10], k, at,
                    None if v is None else round(float(v), 2), note).lastrowid
            commit()
            return jsonify(dict(q(f"SELECT c.*, {dbm.by_sql('c')} FROM chores c WHERE id=?", cid).fetchone())), 201
        d = request.args.get("day", date.today().isoformat())
        if not valid_date(d):
            return err("Dzień w formacie RRRR-MM-DD")
        ks, amounts = enabled(fid)
        items = {k: [] for k in KINDS}
        for r in q(f"SELECT c.id, c.kind, c.at, c.amount, c.note, {dbm.by_sql('c')} FROM chores c WHERE farm_id=? AND day=? ORDER BY at", fid, d):
            items[r["kind"]].append(dict(r))
        for r in q(f"SELECT e.id, e.at, e.eggs AS amount, e.note, {dbm.by_sql('e')} FROM eggs e WHERE farm_id=? AND kind='collect' AND substr(at,1,10)=? "
                   "ORDER BY at", fid, d):
            items["eggs"].append(dict(r, kind="eggs", auto=True))
        birds = q("SELECT COALESCE(SUM(birds),0) FROM flocks WHERE farm_id=?", fid).fetchone()[0]
        return jsonify(day=d, kinds=ks, amounts=amounts, birds=birds, items=items)

    @app.delete("/api/my/chores/<int:cid>")
    @need("farmer")
    def chore_delete(cid):
        if not q("DELETE FROM chores WHERE id=? AND farm_id=?", cid, g.user["farm_id"]).rowcount:
            return err("Nie znaleziono", 404)
        commit()
        return jsonify(ok=True)

    @app.get("/api/my/chores/history")
    @need("farmer")
    def chores_history():
        """Dzień po dniu: godziny odhaczeń, nasypana pasza i nalana woda, policzone kury, zbiory."""
        fid, n = g.user["farm_id"], request.args.get("days", "14")
        if not n.isdigit() or not 1 <= int(n) <= 366:
            return err("Parametr days od 1 do 366")
        start = date.today() - timedelta(days=int(n) - 1)
        days = {(start + timedelta(days=i)).isoformat(): {k: dict(times=[], amount=None) for k in KINDS} for i in range(int(n))}
        rows = list(q("SELECT day, kind, at, amount FROM chores WHERE farm_id=? AND day>=? ORDER BY at", fid, start.isoformat()))
        rows += [dict(day=r["at"][:10], kind="eggs", at=r["at"], amount=r["eggs"]) for r in
                 q("SELECT at, eggs FROM eggs WHERE farm_id=? AND kind='collect' AND at>=? ORDER BY at", fid, start.isoformat())]
        for r in rows:
            if r["day"] not in days:
                continue
            x = days[r["day"]][r["kind"]]
            x["times"].append(r["at"][11:16])
            if r["amount"] is not None:  # kury: ostatnie liczenie dnia; reszta: suma
                x["amount"] = r["amount"] if r["kind"] == "hens" else round((x["amount"] or 0) + r["amount"], 2)
        return jsonify([dict(day=d, **v) for d, v in sorted(days.items(), reverse=True)])
