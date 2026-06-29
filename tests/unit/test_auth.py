"""Unit tests for mcp_chassis.security.auth module."""

import hashlib
import json

import pytest

from mcp_chassis.errors import AuthError
from mcp_chassis.security.auth import (
    AuthIdentity,
    AuthProvider,
    AuthResult,
    NoAuthProvider,
    TokenAuthProvider,
    check_auth,
    create_auth_provider,
)


class TestAuthIdentity:
    """Tests for AuthIdentity dataclass."""

    def test_basic_identity(self) -> None:
        identity = AuthIdentity(id="user1")
        assert identity.id == "user1"
        assert identity.scopes == frozenset()

    def test_identity_with_scopes(self) -> None:
        identity = AuthIdentity(id="admin", scopes=frozenset(["read", "write"]))
        assert "read" in identity.scopes
        assert "write" in identity.scopes

    def test_identity_is_frozen(self) -> None:
        identity = AuthIdentity(id="user")
        with pytest.raises((AttributeError, TypeError)):
            identity.id = "changed"  # type: ignore[misc]


class TestAuthResult:
    """Tests for AuthResult dataclass."""

    def test_success_result(self) -> None:
        identity = AuthIdentity(id="user")
        result = AuthResult.success(identity)
        assert result.authenticated
        assert result.identity == identity
        assert result.reason == ""

    def test_failure_result(self) -> None:
        result = AuthResult.failure("bad token")
        assert not result.authenticated
        assert result.identity is None
        assert result.reason == "bad token"


class TestNoAuthProvider:
    """Tests for NoAuthProvider."""

    @pytest.mark.asyncio
    async def test_authenticate_always_succeeds(self) -> None:
        provider = NoAuthProvider()
        result = await provider.authenticate({})
        assert result.authenticated

    @pytest.mark.asyncio
    async def test_authenticate_returns_local_identity(self) -> None:
        provider = NoAuthProvider()
        result = await provider.authenticate({"some": "context"})
        assert result.identity is not None
        assert result.identity.id == "local"

    @pytest.mark.asyncio
    async def test_authenticate_grants_wildcard_scope(self) -> None:
        provider = NoAuthProvider()
        result = await provider.authenticate({})
        assert result.identity is not None
        assert "*" in result.identity.scopes

    @pytest.mark.asyncio
    async def test_authorize_always_true(self) -> None:
        provider = NoAuthProvider()
        identity = AuthIdentity(id="local", scopes=frozenset(["*"]))
        assert await provider.authorize(identity, "any_tool", ["any_scope"])

    @pytest.mark.asyncio
    async def test_is_auth_provider(self) -> None:
        provider = NoAuthProvider()
        assert isinstance(provider, AuthProvider)


class TestTokenAuthProvider:
    """Tests for TokenAuthProvider."""

    @pytest.mark.asyncio
    async def test_valid_token_authenticates(self) -> None:
        provider = TokenAuthProvider("secret-token")
        result = await provider.authenticate({"token": "secret-token"})
        assert result.authenticated

    @pytest.mark.asyncio
    async def test_invalid_token_fails(self) -> None:
        provider = TokenAuthProvider("secret-token")
        result = await provider.authenticate({"token": "wrong-token"})
        assert not result.authenticated

    @pytest.mark.asyncio
    async def test_missing_token_fails(self) -> None:
        provider = TokenAuthProvider("secret-token")
        result = await provider.authenticate({})
        assert not result.authenticated

    @pytest.mark.asyncio
    async def test_empty_provider_token_fails(self) -> None:
        # Provider configured with empty token — server misconfiguration
        provider = TokenAuthProvider("")
        result = await provider.authenticate({"token": "anything"})
        assert not result.authenticated

    @pytest.mark.asyncio
    async def test_successful_auth_returns_identity(self) -> None:
        provider = TokenAuthProvider("my-token")
        result = await provider.authenticate({"token": "my-token"})
        assert result.identity is not None
        assert result.identity.id == "token-user"

    @pytest.mark.asyncio
    async def test_authorize_with_wildcard_scope(self) -> None:
        provider = TokenAuthProvider("t")
        identity = AuthIdentity(id="u", scopes=frozenset(["*"]))
        assert await provider.authorize(identity, "tool", ["read", "write"])

    @pytest.mark.asyncio
    async def test_authorize_without_required_scope(self) -> None:
        provider = TokenAuthProvider("t")
        identity = AuthIdentity(id="u", scopes=frozenset(["read"]))
        assert not await provider.authorize(identity, "tool", ["read", "write"])

    @pytest.mark.asyncio
    async def test_authorize_with_all_required_scopes(self) -> None:
        provider = TokenAuthProvider("t")
        identity = AuthIdentity(id="u", scopes=frozenset(["read", "write"]))
        assert await provider.authorize(identity, "tool", ["read", "write"])


class TestCreateAuthProvider:
    """Tests for create_auth_provider factory function."""

    def test_creates_no_auth_provider(self) -> None:
        provider = create_auth_provider("none")
        assert isinstance(provider, NoAuthProvider)

    def test_creates_token_auth_provider(self) -> None:
        provider = create_auth_provider("token", "my-secret")
        assert isinstance(provider, TokenAuthProvider)

    def test_creates_apikey_provider(self) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        provider = create_auth_provider("apikey")
        assert isinstance(provider, ApiKeyProvider)

    def test_creates_oauth_provider(self) -> None:
        from mcp_chassis.security.auth import OAuthJWTProvider
        provider = create_auth_provider("oauth")
        assert isinstance(provider, OAuthJWTProvider)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(AuthError):
            create_auth_provider("unknown_provider")


