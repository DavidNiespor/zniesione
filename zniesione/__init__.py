import hashlib
import json
import math
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

import click
from flask import Flask, g, jsonify, request, send_from_directory, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from . import catalog as cat
from . import db as dbm
from . import clients
from . import ekurnik
from . import farmbook
from . import feed
from . import team
from . import services as sv

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
MODES, PICKUPS, DAYS = ("once", "weekly", "biweekly"), ("pickup", "delivery"), ("a", "w", "e")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
KB_DEMO = [
    ("Pierwsze uruchomienie sterownika", "Sterowniki", """Sterownik przychodzi przygotowany do pracy. Wystarczy go podłączyć.

## Krok po kroku
1. Podłącz zasilanie sterownika (zasilacz z zestawu).
2. Połącz sterownik z internetem: Wi-Fi w kurniku albo kabel sieciowy (Waveshare).
3. Odczekaj 2–3 minuty. W portalu przy sterowniku pojawi się **Połączony**.
4. Wejdź w **Sterowanie** i sprawdź, czy przełącznik światła włącza lampę.

## Co jest do czego podłączone
W **Sterowanie → Przypisanie przekaźników** ustawisz, co jest podłączone do każdego przekaźnika:
światło, drzwi, wentylator, grzałka, pompa i inne.

> Jeśli po 10 minutach nadal widzisz *Brak połączenia*, sprawdź zasilanie i zasięg Wi-Fi w kurniku."""),
    ("Światło od wschodu słońca", "Harmonogramy", """Kury znoszą więcej jaj, gdy dzień trwa około 14–16 godzin.
Zimą możesz wydłużyć poranek lampą.

## Przykład: światło od wschodu −30 min do 07:00
1. Wejdź w **Sterowanie → Harmonogramy**.
2. Czym sterować: **Światło**.
3. Kiedy włączyć: **Względem wschodu słońca**, przesunięcie **-30**.
4. Kiedy wyłączyć: **O godzinie**, **07:00**.
5. Kliknij **Dodaj harmonogram**.

Godzina wschodu zmienia się każdego dnia, portal liczy ją sam. Potrzebuje tylko położenia gospodarstwa
(**Więcej → Oferta → Położenie gospodarstwa**).

Gdy wschód słońca wypada później niż godzina wyłączenia, światło tego dnia się nie włącza."""),
    ("Drzwi kurnika: czas pracy silnika", "Drzwi", """Drzwi otwiera i zamyka silnik. Sterownik włącza go na ustalony czas, potem sam wyłącza.

- Zmierz stoperem, ile trwa pełne otwarcie drzwi, i dodaj 2–3 sekundy.
- Wpisz ten czas w **Sterowanie → Czas pracy silnika drzwi**.
- Po zmianie czasu wgraj ponownie **Konfigurację ESPHome**: ten sam czas jest zapisany w sterowniku jako zabezpieczenie,
  gdy kurnik straci internet.

Przekaźniki otwierania i zamykania nigdy nie działają jednocześnie."""),
    ("Zimowe pojenie (szkic)", "Porady", "Artykuł w przygotowaniu: grzałka wody i termostat poniżej 2 °C.", 0),
]
KB_DEMO = [a if len(a) == 4 else (*a, 1) for a in KB_DEMO]


