import hashlib
import hmac
import time

from starlette.requests import Request


def _request(headers: dict[str, str], path: str = "/generate") -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": raw_headers,
        "client": ("10.0.0.8", 1234),
    })


def _signed_headers(ip: str, secret: str, timestamp: str) -> dict[str, str]:
    payload = "\n".join((ip, "POST", "/generate", timestamp))
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Verified-Client-IP": ip,
        "X-Verified-Client-IP-Timestamp": timestamp,
        "X-Verified-Client-IP-Signature": signature,
    }


def test_valid_signature_is_accepted(monkeypatch):
    secret = "dedicated-secret"
    monkeypatch.setenv("PROXY_CLIENT_IP_HMAC_SECRET", secret)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services.verified_client_ip import get_verified_client_ip

    assert get_verified_client_ip(_request(_signed_headers("198.51.100.10", secret, str(int(time.time()))))) == "198.51.100.10"


def test_invalid_expired_and_mismatched_signatures_fall_back(monkeypatch):
    secret = "dedicated-secret"
    monkeypatch.setenv("PROXY_CLIENT_IP_HMAC_SECRET", secret)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services.verified_client_ip import get_verified_client_ip

    valid = _signed_headers("198.51.100.10", secret, str(int(time.time()) - 61))
    assert get_verified_client_ip(_request(valid)) == "10.0.0.8"

    tampered = _signed_headers("198.51.100.11", secret, str(int(time.time())))
    tampered["X-Verified-Client-IP-Signature"] = valid["X-Verified-Client-IP-Signature"]
    assert get_verified_client_ip(_request(tampered)) == "10.0.0.8"


def test_malformed_ip_falls_back(monkeypatch):
    secret = "dedicated-secret"
    monkeypatch.setenv("PROXY_CLIENT_IP_HMAC_SECRET", secret)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services.verified_client_ip import get_verified_client_ip

    assert get_verified_client_ip(_request(_signed_headers("not-an-ip", secret, str(int(time.time()))))) == "10.0.0.8"
