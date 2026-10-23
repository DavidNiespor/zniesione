"""Lista codziennych obowiązków na Starcie: pasza, woda, jaja, kury; godzina, kto, ilości do statystyk."""
from datetime import date, timedelta

from conftest import Client


def test_config_is_optional_and_validated(app, farmer):
    c, _ = farmer
    assert c.get("/api/my/chores/config").get_json() == {"kinds": [], "amounts": True}     # domyślnie wyłączone
    assert c.put("/api/my/chores/config", {"kinds": ["feed", "x"]}).status_code == 400
    assert c.put("/api/my/chores/config", {"kinds": "feed"}).status_code == 400
    r = c.put("/api/my/chores/config", {"kinds": ["hens", "feed", "water", "eggs"], "amounts": False}).get_json()
    assert r == {"kinds": ["feed", "water", "eggs", "hens"], "amounts": False}


def test_check_off_with_time_person_amounts_and_undo(app, farmer, farmer2):
    c, fid = farmer
    c.patch(f"/api/my/team/{c.get('/api/me').get_json()['id']}", {"name": "Dawid"})
    c.post("/api/my/flocks", {"name": "Nioski", "birds": 20})
    for bad in ({"kind": "eggs"}, {"kind": "feed", "amount": -1}, {"kind": "feed", "amount": "2"}, {"kind": "hens", "count": 1.5},
                {"kind": "water", "amount": True}, {"kind": "feed", "date": (date.today() + timedelta(days=1)).isoformat()}):
        assert c.post("/api/my/chores", bad).status_code == 400, bad
    f = c.post("/api/my/chores", {"kind": "feed", "amount": 2.5}).get_json()
    assert f["by_name"] == "Dawid" and f["amount"] == 2.5 and f["day"] == date.today().isoformat()
    c.post("/api/my/chores", {"kind": "feed", "amount": 1})
    c.post("/api/my/chores", {"kind": "water"})                                      # bez ilości
    c.post("/api/my/chores", {"kind": "hens", "count": 19})
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 15})                           # jaja odhaczają się same
    d = c.get("/api/my/chores").get_json()
    assert d["birds"] == 20 and [len(d["items"][k]) for k in ("feed", "water", "eggs", "hens")] == [2, 1, 1, 1]
    assert d["items"]["eggs"][0]["auto"] and d["items"]["eggs"][0]["amount"] == 15 and d["items"]["hens"][0]["amount"] == 19
    assert farmer2[0].get("/api/my/chores").get_json()["items"]["feed"] == []
    assert farmer2[0].delete(f"/api/my/chores/{f['id']}").status_code == 404
    assert c.delete(f"/api/my/chores/{f['id']}").status_code == 200
    h = c.get("/api/my/chores/history?days=3").get_json()
    assert len(h) == 3 and h[0]["day"] == date.today().isoformat()
    assert (h[0]["feed"]["amount"], len(h[0]["feed"]["times"]), h[0]["water"]["amount"], h[0]["hens"]["amount"], h[0]["eggs"]["amount"]) == (1, 1, None, 19, 15)
    y = (date.today() - timedelta(days=1)).isoformat()
    c.post("/api/my/chores", {"kind": "feed", "amount": 3, "date": y})               # dopisane za wczoraj
    a = c.get("/api/my/analytics?days=7").get_json()
    assert (a["daily"][-1]["feed"], a["daily"][-2]["feed"], a["daily"][-3]["feed"]) == (1, 3, None)
    assert (a["totals"]["feed"], a["totals"]["feed_days"], a["totals"]["feed_per_hen_g"]) == (4, 2, 100)   # 4 kg / 2 dni / 20 kur
    assert Client(app).get("/api/my/chores").status_code == 401
