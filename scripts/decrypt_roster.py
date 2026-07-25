#!/usr/bin/env python3
"""
Decrypts the AES-256-GCM envelope produced by encrypt_roster.py. Used by the
Action to reconstruct last run's plaintext roster (in the runner's ephemeral
filesystem only — never committed) so it can be diffed against the freshly
fetched one. If you need to inspect your own roster locally, this is also
the script for that.

Usage:
    python scripts/decrypt_roster.py <input.enc.json> <output.json>
Requires:
    ROSTER_PASSPHRASE environment variable.
"""
import base64
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


def derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def decrypt_file(input_path: str, output_path: str, passphrase: str) -> None:
    with open(input_path, "r") as f:
        envelope = json.load(f)

    salt = base64.b64decode(envelope["salt"])
    iv = base64.b64decode(envelope["iv"])
    ciphertext = base64.b64decode(envelope["ciphertext"])
    iterations = envelope.get("iterations", 210_000)

    key = derive_key(passphrase, salt, iterations)
    plaintext = AESGCM(key).decrypt(iv, ciphertext, None)  # raises if passphrase is wrong

    with open(output_path, "wb") as f:
        f.write(plaintext)

    print(f"Decrypted {input_path} -> {output_path}")


def main():
    if len(sys.argv) != 3:
        print("Usage: decrypt_roster.py <input.enc.json> <output.json>", file=sys.stderr)
        sys.exit(1)

    passphrase = os.environ.get("ROSTER_PASSPHRASE")
    if not passphrase:
        print("ERROR: ROSTER_PASSPHRASE environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    decrypt_file(sys.argv[1], sys.argv[2], passphrase)


if __name__ == "__main__":
    main()
