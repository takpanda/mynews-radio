"""Tests for SSRF prevention in hatena_fetcher module."""
import logging
import socket
from unittest.mock import MagicMock, patch

import pytest


def _mock_getaddrinfo_single(ip_str: str):
    """Return a mock socket.getaddrinfo that resolves every hostname to *ip_str*."""
    def _fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        addr = (ip_str, 0)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", addr)]
    return _fake_getaddrinfo


def _mock_getaddrinfo_multi(ip_strs: list[str]):
    """Return a mock socket.getaddrinfo that resolves every hostname to multiple IPs."""
    def _fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        results = []
        for ip in ip_strs:
            results.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)))
        return results
    return _fake_getaddrinfo


# ---------------------------------------------------------------------------
# _validate_url_public
# ---------------------------------------------------------------------------

class TestValidateUrlPublic:
    """Tests for _validate_url_public."""

    # --- Public URLs (should pass) ---

    def test_public_url_https(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("93.184.216.34")):
            _validate_url_public("https://example.com")

    def test_public_url_github(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("140.82.112.3")):
            _validate_url_public("https://github.com")

    # --- Loopback (127.0.0.1, ::1) ---

    def test_loopback_ipv4_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
            _validate_url_public("http://127.0.0.1")

    def test_loopback_ipv6_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("::1")):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("http://[::1]")

    # --- Private IP ranges ---

    @pytest.mark.parametrize("private_ip", [
        "10.0.0.1",
        "10.255.255.255",
        "10.1.2.3",
    ])
    def test_private_10_0_0_0_8_raises(self, private_ip):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single(private_ip)):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public(f"http://{private_ip}")

    @pytest.mark.parametrize("private_ip", [
        "172.16.0.1",
        "172.20.0.1",
        "172.31.255.255",
    ])
    def test_private_172_16_0_0_12_raises(self, private_ip):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single(private_ip)):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public(f"http://{private_ip}")

    @pytest.mark.parametrize("private_ip", [
        "192.168.0.1",
        "192.168.1.1",
        "192.168.255.255",
    ])
    def test_private_192_168_0_0_16_raises(self, private_ip):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single(private_ip)):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public(f"http://{private_ip}")

    # --- Link-local (169.254.x.x) ---

    @pytest.mark.parametrize("link_local_ip", [
        "169.254.1.1",
        "169.254.254.254",
    ])
    def test_link_local_raises(self, link_local_ip):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single(link_local_ip)):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public(f"http://{link_local_ip}")

    # --- 0.0.0.0 ---

    def test_zero_zero_zero_zero_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("0.0.0.0")):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("http://0.0.0.0")

    # --- Carrier-grade NAT (100.64.0.0/10) ---

    @pytest.mark.parametrize("cgnat_ip", [
        "100.64.0.1",
        "100.80.0.1",
        "100.127.255.255",
    ])
    def test_carrier_grade_nat_raises(self, cgnat_ip):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single(cgnat_ip)):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public(f"http://{cgnat_ip}")

    # --- IPv6 ULA (fc00::/7) and Link-local (fe80::/10) ---

    def test_ipv6_ula_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("fc00::1")):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("http://[fc00::1]")

    def test_ipv6_link_local_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("fe80::1")):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("http://[fe80::1]")

    # --- Hostname that resolves to internal IP (e.g. localhost) ---

    def test_hostname_resolving_to_loopback_blocked(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single("127.0.0.1")):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("http://localhost")

    # --- Multiple resolved IPs, one is internal ---

    def test_multi_resolve_one_internal_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_multi(["93.184.216.34", "10.0.0.1"])):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("https://example.com")

    # --- Without host (malformed URL) ---

    def test_no_host_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
            _validate_url_public("not-a-url")

    # --- DNS resolution failure ---

    def test_dns_failure_raises(self):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
            with pytest.raises(ValueError, match="Access to internal network address is not allowed"):
                _validate_url_public("http://nonexistent.example.com")

    # --- Public IPs that should NOT raise ---

    @pytest.mark.parametrize("public_ip", [
        "8.8.8.8",
        "1.1.1.1",
        "13.107.42.14",
    ])
    def test_public_ip_passes(self, public_ip):
        from app.services.hatena_fetcher import _validate_url_public
        with patch("socket.getaddrinfo", _mock_getaddrinfo_single(public_ip)):
            _validate_url_public(f"http://{public_ip}")


# ---------------------------------------------------------------------------
# fetch_article_by_url (hatena_fetcher.py version)
# ---------------------------------------------------------------------------

