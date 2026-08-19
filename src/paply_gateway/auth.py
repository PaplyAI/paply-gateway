import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time
from typing import Any

from fastapi import HTTPException, Request

from paply_gateway.settings import Settings


@dataclass(frozen=True)
class GatewayIdentity:
    user_id: str


def _decode_segment(segment: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=401, detail="Invalid Paply session token") from error


def _json_object(segment: str) -> dict[str, Any]:
    try:
        value = json.loads(_decode_segment(segment))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=401, detail="Invalid Paply session token") from error
    if not isinstance(value, dict):
        raise HTTPException(status_code=401, detail="Invalid Paply session token")
    return value


def encode_access_token(
    *,
    user_id: str,
    secret: str,
    issuer: str,
    audience: str,
    expires_at: int,
    issued_at: int | None = None,
) -> str:
    normalized_user_id = user_id.strip()
    if not normalized_user_id or len(normalized_user_id) > 128:
        raise ValueError("user_id must contain 1 to 128 characters")
    now = int(time()) if issued_at is None else issued_at
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "aud": audience,
        "exp": expires_at,
        "iat": now,
        "iss": issuer,
        "sub": normalized_user_id,
    }

    def encode(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = f"{encode(header)}.{encode(payload)}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def authenticate_access_token(token: str, settings: Settings) -> GatewayIdentity:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid Paply session token")
    header_segment, payload_segment, signature_segment = parts
    header = _json_object(header_segment)
    payload = _json_object(payload_segment)
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise HTTPException(status_code=401, detail="Unsupported Paply session token")

    signing_input = f"{header_segment}.{payload_segment}".encode()
    expected = hmac.new(
        settings.auth_jwt_secret.encode(), signing_input, hashlib.sha256
    ).digest()
    supplied = _decode_segment(signature_segment)
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid Paply session token")

    if payload.get("iss") != settings.paply_auth_jwt_issuer:
        raise HTTPException(status_code=401, detail="Invalid Paply session issuer")
    audience = payload.get("aud")
    if audience != settings.paply_auth_jwt_audience:
        raise HTTPException(status_code=401, detail="Invalid Paply session audience")
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at <= int(time()):
        raise HTTPException(status_code=401, detail="Paply session has expired")
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int) or issued_at > int(time()) + 60:
        raise HTTPException(status_code=401, detail="Invalid Paply session issue time")
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id.strip()) > 128:
        raise HTTPException(status_code=401, detail="Paply session has no valid user identity")
    return GatewayIdentity(user_id=user_id.strip())


def bearer_identity(request: Request, settings: Settings) -> GatewayIdentity:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="A Paply login session is required")
    return authenticate_access_token(token.strip(), settings)
