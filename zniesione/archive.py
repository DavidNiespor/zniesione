"""Archiwum z dawnego arkusza Google (Plik → Pobierz → CSV): dzienne zbiory, sprzedaż w cenach z kolumn, wydatki.
Dane trafiają do osobnej tabeli i są tylko do podglądu: nie zmieniają stanów jaj, kartoteki ani wydatków w portalu."""
import csv
import io
import json
import re
from datetime import date, datetime

from flask import g, jsonify, request

MAX_BYTES = 5 * 1024 * 1024
FIELDS = {"hens": "ilość kur", "broody": "kwok", "eggs": "jajek", "losses": "straty", "stock": "magazyn", "orders": "zamówienia",
          "home": "dom", "revenue": "suma", "paid_out": "wypłacono", "expense_type": "typ wydatku", "expense": "wydatki"}


def num(s):
    """„1 286,00 zł”, „44,41%”, „6 063” → liczba; puste → None."""
    s = re.sub(r"[\s  zł%]", "", str(s or "")).replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def parse(text):
    """Zwraca listę dni z arkusza. Kolumny rozpoznaje po nagłówkach, więc kolejność w arkuszu może być inna."""
    rows = list(csv.reader(io.StringIO(text)))
    head = next((i for i, r in enumerate(rows[:20]) if any("jajek" in c.lower() for c in r)), None)
    if head is None:
        raise ValueError("Nie rozpoznano arkusza: brak kolumny „Ilość Jajek” w nagłówku")
    h = [c.strip().lower() for c in rows[head]]
    col = {}
    for k, key in FIELDS.items():  # „wydatki” nie może złapać „typ wydatku”, a „dom” tylko dokładnie
        for i, c in enumerate(h):
            if (c == key if k in ("home", "expense", "revenue") else key in c) and i not in col.values():
                col[k] = i
                break
    if "eggs" not in col:
        raise ValueError("Nie rozpoznano arkusza: brak kolumny „Ilość Jajek”")
    # kolumny cen: nagłówek to liczba (np. „1,2”, „1”, „0”), wartości to sprzedane sztuki po tej cenie za sztukę
    prices = [(i, num(c)) for i, c in enumerate(h) if re.fullmatch(r"\d+([.,]\d+)?", c)]
    today, out = date.today(), []
    for r in rows[head + 1:]:
        try:
            d = datetime.strptime(r[0].strip(), "%d.%m.%Y").date()
        except (ValueError, IndexError):
            continue  # wiersz bez daty (np. dopisek pod tabelą)
        cell = lambda k: r[col[k]] if k in col and col[k] < len(r) else ""
        v = {k: num(cell(k)) for k in ("hens", "broody", "eggs", "losses", "stock", "orders", "home", "revenue", "expense")}
        sales = [[p, int(num(r[i]))] for i, p in prices if i < len(r) and num(r[i])]
        busy = any(v[k] for k in ("eggs", "losses", "home", "orders", "revenue", "expense")) or sales or v["eggs"] == 0
        if d > today or not busy:
            continue  # przyszłe dni i puste wiersze (sama liczba kur i saldo) pomijamy
        out.append(dict(day=d.isoformat(), **{k: int(v[k] or 0) for k in ("hens", "broody", "eggs", "losses", "stock", "orders", "home")},
                        sales=sales, revenue=round(v["revenue"] or 0, 2), expense=round(v["expense"] or 0, 2),
                        expense_type=cell("expense_type").strip()[:60], paid_out=cell("paid_out").strip().upper() == "TAK",
                        logged=v["eggs"] is not None))
    if not out:
        raise ValueError("W arkuszu nie ma dni z danymi")
    return out


