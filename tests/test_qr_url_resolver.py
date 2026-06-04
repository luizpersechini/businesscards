"""
Tests for utils/qr_url_resolver — the safe fetcher/parser for QR codes that
encode a URL to a hosted contact page.

No network: validate_url_safe is tested against literal IPs and monkeypatched
DNS; resolve_qr_url is tested with the HTTP layer mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from utils import qr_url_resolver as r


# ── SSRF / scheme / port guard ───────────────────────────────────────────────


class TestValidateUrlSafe:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://127.0.0.1:80/x",
            "https://10.0.0.5/contact",
            "https://192.168.1.10/",
            "https://172.16.5.5/",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata!
            "http://[::1]/x",
            "https://localhost/x",
        ],
    )
    def test_blocks_private_and_loopback(self, url):
        ok, reason = r.validate_url_safe(url)
        assert ok is False
        assert reason

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/x",
            "file:///etc/passwd",
            "gopher://example.com/",
            "javascript:alert(1)",
        ],
    )
    def test_blocks_bad_schemes(self, url):
        ok, _ = r.validate_url_safe(url)
        assert ok is False

    def test_blocks_embedded_credentials(self):
        ok, reason = r.validate_url_safe("https://user:pass@example.com/")
        assert ok is False
        assert "credential" in reason.lower()

    def test_blocks_nonstandard_port(self):
        # 8.8.8.8:22 — public IP but disallowed port
        ok, reason = r.validate_url_safe("http://8.8.8.8:22/")
        assert ok is False
        assert "port" in reason.lower()

    def test_allows_public_https_literal_ip(self):
        ok, reason = r.validate_url_safe("https://8.8.8.8/")
        assert ok is True
        assert reason == ""

    def test_blocks_hostname_resolving_to_private(self, monkeypatch):
        # A hostname that resolves to a private IP must be blocked.
        monkeypatch.setattr(r, "_resolve_host_ips", lambda h: ["192.168.0.42"])
        ok, reason = r.validate_url_safe("https://sneaky.example.com/")
        assert ok is False
        assert "private" in reason.lower() or "reserved" in reason.lower()

    def test_allows_hostname_resolving_to_public(self, monkeypatch):
        monkeypatch.setattr(r, "_resolve_host_ips", lambda h: ["93.184.216.34"])
        ok, reason = r.validate_url_safe("https://example.com/")
        assert ok is True

    def test_blocks_unresolvable_host(self, monkeypatch):
        import socket

        def _boom(host):
            raise socket.gaierror("nope")

        monkeypatch.setattr(r, "_resolve_host_ips", _boom)
        ok, reason = r.validate_url_safe("https://nx.example.invalid/")
        assert ok is False

    def test_empty_url(self):
        assert r.validate_url_safe("")[0] is False
        assert r.validate_url_safe(None)[0] is False


# ── Parsers (no network) ─────────────────────────────────────────────────────


class TestParsers:
    def test_vcard(self):
        vcf = (
            "BEGIN:VCARD\nVERSION:3.0\nFN:Jane Doe\nN:Doe;Jane;;;\n"
            "ORG:Acme Inc\nTITLE:CEO\nEMAIL:jane@acme.com\n"
            "TEL:+15551234567\nURL:https://acme.com\nEND:VCARD"
        )
        out = r._parse_vcard_text(vcf)
        assert out["full_name"] == "Jane Doe"
        assert out["organization"] == "Acme Inc"
        assert out["title"] == "CEO"
        assert "jane@acme.com" in out["emails"]
        assert "+15551234567" in out["phones"]

    def test_mecard(self):
        mc = "MECARD:N:Silva,Joao;ORG:Acme;TEL:+5511999;EMAIL:j@acme.com;;"
        out = r._parse_mecard_text(mc)
        assert out["full_name"] == "Joao Silva"
        assert out["organization"] == "Acme"
        assert "+5511999" in out["phones"]

    def test_jsonld_person(self):
        data = {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": "Maria Souza",
            "jobTitle": "CTO",
            "email": "mailto:maria@beta.com",
            "telephone": "+5511888",
            "worksFor": {"@type": "Organization", "name": "Beta Ltda"},
        }
        out = r._parse_jsonld_person(data)
        assert out["full_name"] == "Maria Souza"
        assert out["title"] == "CTO"
        assert "maria@beta.com" in out["emails"]
        assert out["organization"] == "Beta Ltda"

    def test_html_jsonld_and_mailto(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {"@type":"Person","name":"Bob Lee","email":"bob@x.io"}
          </script>
        </head><body>
          <a href="mailto:other@x.io">mail</a>
          <a href="tel:+15550001111">call</a>
        </body></html>
        """
        fields, vcf_url = r._parse_html(html, "https://card.x.io/bob")
        assert fields["full_name"] == "Bob Lee"
        assert "bob@x.io" in fields["emails"]
        assert "+15550001111" in fields["phones"]
        assert vcf_url is None

    def test_html_discovers_vcf_link(self):
        html = '<a href="/download/contact.vcf">Save contact</a>'
        fields, vcf_url = r._parse_html(html, "https://card.x.io/bob")
        assert vcf_url == "https://card.x.io/download/contact.vcf"

    def test_html_discovers_vcard_endpoint_without_extension(self):
        # Mobiz/WordPress style: /slug/vcard (no .vcf extension)
        html = '<a href="/victorbecattini/vcard">Save contact</a>'
        fields, vcf_url = r._parse_html(html, "https://my.mobiz.pro/victorbecattini/")
        assert vcf_url == "https://my.mobiz.pro/victorbecattini/vcard"

    def test_jsonld_skips_wordpress_author(self):
        # The page author Person (an /author/ archive URL) is the publisher,
        # not the card subject — must be ignored.
        data = {
            "@graph": [
                {
                    "@type": "Person",
                    "@id": "https://site/author/agency/",
                    "url": "https://site/author/agency/",
                    "name": "Agency Admin",
                },
                {"@type": "Organization", "name": "RealCo"},
            ]
        }
        out = r._parse_jsonld_person(data)
        assert out.get("full_name") != "Agency Admin"
        assert out.get("organization") == "RealCo"

    def test_html_og_title_overrides_name_and_fills_company(self):
        # og:title "Name | Company" is authoritative for the owner's name.
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type":"Person","@id":"https://x/author/admin/",'
            '"url":"https://x/author/admin/","name":"Site Admin"}'
            "</script>"
            '<meta property="og:title" content="Victor Becattini | SANDVIK" />'
            "</head><body></body></html>"
        )
        fields, _ = r._parse_html(html, "https://x/")
        assert fields["full_name"] == "Victor Becattini"
        assert fields["organization"] == "SANDVIK"

    def test_vcard_role_maps_to_title(self):
        vcf = "BEGIN:VCARD\nFN:V B\nROLE:VP Sales\nORG:Acme\nEND:VCARD"
        out = r._parse_vcard_text(vcf)
        assert out["title"] == "VP Sales"

    def test_normalize_name_splits_full_into_first_last(self):
        # vCard packed the whole name into the first slot.
        out = r._normalize_name(
            {"full_name": "Victor Becattini", "first_name": "Victor Becattini", "last_name": ""}
        )
        assert out["first_name"] == "Victor"
        assert out["last_name"] == "Becattini"

    def test_normalize_name_three_tokens(self):
        out = r._normalize_name({"full_name": "Ana Maria Souza", "last_name": ""})
        assert out["first_name"] == "Ana"
        assert out["last_name"] == "Maria Souza"

    def test_normalize_name_preserves_existing_split(self):
        out = r._normalize_name({"full_name": "Bob Lee", "first_name": "Bob", "last_name": "Lee"})
        assert out["first_name"] == "Bob"
        assert out["last_name"] == "Lee"

    def test_normalize_name_single_token_untouched(self):
        out = r._normalize_name({"full_name": "Cher", "last_name": ""})
        assert out.get("first_name") in (None, "")
        assert out.get("last_name") == ""

    def test_octet_stream_vcard_is_accepted(self, monkeypatch):
        # A vCard endpoint that serves application/octet-stream must still be
        # read + parsed (common for "save contact" download endpoints).
        monkeypatch.setattr(r, "validate_url_safe", lambda u: (True, ""))
        monkeypatch.setattr(r, "_check_safe_browsing", lambda u: (True, ""))
        vcf = "BEGIN:VCARD\nFN:Octet Person\nEMAIL:o@x.io\nEND:VCARD"
        monkeypatch.setattr(
            r.requests, "get", lambda *a, **k: _mock_resp(vcf, "application/octet-stream")
        )
        out = r.resolve_qr_url("https://example.com/card/vcard")
        assert out["ok"] is True
        assert out["fields"]["full_name"] == "Octet Person"


