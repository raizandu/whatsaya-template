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
import contextlib
import json
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
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
        self.dispatched = []

    def revalidate_claim(self, job_id, lease_token, *, now):
        return True

    def cancel_claimed(self, job_id, lease_token, reason):
        self.cancelled.append((job_id, reason))

    def mark_failed(self, job_id, error, lease_token):
        self.failed.append((job_id, error))

    def mark_uncertain(self, job_id, error, lease_token):
        self.uncertain.append((job_id, error))

    def mark_dispatched(self, job_id, message_id, lease_token, *, at):
        self.dispatched.append((job_id, message_id))

    def defer_claim(self, job_id, lease_token, error, *, at):
        self.deferred = [*getattr(self, "deferred", []), (job_id, error)]


class PartialReplyIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="whatsaya-partial-")
        self.partial_path = Path(self._tmp.name) / "partial_reply_state.json"
        self.path_patch = mock.patch.object(wm, "_PARTIAL_REPLY_PATH", self.partial_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        silence_patch = mock.patch.object(wm, "_check_chat_silenced", return_value=False)
        silence_patch.start()
        self.addCleanup(silence_patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(wm._turn_inflight.discard, TURN)
        self.addCleanup(wm._turn_sent.discard, TURN)
        self.addCleanup(wm._turn_key.pop, CHAT, None)
        self.addCleanup(wm._turn_inbound.pop, TURN, None)
        wm._clear_partial_reply(TURN)

    def test_multiline_opening_retry_reaches_original_cursor_through_gateway(self):
        self._multiline_opening_retry_through_gateway()

    def test_priority_inbound_between_requeue_and_dispatch_blocks_opening_retry(self):
        self._multiline_opening_retry_through_gateway(newer_text="Quero falar com uma pessoa")

    def _multiline_opening_retry_through_gateway(self, newer_text=""):
        """Replay real: o cursor guarda espaços, mas a chave veio do texto com newline."""
        lead = "Olá! Tenho interesse e queria mais informações, por favor."
        original = lead + "\n" + lead
        inbound = {"message_id": "resume:original-batch", "at": 100.0,
                   "text": " ".join(original.split())}
        self.addCleanup(wm._clear_inbound, CHAT)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {
                "WHATSAPP_BUSINESS_PROFILE": "therapify", "WHATSAPP_OWNER_NUMBER": "5521979069520",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(REPO_ROOT / "deploy/clients/therapify/business_profile.json"),
            }))
            wm._business_profile_cache["checked_at"] = 0.0
            self.addCleanup(wm._business_profile_cache.update, {"checked_at": 0.0})
            for name, value in {
                "_OPENING_INBOUND_OUTBOX_PATH": Path(self._tmp.name) / "opening.db",
                "_TURN_SENT_PATH": Path(self._tmp.name) / "sent.json",
                "_pending_inbound": {}, "_pending_inbound_queue": {}, "_seen_message_ids": set(),
                "_turn_key": {}, "_turn_inbound": {}, "_turn_sent": set(), "_turn_inflight": set(),
                "_HUMAN_DELIVER_SYNC": True,
            }.items():
                stack.enter_context(mock.patch.object(wm, name, value))
            turn = wm._register_contact_turn(CHAT, CHAT, original, exact_inbound_snapshot=inbound)
            remaining = "\n\n".join(wm._therapify_first_outbound_bubbles()[2:])
            self.assertTrue(wm._save_partial_reply(turn, CHAT, remaining, inbound, opening=True))
            normalized_turn = wm._register_contact_turn(CHAT, CHAT, inbound["text"], exact_inbound_snapshot=inbound)
            self.assertNotEqual(normalized_turn, turn)
            # Um replay anterior já consumiu a identidade errada; após restart só
            # o cursor original e a lista de turnos entregues sobreviveram.
            wm._turn_sent.add(normalized_turn)
            wm._turn_key.clear()
            wm._turn_inbound.clear()
            for name, value in {
                "_contact_security_reset_snapshot": {}, "_fetch_chat_history": "",
                "_ensure_contact_ai_access": (True, "ok"), "_check_bot_paused": False,
                "_check_chat_silenced": False, "_get_active_owner_status": None,
                "_prompt_injection_kind": None, "_prompt_injection_kind_for_turn": None,
                "_pending_lead_messages": [], "_newer_inbound_arrived": False,
                "_ritmo_gate": None, "_ritmo_send_window_ok": True, "_bot_has_spoken": True,
            }.items():
                stack.enter_context(mock.patch.object(wm, name, return_value=value))
            for name in ("_followup_note_activity", "_complete_pending_panel_unblock",
                         "_persist_turn_sent_to_disk", "_maybe_start_playbook_completion"):
                stack.enter_context(mock.patch.object(wm, name))
            stack.enter_context(mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid))
            stack.enter_context(mock.patch.object(wm, "_coalesce_contact_inbound", side_effect=lambda _cid, text: text))
            delivered = stack.enter_context(mock.patch.object(wm, "_deliver_contact_reply", return_value="ack-last"))
            dispatch_results = []

            def requeue(request, timeout=10):
                payload = json.loads(request.data.decode())
                raw = {"messageId": "resume:retry-event", "resume": {
                    "reason": payload["reason"], "messageIds": payload["messageIds"]}}
                source = SimpleNamespace(platform=SimpleNamespace(value="whatsapp"), user_id=CHAT, chat_id=CHAT)
                event = SimpleNamespace(source=source, text=payload["body"], raw_message=raw, raw=raw, is_historical=False)
                media = {"has_media": False, "media_type": None, "media_urls": [], "message_id": raw["messageId"]}
                gateway = SimpleNamespace(_session_key_for_source=lambda _source: CHAT, _session_model_overrides={})
                if newer_text:
                    # O replay já passou pela validação, mas a entrega no gateway
                    # ainda não começou. Não deixe seu _track apagar a prioridade.
                    wm._track_inbound(CHAT, "newer-priority-inbound", newer_text)
                with mock.patch.object(wm, "_get_media_info", return_value=media):
                    dispatch_results.append(wm.pre_gateway_dispatch(event=event, gateway=gateway))
                return _FakeResponse({"messageId": raw["messageId"]})

            stack.enter_context(mock.patch.object(wm.urllib.request, "urlopen", side_effect=requeue))
            engine = _ResumeEngine()
            job = {"id": "resume-opening", "chat_id": CHAT, "lease_token": "lease",
                   "basis_outbound_id": f"resume:partial_delivery:{turn}"}
            self.assertTrue(wm._replay_resume(engine, job))
            if newer_text:
                self.assertEqual(dispatch_results, [{"action": "skip", "reason": "partial-delivery-newer-inbound"}])
                delivered.assert_not_called()
                self.assertEqual(wm._current_inbound_record(CHAT)["message_id"], "newer-priority-inbound")
                self.assertEqual(wm._partial_reply_for_turn(turn, CHAT)["remaining_text"], remaining)
                return
            self.assertEqual(dispatch_results, [{"action": "skip", "reason": "partial-delivery-scheduled"}])
            delivered.assert_called_once()
            self.assertEqual(delivered.call_args.args, (CHAT, remaining))
            self.assertTrue(delivered.call_args.kwargs["opening_already_started"])
            self.assertIn(turn, wm._turn_sent)
            self.assertEqual(wm._partial_reply_for_turn(turn, CHAT), {})

    def test_partial_resume_requires_matching_inbound_and_certain_cursor(self):
        self.enterContext(mock.patch.object(wm, "_turn_key", {}))
        self.enterContext(mock.patch.object(wm, "_turn_inbound", {}))
        self.enterContext(mock.patch.object(wm, "_turn_sent", set()))
        self.enterContext(mock.patch.object(wm, "_turn_inflight", set()))
        for changed in (
            {"message_id": "different-inbound"},
            {"text": "outra pergunta do lead"},
            {"chat_id": "5511999999999@s.whatsapp.net"},
            {"send_in_flight": True},
        ):
            with self.subTest(changed=changed):
                wm._save_partial_reply(TURN, CHAT, "Bolha restante.", INBOUND, opening=True)
                cursor = json.loads(self.partial_path.read_text())
                incoming = dict(INBOUND)
                if "message_id" in changed or "text" in changed:
                    incoming.update(changed)
                else:
                    cursor[TURN].update(changed)
                    self.partial_path.write_text(json.dumps(cursor))
                with mock.patch.object(wm, "_current_inbound_record", return_value=incoming), \
                     mock.patch.object(wm, "_schedule_contact_reply") as schedule:
                    self.assertFalse(wm._schedule_deterministic_contact_reply(
                        chat_id=CHAT, session_id=CHAT, user_message=incoming["text"],
                        response_text="Bolha restante.",
                        consumed_inbound_token=(incoming["message_id"], incoming["at"]),
                        inbound_snapshot=incoming, resume_turn_key=TURN,
                    ))
                schedule.assert_not_called()
                self.assertEqual(wm._turn_inflight, set())

    def test_opening_retry_does_not_expand_cursor_when_first_outbound_marker_is_absent(self):
        profile = REPO_ROOT / "deploy/clients/therapify/business_profile.json"
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify",
                                        "WHATSAPP_BUSINESS_PROFILE_FILE": str(profile)}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", Path(self._tmp.name) / "opening.db"), \
             mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), \
             mock.patch.object(wm, "_bot_has_spoken", return_value=False), \
             mock.patch.object(wm, "_persist_turn_sent_to_disk"), \
             mock.patch.object(wm, "_maybe_start_playbook_completion"), \
             mock.patch.object(wm, "_deliver_contact_reply", return_value="last-ack") as deliver:
            remaining = "\n\n".join(wm._therapify_first_outbound_bubbles()[2:])
            wm._save_partial_reply(TURN, CHAT, remaining, INBOUND, opening=True)
            wm._turn_inflight.add(TURN)
            self.assertTrue(wm._schedule_contact_reply(
                CHAT, remaining, TURN, consumed_inbound_token=TOKEN, inbound_snapshot=INBOUND,
            ))
        self.assertEqual(deliver.call_args.args, (CHAT, remaining))

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

    def test_partial_timeout_requires_manual_reconciliation_not_automatic_retry(self):
        calls = 0
        def fake_urlopen(req, timeout=10):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _FakeResponse({"messageId": "out-1"})
            raise TimeoutError("resultado desconhecido")

        with mock.patch.object(wm.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(wm.PartialMessageDelivery) as raised:
                wm._human_send(CHAT, "Primeira bolha.\n\nSegunda bolha.")
        self.assertTrue(raised.exception.uncertain)

        wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND)
        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_ritmo_wait_before_send", return_value=True), \
             mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), \
             mock.patch.object(wm, "_deliver_contact_reply", side_effect=raised.exception), \
             mock.patch.object(wm, "_schedule_model_retry") as retry, \
             mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
             mock.patch.object(wm, "_complete_contact_send"), \
             mock.patch.object(wm, "_mark_bot_spoke"):
            self.assertFalse(wm._schedule_contact_reply(
                CHAT, "Primeira bolha.\n\nSegunda bolha.", TURN,
                consumed_inbound_token=TOKEN, inbound_snapshot=INBOUND,
            ))
        retry.assert_not_called()
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_partial_known_503_keeps_safe_retry(self):
        calls = 0
        def fake_urlopen(req, timeout=10):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _FakeResponse({"messageId": "out-1"})
            raise wm.urllib.error.HTTPError("http://bridge/send", 503, "disconnected", {}, None)

        with mock.patch.object(wm.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(wm.PartialMessageDelivery) as raised:
                wm._human_send(CHAT, "Primeira bolha.\n\nSegunda bolha.")
        self.assertFalse(raised.exception.uncertain)
        self.assertEqual(raised.exception.remaining_text, "Segunda bolha.")

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
        self.assertEqual(engine.dispatched, [("resume-1", "requeue-1")])
        # O cursor só é removido depois que o turno reexecutado confirmar o envio.
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT)["remaining_text"], "Segunda bolha.")

    def test_opening_retry_keeps_captured_new_inbound_and_releases_after_last_ack(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        with mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path):
            self.assertTrue(wm._save_partial_reply(TURN, CHAT, "Segunda bolha.\n\nTerceira bolha.", INBOUND, opening=True))
            outbox = wm._opening_inbound_outbox()
            outbox.defer(CHAT, "new-id", TURN, "Uma pergunta", 101.0)
            engine = _ResumeEngine()
            job = {"id": "resume-opening", "chat_id": CHAT, "lease_token": "lease", "basis_outbound_id": f"resume:partial_delivery:{TURN}"}
            with mock.patch.object(wm, "_newer_inbound_arrived", return_value=False), \
                 mock.patch.object(wm, "_pending_lead_messages", return_value=[("new-id", "Uma pergunta")]), \
                 mock.patch.object(wm.urllib.request, "urlopen", return_value=_FakeResponse({"messageId": "requeue"})):
                self.assertTrue(wm._replay_resume(engine, job))
            self.assertEqual(engine.cancelled, [])
            self.assertIsNone(wm._opening_inbound_outbox().claim_next())

            delivered = []
            def complete(_chat, text, *, on_progress, **kwargs):
                delivered.append(text)
                on_progress("")
                return "last-bubble"
            with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
                 mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), \
                 mock.patch.object(wm, "_bot_has_spoken", return_value=True), \
                 mock.patch.object(wm, "_deliver_contact_reply", side_effect=complete), \
                 mock.patch.object(wm, "_complete_contact_send"), \
                 mock.patch.object(wm, "_maybe_start_playbook_completion"):
                self.assertTrue(wm._schedule_contact_reply(CHAT, "texto antigo", TURN, consumed_inbound_token=TOKEN, inbound_snapshot=INBOUND))
            self.assertEqual(delivered, ["Segunda bolha.\n\nTerceira bolha."])
            restored = wm._opening_inbound_outbox()
            item = restored.claim_next()
            self.assertEqual((item["message_id"], item["body"]), ("new-id", "Uma pergunta"))
            self.assertTrue(restored.claim_processing(CHAT, "new-id"))
            self.assertFalse(restored.claim_processing(CHAT, "new-id"))
            self.assertTrue(restored.acknowledge(CHAT, "new-id", "reply-id"))
            self.assertIsNone(wm._opening_inbound_outbox().claim_next())

    def test_opening_defer_persists_all_debounced_ids_before_suppressing_dispatch(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        newer = {"message_id": "new-2", "at": 101.0, "text": "Oi\nQuanto custa?"}
        raw = {"debounceIds": ["new-1", "new-2"], "bodyParts": ["Oi", "Quanto custa?"]}
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_current_inbound_record", return_value=newer), \
             mock.patch.object(wm, "_pending_inbound_queue", {CHAT: [newer]}), \
             mock.patch.object(wm, "_clear_inbound") as clear:
            wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND, opening=True)
            self.assertTrue(wm._defer_new_opening_inbound(CHAT, newer, raw))
            self.assertTrue(wm._opening_inbound_outbox().contains_all(CHAT, ["new-1", "new-2"]))
            clear.assert_called_once()
            self.assertIsNone(wm._opening_inbound_outbox().claim_next())

    def test_pre_gateway_persists_text_before_coalescer_and_keeps_voice_separate(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        source = SimpleNamespace(platform=SimpleNamespace(value="whatsapp"), user_id=CHAT, chat_id=CHAT)
        event = SimpleNamespace(source=source, text="Sim", raw_message={"messageId": "text-real"},
                                raw={"messageId": "text-real"}, is_historical=False)
        media = {"has_media": False, "media_type": None, "media_urls": [], "message_id": "text-real"}
        self.addCleanup(wm._seen_message_ids.discard, "text-real")
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify", "WHATSAPP_OWNER_NUMBER": "5521979069520"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_get_media_info", return_value=media), \
             mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid), \
             mock.patch.object(wm, "_contact_security_reset_snapshot", return_value={}), \
             mock.patch.object(wm, "_prompt_injection_kind", return_value=None), \
             mock.patch.object(wm, "_prompt_injection_kind_for_turn", return_value=None), \
             mock.patch.object(wm, "_fetch_chat_history", return_value=""), \
             mock.patch.object(wm, "_complete_pending_panel_unblock"), \
             mock.patch.object(wm, "_ensure_contact_ai_access", return_value=(True, "ok")), \
             mock.patch.object(wm, "_followup_note_activity"), \
             mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_check_chat_silenced", return_value=False), \
             mock.patch.object(wm, "_coalesce_contact_inbound") as coalescer:
            wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND, opening=True)
            result = wm.pre_gateway_dispatch(event=event, gateway=SimpleNamespace())
            self.assertEqual(result, {"action": "skip", "reason": "opening-deferred"})
            self.assertTrue(wm._opening_inbound_outbox().contains_all(CHAT, ["text-real"]))
            coalescer.assert_not_called()
            media["message_id"] = "text-second"
            second = SimpleNamespace(source=source, text="10", raw_message={"messageId": "text-second"},
                                     raw={"messageId": "text-second"}, is_historical=False)
            self.addCleanup(wm._seen_message_ids.discard, "text-second")
            self.assertEqual(wm.pre_gateway_dispatch(event=second, gateway=SimpleNamespace()),
                             {"action": "skip", "reason": "opening-deferred"})
            reopened = wm._opening_inbound_outbox()
            self.assertTrue(reopened.contains_all(CHAT, ["text-real", "text-second"]))
            reopened.mark_opening_complete(TURN)
            with sqlite3.connect(outbox_path) as conn:
                conn.execute("UPDATE opening_inbound_outbox SET close_at=0")
            batch = wm._opening_inbound_outbox().claim_next()
            self.assertEqual(batch["message_ids"], ["text-real", "text-second"])
            self.assertEqual(batch["body_parts"], ["Sim", "10"])
            media["message_id"] = "human-real"
            human = SimpleNamespace(source=source, text="Quero falar com uma pessoa", raw_message={"messageId": "human-real"},
                                    raw={"messageId": "human-real"}, is_historical=False)
            self.addCleanup(wm._seen_message_ids.discard, "human-real")
            self.addCleanup(wm._clear_inbound, CHAT)
            with mock.patch.object(wm, "_schedule_deterministic_contact_reply", return_value=True):
                self.assertEqual(wm.pre_gateway_dispatch(event=human, gateway=SimpleNamespace()),
                                 {"action": "skip", "reason": "human-handoff-scheduled"})
            self.assertEqual(wm._current_inbound_record(CHAT)["message_id"], "human-real")
            coalescer.assert_not_called()
            media.update({"has_media": True, "media_type": "image", "message_id": "crisis-media"})
            crisis = SimpleNamespace(source=source, text="Estou pensando em me matar agora", raw_message={"messageId": "crisis-media"},
                                     raw={"messageId": "crisis-media"}, is_historical=False)
            self.addCleanup(wm._seen_message_ids.discard, "crisis-media")
            with mock.patch.object(wm, "_activate_therapify_crisis") as activate, \
                 mock.patch.object(wm, "_handle_therapify_crisis") as handle, \
                 mock.patch.object(wm, "_register_contact_turn", return_value="crisis-turn"), \
                 mock.patch.object(wm, "_report_uncertain_opening") as media_report:
                self.assertEqual(wm.pre_gateway_dispatch(event=crisis, gateway=SimpleNamespace()),
                                 {"action": "skip", "reason": "therapify-crisis"})
            activate.assert_called_once()
            handle.assert_called_once()
            media_report.assert_not_called()
            media.update({"has_media": True, "media_type": "audio", "message_id": "voice-real"})
            voice = SimpleNamespace(source=source, text="", raw_message={"messageId": "voice-real"},
                                    raw={"messageId": "voice-real"}, is_historical=False)
            self.addCleanup(wm._seen_message_ids.discard, "voice-real")
            self.addCleanup(wm._opening_capture_failed.clear)
            with mock.patch.object(wm, "_pause_for_opening_uncertainty"), \
                 mock.patch.object(wm, "_followup_cancel"), \
                 mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
                 mock.patch.object(wm, "_report_uncertain_opening") as report:
                self.assertEqual(wm.pre_gateway_dispatch(event=voice, gateway=SimpleNamespace()),
                                 {"action": "skip", "reason": "opening-media-needs-human"})
            report.assert_called_once_with(CHAT, TURN)
            coalescer.assert_not_called()
            self.assertTrue(wm._opening_inbound_outbox().contains_all(CHAT, ["voice-real"]))
            media_item = wm._opening_inbound_outbox().uncertain_batches(CHAT)[0]
            self.assertEqual(wm._opening_inbound_outbox().resolve_batch(CHAT, "voice-real", media_item["version"], "not_sent", "admin"), "manual_required")

    def test_restart_does_not_retry_opening_with_uncertain_bubble(self):
        self.assertTrue(wm._save_partial_reply(TURN, CHAT, "Bolha incerta.", INBOUND, opening=True))
        self.assertTrue(wm._mark_partial_send_in_flight(TURN))
        with mock.patch.object(wm, "_followup_enabled", return_value=True), \
             mock.patch.object(wm, "_followup_engine", return_value=mock.Mock()), \
             mock.patch.object(wm, "_orphan_lead_chats", return_value=[CHAT]), \
             mock.patch.object(wm, "_report_uncertain_opening") as report, \
             mock.patch.object(wm, "_schedule_model_retry") as retry:
            self.assertEqual(wm._recover_after_restart(), 0)
        report.assert_called_once_with(CHAT, TURN)
        retry.assert_not_called()
        self.assertTrue(wm._partial_reply_for_turn(TURN, CHAT)["send_in_flight"])

    def test_opening_inbound_storage_failure_stops_automation_and_alerts(self):
        newer = {"message_id": "new-id", "at": 101.0, "text": "Minha dúvida"}
        self.addCleanup(wm._opening_capture_failed.clear)
        broken = mock.Mock()
        broken.defer_batch.side_effect = OSError("disco indisponível")
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), \
             mock.patch.object(wm, "_opening_inbound_outbox", return_value=broken), \
             mock.patch.object(wm, "_opening_new_inbounds_are_safe", return_value=True), \
             mock.patch.object(wm, "_pause_for_opening_uncertainty") as pause, \
             mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True) as notify, \
             mock.patch.object(wm, "_clear_inbound") as clear:
            wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND, opening=True)
            self.assertTrue(wm._defer_new_opening_inbound(CHAT, newer))
        pause.assert_called_once_with(CHAT)
        notify.assert_called_once()
        clear.assert_not_called()
        self.assertIn(wm._contact_effect_lock_key(CHAT), wm._opening_capture_failed)

    def test_opening_defer_resolves_lid_to_opening_chat_identity(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        lid = "123456789012345@lid"
        newer = {"message_id": "new-id", "at": 101.0, "text": "Olá"}
        def identity(value):
            return ({value}, {"phone-key"})
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_contact_identity_candidates", side_effect=identity), \
             mock.patch.object(wm, "_opening_new_inbounds_are_safe", return_value=True), \
             mock.patch.object(wm, "_clear_inbound"):
            wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND, opening=True)
            self.assertTrue(wm._defer_new_opening_inbound(lid, newer))
            self.assertTrue(wm._opening_inbound_outbox().contains_all(CHAT, ["new-id"]))

    def test_new_message_after_last_bubble_waits_for_deferred_turn(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify", "WHATSAPP_INBOUND_BUFFER_S": "2"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path):
            wm._save_partial_reply(TURN, CHAT, "Última bolha.", INBOUND, opening=True)
            first = {"message_id": "one", "at": 101.0, "text": "Sim"}
            second = {"message_id": "two", "at": 102.0, "text": "10"}
            self.assertTrue(wm._defer_new_opening_inbound(CHAT, first, before_coalesce=True))
            wm._opening_inbound_outbox().mark_opening_complete(TURN)
            wm._clear_partial_reply(TURN)
            self.assertTrue(wm._defer_new_opening_inbound(CHAT, second, before_coalesce=True))
            with sqlite3.connect(outbox_path) as conn:
                conn.execute("UPDATE opening_inbound_outbox SET close_at=0")
            batch = wm._opening_inbound_outbox().claim_next()
            self.assertEqual(batch["message_ids"], ["one", "two"])
            self.assertEqual(batch["body"], "Sim\n10")

    def test_pending_outbox_matches_alias_after_opening_finishes(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        lid = "123456789012345@lid"
        def identity(value):
            return ({value}, {"phone-key"})
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify", "WHATSAPP_INBOUND_BUFFER_S": "2"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_contact_identity_candidates", side_effect=identity):
            outbox = wm._opening_inbound_outbox()
            outbox.defer_batch(CHAT, TURN, [("one", "Sim")], 101, coalesce_s=2)
            outbox.mark_opening_complete(TURN)
            self.assertTrue(wm._defer_new_opening_inbound(lid, {"message_id": "two", "at": 102.0, "text": "10"}, before_coalesce=True))
            self.assertTrue(outbox.contains_all(CHAT, ["one", "two"]))

    def test_explicit_resume_releases_only_authorized_turn_dedup(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        sent_path = Path(self._tmp.name) / "turn-sent.json"
        sent_path.write_text(json.dumps({TURN: 100.0, "other-turn": 100.0}))
        with mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_TURN_SENT_PATH", sent_path):
            wm._opening_inbound_outbox().request_resume(CHAT, [TURN])
            wm._turn_sent.update({TURN, "other-turn"})
            self.addCleanup(wm._turn_sent.discard, "other-turn")
            self.assertTrue(wm._reserve_contact_send(CHAT, CHAT, "oi", expected_turn_key=TURN)[0])
            saved = json.loads(sent_path.read_text())
            self.assertNotIn(TURN, saved)
            self.assertIn("other-turn", saved)
            self.assertFalse(wm._opening_inbound_outbox().turn_authorized(TURN))

    def test_authorization_is_consumed_even_if_turn_dedup_expired(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        sent_path = Path(self._tmp.name) / "turn-sent.json"
        with mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_TURN_SENT_PATH", sent_path), \
             mock.patch.object(wm, "_clear_partial_reply"):
            wm._opening_inbound_outbox().request_resume(CHAT, [TURN])
            wm._turn_sent.discard(TURN)
            self.assertTrue(wm._reserve_contact_send(CHAT, CHAT, "oi", expected_turn_key=TURN)[0])
            self.assertFalse(wm._opening_inbound_outbox().turn_authorized(TURN))
            wm._complete_contact_send(TURN, delivered=True, uncertain=False)
            self.assertFalse(wm._reserve_contact_send(CHAT, CHAT, "oi", expected_turn_key=TURN)[0])

    def test_resume_intent_waits_for_ai_to_be_enabled_then_schedules_cursor(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        engine = mock.Mock()
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_followup_engine", return_value=engine), \
             mock.patch.object(wm, "is_business_time", return_value=False), \
             mock.patch.object(wm, "_schedule_model_retry", return_value=True) as retry, \
             mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=False) as access:
            wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND, opening=True)
            outbox = wm._opening_inbound_outbox()
            outbox.request_resume(CHAT, [TURN])
            self.assertEqual(wm._tick_opening_inbound_outbox(), 0)
            retry.assert_not_called()
            access.return_value = True
            self.assertEqual(wm._tick_opening_inbound_outbox(), 0)
            retry.assert_called_once_with(CHAT, "partial_delivery", turn_key=TURN)
            self.assertEqual(outbox.pending_resumes(), [])

    def test_old_deferred_attempt_cannot_send_after_new_attempt_claimed(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        sent = []
        with mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "_followup_remember_turn"), \
             mock.patch.object(wm, "_assert_delivery_allowed"), \
             mock.patch.object(wm, "_newer_inbound_arrived", return_value=False), \
             mock.patch.object(wm, "_voice_reply_allowed_for", return_value=False), \
             mock.patch.object(wm, "_human_send", side_effect=lambda _chat, _text, **kw: kw["effect_guard"](lambda: sent.append("sent"))):
            outbox = wm._opening_inbound_outbox()
            outbox.defer(CHAT, "new-id", TURN, "oi", 101)
            outbox.mark_opening_complete(TURN)
            old = outbox.claim_next()["attempt_id"]
            outbox.claim_processing(CHAT, "new-id", attempt_id=old)
            outbox.mark_expired_uncertain(before=10**20)
            item = outbox.uncertain_batches(CHAT)[0]
            self.assertEqual(outbox.resolve_batch(CHAT, "new-id", item["version"], "not_sent", "admin"), "manual_required")
            with sqlite3.connect(outbox_path) as conn:
                conn.execute("UPDATE opening_inbound_outbox SET state='ready' WHERE chat_id=?", (CHAT,))
            new = outbox.claim_next()["attempt_id"]
            self.assertNotEqual(old, new)
            with self.assertRaises(wm.StaleContactReply):
                wm._deliver_contact_reply(CHAT, "resposta", inbound_snapshot={"message_id": "new-id", "at": 101,
                    "text": "oi", "opening_deferred": True, "opening_attempt_id": old})
        self.assertEqual(sent, [])

    def test_outbox_requeues_original_id_then_waits_for_reply_ack(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        payloads = []
        def fake_urlopen(req, timeout=10):
            payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeResponse({"messageId": "resume-synthetic"})
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "is_business_time", return_value=True), \
             mock.patch.object(wm, "_assert_delivery_allowed"), \
             mock.patch.object(wm.urllib.request, "urlopen", side_effect=fake_urlopen):
            outbox = wm._opening_inbound_outbox()
            outbox.defer(CHAT, "new-id", TURN, "Minha dúvida", 101.0)
            outbox.mark_opening_complete(TURN)
            self.assertEqual(wm._tick_opening_inbound_outbox(), 1)
            self.assertEqual(payloads[0]["messageIds"], ["new-id"])
            self.assertTrue(payloads[0]["reason"].startswith("opening_deferred:"))
            self.assertEqual(wm._tick_opening_inbound_outbox(), 0)
            self.assertTrue(wm._opening_inbound_outbox().claim_processing(CHAT, "new-id"))
            self.assertTrue(wm._opening_inbound_outbox().acknowledge(CHAT, "new-id", "reply-id"))
            self.assertEqual(wm._tick_opening_inbound_outbox(), 0)

    def test_blocked_chat_does_not_starve_other_ready_chat(self):
        outbox_path = Path(self._tmp.name) / "opening.db"
        other_chat = "556281405460@s.whatsapp.net"
        payloads = []
        def allowed(chat, **_kwargs):
            if chat == CHAT:
                raise wm.DeliveryBlocked("takeover")
        def fake_urlopen(req, timeout=10):
            payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeResponse({"messageId": "queued"})
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), \
             mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", outbox_path), \
             mock.patch.object(wm, "is_business_time", return_value=True), \
             mock.patch.object(wm, "_assert_delivery_allowed", side_effect=allowed), \
             mock.patch.object(wm.urllib.request, "urlopen", side_effect=fake_urlopen):
            outbox = wm._opening_inbound_outbox()
            outbox.defer(CHAT, "first", "turn1", "olá", 101.0)
            outbox.defer(other_chat, "second", "turn2", "olá", 102.0)
            outbox.mark_opening_complete("turn1")
            outbox.mark_opening_complete("turn2")
            self.assertEqual(wm._tick_opening_inbound_outbox(), 1)
            self.assertEqual(payloads[0]["chatId"], other_chat)

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

    def test_owner_takeover_cancels_stuck_opening_replay_instead_of_waiting_silence(self):
        # 11/11: o job ficou adiado sob o silêncio do dono e repetiu a abertura quando ele venceu.
        wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND, opening=True)
        engine = _ResumeEngine()
        job = {
            "id": "resume-takeover",
            "chat_id": CHAT,
            "lease_token": "lease-t",
            "basis_outbound_id": f"resume:partial_delivery:{TURN}",
        }
        with mock.patch.object(wm, "_check_chat_silenced", return_value=True), \
             mock.patch.object(wm, "_chat_status_cache", {CHAT: {"silenced": True, "ts": 0}}), \
             mock.patch.object(wm.urllib.request, "urlopen") as requeue:
            self.assertFalse(wm._replay_resume(engine, job))
        requeue.assert_not_called()
        self.assertEqual(engine.cancelled, [("resume-takeover", "owner_takeover")])
        self.assertEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

    def test_unknown_chat_status_defers_replay_and_keeps_cursor(self):
        wm._save_partial_reply(TURN, CHAT, "Segunda bolha.", INBOUND)
        engine = _ResumeEngine()
        job = {
            "id": "resume-unknown",
            "chat_id": CHAT,
            "lease_token": "lease-u",
            "basis_outbound_id": f"resume:partial_delivery:{TURN}",
        }
        with mock.patch.object(wm, "_check_chat_silenced", return_value=True), \
             mock.patch.object(wm, "_chat_status_cache", {CHAT: {"silenced": True, "ts": 0, "uncertain": True}}):
            self.assertFalse(wm._replay_resume(engine, job))
        self.assertEqual(engine.cancelled, [])
        self.assertEqual(engine.deferred, [("resume-unknown", "chat_status_unavailable")])
        self.assertNotEqual(wm._partial_reply_for_turn(TURN, CHAT), {})

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
