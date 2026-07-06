"""Unit tests for mcp_chassis.security.fit — FIT JWT verification (FSS-0006 §8)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from mcp_chassis.security.fit import FITClaims, FITVerificationError

# ── Fake exception classes (real Exception subclasses so except clauses work) ─


class _FakeInvalidAudienceError(Exception):
    pass


class _FakeExpiredSignatureError(Exception):
    pass


class _FakeImmatureSignatureError(Exception):
    pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _default_payload() -> dict:
    return {
        "jti": "test-jti-123",
        "iss": "https://issuer.example.com",
        "exp": 9_999_999_999,
        "aud": "test-server",
        "legal_authority": "Art. 126a Sv",
        "purpose": "investigation",
        "investigation_id": "inv-001",
        "authorized_tools": [],
        "authorized_analyst": "",
        "invocation_types_permitted": [],
    }


def _make_jwt_mock(
    *,
    header: dict | None = None,
    unverified_payload: dict | None = None,
    verified_payload: dict | None = None,
    header_exc: Exception | None = None,
    unverified_exc: Exception | None = None,
    verified_exc: Exception | None = None,
    key_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock jwt module with configurable behaviour per step."""
    mock = MagicMock()

    # Step 1 — header
    if header_exc:
        mock.get_unverified_header.side_effect = header_exc
    else:
        mock.get_unverified_header.return_value = header or {
            "typ": "FIT+JWT",
            "alg": "EdDSA",
        }

    # Step 2 / step 4 — decode (called twice: unverified then verified)
    if unverified_exc:
        mock.decode.side_effect = [unverified_exc]
    elif verified_exc:
        mock.decode.side_effect = [
            unverified_payload or _default_payload(),
            verified_exc,
        ]
    else:
        mock.decode.side_effect = [
            unverified_payload or _default_payload(),
            verified_payload or _default_payload(),
        ]

    # Step 3 — key resolution
    mock_signing_key = MagicMock()
    mock_signing_key.key = MagicMock()
    mock_jwk_client = MagicMock()
    if key_exc:
        mock_jwk_client.get_signing_key_from_jwt.side_effect = key_exc
    else:
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key
    mock.PyJWKClient = MagicMock(return_value=mock_jwk_client)

    # Exception classes — must be real types for except clauses
    mock.exceptions = MagicMock()
    mock.exceptions.InvalidAudienceError = _FakeInvalidAudienceError
    mock.exceptions.ExpiredSignatureError = _FakeExpiredSignatureError
    mock.exceptions.ImmatureSignatureError = _FakeImmatureSignatureError

    return mock


