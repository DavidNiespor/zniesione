"""Stado, dziennik jaj i baza wiedzy: walidacja, uprawnienia, widoczność szkiców."""
from datetime import datetime, timedelta

from conftest import Client
from zniesione import create_app, db as dbm


def test_flocks_crud_validation_and_ownership(app, farmer, farmer2, anon):
    c, _ = farmer
    for bad in ({"name": ""}, {"name": "x" * 61}, {"name": "A", "birds": -1}, {"name": "A", "birds": "40"},
                {"name": "A", "birds": True}, {"name": "A", "since": "2026-13-01"}, {"name": "A", "since": "15.03.2026"},
                {"name": "A", "notes": "x" * 1001}, {"name": ["A"]}):
        assert c.post("/api/my/flocks", bad).status_code == 400, bad
    f = c.post("/api/my/flocks", {"name": "Stado 1", "birds": 48, "breed": "Zielononóżka", "since": "2026-03-15"}).get_json()
    assert (f["birds"], f["notes"]) == (48, "")
    assert c.patch(f"/api/my/flocks/{f['id']}", {"birds": 45, "notes": "2 kury u weterynarza"}).get_json()["birds"] == 45
    assert c.patch(f"/api/my/flocks/{f['id']}", {"birds": 100001}).status_code == 400
    assert farmer2[0].patch(f"/api/my/flocks/{f['id']}", {"birds": 1}).status_code == 404
    assert farmer2[0].delete(f"/api/my/flocks/{f['id']}").status_code == 404
    assert farmer2[0].get("/api/my/flocks").get_json() == []
    assert anon.get("/api/my/flocks").status_code == 401
    assert c.delete(f"/api/my/flocks/{f['id']}").status_code == 200 and c.get("/api/my/flocks").get_json() == []


def test_egg_log_in_pieces_with_damaged_and_losses(app, farmer, farmer2):
    """Jaja liczone na sztuki: brudne i uszkodzone nie trafiają do magazynu (zmiana z opakowań, wymaganie rolnika)."""
    c, fid = farmer
    for bad in ({"kind": "collect", "eggs": 0}, {"kind": "collect", "eggs": 10, "damaged": 11, "sorted": True}, {"kind": "collect", "eggs": "10"},
                {"kind": "steal", "eggs": 1}, {"kind": "collect", "packs": 3}, {"kind": "loss", "eggs": 0}):
        assert c.post("/api/my/eggs", bad).status_code == 400, bad
    st = c.post("/api/my/eggs", {"kind": "collect", "eggs": 38, "damaged": 3, "sorted": True, "note": "od razu posortowane"}).get_json()["stock"]
    assert (st["eggs"], st["free"]) == (35, 35)
    r = c.post("/api/my/eggs", {"kind": "loss", "eggs": 36})
    assert r.status_code == 409 and "tylko 35" in r.get_json()["error"]
    assert c.post("/api/my/eggs", {"kind": "loss", "eggs": 5, "note": "stłuczone"}).get_json()["stock"]["eggs"] == 30
    log = c.get("/api/my/eggs?days=7").get_json()
    assert (log["collected"], log["damaged"], log["good"], log["lost"], log["sold"]) == (38, 3, 35, 5, 0)
    assert [e["kind"] for e in log["entries"]] == ["loss", "sort", "collect"]
    with app.app_context():
        dbm.get().execute("INSERT INTO eggs(farm_id,kind,eggs,at) VALUES(?,?,?,?)",
                          (fid, "collect", 90, (datetime.now() - timedelta(days=20)).isoformat()))
        dbm.get().commit()
    assert c.get("/api/my/eggs?days=7").get_json()["collected"] == 38
    assert c.get("/api/my/eggs?days=30").get_json()["collected"] == 128
    for bad in ("0", "366", "x"):
        assert c.get(f"/api/my/eggs?days={bad}").status_code == 400
    assert farmer2[0].get("/api/my/eggs").get_json()["entries"] == []


def test_knowledge_base_admin_writes_farmer_reads_published(app, admin, farmer, anon):
    c, _ = farmer
    assert c.post("/api/admin/kb", {"title": "Hack", "body": "x"}).status_code == 403
    assert anon.get("/api/kb").status_code == 401
    for bad in ({"title": "ab", "body": "x"}, {"title": "Tytuł", "body": ""}, {"title": "Tytuł", "body": "x", "published": "tak"},
                {"title": "Tytuł", "body": "x", "category": "c" * 61}, {"title": 5, "body": "x"}, {"title": "Tytuł", "body": "x" * 50001}):
        assert admin.post("/api/admin/kb", bad).status_code == 400, bad
    a = admin.post("/api/admin/kb", {"title": "Wentylacja latem", "category": "Porady", "body": "## Upał\nWłącz **wentylator** powyżej 25 °C."}).get_json()
    assert a["published"] is False                                   # domyślnie szkic
    assert c.get("/api/kb").get_json() == [] and c.get(f"/api/kb/{a['id']}").status_code == 404
    assert [x["id"] for x in admin.get("/api/kb").get_json()] == [a["id"]]
    assert admin.put(f"/api/admin/kb/{a['id']}", {"published": True}).get_json()["published"] is True
    lst = c.get("/api/kb").get_json()
    assert lst[0]["title"] == "Wentylacja latem" and "body" not in lst[0] and lst[0]["excerpt"] == "Upał Włącz wentylator powyżej 25 °C."
    assert c.get(f"/api/kb/{a['id']}").get_json()["body"].startswith("## Upał")
    assert [x["id"] for x in c.get("/api/kb?q=WENTYLATOR").get_json()] == [a["id"]]   # bez rozróżniania wielkości liter
    assert [x["id"] for x in c.get("/api/kb?q=upał").get_json()] == [a["id"]]
    assert c.get("/api/kb?q=kury").get_json() == [] and c.get("/api/kb?category=Drzwi").get_json() == []
    assert c.put(f"/api/admin/kb/{a['id']}", {"title": "Zmiana"}).status_code == 403
    assert c.delete(f"/api/admin/kb/{a['id']}").status_code == 403
    assert admin.delete(f"/api/admin/kb/{a['id']}").status_code == 200
    assert admin.put(f"/api/admin/kb/{a['id']}", {"title": "Nie ma"}).status_code == 404


def test_seed_has_flock_egg_log_and_articles(tmp_path):
    a = create_app({"DATABASE": str(tmp_path / "s.db"), "TESTING": True})
    assert a.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
    c = Client(a)
    c.post("/api/auth/login", {"email": "rolnik@zniesione.test", "password": "Rolnik12345!"})
    assert c.get("/api/my/flocks").get_json()[0]["birds"] == 48
    e = c.get("/api/my/eggs?days=8").get_json()
    assert (e["collected"], e["damaged"] + e["dirty"], e["stock"]["unsorted"]) == (295, 5, 24) and e["stock"]["free"] == 30 and e["reserve_needed_7d"] == 30
    titles = [x["title"] for x in c.get("/api/kb").get_json()]
    assert "Pierwsze uruchomienie sterownika" in titles and not any("szkic" in t for t in titles)
