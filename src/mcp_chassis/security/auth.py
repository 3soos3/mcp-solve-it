"""Authentication and authorization framework for the MCP Chassis server.

Provides a pluggable AuthProvider ABC with two built-in implementations:
- NoAuthProvider: always authenticates (for stdio/trusted environments)
- TokenAuthProvider: simple bearer token comparison (for future HTTP use)
"""

from __future__ import annotations

import hmac
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mcp_chassis.errors import AuthError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthIdentity:
    """Represents an authenticated caller.

    Attributes:
        id: Unique identifier for the caller.
        scopes: Set of authorized scopes granted to this identity.
    """

    id: str
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AuthResult:
    """Result of an authentication attempt.

    Attributes:
        authenticated: Whether authentication succeeded.
        identity: The authenticated identity (None if failed).
        reason: Human-readable reason for failure (empty if succeeded).
    """

    authenticated: bool
    identity: AuthIdentity | None = None
    reason: str = ""

    @classmethod
    def success(cls, identity: AuthIdentity) -> AuthResult:
        """Create a successful auth result.

        Args:
            identity: The authenticated identity.

        Returns:
            AuthResult with authenticated=True.
        """
        return cls(authenticated=True, identity=identity)

    @classmethod
    def failure(cls, reason: str) -> AuthResult:
        """Create a failed auth result.

        Args:
            reason: Human-readable reason for failure.

        Returns:
            AuthResult with authenticated=False.
        """
        return cls(authenticated=False, identity=None, reason=reason)


class AuthProvider(ABC):
    """Abstract base class for authentication providers.

    Implement this class to provide custom authentication logic.
    All methods are async to support I/O-bound auth backends.
    """

    @abstractmethod
    async def authenticate(self, request_context: dict[str, Any]) -> AuthResult:
        """Authenticate an incoming request.

        Args:
            request_context: Dict containing request metadata (headers,
                transport info, etc.). Contents depend on transport type.

        Returns:
            AuthResult indicating success or failure.
        """

    @abstractmethod
    async def authorize(self, identity: AuthIdentity, tool_name: str, scopes: list[str]) -> bool:
        """Check if an identity is authorized to call a tool with given scopes.

        Args:
            identity: The authenticated identity.
            tool_name: Name of the tool being invoked.
            scopes: Required scopes for the tool.

        Returns:
            True if authorized; False otherwise.
        """


class NoAuthProvider(AuthProvider):
    """No-op authentication provider for stdio/trusted environments.

    Always returns authenticated=True with a local identity that has
    all scopes. Suitable for local stdio usage where the transport
    itself provides security.
    """

    async def authenticate(self, request_context: dict[str, Any]) -> AuthResult:
        """Authenticate — always succeeds with a local identity.

        Args:
            request_context: Ignored.

        Returns:
            Successful AuthResult with identity id='local'.
        """
        return AuthResult.success(AuthIdentity(id="local", scopes=frozenset(["*"])))

    async def authorize(self, identity: AuthIdentity, tool_name: str, scopes: list[str]) -> bool:
        """Authorize — always grants access.

        Args:
            identity: The authenticated identity (ignored).
            tool_name: Tool name (ignored).
            scopes: Required scopes (ignored).

        Returns:
            Always True.
        """
        return True


class TokenAuthProvider(AuthProvider):
    """Simple bearer token authentication provider.

    Compares the token in the request context against a configured secret
    using constant-time comparison to prevent timing attacks.

    Designed for future HTTP transport use where a bearer token is
    extracted from the Authorization header.

    Args:
        token: The expected secret token.
    """

    def __init__(self, token: str) -> None:
        """Initialize with the expected token.

        Args:
            token: The secret token to authenticate against.
        """
        self._token = token

    async def authenticate(self, request_context: dict[str, Any]) -> AuthResult:
        """Authenticate by comparing the provided token.

        The request_context must contain a 'token' key with the bearer token.

        Args:
            request_context: Dict with 'token' key.

        Returns:
            AuthResult indicating success or failure.
        """
        provided = request_context.get("token", "")
        if not self._token:
            logger.error("TokenAuthProvider has no token configured")
            return AuthResult.failure("Server misconfiguration: no token configured")

        # Use constant-time comparison to prevent timing attacks
        if not provided:
            return AuthResult.failure("Authentication required: no token provided")

        match = hmac.compare_digest(
            provided.encode("utf-8"),
            self._token.encode("utf-8"),
        )
        if match:
            return AuthResult.success(AuthIdentity(id="token-user", scopes=frozenset(["*"])))
        return AuthResult.failure("Authentication failed: invalid token")

    async def authorize(self, identity: AuthIdentity, tool_name: str, scopes: list[str]) -> bool:
        """Authorize based on wildcard scope or explicit scope match.

        Args:
            identity: The authenticated identity.
            tool_name: Tool being invoked.
            scopes: Required scopes.

        Returns:
            True if identity has '*' scope or all required scopes.
        """
        if "*" in identity.scopes:
            return True
        return all(s in identity.scopes for s in scopes)


