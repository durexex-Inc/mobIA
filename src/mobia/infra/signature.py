import hashlib
import hmac

SIGNATURE_HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="


def compute_signature(app_secret: str, body: bytes) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"


def is_valid_signature(app_secret: str, body: bytes, header_value: str | None) -> bool:
    if not header_value or not header_value.startswith(_PREFIX):
        return False
    return hmac.compare_digest(compute_signature(app_secret, body), header_value)
