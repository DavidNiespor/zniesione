"""Automatyczny rekord DNS dla WireGuard (Cloudflare API zastąpione atrapą)."""
import io
import json

import pytest

from zniesione import ddns


class FakeCF:
    """Atrapa API Cloudflare: strefa zniesione.pl i lista rekordów DNS."""
    def __init__(self, records=None):
        self.records, self.calls = records or [], []

    def __call__(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, url.replace(ddns.API, ""), body))
        assert req.get_header("Authorization") == "Bearer tok"
        if url.endswith("/cdn-cgi/trace"):
            return io.BytesIO(b"fl=1\nh=1.1.1.1\nip=203.0.113.7\nts=1\n")
        if "/zones?name=" in url:
            res = [{"id": "z1"}] if url.endswith("name=zniesione.pl") else []
        elif method == "GET":
            res = self.records
        else:
            res = body
        return io.BytesIO(json.dumps({"success": True, "result": res}).encode())


def test_creates_record_without_proxy():
    cf = FakeCF()
    ip = ddns.public_ip(cf_open(cf))
    assert ip == "203.0.113.7"
    assert ddns.sync("tok", "wg.zniesione.pl", ip, cf) == "created"
    method, path, body = cf.calls[-1]
    assert (method, path) == ("POST", "/zones/z1/dns_records")
    assert body["proxied"] is False and body["content"] == "203.0.113.7" and body["name"] == "wg.zniesione.pl"


def test_updates_changed_ip_or_proxied_record_and_skips_unchanged():
    cf = FakeCF([{"id": "r1", "content": "198.51.100.1", "proxied": False}])
    assert ddns.sync("tok", "wg.zniesione.pl", "203.0.113.7", cf) == "updated"
    assert cf.calls[-1][:2] == ("PUT", "/zones/z1/dns_records/r1")
    proxied = FakeCF([{"id": "r1", "content": "203.0.113.7", "proxied": True}])
    assert ddns.sync("tok", "wg.zniesione.pl", "203.0.113.7", proxied) == "updated"   # proxy psuje WireGuard
    same = FakeCF([{"id": "r1", "content": "203.0.113.7", "proxied": False}])
    assert ddns.sync("tok", "wg.zniesione.pl", "203.0.113.7", same) == "unchanged"
    assert [c[0] for c in same.calls] == ["GET", "GET", "GET"]


def test_reports_missing_zone_and_api_errors():
    with pytest.raises(RuntimeError, match="dostępu do strefy"):
        ddns.sync("tok", "wg.innadomena.pl", "203.0.113.7", FakeCF())

    def failing(req, timeout=None):
        return io.BytesIO(json.dumps({"success": False, "errors": [{"message": "Invalid token"}]}).encode())
    with pytest.raises(RuntimeError, match="Invalid token"):
        ddns.call("GET", "/zones", "tok", opener=failing)


def cf_open(cf):
    return lambda req, timeout=None: cf(req.__class__(req.full_url, headers={"Authorization": "Bearer tok"}), timeout)