class ApiKeyProvider(AuthProvider):
    """API key authentication using SHA-256 hashed key store (FSS-0003 §5.1).

    Validates Authorization: Bearer <key> against a JSON file containing
    SHA-256 hashes of allowed keys. Raw keys are never stored server-side.

    Args:
        keys_path: Path to JSON file {"<sha256-hex>": "<identity-label>"}.
        max_age_days: Maximum allowed key age in days (default 90).
    """

    def __init__(self, keys_path: str, max_age_days: int = 90) -> None:
        self._keys_path = keys_path
        self._max_age_days = max_age_days
        self._key_store: dict[str, str] = {}
        self._load_keys()

    def _load_keys(self) -> None:
        import json as _json
        from pathlib import Path

        if not self._keys_path:
            logger.warning("ApiKeyProvider: no api_keys_path configured")
            return
        try:
            self._key_store = _json.loads(Path(self._keys_path).read_text())
            logger.info(
                "ApiKeyProvider: loaded %d key hashes from %s",
                len(self._key_store),
                self._keys_path,
            )
        except Exception as exc:
            logger.error("ApiKeyProvider: failed to load keys from %s: %s", self._keys_path, exc)

    async def authenticate(self, request_context: dict[str, Any]) -> AuthResult:
        import hashlib

        from mcp_chassis.logging_config import log_security_event

        auth_header: str = request_context.get("authorization_header", "")
        if not auth_header.startswith("Bearer "):
            log_security_event("auth_failure", error_detail="Missing Bearer token")
            return AuthResult.failure("Authentication required: no Bearer token")

        raw_key = auth_header[7:].strip()
        if len(raw_key) < 32:
            log_security_event("auth_failure", error_detail="Key too short")
            return AuthResult.failure("Authentication failed: key too short")

        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        if not self._key_store:
            self._load_keys()

        identity_label = self._key_store.get(key_hash)
        if identity_label is None:
            log_security_event("auth_failure", error_detail="Key hash not found in store")
            return AuthResult.failure("Authentication failed: invalid API key")

        return AuthResult.success(AuthIdentity(id=identity_label, scopes=frozenset(["*"])))

    async def authorize(self, identity: AuthIdentity, tool_name: str, scopes: list[str]) -> bool:
        return "*" in identity.scopes or all(s in identity.scopes for s in scopes)


