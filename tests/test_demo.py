import json
import threading
from http.server import HTTPServer

from conftest import Client
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools import fake_device
from zniesione import services as sv


def test_seed_demo_and_ui_served(app):
    app.config["SEND"] = sv.send_http
    out = runner.invoke(args=["seed-demo"])
    assert out.exit_code != 0  # baza ma już admina z fixture
    assert "zniesione.pl" in app.test_client().get("/").get_data(as_text=True)
    assert app.test_client().get("/prototype").status_code == 200


def test_seed_on_empty_db(tmp_path):
    from zniesione import create_app
    a = create_app({"DATABASE": str(tmp_path / "s.db"), "TESTING": True})
    assert a.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
    c = Client(a)
    assert c.post("/api/auth/login", {"email": "rolnik@zniesione.test", "password": "Rolnik12345!"}).status_code == 200
    d = c.get("/api/my/devices").get_json()[0]
    assert d["stage"] == 3 and d["online"] and d["reading"]["t"] == 21.5
    assert {ch["kind"] for ch in d["channels"]} >= {"vent", "heater", "water_heater"}
    assert len(c.get("/api/farms").get_json()) == 3


def test_api_key_visible_only_to_admin(app, admin, farmer):
    farmer[0].post("/api/my/device-orders", {"model": "tr4"})
    assert "api_key" in admin.get("/api/admin/devices").get_json()[0]
    assert "api_key" not in farmer[0].get("/api/my/devices").get_json()[0]


def test_real_http_path_to_fake_device(app, admin, farmer, monkeypatch):
    """Sprawdza prawdziwe send_http przeciw atrapie urządzenia (bez mocka)."""
    from conftest import online_device
    srv = HTTPServer(("127.0.0.1", 0), fake_device.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("DEVICE_BASE", f"http://127.0.0.1:{srv.server_port}")
    app.config["SEND"] = sv.send_http
    did, _ = online_device(app, admin, farmer)
    assert farmer[0].post(f"/api/my/devices/{did}/channels/ch1", {"state": True}).status_code == 200
    assert fake_device.STATE["ch1"] is True
    srv.shutdown()
    monkeypatch.setenv("DEVICE_BASE", "http://127.0.0.1:1")
    assert farmer[0].post(f"/api/my/devices/{did}/channels/ch1", {"state": False}).status_code == 502
