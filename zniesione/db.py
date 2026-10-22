import sqlite3
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN('admin','farmer')), farm_id INTEGER);
CREATE TABLE IF NOT EXISTS farms(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT DEFAULT '', zip TEXT DEFAULT '',
  breed TEXT DEFAULT '', descr TEXT DEFAULT '', price10 REAL DEFAULT 0, stock INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
  qty INTEGER NOT NULL, mode TEXT NOT NULL, pickup TEXT NOT NULL, total REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, model TEXT NOT NULL, farm_id INTEGER,
  tunnel TEXT NOT NULL, ip TEXT UNIQUE NOT NULL, stage INTEGER NOT NULL DEFAULT 0, api_key TEXT UNIQUE NOT NULL,
  addr TEXT DEFAULT '', online INTEGER DEFAULT 0, last_seen TEXT);
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'other', state INTEGER NOT NULL DEFAULT 0, UNIQUE(device_id,key));
CREATE TABLE IF NOT EXISTS schedules(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL,
  t_on TEXT NOT NULL, t_off TEXT NOT NULL, days TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL,
  threshold REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, UNIQUE(device_id,ch));
CREATE TABLE IF NOT EXISTS readings(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, t REAL, h REAL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL, state INTEGER NOT NULL,
  src TEXT NOT NULL, ok INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flocks(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL,
  birds INTEGER NOT NULL DEFAULT 0, breed TEXT NOT NULL DEFAULT '', since TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS eggs(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN('collect','sale')),
  packs INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kb(id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
  published INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);
"""
# Kolumny dodane po pierwszym wydaniu: dopisywane do istniejących baz przy starcie.
COLUMNS = [
    ("farms", "lat", "REAL"), ("farms", "lon", "REAL"),
    ("devices", "door_run_s", "INTEGER NOT NULL DEFAULT 20"), ("devices", "door", "TEXT"),
    ("devices", "door_want", "INTEGER"), ("devices", "wg_priv", "TEXT"), ("devices", "wg_pub", "TEXT"),
    ("channels", "off_at", "TEXT"), ("channels", "want", "INTEGER"),
    ("schedules", "mode", "TEXT NOT NULL DEFAULT 'time'"), ("schedules", "offset_min", "INTEGER NOT NULL DEFAULT 0"),
    ("schedules", "off_mode", "TEXT NOT NULL DEFAULT 'time'"), ("schedules", "off_offset_min", "INTEGER NOT NULL DEFAULT 0"),
    ("schedules", "duration_s", "INTEGER"),
]


def get():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_app(app):
    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d:
            d.close()
    with app.app_context():
        db = get()
        db.executescript(SCHEMA)
        migrate(db)
        db.commit()


def migrate(db):
    for table, col, ddl in COLUMNS:
        if col not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