@pytest.fixture()
def mock_jwt(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a default-happy mock jwt module."""
    m = _make_jwt_mock()
    monkeypatch.setitem(sys.modules, "jwt", m)
    monkeypatch.setitem(sys.modules, "jwt.exceptions", m.exceptions)
    return m


# ── FITVerificationError ──────────────────────────────────────────────────────


class TestFITVerificationError:
    def test_step_and_message_stored(self) -> None:
        exc = FITVerificationError(3, "Key resolution failed: timeout")
        assert exc.step == 3
        assert "step 3" in str(exc)
        assert "Key resolution failed" in str(exc)

    def test_is_exception(self) -> None:
        assert isinstance(FITVerificationError(0, "x"), Exception)


# ── FITClaims ─────────────────────────────────────────────────────────────────


class TestFITClaims:
    def test_fields_stored(self) -> None:
        c = FITClaims(
            jti="j1",
            issuer="https://iss",
            valid_until="2030-01-01T00:00:00Z",
            aud="srv",
            legal_authority="auth",
            purpose="p",
            investigation_id="inv",
            authorized_tools=["tool_a"],
            authorized_analyst="analyst",
            invocation_types_permitted=["agent_supervised"],
        )
        assert c.jti == "j1"
        assert c.authorized_tools == ["tool_a"]


# ── verify_fit: happy path ────────────────────────────────────────────────────


class TestVerifyFITHappyPath:
    async def test_returns_fit_claims(self, mock_jwt: MagicMock) -> None:
        from mcp_chassis.security.fit import verify_fit

        claims = await verify_fit(
            token="header.payload.sig",
            tool_name="any_tool",
            investigation_id="inv-001",
            client_identity=None,
            invocation_type="agent_supervised",
            server_identity="test-server",
        )
        assert isinstance(claims, FITClaims)
        assert claims.jti == "test-jti-123"
        assert claims.issuer == "https://issuer.example.com"

    async def test_claims_map_all_payload_fields(self, mock_jwt: MagicMock) -> None:
        from mcp_chassis.security.fit import verify_fit

        claims = await verify_fit(
            token="t",
            tool_name="tool",
            investigation_id=None,
            client_identity=None,
            invocation_type="agent_supervised",
            server_identity="",
        )
        assert claims.legal_authority == "Art. 126a Sv"
        assert claims.purpose == "investigation"
        assert claims.investigation_id == "inv-001"


# ── verify_fit: step failures ─────────────────────────────────────────────────


class TestVerifyFITStepFailures:
    async def test_step0_pyjwt_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "jwt", None)  # type: ignore[arg-type]
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 0

    async def test_step1_bad_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _make_jwt_mock(header_exc=ValueError("bad token"))
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 1

    async def test_step1_wrong_typ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _make_jwt_mock(header={"typ": "JWT", "alg": "EdDSA"})
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 1

    async def test_step2_cannot_decode_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _make_jwt_mock(unverified_exc=ValueError("bad payload"))
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 2

    async def test_step2_missing_issuer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {**_default_payload(), "iss": ""}
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 2

    async def test_step2_untrusted_issuer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FSS_FIT_TRUSTED_ISSUERS", "https://other.example.com")
        m = _make_jwt_mock()
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 2

    async def test_step3_key_resolution_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _make_jwt_mock(key_exc=Exception("network error"))
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 3

    async def test_step4_signature_verification_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _make_jwt_mock(verified_exc=Exception("bad sig"))
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 4

    async def test_step5_invalid_audience(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = _make_jwt_mock(
            verified_exc=_FakeInvalidAudienceError("wrong audience")
        )
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 5

    async def test_step7_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _make_jwt_mock(verified_exc=_FakeExpiredSignatureError("expired"))
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 7

    async def test_step7_not_yet_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = _make_jwt_mock(
            verified_exc=_FakeImmatureSignatureError("not yet valid")
        )
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 7

    async def test_step8_investigation_id_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {**_default_payload(), "investigation_id": "inv-999"}
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit(
                "t", "tool", "inv-001", None, "agent_supervised", ""
            )
        assert exc_info.value.step == 8

    async def test_step9_tool_not_authorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {**_default_payload(), "authorized_tools": ["allowed_tool"]}
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "other_tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 9

    async def test_step9_wildcard_pattern_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {**_default_payload(), "authorized_tools": ["solveit_.*"]}
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        claims = await verify_fit(
            "t", "solveit_search", None, None, "agent_supervised", ""
        )
        assert claims.authorized_tools == ["solveit_.*"]

    async def test_step10_analyst_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {**_default_payload(), "authorized_analyst": "alice"}
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, "bob", "agent_supervised", "")
        assert exc_info.value.step == 10

    async def test_step10_analyst_match_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {**_default_payload(), "authorized_analyst": "alice"}
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        claims = await verify_fit("t", "tool", None, "alice", "agent_supervised", "")
        assert claims.authorized_analyst == "alice"

    async def test_step11_invocation_type_not_permitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            **_default_payload(),
            "invocation_types_permitted": ["human_direct"],
        }
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_autonomous", "")
        assert exc_info.value.step == 11

    async def test_step11_permitted_type_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            **_default_payload(),
            "invocation_types_permitted": ["agent_supervised"],
        }
        m = _make_jwt_mock(unverified_payload=payload, verified_payload=payload)
        monkeypatch.setitem(sys.modules, "jwt", m)
        from mcp_chassis.security.fit import verify_fit

        claims = await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert claims.invocation_types_permitted == ["agent_supervised"]


# ── verify_fit: revocation ────────────────────────────────────────────────────


class TestVerifyFITRevocation:
    async def test_step6_revoked_jti_blocked(
        self, mock_jwt: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mcp_chassis.security.fit as fit_module

        monkeypatch.setattr(fit_module, "_REVOKED_JTIS", {"test-jti-123"})
        from mcp_chassis.security.fit import verify_fit

        with pytest.raises(FITVerificationError) as exc_info:
            await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert exc_info.value.step == 6

    async def test_non_revoked_jti_passes(
        self, mock_jwt: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mcp_chassis.security.fit as fit_module

        monkeypatch.setattr(fit_module, "_REVOKED_JTIS", set())
        from mcp_chassis.security.fit import verify_fit

        claims = await verify_fit("t", "tool", None, None, "agent_supervised", "")
        assert claims.jti == "test-jti-123"


# ── _is_trusted_issuer + _jwks_url_for_issuer ─────────────────────────────────


class TestIsTrustedIssuer:
    def test_empty_env_trusts_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FSS_FIT_TRUSTED_ISSUERS", raising=False)
        from mcp_chassis.security.fit import _is_trusted_issuer

        assert _is_trusted_issuer("https://anyone.example.com") is True

    def test_issuer_in_list_trusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FSS_FIT_TRUSTED_ISSUERS", "https://a.com,https://b.com")
        from mcp_chassis.security.fit import _is_trusted_issuer

        assert _is_trusted_issuer("https://a.com") is True
        assert _is_trusted_issuer("https://b.com") is True

    def test_issuer_not_in_list_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FSS_FIT_TRUSTED_ISSUERS", "https://a.com")
        from mcp_chassis.security.fit import _is_trusted_issuer

        assert _is_trusted_issuer("https://other.com") is False


class TestJwksUrlForIssuer:
    def test_default_well_known_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FSS_FIT_ISSUER_JWKS_URL", raising=False)
        from mcp_chassis.security.fit import _jwks_url_for_issuer

        url = _jwks_url_for_issuer("https://issuer.example.com")
        assert url == "https://issuer.example.com/.well-known/fss-jwks.json"

    def test_env_override_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "FSS_FIT_ISSUER_JWKS_URL", "https://custom.example.com/jwks"
        )
        from mcp_chassis.security.fit import _jwks_url_for_issuer

        url = _jwks_url_for_issuer("https://issuer.example.com")
        assert url == "https://custom.example.com/jwks"
