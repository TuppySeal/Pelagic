"""Persistent memory access-gate and data-preservation regression tests."""
from __future__ import annotations

import concurrent.futures
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlasbrowser.memory import HEADER, MemoryFile


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atlas_memory_test_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "Atlas Memory.md"

    def test_constructor_does_not_access_filesystem(self):
        with patch.object(Path, "open", side_effect=AssertionError("automatic access")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("automatic create")), \
                patch.object(Path, "exists", side_effect=AssertionError("automatic inspect")):
            memory = MemoryFile(self.path)
            self.assertEqual(memory.path, self.path)
        self.assertFalse(self.path.parent.exists())

    def test_unauthorized_access_never_opens_or_creates_file(self):
        memory = MemoryFile(self.path)
        with patch.object(Path, "open", side_effect=AssertionError("unauthorized access")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("unauthorized create")):
            for flag in (False, None, 1, "yes"):
                with self.subTest(flag=flag):
                    with self.assertRaises(PermissionError):
                        memory.read(authorized=flag)
                    with self.assertRaises(PermissionError):
                        memory.append("entry", authorized=flag)
                    with self.assertRaises(PermissionError):
                        memory.initialize(authorized=flag)
        self.assertFalse(self.path.parent.exists())

    def test_permission_is_required_again_after_authorized_use(self):
        memory = MemoryFile(self.path)
        memory.append("Explicitly saved", authorized=True)
        with self.assertRaises(PermissionError):
            memory.read()
        with self.assertRaises(PermissionError):
            memory.append("Implicit save")

    def test_authorized_missing_read_does_not_create_file(self):
        self.assertEqual(MemoryFile(self.path).read(authorized=True), "")
        self.assertFalse(self.path.parent.exists())

    def test_initialize_does_not_read_or_replace_existing_document(self):
        memory = MemoryFile(self.path)
        self.assertTrue(memory.initialize(authorized=True))
        self.path.write_bytes(b"An existing document\r\n")
        with patch.object(MemoryFile, "_existing_text", side_effect=AssertionError("initialize read")):
            self.assertFalse(memory.initialize(authorized=True))
        self.assertEqual(self.path.read_bytes(), b"An existing document\r\n")

    def test_append_creates_utf8_and_persists_for_new_instance(self):
        MemoryFile(self.path).append("Remember café and 日本語.", authorized=True)
        content = MemoryFile(self.path).read(authorized=True)
        self.assertTrue(content.startswith(HEADER))
        self.assertIn("Remember café and 日本語.", content)

    def test_append_preserves_prior_content_exactly(self):
        self.path.parent.mkdir()
        prior = b"\xef\xbb\xbf# Existing\r\n\r\nKeep these spaces.  \r\n"
        self.path.write_bytes(prior)
        MemoryFile(self.path).append("New entry", authorized=True)
        self.assertTrue(self.path.read_bytes().startswith(prior))
        self.assertIn("New entry", self.path.read_text(encoding="utf-8"))

    def test_invalid_utf8_refuses_to_overwrite(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"existing\xffcontent")
        memory = MemoryFile(self.path)
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            memory.read(authorized=True)
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            memory.append("New entry", authorized=True)
        self.assertEqual(self.path.read_bytes(), b"existing\xffcontent")

    def test_size_limit_preserves_existing_content(self):
        memory = MemoryFile(self.path, max_chars=120)
        memory.append("Short entry", authorized=True)
        prior = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "limit"):
            memory.append("x" * 100, authorized=True)
        self.assertEqual(self.path.read_bytes(), prior)
        self.path.write_bytes(b"x" * 121)
        with self.assertRaisesRegex(ValueError, "limit"):
            memory.read(authorized=True)

    def test_oversized_entry_does_not_create_file(self):
        with self.assertRaisesRegex(ValueError, "limit"):
            MemoryFile(self.path, max_chars=120).append("x" * 121, authorized=True)
        self.assertFalse(self.path.parent.exists())

    def test_atomic_replace_failure_preserves_document_and_cleans_temp(self):
        memory = MemoryFile(self.path)
        memory.append("First entry", authorized=True)
        prior = self.path.read_bytes()
        with patch("atlasbrowser.memory.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                memory.append("Second entry", authorized=True)
        self.assertEqual(self.path.read_bytes(), prior)
        self.assertEqual(list(self.path.parent.glob(".atlas_memory_*.tmp")), [])

    def test_concurrent_instances_preserve_all_entries(self):
        def save(index):
            MemoryFile(self.path).append(f"Entry-{index:02d}", authorized=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(save, range(20)))
        content = MemoryFile(self.path).read(authorized=True)
        for index in range(20):
            self.assertEqual(content.count(f"Entry-{index:02d}"), 1)
        self.assertEqual(content.count("# Pelagic Memory"), 1)


if __name__ == "__main__":
    unittest.main()
