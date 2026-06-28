#!/usr/bin/env python3
"""Generate an Ed25519 signing keypair for FSS provenance signatures.

Usage:
    python scripts/generate_signing_key.py [--out private_key.pem]

The private key is written to the specified file (chmod 600).
The public key is printed to stdout in PEM format for publication.

Keep the private key secret. Publish the public key so verifiers can
run scripts/verify_provenance.py against your provenance records.

Key rotation: replace keys every 2 years or on suspected compromise
(FSS-0005 §6.3). Retain old public keys for the lifetime of artifacts
signed with the corresponding private key.
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate FSS Ed25519 signing keypair")
    parser.add_argument(
        "--out",
        default="fss_signing_key.pem",
        help="Output path for private key PEM (default: fss_signing_key.pem)",
    )
    args = parser.parse_args()

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )
    except ImportError:
        print("ERROR: cryptography package not installed.", file=sys.stderr)
        print("Run: pip install cryptography", file=sys.stderr)
        return 1

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )

    out_path = Path(args.out)
    out_path.write_bytes(private_pem)
    os.chmod(out_path, 0o600)

    print(f"Private key written to: {out_path} (permissions: 600)")
    print()
    print("Public key (publish this for verifiers):")
    print(public_pem.decode("ascii"))
    print()
    print("Set FSS_SIGNING_KEY_PATH environment variable to the private key path,")
    print("or FSS_SIGNING_KEY_B64 to the base64-encoded raw key bytes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
