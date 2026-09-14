"""Regressões de entrega da Fase 3 e de turnos parcialmente confirmados.

Os testes exercitam os seams que já existem no módulo: token de inbound,
``_run_playbook_completion`` e o scheduler de entrega. A integração completa
com Hermes/bridge fica fora porque exigiria um processo externo; o contrato
testado aqui é a decisão antes do efeito e o estado do turno após a falha.
"""
from __future__ import annotations

import importlib.util
import os
import sys
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
TOKEN = ("inbound-1", 100.0)
CFG = {
    "media_key": "social_proof",
    "lines": ["reframe 1", "reframe 2"],
}


class _ImmediateThread:
    def __init__(self, *, target, args=(), daemon=None, name=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class PlaybookDeliveryResilienceTests(unittest.TestCase):
    def setUp(self):
        wm._calendar_turn_state.pop(CHAT, None)
        self.addCleanup(wm._calendar_turn_state.pop, CHAT, None)

    def test_new_inbound_aborts_before_the_next_media(self):
        sent = []
        newer = mock.patch.object(
            wm,
            "_newer_inbound_arrived",
            side_effect=[False, True],
        )
        with mock.patch.object(
            wm,
            "_load_media_items",
            return_value=[
                {"path": "/media/one.mp4", "type": "video", "caption": ""},
                {"path": "/media/two.jpeg", "type": "image", "caption": ""},
                {"path": "/media/three.jpeg", "type": "image", "caption": ""},
            ],
        ), mock.patch.object(
            wm,
            "_send_bridge_media",
            side_effect=lambda cid, path, kind: sent.append(("media", path, kind)) or "mid",
        ), mock.patch.object(
            wm,
            "_human_send",
            side_effect=lambda cid, text, **kwargs: sent.append(("text", text)) or "tid",
        ), mock.patch.object(wm, "_playbook_offer_slots") as agenda, mock.patch.object(
            wm.time, "sleep"
        ), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=True
        ), newer as newer_mock:
            wm._run_playbook_completion(CHAT, CFG, TOKEN)

        self.assertEqual(sent, [("media", "/media/one.mp4", "video")])
        self.assertEqual(newer_mock.call_count, 2)
        agenda.assert_not_called()

    def test_new_inbound_aborts_before_reframe(self):
        sent = []
        newer = mock.patch.object(
            wm,
            "_newer_inbound_arrived",
            side_effect=[False, False, True],
        )
        with mock.patch.object(
            wm,
            "_load_media_items",
            return_value=[
                {"path": "/media/one.mp4", "type": "video", "caption": ""},
                {"path": "/media/two.jpeg", "type": "image", "caption": ""},
            ],
        ), mock.patch.object(
            wm,
            "_send_bridge_media",
            side_effect=lambda cid, path, kind: sent.append(("media", kind)) or "mid",
        ), mock.patch.object(
            wm,
            "_human_send",
            side_effect=lambda cid, text, **kwargs: sent.append(("text", text)) or "tid",
        ), mock.patch.object(wm, "_playbook_offer_slots") as agenda, mock.patch.object(
            wm.time, "sleep"
        ), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=True
        ), newer as newer_mock:
            wm._run_playbook_completion(CHAT, CFG, TOKEN)

        self.assertEqual(sent, [("media", "video"), ("media", "image")])
        self.assertEqual(newer_mock.call_count, 3)
        agenda.assert_not_called()

    def test_closed_business_window_blocks_every_playbook_effect(self):
        with mock.patch.object(
            wm,
            "_load_media_items",
            return_value=[{"path": "/media/one.mp4", "type": "video", "caption": ""}],
        ), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=False
        ), mock.patch.object(wm, "_send_bridge_media") as media, mock.patch.object(
            wm, "_human_send"
        ) as text, mock.patch.object(wm, "_playbook_offer_slots") as agenda:
            wm._run_playbook_completion(CHAT, CFG, TOKEN)

        media.assert_not_called()
        text.assert_not_called()
        agenda.assert_not_called()

    def test_retry_resumes_after_last_confirmed_media(self):
        record = {
            wm._PLAYBOOK_PENDING_FIELD: 1.0,
            wm._PLAYBOOK_PROGRESS_FIELD: {"media_sent": 1},
        }
        sent = []
        with mock.patch.object(
            wm, "_contact_record_for_chat", return_value=dict(record)
        ), mock.patch.object(
            wm, "_merge_contact_record_atomic", side_effect=lambda _key, fields, **_kw: record.update(fields)
        ), mock.patch.object(
            wm,
            "_load_media_items",
            return_value=[
                {"path": "/media/already.jpeg", "type": "image", "caption": ""},
                {"path": "/media/pending.jpeg", "type": "image", "caption": ""},
            ],
        ), mock.patch.object(
            wm,
            "_send_bridge_media",
            side_effect=lambda _cid, path, _kind: sent.append(path) or "mid",
        ), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=True
        ), mock.patch.object(
            wm, "_newer_inbound_arrived", return_value=False
        ), mock.patch.object(wm, "_human_send"), mock.patch.object(
            wm, "_playbook_offer_slots", return_value=True
        ), mock.patch.object(wm.time, "sleep"):
            wm._run_playbook_completion(CHAT, {"media_key": "proof", "lines": []}, TOKEN)

        self.assertEqual(sent, ["/media/pending.jpeg"])
        self.assertIn(wm._PLAYBOOK_COMPLETION_FIELD, record)

    def test_playbook_claim_does_not_mask_a_partial_sequence(self):
        record = {}

        def merge(_key, fields, **_kwargs):
            record.update(fields)
            return CHAT, dict(record), {CHAT: dict(record)}

        def send_media(_chat_id, path, _kind):
            if path.endswith("two.jpeg"):
                raise wm.PartialMessageDelivery("media-one")
            return "media-one"

        with mock.patch.object(wm, "_playbook_completion_config", return_value={
            "trigger_regex": "Rapidamente",
            "requires_sent_regex": "diagnostico",
            "media_key": "social_proof",
            "lines": ["reframe"],
        }), mock.patch.object(wm, "_chat_bot_sent_matching", return_value=True), mock.patch.object(
            wm, "_contact_record_for_chat", side_effect=lambda _chat: dict(record)
        ), mock.patch.object(wm, "_merge_contact_record_atomic", side_effect=merge), mock.patch.object(
            wm,
            "_load_media_items",
            return_value=[
                {"path": "/media/one.jpeg", "type": "image", "caption": ""},
                {"path": "/media/two.jpeg", "type": "image", "caption": ""},
            ],
        ), mock.patch.object(wm, "_send_bridge_media", side_effect=send_media), mock.patch.object(
            wm, "_human_send"
        ), mock.patch.object(wm, "_playbook_offer_slots"), mock.patch.object(
            wm.time, "sleep"
        ), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=True
        ), mock.patch.object(wm.threading, "Thread", _ImmediateThread):
            self.assertTrue(wm._maybe_start_playbook_completion(CHAT, "Rapidamente", TOKEN))
            # Uma falha parcial deixa o restante do playbook pendente/reexecutável;
            # o timestamp de claim não pode bloquear a segunda tentativa.
            self.assertTrue(wm._maybe_start_playbook_completion(CHAT, "Rapidamente", TOKEN))

    def test_partial_delivery_remains_retryable_instead_of_terminal(self):
        turn_key = "turn-partial"
        wm._turn_key[CHAT] = turn_key
        wm._turn_inflight.add(turn_key)
        wm._turn_sent.discard(turn_key)
        wm._turn_inbound[turn_key] = {
            "message_id": TOKEN[0],
            "at": TOKEN[1],
            "text": "resposta original",
        }
        self.addCleanup(wm._turn_key.pop, CHAT, None)
        self.addCleanup(wm._turn_inflight.discard, turn_key)
        self.addCleanup(wm._turn_sent.discard, turn_key)
        self.addCleanup(wm._turn_inbound.pop, turn_key, None)

        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), mock.patch.object(
            wm, "_ritmo_wait_before_send", return_value=True
        ), mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), mock.patch.object(
            wm,
            "_deliver_contact_reply",
            side_effect=wm.PartialMessageDelivery(
                "confirmed-bubble",
                remaining_text="bolha restante",
                sent_parts=1,
            ),
        ), mock.patch.object(wm, "_followup_register_outbound"), mock.patch.object(
            wm, "_queue_owner_notification_safely", return_value=True
        ), mock.patch.object(
            wm, "_save_partial_reply", return_value=True
        ), mock.patch.object(
            wm, "_schedule_model_retry", return_value=True
        ), mock.patch.object(wm, "_persist_turn_sent_to_disk"):
            self.assertFalse(
                wm._schedule_contact_reply(
                    CHAT,
                    "resposta parcial",
                    turn_key,
                    consumed_inbound_token=TOKEN,
                    inbound_snapshot={
                        "message_id": TOKEN[0],
                        "at": TOKEN[1],
                        "text": "mensagem do lead",
                    },
                )
            )

        self.assertNotIn(turn_key, wm._turn_sent)
        self.assertIn(turn_key, wm._turn_inbound)
        reserved, reserved_key = wm._reserve_contact_send(
            CHAT,
            CHAT,
            "retry",
            expected_turn_key=turn_key,
        )
        self.assertTrue(reserved)
        self.assertEqual(reserved_key, turn_key)


if __name__ == "__main__":
    unittest.main()
