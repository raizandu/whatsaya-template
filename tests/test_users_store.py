"""Usuários do painel: hash de senha, papéis e concorrência de escrita."""
from __future__ import annotations

import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import users_store  # noqa: E402


class UsersStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="whatsaya-users-store-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "panel_users.json"

    def test_create_and_list_never_expose_hash(self):
        created = users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        self.assertNotIn("pbkdf2", created)
        self.assertEqual(created["username"], "ana.silva")
        self.assertEqual(created["role"], "atendente")
        self.assertTrue(created["active"])

        listed = users_store.list_users(self.path)
        self.assertEqual(len(listed), 1)
        self.assertNotIn("pbkdf2", listed[0])
        self.assertNotIn("salt", listed[0])
        self.assertNotIn("hash", listed[0])

        fetched = users_store.get_user(self.path, "ana.silva")
        self.assertEqual(fetched["name"], "Ana Silva")
        self.assertNotIn("pbkdf2", fetched)

    def test_permissoes_por_usuario_e_admin_implica_todas(self):
        ana = users_store.create_user(
            self.path, username="ana", name="Ana", password="SenhaForte#2026", role="atendente",
        )
        self.assertEqual(ana["permissions"], [])
        self.assertFalse(users_store.has_permission(ana, "atendimentos.ver_todos"))
        ana = users_store.set_permissions(self.path, "ana", ["atendimentos.ver_todos", "atendimentos.ver_todos"])
        self.assertEqual(ana["permissions"], ["atendimentos.ver_todos"])
        self.assertTrue(users_store.has_permission(users_store.get_user(self.path, "ana"), "atendimentos.ver_todos"))
        with self.assertRaises(ValueError):
            users_store.set_permissions(self.path, "ana", ["root"])
        with self.assertRaises(KeyError):
            users_store.set_permissions(self.path, "ninguem", [])
        bruno = users_store.create_user(
            self.path, username="bruno", name="Bruno", password="SenhaForte#2026", role="admin",
        )
        self.assertEqual(bruno["permissions"], list(users_store.PERMISSIONS))
        self.assertTrue(users_store.has_permission({"role": "admin", "permissions": []}, "atendimentos.ver_todos"))
        self.assertFalse(users_store.has_permission(None, "atendimentos.ver_todos"))
        criado = users_store.create_user(
            self.path, username="carla", name="Carla", password="SenhaForte#2026", role="atendente",
            permissions=["atendimentos.ver_todos"],
        )
        self.assertEqual(criado["permissions"], ["atendimentos.ver_todos"])

    def test_list_and_get_on_missing_file(self):
        self.assertEqual(users_store.list_users(self.path), [])
        self.assertIsNone(users_store.get_user(self.path, "ninguem"))

    def test_verify_login_ok(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        user = users_store.verify_login(self.path, "ana.silva", "SenhaForte#2026")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "ana.silva")
        self.assertNotIn("pbkdf2", user)

    def test_verify_login_wrong_password(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        self.assertIsNone(users_store.verify_login(self.path, "ana.silva", "errada-errada"))

    def test_verify_login_inactive_user_fails(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        users_store.set_active(self.path, "ana.silva", False)
        self.assertIsNone(users_store.verify_login(self.path, "ana.silva", "SenhaForte#2026"))

    def test_verify_login_missing_file_returns_none_without_creating(self):
        self.assertIsNone(users_store.verify_login(self.path, "ana.silva", "SenhaForte#2026"))
        self.assertFalse(self.path.exists())

    def test_create_user_rejects_short_password(self):
        with self.assertRaises(ValueError):
            users_store.create_user(
                self.path, username="ana.silva", name="Ana Silva", password="curta12", role="atendente",
            )

    def test_create_user_rejects_weak_password(self):
        with self.assertRaises(ValueError):
            users_store.create_user(
                self.path, username="ana.silva", name="Ana Silva", password="admin123", role="atendente",
            )

    def test_create_user_rejects_invalid_username(self):
        for bad in ("Ana Silva", "ab", "a" * 33, "ana@silva"):
            with self.assertRaises(ValueError):
                users_store.create_user(
                    self.path, username=bad, name="Ana Silva", password="SenhaForte#2026", role="atendente",
                )

    def test_create_user_rejects_invalid_role(self):
        with self.assertRaises(ValueError):
            users_store.create_user(
                self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="gerente",
            )

    def test_create_user_rejects_duplicate_username(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        with self.assertRaises(ValueError):
            users_store.create_user(
                self.path, username="ana.silva", name="Outra Ana", password="OutraSenha#2026", role="atendente",
            )

    def test_file_created_with_0600(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_set_password_invalidates_old_password(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        users_store.set_password(self.path, "ana.silva", "SenhaNova#2026")
        self.assertIsNone(users_store.verify_login(self.path, "ana.silva", "SenhaForte#2026"))
        self.assertIsNotNone(users_store.verify_login(self.path, "ana.silva", "SenhaNova#2026"))

    def test_set_password_unknown_user_raises(self):
        with self.assertRaises(ValueError):
            users_store.set_password(self.path, "ninguem", "SenhaForte#2026")

    def test_set_active_toggles(self):
        users_store.create_user(
            self.path, username="ana.silva", name="Ana Silva", password="SenhaForte#2026", role="atendente",
        )
        updated = users_store.set_active(self.path, "ana.silva", False)
        self.assertFalse(updated["active"])
        updated = users_store.set_active(self.path, "ana.silva", True)
        self.assertTrue(updated["active"])

    def test_concurrent_create_does_not_lose_a_user(self):
        errors = []

        def _create(idx):
            try:
                users_store.create_user(
                    self.path, username=f"user{idx}", name=f"Usuário {idx}",
                    password="SenhaForte#2026", role="atendente",
                )
            except Exception as exc:  # pragma: no cover - só para diagnóstico da falha
                errors.append(exc)

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertEqual(errors, [])
        listed = {u["username"] for u in users_store.list_users(self.path)}
        self.assertEqual(listed, {f"user{i}" for i in range(8)})


if __name__ == "__main__":
    unittest.main()