class TestFetchArticleByUrlSsrf:
    """Tests for fetch_article_by_url SSRF handling."""

    def test_internal_address_returns_empty_dict(self):
        from app.services.hatena_fetcher import fetch_article_by_url
        with patch("app.services.hatena_fetcher._validate_url_public",
                   side_effect=ValueError("Access to internal network address is not allowed")):
            result = fetch_article_by_url("http://127.0.0.1")

        assert result == {"title": "", "url": "http://127.0.0.1", "text": "", "source": "url_input"}

    def test_internal_address_logs_warning(self, caplog):
        from app.services.hatena_fetcher import fetch_article_by_url
        caplog.set_level(logging.WARNING)
        with patch("app.services.hatena_fetcher._validate_url_public",
                   side_effect=ValueError("Access to internal network address is not allowed")):
            fetch_article_by_url("http://127.0.0.1")
        assert len(caplog.records) >= 1
        assert any("blocked SSRF" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# _fetch_article_text (hatena_fetcher.py)
# ---------------------------------------------------------------------------

class TestFetchArticleTextSsrf:
    """Tests for _fetch_article_text SSRF handling."""

    def test_internal_address_returns_empty_string(self):
        from app.services.hatena_fetcher import _fetch_article_text
        with patch("app.services.hatena_fetcher._validate_url_public",
                   side_effect=ValueError("Access to internal network address is not allowed")):
            result = _fetch_article_text("http://127.0.0.1")

        assert result == ""

    def test_internal_address_logs_warning(self, caplog):
        from app.services.hatena_fetcher import _fetch_article_text
        caplog.set_level(logging.WARNING)
        with patch("app.services.hatena_fetcher._validate_url_public",
                   side_effect=ValueError("Access to internal network address is not allowed")):
            _fetch_article_text("http://127.0.0.1")
        assert len(caplog.records) >= 1
        assert any("blocked SSRF" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# API layer: POST /generate with internal URL
# ---------------------------------------------------------------------------

class TestGenerateEndpointSsrf:
    """Tests for API-layer SSRF blocking."""

    def test_internal_url_returns_400(self, client):
        resp = client.post("/generate", json={
            "date": "2099-07-01",
            "url": "http://127.0.0.1",
            "style": "solo",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"] == "Access to internal network address is not allowed"

    def test_internal_url_returns_400_ipv6(self, client):
        resp = client.post("/generate", json={
            "date": "2099-07-01",
            "url": "http://[::1]",
            "style": "solo",
        })
        assert resp.status_code == 400

    def test_private_url_returns_400(self, client):
        resp = client.post("/generate", json={
            "date": "2099-07-01",
            "url": "http://10.0.0.1",
            "style": "solo",
        })
        assert resp.status_code == 400

    def test_private_url_192_168_returns_400(self, client):
        resp = client.post("/generate", json={
            "date": "2099-07-01",
            "url": "http://192.168.1.1",
            "style": "solo",
        })
        assert resp.status_code == 400

    def test_public_url_passes_validation(self, client):
        resp = client.post("/generate", json={
            "date": "2099-07-01",
            "url": "https://example.com/article",
            "style": "solo",
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _SafeHTTPRedirectHandler
# ---------------------------------------------------------------------------

class TestSafeHTTPRedirectHandler:
    """Tests for _SafeHTTPRedirectHandler redirect tracking."""

    def test_redirect_validates_new_url(self):
        from app.services.hatena_fetcher import _SafeHTTPRedirectHandler
        handler = _SafeHTTPRedirectHandler()
        req = MagicMock()
        fp = MagicMock()

        with patch("app.services.hatena_fetcher._validate_url_public") as mock_validate:
            with patch.object(handler, "redirect_request", wraps=handler.redirect_request) as spy:
                with patch("urllib.request.HTTPRedirectHandler.redirect_request",
                           return_value=MagicMock(spec=object)):
                    result = spy(req, fp, 302, "Found", {}, "https://public.example.com/page")

        mock_validate.assert_called_once_with("https://public.example.com/page")

    def test_redirect_to_internal_address_propagates_value_error(self):
        from app.services.hatena_fetcher import _SafeHTTPRedirectHandler, _SSRF_ERROR_MESSAGE
        handler = _SafeHTTPRedirectHandler()
        req = MagicMock()
        fp = MagicMock()

        with patch("app.services.hatena_fetcher._validate_url_public",
                   side_effect=ValueError(_SSRF_ERROR_MESSAGE)):
            with pytest.raises(ValueError, match=_SSRF_ERROR_MESSAGE):
                handler.redirect_request(req, fp, 302, "Found", {}, "http://127.0.0.1/admin")

    def test_redirect_to_internal_address_logs_rejection(self, caplog):
        from app.services.hatena_fetcher import _SafeHTTPRedirectHandler
        handler = _SafeHTTPRedirectHandler()
        req = MagicMock()
        fp = MagicMock()

        caplog.set_level(logging.WARNING)
        with patch("app.services.hatena_fetcher._validate_url_public",
                   side_effect=ValueError("Access to internal network address is not allowed")):
            with pytest.raises(ValueError):
                handler.redirect_request(req, fp, 302, "Found", {}, "http://127.0.0.1/admin")

    def test_redirect_to_public_address_passes_through(self):
        from app.services.hatena_fetcher import _SafeHTTPRedirectHandler
        handler = _SafeHTTPRedirectHandler()
        req = MagicMock()
        fp = MagicMock()

        expected_result = MagicMock(spec=object)

        with patch("app.services.hatena_fetcher._validate_url_public") as mock_validate:
            with patch("urllib.request.HTTPRedirectHandler.redirect_request",
                       return_value=expected_result):
                result = handler.redirect_request(req, fp, 302, "Found", {}, "https://public.example.com")

        mock_validate.assert_called_once_with("https://public.example.com")
        assert result is expected_result
