import hashlib
import tempfile
import unittest
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


class TestHashUtilities(unittest.TestCase):
    def test_sha256_file_matches_hashlib(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertEqual(sha256_file(path), expected)
        finally:
            path.unlink()

    def test_verify_db_hash_passes_on_match(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"content").hexdigest()
            verify_db_hash(path, expected)  # should not raise
        finally:
            path.unlink()

    def test_verify_db_hash_raises_on_mismatch(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                verify_db_hash(path, "0" * 64)
        finally:
            path.unlink()


class TestBackup(unittest.TestCase):
    def test_backup_creates_identical_copy_with_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candidate.db"
            db_path.write_bytes(b"fake db content")
            backup_path = backup_database(db_path)
            self.assertEqual(backup_path.name, "candidate.db.pre-phase3-backup")
            self.assertEqual(backup_path.read_bytes(), db_path.read_bytes())
