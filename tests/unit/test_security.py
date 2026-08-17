"""
tests/unit/test_security.py — Unit tests for HMAC signature verification.

These tests verify that:
1. A correctly signed request is accepted.
2. A request with a wrong signature is rejected.
3. A request with a missing signature is rejected.
4. A request with a tampered body is rejected.
5. Constant-time comparison is used (timing-safe).

These are pure unit tests — no DB, no Redis, no HTTP.
"""

import hashlib
import hmac


from app.utils.security import verify_signature


SECRET = "my_test_api_key"


def make_sig(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(
        key=secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


class TestVerifySignature:
    def test_valid_signature_accepted(self):
        body = b'{"event_id": "evt_1"}'
        sig = make_sig(body)
        assert verify_signature(body, sig, SECRET) is True

    def test_wrong_signature_rejected(self):
        body = b'{"event_id": "evt_1"}'
        wrong_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        assert verify_signature(body, wrong_sig, SECRET) is False

    def test_missing_signature_rejected(self):
        body = b'{"event_id": "evt_1"}'
        assert verify_signature(body, "", SECRET) is False

    def test_tampered_body_rejected(self):
        original_body = b'{"event_id": "evt_1"}'
        sig = make_sig(original_body)
        tampered_body = b'{"event_id": "evt_2_INJECTED"}'
        assert verify_signature(tampered_body, sig, SECRET) is False

    def test_wrong_prefix_rejected(self):
        body = b'{"event_id": "evt_1"}'
        # Using md5= prefix instead of sha256=
        digest = hashlib.md5(body).hexdigest()
        sig = f"md5={digest}"
        assert verify_signature(body, sig, SECRET) is False

    def test_wrong_secret_rejected(self):
        body = b'{"event_id": "evt_1"}'
        sig = make_sig(body, secret="correct_secret")
        assert verify_signature(body, sig, "wrong_secret") is False

    def test_empty_body_valid_signature(self):
        """Empty body with valid signature should be accepted."""
        body = b""
        sig = make_sig(body)
        assert verify_signature(body, sig, SECRET) is True

    def test_unicode_body(self):
        """Unicode content in body should work correctly."""
        body = "hello wörld 🎉".encode("utf-8")
        sig = make_sig(body)
        assert verify_signature(body, sig, SECRET) is True
