"""Verify a file's SHA-256 against an expected value.

Used by every materialization task in the 2026-08-04 consolidation plan
to confirm an artifact pulled from Drive matches its recorded hash before
it's treated as authoritative.
"""
import hashlib
import sys


def verify_checksum(path: str, expected_sha256: str) -> bool:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256.lower()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_checksum.py <path> <expected_sha256>", file=sys.stderr)
        return 2
    path, expected = sys.argv[1], sys.argv[2]
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual == expected.lower():
        print(f"OK {path}")
        return 0
    print(f"MISMATCH {path}: expected {expected}, got {actual}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