def err(msg, code=400):
    return jsonify(error=msg), code


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def integer(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def valid_date(s):
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)) and datetime.strptime(s, "%Y-%m-%d") is not None
    except ValueError:
        return False


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
                      PROXY_COUNT=int(os.environ.get("PROXY_COUNT") or 0),
                      REAL_IP_HEADER=os.environ.get("REAL_IP_HEADER", ""),
                      WG_CONF=os.environ.get("WG_CONF", ""),
                      ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", ""), ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
                      SMTP_HOST=os.environ.get("SMTP_HOST", ""), SMTP_PORT=os.environ.get("SMTP_PORT", "587"),
                      SMTP_USER=os.environ.get("SMTP_USER", ""), SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
                      MAIL_FROM=os.environ.get("MAIL_FROM", ""), MAIL=farmbook.send_mail,
                      BUILDER_URL=os.environ.get("BUILDER_URL", ""), BUILDER_TOKEN=os.environ.get("BUILDER_TOKEN", ""),
                      BUILDER_CALL=sv.builder_call, MAX_CONTENT_LENGTH=64 * 1024 * 1024,
                      SEND=sv.send_http, RUN_SCHEDULER=os.environ.get("RUN_SCHEDULER") == "1")
    app.config.update(test_config or {})
    if app.config["PROXY_COUNT"]:  # za odwrotnym proxy lub Cloudflare Tunnel: adres klienta z X-Forwarded-For
        n = app.config["PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n)
    dbm.init_app(app)
    if app.config["ADMIN_EMAIL"] and app.config["ADMIN_PASSWORD"]:  # pierwsze konto admina ze zmiennych stacka
        email = app.config["ADMIN_EMAIL"].strip().lower()
        if len(app.config["ADMIN_PASSWORD"]) < 8:
            raise RuntimeError("ADMIN_PASSWORD musi mieć co najmniej 8 znaków")
        with app.app_context():
            db = dbm.get()
            if not db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():  # istniejącego nie nadpisujemy
                db.execute("INSERT INTO users(email,pw,role) VALUES(?,?,'admin')", (email, generate_password_hash(app.config["ADMIN_PASSWORD"])))
                db.commit()
                app.logger.warning("Utworzono konto administratora %s", email)
    if app.config["WG_CONF"]:  # przy starcie: kontener wireguard czeka na ten plik
        with app.app_context():
            sv.write_wg_conf(dbm.get(), app.config["WG_CONF"])
    with app.app_context():
        clients.backfill(dbm.get())
    fails, fails_lock = {}, threading.Lock()  # nieudane logowania: klucz -> czasy prób (pamięć procesu)

    def q(sql, *a):
        return dbm.get().execute(sql, a)

    def commit():
        dbm.get().commit()

    def body():
        b = request.get_json(silent=True)
        return b if isinstance(b, dict) else {}

    def client_ip():
        # REAL_IP_HEADER (np. CF-Connecting-IP) tylko wtedy, gdy aplikacja jest osiągalna wyłącznie przez Cloudflare
        h = app.config["REAL_IP_HEADER"]
        return (request.headers.get(h) if h else None) or request.remote_addr

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
                dbm.set_user(dbm.get(), u["id"])
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
                    **({"api_key": d["api_key"], "sensor": d["sensor"], "sensor_pins": json.loads(d["sensor_pins"] or "{}"),
                        "wifi_ssid": d["wifi_ssid"], "wifi_set": bool(d["wifi_password"]), "fw_job": d["fw_job"],
                        "chip": "ESP32-S3" if "s3" in cat.MODELS[d["model"]].get("board", "") else "ESP32",
                        "firmware": not cat.MODELS[d["model"]].get("shelly") and not cat.MODELS[d["model"]].get("eth")} if admin else {}))

    def new_device(model, farm_id, tunnel, addr):
        code = "kurnik-" + secrets.token_hex(2)
        did = q("INSERT INTO devices(code,model,farm_id,tunnel,ip,api_key,addr) VALUES(?,?,?,?,?,?,?)",
                code, model, farm_id, tunnel, sv.alloc_ip(dbm.get()), secrets.token_urlsafe(24), addr[:200]).lastrowid
        for k, n, kind in cat.default_channels(model):
            q("INSERT INTO channels(device_id,key,name,kind) VALUES(?,?,?,?)", did, k, n, kind)
        commit()
        wg_sync()
        return did

    def wg_sync():
        if app.config["WG_CONF"]:  # serwer WireGuard w stacku: nowy sterownik trafia do wg0.conf od razu
            sv.write_wg_conf(dbm.get(), app.config["WG_CONF"])

    # ---------- publiczne ----------
    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    static = os.path.join(app.root_path, "static")
    with open(os.path.join(static, "app.html"), encoding="utf-8") as f:
        page = f.read()
    ver = hashlib.sha256(b"".join(open(os.path.join(static, n), "rb").read() for n in ("app.js", "app.css"))).hexdigest()[:10]
    page = page.replace("?v=2", "?v=" + ver)  # nowa wersja plików = nowy adres, więc cache Cloudflare nie poda starych

    @app.get("/")
    def index():
        return page, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"}

    @app.get("/sw.js")
    def service_worker():  # z katalogu głównego, żeby obejmował całą aplikację
        r = send_from_directory(static, "sw.js", mimetype="text/javascript", max_age=0)
        r.headers["Cache-Control"] = "no-cache"
        return r

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
        oid = q("INSERT INTO orders(farm_id,name,phone,qty,mode,pickup,total,created,client_id) VALUES(?,?,?,?,?,?,?,?,?)",
                fid, name, phone, qty, mode, pickup, qty * f["price10"], datetime.now().isoformat(),
                clients.ensure_client(dbm.get(), fid, name, phone)).lastrowid  # klient trafia do kartoteki rolnika
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
        keys = [(("email", email), app.config["LOGIN_MAX_EMAIL"]), (("ip", client_ip()), app.config["LOGIN_MAX_IP"])]
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
        return jsonify(id=g.user["id"], email=g.user["email"], role=g.user["role"], farm_id=g.user["farm_id"],
                       name=g.user["name"] or g.user["email"].split("@")[0], owner=bool(g.user["owner"]))

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
        sub = farmbook.subscription_from_order(dbm.get(), o) if action == "confirm" else None
        commit()
        return jsonify(ok=True, subscription_id=sub)

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

    clients.register(app, need, q, commit, body, err, integer)

    # ---------- stado i jaja ----------
    FLOCK = dict(name="", birds=0, breed="", since="", notes="")

    def flock_save(b, old):
        f = {**FLOCK, **({k: old[k] for k in FLOCK} if old else {}), **{k: b[k] for k in FLOCK if k in b}}
        if not isinstance(f["name"], str) or not f["name"].strip() or len(f["name"]) > 60:
            return err("Podaj nazwę stada (do 60 znaków)")
        if not integer(f["birds"], 0, 100000):
            return err("Liczba kur od 0 do 100 000")
        for k, n in (("breed", 60), ("notes", 1000)):
            if not isinstance(f[k], str) or len(f[k]) > n:
                return err(f"Pole {k} może mieć do {n} znaków")
        if not isinstance(f["since"], str) or (f["since"] and not valid_date(f["since"])):
            return err("Data w formacie RRRR-MM-DD")
        vals = [f["name"].strip(), f["birds"], f["breed"].strip(), f["since"], f["notes"].strip()]
        if old:
            q("UPDATE flocks SET name=?,birds=?,breed=?,since=?,notes=? WHERE id=?", *vals, old["id"])
            fid = old["id"]
        else:
            fid = q("INSERT INTO flocks(farm_id,name,birds,breed,since,notes) VALUES(?,?,?,?,?,?)", g.user["farm_id"], *vals).lastrowid
        commit()
        return jsonify(dict(q("SELECT * FROM flocks WHERE id=?", fid).fetchone())), 200 if old else 201

    @app.route("/api/my/flocks", methods=["GET", "POST"])
    @need("farmer")
    def flocks():
        if request.method == "POST":
            return flock_save(body(), None)
        return jsonify([dict(r) for r in q("SELECT * FROM flocks WHERE farm_id=? ORDER BY id", g.user["farm_id"])])

    @app.route("/api/my/flocks/<int:fid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def flock(fid):
        old = q("SELECT * FROM flocks WHERE id=? AND farm_id=?", fid, g.user["farm_id"]).fetchone()
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "PATCH":
            return flock_save(body(), old)
        q("DELETE FROM flocks WHERE id=?", fid)
        commit()
        return jsonify(ok=True)

    farmbook.register(app, need, q, commit, body, err, integer)
    feed.register(app, need, q, commit, body, err)
    team.register(app, need, q, commit, body, err)

    # ---------- baza wiedzy ----------
    def kb_json(r, full=True):
        out = dict(id=r["id"], title=r["title"], category=r["category"], published=bool(r["published"]),
                   created=r["created"], updated=r["updated"])
        if full:
            out["body"] = r["body"]
        else:
            out["excerpt"] = " ".join(re.sub(r"[#*`>\[\]!_|-]+|\(https?://\S+?\)", " ", r["body"]).split())[:180]
        return out

    def kb_visible(r):
        return r and (r["published"] or g.user["role"] == "admin")

    @app.get("/api/kb")
    @need()
    def kb_list():
        s, c = request.args.get("q", "").strip().casefold(), request.args.get("category", "")
        rows = [r for r in q("SELECT * FROM kb ORDER BY updated DESC") if kb_visible(r) and (not c or r["category"] == c)
                and (not s or s in f"{r['title']} {r['category']} {r['body']}".casefold())]
        return jsonify([kb_json(r, False) for r in rows])

    @app.get("/api/kb/<int:aid>")
    @need()
    def kb_get(aid):
        r = q("SELECT * FROM kb WHERE id=?", aid).fetchone()
        return jsonify(kb_json(r)) if kb_visible(r) else err("Nie znaleziono", 404)

    def kb_save(b, old):
        a = {**({k: old[k] for k in ("title", "category", "body")} if old else {"title": "", "category": "", "body": ""}),
             "published": bool(old["published"]) if old else False,
             **{k: b[k] for k in ("title", "category", "body", "published") if k in b}}
        if not isinstance(a["title"], str) or not 3 <= len(a["title"].strip()) <= 150:
            return err("Tytuł od 3 do 150 znaków")
        if not isinstance(a["category"], str) or len(a["category"].strip()) > 60:
            return err("Kategoria do 60 znaków")
        if not isinstance(a["body"], str) or not a["body"].strip() or len(a["body"]) > 50000:
            return err("Treść artykułu jest wymagana (do 50 000 znaków)")
        if not isinstance(a["published"], bool):
            return err("Pole published musi być true lub false")
        now = datetime.now().isoformat(timespec="seconds")
        vals = [a["title"].strip(), a["category"].strip(), a["body"], int(a["published"]), now]
        if old:
            q("UPDATE kb SET title=?,category=?,body=?,published=?,updated=? WHERE id=?", *vals, old["id"])
            aid = old["id"]
        else:
            aid = q("INSERT INTO kb(title,category,body,published,updated,created) VALUES(?,?,?,?,?,?)", *vals, now).lastrowid
        commit()
        return jsonify(kb_json(q("SELECT * FROM kb WHERE id=?", aid).fetchone())), 200 if old else 201

    @app.post("/api/admin/kb")
    @need("admin")
    def kb_add():
        return kb_save(body(), None)

    @app.route("/api/admin/kb/<int:aid>", methods=["PUT", "DELETE"])
    @need("admin")
    def kb_edit(aid):
        old = q("SELECT * FROM kb WHERE id=?", aid).fetchone()
        if not old:
            return err("Nie znaleziono", 404)
        if request.method == "PUT":
            return kb_save(body(), old)
        q("DELETE FROM kb WHERE id=?", aid)
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
        if "sensor" in b:  # czujnik w firmware: rodzaj i piny (nie piny przekaźników)
            kind, pins = b["sensor"], b.get("sensor_pins") or {}
            need_pins = {"": (), "sht3x": ("sda", "scl"), "dht22": ("pin",), "ds18b20": ("pin",)}.get(kind) if isinstance(kind, str) else None
            if need_pins is None:
                return err("Czujnik: brak, sht3x, dht22 albo ds18b20")
            m = cat.MODELS[d["model"]]
            busy = set(m.get("relays", [])) | set((m.get("sr") or {}).values())
            if not isinstance(pins, dict) or any(not integer(pins.get(k), 0, 48) or pins[k] in busy for k in need_pins) \
                    or len({pins[k] for k in need_pins}) != len(need_pins):
                return err(f"Podaj różne piny GPIO 0-48 dla: {', '.join(need_pins)} (bez pinów przekaźników: {sorted(busy)})")
            q("UPDATE devices SET sensor=?, sensor_pins=? WHERE id=?", kind, json.dumps({k: pins[k] for k in need_pins}), did)
        for k, n in (("wifi_ssid", 32), ("wifi_password", 63)):
            if k in b:
                if not isinstance(b[k], str) or len(b[k]) > n:
                    return err(f"Pole {k} do {n} znaków")
                q(f"UPDATE devices SET {k}=? WHERE id=?", b[k], did)
        commit()
        return jsonify(dev_json(q("SELECT * FROM devices WHERE id=?", did).fetchone(), True))

    # ---------- import z e-kurnika z panelu admina ----------
    def uploads_dir():
        d = os.path.join(os.path.dirname(os.path.abspath(app.config["DATABASE"])), "uploads")
        os.makedirs(d, exist_ok=True)
        return d

    @app.post("/api/admin/ekurnik/upload")
    @need("admin")
    def ekurnik_upload():
        f = request.files.get("file")
        if not f:
            return err("Wybierz plik kopii bazy e-kurnika (.db)")
        token = secrets.token_hex(8)
        path = os.path.join(uploads_dir(), token + ".db")
        f.save(path)
        import sqlite3 as _sq
        src = _sq.connect(f"file:{path}?mode=ro", uri=True)
        try:
            farms = [dict(gid=r[0], name=r[1], clients=r[2], days=r[3]) for r in ekurnik.farms_summary(src)]
        except _sq.DatabaseError:  # to nie jest baza e-kurnika
            farms = None
        finally:
            src.close()  # na Windows otwarty plik nie dałby się usunąć
        if farms is None:
            os.remove(path)
            return err("To nie jest kopia bazy e-kurnika (brak tabeli gospodarstw)")
        return jsonify(token=token, farms=farms), 201

    @app.post("/api/admin/ekurnik/import")
    @need("admin")
    def ekurnik_import():
        b = body()
        token, email, gid = b.get("token"), str(b.get("email", "")).strip().lower(), b.get("gid")
        path = os.path.join(uploads_dir(), f"{token}.db") if isinstance(token, str) and re.fullmatch(r"[0-9a-f]{16}", token) else ""
        if not path or not os.path.exists(path):
            return err("Najpierw wgraj plik kopii (albo wgraj go ponownie)", 404)
        if not integer(gid, 1, 10 ** 9) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return err("Wybierz gospodarstwo i podaj e-mail konta rolnika")
        u = q("SELECT * FROM users WHERE email=?", email).fetchone()
        if u and u["role"] != "farmer":
            return err("To konto nie jest kontem rolnika")
        created = False
        if not u:  # nowe konto rolnika z farmą nazwaną jak gospodarstwo w e-kurniku
            pw = b.get("password", "")
            if not isinstance(pw, str) or len(pw) < 8:
                return err("Konta nie ma: podaj hasło (min. 8 znaków), żeby je założyć")
            import sqlite3 as _sq
            src = _sq.connect(f"file:{path}?mode=ro", uri=True)
            row = src.execute("SELECT nazwa FROM gospodarstwa WHERE id=?", (gid,)).fetchone()
            src.close()
            if not row:
                return err(f"W kopii nie ma gospodarstwa {gid}")
            fid = q("INSERT INTO farms(name) VALUES(?)", (str(b.get("farm_name") or row[0] or "Gospodarstwo")).strip()[:100]).lastrowid
            q("INSERT INTO users(email,pw,role,farm_id) VALUES(?,?,?,?)", email, generate_password_hash(pw), "farmer", fid)
            commit()
            u, created = q("SELECT * FROM users WHERE email=?", email).fetchone(), True
        try:
            n = ekurnik.import_ekurnik(dbm.get(), path, u["farm_id"], gid)
        except ValueError as e:
            return err(str(e), 409)
        os.remove(path)
        return jsonify(created=created, email=email, counts=n)

    # ---------- firmware ESPHome: kompilacja i wgrywanie z panelu admina (kontener esphome w stacku) ----------
    def fw_device(did):
        d = q("SELECT * FROM devices WHERE id=?", did).fetchone()
        if not d:
            return None, err("Nie znaleziono", 404)
        m = cat.MODELS[d["model"]]
        if m.get("shelly") or m.get("eth"):
            return None, err("Ten model nie jest budowany z portalu (Shelly: własny firmware; Waveshare: uzupełnij piny Ethernet)", 409)
        if not app.config["BUILDER_URL"]:
            return None, err("Budowanie firmware nie jest skonfigurowane (BUILDER_URL)", 503)
        return d, None

    @app.route("/api/admin/devices/<int:did>/firmware", methods=["GET", "POST"])
    @need("admin")
    def firmware(did):
        d, e = fw_device(did)
        if e:
            return e
        if request.method == "GET":
            if not d["fw_job"]:
                return jsonify(status="none")
            code, data = app.config["BUILDER_CALL"](app.config, "GET", f"/jobs/{d['fw_job']}")
            return jsonify(data) if code == 200 else err("Builder nie zna tego zadania (np. po restarcie). Skompiluj ponownie.", 404)
        action = body().get("action")
        if action not in ("compile", "upload"):
            return err("Akcja: compile (kompilacja do wgrania przez USB) albo upload (kompilacja i wgranie przez sieć)")
        if not d["wifi_ssid"] or not d["wifi_password"]:
            return err("Najpierw wpisz sieć Wi-Fi kurnika (nazwa i hasło)", 409)
        if action == "upload" and (d["tunnel"] != "wg" or not d["online"]):
            return err("Wgranie przez sieć działa dla sterownika połączonego przez WireGuard. Pierwszy raz wgraj przez USB.", 409)
        d = sv.device_keys(dbm.get(), d)
        ch = [dict(c) for c in q("SELECT * FROM channels WHERE device_id=? ORDER BY id", did)]
        code, data = app.config["BUILDER_CALL"](app.config, "POST", "/jobs", {
            "name": d["code"], "action": action, "ip": d["ip"], "yaml": sv.esphome_yaml(d, ch, dbm.get()),
            "secrets": sv.esphome_secrets(d, dbm.get())})
        if code != 201:
            return err(f"Builder odrzucił zadanie: {data.get('error') if isinstance(data, dict) else data}", 502)
        q("UPDATE devices SET fw_job=? WHERE id=?", data["id"], did)
        commit()
        return jsonify(id=data["id"], status="queued"), 201

    @app.get("/api/admin/devices/<int:did>/firmware.bin")
    @need("admin")
    def firmware_bin(did):
        d, e = fw_device(did)
        if e:
            return e
        code, data = app.config["BUILDER_CALL"](app.config, "GET", f"/jobs/{d['fw_job']}/firmware", raw=True)
        if code != 200:
            return err("Firmware nie jest gotowe", 404)
        return data, 200, {"Content-Type": "application/octet-stream",
                           "Content-Disposition": f"attachment; filename={d['code']}.factory.bin", "Cache-Control": "no-store"}

    @app.get("/api/admin/devices/<int:did>/manifest.json")
    @need("admin")
    def firmware_manifest(did):
        """Manifest dla ESP Web Tools: wgranie przez USB z przeglądarki (Chrome/Edge na komputerze)."""
        d, e = fw_device(did)
        if e:
            return e
        chip = "ESP32-S3" if "s3" in cat.MODELS[d["model"]]["board"] else "ESP32"
        return jsonify(name=f"Sterownik {d['code']}", version=d["fw_job"], new_install_prompt_erase=True,
                       builds=[{"chipFamily": chip, "parts": [{"path": f"/api/admin/devices/{did}/firmware.bin", "offset": 0}]}])

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
            wg_sync()
        return jsonify({k: sv.cfg(dbm.get(), k) for k in sv.DEFAULTS})

    @app.get("/api/admin/devices/<int:did>/secrets")
    @need("admin")
    def admin_secrets(did):
        d = q("SELECT * FROM devices WHERE id=?", did).fetchone()
        if not d:
            return err("Nie znaleziono", 404)
        if d["tunnel"] == "wg" and not d["wg_pub"]:
            q("UPDATE devices SET wg_priv=?, wg_pub=? WHERE id=?", *sv.wg_keypair(), did)
            commit()
            wg_sync()
            d = q("SELECT * FROM devices WHERE id=?", did).fetchone()
        return sv.esphome_secrets(d, dbm.get()), 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}

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

    @app.cli.command("import-ekurnik")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--email", required=True, help="E-mail konta rolnika w portalu, do którego farmy trafią dane")
    @click.option("--gid", type=int, help="Numer gospodarstwa w e-kurniku (gdy jest ich kilka)")
    def import_ekurnik_cmd(path, email, gid):
        """Import danych z kopii bazy e-kurnika (klienci, salda, sprzedaż, zbiory, wydatki, wyposażenie...)."""
        import sqlite3 as _sq
        u = q("SELECT * FROM users WHERE email=? AND role='farmer'", email.strip().lower()).fetchone()
        if not u:
            raise click.ClickException(f"Nie ma konta rolnika {email}")
        src = _sq.connect(f"file:{path}?mode=ro", uri=True)
        farms = [f for f in ekurnik.farms_summary(src) if f[2] or f[3]]
        src.close()
        if gid is None:
            if len(farms) != 1:
                lines = "\n".join(f"  --gid {f[0]}: {f[1]} (klientów: {f[2]}, dni zbiorów: {f[3]})" for f in farms)
                raise click.ClickException("W bazie jest kilka gospodarstw z danymi, wybierz jedno:\n" + lines)
            gid = farms[0][0]
        try:
            n = ekurnik.import_ekurnik(dbm.get(), path, u["farm_id"], gid)
        except ValueError as e:
            raise click.ClickException(str(e))
        click.echo("Zaimportowano: " + ", ".join(f"{k}: {v}" for k, v in n.items()))

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
        q("UPDATE farms SET lat=?, lon=? WHERE id=1", 50.669, 17.753)
        for i in range(48, 0, -1):  # historia z ostatniej doby do wykresu
            at = datetime.now() - timedelta(minutes=30 * i)
            t = round(19 + 3 * math.sin((at.hour + at.minute / 60 - 9) / 24 * 2 * math.pi), 1)
            q("INSERT INTO readings(device_id,t,h,at) VALUES(?,?,?,?)", did, t, round(70 - (t - 19) * 4), at.isoformat())
        q("INSERT INTO readings(device_id,t,h,at) VALUES(?,?,?,?)", did, 21.5, 58, datetime.now().isoformat())
        for k, n, kind in (("ch4", "Wentylator", "vent"), ("ch5", "Ogrzewanie", "heater"), ("ch6", "Grzałka wody", "water_heater")):
            q("UPDATE channels SET name=?,kind=? WHERE device_id=? AND key=?", n, kind, did, k)
        q("INSERT INTO flocks(farm_id,name,birds,breed,since,notes) VALUES(1,?,?,?,?,?)", "Stado główne", 48,
          "Zielononóżka kuropatwiana", "2026-03-15", "Wybieg za stodołą, zamykane na noc.")
        for i, (n, dmg) in enumerate(((38, 1), (41, 0), (35, 2), (40, 1), (42, 0), (36, 1), (39, 0))):  # zbiory z tygodnia, w sztukach
            at = (datetime.now() - timedelta(days=7 - i, hours=-2)).isoformat()
            q("INSERT INTO eggs(farm_id,kind,eggs,at) VALUES(1,'collect',?,?)", n, at)
            q("INSERT INTO eggs(farm_id,kind,eggs,dirty,packs,at) VALUES(1,'sort',?,?,?,?)", n - dmg, dmg, (n - dmg) // 10, at)
        q("UPDATE farms SET unsorted=24 WHERE id=1")  # dzisiejszy zbiór czeka na sortowanie
        items = {}
        for name, cat_, stock, mn, price, prot, en, ca in (("Pszenica", "grain", 300, 100, 1.1, 11.5, 2900, 0.5),
                                                          ("Kukurydza", "grain", 200, 50, 1.2, 9, 3350, 0.2),
                                                          ("Śruta sojowa", "protein", 60, 25, 2.4, 46, 2400, 3),
                                                          ("Kreda pastewna", "mineral", 30, 10, 0.6, None, None, 370)):
            items[name] = q("INSERT INTO feed_items(farm_id,name,category,stock,min_stock,price,protein,energy,calcium) VALUES(1,?,?,?,?,?,?,?,?)",
                            name, cat_, stock, mn, price, prot, en, ca).lastrowid
        rid = q("INSERT INTO recipes(farm_id,name,season,active) VALUES(1,'Nioski cały rok','all',1)").lastrowid
        for name, pct in (("Pszenica", 50), ("Kukurydza", 25), ("Śruta sojowa", 18), ("Kreda pastewna", 7)):
            q("INSERT INTO recipe_items(recipe_id,item_id,percent) VALUES(?,?,?)", rid, items[name], pct)
        q("INSERT INTO eggs(farm_id,kind,eggs,at) VALUES(1,'collect',24,?)", (datetime.now() - timedelta(hours=1)).isoformat())
        q("UPDATE farms SET eggs=stock*10+60, reserved=30 WHERE id=1")  # magazyn: 12 opak. w sklepie, 30 szt. rezerwy, 30 wolnych
        for name, phone, price, history in (  # kartoteka: dług, nadpłata, stały klient z własną ceną
                ("Pani Zofia (sąsiadka)", "601202303", None, [("sale", 28, "later", 6), ("payment", -10, "cash", 3)]),
                ("Pan Marek", "602404505", None, [("sale", 14, "cash", 5), ("payment", -24, "cash", 5)]),
                ("Sklep „Lipka”", "603606707", 12.0, [("sale", 60, "transfer", 2), ("payment", -60, "transfer", 2)])):
            cid = q("INSERT INTO clients(farm_id,name,phone,phone_key,price10,created) VALUES(1,?,?,?,?,?)",
                    name, phone, clients.phone_key(phone), price, datetime.now().isoformat(timespec="seconds")).lastrowid
            sid = None
            for kind, amount, method, ago in history:
                at = (datetime.now() - timedelta(days=ago)).isoformat(timespec="seconds")
                if kind == "sale":
                    p10 = price or 14
                    sid = q("INSERT INTO sales(farm_id,client_id,at,packs,price10,total,method,paid) VALUES(1,?,?,?,?,?,?,?)",
                            cid, at, round(amount / p10), p10, amount, method, 0 if method == "later" else amount).lastrowid
                q("INSERT INTO ledger(farm_id,client_id,at,kind,amount,method,sale_id,note) VALUES(1,?,?,?,?,?,?,?)", cid, at, kind,
                  amount, "" if kind == "sale" else method, sid, "Sprzedaż" if kind == "sale" else "Wpłata")
            if name.startswith("Pani Zofia"):  # stała klientka: 30 szt. co tydzień, dostawa dziś
                q("INSERT INTO subscriptions(farm_id,client_id,eggs,every_days,next_date,method,created) VALUES(1,?,30,7,?,'later',?)",
                  cid, datetime.now().date().isoformat(), datetime.now().isoformat(timespec="seconds"))
        q("UPDATE sales SET eggs=packs*10 WHERE farm_id=1")
        for d, cat_, name, qty, unit, price in ((10, "Pasza i zboże", "Pszenica", 100, "kg", 1.1), (20, "Pasza i zboże", "Kukurydza", 50, "kg", 1.2),
                                                 (15, "Witaminy i suplementy", "Witaminy do wody", 1, "szt", 27.5), (5, "Ściółka", "Słoma", 4, "kostka", 12)):
            q("INSERT INTO expenses(farm_id,date,category,name,qty,unit,unit_price,total) VALUES(1,?,?,?,?,?,?,?)",
              (datetime.now().date() - timedelta(days=d)).isoformat(), cat_, name, qty, unit, price, round(qty * price, 2))
        for name, cat_, bought, price, state, check in (("Poidło automatyczne 10 l", "Poidło", "2026-03-15", 89, "ok", ""),
                                                        ("Karmidło tubowe", "Karmidło", "2026-03-15", 65, "ok", ""),
                                                        ("Lampa grzewcza", "Oświetlenie", "2025-11-02", 120, "repair",
                                                         (datetime.now().date() + timedelta(days=5)).isoformat())):
            q("INSERT INTO equipment(farm_id,name,category,bought,price,state,next_check) VALUES(1,?,?,?,?,?,?)", name, cat_, bought, price, state, check)
        now = datetime.now().isoformat(timespec="seconds")
        for title, cat_, text, pub in KB_DEMO:
            q("INSERT INTO kb(title,category,body,published,created,updated) VALUES(?,?,?,?,?,?)", title, cat_, text, pub, now, now)
        commit()
        click.echo("Gotowe: admin@zniesione.test / Admin12345!  rolnik@zniesione.test / Rolnik12345!")

    # polecenia konsolowe (np. create-admin w działającym kontenerze) nie uruchamiają drugiego silnika obok serwera
    if app.config["RUN_SCHEDULER"] and not set(sys.argv) & {"create-admin", "seed-demo", "shell", "routes"}:
        def loop():
            ev, minute = threading.Event(), None
            while not ev.wait(app.config["TICK_S"]):  # krótki obieg: impulsy drzwi trwają sekundy
                try:
                    sv.tick(app)
                    if datetime.now().minute != minute:  # przypomnienia o zbiorze: raz na minutę
                        minute = datetime.now().minute
                        with app.app_context():
                            farmbook.reminders(app, dbm.get())
                except Exception:  # noqa: BLE001
                    app.logger.exception("tick failed")
        threading.Thread(target=loop, daemon=True, name="scheduler").start()
    return app
