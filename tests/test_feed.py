"""Pasza: magazyn składników, przyjęcie zakupu z wydatkiem, receptury z wartościami odżywczymi, mieszalnia."""


def item(c, name, **kw):
    return c.post("/api/my/feed/items", {"name": name, **kw}).get_json()["id"]


def test_feed_items_purchase_adjust_and_low_stock(app, farmer, farmer2):
    c, _ = farmer
    for bad in ({"name": ""}, {"name": "X", "category": "kamienie"}, {"name": "X", "price": -1}, {"name": "X", "protein": 120},
                {"name": "X", "stock": -5}):
        assert c.post("/api/my/feed/items", bad).status_code == 400, bad
    w = item(c, "Pszenica", category="grain", stock=50, min_stock=100, price=1.1, protein=11.5, energy=2900)
    f = c.get("/api/my/feed").get_json()
    assert f["items"][0]["low"] is True and f["low"] == 1 and f["value"] == 55
    r = c.post(f"/api/my/feed/items/{w}/purchase", {"qty": 500, "price": 1.2, "supplier": "GS Lipowa"}).get_json()
    assert r["item"]["stock"] == 550 and r["item"]["price"] == 1.2 and not r["item"]["low"]
    ex = c.get("/api/my/expenses").get_json()
    assert ex["entries"][0]["name"] == "Pszenica" and ex["entries"][0]["total"] == 600 and ex["by_category"] == {"Pasza i zboże": 600}
    c.post(f"/api/my/feed/items/{w}/purchase", {"qty": 10, "price": 0, "expense": False})       # np. własne zboże
    assert c.get("/api/my/expenses").get_json()["total"] == 600
    assert c.post(f"/api/my/feed/items/{w}/purchase", {"qty": 0, "price": 1}).status_code == 400
    assert c.post(f"/api/my/feed/items/{w}/adjust", {"stock": 500, "note": "spis"}).get_json()["stock"] == 500
    assert [m["kind"] for m in c.get("/api/my/feed").get_json()["moves"]][:3] == ["adjust", "purchase", "purchase"]
    o = farmer2[0]
    assert o.get("/api/my/feed").get_json()["items"] == []
    assert o.post(f"/api/my/feed/items/{w}/purchase", {"qty": 1, "price": 1}).status_code == 404
    assert o.patch(f"/api/my/feed/items/{w}", {"name": "X"}).status_code == 404


def test_recipe_nutrition_and_mixing(app, farmer, farmer2):
    c, _ = farmer
    w = item(c, "Pszenica", stock=100, price=1.0, protein=12, energy=2900, calcium=0.5)
    k = item(c, "Kukurydza", stock=100, price=1.2, protein=9, energy=3350, calcium=0.2)
    s = item(c, "Śruta sojowa", category="protein", stock=5, price=2.5, protein=46, energy=2400, calcium=3)
    m = item(c, "Kreda pastewna", category="mineral", stock=50, price=0.6, calcium=370)
    bad = {"name": "Zła", "items": [{"item_id": w, "percent": 60}, {"item_id": k, "percent": 30}]}
    r = c.post("/api/my/feed/recipes", bad)
    assert r.status_code == 400 and "90.0%" in r.get_json()["error"]
    assert c.post("/api/my/feed/recipes", {"name": "Dup", "items": [{"item_id": w, "percent": 50}, {"item_id": w, "percent": 50}]}).status_code == 400
    rec = c.post("/api/my/feed/recipes", {"name": "Nioski lato", "season": "summer", "items": [
        {"item_id": w, "percent": 40}, {"item_id": k, "percent": 30}, {"item_id": s, "percent": 20}, {"item_id": m, "percent": 10}]}).get_json()
    n = rec["nutrition"]
    assert rec["total_percent"] == 100 and n["protein"] == 16.7 and n["protein_share"] == 90       # kreda bez białka liczona jako 0
    assert n["calcium"] == 37.86 and n["price"] == 1.32
    assert c.patch(f"/api/my/feed/recipes/{rec['id']}", {"active": True}).get_json()["active"] is True
    r = c.post("/api/my/feed/mix", {"recipe_id": rec["id"], "kg": 50})                                 # soja: potrzeba 10 kg, jest 5
    assert r.status_code == 409 and "Śruta sojowa: potrzeba 10 kg, jest 5" in r.get_json()["error"]
    r = c.post("/api/my/feed/mix", {"recipe_id": rec["id"], "kg": 25}).get_json()
    assert r["cost"] == 33 and {u["name"]: u["kg"] for u in r["used"]} == {"Pszenica": 10, "Kukurydza": 7.5, "Śruta sojowa": 5, "Kreda pastewna": 2.5}
    st = {i["name"]: i["stock"] for i in c.get("/api/my/feed").get_json()["items"]}
    assert st == {"Pszenica": 90, "Kukurydza": 92.5, "Śruta sojowa": 0, "Kreda pastewna": 47.5}
    assert c.get("/api/my/feed").get_json()["mixes"][0]["recipe"] == "Nioski lato"
    assert c.delete(f"/api/my/feed/items/{w}").status_code == 409                                       # w recepturze
    assert farmer2[0].post("/api/my/feed/mix", {"recipe_id": rec["id"], "kg": 1}).status_code == 404
    assert farmer2[0].delete(f"/api/my/feed/recipes/{rec['id']}").status_code == 404
    assert c.delete(f"/api/my/feed/recipes/{rec['id']}").status_code == 200 and c.delete(f"/api/my/feed/items/{w}").status_code == 200
