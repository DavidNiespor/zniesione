"""Usuwanie sterownika, sterownik z Home Assistant (atrapa REST API HA), kamery Thingino przez WireGuard."""
from datetime import datetime

from zniesione import services as sv


class FakeHA:
    """Atrapa REST API Home Assistant: /api/, /api/states, /api/states/<encja>, /api/services/<domena>/turn_on|off."""
    def __init__(self, token="dobry"):
        self.token, self.calls = token, []
        self.states = [
            {"entity_id": "switch.kurnik_swiatlo", "state": "off", "attributes": {"friendly_name": "Kurnik światło"}},
            {"entity_id": "light.wybieg", "state": "on", "attributes": {"friendly_name": "Wybieg"}},
            {"entity_id": "sensor.kurnik_temp", "state": "18.5", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C"}},
            {"entity_id": "sensor.kurnik_wilg", "state": "71", "attributes": {"device_class": "humidity", "unit_of_measurement": "%"}},
            {"entity_id": "sensor.prad", "state": "3", "attributes": {"unit_of_measurement": "kWh"}},
            {"entity_id": "automation.x", "state": "on", "attributes": {}}]

    def __call__(self, dev, method, path, body=None):
        self.calls.append((sv.ha_base(dev), method, path, body))
        if dev["ha_token"] != self.token:
            return 401, {"error": "Home Assistant odrzucił token"}
        if path == "/api/":
            return 200, {"message": "API running."}
        if path == "/api/states":
            return 200, self.states
        if path.startswith("/api/states/"):
            e = next((s for s in self.states if s["entity_id"] == path[12:]), None)
            return (200, e) if e else (404, {"error": "HTTP 404"})
        if path.startswith("/api/services/"):
            return 200, []
        return 404, {}


def ha_farm(app, admin, farmer):
    c, fid = farmer
    assert admin.patch(f"/api/admin/farms/{fid}", {"ha_enabled": True}).get_json()["ha_enabled"] is True
    app.config["HA_CALL"] = ha = FakeHA()
    return c, ha


def test_ha_device_needs_admin_flag_and_validates(app, admin, farmer):
    c, fid = farmer
    assert c.get("/api/me").get_json()["ha"] is False
    assert c.post("/api/my/ha-devices", {"addr": "Kurnik", "token": "x"}).status_code == 403
    assert "ha" not in [m["id"] for m in c.get("/api/catalog").get_json()]
    assert c.post("/api/my/device-orders", {"model": "ha", "addr": "x"}).status_code == 400
    admin.patch(f"/api/admin/farms/{fid}", {"ha_enabled": True})
    assert c.get("/api/me").get_json()["ha"] is True
    for bad in ({"addr": "", "token": "t"}, {"addr": "K", "token": ""}, {"addr": "K", "token": "t", "tunnel": "x"},
                {"addr": "K", "token": "t", "tunnel": "url", "url": "ftp://ha.example.pl"},
                {"addr": "K", "token": "t", "tunnel": "url", "url": "http://127.0.0.1:8123"},
                {"addr": "K", "token": "t", "tunnel": "url", "url": "http://esphome:6052"},
                {"addr": "K", "token": "t", "tunnel": "url", "url": "http://169.254.169.254"},
                {"addr": "K", "token": "t", "tunnel": "url", "url": "https://ha.example.pl/api/x"}):
        assert c.post("/api/my/ha-devices", bad).status_code == 400, bad
    f = admin.get("/api/admin/farms").get_json()
    assert next(x for x in f if x["id"] == fid)["users"] == ["a@x.pl"]


def test_ha_device_wireguard_entities_control_and_readings(app, admin, farmer, farmer2):
    c, ha = ha_farm(app, admin, farmer)
    d = c.post("/api/my/ha-devices", {"addr": "Kurnik (HA)", "tunnel": "wg", "token": "dobry"}).get_json()
    assert (d["model"], d["stage"], d["ha_token_set"]) == ("ha", 3, True) and "ha_token" not in d
    conf = c.get(f"/api/my/devices/{d['id']}/ha/wireguard").get_data(as_text=True)
    assert f"Address = {d['ip']}/32" in conf and "PrivateKey = " in conf and "AllowedIPs = 10.8.0.1/32" in conf
    assert farmer2[0].get(f"/api/my/devices/{d['id']}/ha/wireguard").status_code == 404
    e = c.get(f"/api/my/devices/{d['id']}/ha/entities").get_json()
    assert [x["entity_id"] for x in e["switches"]] == ["light.wybieg", "switch.kurnik_swiatlo"]
    assert [(x["entity_id"], x["kind"]) for x in e["sensors"]] == [("sensor.kurnik_temp", "t"), ("sensor.kurnik_wilg", "h")]
    assert ha.calls[-1][0] == f"http://{d['ip']}:8123"                                  # przez tunel WireGuard
    bad = [{"entity_id": "automation.x", "name": "X", "kind": "other"}]
    assert c.put(f"/api/my/devices/{d['id']}/ha/channels", {"channels": bad}).status_code == 400
    r = c.put(f"/api/my/devices/{d['id']}/ha/channels", {"channels": [
        {"entity_id": "switch.kurnik_swiatlo", "name": "Światło", "kind": "light"},
        {"entity_id": "light.wybieg", "name": "Lampa wybiegu", "kind": "other"}], "temp": "sensor.kurnik_temp", "hum": "sensor.kurnik_wilg"}).get_json()
    assert [(x["key"], x["kind"]) for x in r["channels"]] == [("switch.kurnik_swiatlo", "light"), ("light.wybieg", "other")]
    # sterowanie idzie przez REST API HA (prawdziwy send_http z atrapą)
    app.config["SEND"] = sv.send_http
    import zniesione.services as s2
    orig = s2.ha_call
    s2.ha_call = ha
    try:
        assert c.post(f"/api/my/devices/{d['id']}/channels/switch.kurnik_swiatlo", {"state": True}).status_code == 200
    finally:
        s2.ha_call = orig
    assert ha.calls[-1][1:] == ("POST", "/api/services/switch/turn_on", {"entity_id": "switch.kurnik_swiatlo"})
    # silnik co minutę pyta HA: sterownik online, odczyt temperatury i wilgotności
    sv.tick(app, datetime.now())
    dv = c.get("/api/my/devices").get_json()[0]
    assert dv["online"] and dv["reading"]["t"] == 18.5 and dv["reading"]["h"] == 71
    # wycofanie encji usuwa jej kanał
    r = c.put(f"/api/my/devices/{d['id']}/ha/channels", {"channels": [{"entity_id": "light.wybieg", "name": "Lampa", "kind": "light"}]}).get_json()
    assert [x["key"] for x in r["channels"]] == ["light.wybieg"]
    assert c.patch(f"/api/my/devices/{d['id']}/ha", {"token": "zly"}).status_code == 200
    assert c.get(f"/api/my/devices/{d['id']}/ha/entities").status_code == 502
    assert "token" in c.get("/api/my/devices").get_json()[0]["ha_error"]                 # powód błędu widać w karcie


def test_ha_by_url(app, admin, farmer):
    c, ha = ha_farm(app, admin, farmer)
    d = c.post("/api/my/ha-devices", {"addr": "Dom", "tunnel": "url", "url": "https://dom.example.pl/", "token": "dobry"}).get_json()
    assert d["ha_url"] == "https://dom.example.pl"
    c.get(f"/api/my/devices/{d['id']}/ha/entities")
    assert ha.calls[-1][0] == "https://dom.example.pl"
    assert c.get(f"/api/my/devices/{d['id']}/ha/wireguard").status_code == 404


def test_delete_device_by_farmer_and_admin(app, admin, farmer, farmer2):
    from conftest import online_device
    c, _ = farmer
    did, _ = online_device(app, admin, farmer)
    c.post(f"/api/my/devices/{did}/schedules", {"ch": "ch1", "t_on": "06:00", "t_off": "20:00", "days": "a"})
    assert farmer2[0].delete(f"/api/my/devices/{did}").status_code == 404
    assert c.delete(f"/api/my/devices/{did}").status_code == 200
    assert c.get("/api/my/devices").get_json() == []
    with app.app_context():
        from zniesione import db as dbm
        assert not any(dbm.get().execute(f"SELECT 1 FROM {t} WHERE device_id=?", (did,)).fetchone() for t in ("channels", "schedules", "log", "readings"))
    did2 = c.post("/api/my/device-orders", {"model": "tr4", "addr": "Wieś 1"}).get_json()["id"]
    assert admin.delete(f"/api/admin/devices/{did2}").status_code == 200 and admin.delete(f"/api/admin/devices/{did2}").status_code == 404


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 50


def test_cameras_wireguard_and_snapshot(app, farmer, farmer2, tmp_path):
    c, _ = farmer
    got = []
    app.config["CAM_FETCH"] = lambda cam: (got.append(cam), (True, JPEG) if cam["cam_pass"] == "tajne" else (False, "Kamera odrzuciła login lub hasło"))[1]
    assert c.post("/api/my/cameras", {"name": ""}).status_code == 400
    cam = c.post("/api/my/cameras", {"name": "Kurnik środek", "password": "tajne"}).get_json()
    assert cam["user"] == "thingino" and cam["ip"].startswith("10.8.0.") and "cam_pass" not in cam
    conf = c.get(f"/api/my/cameras/{cam['id']}/wireguard").get_data(as_text=True)
    assert f"Address = {cam['ip']}/32" in conf and "PersistentKeepalive = 25" in conf
    r = c.get(cam["snapshot"])
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data == JPEG and r.headers["Cache-Control"] == "no-store"
    assert got[-1]["ip"] == cam["ip"]
    c.patch(f"/api/my/cameras/{cam['id']}", {"password": "zle"})
    r = c.get(cam["snapshot"])
    assert r.status_code == 502 and "login" in r.get_json()["error"]
    assert farmer2[0].get(cam["snapshot"]).status_code == 404
    # kamera i sterowniki dostają różne adresy w tunelu, a serwer WireGuard zna klucz kamery
    with app.app_context():
        from zniesione import db as dbm
        text = sv.write_wg_conf(dbm.get(), str(tmp_path / "wg0.conf"))
    assert f"AllowedIPs = {cam['ip']}/32" in text
    d = c.post("/api/my/device-orders", {"model": "tr4", "addr": "x"}).get_json()
    assert c.get("/api/my/devices").get_json()[0]["ip"] != cam["ip"] and d
    assert c.delete(f"/api/my/cameras/{cam['id']}").status_code == 200 and c.get("/api/my/cameras").get_json() == []


def test_snapshot_reads_thingino_image_jpg_with_basic_auth(monkeypatch):
    """Prawdziwy cam_fetch: adres /image.jpg i nagłówek Basic z loginem kamery (wg dokumentacji Thingino)."""
    seen = {}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return JPEG

    def fake(req, timeout):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        return R()
    monkeypatch.setattr(sv.urllib.request, "urlopen", fake)
    monkeypatch.delenv("CAMERA_BASE", raising=False)
    assert sv.cam_fetch({"ip": "10.8.0.20", "cam_user": "thingino", "cam_pass": "thingino"}) == (True, JPEG)
    assert seen == {"url": "http://10.8.0.20/image.jpg", "auth": "Basic dGhpbmdpbm86dGhpbmdpbm8="}


def test_ha_call_real_http_errors_are_explained():
    """Prawdziwe połączenia HTTP do lokalnej atrapy HA: token, Cloudflare, strona zamiast API, zamknięty port, nagłówek User-Agent."""
    import json as _json
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["ua"], seen["auth"] = self.headers.get("User-Agent"), self.headers.get("Authorization")
            code, ctype, body = {"/ok/api/": (200, "application/json", _json.dumps({"message": "API running."})),
                                 "/bad/api/": (401, "application/json", "{}"),
                                 "/cf/api/": (403, "text/html", "<title>Attention Required! | Cloudflare</title>"),
                                 "/html/api/": (200, "text/html", "<html>Cloudflare challenge</html>")}.get(self.path, (404, "text/plain", "x"))
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    dev = lambda p, tok="tajny": {"tunnel": "url", "ha_url": base + p, "ha_token": tok + "\n", "ip": "10.8.0.9"}
    try:
        assert sv.ha_call(dev("/ok"), "GET", "/api/") == (200, {"message": "API running."})
        assert seen == {"ua": "zniesione-portal/1.0", "auth": "Bearer tajny"}           # token bez znaku nowej linii z wklejenia
        c, js = sv.ha_call(dev("/bad"), "GET", "/api/")
        assert c == 401 and "token" in js["error"]
        c, js = sv.ha_call(dev("/cf"), "GET", "/api/")
        assert c == 403 and "Cloudflare" in js["error"]
        c, js = sv.ha_call(dev("/html"), "GET", "/api/")
        assert c == 502 and "stronę zamiast API" in js["error"]
        c, js = sv.ha_call(dev("/x"), "GET", "/api/")
        assert c == 404 and "bez ścieżki" in js["error"]
    finally:
        srv.shutdown()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                                            # port na pewno zamknięty
    c, js = sv.ha_call({"tunnel": "url", "ha_url": f"http://127.0.0.1:{port}", "ha_token": "t", "ip": ""}, "GET", "/api/")
    assert c == 503 and "odrzucone" in js["error"]
