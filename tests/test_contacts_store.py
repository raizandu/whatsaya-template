"""Lock entre processos e escrita atômica de personal_contacts.json."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import contacts_store  # noqa: E402


class ContactsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="whatsaya-contacts-store-")
        self.path = Path(self.tmp.name) / "personal_contacts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_record_creates_file_merges_fields_and_removes_none(self):
        contacts_store.update_record(self.path, ["55@s.whatsapp.net"], {"name": "Ana", "blocked": True})
        contacts_store.update_record(self.path, ["55@s.whatsapp.net", "99@lid"], {"blocked": False, "name": None, "notes": "vip"})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["55@s.whatsapp.net"], {"blocked": False, "notes": "vip"})
        self.assertEqual(data["99@lid"], {"blocked": False, "notes": "vip"})
        self.assertFalse(list(self.path.parent.glob("*.tmp")), "tmp de escrita não pode sobrar")

    def test_lock_is_reentrant_in_process(self):
        with contacts_store.file_lock(self.path):
            with contacts_store.file_lock(self.path):
                contacts_store.write_contacts_atomic(self.path, {"a": {}})
        self.assertEqual(contacts_store.read_contacts(self.path), {"a": {}})
        self.assertIsNone(contacts_store._HELD["fd"])

    def test_lock_excludes_another_process(self):
        lock_file = contacts_store.lock_path_for(self.path)
        with contacts_store.file_lock(self.path):
            probe = subprocess.run(
                [sys.executable, "-c", (
                    "import fcntl, sys\n"
                    f"fd = open({str(lock_file)!r}, 'a+')\n"
                    "try:\n"
                    "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                    "    print('livre')\n"
                    "except BlockingIOError:\n"
                    "    print('travado')\n"
                )],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(probe.stdout.strip(), "travado")
        probe = subprocess.run(
            [sys.executable, "-c", (
                "import fcntl\n"
                f"fd = open({str(lock_file)!r}, 'a+')\n"
                "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "print('livre')\n"
            )],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(probe.stdout.strip(), "livre")

    def test_read_contacts_rejects_non_object(self):
        self.path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(ValueError):
            contacts_store.read_contacts(self.path)


if __name__ == "__main__":
    unittest.main()
