"""
utils/security.py — HMAC-SHA256 webhook signature verification.
"""

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """
    Return True if the X-PseudoGram-Signature header is valid.

    Args:
        raw_body:         The raw request body bytes (before JSON parsing).
        signature_header: The full value of X-PseudoGram-Signature, e.g.
                          "sha256=abc123...".
        secret:           The shared secret (PSEUDOGRAM_API_KEY).

    Returns:
        True if valid, False otherwise.
    """
    if not signature_header:
        logger.warning("Missing X-PseudoGram-Signature header")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Unexpected signature format: %s", signature_header[:20])
        return False

    provided_hex = signature_header[len("sha256="):]

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    is_valid = hmac.compare_digest(expected, provided_hex)

    if not is_valid:
        logger.warning("Signature mismatch — rejecting webhook")

    return is_valid
