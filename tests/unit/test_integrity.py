"""Unit tests for mcp_chassis.utils.integrity — CAI, signing (FSS-0005)."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from mcp_chassis.utils.integrity import (
    compute_cai,
    compute_json_cai,
    compute_kb_version_id,
    load_signing_key,
)


class TestComputeCai:
    """Tests for compute_cai — Content-Addressed Identifier."""

    def test_returns_sha2_256_format(self) -> None:
        cai = compute_cai(b"hello")
        assert cai.startswith("sha2-256:")
        hex_part = cai[len("sha2-256:") :]
        assert len(hex_part) == 64  # SHA-256 = 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_known_sha256_value(self) -> None:
        # SHA-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        cai = compute_cai(b"")
        assert cai == "sha2-256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_sha2_384_algorithm(self) -> None:
        cai = compute_cai(b"hello", algorithm="sha2-384")
        assert cai.startswith("sha2-384:")
        hex_part = cai[len("sha2-384:") :]
        assert len(hex_part) == 96  # SHA-384 = 48 bytes

    def test_sha2_512_algorithm(self) -> None:
        cai = compute_cai(b"hello", algorithm="sha2-512")
        assert cai.startswith("sha2-512:")
        hex_part = cai[len("sha2-512:") :]
        assert len(hex_part) == 128  # SHA-512 = 64 bytes

    def test_unknown_algorithm_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported algorithm"):
            compute_cai(b"hello", algorithm="md5")

    def test_different_inputs_different_cai(self) -> None:
        assert compute_cai(b"a") != compute_cai(b"b")

    def test_same_input_same_cai(self) -> None:
        assert compute_cai(b"test") == compute_cai(b"test")


class TestComputeJsonCai:
    """Tests for compute_json_cai — CAI of JSON-serialisable objects."""

    def test_returns_sha2_256_format(self) -> None:
        cai = compute_json_cai({"key": "value"})
        assert cai.startswith("sha2-256:")

    def test_same_dict_same_cai(self) -> None:
        obj = {"b": 2, "a": 1}
        assert compute_json_cai(obj) == compute_json_cai(obj)

    def test_different_dicts_different_cai(self) -> None:
        assert compute_json_cai({"a": 1}) != compute_json_cai({"a": 2})

    def test_list_input(self) -> None:
        cai = compute_json_cai([1, 2, 3])
        assert cai.startswith("sha2-256:")

    def test_string_input(self) -> None:
        cai = compute_json_cai("hello")
        assert cai.startswith("sha2-256:")

    def test_none_input(self) -> None:
        cai = compute_json_cai(None)
        assert cai.startswith("sha2-256:")


class TestComputeKbVersionId:
    """Tests for compute_kb_version_id — CAI of KB data directory."""

    def test_returns_sha2_256_format(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "technique.json").write_text('{"id": "DFT-1001"}')
        cai = compute_kb_version_id(str(tmp_path))
        assert cai.startswith("sha2-256:")

    def test_empty_directory_returns_cai(self, tmp_path: pathlib.Path) -> None:
        cai = compute_kb_version_id(str(tmp_path))
        assert cai.startswith("sha2-256:")

    def test_different_content_different_cai(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}')
        cai1 = compute_kb_version_id(str(tmp_path))
        f.write_text('{"a": 2}')
        cai2 = compute_kb_version_id(str(tmp_path))
        assert cai1 != cai2

    def test_adding_file_changes_cai(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "a.json").write_text('{"x": 1}')
        cai1 = compute_kb_version_id(str(tmp_path))
        (tmp_path / "b.json").write_text('{"y": 2}')
        cai2 = compute_kb_version_id(str(tmp_path))
        assert cai1 != cai2

    def test_ignores_non_json_files(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "readme.txt").write_text("ignored")
        cai1 = compute_kb_version_id(str(tmp_path))
        (tmp_path / "extra.txt").write_text("also ignored")
        cai2 = compute_kb_version_id(str(tmp_path))
        assert cai1 == cai2

    def test_deterministic_across_calls(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "data.json").write_text('{"id": "DFT-1001"}')
        assert compute_kb_version_id(str(tmp_path)) == compute_kb_version_id(str(tmp_path))


class TestEnsureSigningKeyPair:
    """Tests for ensure_signing_key_pair — auto-generation and loading."""

    def test_generates_key_pair_when_absent(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("cryptography")
        from mcp_chassis.utils.integrity import ensure_signing_key_pair

        key = ensure_signing_key_pair(tmp_path)
        assert key is not None
        assert (tmp_path / "priv.pem").exists()
        assert (tmp_path / "pub.pem").exists()

    def test_priv_pem_has_restricted_permissions(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("cryptography")
        from mcp_chassis.utils.integrity import ensure_signing_key_pair

        ensure_signing_key_pair(tmp_path)
        mode = (tmp_path / "priv.pem").stat().st_mode & 0o777
        assert mode == 0o600

    def test_loads_existing_pair(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("cryptography")
        from mcp_chassis.utils.integrity import ensure_signing_key_pair

        key1 = ensure_signing_key_pair(tmp_path)
        key2 = ensure_signing_key_pair(tmp_path)
        assert key1 is not None and key2 is not None
        # Same key material — public keys match
        from cryptography.hazmat.primitives import serialization

        pub1 = key1.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        pub2 = key2.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        assert pub1 == pub2

    def test_kid_is_stable_for_same_key(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("cryptography")
        from mcp_chassis.utils.integrity import _compute_key_id, ensure_signing_key_pair

        key1 = ensure_signing_key_pair(tmp_path)
        key2 = ensure_signing_key_pair(tmp_path)
        assert _compute_key_id(key1) == _compute_key_id(key2)

    def test_returns_none_for_incomplete_pair(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("cryptography")
        from mcp_chassis.utils.integrity import ensure_signing_key_pair

        (tmp_path / "priv.pem").write_bytes(b"stub")
        assert ensure_signing_key_pair(tmp_path) is None

    def test_returns_none_for_unwritable_dir(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("cryptography")
        from mcp_chassis.utils.integrity import ensure_signing_key_pair

        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir(mode=0o555)
        assert ensure_signing_key_pair(ro_dir) is None


class TestLoadSigningKey:
    """Tests for load_signing_key — priority: env vars > auto-generated pair."""

    def test_no_env_vars_returns_none_when_signing_disabled(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FSS_SIGNING_KEY_PATH", raising=False)
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        monkeypatch.setenv("FSS_SIGNING", "false")
        monkeypatch.setenv("FSS_METADATA", "false")
        monkeypatch.setenv("FSS_KEY_DIR", str(tmp_path))
        assert load_signing_key() is None

    def test_falls_back_to_auto_generate_when_fss_signing_enabled(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("cryptography")
        monkeypatch.delenv("FSS_SIGNING_KEY_PATH", raising=False)
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        monkeypatch.setenv("FSS_SIGNING", "true")
        monkeypatch.setenv("FSS_METADATA", "false")
        monkeypatch.setenv("FSS_KEY_DIR", str(tmp_path))
        key = load_signing_key()
        assert key is not None
        assert (tmp_path / "priv.pem").exists()

    def test_no_env_vars_no_writable_dir_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FSS_SIGNING_KEY_PATH", raising=False)
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        monkeypatch.setenv("FSS_SIGNING", "true")
        monkeypatch.setenv("FSS_METADATA", "false")
        monkeypatch.setenv("FSS_KEY_DIR", "/nonexistent/readonly/path")
        assert load_signing_key() is None

    def test_missing_key_file_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setenv("FSS_SIGNING_KEY_PATH", str(tmp_path / "nonexistent.pem"))
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        assert load_signing_key() is None

    def test_invalid_b64_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FSS_SIGNING_KEY_PATH", raising=False)
        monkeypatch.setenv("FSS_SIGNING_KEY_B64", "not-valid-base64!!!")
        assert load_signing_key() is None


class TestEd25519Signing:
    """Tests for sign_provenance — Ed25519 signature round-trip."""

    @pytest.fixture()
    def signing_key(self) -> object:
        pytest.importorskip("cryptography", reason="cryptography not installed")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        return Ed25519PrivateKey.generate()

    def test_sign_provenance_returns_dict_with_value_and_kid(self, signing_key: object) -> None:
        from mcp_chassis.utils.integrity import sign_provenance

        payload = {
            "transaction_id": "test-uuid",
            "tool_name": "solveit_search",
            "tool_version": "1.0.0",
            "result_cai": "sha2-256:abc123",
            "timestamp_utc": "2026-06-29T10:00:00.000Z",
        }
        sig = sign_provenance(payload, signing_key)
        assert isinstance(sig, dict)
        assert "value" in sig and "kid" in sig
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in valid_chars for c in sig["value"])
        assert all(c in valid_chars for c in sig["kid"])

    def test_sign_verify_round_trip(self, signing_key: object) -> None:
        import base64

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from mcp_chassis.utils.integrity import sign_provenance

        assert isinstance(signing_key, Ed25519PrivateKey)
        public_key = signing_key.public_key()

        # data_signature covers exactly 4 fields per FSS-0005 §6.2
        payload = {
            "transaction_id": "abc-123",
            "timestamp_utc": "2026-06-29T12:00:00.000Z",
            "parameters_cai": "sha2-256:params",
            "result_cai": "sha2-256:deadbeef",
            # extra fields that must NOT appear in signed payload
            "tool_name": "solveit_get_technique",
            "tool_version": "1.0.0",
            "kb_version_id": "sha2-256:deadbeef",
        }
        sig = sign_provenance(payload, signing_key)
        sig_bytes = base64.urlsafe_b64decode(sig["value"] + "==")

        # Reconstruct exactly the 4 signed fields (FSS-0005 §6.2)
        signed_fields = {
            k: payload[k]
            for k in ("transaction_id", "timestamp_utc", "parameters_cai", "result_cai")
            if k in payload
        }
        try:
            import jcs

            message = jcs.canonicalize(signed_fields)
        except ImportError:
            message = json.dumps(signed_fields, sort_keys=True, separators=(",", ":")).encode()

        public_key.verify(sig_bytes, message)

    def test_same_kid_for_same_key(self, signing_key: object) -> None:
        from mcp_chassis.utils.integrity import sign_provenance

        payload = {
            "transaction_id": "t1",
            "tool_name": "tool",
            "tool_version": "1.0.0",
            "result_cai": "sha2-256:abc",
            "timestamp_utc": "2026-06-29T00:00:00.000Z",
        }
        sig1 = sign_provenance(payload, signing_key)
        sig2 = sign_provenance({**payload, "transaction_id": "t2"}, signing_key)
        assert sig1["kid"] == sig2["kid"]

    def test_different_payload_different_signature(self, signing_key: object) -> None:
        from mcp_chassis.utils.integrity import sign_provenance

        base = {
            "transaction_id": "t1",
            "tool_name": "tool",
            "tool_version": "1.0.0",
            "result_cai": "sha2-256:abc",
            "timestamp_utc": "2026-06-29T00:00:00.000Z",
        }
        modified = {**base, "result_cai": "sha2-256:def"}
        assert (
            sign_provenance(base, signing_key)["value"]
            != sign_provenance(modified, signing_key)["value"]
        )

    def test_load_and_use_generated_key(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("cryptography")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )

        from mcp_chassis.utils.integrity import load_signing_key, sign_provenance

        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        key_file = tmp_path / "key.pem"
        key_file.write_bytes(pem)

        monkeypatch.setenv("FSS_SIGNING_KEY_PATH", str(key_file))
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        monkeypatch.setenv("FSS_SIGNING", "true")
        monkeypatch.setenv("FSS_METADATA", "false")

        loaded_key = load_signing_key()
        assert loaded_key is not None

        payload = {
            "transaction_id": "t",
            "tool_name": "t",
            "tool_version": "1.0.0",
            "result_cai": "sha2-256:abc",
            "timestamp_utc": "2026-06-29T00:00:00.000Z",
        }
        sig = sign_provenance(payload, loaded_key)
        assert isinstance(sig, dict)
        assert "value" in sig and "kid" in sig


class TestVectorSigning:
    """FSS-0005 §6.2, §6.3 — known-answer Ed25519 signature verification tests.

    Run with:
        FSS_VECTORS_PATH=../fss-conformance-suite/internal/vectors/testdata \
            pytest tests/unit/test_integrity.py::TestVectorSigning -v
    """

    @pytest.fixture(scope="class")
    def vectors(self) -> list[dict]:
        path = os.environ.get("FSS_VECTORS_PATH", "")
        if not path:
            pytest.skip("FSS_VECTORS_PATH not set; skipping cross-language vector tests")
        data = json.loads((pathlib.Path(path) / "signing_vectors.json").read_text())
        return data["vectors"]

    def test_all_signing_vectors(self, vectors: list[dict]) -> None:
        pytest.importorskip("cryptography")
        import base64

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            import jcs as _jcs
            def canonicalize(obj: object) -> bytes:
                return _jcs.canonicalize(obj)
        except ImportError:
            def canonicalize(obj: object) -> bytes:
                return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

        for v in vectors:
            sig_b64 = v.get("signature_base64url")
            payload = v.get("payload")
            if not sig_b64 or payload is None:
                continue  # JWKS structure or chain hash vectors

            jwk = v.get("test_public_key_jwk")
            if not jwk:
                jwks = v.get("jwks")
                if not jwks or not jwks.get("keys"):
                    continue  # no public key in vector
                jwk = jwks["keys"][0]

            pub_bytes = base64.urlsafe_b64decode(jwk["x"] + "==")
            pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)

            message = canonicalize(payload)
            sig_bytes = base64.urlsafe_b64decode(sig_b64 + "==")
            expected = v.get("expected_result", "PASS")

            if expected == "PASS":
                try:
                    pub_key.verify(sig_bytes, message)
                except InvalidSignature as exc:
                    raise AssertionError(
                        f"Vector {v['id']} ({v['description']}): "
                        "expected PASS but verification failed"
                    ) from exc
            else:
                try:
                    pub_key.verify(sig_bytes, message)
                    raise AssertionError(
                        f"Vector {v['id']} ({v['description']}): "
                        "expected FAIL but verification succeeded"
                    )
                except (InvalidSignature, Exception):
                    pass


class TestVectorCAI:
    """FSS-0005 §3, §4.3 — known-answer tests against shared vector file.

    Run with:
        FSS_VECTORS_PATH=../fss-conformance-suite/internal/vectors/testdata \
            pytest tests/unit/test_integrity.py::TestVectorCAI -v
    """

    @pytest.fixture(scope="class")
    def vectors(self) -> list[dict]:
        path = os.environ.get("FSS_VECTORS_PATH", "")
        if not path:
            pytest.skip("FSS_VECTORS_PATH not set; skipping cross-language vector tests")
        data = json.loads((pathlib.Path(path) / "cai_vectors.json").read_text())
        return data["vectors"]

    def test_all_cai_vectors(self, vectors: list[dict]) -> None:
        for v in vectors:
            got = compute_json_cai(v["input"])
            assert got == v["cai"], (
                f"Vector {v['id']} ({v['description']}): "
                f"got {got!r}, want {v['cai']!r}"
            )
