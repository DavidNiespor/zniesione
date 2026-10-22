from conftest import Client, make, online_device


def test_csrf_header_required(app):
    r = app.test_client().post("/api/auth/login", json={"email": "a", "password": "b"})
    assert r.status_code == 403


def test_register_login_roles(app, farmer, anon):
    c, fid = farmer
    assert c.get("/api/me").get_json()["role"] == "farmer"
    assert anon.get("/api/me").status_code == 401
    assert c.get("/api/admin/devices").status_code == 403
    assert anon.post("/api/auth/login", {"email": "a@x.pl", "password": "zle"}).status_code == 401
    assert anon.post("/api/auth/register", {"email": "a@x.pl", "password": "haslo12345", "farm_name": "x"}).status_code == 409
    assert anon.post("/api/auth/register", {"email": "z@x.pl", "password": "krotkie", "farm_name": "x"}).status_code == 400


def test_public_search_and_order_flow(app, farmer, anon):
    c, fid = farmer
    c.put("/api/my/farm", {"price10": 14, "stock": 5, "descr": "Eko"})
    assert [f["name"] for f in anon.get("/api/farms?q=45-0").get_json()] == ["Farma A"]
    assert anon.get("/api/farms?q=nic").get_json() == []
    r = anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "123456789", "qty": 3, "mode": "weekly", "pickup": "delivery"})
    assert r.status_code == 201 and r.get_json()["total"] == 42
    oid = r.get_json()["id"]
    assert anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "abc", "qty": 3}).status_code == 400
    assert anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "123456789", "qty": 0}).status_code == 400
    assert anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "123456789", "qty": True}).status_code == 400
    assert c.post(f"/api/my/orders/{oid}/confirm").status_code == 200
    assert c.post(f"/api/my/orders/{oid}/confirm").status_code == 409
    assert anon.get(f"/api/farms/{fid}").get_json()["stock"] == 2
    big = anon.post(f"/api/farms/{fid}/orders", {"name": "A", "phone": "123456789", "qty": 10}).get_json()["id"]
    assert c.post(f"/api/my/orders/{big}/confirm").status_code == 409


def test_farmer_cannot_touch_other_farm_order(app, farmer, farmer2, anon):
    (c1, f1), (c2, f2) = farmer, farmer2
    oid = anon.post(f"/api/farms/{f1}/orders", {"name": "Jan", "phone": "123456789", "qty": 1}).get_json()["id"]
    assert c2.post(f"/api/my/orders/{oid}/reject").status_code == 404
    assert c2.get("/api/my/orders").get_json() == []


def test_catalog_restriction(app, farmer):
    c, _ = farmer
    assert {m["id"] for m in c.get("/api/catalog").get_json()} == {"tr4", "trs3", "wsp", "shp"}
    assert c.post("/api/my/device-orders", {"model": "own"}).status_code == 400
    assert c.post("/api/my/device-orders", {"model": "tr4", "tunnel": "ts"}).status_code == 400
    assert c.post("/api/my/device-orders", {"model": "shp"}).status_code == 201


def test_admin_assignment_and_ip_allocation(app, admin, farmer, farmer2):
    (c1, f1), (c2, f2) = farmer, farmer2
    d1 = c1.post("/api/my/device-orders", {"model": "tr4"}).get_json()["id"]
    d2 = c2.post("/api/my/device-orders", {"model": "trs3"}).get_json()["id"]
    ips = {d["ip"] for d in admin.get("/api/admin/devices").get_json()}
    assert len(ips) == 2 and all(i.startswith("10.8.0.") for i in ips)
    assert c2.get(f"/api/my/devices/{d1}/yaml").status_code == 404
    assert admin.patch(f"/api/admin/devices/{d1}", {"farm_id": f2}).status_code == 200
    assert [d["id"] for d in c2.get("/api/my/devices").get_json()].count(d1) == 1
    assert c1.get("/api/my/devices").get_json() == []
    assert admin.patch(f"/api/admin/devices/{d1}", {"stage": 3}).status_code == 400
    assert admin.patch(f"/api/admin/devices/{d1}", {"farm_id": 999}).status_code == 400
    r = admin.post("/api/admin/devices", {"model": "wsp", "farm_id": f1, "addr": "hala"})
    assert r.status_code == 201
    assert admin.post("/api/admin/devices", {"model": "own", "farm_id": f1}).status_code == 400


def test_yaml_generation_and_config(app, admin, farmer):
    c, _ = farmer
    did = c.post("/api/my/device-orders", {"model": "tr4"}).get_json()["id"]
    assert c.get(f"/api/my/devices/{did}/yaml").status_code == 409
    admin.patch(f"/api/admin/devices/{did}", {"stage": 1})
    y = c.get(f"/api/my/devices/{did}/yaml").get_data(as_text=True)
    assert "board: esp32dev" in y and "GPIO21" in y and "GPIO5" in y and "wireguard:" in y and "10.8.0.10" in y
    assert admin.put("/api/admin/config", {"net": "10.9.1", "wg_endpoint": "vpn.example.pl"}).status_code == 200
    assert admin.put("/api/admin/config", {"net": "zle"}).status_code == 400
    assert admin.put("/api/admin/config", {"bogus": "1"}).status_code == 400
    assert "peer_endpoint: vpn.example.pl" in c.get(f"/api/my/devices/{did}/yaml").get_data(as_text=True)
    d3 = admin.post("/api/admin/devices", {"model": "shp", "farm_id": 1}).get_json()["id"]
    admin.patch(f"/api/admin/devices/{d3}", {"stage": 1})
    assert "nie używa ESPHome" in c.get(f"/api/my/devices/{d3}/yaml").get_data(as_text=True)
    d4 = c.post("/api/my/device-orders", {"model": "trs3", "tunnel": "ts"}).get_json()["id"]
    admin.patch(f"/api/admin/devices/{d4}", {"stage": 1})
    y4 = c.get(f"/api/my/devices/{d4}/yaml").get_data(as_text=True)
    assert "esphome-tailscale" in y4 and "sn74hc595" in y4 and "data_pin: 7" in y4


def test_readings_auth_and_validation(app, admin, farmer):
    did, key = online_device(app, admin, farmer)
    anon = Client(app)
    assert anon.post("/api/device/readings", {"t": 20}, headers={"X-Api-Key": "zly"}).status_code == 401
    assert anon.post("/api/device/readings", {"t": 999}, headers={"X-Api-Key": key}).status_code == 400
    d = farmer[0].get("/api/my/devices").get_json()[0]
    assert d["online"] and d["reading"]["t"] == 20