# ── Orchestration (mocked fetch) ─────────────────────────────────────────────


def _mock_resp(body: str, ctype: str):
    m = MagicMock()
    m.headers = {"Content-Type": ctype}
    m.url = "https://example.com/final"
    m.encoding = "utf-8"
    m.is_redirect = False
    m.status_code = 200
    m.iter_content = lambda chunk_size=16384: iter([body.encode("utf-8")])
    m.close = lambda: None
    return m


class TestResolveOrchestration:
    def test_resolve_blocks_unsafe_url_before_fetch(self):
        # Should never call requests for a private URL.
        with patch.object(r.requests, "get") as g:
            out = r.resolve_qr_url("http://127.0.0.1/x")
        assert out["ok"] is False
        g.assert_not_called()

    def test_resolve_vcard(self, monkeypatch):
        monkeypatch.setattr(r, "validate_url_safe", lambda u: (True, ""))
        monkeypatch.setattr(r, "_check_safe_browsing", lambda u: (True, ""))
        vcf = "BEGIN:VCARD\nFN:Ana Paula\nEMAIL:ana@acme.com\nEND:VCARD"
        monkeypatch.setattr(r.requests, "get", lambda *a, **k: _mock_resp(vcf, "text/vcard"))
        out = r.resolve_qr_url("https://example.com/ana.vcf")
        assert out["ok"] is True
        assert out["source"] == "vcard"
        assert out["fields"]["full_name"] == "Ana Paula"
        assert "ana@acme.com" in out["fields"]["emails"]

    def test_resolve_html(self, monkeypatch):
        monkeypatch.setattr(r, "validate_url_safe", lambda u: (True, ""))
        monkeypatch.setattr(r, "_check_safe_browsing", lambda u: (True, ""))
        html = (
            '<html><body><a href="mailto:z@acme.com">e</a>'
            '<a href="tel:+15551112222">p</a></body></html>'
        )
        monkeypatch.setattr(r.requests, "get", lambda *a, **k: _mock_resp(html, "text/html"))
        out = r.resolve_qr_url("https://example.com/card")
        assert out["ok"] is True
        assert "z@acme.com" in out["fields"]["emails"]

    def test_resolve_empty_page(self, monkeypatch):
        monkeypatch.setattr(r, "validate_url_safe", lambda u: (True, ""))
        monkeypatch.setattr(r, "_check_safe_browsing", lambda u: (True, ""))
        monkeypatch.setattr(
            r.requests,
            "get",
            lambda *a, **k: _mock_resp("<html><body>nothing</body></html>", "text/html"),
        )
        out = r.resolve_qr_url("https://example.com/blank")
        assert out["ok"] is False
        assert "no contact data" in out["reason"].lower()
