"""Kopie zapasowe bazy SQLite dla kontenera „kopie” w docker-compose.yml.
Uruchom: python -m zniesione.backup  (zmienne: DATABASE, BACKUP_DIR, BACKUP_EVERY_H, KEEP_DAYS)"""
import glob
import os
import sqlite3
import time
from datetime import datetime, timedelta


def backup_once(db_path, out_dir, keep_days, now=None):
    """Spójna kopia także w trakcie pracy portalu (API backup SQLite). Usuwa kopie starsze niż keep_days dni."""
    now = now or datetime.now()
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"zniesione-{now:%Y-%m-%d_%H%M}.db")
    src, dst = sqlite3.connect(db_path), sqlite3.connect(out)
    with dst:
        src.backup(dst)
    src.close(), dst.close()
    for f in glob.glob(os.path.join(out_dir, "zniesione-*.db")):
        try:
            if datetime.strptime(os.path.basename(f)[10:-3], "%Y-%m-%d_%H%M") < now - timedelta(days=keep_days):
                os.remove(f)
        except ValueError:
            pass  # obcy plik o podobnej nazwie: zostaw
    return out


def main():
    db, out = os.environ.get("DATABASE", "/data/zniesione.db"), os.environ.get("BACKUP_DIR", "/backup")
    every, keep = float(os.environ.get("BACKUP_EVERY_H", "24")), int(os.environ.get("KEEP_DAYS", "14"))
    while True:
        if os.path.exists(db):
            print("Kopia zapisana:", backup_once(db, out, keep), flush=True)
        else:
            print("Brak bazy", db, "- spróbuję później", flush=True)
        time.sleep(every * 3600)  # osobny proces kontenera kopii, nie wątek portalu


if __name__ == "__main__":
    main()
