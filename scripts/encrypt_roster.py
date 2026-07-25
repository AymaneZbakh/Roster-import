#!/usr/bin/env python3
"""
Encrypts a JSON file with AES-256-GCM, keyed by PBKDF2-HMAC-SHA256 over a
passphrase. Produces a small JSON envelope (salt/iv/ciphertext, all base64)
that is safe to commit to a PUBLIC repo — without the passphrase it's just
noise.

The parameters here (PBKDF2-SHA256, 210_000 iterations, AES-GCM, 16-byte
salt, 12-byte IV) are chosen to match exactly what the browser side derives
via the Web Crypto API in index.html. If you change one side, change both.

Usage:
    python scripts/encrypt_roster.py <input.json> <output.enc.json>
Requires:
    ROSTER_PASSPHRASE environment variable (the same passphrase used to
    unlock the app in the browser).
"""
import base64
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

PBKDF2_ITERATIONS = 210_000
SALT_LEN = 16
IV_LEN = 12
KEY_LEN = 32  # 256-bit AES key


def derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_file(input_path: str, output_path: str, passphrase: str) -> None:
    with open(input_path, "rb") as f:
        plaintext = f.read()

    # Fail loudly on empty/invalid JSON rather than silently encrypting junk.
    json.loads(plaintext)

    salt = os.urandom(SALT_LEN)
    iv = os.urandom(IV_LEN)
    key = derive_key(passphrase, salt)

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)  # tag is appended automatically

    envelope = {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }

    with open(output_path, "w") as f:
        json.dump(envelope, f)

    print(f"Encrypted {input_path} -> {output_path} ({len(ciphertext)} bytes ciphertext)")


def main():
    if len(sys.argv) != 3:
        print("Usage: encrypt_roster.py <input.json> <output.enc.json>", file=sys.stderr)
        sys.exit(1)

    passphrase = os.environ.get("ROSTER_PASSPHRASE")
    if not passphrase:
        print("ERROR: ROSTER_PASSPHRASE environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    if len(passphrase) < 8:
        print("ERROR: ROSTER_PASSPHRASE is too short — use 8+ characters, "
              "ideally a random passphrase, not a 6-digit PIN.", file=sys.stderr)
        sys.exit(1)

    encrypt_file(sys.argv[1], sys.argv[2], passphrase)


if __name__ == "__main__":
    main()
