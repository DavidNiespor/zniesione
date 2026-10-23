"""Brudne jaja jako osobna pula, wpisy z wcześniejszą datą, poprawianie i usuwanie wpisów, budynki ze stadami."""
from datetime import date, timedelta


def pools(c):
    return c.get("/api/my/eggs?days=1").get_json()["stock"]


def test_dirty_eggs_can_be_sold_or_given_but_not_offered(app, farmer):
    c, _ = farmer
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 50})
    p = c.post("/api/my/eggs", {"kind": "sort", "good": 40, "dirty": 8, "damaged": 2}).get_json()["stock"]
    assert (p["eggs"], p["dirty"], p["unsorted"]) == (40, 8, 0)
    assert c.post("/api/my/eggs", {"kind": "gift", "eggs": 9, "who": "Mama", "pool": "dirty"}).status_code == 409
    assert c.post("/api/my/eggs", {"kind": "gift", "eggs": 5, "who": "Mama", "pool": "dirty"}).get_json()["stock"]["dirty"] == 3
    assert c.post("/api/my/eggs", {"kind": "gift", "eggs": 1, "who": "Mama", "pool": "zle"}).status_code == 400
    s = c.post("/api/my/sales", {"eggs": 3, "source": "dirty", "method": "cash", "price": 0.5}).get_json()
    assert pools(c)["dirty"] == 0 and pools(c)["eggs"] == 40
    assert c.delete(f"/api/my/sales/{s['id']}").status_code == 200
    assert pools(c)["dirty"] == 3


def test_entry_with_past_date_and_limits(app, farmer):
    c, _ = farmer
    y = (date.today() - timedelta(days=2)).isoformat()
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 20, "date": y})
    e = c.get("/api/my/eggs?days=7").get_json()["entries"][0]
    assert e["at"] == y + "T12:00:00"
    for bad in ((date.today() + timedelta(days=1)).isoformat(), "2020-01-01", "wczoraj"):
        assert c.post("/api/my/eggs", {"kind": "collect", "eggs": 1, "date": bad}).status_code == 400
    s = c.post("/api/my/sales", {"eggs": 1, "source": "free", "method": "cash", "date": y})
    assert s.status_code == 409   # dobrych jaj brak (nieposortowane)


def test_edit_and_delete_entries_revert_pools(app, farmer, farmer2):
    c, _ = farmer
    col = c.post("/api/my/eggs", {"kind": "collect", "eggs": 30}).get_json()
    eid = c.get("/api/my/eggs").get_json()["entries"][0]["id"]
    assert c.patch(f"/api/my/eggs/{eid}", {"eggs": 25, "note": "poprawka"}).get_json()["stock"]["unsorted"] == 25
    assert farmer2[0].patch(f"/api/my/eggs/{eid}", {"eggs": 1}).status_code == 404
    c.post("/api/my/eggs", {"kind": "sort", "good": 20, "dirty": 4, "damaged": 1})
    sort_id = c.get("/api/my/eggs").get_json()["entries"][0]["id"]
    assert c.delete(f"/api/my/eggs/{eid}").status_code == 409            # najpierw sortowanie
    g = c.post("/api/my/eggs", {"kind": "gift", "eggs": 5, "who": "Mama"})
    gid = c.get("/api/my/eggs").get_json()["entries"][0]["id"]
    assert c.patch(f"/api/my/eggs/{gid}", {"eggs": 8}).get_json()["stock"]["eggs"] == 12
    assert c.patch(f"/api/my/eggs/{gid}", {"eggs": 30}).status_code == 409
    assert c.delete(f"/api/my/eggs/{sort_id}").status_code == 409          # 8 dobrych już rozdane
    assert c.delete(f"/api/my/eggs/{gid}").get_json()["stock"]["eggs"] == 20
    p = c.delete(f"/api/my/eggs/{sort_id}").get_json()["stock"]
    assert (p["eggs"], p["dirty"], p["unsorted"]) == (0, 0, 25)
    assert c.delete(f"/api/my/eggs/{eid}").get_json()["stock"]["unsorted"] == 0
    assert c.get("/api/my/eggs").get_json()["entries"] == []
    assert g.status_code == 201 and col


def test_sale_date_and_notes_can_be_corrected(app, farmer):
    c, _ = farmer
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 10, "sorted": True})
    sid = c.post("/api/my/sales", {"eggs": 10, "method": "cash"}).get_json()["id"]
    y = (date.today() - timedelta(days=3)).isoformat()
    s = c.patch(f"/api/my/sales/{sid}", {"date": y, "notes": "targ"}).get_json()
    assert s["at"].startswith(y) and s["notes"] == "targ"
    assert c.patch(f"/api/my/sales/{sid}", {"date": "2000-01-01"}).status_code == 400


def test_buildings_hold_many_flocks_and_collection_by_building(app, farmer, farmer2):
    c, _ = farmer
    b = c.post("/api/my/buildings", {"name": "Kurnik duży"}).get_json()
    assert c.post("/api/my/buildings", {"name": ""}).status_code == 400
    for name, birds in (("Nioski 2025", 40), ("Zielononóżki", 15)):
        r = c.post("/api/my/flocks", {"name": name, "birds": birds, "building_id": b["id"]})
        assert r.status_code in (200, 201), r.get_json()
    other = farmer2[0].post("/api/my/buildings", {"name": "Obcy"}).get_json()
    assert c.post("/api/my/flocks", {"name": "X", "birds": 1, "building_id": other["id"]}).status_code == 400
    lst = c.get("/api/my/buildings").get_json()
    assert lst[0]["birds"] == 55 and len(lst[0]["flocks"]) == 2
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 33, "building_id": b["id"]})
    assert c.post("/api/my/eggs", {"kind": "collect", "eggs": 1, "building_id": other["id"]}).status_code == 400
    assert c.get("/api/my/eggs").get_json()["by_building"] == {"Kurnik duży": 33}
    assert c.patch(f"/api/my/buildings/{b['id']}", {"name": "Kurnik A"}).get_json()["name"] == "Kurnik A"
    assert farmer2[0].delete(f"/api/my/buildings/{b['id']}").status_code == 404
    assert c.delete(f"/api/my/buildings/{b['id']}").status_code == 200
    assert c.get("/api/my/buildings").get_json() == []
