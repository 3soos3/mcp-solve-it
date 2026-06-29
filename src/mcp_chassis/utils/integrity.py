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


def compute_cai(data: bytes, algorithm: str = "sha2-256") -> str:
    """Return CAI for arbitrary bytes using the named algorithm.

    Args:
        data: Raw bytes to hash.
        algorithm: One of 'sha2-256', 'sha2-384', 'sha2-512'.

    Returns:
        CAI string in the form 'algorithm:lowercase-hex'.
    """
    if algorithm not in _ALGO_MAP:
        raise ValueError(
            f"Unsupported algorithm '{algorithm}'. "
            f"Approved: {list(_ALGO_MAP)}"
        )
    digest = hashlib.new(_ALGO_MAP[algorithm], data).hexdigest()
    return f"{algorithm}:{digest}"


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
        logger.warning(
            "jcs not installed — using json.dumps fallback (not RFC 8785 compliant). "
            "Run: pip install jcs"
        )
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

def load_signing_key() -> Any | None:
    """Load the Ed25519 signing key from environment.

    Reads from FSS_SIGNING_KEY_PATH (PEM file) or FSS_SIGNING_KEY_B64
    (base64-encoded raw 32-byte key). Returns None if neither is set,
    making signing optional for deployments without HSM.

    Returns:
        Ed25519PrivateKey or None if not configured / cryptography missing.
    """
    import os

    if not _CRYPTO_AVAILABLE:
        logger.debug("cryptography not installed — signing unavailable")
        return None

    key_path = os.environ.get("FSS_SIGNING_KEY_PATH")
    if key_path:
        try:
            pem_bytes = Path(key_path).read_bytes()
            return load_pem_private_key(pem_bytes, password=None)
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

    return None


def sign_provenance(payload: dict[str, Any], key: Any) -> str:
    """Sign the FSS provenance payload with Ed25519.

    Signed fields (FSS-0005 §6.1):
        transaction_id, tool_name, tool_version, result_cai, timestamp_utc

    Args:
        payload: The full _provenance dict (only FSS-required fields signed).
        key: Ed25519PrivateKey from load_signing_key().

    Returns:
        Base64url-encoded signature string.
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for signing")

    signed_fields = {
        k: payload[k]
        for k in ("transaction_id", "tool_name", "tool_version",
                  "result_cai", "timestamp_utc")
        if k in payload
    }
    if _JCS_AVAILABLE:
        message = _jcs.canonicalize(signed_fields)
    else:
        message = json.dumps(
            signed_fields, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    signature_bytes = key.sign(message)
    return base64.urlsafe_b64encode(signature_bytes).rstrip(b"=").decode("ascii")


__all__ = [
    "compute_cai",
    "compute_json_cai",
    "compute_kb_version_id",
    "load_signing_key",
    "sign_provenance",
]
