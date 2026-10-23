"""Sterowniki i kamery spoza oferty: własny sterownik spięty z Home Assistant (dla farm, którym włączy to administrator)
oraz kamery z firmware Thingino łączące się przez WireGuard. Tu też usuwanie sterownika i lista farm w panelu admina."""
import ipaddress
import secrets
import urllib.parse
from datetime import datetime

import click
from flask import Response, g, jsonify, request

from . import catalog as cat
from . import db as dbm
from . import services as sv

# nazwy kontenerów stacka: adres Home Assistant nie może wskazywać usług wewnątrz serwera
STACK_HOSTS = {"localhost", "zniesione", "esphome", "poczta", "poczta-start", "webmail", "dns", "wireguard", "cloudflared", "kopie",
               "siec", "certyfikat"}
MAX_CAMERAS = 8


def ha_url_ok(u):
    try:
        m = urllib.parse.urlsplit(u)
        port = m.port
    except ValueError:
        return False
    if m.scheme not in ("http", "https") or not m.hostname or m.path not in ("", "/") or m.query or m.username or port == 0:
        return False
    h = m.hostname.lower()
    if h in STACK_HOSTS or h.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return True
    return not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast)


def register(app, need, q, commit, body, err, integer, dev_json, wg_sync, own_device):
    def text_field(b, k, n, required=False):
        v = b.get(k, "")
        if not isinstance(v, str) or len(v) > n or (required and not v.strip()):
            return None
        return v.strip()

    _db = dbm.get

    def delete_device(did):
        for t in ("channels", "schedules", "rules", "readings", "log"):
            q(f"DELETE FROM {t} WHERE device_id=?", did)
        q("DELETE FROM devices WHERE id=?", did)
        commit()
        wg_sync()  # klucz sterownika znika z serwera WireGuard

    @app.delete("/api/my/devices/<int:did>")
    @need("farmer")
    def my_device_delete(did):
        if not own_device(did):
            return err("Nie znaleziono", 404)
        delete_device(did)
        return jsonify(ok=True)

    @app.delete("/api/admin/devices/<int:did>")
    @need("admin")
    def admin_device_delete(did):
        if not q("SELECT 1 FROM devices WHERE id=?", did).fetchone():
            return err("Nie znaleziono", 404)
        delete_device(did)
        return jsonify(ok=True)

    # ---------- Home Assistant ----------
    def ha_farm():
        return q("SELECT ha_enabled FROM farms WHERE id=?", g.user["farm_id"]).fetchone()["ha_enabled"]

    def ha_device(did):
        d = own_device(did)
        return d if d and d["model"] == "ha" else None

    @app.post("/api/my/ha-devices")
    @need("farmer")
    def ha_add():
        """Sterownik, który już działa w Home Assistant: portal steruje encjami przez REST API HA (token długoterminowy)."""
        if not ha_farm():
            return err("Sterowniki z Home Assistant włącza administrator portalu", 403)
        b = body()
        addr, tunnel, url, token = text_field(b, "addr", 200, True), b.get("tunnel", "wg"), text_field(b, "url", 200), text_field(b, "token", 400, True)
        if not addr:
            return err("Podaj nazwę, np. Kurnik (Home Assistant)")
        if tunnel not in ("wg", "url"):
            return err("Połączenie: wg (Home Assistant w tunelu WireGuard) albo url (adres Home Assistant)")
        if tunnel == "url" and not (url and ha_url_ok(url)):
            return err("Adres Home Assistant: http(s)://nazwa-lub-IP[:port], bez ścieżki (np. https://dom.example.pl)")
        if not token:
            return err("Wklej token długoterminowy z Home Assistant (Profil → Bezpieczeństwo → Tokeny długoterminowe)")
        did = q("INSERT INTO devices(code,model,farm_id,tunnel,ip,api_key,addr,stage,ha_url,ha_token) VALUES(?,?,?,?,?,?,?,?,?,?)",
                "ha-" + secrets.token_hex(2), "ha", g.user["farm_id"], tunnel, sv.alloc_ip(_db()),
                secrets.token_urlsafe(24), addr, 3, url.rstrip("/") if tunnel == "url" else "", token).lastrowid
        commit()
        if tunnel == "wg":
            sv.device_keys(_db(), q("SELECT * FROM devices WHERE id=?", did).fetchone())
            wg_sync()
        return jsonify(dev_json(q("SELECT * FROM devices WHERE id=?", did).fetchone())), 201

    @app.get("/api/my/devices/<int:did>/ha/wireguard")
    @need("farmer")
    def ha_wireguard(did):
        d = ha_device(did)
        if not d or d["tunnel"] != "wg":
            return err("Nie znaleziono", 404)
        d = sv.device_keys(_db(), d)
        return Response(sv.peer_conf(_db(), d["ip"], d["wg_priv"], f"Home Assistant: {d['addr']} (dodatek WireGuard)"), mimetype="text/plain")

    @app.patch("/api/my/devices/<int:did>/ha")
    @need("farmer")
    def ha_patch(did):
        d, b = ha_device(did), body()
        if not d:
            return err("Nie znaleziono", 404)
        if "url" in b:
            u = text_field(b, "url", 200)
            if d["tunnel"] != "url" or not (u and ha_url_ok(u)):
                return err("Adres Home Assistant: http(s)://nazwa-lub-IP[:port], bez ścieżki")
            q("UPDATE devices SET ha_url=? WHERE id=?", u.rstrip("/"), did)
        if "token" in b:
            t = text_field(b, "token", 400, True)
            if not t:
                return err("Token nie może być pusty")
            q("UPDATE devices SET ha_token=? WHERE id=?", t, did)
        if "addr" in b:
            a = text_field(b, "addr", 200, True)
            if not a:
                return err("Podaj nazwę")
            q("UPDATE devices SET addr=? WHERE id=?", a, did)
        commit()
        return jsonify(dev_json(q("SELECT * FROM devices WHERE id=?", did).fetchone()))

    @app.get("/api/my/devices/<int:did>/ha/entities")
    @need("farmer")
    def ha_entities(did):
        """Encje z Home Assistant do wyboru: przełączniki (switch, light, input_boolean, fan) i czujniki temperatury i wilgotności."""
        d = ha_device(did)
        if not d:
            return err("Nie znaleziono", 404)
        code, js = app.config["HA_CALL"](dict(d), "GET", "/api/states")
        if code != 200 or not isinstance(js, list):
            return err((js or {}).get("error", f"Home Assistant: HTTP {code}") if isinstance(js, dict) else f"Home Assistant: HTTP {code}", 502)
        sw, sens = [], []
        for e in js:
            eid, at = str(e.get("entity_id", "")), e.get("attributes") or {}
            item = dict(entity_id=eid, name=str(at.get("friendly_name") or eid)[:80], state=str(e.get("state", ""))[:30])
            dom = eid.split(".", 1)[0]
            if dom in sv.HA_DOMAINS:
                sw.append(item)
            elif dom == "sensor" and (at.get("device_class") in ("temperature", "humidity") or at.get("unit_of_measurement") in ("°C", "%")):
                sens.append(dict(item, kind="h" if at.get("device_class") == "humidity" or at.get("unit_of_measurement") == "%" else "t",
                                 unit=str(at.get("unit_of_measurement") or "")))
        q("UPDATE devices SET online=1, last_seen=? WHERE id=?", datetime.now().isoformat(), did)
        commit()
        return jsonify(switches=sorted(sw, key=lambda x: x["entity_id"]), sensors=sorted(sens, key=lambda x: x["entity_id"]))

    @app.put("/api/my/devices/<int:did>/ha/channels")
    @need("farmer")
    def ha_channels(did):
        """Wybrane encje stają się kanałami sterownika (z harmonogramami, termostatem i drzwiami jak w sterownikach z oferty)."""
        d, b = ha_device(did), body()
        if not d:
            return err("Nie znaleziono", 404)
        chans, ent = b.get("channels", []), lambda s: isinstance(s, str) and len(s) <= 120 and s.split(".", 1)[0] in sv.HA_DOMAINS and "." in s
        if not isinstance(chans, list) or len(chans) > 16:
            return err("Najwyżej 16 encji")
        keys = []
        for c in chans:
            if not isinstance(c, dict) or not ent(c.get("entity_id")) or c.get("kind", "other") not in cat.KINDS \
                    or not isinstance(c.get("name"), str) or not c["name"].strip() or len(c["name"]) > 60 or c["entity_id"] in keys:
                return err("Każda encja: entity_id (switch, light, input_boolean, fan), nazwa do 60 znaków i rodzaj urządzenia")
            keys.append(c["entity_id"])
        for k in ("temp", "hum"):
            v = b.get(k, "")
            if v and not (isinstance(v, str) and v.startswith("sensor.") and len(v) <= 120):
                return err("Czujnik: encja sensor.*")
        old = {r["key"] for r in q("SELECT key FROM channels WHERE device_id=?", did)}
        for k in old - set(keys):
            for t in ("channels", "schedules", "rules"):
                q(f"DELETE FROM {t} WHERE device_id=? AND {'key' if t == 'channels' else 'ch'}=?", did, k)
        for c in chans:
            if c["entity_id"] in old:
                q("UPDATE channels SET name=?, kind=? WHERE device_id=? AND key=?", c["name"].strip(), c.get("kind", "other"), did, c["entity_id"])
            else:
                q("INSERT INTO channels(device_id,key,name,kind) VALUES(?,?,?,?)", did, c["entity_id"], c["name"].strip(), c.get("kind", "other"))
        q("UPDATE devices SET ha_temp=?, ha_hum=? WHERE id=?", b.get("temp", "") or "", b.get("hum", "") or "", did)
        commit()
        return jsonify(dev_json(q("SELECT * FROM devices WHERE id=?", did).fetchone()))

    # ---------- kamery (Thingino przez WireGuard) ----------
    def cam_json(c):
        return dict(id=c["id"], name=c["name"], building_id=c["building_id"], ip=c["ip"], user=c["cam_user"], last_ok=c["last_ok"],
                    snapshot=f"/api/my/cameras/{c['id']}/snapshot")

    def own_cam(cid):
        return q("SELECT * FROM cameras WHERE id=? AND farm_id=?", cid, g.user["farm_id"]).fetchone()

    def cam_fields(b, old):
        out = {}
        if "name" in b or not old:
            out["name"] = text_field(b, "name", 60, True)
            if not out["name"]:
                return None, "Podaj nazwę kamery, np. Kurnik od środka"
        for k, col in (("user", "cam_user"), ("password", "cam_pass")):
            if k in b:
                v = text_field(b, k, 64, True)
                if not v:
                    return None, "Login i hasło kamery do 64 znaków"
                out[col] = v
        if "building_id" in b:
            v = b["building_id"]
            if v is not None and (not integer(v, 1, 10 ** 9) or not q("SELECT 1 FROM buildings WHERE id=? AND farm_id=?", v, g.user["farm_id"]).fetchone()):
                return None, "Nieznany budynek"
            out["building_id"] = v
        return out, None

    @app.route("/api/my/cameras", methods=["GET", "POST"])
    @need("farmer")
    def cameras():
        fid = g.user["farm_id"]
        if request.method == "GET":
            return jsonify([cam_json(c) for c in q("SELECT * FROM cameras WHERE farm_id=? ORDER BY id", fid)])
        if q("SELECT COUNT(*) FROM cameras WHERE farm_id=?", fid).fetchone()[0] >= MAX_CAMERAS:
            return err(f"Najwyżej {MAX_CAMERAS} kamer na gospodarstwo", 409)
        f, msg = cam_fields(body(), None)
        if msg:
            return err(msg)
        priv, pub = sv.wg_keypair()
        cid = q("INSERT INTO cameras(farm_id,building_id,name,ip,wg_priv,wg_pub,cam_user,cam_pass,created) VALUES(?,?,?,?,?,?,?,?,?)", fid,
                f.get("building_id"), f["name"], sv.alloc_ip(_db()), priv, pub, f.get("cam_user", "thingino"), f.get("cam_pass", "thingino"),
                datetime.now().isoformat(timespec="seconds")).lastrowid
        commit()
        wg_sync()
        return jsonify(cam_json(own_cam(cid))), 201

    @app.route("/api/my/cameras/<int:cid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def camera(cid):
        c = own_cam(cid)
        if not c:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            q("DELETE FROM cameras WHERE id=?", cid)
            commit()
            wg_sync()
            return jsonify(ok=True)
        f, msg = cam_fields(body(), c)
        if msg:
            return err(msg)
        for k, v in f.items():
            q(f"UPDATE cameras SET {k}=? WHERE id=?", v, cid)
        commit()
        return jsonify(cam_json(own_cam(cid)))

    @app.get("/api/my/cameras/<int:cid>/wireguard")
    @need("farmer")
    def camera_wg(cid):
        c = own_cam(cid)
        if not c:
            return err("Nie znaleziono", 404)
        return Response(sv.peer_conf(_db(), c["ip"], c["wg_priv"], f"Kamera: {c['name']} (WireGuard w Thingino)"), mimetype="text/plain")

    @app.get("/api/my/cameras/<int:cid>/snapshot")
    @need("farmer")
    def camera_snapshot(cid):
        c = own_cam(cid)
        if not c:
            return err("Nie znaleziono", 404)
        ok, data = app.config["CAM_FETCH"](dict(c))
        if not ok:
            return err(data, 502)
        q("UPDATE cameras SET last_ok=? WHERE id=?", datetime.now().isoformat(timespec="seconds"), cid)
        commit()
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    # ---------- admin: farmy i funkcje dodatkowe ----------
    @app.get("/api/admin/farms")
    @need("admin")
    def admin_farms():
        out = []
        for f in q("SELECT * FROM farms ORDER BY name"):
            out.append(dict(id=f["id"], name=f["name"], city=f["city"], ha_enabled=bool(f["ha_enabled"]),
                            users=[r["email"] for r in q("SELECT email FROM users WHERE farm_id=? ORDER BY owner DESC, id", f["id"])],
                            devices=q("SELECT COUNT(*) FROM devices WHERE farm_id=?", f["id"]).fetchone()[0],
                            cameras=q("SELECT COUNT(*) FROM cameras WHERE farm_id=?", f["id"]).fetchone()[0]))
        return jsonify(out)

    @app.patch("/api/admin/farms/<int:fid>")
    @need("admin")
    def admin_farm_patch(fid):
        b = body()
        if not q("SELECT 1 FROM farms WHERE id=?", fid).fetchone():
            return err("Nie znaleziono", 404)
        if not isinstance(b.get("ha_enabled"), bool):
            return err("Pole ha_enabled musi być true lub false")
        q("UPDATE farms SET ha_enabled=? WHERE id=?", int(b["ha_enabled"]), fid)
        commit()
        return jsonify(ok=True, ha_enabled=b["ha_enabled"])

    @app.cli.command("farm-ha")
    @click.option("--email", required=True, help="E-mail konta rolnika")
    @click.option("--off", is_flag=True, help="Wyłącz zamiast włączyć")
    def farm_ha_cmd(email, off):
        """Włącza (albo wyłącza) dodawanie sterowników z Home Assistant dla farmy tego konta."""
        u = q("SELECT farm_id FROM users WHERE email=? AND role='farmer'", email.strip().lower()).fetchone()
        if not u:
            raise click.ClickException(f"Nie ma konta rolnika {email}")
        q("UPDATE farms SET ha_enabled=? WHERE id=?", 0 if off else 1, u["farm_id"])
        commit()
        click.echo(f"Home Assistant {'wyłączony' if off else 'włączony'} dla farmy konta {email}")