def summary(days):
    months, tot, by_price, exp = {}, dict(eggs=0, losses=0, home=0, sold=0, given=0, revenue=0.0, expenses=0.0), {}, []
    for d in days:
        m = months.setdefault(d["day"][:7], dict(month=d["day"][:7], eggs=0, layers=0, logged=0, hens=0, sold=0, home=0, revenue=0.0, expenses=0.0))
        m["hens"] = d["hens"] or m["hens"]
        if d["logged"]:
            m["eggs"] += d["eggs"]; m["logged"] += 1; m["layers"] += max(0, d["hens"] - d["broody"])
        for p, n in d["sales"]:
            by_price[p] = by_price.get(p, 0) + n
            if p > 0:
                m["sold"] += n; tot["sold"] += n
            else:
                tot["given"] += n
        m["home"] += d["home"]; m["revenue"] += d["revenue"]; m["expenses"] += d["expense"]
        tot["eggs"] += d["eggs"]; tot["losses"] += d["losses"]; tot["home"] += d["home"]
        tot["revenue"] += d["revenue"]; tot["expenses"] += d["expense"]
        if d["expense"]:
            exp.append(dict(day=d["day"], type=d["expense_type"], amount=d["expense"]))
    for m in months.values():  # nieśność: jaja / kury bez kwok, tylko dni z wpisanym zbiorem
        layers = m.pop("layers")
        m["laying"] = round(m["eggs"] * 100 / layers, 1) if m["logged"] and layers else None
        m["revenue"], m["expenses"] = round(m["revenue"], 2), round(m["expenses"], 2)
    tot = {k: round(v, 2) for k, v in tot.items()}
    tot["profit"] = round(tot["revenue"] - tot["expenses"], 2)
    return dict(first=days[0]["day"], last=days[-1]["day"], days=len(days), totals=tot, by_price={str(k): v for k, v in sorted(by_price.items())},
                monthly=list(months.values()), expenses=exp)


def store(q, fid, days, name):
    """Zapis archiwum farmy; ponowny import zastępuje poprzedni."""
    q("DELETE FROM archive_days WHERE farm_id=?", fid)
    for d in days:
        q("INSERT INTO archive_days(farm_id,day,hens,broody,eggs,logged,losses,stock,orders,home,sales,revenue,expense,expense_type,paid_out) "
          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fid, d["day"], d["hens"], d["broody"], d["eggs"], int(d["logged"]), d["losses"],
          d["stock"], d["orders"], d["home"], json.dumps(d["sales"]), d["revenue"], d["expense"], d["expense_type"], int(d["paid_out"]))
    q("UPDATE farms SET archive_name=?, archive_at=? WHERE id=?", name[-120:], datetime.now().isoformat(timespec="seconds"), fid)


def register(app, need, q, commit, err):
    @app.route("/api/my/archive", methods=["GET", "POST", "DELETE"])
    @need("farmer")
    def archive():
        fid = g.user["farm_id"]
        if request.method == "DELETE":
            q("DELETE FROM archive_days WHERE farm_id=?", fid)
            q("UPDATE farms SET archive_name='', archive_at='' WHERE id=?", fid)
            commit()
            return jsonify(ok=True)
        if request.method == "POST":
            f = request.files.get("file")
            if not f:
                return err("Wybierz plik CSV pobrany z arkusza Google")
            raw = f.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                return err("Plik większy niż 5 MB")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1250", errors="replace")  # CSV zapisany w Excelu
            try:
                days = parse(text)
            except ValueError as e:
                return err(str(e))
            store(q, fid, days, f.filename or "arkusz.csv")
            commit()
            return jsonify(days=len(days), first=days[0]["day"], last=days[-1]["day"]), 201
        rows = q("SELECT * FROM archive_days WHERE farm_id=? ORDER BY day", fid).fetchall()
        meta = q("SELECT archive_name, archive_at FROM farms WHERE id=?", fid).fetchone()
        if not rows:
            return jsonify(empty=True)
        days = [dict(r, sales=json.loads(r["sales"]), logged=bool(r["logged"]), paid_out=bool(r["paid_out"])) for r in rows]
        for d in days:
            d.pop("farm_id"), d.pop("id")
        return jsonify(empty=False, name=meta["archive_name"], imported=meta["archive_at"], days_list=days, **summary(days))
