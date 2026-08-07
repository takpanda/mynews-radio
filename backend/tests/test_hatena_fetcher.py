"""Tests for SSRF prevention in hatena_fetcher module."""
import json
import logging
import re
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


def _mock_open_resp(html_text: str) -> MagicMock:
    """Build a mock response for _SAFE_OPENER.open() returning *html_text* as UTF-8."""
    resp = MagicMock()
    resp.read.return_value = html_text.encode("utf-8")
    resp.headers.get_content_charset.return_value = "utf-8"
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


# ---------------------------------------------------------------------------
# Fixed test data: minimized Studio.Design (Nuxt) page for
# https://mx.general.hokudai.ac.jp/posts/SuvDaMaR (BEE-615)
#
# Studio.Design renders the article body client-side only; the static HTML
# ships an empty content area, with the body pre-serialized inside the
# #__NUXT_DATA__ JSON payload under a "dynamicData<url-path>" entry. This is
# the real page's payload structure, trimmed to the minimum needed to
# reproduce the extraction path (verified against the live page's HTML).
# ---------------------------------------------------------------------------

STUDIO_DESIGN_URL = "https://mx.general.hokudai.ac.jp/posts/SuvDaMaR"
STUDIO_DESIGN_TITLE = "Copilot活用に向けた「Microsoft Teamsでの情報共有の考え方」を作成しました"
STUDIO_DESIGN_BODY_HTML = (
    '<p data-uid="zoH3bqcK">こんにちは！「事務職員が変われば、北大は変わる」を信じてる、'
    "北海道大学DX業務推進室の佐久間です。</p>"
    '<p data-uid="MCex6DTT">Microsoft 365 Copilotをもっと活用するためには、業務に関する情報がTeams上に'
    "適切に共有・蓄積されていることが重要だと感じています。そこで当室では、"
    "「Microsoft Teamsでの情報共有の考え方」を作成しました。</p>"
)


def _studio_design_nuxt_payload(
    dynamic_data_key: str = "dynamicDataposts/SuvDaMaR",
    entry_idx: object = 4,
    body_idx: object = 5,
    body_value: object = STUDIO_DESIGN_BODY_HTML,
) -> list:
    """Build a Nuxt devalue-style payload matching the real page's structure."""
    return [
        ["ShallowReactive", 1],
        {"data": 2},
        ["ShallowReactive", 3],
        {dynamic_data_key: entry_idx},
        {"body": body_idx, "title": 6},
        body_value,
        STUDIO_DESIGN_TITLE,
    ]


def _studio_design_html(payload_json: str) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        f'<meta property="og:title" content="{STUDIO_DESIGN_TITLE}">'
        f"<title>{STUDIO_DESIGN_TITLE}  |  北海道大学DX業務推進室</title>"
        '</head><body><div id="__nuxt"></div>'
        '<script type="application/json" data-nuxt-data="nuxt-app" data-ssr="true" '
        f'id="__NUXT_DATA__">{payload_json}</script>'
        "</body></html>"
    )


STUDIO_DESIGN_HTML = _studio_design_html(
    json.dumps(_studio_design_nuxt_payload(), ensure_ascii=False)
)

NORMAL_SERVER_RENDERED_HTML = (
    "<!DOCTYPE html><html><head><title>通常記事のタイトル</title></head>"
    "<body><article><p>"
    + "これは通常のサーバーサイドレンダリングされた記事の本文です。" * 4
    + "</p></article></body></html>"
)


def _fake_trafilatura_extract(html_text: str, url: str | None = None, **kwargs) -> str | None:
    """Deterministic stand-in for trafilatura.extract(): strips <script> blocks and tags.

    Used instead of the real library so these tests don't depend on it being
    importable/unmocked — test_url_fetcher.py replaces sys.modules["trafilatura"]
    with a MagicMock at import time, which would otherwise leak into any test
    that runs in the same session.
    """
    body_match = re.search(r"<body[^>]*>(.*)</body>", html_text, re.DOTALL)
    content = body_match.group(1) if body_match else html_text
    without_scripts = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", without_scripts)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


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
        with patch("app.api.generate._run_commentary_generation") as mock_run:
            resp = client.post("/generate", json={
                "date": "2099-07-01",
                "url": "https://example.com/article",
                "style": "solo",
            })
        assert resp.status_code == 200
        mock_run.assert_called_once()


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


# ---------------------------------------------------------------------------
# _extract_studio_design_nuxt_body (BEE-615)
# ---------------------------------------------------------------------------

