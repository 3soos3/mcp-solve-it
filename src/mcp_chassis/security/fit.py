"""FIT JWT validation (FSS-0006 §8)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_REVOKED_JTIS: set[str] = set()  # populated by future revocation endpoint
_JWKS_CACHE: dict[str, tuple[Any, float]] = {}  # url → (jwks_data, cached_at)
_JWKS_TTL = 300.0


@dataclass
class FITClaims:
    jti: str
    issuer: str
    valid_until: str  # ISO 8601 UTC
    aud: str
    legal_authority: str
    purpose: str
    investigation_id: str
    authorized_tools: list[str]
    authorized_analyst: str
    invocation_types_permitted: list[str]


class FITVerificationError(Exception):
    def __init__(self, step: int, reason: str) -> None:
        self.step = step
        super().__init__(f"FIT step {step} failed: {reason}")


async def _fetch_jwks(url: str) -> Any:
    import httpx
    now = time.monotonic()
    cached = _JWKS_CACHE.get(url)
    if cached and (now - cached[1]) < _JWKS_TTL:
        return cached[0]
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    _JWKS_CACHE[url] = (data, now)
    return data


def _jwks_url_for_issuer(issuer: str) -> str:
    import os
    override = os.environ.get("FSS_FIT_ISSUER_JWKS_URL")
    if override:
        return override
    # Auto-discover: try {iss}/.well-known/fss-jwks.json
    return issuer.rstrip("/") + "/.well-known/fss-jwks.json"


def _is_trusted_issuer(issuer: str) -> bool:
    import os
    trusted_env = os.environ.get("FSS_FIT_TRUSTED_ISSUERS", "")
    if not trusted_env:
        return True  # Open trust — accept any issuer we can verify
    trusted = [i.strip() for i in trusted_env.split(",") if i.strip()]
    return issuer in trusted


async def verify_fit(
    token: str,
    tool_name: str,
    investigation_id: str | None,
    client_identity: str | None,
    invocation_type: str,
    server_identity: str,
) -> FITClaims:
    """Run the 11-step FIT verification procedure (FSS-0006 §8.2).

    Raises FITVerificationError on any step failure.
    """
    try:
        import jwt as pyjwt
        from jwt import PyJWKClient
    except ImportError as exc:
        raise FITVerificationError(0, "PyJWT not installed — cannot verify FIT") from exc

    # Step 1 — Type check
    try:
        header = pyjwt.get_unverified_header(token)
    except Exception as exc:
        raise FITVerificationError(1, f"Cannot decode FIT header: {exc}") from exc
    if header.get("typ") != "FIT+JWT":
        raise FITVerificationError(1, f"FIT typ must be FIT+JWT, got {header.get('typ')!r}")

    # Step 2 — Issuer resolution
    try:
        unverified = pyjwt.decode(token, options={"verify_signature": False})
    except Exception as exc:
        raise FITVerificationError(2, f"Cannot decode FIT payload: {exc}") from exc
    issuer = unverified.get("iss", "")
    if not issuer:
        raise FITVerificationError(2, "FIT has no iss claim")
    if not _is_trusted_issuer(issuer):
        raise FITVerificationError(2, f"FIT issuer {issuer!r} not in trusted issuers")

    # Step 3 — Key resolution and Step 4 — Signature verification
    jwks_url = _jwks_url_for_issuer(issuer)
    try:
        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
    except Exception as exc:
        raise FITVerificationError(3, f"Key resolution failed: {exc}") from exc

    try:
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "EdDSA"],
            options={"require": ["exp", "jti"]},
            audience=server_identity if server_identity else None,
            leeway=30,
        )
    except pyjwt.exceptions.InvalidAudienceError as exc:
        raise FITVerificationError(5, f"Audience check failed: {exc}") from exc
    except pyjwt.exceptions.ExpiredSignatureError as exc:
        raise FITVerificationError(7, f"FIT expired: {exc}") from exc
    except pyjwt.exceptions.ImmatureSignatureError as exc:
        raise FITVerificationError(7, f"FIT not yet valid: {exc}") from exc
    except Exception as exc:
        raise FITVerificationError(4, f"Signature verification failed: {exc}") from exc

    # Step 5 — Audience check (already done by pyjwt.decode with audience=)
    # (handled above)

    # Step 6 — Revocation check
    jti = payload.get("jti", "")
    if jti in _REVOKED_JTIS:
        raise FITVerificationError(6, f"FIT jti {jti!r} is revoked")

    # Step 7 — Time window already checked by pyjwt.decode (exp/nbf + leeway)

    # Step 8 — Investigation match
    fit_inv_id = payload.get("investigation_id")
    if investigation_id and fit_inv_id and fit_inv_id != investigation_id:
        raise FITVerificationError(
            8,
            f"investigation_id mismatch: FIT has {fit_inv_id!r}, request has {investigation_id!r}",
        )

    # Step 9 — Tool authorization
    authorized_tools: list[str] = payload.get("authorized_tools", [])
    if authorized_tools:
        import re as _re
        matched = any(
            tool_name == pattern or _re.fullmatch(pattern, tool_name)
            for pattern in authorized_tools
        )
        if not matched:
            raise FITVerificationError(
                9, f"Tool {tool_name!r} not in authorized_tools {authorized_tools}"
            )

    # Step 10 — Analyst match
    authorized_analyst = payload.get("authorized_analyst", "")
    if authorized_analyst and client_identity and authorized_analyst != client_identity:
        raise FITVerificationError(
            10,
            f"client_identity {client_identity!r} != authorized_analyst {authorized_analyst!r}",
        )

    # Step 11 — Invocation type check
    permitted_types: list[str] = payload.get("invocation_types_permitted", [])
    if permitted_types and invocation_type not in permitted_types:
        raise FITVerificationError(
            11, f"invocation_type {invocation_type!r} not in permitted {permitted_types}"
        )

    # Build exp as ISO 8601
    import datetime
    exp = payload.get("exp", 0)
    valid_until = datetime.datetime.fromtimestamp(exp, tz=datetime.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    aud = payload.get("aud", "")
    if isinstance(aud, list):
        aud = aud[0] if aud else ""

    return FITClaims(
        jti=jti,
        issuer=issuer,
        valid_until=valid_until,
        aud=aud,
        legal_authority=payload.get("legal_authority", ""),
        purpose=payload.get("purpose", ""),
        investigation_id=payload.get("investigation_id", ""),
        authorized_tools=authorized_tools,
        authorized_analyst=authorized_analyst,
        invocation_types_permitted=permitted_types,
    )
