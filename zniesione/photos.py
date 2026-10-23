"""Zdjęcia gospodarstwa, budynków i stad. Widać je w sklepie przy karcie gospodarstwa, więc klient widzi kurniki i kury.
Plik sprawdzany po zawartości (JPEG, PNG, WebP), zapisywany pod losową nazwą obok bazy, w katalogu photos/."""
import os
import secrets
from datetime import datetime

from flask import g, jsonify, request, send_file

MAX_BYTES = 8 * 1024 * 1024
MAX_PER_FARM = 60
TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def kind(head):
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def photo_json(p):
    return dict(id=p["id"], url=f"/photos/{p['id']}", caption=p["caption"], building_id=p["building_id"], flock_id=p["flock_id"])


def register(app, need, q, commit, body, err):
    def folder():
        d = os.path.join(os.path.dirname(os.path.abspath(app.config["DATABASE"])), "photos")
        os.makedirs(d, exist_ok=True)
        return d

    def owned(table, v, fid):
        return v is None or q(f"SELECT 1 FROM {table} WHERE id=? AND farm_id=?", v, fid).fetchone()

    @app.route("/api/my/photos", methods=["GET", "POST"])
    @need("farmer")
    def photos():
        fid = g.user["farm_id"]
        if request.method == "GET":
            return jsonify([photo_json(p) for p in q("SELECT * FROM photos WHERE farm_id=? ORDER BY id", fid)])
        f = request.files.get("file")
        if not f:
            return err("Wybierz zdjęcie")
        data = f.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return err("Zdjęcie większe niż 8 MB")
        ext = kind(data[:16])
        if not ext:
            return err("Zdjęcie w formacie JPEG, PNG albo WebP")
        if q("SELECT COUNT(*) FROM photos WHERE farm_id=?", fid).fetchone()[0] >= MAX_PER_FARM:
            return err(f"Najwyżej {MAX_PER_FARM} zdjęć na gospodarstwo. Usuń starsze.", 409)
        ids = {}
        for k, t in (("building_id", "buildings"), ("flock_id", "flocks")):
            v = request.form.get(k) or None
            if v is not None and (not v.isdigit() or not owned(t, int(v), fid)):
                return err("Nieznany budynek lub stado")
            ids[k] = int(v) if v else None
        caption = (request.form.get("caption") or "").strip()[:120]
        name = f"{secrets.token_hex(12)}.{ext}"
        with open(os.path.join(folder(), name), "wb") as fh:
            fh.write(data)
        pid = q("INSERT INTO photos(farm_id,building_id,flock_id,file,caption,created) VALUES(?,?,?,?,?,?)", fid, ids["building_id"],
                ids["flock_id"], name, caption, datetime.now().isoformat(timespec="seconds")).lastrowid
        commit()
        return jsonify(photo_json(q("SELECT * FROM photos WHERE id=?", pid).fetchone())), 201

    @app.route("/api/my/photos/<int:pid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def photo(pid):
        p = q("SELECT * FROM photos WHERE id=? AND farm_id=?", pid, g.user["farm_id"]).fetchone()
        if not p:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            q("DELETE FROM photos WHERE id=?", pid)
            commit()
            try:
                os.remove(os.path.join(folder(), p["file"]))
            except OSError:
                pass  # plik już usunięty: wpis i tak znika
            return jsonify(ok=True)
        c = body().get("caption", "")
        if not isinstance(c, str) or len(c) > 120:
            return err("Podpis do 120 znaków")
        q("UPDATE photos SET caption=? WHERE id=?", c.strip(), pid)
        commit()
        return jsonify(photo_json(q("SELECT * FROM photos WHERE id=?", pid).fetchone()))

    @app.get("/photos/<int:pid>")
    def photo_file(pid):
        """Publiczne: zdjęcia są pokazywane w sklepie, ale tylko aktywnych gospodarstw."""
        p = q("SELECT p.* FROM photos p JOIN farms f ON f.id=p.farm_id WHERE p.id=? AND f.active=1", pid).fetchone()
        path = p and os.path.join(folder(), p["file"])
        if not p or not os.path.isfile(path):
            return err("Nie znaleziono", 404)
        r = send_file(path, mimetype=TYPES[p["file"].rsplit(".", 1)[1]], max_age=86400)
        r.headers["X-Content-Type-Options"] = "nosniff"
        return r

    def shop_extra(fid):
        """Do karty gospodarstwa w sklepie: zdjęcia ogólne, budynki ze stadami i ich zdjęciami."""
        ph = [dict(p) for p in q("SELECT * FROM photos WHERE farm_id=? ORDER BY id", fid)]
        pick = lambda **k: [photo_json(p) for p in ph if all(p[a] == b for a, b in k.items())]
        fl = [dict(x) for x in q("SELECT id, name, breed, birds, building_id FROM flocks WHERE farm_id=? ORDER BY name", fid)]
        flock = lambda x: dict(name=x["name"], breed=x["breed"], birds=x["birds"], photos=pick(flock_id=x["id"]))
        bs = [dict(name=b["name"], notes=b["notes"], flocks=[flock(x) for x in fl if x["building_id"] == b["id"]],
                   photos=pick(building_id=b["id"], flock_id=None)) for b in q("SELECT * FROM buildings WHERE farm_id=? ORDER BY name", fid)]
        bids = {b["id"] for b in q("SELECT id FROM buildings WHERE farm_id=?", fid)}
        loose = [flock(x) for x in fl if x["building_id"] not in bids]
        return dict(photos=pick(building_id=None, flock_id=None), buildings=bs, flocks=loose)

    return shop_extra
