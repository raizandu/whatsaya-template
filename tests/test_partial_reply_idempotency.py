"""Regressões para entrega parcial de respostas comuns.

O bridge confirma cada bolha individualmente. Estes testes mantêm o contrato de
idempotência no ponto em que ele é observável pelo manager: uma falha posterior
deve carregar somente o texto ainda não confirmado, persistir esse cursor e
retomá-lo sem repetir a primeira bolha. A modalidade híbrida (texto/voz) é
deliberadamente mais conservadora: quando houver efeito de voz, não se deve
reconstituir uma sequência parcial sem saber quais efeitos foram confirmados.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("WHATSAPP_HUMAN_TEST_MODE", "1")

MODULE_PATH = REPO_ROOT / "whatsapp_manager.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_manager", MODULE_PATH)
assert SPEC and SPEC.loader
wm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wm
SPEC.loader.exec_module(wm)


CHAT = "556281405459@s.whatsapp.net"
TURN = "turn-partial-idempotency"
TOKEN = ("inbound-partial-1", 100.0)
INBOUND = {
    "message_id": TOKEN[0],
    "at": TOKEN[1],
    "text": "mensagem original do lead",
}


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _ResumeEngine:
    def __init__(self):
        self.cancelled = []
        self.failed = []
        self.uncertain = []
        self.sent = []

    def revalidate_claim(self, job_id, lease_token, *, now):
        return True

    def cancel_claimed(self, job_id, lease_token, reason):
        self.cancelled.append((job_id, reason))

    def mark_failed(self, job_id, error, lease_token):
        self.failed.append((job_id, error))

    def mark_uncertain(self, job_id, error, lease_token):
        self.uncertain.append((job_id, error))

    def mark_sent(self, job_id, message_id, lease_token):
        self.sent.append((job_id, message_id))


class PartialReplyIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="whatsaya-partial-")
        self.partial_path = Path(self._tmp.name) / "partial_reply_state.json"
        self.path_patch = mock.patch.object(wm, "_PARTIAL_REPLY_PATH", self.partial_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(wm._turn_inflight.discard, TURN)
        self.addCleanup(wm._turn_sent.discard, TURN)
        self.addCleanup(wm._turn_key.pop, CHAT, None)
        self.addCleanup(wm._turn_inbound.pop, TURN, None)
        wm._clear_partial_reply(TURN)

    def test_human_send_exposes_only_unconfirmed_bubbles(self):
        calls = []

        def fake_urlopen(req, timeout=10):
            payload = json.loads(req.data.decode("utf-8"))
            calls.append(payload)
            if len(calls) == 1:
                return _FakeResponse({"messageId": "out-1"})
            raise RuntimeError("bridge caiu depois da primeira bolha")

        with mock.patch.object(wm.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(wm.PartialMessageDelivery) as raised:
                wm._human_send(
                    CHAT,
                    "Primeira bolha.\n\nSegunda bolha.\n\nTerceira bolha.",
                    automation=False,
                )

        err = raised.exception
        self.assertEqual(err.message_id, "out-1")
        self.assertEqual(err.sent_parts, 1)
        self.assertEqual(err.remaining_text, "Segunda bolha.\n\nTerceira bolha.")
        self.assertEqual([payload["message"] for payload in calls], ["Primeira bolha.", "Segunda bolha."])

    def test_partial_cursor_is_durable_and_cleared_after_confirmed_retry(self):
        self.assertTrue(
            wm._save_partial_reply(
                TURN,
                CHAT,
                "Segunda bolha.\n\nTerceira bolha.",
                INBOUND,
            )
        )
        # Ler novamente do arquivo, e não de um cache em memória, é parte do
        # contrato: um restart deve conservar apenas o restante não confirmado.
        self.assertEqual(
            wm._partial_reply_for_turn(TURN, CHAT)["remaining_text"],
            "Segunda bolha.\n\nTerceira bolha.",
        )
        persisted = json.loads(self.partial_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted[TURN]["inbound_message_id"], TOKEN[0])

        wm._turn_key[CHAT] = TURN
        wm._turn_inflight.add(TURN)
        wm._turn_inbound[TURN] = dict(INBOUND)
        delivered = []
        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), mock.patch.object(
            wm, "_ritmo_wait_before_send", return_value=True
        ), mock.patch.object(
            wm, "_ritmo_send_window_ok", return_value=True
        ), mock.patch.object(
            wm, "_deliver_contact_reply", side_effect=lambda _cid, text, **_kw: delivered.append(text) or "out-2"
        ), mock.patch.object(
            wm, "_persist_turn_sent_to_disk"
        ), mock.patch.object(
            wm, "_maybe_start_playbook_completion"
        ), mock.patch.object(
            wm, "_mark_bot_spoke"
        ):
            self.assertTrue(
                wm._schedule_contact_reply(
                    CHAT,
                    "Primeira bolha.\n\nSegunda bolha.\n\nTerceira bolha.",
                    TURN,
                    consumed_inbound_token=TOKEN,
                    inbound_snapshot=INBOUND,
                )
            )

        self.assertEqual(delivered, ["Segunda bolha.\n\nTerceira bolha."])
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})
        self.assertIn(TURN, wm._turn_sent)

    def test_replay_uses_original_inbound_when_db_has_no_pending_message(self):
        wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND)
        engine = _ResumeEngine()
        job = {
            "id": "resume-1",
            "chat_id": CHAT,
            "lease_token": "lease-1",
            "basis_outbound_id": f"resume:partial_delivery:{TURN}",
        }
        sent_payloads = []

        def fake_urlopen(req, timeout=10):
            sent_payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeResponse({"messageId": "requeue-1"})

        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=False), mock.patch.object(
            wm.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            self.assertTrue(wm._replay_resume(engine, job))

        self.assertEqual(sent_payloads[0]["body"], INBOUND["text"])
        self.assertEqual(sent_payloads[0]["bodyParts"], [INBOUND["text"]])
        self.assertEqual(sent_payloads[0]["messageIds"], [TOKEN[0]])
        self.assertEqual(engine.sent, [("resume-1", "requeue-1")])
        # O cursor só é removido depois que o turno reexecutado confirmar o envio.
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT)["remaining_text"], "Segunda bolha.")

    def test_partial_resume_uses_the_job_cursor_not_the_latest_chat_cursor(self):
        first_turn = "turn-partial-a"
        second_turn = "turn-partial-b"
        first_inbound = {
            "message_id": "inbound-a",
            "at": 100.0,
            "text": "mensagem A",
        }
        second_inbound = {
            "message_id": "inbound-b",
            "at": 200.0,
            "text": "mensagem B",
        }
        self.addCleanup(wm._clear_partial_reply, first_turn)
        self.addCleanup(wm._clear_partial_reply, second_turn)
        self.assertTrue(wm._save_partial_reply(first_turn, CHAT, "restante A", first_inbound))
        self.assertTrue(wm._save_partial_reply(second_turn, CHAT, "restante B", second_inbound))

        engine = _ResumeEngine()
        job = {
            "id": "resume-exact-cursor",
            "chat_id": CHAT,
            "lease_token": "lease-exact-cursor",
            # O reason continua compatível com instalações antigas; a identidade
            # do cursor segue no próprio job para não escolher o último por chat.
            "basis_outbound_id": f"resume:partial_delivery:{first_turn}",
            "partial_turn_key": first_turn,
        }
        sent_payloads = []

        def fake_urlopen(req, timeout=10):
            sent_payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeResponse({"messageId": "requeue-exact-cursor"})

        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=False), mock.patch.object(
            wm.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            self.assertTrue(wm._replay_resume(engine, job))

        self.assertEqual(sent_payloads[0]["body"], first_inbound["text"])
        self.assertEqual(sent_payloads[0]["messageIds"], [first_inbound["message_id"]])

    def test_delay_cut_does_not_leave_an_orphan_partial_cursor(self):
        self.assertTrue(wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND))
        wm._turn_key[CHAT] = TURN
        wm._turn_inflight.add(TURN)
        wm._turn_inbound[TURN] = dict(INBOUND)

        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), mock.patch.object(
            wm, "_ritmo_wait_before_send", return_value=False
        ), mock.patch.object(wm, "_note_unsent_reply"), mock.patch.object(
            wm, "_persist_turn_sent_to_disk"
        ):
            self.assertFalse(
                wm._schedule_contact_reply(
                    CHAT,
                    "Primeira bolha.\n\nSegunda bolha.",
                    TURN,
                    consumed_inbound_token=TOKEN,
                    inbound_snapshot=INBOUND,
                )
            )

        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_business_window_cut_does_not_leave_an_orphan_partial_cursor(self):
        self.assertTrue(wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND))
        wm._turn_key[CHAT] = TURN
        wm._turn_inflight.add(TURN)
        wm._turn_inbound[TURN] = dict(INBOUND)

        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), mock.patch.object(
            wm, "_ritmo_wait_before_send", return_value=True
        ), mock.patch.object(wm, "_ritmo_send_window_ok", return_value=False), mock.patch.object(
            wm, "_note_unsent_reply"
        ), mock.patch.object(wm, "_schedule_model_retry", return_value=False) as retry, mock.patch.object(
            wm, "_queue_owner_notification_safely", return_value=True
        ), mock.patch.object(wm, "_persist_turn_sent_to_disk"):
            self.assertFalse(
                wm._schedule_contact_reply(
                    CHAT,
                    "Primeira bolha.\n\nSegunda bolha.",
                    TURN,
                    consumed_inbound_token=TOKEN,
                    inbound_snapshot=INBOUND,
                )
            )

        retry.assert_called_once_with(CHAT, "partial_delivery", turn_key=TURN)
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_partial_failure_without_schedulable_retry_becomes_terminal(self):
        wm._turn_key[CHAT] = TURN
        wm._turn_inflight.add(TURN)
        wm._turn_inbound[TURN] = dict(INBOUND)
        partial = wm.PartialMessageDelivery(
            "out-1",
            remaining_text="Segunda bolha.",
            sent_parts=1,
        )

        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), mock.patch.object(
            wm, "_ritmo_wait_before_send", return_value=True
        ), mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), mock.patch.object(
            wm, "_deliver_contact_reply", side_effect=partial
        ), mock.patch.object(wm, "_schedule_model_retry", return_value=False), mock.patch.object(
            wm, "_queue_owner_notification_safely", return_value=True
        ), mock.patch.object(wm, "_persist_turn_sent_to_disk"), mock.patch.object(
            wm, "_mark_bot_spoke"
        ):
            self.assertFalse(
                wm._schedule_contact_reply(
                    CHAT,
                    "Primeira bolha.\n\nSegunda bolha.",
                    TURN,
                    consumed_inbound_token=TOKEN,
                    inbound_snapshot=INBOUND,
                )
            )

        self.assertIn(TURN, wm._turn_sent)
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_partial_replay_checks_sqlite_for_newer_inbound_after_restart(self):
        self.assertTrue(wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND))
        db_path = Path(self._tmp.name) / "whatsapp_messages.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE messages (chat_id TEXT, message_id TEXT, body TEXT, from_me INTEGER, timestamp REAL)"
            )
            conn.executemany(
                "INSERT INTO messages(chat_id, message_id, body, from_me, timestamp) VALUES (?, ?, ?, ?, ?)",
                [
                    (CHAT, TOKEN[0], INBOUND["text"], 0, TOKEN[1]),
                    (CHAT, "outbound-before-b", "bolha confirmada", 1, 150.0),
                    (CHAT, "inbound-b", "mensagem B nova", 0, 200.0),
                ],
            )
            conn.commit()

        engine = _ResumeEngine()
        job = {
            "id": "resume-after-restart",
            "chat_id": CHAT,
            "lease_token": "lease-after-restart",
            "basis_outbound_id": f"resume:partial_delivery:{TURN}",
            "partial_turn_key": TURN,
        }
        with mock.patch.object(wm, "_MSG_DB_PATH", db_path), mock.patch.object(
            wm, "_current_inbound_record", return_value={}
        ), mock.patch.object(wm, "_resolve_phone_from_jid", return_value=""), mock.patch.object(
            wm.urllib.request, "urlopen"
        ) as urlopen:
            self.assertFalse(wm._replay_resume(engine, job))

        urlopen.assert_not_called()
        self.assertTrue(engine.cancelled)
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_save_rejects_partial_cursor_without_valid_inbound_token(self):
        self.assertFalse(
            wm._save_partial_reply(
                TURN,
                CHAT,
                "Segunda bolha.",
                {"text": "", "message_id": "", "at": 0},
            )
        )
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_replay_rejects_persisted_cursor_with_empty_inbound(self):
        self.partial_path.write_text(
            json.dumps(
                {
                    TURN: {
                        "chat_id": CHAT,
                        "remaining_text": "Segunda bolha.",
                        "inbound_text": "",
                        "inbound_message_id": "",
                        "inbound_at": 0,
                        "updated_at": wm.time.time(),
                    }
                }
            ),
            encoding="utf-8",
        )
        engine = _ResumeEngine()
        job = {
            "id": "resume-invalid-cursor",
            "chat_id": CHAT,
            "lease_token": "lease-invalid-cursor",
            "basis_outbound_id": f"resume:partial_delivery:{TURN}",
            "partial_turn_key": TURN,
        }
        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=False), mock.patch.object(
            wm.urllib.request, "urlopen"
        ) as urlopen:
            self.assertFalse(wm._replay_resume(engine, job))

        urlopen.assert_not_called()
        self.assertTrue(engine.cancelled)
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_partial_replay_original_message_id_reuses_the_same_turn_key(self):
        first_turn = wm._register_contact_turn(
            CHAT,
            CHAT,
            INBOUND["text"],
            exact_inbound_snapshot=dict(INBOUND),
        )
        self.addCleanup(wm._turn_inbound.pop, first_turn, None)
        self.addCleanup(wm._turn_inflight.discard, first_turn)
        self.addCleanup(wm._turn_sent.discard, first_turn)
        self.addCleanup(wm._clear_partial_reply, first_turn)
        self.assertTrue(
            wm._save_partial_reply(first_turn, CHAT, "Segunda bolha.", INBOUND)
        )

        replay_turn = wm._register_contact_turn(
            CHAT,
            CHAT,
            INBOUND["text"],
            exact_inbound_snapshot={
                **INBOUND,
                # O bridge cria um ID sintético para o evento, mas o dispatcher
                # restaura este ID original no replay partial_delivery.
                "at": 200.0,
            },
        )

        self.assertEqual(replay_turn, first_turn)
        self.assertEqual(
            wm._partial_reply_for_turn(replay_turn, CHAT)["remaining_text"],
            "Segunda bolha.",
        )

    def test_newer_inbound_cancels_partial_replay_and_clears_cursor(self):
        wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND)
        engine = _ResumeEngine()
        job = {
            "id": "resume-2",
            "chat_id": CHAT,
            "lease_token": "lease-2",
            "basis_outbound_id": f"resume:partial_delivery:{TURN}",
        }
        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=True):
            self.assertFalse(wm._replay_resume(engine, job))

        self.assertEqual(engine.cancelled, [("resume-2", "newer_inbound")])
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_text_fallback_keeps_cursor_when_voice_is_not_allowed(self):
        # O fallback do fish_tts representa a resposta como ``spoken``; sem PTT
        # permitido, ainda assim é uma sequência de texto idempotente e seu
        # remaining_text deve chegar ao scheduler.
        partial = wm.PartialMessageDelivery(
            "text-1",
            remaining_text="Segunda bolha.",
            sent_parts=1,
        )
        with mock.patch.object(wm, "_split_voice_and_text", return_value=("Primeira bolha.", "", "")), mock.patch.object(
            wm, "_voice_reply_allowed_for", return_value=False
        ), mock.patch.object(wm, "_followup_remember_turn"), mock.patch.object(
            wm, "_human_send", side_effect=partial
        ):
            with self.assertRaises(wm.PartialMessageDelivery) as raised:
                wm._deliver_contact_reply(
                    CHAT,
                    "Primeira bolha.",
                    inbound_snapshot=INBOUND,
                )

        self.assertEqual(raised.exception.remaining_text, "Segunda bolha.")

    def test_hybrid_voice_clears_unsafe_cursor(self):
        partial = wm.PartialMessageDelivery(
            "text-before",
            remaining_text="written-after",
            sent_parts=1,
        )
        send_calls = []

        def send_text(_chat_id, text, **_kwargs):
            send_calls.append(text)
            if len(send_calls) == 2:
                raise partial
            return "text-before"

        with mock.patch.object(
            wm, "_split_voice_and_text", return_value=("spoken", "intro", "written-after")
        ), mock.patch.object(wm, "_voice_reply_allowed_for", return_value=True), mock.patch.object(
            wm, "_followup_remember_turn"
        ), mock.patch.object(wm, "_human_send", side_effect=send_text), mock.patch.object(
            wm, "_maybe_send_voice", return_value="voice-1"
        ):
            with self.assertRaises(wm.PartialMessageDelivery) as raised:
                wm._deliver_contact_reply(
                    CHAT,
                    "spoken",
                    inbound_snapshot=INBOUND,
                )

        self.assertEqual(send_calls, ["intro", "written-after"])
        self.assertEqual(raised.exception.remaining_text, "")


if __name__ == "__main__":
    unittest.main()
