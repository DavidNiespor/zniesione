"""Kilku zarządzających jedną farmą: osobne loginy, właściciel zarządza zespołem, wpisy mają autora."""
from conftest import Client


def test_owner_adds_member_who_logs_in_separately_and_entries_show_author(app, farmer, farmer2):
    owner, fid = farmer
    owner.patch(f"/api/my/team/{owner.get('/api/me').get_json()['id']}", {"name": "Dawid"})
    for bad in ({"email": "x", "name": "Ola", "password": "haslo1234"}, {"email": "o@x.pl", "name": "", "password": "haslo1234"},
                {"email": "o@x.pl", "name": "Ola", "password": "krotkie"}, {"email": "b@x.pl", "name": "Ola", "password": "haslo1234"}):
        assert owner.post("/api/my/team", bad).status_code in (400, 409), bad
    m = owner.post("/api/my/team", {"email": "ola@x.pl", "name": "Ola", "password": "haslo1234"}).get_json()
    assert (m["name"], m["owner"]) == ("Ola", False)
    ola = Client(app)
    assert ola.post("/api/auth/login", {"email": "ola@x.pl", "password": "haslo1234"}).get_json()["farm_id"] == fid
    assert ola.get("/api/me").get_json()["owner"] is False
    owner.post("/api/my/eggs", {"kind": "collect", "eggs": 30})
    ola.post("/api/my/eggs", {"kind": "collect", "eggs": 12})
    ola.post("/api/my/eggs", {"kind": "sort", "good": 40, "dirty": 2})
    by = [(e["kind"], e["eggs"], e["by_name"]) for e in owner.get("/api/my/eggs").get_json()["entries"]]
    assert by == [("sort", 40, "Ola"), ("collect", 12, "Ola"), ("collect", 30, "Dawid")]
    s = ola.post("/api/my/sales", {"eggs": 10, "method": "cash"}).get_json()
    assert owner.get("/api/my/sales").get_json()[0]["by_name"] == "Ola" and s["total"] == 0
    assert [x["name"] for x in owner.get("/api/my/team").get_json()] == ["Dawid", "Ola"]
    assert ola.post("/api/my/team", {"email": "z@x.pl", "name": "Z", "password": "haslo1234"}).status_code == 403   # nie właściciel
    assert ola.delete(f"/api/my/team/{m['id']}").status_code == 403
    assert ola.patch(f"/api/my/team/{m['id']}", {"name": "Aleksandra"}).get_json()["name"] == "Aleksandra"           # własne imię
    assert farmer2[0].patch(f"/api/my/team/{m['id']}", {"name": "X"}).status_code == 404
    me = owner.get("/api/me").get_json()["id"]
    assert owner.delete(f"/api/my/team/{me}").status_code == 409
    assert owner.delete(f"/api/my/team/{m['id']}").status_code == 200
    assert ola.get("/api/me").status_code == 401


def test_change_password(app, farmer):
    c, _ = farmer
    assert c.put("/api/my/password", {"old": "zle", "new": "nowehaslo1"}).status_code == 403
    assert c.put("/api/my/password", {"old": "haslo12345", "new": "krotkie"}).status_code == 400
    assert c.put("/api/my/password", {"old": "haslo12345", "new": "nowehaslo1"}).status_code == 200
    assert Client(app).post("/api/auth/login", {"email": "a@x.pl", "password": "nowehaslo1"}).status_code == 200


def test_author_tracking_does_not_lock_database_between_requests(app, farmer, tmp_path):
    """Dwa równoległe zapytania (np. dwa podglądy kamer) zapisują do bazy: oznaczenie autora nie może trzymać blokady."""
    import sqlite3
    from zniesione import db as dbm
    path = app.config["DATABASE"]
    a, b = sqlite3.connect(path, timeout=0.3), sqlite3.connect(path, timeout=0.3)
    try:
        dbm.set_user(a, 1)
        a.execute("SELECT * FROM farms").fetchall()          # zapytanie A czyta (np. czeka na kamerę)
        dbm.set_user(b, 1)
        b.execute("UPDATE farms SET remind_sent=''")         # zapytanie B w tym czasie zapisuje
        b.commit()
        a.execute("UPDATE farms SET remind_sent=''")
        a.commit()
    finally:
        a.close(), b.close()
