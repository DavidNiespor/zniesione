from datetime import datetime

from conftest import Client, online_device
from zniesione import db as dbm, services as sv

S = lambda on, off, days="a", en=1: {"t_on": on, "t_off": off, "days": days, "enabled": en}


def test_schedule_window_and_overnight():
    d = lambda h, m, day=6: datetime(2026, 10, 19 + day, h, m)  # 19.10.2026 to poniedziałek
    assert sv.sched_active(S("06:00", "18:00"), d(6, 0)) and not sv.sched_active(S("06:00", "18:00"), d(18, 0))
    night = S("22:00", "05:00", "w")  # Pn-Pt, okno przez północ
    assert sv.sched_active(night, datetime(2026, 10, 19, 23, 0))      # pon 23:00
    assert sv.sched_active(night, datetime(2026, 10, 20, 4, 0))       # wt 04:00 (start w pon)
    assert not sv.sched_active(night, datetime(2026, 10, 24, 23, 0))  # sob 23:00
    assert not sv.sched_active(night, datetime(2026, 10, 25, 4, 0))   # nd 04:00 (start w sob)
    assert sv.sched_active(night, datetime(2026, 10, 24, 4, 0))       # sob 04:00 (start w pt)
    assert sv.sched_active(S("08:00", "09:00", "e"), datetime(2026, 10, 24, 8, 30))
    assert not sv.sched_active(S("08:00", "08:00"), datetime(2026, 10, 24, 8, 0))


def test_thermostat_hysteresis():
    assert sv.thermo("vent", 26, 25, False) is True
    assert sv.thermo("vent", 24.5, 25, True) is True      # w strefie histerezy trzyma stan
    assert sv.thermo("vent", 24, 25, True) is False
    assert sv.thermo("heater", 4, 5, False) is True
    assert sv.thermo("heater", 5.5, 5, True) is True
    assert sv.thermo("heater", 6, 5, True) is False


def test_manual_control_logging_and_failure(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    assert c.post(f"/api/my/devices/{did}/channels/ch1", {"state": "tak"}).status_code == 400
    assert c.post(f"/api/my/devices/{did}/channels/ch1", {"state": True}).status_code == 200
    assert app.sent[-1][1:] == ("ch1", True)
    assert c.get("/api/my/devices").get_json()[0]["channels"][0]["state"] == 1
    app.config["SEND_OK"] = False
    assert c.post(f"/api/my/devices/{did}/channels/ch1", {"state": False}).status_code == 502
    assert c.get("/api/my/devices").get_json()[0]["channels"][0]["state"] == 1  # stan nie zmieniony przy błędzie
    with app.app_context():
        assert dbm.get().execute("SELECT COUNT(*) FROM log").fetchone()[0] == 2


def test_control_requires_ownership_and_online(app, admin, farmer, farmer2):
    did, _k = online_device(app, admin, farmer)
    assert farmer2[0].post(f"/api/my/devices/{did}/channels/ch1", {"state": True}).status_code == 404
    d2 = farmer2[0].post("/api/my/device-orders", {"model": "tr4"}).get_json()["id"]
    assert farmer2[0].post(f"/api/my/devices/{d2}/channels/ch1", {"state": True}).status_code == 409


def test_door_interlock(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    assert c.post(f"/api/my/devices/{did}/channels/ch2", {"state": True}).status_code == 200
    assert c.post(f"/api/my/devices/{did}/channels/ch3", {"state": True}).status_code == 409
    c.post(f"/api/my/devices/{did}/channels/ch2", {"state": False})
    assert c.post(f"/api/my/devices/{did}/channels/ch3", {"state": True}).status_code == 200


def test_schedule_crud_validation_and_engine(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    base = f"/api/my/devices/{did}/schedules"
    assert c.post(base, {"ch": "ch2", "t_on": "06:00", "t_off": "07:00", "days": "a"}).status_code == 400   # drzwi
    assert c.post(base, {"ch": "ch1", "t_on": "25:00", "t_off": "07:00", "days": "a"}).status_code == 400
    assert c.post(base, {"ch": "nope", "t_on": "06:00", "t_off": "07:00", "days": "a"}).status_code == 400
    sid = c.post(base, {"ch": "ch1", "t_on": "06:00", "t_off": "18:00", "days": "a"}).get_json()["id"]
    assert len(c.get(base).get_json()) == 1
    assert sv_tick(app, 7, 0) == [(c.get("/api/my/devices").get_json()[0]["code"], "ch1", True, True)]
    assert sv_tick(app, 7, 5) == []                      # brak zmian: nic nie wysyła
    assert sv_tick(app, 19, 0)[0][2] is False            # po oknie wyłącza
    # utracona minuta: silnik porównuje stan, więc nadrabia po restarcie
    assert sv_tick(app, 8, 3)[0][2] is True
    assert c.delete(f"{base}/{sid}").status_code == 200 and c.delete(f"{base}/{sid}").status_code == 404


def sv_tick(app, h, m):
    now = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    with app.app_context():
        dbm.get().execute("UPDATE devices SET last_seen=?", (now.isoformat(),))
        dbm.get().commit()
    return sv.tick(app, now)


def test_thermostat_rule_end_to_end(app, admin, farmer):
    c, _ = farmer
    did, key = online_device(app, admin, farmer, kinds={"ch4": "vent", "ch5": "heater", "ch6": "pump"})
    rp = f"/api/my/devices/{did}/rules"
    assert c.put(f"{rp}/ch6", {"threshold": 25}).status_code == 400          # pompa nie ma termostatu
    assert c.put(f"{rp}/ch4", {"threshold": 999}).status_code == 400
    assert c.put(f"{rp}/ch4", {"threshold": 25}).status_code == 200
    assert c.put(f"{rp}/ch5", {"threshold": 5}).status_code == 200
    cl = Client(app)
    cl.post("/api/device/readings", {"t": 28, "h": 60}, headers={"X-Api-Key": key})
    sent = sv_tick(app, 12, 0)
    assert {(s[1], s[2]) for s in sent} == {("ch4", True)}                    # wentylacja włączona, grzanie nie
    cl.post("/api/device/readings", {"t": 2, "h": 60}, headers={"X-Api-Key": key})
    sent = sv_tick(app, 12, 1)
    assert {(s[1], s[2]) for s in sent} == {("ch4", False), ("ch5", True)}
    assert c.put(f"{rp}/ch5", {"threshold": 5, "enabled": False}).status_code == 200


def test_offline_device_is_skipped_and_marked(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    c.post(f"/api/my/devices/{did}/schedules", {"ch": "ch1", "t_on": "00:00", "t_off": "23:59", "days": "a"})
    now = datetime.now()
    with app.app_context():
        dbm.get().execute("UPDATE devices SET last_seen='2000-01-01T00:00:00'")
        dbm.get().commit()
    assert sv.tick(app, now) == []
    assert c.get("/api/my/devices").get_json()[0]["online"] is False


def test_failed_send_is_retried_next_tick(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    c.post(f"/api/my/devices/{did}/schedules", {"ch": "ch1", "t_on": "06:00", "t_off": "18:00", "days": "a"})
    app.config["SEND_OK"] = False
    assert sv_tick(app, 7, 0)[0][3] is False
    app.config["SEND_OK"] = True
    assert sv_tick(app, 7, 1)[0][3] is True


def test_admin_tick_endpoint_needs_admin(app, admin, farmer):
    assert farmer[0].post("/api/admin/tick").status_code == 403
    assert admin.post("/api/admin/tick").status_code == 200


from zniesione import services as sv  # noqa: E402
