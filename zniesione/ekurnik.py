"""Import danych z bazy e-kurnika (ferma.db lub jej kopii) do jednej farmy portalu.

Uruchom:  flask --app zniesione import-ekurnik KOPIA.db --email rolnik@... [--gid N]
Przenosi: klientów (z ceną indywidualną), historię zakupów i wpłat z saldem zgodnym z e-kurnikiem, sprzedaż,
zbiory jaj, straty, stan magazynu, stada, wydatki, wyposażenie, zamówienia cykliczne i cenę jajka.
Plik e-kurnika jest otwierany tylko do odczytu. Farmę można zaimportować raz."""
import re
import sqlite3
from datetime import datetime

from .clients import phone_key

METHOD = {"gotowka": "cash", "przelew": "transfer", "nastepnym_razem": "later", "z_salda": "balance"}
STATE = {"sprawne": "ok", "do naprawy": "repair", "uszkodzone": "broken", "zepsute": "broken", "wycofane": "retired"}
CATEGORY = {"Zboże/pasza": "Pasza i zboże", "Zboze/pasza": "Pasza i zboże", "Witaminy/suplementy": "Witaminy i suplementy"}


def farms_summary(src):
    """Gospodarstwa w bazie e-kurnika z liczbą klientów i dni produkcji (do wyboru --gid)."""
    return src.execute("""SELECT g.id, g.nazwa, (SELECT COUNT(*) FROM klienci k WHERE k.gospodarstwo_id=g.id) AS klienci,
                          (SELECT COUNT(*) FROM produkcja p WHERE p.gospodarstwo_id=g.id) AS dni FROM gospodarstwa g ORDER BY g.id""").fetchall()


def iso(v, hour="12:00:00"):
    """Data z e-kurnika (DATE, 'YYYY-MM-DD HH:MM:SS' albo ISO) jako ISO z godziną; None, gdy nie da się odczytać."""
    s = str(v or "").strip().replace(" ", "T")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T" + hour
    try:
        return datetime.fromisoformat(s[:19]).isoformat(timespec="seconds")
    except ValueError:
        return None