class TestCheckAuth:
    """Tests for check_auth convenience function."""

    @pytest.mark.asyncio
    async def test_successful_auth_returns_identity(self) -> None:
        provider = NoAuthProvider()
        identity = await check_auth(provider, {}, "my_tool", [])
        assert identity.id == "local"

    @pytest.mark.asyncio
    async def test_failed_auth_raises_auth_error(self) -> None:
        provider = TokenAuthProvider("secret")
        with pytest.raises(AuthError):
            await check_auth(provider, {"token": "wrong"}, "tool", [])

    @pytest.mark.asyncio
    async def test_failed_authz_raises_auth_error(self) -> None:
        # Auth succeeds but authz fails because of missing scope
        # (token provider grants * scope on success, so we test with a custom provider)
        class RestrictedProvider(AuthProvider):
            async def authenticate(self, request_context: dict) -> AuthResult:
                return AuthResult.success(
                    AuthIdentity(id="limited", scopes=frozenset(["read"]))
                )

            async def authorize(
                self, identity: AuthIdentity, tool_name: str, scopes: list[str]
            ) -> bool:
                return False

        provider_r = RestrictedProvider()
        with pytest.raises(AuthError, match="Authorization failed"):
            await check_auth(provider_r, {}, "admin_tool", ["admin"])


class TestApiKeyProvider:
    """Tests for ApiKeyProvider — hashed key store auth."""

    def _make_key_store(self, tmp_path: object, keys: dict[str, str]) -> str:
        """Write a hashed key store JSON file and return its path."""
        import pathlib
        store = {
            hashlib.sha256(k.encode()).hexdigest(): label
            for k, label in keys.items()
        }
        p = pathlib.Path(str(tmp_path)) / "keys.json"
        p.write_text(json.dumps(store))
        return str(p)

    @pytest.mark.asyncio
    async def test_valid_key_authenticates(self, tmp_path: object) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        raw_key = "a" * 32  # 32 bytes entropy minimum
        path = self._make_key_store(tmp_path, {raw_key: "analyst-1"})
        provider = ApiKeyProvider(keys_path=path)
        result = await provider.authenticate(
            {"authorization_header": f"Bearer {raw_key}"}
        )
        assert result.authenticated
        assert result.identity is not None
        assert result.identity.id == "analyst-1"

    @pytest.mark.asyncio
    async def test_wrong_key_fails(self, tmp_path: object) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        raw_key = "a" * 32
        path = self._make_key_store(tmp_path, {raw_key: "analyst-1"})
        provider = ApiKeyProvider(keys_path=path)
        result = await provider.authenticate(
            {"authorization_header": "Bearer " + "b" * 32}
        )
        assert not result.authenticated

    @pytest.mark.asyncio
    async def test_missing_authorization_header_fails(self, tmp_path: object) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        path = self._make_key_store(tmp_path, {"a" * 32: "analyst-1"})
        provider = ApiKeyProvider(keys_path=path)
        result = await provider.authenticate({})
        assert not result.authenticated
        assert "no Bearer token" in result.reason

    @pytest.mark.asyncio
    async def test_key_too_short_fails(self, tmp_path: object) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        path = self._make_key_store(tmp_path, {"short": "analyst-1"})
        provider = ApiKeyProvider(keys_path=path)
        result = await provider.authenticate(
            {"authorization_header": "Bearer short"}
        )
        assert not result.authenticated
        assert "too short" in result.reason

    @pytest.mark.asyncio
    async def test_empty_key_store_fails(self, tmp_path: object) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        path = self._make_key_store(tmp_path, {})
        provider = ApiKeyProvider(keys_path=path)
        result = await provider.authenticate(
            {"authorization_header": "Bearer " + "a" * 32}
        )
        assert not result.authenticated

    @pytest.mark.asyncio
    async def test_authorize_grants_wildcard(self, tmp_path: object) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        path = self._make_key_store(tmp_path, {"a" * 32: "analyst-1"})
        provider = ApiKeyProvider(keys_path=path)
        identity = AuthIdentity(id="analyst-1", scopes=frozenset(["*"]))
        assert await provider.authorize(identity, "any_tool", ["any_scope"])

    def test_missing_keys_path_logs_warning(self) -> None:
        from mcp_chassis.security.auth import ApiKeyProvider
        # Should not raise — just logs a warning
        provider = ApiKeyProvider(keys_path="")
        assert provider is not None


class TestOAuthJWTProvider:
    """Tests for OAuthJWTProvider — basic instantiation and auth failure paths."""

    def test_creates_with_config(self) -> None:
        from mcp_chassis.security.auth import OAuthJWTProvider
        provider = OAuthJWTProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            audience="my-api",
            issuer="https://example.com/",
        )
        assert provider is not None

    @pytest.mark.asyncio
    async def test_missing_bearer_token_fails(self) -> None:
        from mcp_chassis.security.auth import OAuthJWTProvider
        provider = OAuthJWTProvider(jwks_url="https://example.com/jwks",
                                    audience="", issuer="")
        result = await provider.authenticate({})
        assert not result.authenticated
        assert "no Bearer token" in result.reason

    @pytest.mark.asyncio
    async def test_missing_authorization_header_fails(self) -> None:
        from mcp_chassis.security.auth import OAuthJWTProvider
        provider = OAuthJWTProvider(jwks_url="https://example.com/jwks",
                                    audience="", issuer="")
        result = await provider.authenticate({"authorization_header": "Basic abc"})
        assert not result.authenticated

    @pytest.mark.asyncio
    async def test_authorize_grants_wildcard(self) -> None:
        from mcp_chassis.security.auth import OAuthJWTProvider
        provider = OAuthJWTProvider(jwks_url="", audience="", issuer="")
        identity = AuthIdentity(id="sub-123", scopes=frozenset(["*"]))
        assert await provider.authorize(identity, "tool", ["scope"])