class TestExtractStudioDesignNuxtBody:
    """Unit tests for the Nuxt #__NUXT_DATA__ payload parsing helper."""

    def test_extracts_body_html_for_matching_path(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        result = _extract_studio_design_nuxt_body(STUDIO_DESIGN_HTML, STUDIO_DESIGN_URL)
        assert result == STUDIO_DESIGN_BODY_HTML

    def test_no_nuxt_data_script_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        result = _extract_studio_design_nuxt_body(NORMAL_SERVER_RENDERED_HTML, "https://example.com/normal")
        assert result == ""

    def test_broken_json_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        html = _studio_design_html("{not valid json")
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_payload_not_a_list_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        html = _studio_design_html(json.dumps({"unexpected": "shape"}))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_target_article_not_found_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        payload = _studio_design_nuxt_payload(dynamic_data_key="dynamicDataposts/OtherArticle")
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_entry_index_out_of_range_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        payload = _studio_design_nuxt_payload(entry_idx=999)
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_body_index_out_of_range_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        payload = _studio_design_nuxt_payload(body_idx=999)
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_entry_missing_body_key_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        payload = _studio_design_nuxt_payload()
        payload[4] = {"title": 6}  # no "body" key
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_body_value_wrong_type_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        payload = _studio_design_nuxt_payload(body_value=12345)
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_entry_index_not_an_int_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        payload = _studio_design_nuxt_payload(entry_idx="not-an-int")
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))
        result = _extract_studio_design_nuxt_body(html, STUDIO_DESIGN_URL)
        assert result == ""

    def test_empty_url_path_returns_empty(self):
        from app.services.hatena_fetcher import _extract_studio_design_nuxt_body
        result = _extract_studio_design_nuxt_body(STUDIO_DESIGN_HTML, "https://mx.general.hokudai.ac.jp/")
        assert result == ""


# ---------------------------------------------------------------------------
# fetch_article_by_url: Nuxt payload fallback (BEE-615)
# ---------------------------------------------------------------------------

class TestFetchArticleByUrlNuxtFallback:
    """Tests for the Studio.Design Nuxt payload fallback in fetch_article_by_url."""

    def test_studio_design_page_uses_nuxt_fallback(self, caplog):
        from app.services.hatena_fetcher import fetch_article_by_url
        caplog.set_level(logging.INFO)

        with patch("app.services.hatena_fetcher._validate_url_public"):
            with patch("app.services.hatena_fetcher._SAFE_OPENER.open", return_value=_mock_open_resp(STUDIO_DESIGN_HTML)):
                with patch("trafilatura.extract", side_effect=_fake_trafilatura_extract):
                    result = fetch_article_by_url(STUDIO_DESIGN_URL)

        assert result["title"] == STUDIO_DESIGN_TITLE
        assert len(result["text"]) >= 50
        assert result["source"] == "url_input"
        assert any("nuxt_payload" in rec.getMessage() for rec in caplog.records)

    def test_normal_server_rendered_page_does_not_use_nuxt_fallback(self):
        from app.services.hatena_fetcher import fetch_article_by_url
        url = "https://example.com/normal"

        with patch("app.services.hatena_fetcher._validate_url_public"):
            with patch("app.services.hatena_fetcher._SAFE_OPENER.open", return_value=_mock_open_resp(NORMAL_SERVER_RENDERED_HTML)):
                with patch("trafilatura.extract", side_effect=_fake_trafilatura_extract):
                    with patch(
                        "app.services.hatena_fetcher._extract_studio_design_nuxt_body"
                    ) as mock_nuxt_extract:
                        result = fetch_article_by_url(url)

        mock_nuxt_extract.assert_not_called()
        assert result["title"] == "通常記事のタイトル"
        assert len(result["text"]) >= 50

    def test_broken_nuxt_payload_falls_back_to_existing_failure_handling(self):
        from app.services.hatena_fetcher import fetch_article_by_url
        html = _studio_design_html("{not valid json")

        with patch("app.services.hatena_fetcher._validate_url_public"):
            with patch("app.services.hatena_fetcher._SAFE_OPENER.open", return_value=_mock_open_resp(html)):
                result = fetch_article_by_url(STUDIO_DESIGN_URL)

        assert result["text"] == ""
        assert result["source"] == "url_input"

    def test_target_article_missing_falls_back_to_existing_failure_handling(self):
        from app.services.hatena_fetcher import fetch_article_by_url
        payload = _studio_design_nuxt_payload(dynamic_data_key="dynamicDataposts/OtherArticle")
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))

        with patch("app.services.hatena_fetcher._validate_url_public"):
            with patch("app.services.hatena_fetcher._SAFE_OPENER.open", return_value=_mock_open_resp(html)):
                result = fetch_article_by_url(STUDIO_DESIGN_URL)

        assert result["text"] == ""

    def test_nuxt_body_value_wrong_type_falls_back_to_existing_failure_handling(self):
        from app.services.hatena_fetcher import fetch_article_by_url
        payload = _studio_design_nuxt_payload(body_value={"unexpected": "dict"})
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))

        with patch("app.services.hatena_fetcher._validate_url_public"):
            with patch("app.services.hatena_fetcher._SAFE_OPENER.open", return_value=_mock_open_resp(html)):
                result = fetch_article_by_url(STUDIO_DESIGN_URL)

        assert result["text"] == ""

    def test_nuxt_extraction_still_too_short_falls_back_to_existing_failure_handling(self):
        from app.services.hatena_fetcher import fetch_article_by_url
        payload = _studio_design_nuxt_payload(body_value="<p>短い本文</p>")
        html = _studio_design_html(json.dumps(payload, ensure_ascii=False))

        with patch("app.services.hatena_fetcher._validate_url_public"):
            with patch("app.services.hatena_fetcher._SAFE_OPENER.open", return_value=_mock_open_resp(html)):
                with patch("trafilatura.extract", side_effect=_fake_trafilatura_extract):
                    result = fetch_article_by_url(STUDIO_DESIGN_URL)

        assert result["text"] == ""
