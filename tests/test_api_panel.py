"""API panelu rolnika: drzwi, harmonogramy (wschód, zachód, czas trwania), restart, dziennik, odczyty, uprawnienia."""
from datetime import datetime, timedelta

from conftest import Client, online_device
from zniesione import create_app, db as dbm, services as sv

LAT, LON = 50.67, 17.93  # Opole


def tick_at(app, now):
    with app.app_context():
        dbm.get().execute("UPDATE devices SET last_seen=?", (now.isoformat(),))
        dbm.get().commit()
    return sv.tick(app, now)


def restart(app):
    """Symulowany restart: nowa instancja aplikacji na tej samej bazie, bez stanu w pamięci."""
    a = create_app({"DATABASE": app.config["DATABASE"], "TESTING": True, "SECRET_KEY": "t"})
    a.sent = []

    def fake(dev, ch, state):
        a.sent.append((dev["code"], ch, state))
        ok = a.config.get("SEND_OK", True)
        return ok, None if ok else "timeout"
    a.config["SEND"] = fake
    return a


def chan(app, key):
    with app.app_context():
        return dict(dbm.get().execute("SELECT * FROM channels WHERE key=?", (key,)).fetchone())


def never_both_door_relays(sent):
    on = {}
    for x in sent:
        on[x[1]] = x[2]
        assert not (on.get("ch2") and on.get("ch3")), sent


def test_devices_payload_has_rules_readings_and_door_setting(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer, kinds={"ch4": "vent"})
    c.put(f"/api/my/devices/{did}/rules/ch4", {"threshold": 26.5, "enabled": False})
    d = c.get("/api/my/devices").get_json()[0]
    ch = {x["key"]: x for x in d["channels"]}
    assert ch["ch4"]["rule"] == {"threshold": 26.5, "enabled": False} and ch["ch1"]["rule"] is None
    assert d["door_run_s"] == 20 and d["door"] is None and d["readings"][0]["t"] == 20 and d["last_seen"]
    assert c.put(f"/api/my/devices/{did}/rules/ch4", {"threshold": 25, "enabled": "tak"}).status_code == 400


def test_door_run_setting_validation_and_ownership(app, admin, farmer, farmer2):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    for bad in (0, 301, "20", True, 2.5):
        assert c.patch(f"/api/my/devices/{did}", {"door_run_s": bad}).status_code == 400
    assert c.patch(f"/api/my/devices/{did}", {"door_run_s": 35}).get_json()["door_run_s"] == 35
    assert farmer2[0].patch(f"/api/my/devices/{did}", {"door_run_s": 5}).status_code == 404


def test_manual_door_is_a_pulse_with_interlock(app, admin, farmer, farmer2):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    url = f"/api/my/devices/{did}/door"
    assert c.post(url, {"action": "wyważ"}).status_code == 400
    assert farmer2[0].post(url, {"action": "open"}).status_code == 404
    assert c.post(url, {"action": "open"}).status_code == 200
    assert app.sent[-1][1:] == ("ch2", True) and chan(app, "ch2")["off_at"]
    assert c.get("/api/my/devices").get_json()[0]["door"] == "open"
    assert c.post(url, {"action": "close"}).status_code == 200         # najpierw wyłącza otwieranie
    assert [x[1:] for x in app.sent[-2:]] == [("ch2", False), ("ch3", True)]
    never_both_door_relays(app.sent)
    assert tick_at(app, datetime.now() + timedelta(seconds=10)) == []  # silnik pracuje jeszcze 20 s
    sent = tick_at(app, datetime.now() + timedelta(seconds=25))
    assert [x[1:3] for x in sent] == [("ch3", False)] and chan(app, "ch3")["off_at"] is None
    for k in ("ch2", "ch3"):
        c.patch(f"/api/my/devices/{did}/channels/{k}", {"kind": "light"})
    assert c.post(url, {"action": "open"}).status_code == 409          # brak przekaźnika drzwi


