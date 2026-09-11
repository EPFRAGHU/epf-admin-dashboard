"""Signed, expiring tokens for the one-time set-password handover link.

No email/SMS is sent by this app -- the link is surfaced in the UI for the
superadmin / reseller to deliver manually. The token is stateless and signed
with the same JWT_SECRET the rest of the app uses; an Enrollment row also
stores the token's `jti` so a resend can invalidate the previous link.
"""
import os
from itsdangerous import URLSafeTimedSerializer

_SECRET = os.environ.get("JWT_SECRET", "epf-keka-theme-super-secret-jwt-key-2026")
_SALT = "reseller-set-password-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_SECRET, salt=_SALT)


def make_set_password_token(user_id: int, jti: str) -> str:
    return _serializer().dumps({"user_id": int(user_id), "jti": str(jti)})


def read_set_password_token(token: str, max_age_days: int = 7):
    try:
        data = _serializer().loads(token, max_age=max_age_days * 86400)
        if not isinstance(data, dict):
            return None
        return {"user_id": int(data["user_id"]), "jti": str(data["jti"])}
    except Exception:
        return None
