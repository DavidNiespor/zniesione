"""Czyste funkcje silnika: wschód i zachód słońca, okna harmonogramów, czas trwania."""
from datetime import date, datetime, timezone

from zniesione import services as sv

WAW = (52.2297, 21.0122)


def near(dt, h, m, tol=2):
    return abs((dt.hour * 60 + dt.minute + dt.second / 60) - (h * 60 + m)) <= tol


def test_sun_times_known_dates_warsaw():
    # tablice astronomiczne dla Warszawy (czas UTC): 21.06.2026 wschód 02:14, zachód 19:01;
    # 21.12.2026 wschód 06:43, zachód 14:25
    r, s = sv.sun_times(*WAW, date(2026, 6, 21))
    assert r.tzinfo == timezone.utc and near(r, 2, 14) and near(s, 19, 1)
    r, s = sv.sun_times(*WAW, date(2026, 12, 21))
    assert near(r, 6, 43) and near(s, 14, 25)


def test_sun_times_equator_and_polar():
    r, s = sv.sun_times(0, 0, date(2026, 3, 20))       # równonoc na równiku: ok. 06:04 i 18:11 UTC
    assert near(r, 6, 4, 4) and near(s, 18, 11, 4)
    assert sv.sun_times(69.65, 18.96, date(2026, 6, 21)) is None   # Tromsø: dzień polarny
    assert sv.sun_times(69.65, 18.96, date(2026, 12, 21)) is None  # noc polarna
    assert sv.sun_times(90, 0, date(2026, 6, 21)) is None


def fixed_sun(day):  # wschód 06:00, zachód 18:30 każdego dnia
    return datetime.combine(day, datetime.min.time()).replace(hour=6), \
        datetime.combine(day, datetime.min.time()).replace(hour=18, minute=30)


def S(**k):
    base = {"t_on": "00:00", "t_off": "00:00", "days": "a", "enabled": 1}
    return {**base, **k}


def test_sunrise_window_with_offset_to_fixed_time():
    s = S(mode="sunrise", offset_min=-30, t_off="07:00")          # od wschodu −30 min do 07:00
    at = lambda h, m: datetime(2026, 10, 22, h, m)
    assert not sv.sched_active(s, at(5, 29), fixed_sun)
    assert sv.sched_active(s, at(5, 30), fixed_sun) and sv.sched_active(s, at(6, 59), fixed_sun)
    assert not sv.sched_active(s, at(7, 0), fixed_sun)
    assert not sv.sched_active(s, at(5, 45), None)                 # bez położenia farmy nie działa


def test_sunset_window_overnight_and_duration():
    s = S(mode="sunset", offset_min=15, off_mode="time", t_off="01:00")   # 18:45 - 01:00 następnego dnia
    assert sv.sched_active(s, datetime(2026, 10, 22, 23, 0), fixed_sun)
    assert sv.sched_active(s, datetime(2026, 10, 23, 0, 30), fixed_sun)
    assert not sv.sched_active(s, datetime(2026, 10, 22, 18, 44), fixed_sun)
    feed = S(t_on="07:00", duration_s=90)
    w = sv.sched_window(feed, datetime(2026, 10, 22, 7, 1), None)
    assert w == (datetime(2026, 10, 22, 7, 0), datetime(2026, 10, 22, 7, 1, 30))
    assert not sv.sched_active(feed, datetime(2026, 10, 22, 7, 1, 30))
    door = S(mode="sunrise", off_mode="sunset", off_offset_min=20)       # drzwi: od wschodu do zachodu +20
    assert sv.window(door, date(2026, 10, 22), fixed_sun) == (6 * 3600, 18 * 3600 + 50 * 60)


def test_rule_ignored_for_kinds_without_thermostat():
    rule = {"threshold": 25, "enabled": 1}
    assert sv.desired("light", [], rule, 30, datetime(2026, 1, 1), False) is None
    assert sv.desired("vent", [], rule, 30, datetime(2026, 1, 1), False) is True
