#!/usr/bin/env python3
"""Verify a FSS provenance record from a SOLVE-IT MCP tool response.

Implements the FSS-0005 §8 verification procedure (7 steps).
Useful for investigators verifying tool results in a legal context.

Usage:
    python scripts/verify_provenance.py <provenance_json_file>
    python scripts/verify_provenance.py --json '{"transaction_id": ...}'

The input must be either:
- A JSON file containing the _provenance dict extracted from a tool response
- Or a JSON file containing the full tool response (the script extracts _provenance)

Exit codes:
    0 - All applicable steps passed
    1 - One or more steps failed or errored
    2 - Usage error
"""

import argparse
import base64
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _cai_of_bytes(data: bytes, algorithm: str = "sha2-256") -> str:
    algo_map = {"sha2-256": "sha256", "sha2-384": "sha384", "sha2-512": "sha512"}
    if algorithm not in algo_map:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    digest = hashlib.new(algo_map[algorithm], data).hexdigest()
    return f"{algorithm}:{digest}"


def _canonical_bytes(obj: object) -> bytes:
    try:
        import jcs
        return jcs.canonicalize(obj)
    except ImportError:
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP (not applicable)"


def verify(provenance: dict, artifact_content: object = None,
           parameters: object = None, public_key_pem: str = "") -> int:
    """Run all 7 FSS-0005 §8 verification steps. Returns exit code."""
    failures = 0

    def report(step: str, result: str, detail: str = "") -> None:
        nonlocal failures
        icon = "✓" if result == PASS else ("✗" if result == FAIL else "·")
        print(f"  {icon} {step}: {result}")
        if detail:
            print(f"      {detail}")
        if result == FAIL:
            failures += 1

    print("FSS-0005 §8 Provenance Verification")
    print("=" * 50)

    # Step 1: Artifact content integrity
    print("\nStep 1: Artifact content integrity")
    artifact_id = provenance.get("artifact_id") or provenance.get("result_cai")
    if artifact_content is None:
        report("1", SKIP, "No artifact content provided; supply with --artifact")
    elif not artifact_id:
        report("1", FAIL, "No artifact_id in provenance record")
    else:
        try:
            algorithm = artifact_id.split(":")[0]
            computed = _cai_of_bytes(_canonical_bytes(artifact_content), algorithm)
            if computed == artifact_id:
                report("1", PASS, f"artifact_id matches: {artifact_id}")
            else:
                report("1", FAIL, f"Expected {artifact_id}, got {computed}")
        except Exception as exc:
            report("1", FAIL, str(exc))

    # Step 2: Input (parameters) integrity
    print("\nStep 2: Input parameters integrity")
    parameters_cai = provenance.get("parameters_cai")
    if parameters is None:
        report("2", SKIP, "No parameters provided; supply with --parameters")
    elif not parameters_cai:
        report("2", SKIP, "No parameters_cai in provenance record")
    else:
        try:
            algorithm = parameters_cai.split(":")[0]
            computed = _cai_of_bytes(_canonical_bytes(parameters), algorithm)
            if computed == parameters_cai:
                report("2", PASS, f"parameters_cai matches: {parameters_cai}")
            else:
                report("2", FAIL, f"Expected {parameters_cai}, got {computed}")
        except Exception as exc:
            report("2", FAIL, str(exc))

    # Step 3: KB version integrity
    print("\nStep 3: KB version integrity")
    kb_version_id = provenance.get("kb_version_id")
    kb_version = provenance.get("kb_version", "unknown")
    if not kb_version_id:
        report("3", SKIP, "No kb_version_id in provenance record")
    else:
        report("3", SKIP,
               f"Manual step: retrieve KB '{kb_version}' from Zenodo and recompute CAI.\n"
               f"      Expected: {kb_version_id}\n"
               f"      Run: python -c \"from mcp_chassis.utils.integrity import "
               f"compute_kb_version_id; print(compute_kb_version_id('<data_path>'))\"")

    # Step 4: Timestamp consistency
    print("\nStep 4: Timestamp consistency")
    ts = provenance.get("timestamp_utc")
    if not ts:
        report("4", FAIL, "No timestamp_utc in provenance record")
    else:
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                report("4", FAIL, "timestamp_utc missing timezone (must be UTC)")
            else:
                age_days = (datetime.now(UTC) - dt).days
                if age_days < 0:
                    report("4", FAIL, f"timestamp_utc is in the future: {ts}")
                elif age_days > 3650:
                    report("4", FAIL, f"timestamp_utc is more than 10 years old: {ts}")
                else:
                    report("4", PASS, f"timestamp_utc valid: {ts} ({age_days} days ago)")
        except (ValueError, TypeError) as exc:
            report("4", FAIL, f"Invalid timestamp format: {exc}")

    # Step 5: Server authenticity (signature verification)
    print("\nStep 5: Server authenticity (Ed25519 signature)")
    signature = provenance.get("signature")
    if not signature:
        report("5", SKIP, "No signature in provenance record (signing optional for Profile A)")
    elif not public_key_pem:
        report("5", SKIP, "No public key provided; supply with --public-key")
    else:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key

            pub_key = load_pem_public_key(public_key_pem.encode("utf-8"))
            signed_fields = {
                k: provenance[k]
                for k in ("transaction_id", "tool_name", "tool_version",
                          "result_cai", "timestamp_utc")
                if k in provenance
            }
            message = _canonical_bytes(signed_fields)
            sig_bytes = base64.urlsafe_b64decode(signature + "==")
            pub_key.verify(sig_bytes, message)  # type: ignore[attr-defined]
            report("5", PASS, "Ed25519 signature valid")
        except Exception as exc:
            report("5", FAIL, f"Signature verification failed: {exc}")

    # Step 6: Audit log chain integrity (Profile B/C only)
    print("\nStep 6: Audit log chain integrity")
    report("6", SKIP, "Applicable to Profile B/C only (external audit log required)")

    # Step 7: Reproducibility (optional)
    print("\nStep 7: Reproducibility")
    deterministic = provenance.get("deterministic", True)
    if not deterministic:
        report("7", SKIP, "Tool declared non-deterministic; reproducibility not applicable")
    else:
        report("7", SKIP,
               "Manual step: re-execute tool with same parameters against same KB version,\n"
               "      compute result CAI, compare to artifact_id in this record.")

    print()
    if failures == 0:
        print(f"Result: ALL APPLICABLE STEPS PASSED")
        return 0
    else:
        print(f"Result: {failures} STEP(S) FAILED")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify FSS-0005 provenance record"
    )
    parser.add_argument("input", nargs="?", help="JSON file with _provenance dict or full response")
    parser.add_argument("--json", help="Inline JSON string containing _provenance")
    parser.add_argument("--public-key", help="PEM public key file for signature verification")
    args = parser.parse_args()

    if not args.input and not args.json:
        parser.print_help()
        return 2

    try:
        if args.json:
            data = json.loads(args.json)
        else:
            data = json.loads(Path(args.input).read_text())
    except Exception as exc:
        print(f"ERROR reading input: {exc}", file=sys.stderr)
        return 2

    # Extract _provenance if given a full tool response
    provenance = data.get("_provenance", data)

    public_key_pem = ""
    if args.public_key:
        try:
            public_key_pem = Path(args.public_key).read_text()
        except Exception as exc:
            print(f"ERROR reading public key: {exc}", file=sys.stderr)
            return 2

    return verify(provenance, public_key_pem=public_key_pem)


if __name__ == "__main__":
    sys.exit(main())
