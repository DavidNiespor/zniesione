"""Kilku zarządzających jedną farmą: osobne loginy, właściciel dodaje i usuwa osoby. Każdy wpis zapisuje, kto go zrobił
(db.set_user + wyzwalacze), więc widać, kto zbierał, kto sortował i kto sprzedał."""
import re

from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


def register(app, need, q, commit, body, err):
    def member_json(u):
        return dict(id=u["id"], email=u["email"], name=u["name"] or u["email"].split("@")[0], owner=bool(u["owner"]), me=u["id"] == g.user["id"])

    @app.route("/api/my/team", methods=["GET", "POST"])
    @need("farmer")
    def team():
        fid = g.user["farm_id"]
        if request.method == "POST":
            if not g.user["owner"]:
                return err("Osoby dodaje właściciel farmy", 403)
            b = body()
            email, name, pw = str(b.get("email", "")).strip().lower(), b.get("name", ""), b.get("password", "")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                return err("Niepoprawny e-mail")
            if not isinstance(name, str) or not name.strip() or len(name) > 60:
                return err("Podaj imię (do 60 znaków)")
            if not isinstance(pw, str) or len(pw) < 8:
                return err("Hasło musi mieć co najmniej 8 znaków")
            if q("SELECT 1 FROM users WHERE email=?", email).fetchone():
                return err("Ten e-mail ma już konto", 409)
            uid = q("INSERT INTO users(email,pw,role,farm_id,name,owner) VALUES(?,?,?,?,?,0)", email, generate_password_hash(pw), "farmer", fid,
                    name.strip()).lastrowid
            commit()
            return jsonify(member_json(q("SELECT * FROM users WHERE id=?", uid).fetchone())), 201
        return jsonify([member_json(u) for u in q("SELECT * FROM users WHERE farm_id=? AND role='farmer' ORDER BY owner DESC, id", fid)])

    @app.route("/api/my/team/<int:uid>", methods=["PATCH", "DELETE"])
    @need("farmer")
    def member(uid):
        u = q("SELECT * FROM users WHERE id=? AND farm_id=? AND role='farmer'", uid, g.user["farm_id"]).fetchone()
        if not u:
            return err("Nie znaleziono", 404)
        if request.method == "DELETE":
            if not g.user["owner"]:
                return err("Osoby usuwa właściciel farmy", 403)
            if uid == g.user["id"]:
                return err("Nie można usunąć własnego konta", 409)
            q("DELETE FROM users WHERE id=?", uid)  # wpisy zostają, z imieniem w historii nie (konto usunięte)
            commit()
            return jsonify(ok=True)
        if uid != g.user["id"] and not g.user["owner"]:
            return err("Brak uprawnień", 403)
        b = body()
        if "name" in b:
            if not isinstance(b["name"], str) or not b["name"].strip() or len(b["name"]) > 60:
                return err("Podaj imię (do 60 znaków)")
            q("UPDATE users SET name=? WHERE id=?", b["name"].strip(), uid)
        if "owner" in b:
            if not g.user["owner"] or not isinstance(b["owner"], bool):
                return err("Uprawnienia właściciela nadaje właściciel", 403)
            if not b["owner"] and uid == g.user["id"]:
                return err("Nie możesz odebrać sobie uprawnień właściciela", 409)
            q("UPDATE users SET owner=? WHERE id=?", int(b["owner"]), uid)
        commit()
        return jsonify(member_json(q("SELECT * FROM users WHERE id=?", uid).fetchone()))

    @app.put("/api/my/password")
    @need()
    def change_password():
        b = body()
        if not check_password_hash(g.user["pw"], str(b.get("old", ""))):
            return err("Obecne hasło jest niepoprawne", 403)
        if not isinstance(b.get("new"), str) or len(b["new"]) < 8:
            return err("Nowe hasło musi mieć co najmniej 8 znaków")
        q("UPDATE users SET pw=? WHERE id=?", generate_password_hash(b["new"]), g.user["id"])
        commit()
        return jsonify(ok=True)