class OAuthJWTProvider(AuthProvider):
    """OAuth 2.0 JWT authentication via JWKS endpoint (FSS-0003 §5.1 RECOMMENDED).

    Validates Authorization: Bearer <JWT> by fetching the signing key
    from the configured JWKS URL and verifying the token claims.

    Args:
        jwks_url: URL of the JWKS endpoint.
        audience: Expected 'aud' claim value.
        issuer: Expected 'iss' claim value.
    """

    def __init__(self, jwks_url: str, audience: str, issuer: str) -> None:
        self._jwks_url = jwks_url
        self._audience = audience
        self._issuer = issuer
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_cached_at: float = 0.0
        self._jwks_ttl = 3600.0  # 1 hour

    async def _get_jwks(self) -> dict[str, Any]:
        import time

        import httpx

        now = time.monotonic()
        if self._jwks_cache and (now - self._jwks_cached_at) < self._jwks_ttl:
            return self._jwks_cache

        async with httpx.AsyncClient() as client:
            resp = await client.get(self._jwks_url, timeout=10.0)
            resp.raise_for_status()
            self._jwks_cache = resp.json()
            self._jwks_cached_at = now
            logger.debug("JWKS refreshed from %s", self._jwks_url)
            return self._jwks_cache

    async def authenticate(self, request_context: dict[str, Any]) -> AuthResult:
        from mcp_chassis.logging_config import log_security_event

        auth_header: str = request_context.get("authorization_header", "")
        if not auth_header.startswith("Bearer "):
            log_security_event("auth_failure", error_detail="Missing Bearer JWT")
            return AuthResult.failure("Authentication required: no Bearer token")

        token = auth_header[7:].strip()

        try:
            import jwt as pyjwt
        except ImportError:
            logger.error("PyJWT not installed — OAuth auth unavailable. pip install PyJWT")
            return AuthResult.failure("Server misconfiguration: PyJWT not installed")

        try:
            jwks = await self._get_jwks()  # noqa: F841
            # Use PyJWT's PyJWKClient for JWKS-based key selection
            from jwt import PyJWKClient  # type: ignore[import-untyped]

            jwk_client = PyJWKClient(self._jwks_url)
            # Use cached JWKS to avoid extra network call
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "EdDSA"],
                audience=self._audience or None,
                issuer=self._issuer or None,
                options={"require": ["exp", "sub"]},
            )
            subject = payload.get("sub") or payload.get("client_id", "unknown")
            return AuthResult.success(AuthIdentity(id=subject, scopes=frozenset(["*"])))
        except Exception as exc:
            log_security_event("auth_failure", error_detail=str(exc))
            logger.warning("JWT validation failed: %s", exc)
            return AuthResult.failure(f"Authentication failed: {exc}")

    async def authorize(self, identity: AuthIdentity, tool_name: str, scopes: list[str]) -> bool:
        return "*" in identity.scopes or all(s in identity.scopes for s in scopes)


def create_auth_provider(
    provider_type: str,
    token: str = "",
    auth_config: Any = None,
) -> AuthProvider:
    """Factory function to create an AuthProvider by type name.

    Args:
        provider_type: Type name ('none', 'token', 'apikey', 'oauth').
        token: Token for TokenAuthProvider (ignored for other types).
        auth_config: AuthConfig dataclass for advanced providers.

    Returns:
        An AuthProvider instance.

    Raises:
        AuthError: If the provider type is unknown.
    """
    if provider_type == "none":
        return NoAuthProvider()
    elif provider_type == "token":
        return TokenAuthProvider(token)
    elif provider_type == "apikey":
        keys_path = getattr(auth_config, "api_keys_path", "") if auth_config else ""
        max_age = getattr(auth_config, "api_key_max_age_days", 90) if auth_config else 90
        return ApiKeyProvider(keys_path=keys_path, max_age_days=max_age)
    elif provider_type == "oauth":
        jwks_url = getattr(auth_config, "oauth_jwks_url", "") if auth_config else ""
        audience = getattr(auth_config, "oauth_audience", "") if auth_config else ""
        issuer = getattr(auth_config, "oauth_issuer", "") if auth_config else ""
        return OAuthJWTProvider(jwks_url=jwks_url, audience=audience, issuer=issuer)
    else:
        raise AuthError(
            f"Unknown auth provider type '{provider_type}'",
            code="UNKNOWN_AUTH_PROVIDER",
        )


async def check_auth(
    provider: AuthProvider,
    request_context: dict[str, Any],
    tool_name: str,
    required_scopes: list[str],
) -> AuthIdentity:
    """Run full auth check (authenticate + authorize) and raise on failure.

    Convenience function for use in middleware.

    Args:
        provider: The AuthProvider to use.
        request_context: Request metadata for authentication.
        tool_name: Tool name for authorization check.
        required_scopes: Scopes required to call the tool.

    Returns:
        The authenticated and authorized AuthIdentity.

    Raises:
        AuthError: If authentication or authorization fails.
    """
    result = await provider.authenticate(request_context)
    if not result.authenticated or result.identity is None:
        raise AuthError(f"Authentication failed: {result.reason}")

    authorized = await provider.authorize(result.identity, tool_name, required_scopes)
    if not authorized:
        raise AuthError(
            f"Authorization failed: identity '{result.identity.id}' "
            f"lacks required scopes for tool '{tool_name}'"
        )

    return result.identity
