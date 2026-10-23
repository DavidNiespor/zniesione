"""Automatyczne rekordy DNS w Cloudflare: WireGuard i poczta (API Cloudflare zastąpione atrapą)."""
import io
import json
import urllib.parse

import pytest

from zniesione import ddns


class FakeCF:
    """Atrapa API Cloudflare: strefa zniesione.pl i lista rekordów DNS."""
    def __init__(self, recs=()):
        self.recs, self.calls, self.n = [dict(r, id=f"r{i}") for i, r in enumerate(recs)], [], 100

    def __call__(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, url.replace(ddns.API, ""), body))
        assert req.get_header("Authorization") == "Bearer tok"
        if url.endswith("/cdn-cgi/trace"):
            return self.ok_text(b"fl=1\nh=1.1.1.1\nip=203.0.113.7\nts=1\n")
        p = urllib.parse.urlparse(url)
        qs = dict(urllib.parse.parse_qsl(p.query))
        if p.path.endswith("/zones"):
            res = [{"id": "z1"}] if qs["name"] == "zniesione.pl" else []
        elif method == "GET":
            res = [r for r in self.recs if r["type"] == qs["type"] and r["name"] == qs["name"]]
        elif method == "POST":
            self.n += 1
            res = dict(body, id=f"r{self.n}")
            self.recs.append(res)
        else:
            rid = p.path.rsplit("/", 1)[1]
            res = next(r for r in self.recs if r["id"] == rid)
            res.update(body)
        return self.ok_text(json.dumps({"success": True, "result": res}).encode())

    @staticmethod
    def ok_text(b):
        return io.BytesIO(b)

    def find(self, t, name):
        return [r for r in self.recs if r["type"] == t and r["name"] == name]


def test_public_ip_and_wireguard_record_without_proxy():
    cf = FakeCF()
    assert ddns.public_ip(lambda req, timeout=None: io.BytesIO(b"ip=203.0.113.7\n")) == "203.0.113.7"
    assert ddns.sync("tok", "wg.zniesione.pl", "203.0.113.7", cf) == "created"
    (r,) = cf.find("A", "wg.zniesione.pl")
    assert r["proxied"] is False and r["content"] == "203.0.113.7"
    assert ddns.sync("tok", "wg.zniesione.pl", "203.0.113.7", cf) == "unchanged"
    assert ddns.sync("tok", "wg.zniesione.pl", "198.51.100.9", cf) == "updated"     # zmiana IP
    proxied = FakeCF([{"type": "A", "name": "wg.zniesione.pl", "content": "198.51.100.9", "proxied": True}])
    assert ddns.sync("tok", "wg.zniesione.pl", "198.51.100.9", proxied) == "updated"  # proxy psuje WireGuard


def test_mail_records_created_with_dkim_from_mailserver(tmp_path):
    key = tmp_path / "mail.txt"
    key.write_text('mail._domainkey\tIN\tTXT\t( "v=DKIM1; h=sha256; k=rsa; "\n\t  "p=MIIBIjAN"\n\t  "BgkqhkiG9w0" )  ; ----- DKIM key mail for zniesione.pl\n')
    cf = FakeCF()
    out = dict(ddns.sync_mail("tok", "zniesione.pl", "203.0.113.7", str(key), cf))
    assert set(out.values()) == {"created"}
    assert cf.find("A", "mail.zniesione.pl")[0]["proxied"] is False
    mx = cf.find("MX", "zniesione.pl")[0]
    assert (mx["content"], mx["priority"]) == ("mail.zniesione.pl", 10)
    assert cf.find("TXT", "zniesione.pl")[0]["content"] == "v=spf1 mx -all"
    assert cf.find("TXT", "_dmarc.zniesione.pl")[0]["content"].startswith("v=DMARC1; p=quarantine; rua=mailto:postmaster@")
    assert cf.find("TXT", "mail._domainkey.zniesione.pl")[0]["content"] == "v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqhkiG9w0"
    again = dict(ddns.sync_mail("tok", "zniesione.pl", "203.0.113.7", str(key), cf))
    assert set(again.values()) == {"unchanged"}                                      # drugi obieg nic nie zmienia


def test_existing_spf_and_dmarc_are_kept_and_foreign_mx_reported(tmp_path):
    cf = FakeCF([{"type": "TXT", "name": "zniesione.pl", "content": '"v=spf1 include:_spf.mx.cloudflare.net ~all"'},
                 {"type": "TXT", "name": "zniesione.pl", "content": "google-site-verification=abc"},
                 {"type": "TXT", "name": "_dmarc.zniesione.pl", "content": "v=DMARC1; p=none"},
                 {"type": "MX", "name": "zniesione.pl", "content": "route1.mx.cloudflare.net", "priority": 5}])
    out = ddns.sync_mail("tok", "zniesione.pl", "203.0.113.7", str(tmp_path / "brak.txt"), cf)
    txt = dict(out)
    assert txt["SPF zniesione.pl"].startswith("kept") and txt["DMARC _dmarc.zniesione.pl"] == "kept"
    assert any("route1.mx.cloudflare.net" in v for _, v in out)
    assert txt["DKIM mail._domainkey.zniesione.pl"] == "czeka na klucz od serwera poczty"
    assert cf.find("TXT", "_dmarc.zniesione.pl")[0]["content"] == "v=DMARC1; p=none"   # nie nadpisany
    assert len(cf.find("TXT", "zniesione.pl")) == 2                                      # weryfikacja Google została


def test_errors_are_reported():
    with pytest.raises(RuntimeError, match="dostępu do strefy"):
        ddns.sync("tok", "wg.innadomena.pl", "203.0.113.7", FakeCF())

    def failing(req, timeout=None):
        return io.BytesIO(json.dumps({"success": False, "errors": [{"message": "Invalid token"}]}).encode())
    with pytest.raises(RuntimeError, match="Invalid token"):
        ddns.call("GET", "/zones", "tok", opener=failing)
    assert ddns.norm('"v=DKIM1; p=AB" "CD"') == "v=DKIM1; p=ABCD"