def test_raw_door_relay_also_turns_off_by_itself(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    assert c.post(f"/api/my/devices/{did}/channels/ch2", {"state": True}).status_code == 200
    assert [x[1:3] for x in tick_at(app, datetime.now() + timedelta(seconds=21))] == [("ch2", False)]


def test_door_off_survives_restart_and_device_failure(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    assert c.post(f"/api/my/devices/{did}/door", {"action": "open"}).status_code == 200
    a2 = restart(app)                     # aplikacja padła w trakcie pracy silnika drzwi
    a2.config["SEND_OK"] = False          # a sterownik chwilowo nie odpowiada
    t = datetime.now() + timedelta(seconds=25)
    assert [x[1:] for x in tick_at(a2, t)] == [("ch2", False, False)]
    assert chan(a2, "ch2")["state"] == 1 and chan(a2, "ch2")["off_at"]
    assert tick_at(a2, t + timedelta(seconds=10)) == []                # odstęp przed ponowieniem
    a2.config["SEND_OK"] = True
    assert [x[1:] for x in tick_at(a2, t + timedelta(seconds=35))] == [("ch2", False, True)]
    assert chan(a2, "ch2")["state"] == 0


def test_door_command_without_answer_is_still_switched_off(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    app.config["SEND_OK"] = False
    assert c.post(f"/api/my/devices/{did}/door", {"action": "open"}).status_code == 502
    app.config["SEND_OK"] = True          # przekaźnik mógł zadziałać mimo błędu: silnik wysyła wyłączenie
    assert [x[1:3] for x in tick_at(app, datetime.now() + timedelta(seconds=1))] == [("ch2", False)]


def test_sun_schedules_need_farm_location(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    light = {"ch": "ch1", "mode": "sunrise", "offset_min": -30, "t_off": "07:00", "days": "a"}
    r = c.post(f"/api/my/devices/{did}/schedules", light)
    assert r.status_code == 400 and "położenie" in r.get_json()["error"]
    c.put("/api/my/farm", {"lat": LAT, "lon": LON})
    r = c.post(f"/api/my/devices/{did}/schedules", light)
    assert r.status_code == 201
    rise = sv.local_sun(LAT, LON, datetime.now().date())[0] - timedelta(minutes=30)
    s = r.get_json()
    assert s["mode"] == "sunrise" and s["offset_min"] == -30 and s["t_off"] == "07:00"
    if rise.time() < datetime.strptime("07:00", "%H:%M").time():
        assert s["today_on"] == rise.strftime("%H:%M") and s["today_off"] == "07:00"
    else:  # zimą wschód −30 min bywa po 07:00: tego dnia światło się nie włącza
        assert s["today_on"] is None


def test_sunrise_light_until_seven_via_engine(app, admin, farmer):
    """Kryterium odbioru: światło od wschodu −30 min do 07:00."""
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    c.put("/api/my/farm", {"lat": LAT, "lon": LON})
    c.post(f"/api/my/devices/{did}/schedules",
           {"ch": "ch1", "mode": "sunrise", "offset_min": -30, "t_off": "07:00", "days": "a"})
    day = datetime(2027, 4, 15)
    start = sv.local_sun(LAT, LON, day.date())[0] - timedelta(minutes=30)
    assert start.time() < datetime(2027, 4, 15, 7).time()
    assert tick_at(app, start - timedelta(minutes=1)) == []
    assert [x[1:] for x in tick_at(app, start + timedelta(minutes=1))] == [("ch1", True, True)]
    assert [x[1:] for x in tick_at(app, day.replace(hour=7))] == [("ch1", False, True)]


def test_door_schedule_from_sunrise_to_sunset(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    c.put("/api/my/farm", {"lat": LAT, "lon": LON})
    base = f"/api/my/devices/{did}/schedules"
    door = {"ch": "ch2", "mode": "sunrise", "off_mode": "sunset", "off_offset_min": 20, "days": "a"}
    assert c.post(base, {**door, "duration_s": 60}).status_code == 400   # drzwi bez czasu trwania
    assert c.post(base, door).status_code == 201
    day = datetime(2027, 4, 15)
    rise, sset = sv.local_sun(LAT, LON, day.date())
    t = rise + timedelta(minutes=1)
    assert [x[1:3] for x in tick_at(app, t)] == [("ch2", True)]
    assert tick_at(app, t + timedelta(seconds=5)) == []                    # bez powtórnego impulsu
    assert [x[1:3] for x in tick_at(app, t + timedelta(seconds=21))] == [("ch2", False)]
    c.post(f"/api/my/devices/{did}/door", {"action": "close"})           # rolnik zamyka ręcznie w dzień
    tick_at(app, t + timedelta(hours=2))                                   # koniec impulsu zamykania
    assert tick_at(app, t + timedelta(hours=3)) == []                      # ręczna zmiana obowiązuje
    t2 = sset + timedelta(minutes=21)
    sent = tick_at(app, t2)
    assert sent == [] and c.get("/api/my/devices").get_json()[0]["door"] == "closed"  # już zamknięte
    c.post(f"/api/my/devices/{did}/door", {"action": "open"})          # i otwiera ręcznie wieczorem
    assert [x[1:3] for x in tick_at(app, t2 + timedelta(minutes=1))] == [("ch2", False)]
    assert [x[1:3] for x in tick_at(app, (rise + timedelta(days=1, minutes=1)))] == []  # otwarte: bez zmian
    never_both_door_relays(app.sent)


def test_duration_schedule_switches_off_after_restart(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer, kinds={"ch5": "feeder"})
    base = f"/api/my/devices/{did}/schedules"
    for bad in (0, 43201, "90", 1.5):
        assert c.post(base, {"ch": "ch5", "t_on": "07:00", "duration_s": bad, "days": "a"}).status_code == 400
    s = c.post(base, {"ch": "ch5", "t_on": "07:00", "duration_s": 90, "days": "a"}).get_json()
    assert s["today_on"] == "07:00" and s["today_off"] == "07:01" and s["t_off"] == ""
    t = datetime(2027, 4, 15, 7, 0, 10)
    assert [x[1:] for x in tick_at(app, t)] == [("ch5", True, True)]
    assert chan(app, "ch5")["off_at"] == "2027-04-15T07:01:30"
    a2 = restart(app)
    assert tick_at(a2, t + timedelta(seconds=60)) == []
    assert [x[1:] for x in tick_at(a2, t + timedelta(seconds=81))] == [("ch5", False, True)]
    assert tick_at(a2, t + timedelta(seconds=120)) == []


def test_schedule_patch_toggle_validation_and_permissions(app, admin, farmer, farmer2):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    base = f"/api/my/devices/{did}/schedules"
    sid = c.post(base, {"ch": "ch1", "t_on": "06:00", "t_off": "18:00", "days": "a"}).get_json()["id"]
    url = f"{base}/{sid}"
    assert c.patch(url, {"enabled": False}).get_json()["enabled"] is False
    assert tick_at(app, datetime.now().replace(hour=12, minute=0)) == []   # wyłączony nie działa
    r = c.patch(url, {"enabled": True, "t_on": "05:30", "t_off": "07:00", "days": "w"}).get_json()
    assert (r["enabled"], r["t_on"], r["t_off"], r["days"]) == (True, "05:30", "07:00", "w")
    for bad in ({"enabled": "nie"}, {"t_on": "7:00"}, {"t_off": "24:00"}, {"days": "pn"}, {"mode": "noon"},
                {"mode": "sunset"}, {"offset_min": 181}, {"off_offset_min": True}, {"ch": "ch3"}, {"ch": ["ch1"]},
                {"t_on": "07:00"}):
        assert c.patch(url, bad).status_code == 400, bad
    assert farmer2[0].patch(url, {"enabled": False}).status_code == 404
    assert farmer2[0].get(base).status_code == 404
    assert farmer2[0].delete(url).status_code == 404
    assert c.patch(f"{base}/999", {"enabled": False}).status_code == 404
    assert len(c.get(base).get_json()) == 1


def test_manual_change_kept_until_next_schedule_change(app, admin, farmer):
    c, _ = farmer
    did, _k = online_device(app, admin, farmer)
    c.post(f"/api/my/devices/{did}/schedules", {"ch": "ch1", "t_on": "06:00", "t_off": "18:00", "days": "a"})
    day = datetime.now().replace(second=0, microsecond=0)
    assert [x[1:3] for x in tick_at(app, day.replace(hour=7, minute=0))] == [("ch1", True)]
    c.post(f"/api/my/devices/{did}/channels/ch1", {"state": False})        # rolnik gasi światło ręcznie
    assert tick_at(app, day.replace(hour=7, minute=5)) == []
    assert tick_at(app, day.replace(hour=18, minute=0)) == []
    assert [x[1:3] for x in tick_at(app, day.replace(hour=6, minute=0) + timedelta(days=1))] == [("ch1", True)]


def test_event_log_names_sources_and_permissions(app, admin, farmer, farmer2):
    c, _ = farmer
    did, key = online_device(app, admin, farmer, kinds={"ch4": "vent"})
    c.post(f"/api/my/devices/{did}/channels/ch1", {"state": True})
    app.config["SEND_OK"] = False
    c.post(f"/api/my/devices/{did}/channels/ch1", {"state": False})
    app.config["SEND_OK"] = True
    c.put(f"/api/my/devices/{did}/rules/ch4", {"threshold": 25})
    Client(app).post("/api/device/readings", {"t": 30, "h": 50}, headers={"X-Api-Key": key})
    tick_at(app, datetime.now())
    log = c.get(f"/api/my/devices/{did}/log").get_json()
    assert [(e["ch_name"], e["state"], e["src"], e["ok"]) for e in log] == [
        ("Przekaźnik 4", True, "thermostat", True), ("Światło", False, "manual", False), ("Światło", True, "manual", True)]
    assert log[0]["kind"] == "vent" and log[0]["at"]
    assert len(c.get(f"/api/my/devices/{did}/log?limit=1").get_json()) == 1
    for bad in ("0", "201", "abc", "-1"):
        assert c.get(f"/api/my/devices/{did}/log?limit={bad}").status_code == 400
    assert farmer2[0].get(f"/api/my/devices/{did}/log").status_code == 404


def test_readings_history_window_and_permissions(app, admin, farmer, farmer2):
    c, _ = farmer
    did, key = online_device(app, admin, farmer)
    with app.app_context():
        dbm.get().execute("INSERT INTO readings(device_id,t,h,at) VALUES(?,?,?,?)",
                          (did, 5, 90, (datetime.now() - timedelta(hours=30)).isoformat()))
        dbm.get().commit()
    Client(app).post("/api/device/readings", {"t": 22.5, "h": 55}, headers={"X-Api-Key": key})
    day = c.get(f"/api/my/devices/{did}/readings").get_json()
    assert [r["t"] for r in day] == [20, 22.5]
    assert [r["t"] for r in c.get(f"/api/my/devices/{did}/readings?hours=48").get_json()] == [5, 20, 22.5]
    for bad in ("0", "169", "x"):
        assert c.get(f"/api/my/devices/{did}/readings?hours={bad}").status_code == 400
    assert farmer2[0].get(f"/api/my/devices/{did}/readings").status_code == 404
