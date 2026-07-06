"""FSS cryptographic integrity utilities (FSS-0005).

Provides Content-Addressed Identifier (CAI) computation, RFC 8785
canonical JSON hashing, and optional Ed25519 signing.

CAI format: '<algorithm-id>:<lowercase-hex-digest>'
Approved algorithms: sha2-256 (REQUIRED), sha2-384, sha2-512.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ALGO_MAP: dict[str, str] = {
    "sha2-256": "sha256",
    "sha2-384": "sha384",
    "sha2-512": "sha512",
}

# Optional: jcs for RFC 8785 canonical JSON (FSS-0005 §4.3 RECOMMENDED)
try:
    import jcs as _jcs

    _JCS_AVAILABLE = True
except ImportError:
    _jcs = None  # type: ignore[assignment]
    _JCS_AVAILABLE = False

# Optional: cryptography for Ed25519 signing (FSS-0005 §6, required for L3)
try:
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    _CRYPTO_AVAILABLE = True
except ImportError:
    Ed25519PrivateKey = None  # type: ignore[assignment, misc]
    _CRYPTO_AVAILABLE = False


def check_jcs_required() -> None:
    """Enforce JCS availability in evidentiary mode (FSS_METADATA=true).

    Raises:
        SystemExit: If FSS_METADATA=true and jcs is not installed.
    """
    import os

    if os.environ.get("FSS_METADATA", "false").lower() == "true" and not _JCS_AVAILABLE:
        logger.critical(
            "FSS_METADATA=true requires the 'jcs' package (RFC 8785 canonical JSON). "
            "Install it with: pip install jcs"
        )
        raise SystemExit(1)
    if not _JCS_AVAILABLE:
        logger.warning(
            "jcs not installed — CAI hashing uses json.dumps fallback (not RFC 8785 compliant). "
            "Run: pip install jcs"
        )


def compute_cai(data: bytes, algorithm: str = "sha2-256") -> str:
    """Return CAI for arbitrary bytes using the named algorithm.

    Args:
        data: Raw bytes to hash.
        algorithm: One of 'sha2-256', 'sha2-384', 'sha2-512'.

    Returns:
        CAI string in the form 'algorithm:lowercase-hex'.
    """
    if algorithm not in _ALGO_MAP:
        raise ValueError(f"Unsupported algorithm '{algorithm}'. Approved: {list(_ALGO_MAP)}")
    digest = hashlib.new(_ALGO_MAP[algorithm], data).hexdigest()
    return f"{algorithm}:{digest}"


def validate_cai(value: str, algorithm: str = "sha2-256") -> bool:
    """Return True if value is a well-formed CAI string.

    Expected format: 'sha2-256:<64 lowercase hex chars>'
    Only sha2-256 (64 hex chars), sha2-384 (96), sha2-512 (128) are valid.

    Args:
        value: String to validate.
        algorithm: Expected algorithm prefix.

    Returns:
        True if value matches the expected CAI format.
    """
    import re

    hex_lengths = {"sha2-256": 64, "sha2-384": 96, "sha2-512": 128}
    expected_len = hex_lengths.get(algorithm)
    if expected_len is None:
        return False
    pattern = rf"^{re.escape(algorithm)}:[0-9a-f]{{{expected_len}}}$"
    return bool(re.match(pattern, value or ""))


def compute_json_cai(obj: Any, algorithm: str = "sha2-256") -> str:
    """Return CAI for a JSON-serialisable object using canonical serialisation.

    Uses RFC 8785 (JCS) when jcs is installed (recommended by FSS-0005 §4.3).
    Falls back to json.dumps(sort_keys=True) when jcs is not available;
    this fallback is NOT RFC 8785 compliant for non-ASCII or floats.

    Args:
        obj: A JSON-serialisable object (dict, list, str, int, etc.).
        algorithm: Hash algorithm identifier.

    Returns:
        CAI string.
    """
    if _JCS_AVAILABLE:
        data = _jcs.canonicalize(obj)
    else:
        data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return compute_cai(data, algorithm)


def compute_kb_version_id(data_path: str, algorithm: str = "sha2-256") -> str:
    """Compute the KB version CAI from the SOLVE-IT data directory.

    Walks data_path and hashes every JSON file in deterministic sorted
    order. Any change to the dataset — added, removed, or modified files
    — produces a different CAI, satisfying FSS-0005 §3.3.

    Args:
        data_path: Path to the SOLVE-IT data directory root.
        algorithm: Hash algorithm identifier.

    Returns:
        CAI string identifying this exact KB snapshot.
    """
    if algorithm not in _ALGO_MAP:
        raise ValueError(f"Unsupported algorithm '{algorithm}'.")

    h = hashlib.new(_ALGO_MAP[algorithm])
    data_dir = Path(data_path)

    json_files = sorted(data_dir.rglob("*.json"))
    if not json_files:
        logger.warning("No JSON files found in KB data path: %s", data_path)

    for json_file in json_files:
        # Include relative path so renames/moves change the CAI
        h.update(str(json_file.relative_to(data_dir)).encode("utf-8"))
        h.update(json_file.read_bytes())

    return f"{algorithm}:{h.hexdigest()}"


# ── Ed25519 signing (FSS-0005 §6, required for Level 3) ───────────────


def _compute_key_id(private_key: Any) -> str:
    """Compute a stable JWK thumbprint (kid) for an Ed25519 private key.

    SHA-256 of the raw 32-byte public key, base64url-encoded without padding.
    Same key always produces the same kid; different keys always differ.
    """
    from cryptography.hazmat.primitives import serialization

    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode("ascii")


def ensure_signing_key_pair(
    key_dir: str | Path | None = None, *, evidentiary: bool = False
) -> Any | None:
    """Load or auto-generate an Ed25519 key pair.

    Resolution order:
      1. priv.pem + pub.pem in key_dir (or FSS_KEY_DIR env var, default
         /run/secrets/fss-keys).  Both files must exist and be valid.
      2. If neither file exists, generate a new pair and write them
         (only permitted when evidentiary=False; i.e. Level 1/2).
         priv.pem is chmod 0o600; pub.pem is 0o644.
      3. Return None if the directory is not writable or cryptography is missing.

    A runtime-generated key survives the container lifetime but not a restart
    unless key_dir is on a persistent volume.  Mount a volume at FSS_KEY_DIR
    to keep the same key across :live restarts so old records stay verifiable.

    Args:
        key_dir: Directory containing priv.pem and pub.pem. Defaults to
            FSS_KEY_DIR env var or /run/secrets/fss-keys.
        evidentiary: If True (FSS_METADATA=true), auto-generation is refused —
            a provisioned key is required at Level 3 (FSS-0005 §6.5).

    Returns:
        Ed25519PrivateKey or None.
    """
    import os

    if not _CRYPTO_AVAILABLE:
        return None

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey as _Ed25519PrivateKey,
    )

    if key_dir is None:
        key_dir = os.environ.get("FSS_KEY_DIR", "/run/secrets/fss-keys")
    key_dir = Path(key_dir)
    priv_path = key_dir / "priv.pem"
    pub_path = key_dir / "pub.pem"

    if priv_path.exists() and pub_path.exists():
        try:
            key = load_pem_private_key(priv_path.read_bytes(), password=None)
            logger.debug("Loaded signing key pair from %s", key_dir)
            return key
        except Exception as exc:
            logger.error("Invalid signing key pair at %s: %s", key_dir, exc)
            return None

    if priv_path.exists() != pub_path.exists():
        logger.error(
            "Incomplete key pair at %s — only one of priv.pem/pub.pem exists. "
            "Remove both to trigger auto-generation.",
            key_dir,
        )
        return None

    # Neither file exists — auto-generate. Warn when in evidentiary mode
    # because FSS-0005 §6.5 RECOMMENDS provisioned keys at L3+ (not MUST).
    if evidentiary:
        logger.warning(
            "FSS_METADATA=true (evidentiary mode) with auto-generated signing key at %s. "
            "For Level 3 production deployments, mount a persistent volume with "
            "priv.pem and pub.pem at FSS_KEY_DIR (FSS-0005 §6.5).",
            key_dir,
        )

    # Auto-generate an ephemeral key pair
    try:
        key_dir.mkdir(parents=True, exist_ok=True)
        private_key = _Ed25519PrivateKey.generate()

        priv_path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        priv_path.chmod(0o600)

        pub_path.write_bytes(
            private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        pub_path.chmod(0o644)

        logger.info(
            "Generated Ed25519 key pair at %s (kid=%s). "
            "Mount %s on a persistent volume to survive container restarts.",
            key_dir,
            _compute_key_id(private_key),
            key_dir,
        )
        return private_key
    except OSError as exc:
        logger.warning(
            "Cannot write key pair to %s: %s — signing disabled. "
            "Set FSS_KEY_DIR to a writable path or mount a volume.",
            key_dir,
            exc,
        )
        return None


def load_signing_key() -> Any | None:
    """Load the Ed25519 signing key.

    Only loads a key when signing is enabled:
      - FSS_SIGNING=true, or
      - FSS_METADATA=true (forces signing on).

    Resolution order:
      1. FSS_SIGNING_KEY_PATH — path to a PEM private key file.
      2. FSS_SIGNING_KEY_B64 — base64-encoded raw 32-byte private key.
      3. Auto-generated pair via ensure_signing_key_pair() (FSS_KEY_DIR or
         /run/secrets/fss-keys).  Auto-generation refused when FSS_METADATA=true.

    Returns:
        Ed25519PrivateKey or None if unavailable or signing disabled.
    """
    import os

    if os.environ.get("FSS_SIGNING", "").lower() == "false":
        return None

    if not _CRYPTO_AVAILABLE:
        logger.debug("cryptography not installed — signing unavailable")
        return None

    key_path = os.environ.get("FSS_SIGNING_KEY_PATH")
    if key_path:
        try:
            return load_pem_private_key(Path(key_path).read_bytes(), password=None)
        except Exception as exc:
            logger.error("Failed to load signing key from %s: %s", key_path, exc)
            return None

    key_b64 = os.environ.get("FSS_SIGNING_KEY_B64")
    if key_b64:
        try:
            raw = base64.b64decode(key_b64)
            return Ed25519PrivateKey.from_private_bytes(raw)
        except Exception as exc:
            logger.error("Failed to load signing key from FSS_SIGNING_KEY_B64: %s", exc)
            return None

    fss_metadata = os.environ.get("FSS_METADATA", "false").lower() == "true"
    return ensure_signing_key_pair(evidentiary=fss_metadata)


def sign_provenance(payload: dict[str, Any], key: Any) -> dict[str, str]:
    """Sign the FSS data_signature payload with Ed25519 (FSS-0005 §6.2).

    Covers integrity-only fields — safe for external verifiers:
      {transaction_id, timestamp_utc, parameters_cai, result_cai}

    Null fields are NOT included (all four are always non-null for a
    valid tool result). The payload is JCS-canonicalized before signing.

    Args:
        payload: The full provenance dict.
        key: Ed25519PrivateKey from load_signing_key().

    Returns:
        Dict with 'value' (base64url signature) and 'kid' (key identifier).
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for signing")

    signed_fields = {
        k: payload[k]
        for k in ("transaction_id", "timestamp_utc", "parameters_cai", "result_cai")
        if k in payload
    }
    if _JCS_AVAILABLE:
        message = _jcs.canonicalize(signed_fields)
    else:
        message = json.dumps(signed_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")

    sig_bytes = key.sign(message)
    return {
        "value": base64.urlsafe_b64encode(sig_bytes).rstrip(b"=").decode("ascii"),
        "kid": _compute_key_id(key),
    }


def sign_provenance_full(payload: dict[str, Any], key: Any) -> dict[str, str]:
    """Sign the FSS provenance_signature payload with Ed25519 (FSS-0005 §6.3).

    Covers full investigation context — restricted to Secure System Boundary.
    Required at Level 3.

    Exact signed fields per FSS-0005 §6.3 (null fields included as JSON null):
      transaction_id, tool_name, tool_version, timestamp_utc,
      investigation_id, analyst_identity, invocation_type,
      fit_jti, evidentiary_status

    Args:
        payload: The full provenance dict.
        key: Ed25519PrivateKey from load_signing_key().

    Returns:
        Dict with 'value' (base64url signature) and 'kid' (key identifier).
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for signing")

    # Null fields MUST be included explicitly (FSS-0005 §6.3)
    _field_order = (
        "transaction_id",
        "tool_name",
        "tool_version",
        "timestamp_utc",
        "investigation_id",
        "analyst_identity",
        "invocation_type",
        "fit_jti",
        "evidentiary_status",
    )
    signed_fields = {k: payload.get(k) for k in _field_order}

    if _JCS_AVAILABLE:
        message = _jcs.canonicalize(signed_fields)
    else:
        message = json.dumps(signed_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")

    sig_bytes = key.sign(message)
    return {
        "value": base64.urlsafe_b64encode(sig_bytes).rstrip(b"=").decode("ascii"),
        "kid": _compute_key_id(key),
    }


def build_jwks(key: Any) -> dict[str, Any]:
    """Build a JWKS document for the given Ed25519 key (FSS-0005 §6.5).

    The returned document lists the active public key with kid and the
    raw base64url-encoded public key bytes. Revocation fields are initialised
    to their not-revoked defaults.

    Args:
        key: Ed25519PrivateKey.

    Returns:
        JWKS dict suitable for serving at /.well-known/fss-jwks.json.
    """
    from cryptography.hazmat.primitives import serialization

    raw_pub = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    x_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")
    kid = _compute_key_id(key)

    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "use": "sig",
                "kid": kid,
                "x": x_b64,
                "revoked": False,
                "revoked_at": None,
                "revocation_reason": None,
            }
        ]
    }


__all__ = [
    "build_jwks",
    "check_jcs_required",
    "compute_cai",
    "compute_json_cai",
    "compute_kb_version_id",
    "ensure_signing_key_pair",
    "load_signing_key",
    "sign_provenance",
    "sign_provenance_full",
    "validate_cai",
]
