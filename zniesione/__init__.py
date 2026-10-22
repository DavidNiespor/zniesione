import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.security import check_password_hash, generate_password_hash

from . import catalog as cat
from . import db as dbm
from . import services as sv

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
MODES, PICKUPS, DAYS = ("once", "weekly", "biweekly"), ("pickup", "delivery"), ("a", "w", "e")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def err(msg, code=400):
    return jsonify(error=msg), code


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def integer(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


class Session(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        # Secure poza trybem testowym; wyjątek: uruchomienie lokalne po http://127.0.0.1 lub localhost
        return app.config["SESSION_COOKIE_SECURE"] and request.host.rsplit(":", 1)[0] not in LOCAL_HOSTS


def create_app(test_config=None):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.session_interface = Session()
    app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
                      DATABASE=os.environ.get("DATABASE", "zniesione.db"),
                      SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=not (test_config or {}).get("TESTING"),
                      LOGIN_MAX_EMAIL=5, LOGIN_MAX_IP=20, LOGIN_WINDOW_S=600,
                      TICK_S=float(os.environ.get("TICK_S", "2")),
                      SEND=sv.send_http, RUN_SCHEDULER=os.environ.get("RUN_SCHEDULER") == "1")
    app.config.update(test_config or {})
    dbm.init_app(app)
    fails, fails_lock = {}, threading.Lock()  # nieudane logowania: klucz -> czasy prób (pamięć procesu)

    def q(sql, *a):
        return dbm.get().execute(sql, a)

    def commit():
        dbm.get().commit()

    def body():
        b = request.get_json(silent=True)
        return b if isinstance(b, dict) else {}

    def login_blocked(keys, failed=False):
        now, win = time.monotonic(), app.config["LOGIN_WINDOW_S"]
        with fails_lock:
            for k, _ in keys:
                fails[k] = [t for t in fails.get(k, []) if now - t < win] + ([now] if failed else [])
                if not fails[k]:
                    del fails[k]
            return any(len(fails.get(k, [])) >= lim for k, lim in keys)

    @app.before_request
    def csrf():  # własny nagłówek wymusza preflight CORS, więc strony trzecie nie wyślą żądania z sesją
        if request.method in MUTATING and request.path.startswith("/api") and request.endpoint != "device_readings":
            if request.headers.get("X-Requested-With") != "zniesione":
                return err("Brak nagłówka X-Requested-With", 403)

    def need(role=None):
        def deco(f):
            @wraps(f)
            def w(*a, **k):
                uid = session.get("uid")
                u = q("SELECT * FROM users WHERE id=?", uid).fetchone() if uid else None
                if not u:
                    return err("Wymagane logowanie", 401)
                if role and u["role"] != role:
                    return err("Brak uprawnień", 403)
                g.user = u
                return f(*a, **k)
            return w
        return deco

    def own_device(did):
        return q("SELECT * FROM devices WHERE id=? AND farm_id=?", did, g.user["farm_id"]).fetchone()

    def dev_json(d, admin=False):
        rules = {r["ch"]: dict(threshold=r["threshold"], enabled=bool(r["enabled"]))
                 for r in q("SELECT * FROM rules WHERE device_id=?", d["id"])}
        ch = [dict(c, rule=rules.get(c["key"]) if c["kind"] in cat.COOL | cat.HEAT else None)
              for c in q("SELECT key,name,kind,state,off_at FROM channels WHERE device_id=? ORDER BY id", d["id"])]
        rs = [dict(r) for r in q("SELECT t,h,at FROM readings WHERE device_id=? ORDER BY id DESC LIMIT 10", d["id"])]
        return dict(id=d["id"], code=d["code"], model=d["model"], model_name=cat.MODELS[d["model"]]["name"],
                    tunnel=d["tunnel"], ip=d["ip"], stage=d["stage"], online=bool(d["online"]), addr=d["addr"],
                    farm_id=d["farm_id"], channels=ch, reading=rs[0] if rs else None, readings=rs,
                    last_seen=d["last_seen"], door=d["door"], door_run_s=d["door_run_s"],
                    **({"api_key": d["api_key"]} if admin else {}))

    def new_device(model, farm_id, tunnel, addr):
        code = "kurnik-" + secrets.token_hex(2)
        did = q("INSERT INTO devices(code,model,farm_id,tunnel,ip,api_key,addr) VALUES(?,?,?,?,?,?,?)",
                code, model, farm_id, tunnel, sv.alloc_ip(dbm.get()), secrets.token_urlsafe(24), addr[:200]).lastrowid
        for k, n, kind in cat.default_channels(model):
            q("INSERT INTO channels(device_id,key,name,kind) VALUES(?,?,?,?)", did, k, n, kind)
        commit()
        return did

    # ---------- publiczne ----------
    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(app.root_path, "static"), "app.html")

    @app.get("/prototype")
    def prototype():
        return send_from_directory(os.path.join(app.root_path, "static"), "prototype.html")

    @app.get("/api/catalog")
    def catalog():
        return jsonify([dict(id=k, name=v["name"], channels=v["channels"], tunnels=v["tunnels"],
                             cheapest=bool(v.get("cheapest")), default=k == cat.DEFAULT_MODEL)
                        for k, v in cat.MODELS.items()])

    @app.get("/api/kinds")
    def kinds():
        return jsonify([dict(id=k, name=cat.KIND_NAMES[k]) for k in cat.KINDS])

    def farm_json(f):
        return dict(id=f["id"], name=f["name"], city=f["city"], zip=f["zip"], breed=f["breed"],
                    descr=f["descr"], price10=f["price10"], stock=f["stock"])

    @app.get("/api/farms")
    def farms():
        s = "%" + request.args.get("q", "").strip().lower() + "%"
        rows = q("SELECT * FROM farms WHERE active=1 AND (lower(name) LIKE ? OR lower(city) LIKE ? OR zip LIKE ?)", s, s, s)
        return jsonify([farm_json(f) for f in rows])

    @app.get("/api/farms/<int:fid>")
    def farm(fid):
        f = q("SELECT * FROM farms WHERE id=? AND active=1", fid).fetchone()
        return jsonify(farm_json(f)) if f else err("Nie znaleziono", 404)

    @app.post("/api/farms/<int:fid>/orders")
    def order(fid):
        f, b = q("SELECT * FROM farms WHERE id=? AND active=1", fid).fetchone(), body()
        if not f:
            return err("Nie znaleziono", 404)
        name, phone = str(b.get("name", "")).strip(), str(b.get("phone", "")).strip()
        qty = b.get("qty")
        if not name or len(name) > 100:
            return err("Podaj imię i nazwisko")
        if not re.fullmatch(r"\+?[0-9 ]{7,15}", phone):
            return err("Niepoprawny telefon")
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= 50:
            return err("Ilość od 1 do 50")
        mode, pickup = b.get("mode", "once"), b.get("pickup", "pickup")
        if mode not in MODES or pickup not in PICKUPS:
            return err("Niepoprawny rodzaj zamówienia lub odbioru")
        oid = q("INSERT INTO orders(farm_id,name,phone,qty,mode,pickup,total,created) VALUES(?,?,?,?,?,?,?,?)",
                fid, name, phone, qty, mode, pickup, qty * f["price10"], datetime.now().isoformat()).lastrowid
        commit()
        return jsonify(id=oid, status="pending", total=qty * f["price10"]), 201

    # ---------- konta ----------
    @app.post("/api/auth/register")
    def register():
        b = body()
        email, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return err("Niepoprawny e-mail")
        if len(pw) < 8:
            return err("Hasło musi mieć co najmniej 8 znaków")
        if not str(b.get("farm_name", "")).strip():
            return err("Podaj nazwę gospodarstwa")
        if q("SELECT 1 FROM users WHERE email=?", email).fetchone():
            return err("Ten e-mail jest już zarejestrowany", 409)
        fid = q("INSERT INTO farms(name,city,zip) VALUES(?,?,?)", b["farm_name"].strip()[:100],
                str(b.get("city", ""))[:80], str(b.get("zip", ""))[:10]).lastrowid
        uid = q("INSERT INTO users(email,pw,role,farm_id) VALUES(?,?,?,?)", email, generate_password_hash(pw), "farmer", fid).lastrowid
        commit()
        session["uid"] = uid
        return jsonify(id=uid, farm_id=fid), 201

    @app.post("/api/auth/login")
    def login():
        b = body()
        email = str(b.get("email", "")).strip().lower()
        keys = [(("email", email), app.config["LOGIN_MAX_EMAIL"]), (("ip", request.remote_addr), app.config["LOGIN_MAX_IP"])]
        if login_blocked(keys):
            return err("Za dużo nieudanych prób logowania. Spróbuj ponownie za 10 minut.", 429)
        u = q("SELECT * FROM users WHERE email=?", email).fetchone()
        if not u or not check_password_hash(u["pw"], str(b.get("password", ""))):
            login_blocked(keys, failed=True)
            return err("Błędny e-mail lub hasło", 401)
        with fails_lock:
            fails.pop(("email", email), None)
        session.clear()
        session["uid"] = u["id"]
        return jsonify(id=u["id"], role=u["role"], farm_id=u["farm_id"])

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    @need()
    def me():
        return jsonify(id=g.user["id"], email=g.user["email"], role=g.user["role"], farm_id=g.user["farm_id"])

    # ---------- rolnik ----------
    @app.route("/api/my/farm", methods=["GET", "PUT"])
    @need("farmer")
    def my_farm():
        b, sets, vals = (body() if request.method == "PUT" else {}), [], []
        for k, t in (("name", str), ("city", str), ("zip", str), ("breed", str), ("descr", str)):
            if k in b:
                if not isinstance(b[k], t) or (k == "name" and not b[k].strip()):
                    return err(f"Niepoprawne pole {k}")
                sets.append(f"{k}=?"), vals.append(b[k].strip()[:500])
        for k in ("price10", "stock"):
            if k in b:
                if not isinstance(b[k], (int, float)) or isinstance(b[k], bool) or b[k] < 0:
                    return err(f"Niepoprawne pole {k}")
                sets.append(f"{k}=?"), vals.append(b[k])
        for k, lim in (("lat", 90), ("lon", 180)):  # położenie do wschodu i zachodu słońca, null czyści
            if k in b:
                if b[k] is not None and (not num(b[k]) or not -lim <= b[k] <= lim):
                    return err(f"Niepoprawne pole {k}")
                sets.append(f"{k}=?"), vals.append(b[k])
        if sets:
            q(f"UPDATE farms SET {','.join(sets)} WHERE id=?", *vals, g.user["farm_id"])
            commit()
        f = q("SELECT * FROM farms WHERE id=?", g.user["farm_id"]).fetchone()
        return jsonify({**farm_json(f), "lat": f["lat"], "lon": f["lon"]})

    @app.get("/api/my/orders")
    @need("farmer")
    def my_orders():
        return jsonify([dict(r) for r in q("SELECT * FROM orders WHERE farm_id=? ORDER BY id DESC", g.user["farm_id"])])

    @app.post("/api/my/orders/<int:oid>/<action>")
    @need("farmer")
    def order_action(oid, action):
        if action not in ("confirm", "reject"):
            return err("Nieznana akcja", 404)
        o = q("SELECT * FROM orders WHERE id=? AND farm_id=?", oid, g.user["farm_id"]).fetchone()
        if not o:
            return err("Nie znaleziono", 404)
        if o["status"] != "pending":
            return err("Zamówienie zostało już rozpatrzone", 409)
        if action == "confirm":
            f = q("SELECT stock FROM farms WHERE id=?", o["farm_id"]).fetchone()
            if f["stock"] < o["qty"]:
                return err("Za mały stan magazynowy", 409)
            q("UPDATE farms SET stock=stock-? WHERE id=?", o["qty"], o["farm_id"])
        q("UPDATE orders SET status=? WHERE id=?", "confirmed" if action == "confirm" else "rejected", oid)
        commit()
        return jsonify(ok=True)

    @app.post("/api/my/device-orders")
    @need("farmer")
    def device_order():
        b = body()
        m = cat.MODELS.get(b.get("model")) if isinstance(b.get("model"), str) else None
        if not m:
            return err("Można zamówić tylko sterowniki z katalogu operatora")
        tunnel = b.get("tunnel") or m["tunnels"][0]
        if tunnel not in m["tunnels"]:
            return err("Ten model nie obsługuje wybranego połączenia")
        did = new_device(b["model"], g.user["farm_id"], tunnel, str(b.get("addr", "")))
        return jsonify(id=did), 201

    @app.get("/api/my/devices")
    @need("farmer")
    def my_devices():
        return jsonify([dev_json(d) for d in q("SELECT * FROM devices WHERE farm_id=?", g.user["farm_id"])])

    @app.patch("/api/my/devices/<int:did>")
    @need("farmer")
    def my_device_patch(did):
        d, b = own_device(did), body()
        if not d:
            return err("Nie znaleziono", 404)
        if "door_run_s" in b:
            if not integer(b["door_run_s"], 1, 300):
                return err("Czas pracy silnika drzwi od 1 do 300 s")
            q("UPDATE devices SET door_run_s=? WHERE id=?", b["door_run_s"], did)
            commit()
        return jsonify(dev_json(own_device(did)))

    @app.post("/api/my/devices/<int:did>/door")
    @need("farmer")
    def door_action(did):
        d, action = own_device(did), body().get("action")
        if not d:
            return err("Nie znaleziono", 404)
        if action not in ("open", "close"):
            return err("Akcja musi być open lub close")
        if not q("SELECT 1 FROM channels WHERE device_id=? AND kind=?", did, "door_" + action).fetchone():
            return err("Ten sterownik nie ma przekaźnika drzwi", 409)
        if d["stage"] < 3 or not d["online"]:
            return err("Urządzenie jest niedostępne", 409)
        ok, e = sv.door(app, d, action, "manual")
        return (jsonify(ok=True), 200) if ok else (jsonify(error=f"Urządzenie nie odpowiada: {e}"), 502)

    @app.get("/api/my/devices/<int:did>/log")
    @need("farmer")
    def device_log(did):
        lim = request.args.get("limit", "30")
        if not own_device(did):
            return err("Nie znaleziono", 404)
        if not lim.isdigit() or not 1 <= int(lim) <= 200:
            return err("Parametr limit od 1 do 200")
        rows = q("SELECT l.*, c.name, c.kind FROM log l LEFT JOIN channels c ON c.device_id=l.device_id AND c.key=l.ch "
                 "WHERE l.device_id=? ORDER BY l.id DESC LIMIT ?", did, int(lim))
        return jsonify([dict(id=r["id"], at=r["at"], ch=r["ch"], ch_name=r["name"] or r["ch"], kind=r["kind"],
                             state=bool(r["state"]), src=r["src"], ok=bool(r["ok"])) for r in rows])

    @app.get("/api/my/devices/<int:did>/readings")
    @need("farmer")
    def device_history(did):
        hours = request.args.get("hours", "24")
        if not own_device(did):
            return err("Nie znaleziono", 404)
        if not hours.isdigit() or not 1 <= int(hours) <= 168:
            return err("Parametr hours od 1 do 168")
        since = (datetime.now() - timedelta(hours=int(hours))).isoformat()
        rows = q("SELECT t,h,at FROM readings WHERE device_id=? AND at>=? ORDER BY at", did, since).fetchall()
        step = max(1, len(rows) // 288)  # do wykresu wystarczy ok. 300 punktów
        return jsonify([dict(r) for r in rows[::step] + (rows[-1:] if (len(rows) - 1) % step else [])])

    @app.get("/api/my/devices/<int:did>/yaml")
    @need("farmer")
    def my_yaml(did):
        d = own_device(did)
        if not d:
            return err("Nie znaleziono", 404)
        if d["stage"] < 1:
            return err("Konfiguracja nie jest jeszcze gotowa", 409)
        ch = [dict(c) for c in q("SELECT * FROM channels WHERE device_id=? ORDER BY id", did)]
        return sv.esphome_yaml(d, ch, dbm.get()), 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/api/my/devices/<int:did>/channels/<key>", methods=["POST", "PATCH"])
    @need("farmer")
    def channel(did, key):
        d = own_device(did)
        c = q("SELECT * FROM channels WHERE device_id=? AND key=?", did, key).fetchone() if d else None
        if not c:
            return err("Nie znaleziono", 404)
        b = body()
        if request.method == "PATCH":
            name, kind = b.get("name", c["name"]), b.get("kind", c["kind"])
            if not isinstance(name, str) or not name.strip() or kind not in cat.KINDS:
                return err("Niepoprawna nazwa lub rodzaj")
            q("UPDATE channels SET name=?,kind=?,want=NULL WHERE id=?", name.strip()[:60], kind, c["id"])
            commit()
            return jsonify(ok=True)
        if not isinstance(b.get("state"), bool):
            return err("Pole state musi być true lub false")
        if d["stage"] < 3 or not d["online"]:
            return err("Urządzenie jest niedostępne", 409)
        pair = {"door_open": "door_close", "door_close": "door_open"}.get(c["kind"])
        if pair and b["state"] and q("SELECT 1 FROM channels WHERE device_id=? AND kind=? AND state=1", did, pair).fetchone():
            return err("Blokada: przekaźniki drzwi nie mogą działać jednocześnie", 409)
        kw = {"off_at": datetime.now() + timedelta(seconds=d["door_run_s"])} if pair and b["state"] else {}
        ok, e = sv.command(app, d, c, b["state"], "manual", **kw)
        if ok and kw:  # przekaźnik drzwi zawsze jako impuls, wyłączy go silnik
            q("UPDATE devices SET door=? WHERE id=?", "open" if c["kind"] == "door_open" else "closed", did)
            commit()
        return (jsonify(ok=True), 200) if ok else (jsonify(error=f"Urządzenie nie odpowiada: {e}"), 502)

    def farm_sun():
        f = q("SELECT lat, lon FROM farms WHERE id=?", g.user["farm_id"]).fetchone()
        return sv.farm_sun(f["lat"], f["lon"])

    def sched_json(r, sun):
        w = sv.window(r, datetime.now().date(), sun)
        hm = lambda x: f"{x // 3600 % 24:02d}:{x // 60 % 60:02d}"
        return dict(r, enabled=bool(r["enabled"]), today_on=w and hm(w[0]), today_off=w and hm(w[1]))

    def sched_check(did, s, sun):
        """Waliduje pełny harmonogram (po scaleniu zmian z zapisanym). Zwraca komunikat błędu albo None."""
        c = q("SELECT kind FROM channels WHERE device_id=? AND key=?", did, s["ch"]).fetchone() \
            if isinstance(s["ch"], str) else None
        if not c:
            return "Nieznany kanał"
        if c["kind"] == "door_close":
            return "Harmonogram drzwi ustaw na kanale otwierania drzwi"
        if s["days"] not in DAYS:
            return "Niepoprawne dni"
        if s["mode"] not in sv.MODES or s["off_mode"] not in sv.MODES:
            return "Niepoprawny rodzaj harmonogramu (time, sunrise, sunset)"
        if not isinstance(s["enabled"], (bool, int)):
            return "Pole enabled musi być true lub false"
        if not (integer(s["offset_min"], -180, 180) and integer(s["off_offset_min"], -180, 180)):
            return "Przesunięcie od -180 do 180 minut"
        if s["mode"] == "time" and not sv.valid_hm(s["t_on"]):
            return "Niepoprawna godzina włączenia (GG:MM)"
        if s["duration_s"] is not None:
            if c["kind"] == "door_open":
                return "Drzwi mają porę otwarcia i zamknięcia, bez czasu trwania"
            if not integer(s["duration_s"], 1, 43200):
                return "Czas działania od 1 s do 12 h"
        elif s["off_mode"] == "time" and not sv.valid_hm(s["t_off"]):
            return "Niepoprawna godzina wyłączenia (GG:MM)"
        elif s["mode"] == s["off_mode"] == "time" and s["t_on"] == s["t_off"]:
            return "Początek i koniec nie mogą być takie same"
        uses_sun = s["mode"] != "time" or (s["duration_s"] is None and s["off_mode"] != "time")
        if uses_sun and not sun:
            return "Ustaw położenie gospodarstwa w Ofercie, aby użyć wschodu i zachodu słońca"
        return None

    SCHED = dict(ch=None, mode="time", t_on="", offset_min=0, off_mode="time", t_off="", off_offset_min=0,
                 duration_s=None, days="a", enabled=True)

    def reevaluate(did, *keys):
        """Po zmianie harmonogramu lub termostatu silnik ocenia kanał od nowa przy najbliższym obiegu."""
        q(f"UPDATE channels SET want=NULL WHERE device_id=? AND key IN ({','.join('?' * len(keys))})", did, *keys)
        q("UPDATE devices SET door_want=NULL WHERE id=?", did)

    def sched_save(did, sid, b, old):
        if "enabled" in b and not isinstance(b["enabled"], bool):
            return err("Pole enabled musi być true lub false")
        s = {**SCHED, **{k: old[k] for k in SCHED if old}, **{k: b[k] for k in SCHED if k in b}}
        sun = farm_sun()
        msg = sched_check(did, s, sun)
        if msg:
            return err(msg)
        vals = [s["ch"], s["mode"], s["t_on"] if sv.valid_hm(s["t_on"]) else "", s["offset_min"] if s["mode"] != "time" else 0,
                s["off_mode"], s["t_off"] if s["duration_s"] is None and sv.valid_hm(s["t_off"]) else "",
                s["off_offset_min"] if s["off_mode"] != "time" else 0, s["duration_s"], s["days"], int(bool(s["enabled"]))]
        cols = "ch,mode,t_on,offset_min,off_mode,t_off,off_offset_min,duration_s,days,enabled"
        if sid:
            q(f"UPDATE schedules SET {','.join(c + '=?' for c in cols.split(','))} WHERE id=?", *vals, sid)
        else:
            sid = q(f"INSERT INTO schedules(device_id,{cols}) VALUES(?,{','.join('?' * len(vals))})", did, *vals).lastrowid
        reevaluate(did, s["ch"], *([old["ch"]] if old else []))
        commit()
        return jsonify(sched_json(q("SELECT * FROM schedules WHERE id=?", sid).fetchone(), sun)), 200 if old else 201

    @app.route("/api/my/devices/<int:did>/schedules", methods=["GET", "POST"])
    @need("farmer")
    def schedules(did):
        if not own_device(did):
            return err("Nie znaleziono", 404)
        if request.method == "GET":
            sun = farm_sun()
            return jsonify([sched_json(r, sun) for r in q("SELECT * FROM schedules WHERE device_id=? ORDER BY id", did)])
        return sched_save(did, None, body(), None)

    @app.patch("/api/my/devices/<int:did>/schedules/<int:sid>")
    @need("farmer")
    def patch_schedule(did, sid):
        old = q("SELECT * FROM schedules WHERE id=? AND device_id=?", sid, did).fetchone() if own_device(did) else None
        if not old:
            return err("Nie znaleziono", 404)
        return sched_save(did, sid, body(), old)

    @app.delete("/api/my/devices/<int:did>/schedules/<int:sid>")
    @need("farmer")
    def del_schedule(did, sid):
        if not own_device(did):
            return err("Nie znaleziono", 404)
        old = q("SELECT ch FROM schedules WHERE id=? AND device_id=?", sid, did).fetchone()
        n = q("DELETE FROM schedules WHERE id=? AND device_id=?", sid, did).rowcount
        if n:
            reevaluate(did, old["ch"])
        commit()
        return jsonify(ok=True) if n else err("Nie znaleziono", 404)

    @app.put("/api/my/devices/<int:did>/rules/<key>")
    @need("farmer")
    def rule(did, key):
        d = own_device(did)
        c = q("SELECT kind FROM channels WHERE device_id=? AND key=?", did, key).fetchone() if d else None
        if not c:
            return err("Nie znaleziono", 404)
        b = body()
        if c["kind"] not in cat.COOL | cat.HEAT:
            return err("Termostat dostępny tylko dla wentylacji i grzania")
        if not isinstance(b.get("threshold"), (int, float)) or isinstance(b.get("threshold"), bool) or not -20 <= b["threshold"] <= 60:
            return err("Próg temperatury od -20 do 60 °C")
        if not isinstance(b.get("enabled", True), bool):
            return err("Pole enabled musi być true lub false")
        q("INSERT INTO rules(device_id,ch,threshold,enabled) VALUES(?,?,?,?) ON CONFLICT(device_id,ch) "
          "DO UPDATE SET threshold=excluded.threshold, enabled=excluded.enabled", did, key, b["threshold"], int(bool(b.get("enabled", True))))
        reevaluate(did, key)
        commit()
        return jsonify(ok=True)

    # ---------- urządzenie ----------
    @app.post("/api/device/readings")
    def device_readings():
        key = request.headers.get("X-Api-Key", "")
        d = q("SELECT * FROM devices WHERE api_key=?", key).fetchone() if key else None
        if not d:
            return err("Brak autoryzacji urządzenia", 401)
        b = body()
        t, h = b.get("t"), b.get("h")
        for v, lo, hi in ((t, -40, 80), (h, 0, 100)):
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi):
                return err("Odczyt poza zakresem")
        now = datetime.now().isoformat()
        q("INSERT INTO readings(device_id,t,h,at) VALUES(?,?,?,?)", d["id"], t, h, now)
        q("UPDATE devices SET online=1,last_seen=? WHERE id=?", now, d["id"])
        commit()
        return jsonify(ok=True)

    # ---------- admin ----------
    @app.get("/api/admin/devices")
    @need("admin")
    def admin_devices():
        return jsonify([dev_json(d, True) for d in q("SELECT * FROM devices ORDER BY id")])

    @app.post("/api/admin/devices")
    @need("admin")
    def admin_add_device():
        b = body()
        m = cat.MODELS.get(b.get("model")) if isinstance(b.get("model"), str) else None
        if not m or not q("SELECT 1 FROM farms WHERE id=?", b.get("farm_id")).fetchone():
            return err("Niepoprawny model lub farma")
        tunnel = b.get("tunnel") or m["tunnels"][0]
        if tunnel not in m["tunnels"]:
            return err("Ten model nie obsługuje wybranego połączenia")
        return jsonify(id=new_device(b["model"], b["farm_id"], tunnel, str(b.get("addr", "")))), 201

    @app.patch("/api/admin/devices/<int:did>")
    @need("admin")
    def admin_patch_device(did):
        d, b = q("SELECT * FROM devices WHERE id=?", did).fetchone(), body()
        if not d:
            return err("Nie znaleziono", 404)
        if "farm_id" in b:
            if not q("SELECT 1 FROM farms WHERE id=?", b["farm_id"]).fetchone():
                return err("Nie ma takiej farmy")
            q("UPDATE devices SET farm_id=? WHERE id=?", b["farm_id"], did)
        if "stage" in b:
            if b["stage"] not in (d["stage"], d["stage"] + 1) or b["stage"] > 3:
                return err("Etap można tylko zwiększać o jeden (maks. 3)")
            q("UPDATE devices SET stage=? WHERE id=?", b["stage"], did)
        commit()
        return jsonify(dev_json(q("SELECT * FROM devices WHERE id=?", did).fetchone(), True))

    @app.route("/api/admin/config", methods=["GET", "PUT"])
    @need("admin")
    def admin_config():
        if request.method == "PUT":
            b = body()
            checks = {"wg_endpoint": r"[A-Za-z0-9.-]{1,100}", "wg_port": r"[0-9]{2,5}", "net": r"\d{1,3}\.\d{1,3}\.\d{1,3}"}
            for k, v in b.items():
                if k not in checks or not re.fullmatch(checks[k], str(v)):
                    return err(f"Niepoprawne pole {k}")
                q("INSERT INTO config(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", k, str(v))
            commit()
        return jsonify({k: sv.cfg(dbm.get(), k) for k in sv.DEFAULTS})

    @app.post("/api/admin/tick")
    @need("admin")
    def admin_tick():
        return jsonify(sent=sv.tick(app))

    @app.cli.command("create-admin")
    def create_admin():
        import click
        email = click.prompt("E-mail")
        pw = click.prompt("Hasło (min. 8 znaków)", hide_input=True)
        if len(pw) < 8:
            raise click.ClickException("Hasło za krótkie")
        q("INSERT INTO users(email,pw,role) VALUES(?,?,?)", email.lower(), generate_password_hash(pw), "admin")
        commit()
        click.echo("Utworzono administratora")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Dane demonstracyjne do testów funkcjonalnych (hasła w README)."""
        import click
        if q("SELECT 1 FROM users").fetchone():
            raise click.ClickException("Baza ma już użytkowników. Użyj pustej bazy.")
        q("INSERT INTO users(email,pw,role) VALUES(?,?,?)", "admin@zniesione.test", generate_password_hash("Admin12345!"), "admin")
        for i, (n, c, z, b, p, s, d) in enumerate([
                ("Kurnik pod Lipą", "Dąbrowa", "45-120", "Ekologiczny", 14, 12, "Jaja z wolnego wybiegu, kury karmione własnym zbożem."),
                ("Ekoferma Wierzba", "Brzezie", "45-300", "Wolny wybieg", 12, 30, "Sprzedaż w soboty."),
                ("Gospodarstwo Sowa", "Lipowa", "46-010", "Ściółkowy", 10, 8, "")], 1):
            fid = q("INSERT INTO farms(name,city,zip,breed,price10,stock,descr) VALUES(?,?,?,?,?,?,?)", n, c, z, b, p, s, d).lastrowid
            q("INSERT INTO users(email,pw,role,farm_id) VALUES(?,?,?,?)", "rolnik@zniesione.test" if i == 1 else f"rolnik{i}@zniesione.test",
              generate_password_hash("Rolnik12345!"), "farmer", fid)
        did = new_device("trs3", 1, "wg", "kurnik 1")
        q("UPDATE devices SET stage=3,online=1,last_seen=? WHERE id=?", datetime.now().isoformat(), did)
        q("INSERT INTO readings(device_id,t,h,at) VALUES(?,?,?,?)", did, 21.5, 58, datetime.now().isoformat())
        for k, n, kind in (("ch4", "Wentylator", "vent"), ("ch5", "Ogrzewanie", "heater"), ("ch6", "Grzałka wody", "water_heater")):
            q("UPDATE channels SET name=?,kind=? WHERE device_id=? AND key=?", n, kind, did, k)
        commit()
        click.echo("Gotowe: admin@zniesione.test / Admin12345!  rolnik@zniesione.test / Rolnik12345!")

    if app.config["RUN_SCHEDULER"]:
        def loop():
            ev = threading.Event()
            while not ev.wait(app.config["TICK_S"]):  # krótki obieg: impulsy drzwi trwają sekundy
                try:
                    sv.tick(app)
                except Exception:  # noqa: BLE001
                    app.logger.exception("tick failed")
        threading.Thread(target=loop, daemon=True, name="scheduler").start()
    return app
