"""Panel rolnika: katalog, położenie farmy, migracja bazy."""
import sqlite3

from conftest import Client
from zniesione import create_app


def test_catalog_marks_cheapest_default_model(app, farmer):
    ct = farmer[0].get("/api/catalog").get_json()
    assert [m["id"] for m in ct if m["cheapest"]] == ["tr4"]
    assert [m["id"] for m in ct if m["default"]] == ["tr4"]
    assert all("price" not in m for m in ct)


def test_only_catalog_devices_can_be_connected(app, admin, farmer):
    c, fid = farmer
    for bad in ({"model": "own"}, {"model": "TR4"}, {}, {"model": None}, {"model": ["tr4"]}):
        assert c.post("/api/my/device-orders", bad).status_code == 400
    assert admin.post("/api/admin/devices", {"model": "esp32-diy", "farm_id": fid}).status_code == 400
    assert c.post("/api/my/devices", {"model": "tr4"}).status_code == 405       # brak ścieżki „dodaj własne”
    # liczby przekaźników nie da się podać z zewnątrz: pochodzi z katalogu
    did = c.post("/api/my/device-orders", {"model": "tr4", "channels": 16}).get_json()["id"]
    assert len(next(d for d in c.get("/api/my/devices").get_json() if d["id"] == did)["channels"]) == 4
    assert c.patch(f"/api/my/devices/{did}/channels/ch1", {"kind": "laser"}).status_code == 400
    assert c.get("/api/my/devices").get_json()[0]["model"] == "tr4"


def test_kinds_have_polish_names(app):
    k = {x["id"]: x["name"] for x in app.test_client().get("/api/kinds").get_json()}
    assert k["door_open"] == "Drzwi: otwórz" and k["vent"] == "Wentylacja" and len(k) == 10


def test_farm_location_validation_and_privacy(app, farmer, anon):
    c, fid = farmer
    assert c.get("/api/my/farm").get_json()["lat"] is None
    assert c.put("/api/my/farm", {"lat": 91}).status_code == 400
    assert c.put("/api/my/farm", {"lon": "17"}).status_code == 400
    assert c.put("/api/my/farm", {"lat": True}).status_code == 400
    r = c.put("/api/my/farm", {"lat": 50.67, "lon": 17.93}).get_json()
    assert (r["lat"], r["lon"]) == (50.67, 17.93)
    assert "lat" not in anon.get(f"/api/farms/{fid}").get_json()
    assert c.put("/api/my/farm", {"lat": None, "lon": None}).get_json()["lat"] is None
    assert anon.get("/api/my/farm").status_code == 401


def test_old_database_is_migrated(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("""CREATE TABLE schedules(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL,
      t_on TEXT NOT NULL, t_off TEXT NOT NULL, days TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
      INSERT INTO schedules(device_id,ch,t_on,t_off,days) VALUES(1,'ch1','06:00','18:00','a');""")
    con.commit(), con.close()
    create_app({"DATABASE": str(p), "TESTING": True})
    row = sqlite3.connect(p).execute("SELECT mode, offset_min, duration_s FROM schedules").fetchone()
    assert row == ("time", 0, None)
    create_app({"DATABASE": str(p), "TESTING": True})  # drugi start nic nie psuje


def test_seed_demo_has_location_and_day_of_readings(tmp_path):
    a = create_app({"DATABASE": str(tmp_path / "s.db"), "TESTING": True})
    assert a.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
    c = Client(a)
    c.post("/api/auth/login", {"email": "rolnik@zniesione.test", "password": "Rolnik12345!"})
    assert c.get("/api/my/farm").get_json()["lat"] is not None
    did = c.get("/api/my/devices").get_json()[0]["id"]
    assert len(c.get(f"/api/my/devices/{did}/readings?hours=24").get_json()) >= 40


def test_index_links_assets_by_content_version(app):
    r = app.test_client().get("/")
    html = r.get_data(as_text=True)
    assert "?v=2\"" not in html and "/static/app.js?v=" in html and r.headers["Cache-Control"] == "no-cache"


def test_installable_app_manifest_service_worker_and_icons(app):
    import json
    c = app.test_client()
    html = c.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in html and "apple-touch-icon" in html
    m = json.loads(c.get("/static/manifest.webmanifest").get_data(as_text=True))
    assert m["display"] == "standalone" and {i["sizes"] for i in m["icons"]} >= {"192x192", "512x512"}
    for i in m["icons"]:
        r = c.get(i["src"])
        assert r.status_code == 200 and r.data[:4] == bytes([137, 80, 78, 71])  # nagłówek PNG
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["Content-Type"] and "/api/" in sw.get_data(as_text=True)