def has(src, table):
    return bool(src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def import_ekurnik(db, path, farm_id, gid):
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    key = f"ekurnik_import_{farm_id}"
    if db.execute("SELECT 1 FROM config WHERE k=?", (key,)).fetchone():
        raise ValueError("Ta farma ma już zaimportowane dane z e-kurnika")
    if not src.execute("SELECT 1 FROM gospodarstwa WHERE id=?", (gid,)).fetchone():
        raise ValueError(f"W bazie e-kurnika nie ma gospodarstwa {gid}")
    n = dict(klienci=0, transakcje=0, sprzedaz=0, zbiory=0, straty=0, stada=0, wydatki=0, wyposazenie=0, cykliczne=0, wyrownania=0)
    now = datetime.now().isoformat(timespec="seconds")

    price = src.execute("SELECT wartosc FROM ustawienia WHERE klucz='cena_jajka' AND gospodarstwo_id=?", (gid,)).fetchone()
    if price:
        try:
            db.execute("UPDATE farms SET price10=? WHERE id=? AND COALESCE(price10,0)=0", (round(float(price[0]) * 10, 2), farm_id))
        except ValueError:
            pass

    cmap = {}  # id klienta w e-kurniku -> id w portalu
    for k in src.execute("SELECT * FROM klienci WHERE gospodarstwo_id=?", (gid,)):
        cols = k.keys()
        phone, pk = (k["telefon"] or "").strip()[:20], phone_key(k["telefon"])
        cena = float(k["cena_indyw"] or 0) if "cena_indyw" in cols else 0
        hit = db.execute("SELECT id FROM clients WHERE farm_id=? AND phone_key=? AND phone_key!=''", (farm_id, pk)).fetchone()
        if hit:  # ten sam numer jest już w kartotece (np. z zamówienia w sklepie)
            cmap[k["id"]] = hit["id"]
            continue
        cmap[k["id"]] = db.execute(
            "INSERT INTO clients(farm_id,name,phone,phone_key,email,address,notes,price10,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (farm_id, (k["nazwa"] or "Klient").strip()[:100], phone, pk, (k["email"] or "").strip()[:120], (k["adres"] or "").strip()[:200],
             (k["uwagi"] or "").strip()[:1000], round(cena * 10, 2) if cena >= 0.1 else None, now)).lastrowid
        n["klienci"] += 1

    # historia salda: sprzedaż na dług (+), wpłaty (-), korekty; na końcu wyrównanie do salda z e-kurnika
    for t in src.execute("SELECT * FROM konta_transakcje WHERE gospodarstwo_id=? ORDER BY data, id", (gid,)):
        cid, at = cmap.get(t["klient_id"]), iso(t["data"])
        if not cid or not at:
            continue
        kind = {"sprzedaz": "sale", "wplata": "payment", "korekta": "correction"}.get(t["typ"], "correction")
        opis = (t["opis"] or "").strip()
        method = ("transfer" if re.search(r"przelew", opis, re.I) else "blik" if re.search(r"blik", opis, re.I) else "cash") if kind == "payment" else ""
        db.execute("INSERT INTO ledger(farm_id,client_id,at,kind,amount,method,note) VALUES(?,?,?,?,?,?,?)",
                   (farm_id, cid, at, kind, round(float(t["kwota"] or 0), 2), method, ("e-kurnik: " + opis)[:200]))
        n["transakcje"] += 1
    for s in src.execute("SELECT klient_id, saldo_pln FROM konta_saldo"):
        cid = cmap.get(s["klient_id"])
        if not cid:
            continue
        cur = db.execute("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE client_id=?", (cid,)).fetchone()[0]
        diff = round(float(s["saldo_pln"] or 0) - cur, 2)
        if abs(diff) > 0.005:
            db.execute("INSERT INTO ledger(farm_id,client_id,at,kind,amount,note) VALUES(?,?,?,?,?,?)",
                       (farm_id, cid, now, "correction", diff, "Wyrównanie do salda z e-kurnika"))
            n["wyrownania"] += 1

    # sprzedaż (historia w kartotece; saldo pochodzi z transakcji powyżej, więc bez wpisów w ledger)
    for s in src.execute("SELECT * FROM sprzedaz_szczegol WHERE gospodarstwo_id=? ORDER BY data, id", (gid,)):
        at, eggs = iso(s["data"]), int(s["ilosc"] or 0)
        if not at or eggs <= 0:
            continue
        method = METHOD.get(s["typ"], "cash")
        total = round(float(s["wartosc"] or 0), 2)
        db.execute("INSERT INTO sales(farm_id,client_id,at,eggs,packs,price10,total,method,paid,notes,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (farm_id, cmap.get(s["klient_id"]), at, eggs, eggs // 10, round(float(s["cena_szt"] or 0) * 10, 2), total, method,
                    total if method in ("cash", "transfer") else 0, ("e-kurnik " + (s["uwagi"] or "")).strip()[:200], "free"))
        n["sprzedaz"] += 1

    # dziennik jaj: zbiory, sprzedane (jak liczy e-kurnik: więcej z sumy sprzedaży i wpisu dziennego), straty
    detail = {r[0]: r[1] for r in src.execute("SELECT data, SUM(ilosc) FROM sprzedaz_szczegol WHERE gospodarstwo_id=? GROUP BY data", (gid,))}
    days = set(detail)
    for p in src.execute("SELECT data, jaja_zebrane, jaja_sprzedane FROM produkcja WHERE gospodarstwo_id=? ORDER BY data", (gid,)):
        days.discard(p["data"])
        if (p["jaja_zebrane"] or 0) > 0 and iso(p["data"]):
            db.execute("INSERT INTO eggs(farm_id,kind,eggs,packs,at,note) VALUES(?,?,?,?,?,?)",
                       (farm_id, "collect", p["jaja_zebrane"], p["jaja_zebrane"] // 10, iso(p["data"], "18:00:00"), "e-kurnik"))
            n["zbiory"] += 1
        sold = max(int(detail.get(p["data"]) or 0), int(p["jaja_sprzedane"] or 0))
        if sold and iso(p["data"]):
            db.execute("INSERT INTO eggs(farm_id,kind,eggs,packs,at,note) VALUES(?,?,?,?,?,?)",
                       (farm_id, "sale", sold, sold // 10, iso(p["data"], "19:00:00"), "e-kurnik"))
    for d in days:  # sprzedaż w dniach bez wpisu produkcji
        if iso(d):
            db.execute("INSERT INTO eggs(farm_id,kind,eggs,packs,at,note) VALUES(?,?,?,?,?,?)",
                       (farm_id, "sale", int(detail[d]), int(detail[d]) // 10, iso(d, "19:00:00"), "e-kurnik"))
    if has(src, "jaja_straty"):
        for s in src.execute("SELECT * FROM jaja_straty WHERE gospodarstwo_id=?", (gid,)):
            if iso(s["data"]) and (s["ilosc"] or 0) > 0:
                db.execute("INSERT INTO eggs(farm_id,kind,eggs,at,note) VALUES(?,?,?,?,?)",
                           (farm_id, "loss", s["ilosc"], iso(s["data"], "20:00:00"), ("e-kurnik: " + (s["powod"] or "") + " " + (s["uwagi"] or "")).strip()[:200]))
                n["straty"] += 1
    stock = warehouse(src, gid)
    db.execute("UPDATE farms SET eggs=eggs+? WHERE id=?", (stock, farm_id))
    db.execute("INSERT INTO eggs(farm_id,kind,eggs,at,note) VALUES(?,?,?,?,?)", (farm_id, "inventory", stock, now, "Stan magazynu z e-kurnika"))

    for s in src.execute("SELECT * FROM stado WHERE gospodarstwo_id=? AND COALESCE(aktywne,1)=1", (gid,)):
        name = (s["nazwa"] or "Stado").strip()
        if s["gatunek"] == "kogut" and "kogut" not in name.lower():
            name += " (koguty)"
        db.execute("INSERT INTO flocks(farm_id,name,birds,breed,since,notes) VALUES(?,?,?,?,?,?)",
                   (farm_id, name[:60], int(s["liczba"] or 0), (s["rasa"] or "")[:60], (iso(s["data_dodania"]) or "")[:10], (s["uwagi"] or "")[:1000]))
        n["stada"] += 1
    for w in src.execute("SELECT * FROM wydatki WHERE gospodarstwo_id=?", (gid,)):
        if not iso(w["data"]):
            continue
        unit = (w["jednostka"] or "szt") if w["jednostka"] not in (None, "", "import") else "szt"
        db.execute("INSERT INTO expenses(farm_id,date,category,name,qty,unit,unit_price,total,supplier,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (farm_id, iso(w["data"])[:10], CATEGORY.get(w["kategoria"], w["kategoria"] or "Inne")[:60], (w["nazwa"] or "Wydatek")[:120],
                    float(w["ilosc"] or 1), unit[:10], float(w["cena_jednostkowa"] or 0), round(float(w["wartosc_total"] or 0), 2),
                    (w["dostawca"] or "")[:120], (w["uwagi"] or "")[:500]))
        n["wydatki"] += 1
    for w in src.execute("SELECT * FROM wyposazenie WHERE gospodarstwo_id=?", (gid,)):
        db.execute("INSERT INTO equipment(farm_id,name,category,bought,price,state,next_check,notes) VALUES(?,?,?,?,?,?,?,?)",
                   (farm_id, (w["nazwa"] or "Wyposażenie")[:120], (w["kategoria"] or "")[:60], (iso(w["data_zakupu"]) or "")[:10],
                    float(w["cena"] or 0), STATE.get((w["stan"] or "").lower(), "ok"), (iso(w["nastepny_przeglad"]) or "")[:10], (w["uwagi"] or "")[:500]))
        n["wyposazenie"] += 1
    for z in src.execute("SELECT * FROM zamowienia WHERE gospodarstwo_id=? AND cykl_dni>0 AND cykl_aktywne=1 AND status IN ('nowe','potwierdzone')", (gid,)):
        cid = cmap.get(z["klient_id"])
        if cid and iso(z["data_dostawy"]):
            db.execute("INSERT INTO subscriptions(farm_id,client_id,eggs,every_days,next_date,method,notes,created) VALUES(?,?,?,?,?,?,?,?)",
                       (farm_id, cid, int(z["ilosc"]), min(90, int(z["cykl_dni"])), iso(z["data_dostawy"])[:10],
                        {"gotowka": "cash", "przelew": "transfer"}.get(z["platnosc_typ"], "later"), "Z e-kurnika", now))
            n["cykliczne"] += 1
    db.execute("INSERT INTO config(k,v) VALUES(?,?)", (key, now))
    db.commit()
    src.close()
    n["magazyn_szt"] = stock
    return n


def warehouse(src, gid):
    """Stan magazynu jak w e-kurniku: ostatnia inwentaryzacja + zebrane po niej - sprzedane - straty."""
    inv = src.execute("SELECT data, stan FROM inwentaryzacje WHERE gospodarstwo_id=? ORDER BY data DESC, id DESC LIMIT 1", (gid,)).fetchone() \
        if has(src, "inwentaryzacje") else None
    base, since = (int(inv["stan"]), inv["data"]) if inv else (0, "0000-00-00")
    collected = src.execute("SELECT COALESCE(SUM(jaja_zebrane),0) FROM produkcja WHERE gospodarstwo_id=? AND data>?", (gid, since)).fetchone()[0]
    detail = {r[0]: r[1] for r in src.execute("SELECT data, SUM(ilosc) FROM sprzedaz_szczegol WHERE gospodarstwo_id=? AND data>? GROUP BY data", (gid, since))}
    daily = {r[0]: r[1] or 0 for r in src.execute("SELECT data, jaja_sprzedane FROM produkcja WHERE gospodarstwo_id=? AND data>?", (gid, since))}
    sold = sum(max(int(detail.get(d) or 0), int(daily.get(d) or 0)) for d in set(detail) | set(daily))
    lost = src.execute("SELECT COALESCE(SUM(ilosc),0) FROM jaja_straty WHERE gospodarstwo_id=? AND data>?", (gid, since)).fetchone()[0] \
        if has(src, "jaja_straty") else 0
    return max(0, base + int(collected) - sold - int(lost))
