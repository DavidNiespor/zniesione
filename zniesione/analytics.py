"""Kalendarz zamówień i dostaw, analityka z wykresami (serie dzienne i miesięczne) oraz eksport danych farmy do CSV w ZIP."""
import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta

from flask import g, jsonify, request, send_file

from .farmbook import valid_date

# tabele farmy w eksporcie (wszystkie mają farm_id); hasła i klucze sterowników nie trafiają do eksportu
EXPORT = ("clients", "sales", "ledger", "eggs", "subscriptions", "orders", "expenses", "equipment", "flocks", "buildings",
          "feed_items", "feed_moves", "recipes", "mixes", "chores")


def months_back(d, n):
    """Pierwsze dni n ostatnich miesięcy, od najstarszego."""
    y, m, out = d.year, d.month, []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def register(app, need, q, commit, body, err):
    @app.patch("/api/my/orders/<int:oid>")
    @need("farmer")
    def order_patch(oid):
        """Termin odbioru lub dostawy zamówienia (widoczny w kalendarzu)."""
        o = q("SELECT * FROM orders WHERE id=? AND farm_id=?", oid, g.user["farm_id"]).fetchone()
        if not o:
            return err("Nie znaleziono", 404)
        d = body().get("due_date", "")
        if d != "" and not valid_date(d):
            return err("Termin w formacie RRRR-MM-DD")
        q("UPDATE orders SET due_date=? WHERE id=?", d, oid)
        commit()
        return jsonify(dict(q("SELECT * FROM orders WHERE id=?", oid).fetchone()))

    @app.get("/api/my/calendar")
    @need("farmer")
    def calendar():
        """Miesiąc: zamówienia (termin albo dzień złożenia), dostawy zamówień cyklicznych, wykonana sprzedaż i zbiory."""
        fid, month = g.user["farm_id"], request.args.get("month", date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            return err("Miesiąc w formacie RRRR-MM")
        first = date.fromisoformat(month + "-01")
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        lo, hi = first.isoformat(), last.isoformat()
        days = {}

        def add(d, item):
            days.setdefault(d, []).append(item)

        for o in q("SELECT id,name,qty,status,due_date,created,pickup FROM orders WHERE farm_id=? AND status IN ('pending','confirmed')", fid):
            d = o["due_date"] or o["created"][:10]
            if lo <= d <= hi:
                add(d, dict(type="order", id=o["id"], name=o["name"], packs=o["qty"], status=o["status"], pickup=o["pickup"],
                            due=bool(o["due_date"])))
        for s in q("SELECT s.id, s.eggs, s.every_days, s.next_date, c.name FROM subscriptions s JOIN clients c ON c.id=s.client_id "
                   "WHERE s.farm_id=? AND s.active=1", fid):
            if not valid_date(s["next_date"]):
                continue
            d = date.fromisoformat(s["next_date"])
            while d <= last:  # kolejne dostawy od najbliższej
                if d >= first:
                    add(d.isoformat(), dict(type="sub", id=s["id"], name=s["name"], eggs=s["eggs"]))
                d += timedelta(days=max(1, s["every_days"]))
        for r in q("SELECT substr(at,1,10) d, COUNT(*) n, SUM(eggs) e, SUM(total) t FROM sales WHERE farm_id=? AND at>=? AND at<? "
                   "GROUP BY d", fid, lo, (last + timedelta(days=1)).isoformat()):
            add(r["d"], dict(type="sales", count=r["n"], eggs=r["e"], total=round(r["t"], 2)))
        for r in q("SELECT substr(at,1,10) d, SUM(eggs) e FROM eggs WHERE farm_id=? AND kind='collect' AND at>=? AND at<? GROUP BY d",
                   fid, lo, (last + timedelta(days=1)).isoformat()):
            add(r["d"], dict(type="collect", eggs=r["e"]))
        return jsonify(month=month, first=lo, last=hi, days=days)

    @app.get("/api/my/analytics")
    @need("farmer")
    def analytics():
        fid = g.user["farm_id"]
        n = request.args.get("days", "90")
        if not n.isdigit() or not 7 <= int(n) <= 366:
            return err("Parametr days od 7 do 366")
        n = int(n)
        start = date.today() - timedelta(days=n - 1)
        since = start.isoformat()
        birds = q("SELECT COALESCE(SUM(birds),0) FROM flocks WHERE farm_id=?", fid).fetchone()[0]
        daily = {(start + timedelta(days=i)).isoformat(): dict(collected=0, sold=0, given=0, lost=0, revenue=0.0, feed=None, water=None) for i in range(n)}
        for r in q("SELECT day, kind, SUM(amount) a FROM chores WHERE farm_id=? AND day>=? AND kind IN ('feed','water') AND amount IS NOT NULL "
                   "GROUP BY day, kind", fid, since):  # nasypana pasza (kg) i nalana woda (l) z listy obowiązków
            if r["day"] in daily:
                daily[r["day"]][r["kind"]] = round(r["a"], 2)
        for r in q("SELECT substr(at,1,10) d, kind, SUM(eggs) e FROM eggs WHERE farm_id=? AND at>=? AND kind IN ('collect','gift','loss') "
                   "GROUP BY d, kind", fid, since):
            if r["d"] in daily:
                daily[r["d"]][dict(collect="collected", gift="given", loss="lost")[r["kind"]]] = r["e"]
        for r in q("SELECT substr(at,1,10) d, SUM(eggs) e, SUM(total) t FROM sales WHERE farm_id=? AND at>=? GROUP BY d", fid, since):
            if r["d"] in daily:
                daily[r["d"]].update(sold=r["e"], revenue=round(r["t"], 2))
        # nieśność tylko dla dni z wpisanym zbiorem (dzień bez wpisu to brak danych, nie zero jaj)
        series = [dict(date=d, **v, laying=round(v["collected"] * 100 / birds, 1) if birds and v["collected"] else None) for d, v in daily.items()]
        logged = sum(1 for s in series if s["collected"])

        months = months_back(date.today(), max(1, min(12, (n + 29) // 30)))
        monthly = {m: dict(month=m, revenue=0.0, expenses=0.0) for m in months}
        for r in q("SELECT substr(at,1,7) m, SUM(total) t FROM sales WHERE farm_id=? AND at>=? GROUP BY m", fid, months[0]):
            if r["m"] in monthly:
                monthly[r["m"]]["revenue"] = round(r["t"], 2)
        for r in q("SELECT substr(date,1,7) m, SUM(total) t FROM expenses WHERE farm_id=? AND date>=? GROUP BY m", fid, months[0]):
            if r["m"] in monthly:
                monthly[r["m"]]["expenses"] = round(r["t"], 2)
        for m in monthly.values():
            m["profit"] = round(m["revenue"] - m["expenses"], 2)

        methods = {}
        for r in q("SELECT method, -SUM(amount) v FROM ledger WHERE farm_id=? AND at>=? AND kind IN ('payment','refund') GROUP BY method",
                   fid, since):
            methods[r["method"]] = methods.get(r["method"], 0) + r["v"]
        for r in q("SELECT method, SUM(paid) v FROM sales WHERE farm_id=? AND at>=? AND client_id IS NULL GROUP BY method", fid, since):
            methods[r["method"]] = methods.get(r["method"], 0) + r["v"]
        top = [dict(r) for r in q("SELECT c.name, SUM(s.eggs) eggs, ROUND(SUM(s.total),2) total FROM sales s JOIN clients c ON c.id=s.client_id "
                                  "WHERE s.farm_id=? AND s.at>=? GROUP BY s.client_id ORDER BY eggs DESC LIMIT 10", fid, since)]
        people = {}
        for r in q("SELECT u.id, COALESCE(NULLIF(u.name,''), u.email) name FROM users u WHERE u.farm_id=? AND u.role='farmer'", fid):
            people[r["id"]] = dict(name=r["name"], collected=0, sorted=0, sales=0, sold=0)
        for r in q("SELECT user_id, kind, SUM(eggs) e FROM eggs WHERE farm_id=? AND at>=? AND kind IN ('collect','sort') GROUP BY user_id, kind",
                   fid, since):
            if r["user_id"] in people:
                people[r["user_id"]]["collected" if r["kind"] == "collect" else "sorted"] = r["e"]
        for r in q("SELECT user_id, COUNT(*) n, SUM(eggs) e FROM sales WHERE farm_id=? AND at>=? GROUP BY user_id", fid, since):
            if r["user_id"] in people:
                people[r["user_id"]].update(sales=r["n"], sold=r["e"])
        tot = {k: sum(s[k] for s in series) for k in ("collected", "sold", "given", "lost")}
        for k in ("feed", "water"):
            v = [s[k] for s in series if s[k] is not None]
            tot[k], tot[k + "_days"] = round(sum(v), 2), len(v)
        tot["feed_per_hen_g"] = round(tot["feed"] * 1000 / (birds * tot["feed_days"]), 0) if birds and tot["feed_days"] else None
        tot["water_per_hen_ml"] = round(tot["water"] * 1000 / (birds * tot["water_days"]), 0) if birds and tot["water_days"] else None
        return jsonify(days=n, birds=birds, daily=series, monthly=list(monthly.values()),
                       methods={k: round(v, 2) for k, v in methods.items() if abs(v) > 0.005}, top_clients=top,
                       people=[p for p in people.values() if p["collected"] or p["sorted"] or p["sales"]],
                       totals=dict(tot, revenue=round(sum(s["revenue"] for s in series), 2),
                                   days_logged=logged, laying=round(tot["collected"] * 100 / (birds * logged), 1) if birds and logged else None))

    @app.get("/api/my/export.zip")
    @need("farmer")
    def export():
        """Kopia danych farmy na własny komputer: każda tabela jako CSV (otwiera się w Excelu)."""
        fid, buf = g.user["farm_id"], io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for t in EXPORT:
                rows = q(f"SELECT * FROM {t} WHERE farm_id=? ORDER BY id", fid).fetchall()
                cols = [r[1] for r in q(f"PRAGMA table_info({t})")]
                s = io.StringIO()
                w = csv.writer(s, delimiter=";")
                w.writerow(cols)
                w.writerows([[r[c] for c in cols] for r in rows])
                z.writestr(f"{t}.csv", "﻿" + s.getvalue())  # BOM: Excel rozpozna polskie znaki
            items = q("SELECT ri.* FROM recipe_items ri JOIN recipes r ON r.id=ri.recipe_id WHERE r.farm_id=? ORDER BY ri.id", fid).fetchall()
            s = io.StringIO()
            w = csv.writer(s, delimiter=";")
            w.writerow(["id", "recipe_id", "item_id", "percent"])
            w.writerows([[r["id"], r["recipe_id"], r["item_id"], r["percent"]] for r in items])
            z.writestr("recipe_items.csv", "﻿" + s.getvalue())
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name=f"farma-{datetime.now():%Y-%m-%d}.zip")
