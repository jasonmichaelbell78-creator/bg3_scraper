import hashlib
import tempfile
import unittest
from pathlib import Path

from app.catalog_pipeline.verify_checksum import verify_checksum


class TestVerifyChecksum(unittest.TestCase):
    def test_matching_hash_returns_true(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertTrue(verify_checksum(str(path), expected))
        finally:
            path.unlink()

    def test_mismatched_hash_returns_false(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            self.assertFalse(verify_checksum(str(path), "0" * 64))
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
