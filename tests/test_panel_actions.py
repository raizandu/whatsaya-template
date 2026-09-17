"""Escritas do painel: contatos, funil, follow-ups e bridge."""
from __future__ import annotations

import base64
import dataclasses
import json
from datetime import datetime, timezone
import sqlite3
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import atendimento_store  # noqa: E402
import contacts_store  # noqa: E402
import users_store  # noqa: E402
from commercial_followups import FollowupEngine  # noqa: E402
from panel import actions as panel_actions  # noqa: E402
from panel import data as panel_data  # noqa: E402
from panel import server as panel_server  # noqa: E402
from tests.test_panel_data import BLOCKED, LEAD, LEAD2, LEAD_LID, NOW, PanelFixture  # noqa: E402

OWNER_DIGITS = "5547999414100"


class FakeBridge:
    """Registra o que o painel pediu ao bridge e responde como o bridge real."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.down = False
        self.silence_down = False
        self.send_response: dict | None = None
        self.media_response: dict | None = None
        self.seen_files: list[bool] = []
        self.settings = {"rejectCalls": False, "groupsEnabled": False, "debounceInitialMs": 8000}
        self.number_exists: bool | None = True   # None = ponte antiga sem /number-exists
        self.number_jid: str | None = None

    def get_json_status(self, path):
        if self.down:
            return None, None
        if path.startswith("/number-exists?phone="):
            if self.number_exists is None:
                return 404, {"error": "not found"}
            digits = path.split("=", 1)[1]
            jid = self.number_jid or f"{digits}@s.whatsapp.net"
            return 200, {"success": True, "phone": digits, "exists": self.number_exists, "jid": jid if self.number_exists else None}
        return 404, None

    def get_json(self, path):
        if self.down:
            return None
        if path == "/runtime-settings":
            return {"success": True, "settings": self.settings.copy()}
        if path == "/bot-status":
            return {"botPaused": False, "lidToPhone": {}}
        if path == "/chat-silence":
            return {"silencedChats": []}
        return None

    def post_json(self, path, body, timeout=None):
        self.calls.append((path, body))
        if self.down:
            return None
        if path == "/send":
            if self.send_response is not None:
                return self.send_response
            message_id = f"panel-out-{len(self.calls)}"
            return {"success": True, "messageId": message_id, "messageIds": [message_id]}
        if path == "/send-media":
            import os
            self.seen_files.append(os.path.isfile(body["filePath"]))
            if self.media_response is not None:
                return self.media_response
            message_id = f"panel-media-{len(self.calls)}"
            return {"success": True, "messageId": message_id,
                    "media": {"mediaKey": f"media/x/{message_id}.pdf", "mime": "application/pdf", "size": 3, "name": body["fileName"]}}
        if path == "/bot-pause":
            return {"success": True, "botPaused": body["paused"]}
        if path == "/chat-silence":
            if self.silence_down:
                return {"success": False}
            return {"success": True, "chatId": body["chatId"], "hold": bool(body.get("hold")),
                    "silencedUntil": 0 if body.get("hold") else 1, "timeLeftSeconds": 0 if body.get("hold") else 600}
        if path == "/chat-unsilence":
            return {"success": True, "chatId": body["chatId"]}
        if path == "/runtime-settings":
            self.settings = body.copy()
            return {"success": True, "settings": self.settings.copy()}
        return None


class ContactActionsTest(PanelFixture):
    def _contacts(self):
        return contacts_store.read_contacts(self.paths.contacts_json)

    def test_block_by_chat_id_marks_phone_and_lid_and_cancels_followups(self):
        result = panel_actions.block(self.paths, chat_id=LEAD, owner_number=OWNER_DIGITS)
        self.assertEqual(set(result["keys"]), {LEAD, LEAD_LID})
        data = self._contacts()
        for key in (LEAD, LEAD_LID):
            self.assertIs(data[key]["blocked"], True, key)
            self.assertIs(data[key]["ai_enabled"], False, key)
            self.assertEqual(data[key]["ai_disabled_reason"], "panel_block")
        self.assertIn("Mariana Lopes", [b["name"] for b in result["blocked"]])
        jobs = FollowupEngine(self.paths.followups_db).get_jobs(LEAD)
        self.assertFalse([j for j in jobs if j["status"] in ("pending", "leased")], "toques abertos devem ser cancelados")
        self.assertTrue(contacts_store.lock_path_for(self.paths.contacts_json).exists())

    def test_block_by_name_and_by_digits(self):
        by_name = panel_actions.block(self.paths, query="rafael", owner_number=OWNER_DIGITS)
        self.assertEqual(by_name["chat_id"], LEAD2)
        by_digits = panel_actions.block(self.paths, query="+55 47 9 9941-4105", owner_number=OWNER_DIGITS)
        self.assertEqual(by_digits["chat_id"], LEAD)
        unknown = panel_actions.block(self.paths, query="5599911112222", owner_number=OWNER_DIGITS)
        self.assertEqual(unknown["chat_id"], "5599911112222@s.whatsapp.net")
        self.assertIs(self._contacts()["5599911112222@s.whatsapp.net"]["blocked"], True)

    def test_block_refuses_owner_and_unknown_name(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.block(self.paths, query=OWNER_DIGITS, owner_number=OWNER_DIGITS)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.block(self.paths, query="ninguém", owner_number=OWNER_DIGITS)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.block(self.paths, query="", owner_number=OWNER_DIGITS)

    def test_unblock_only_records_the_intent_and_keeps_ai_off(self):
        result = panel_actions.unblock(self.paths, chat_id=BLOCKED)
        self.assertTrue(result["pending_reset"])
        record = self._contacts()[BLOCKED]
        self.assertIs(record["blocked"], False)
        self.assertIs(record["ai_enabled"], False)
        self.assertIs(record["session_reset_pending"], True)
        self.assertEqual(record["ai_disabled_reason"], "panel_unblock_reset_pending")
        self.assertEqual(result["blocked"], [])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.unblock(self.paths, chat_id="inexistente@s.whatsapp.net")


class FunnelActionsTest(PanelFixture):
    def test_set_stage_moves_lead_and_cancels_open_jobs(self):
        result = panel_actions.set_stage(self.paths, chat_id=LEAD, stage="proposal")
        self.assertEqual(result["lead"]["stage"], "proposal")
        board = panel_data.leads(self.paths, now=NOW)
        by_stage = {c["id"]: [x["name"] for x in c["cards"]] for c in board["stages"]}
        self.assertIn("Mariana Lopes", by_stage["proposal"])
        open_jobs = [j for j in FollowupEngine(self.paths.followups_db).get_jobs(LEAD) if j["status"] == "pending"]
        self.assertEqual(open_jobs, [])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_stage(self.paths, chat_id=LEAD, stage="ganho")
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_stage(self.paths, chat_id="nao@s.whatsapp.net", stage="new")

    def test_followup_handback_clears_takeover_and_resumes_automation(self):
        engine = FollowupEngine(self.paths.followups_db)
        engine.note_human_takeover(LEAD2)
        assert engine.get_lead(LEAD2)["takeover"] == 1

        result = panel_actions.followup(self.paths, chat_id=LEAD2, action="handback")

        self.assertEqual(result["action"], "handback")
        self.assertFalse(result["takeover"])
        self.assertTrue(result["automation_enabled"])
        lead = engine.get_lead(LEAD2)
        self.assertEqual(lead["takeover"], 0)
        self.assertEqual(lead["automation_enabled"], 1)

    def test_followup_pause_resume_and_cancel(self):
        paused = panel_actions.followup(self.paths, chat_id=LEAD2, action="pause")
        self.assertFalse(paused["automation_enabled"])
        self.assertEqual(paused["open_jobs"], 0)
        resumed = panel_actions.followup(self.paths, chat_id=LEAD2, action="resume")
        self.assertTrue(resumed["automation_enabled"])
        engine = FollowupEngine(self.paths.followups_db)
        engine.note_outbound(LEAD2, message_id="out-3", at=NOW)
        self.assertTrue([j for j in engine.get_jobs(LEAD2) if j["status"] == "pending"])
        cancelled = panel_actions.followup(self.paths, chat_id=LEAD2, action="cancel")
        self.assertTrue(cancelled["automation_enabled"], "cancelar não desliga a automação")
        self.assertEqual(cancelled["open_jobs"], 0)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.followup(self.paths, chat_id=LEAD2, action="explode")

    def test_estimated_value_accepts_brl_formats_and_can_be_cleared(self):
        for value in ("4.800,00", "4800", "4800.00"):
            result = panel_actions.set_estimated_value(self.paths, chat_id=LEAD, value_brl=value)
            self.assertEqual(result["estimated_value_cents"], 480_000)
        cleared = panel_actions.set_estimated_value(self.paths, chat_id=LEAD, value_brl="")
        self.assertIsNone(cleared["estimated_value_cents"])
        for value in ("quatro mil", "12,345", "100000000"):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.set_estimated_value(self.paths, chat_id=LEAD, value_brl=value)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_estimated_value(self.paths, chat_id="inexistente@s.whatsapp.net", value_brl="10")


class ReplyActionTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()

    def _message_count(self, chat_id):
        conn = sqlite3.connect(self.paths.messages_db)
        try:
            return conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]
        finally:
            conn.close()

    def test_reply_sends_persists_autoria_and_silences(self):
        before = self._message_count(LEAD)

        result = panel_actions.reply(
            self.paths, self.bridge, chat_id=LEAD, message="Pode ser quinta às 14h.",
            sent_by="Anthony", sent_by_user="dono", owner_number=OWNER_DIGITS,
        )

        self.assertEqual(result["chat_id"], LEAD)
        self.assertEqual(result["sent_by"], "Anthony")
        self.assertEqual(result["sent_by_user"], "dono")
        self.assertIs(result["silenced"], True)
        self.assertNotIn("warning", result)
        self.assertEqual(self._message_count(LEAD), before + 1)

        conn = sqlite3.connect(self.paths.messages_db)
        row = conn.execute(
            "SELECT from_me, sender_name, message_type, body FROM messages WHERE message_id=?",
            (result["message_id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(row, (1, "Anthony", "text", "Pode ser quinta às 14h."))

        self.assertEqual([c[0] for c in self.bridge.calls], ["/send", "/chat-silence"])
        send_body = self.bridge.calls[0][1]
        self.assertEqual(send_body["chatId"], LEAD)
        self.assertIs(send_body["automation"], False)
        self.assertEqual(self.bridge.calls[1][1]["chatId"], LEAD)

        # Autoria própria mesmo sem nenhum `[human-send]` no log daquele dia.
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        item = next(
            item for item in detail["timeline"] if item["type"] == "message"
            and any(b["message_id"] == result["message_id"] for b in item["bubbles"])
        )
        self.assertEqual(item["owner"], "owner")
        self.assertEqual(item["sent_by"], "Anthony")

    def test_reply_fails_closed_when_bridge_is_down(self):
        self.bridge.down = True
        before = self._message_count(LEAD)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self._message_count(LEAD), before)
        self.assertFalse(Path(self.paths.panel_db).exists())

    def test_reply_without_message_id_persists_nothing(self):
        self.bridge.send_response = {"success": True, "info": "blocked"}
        before = self._message_count(LEAD)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self._message_count(LEAD), before)
        self.assertFalse(Path(self.paths.panel_db).exists())

    def test_reply_persists_message_even_when_silence_fails(self):
        self.bridge.silence_down = True
        before = self._message_count(LEAD)

        result = panel_actions.reply(
            self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono",
        )

        self.assertEqual(self._message_count(LEAD), before + 1)
        self.assertIsNone(result["silenced"])
        self.assertIn("warning", result)

    def test_reply_refuses_blocked_contact_before_reaching_the_bridge(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reply(self.paths, self.bridge, chat_id=BLOCKED, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self.bridge.calls, [])

    def test_reply_refuses_empty_blank_or_too_long_message(self):
        for text in ("", "   ", "x" * 4097):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message=text, sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self.bridge.calls, [])

    def test_reply_refuses_group_chats_and_chat_ids_without_a_valid_suffix(self):
        for bad in ("120363012345678901@g.us", "5547999414105", "", "5547999414105@broadcast"):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.reply(self.paths, self.bridge, chat_id=bad, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self.bridge.calls, [])

    def test_reply_marks_takeover_when_the_lead_is_in_the_funnel(self):
        engine = FollowupEngine(self.paths.followups_db)
        self.assertFalse(engine.get_lead(LEAD)["takeover"])

        panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono")

        self.assertTrue(engine.get_lead(LEAD)["takeover"])

    def test_reply_does_not_break_when_contact_has_no_lead_in_the_funnel(self):
        chat_id = "5599988887777@s.whatsapp.net"
        result = panel_actions.reply(self.paths, self.bridge, chat_id=chat_id, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(result["chat_id"], chat_id)
        self.assertIsNone(FollowupEngine(self.paths.followups_db).get_lead(chat_id))


class ReplyMediaActionTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()

    def _send(self, **overrides):
        kwargs = dict(
            chat_id=LEAD, data=b"%PDF", file_name="exame.pdf", mime="application/pdf", caption="segue o exame",
            sent_by="Ana", sent_by_user="ana", owner_number=OWNER_DIGITS,
        )
        kwargs.update(overrides)
        return panel_actions.reply_media(self.paths, self.bridge, **kwargs)

    def test_sends_via_bridge_persists_media_key_and_cleans_the_outbox(self):
        result = self._send()
        self.assertEqual([c[0] for c in self.bridge.calls], ["/send-media", "/chat-silence"])
        call = self.bridge.calls[0][1]
        self.assertEqual((call["chatId"], call["mediaType"], call["fileName"], call["caption"], call["automation"]),
                         (LEAD, "document", "exame.pdf", "segue o exame", False))
        self.assertEqual(self.bridge.seen_files, [True])
        outbox = self.paths.messages_db.parent / "panel_outbox"
        self.assertEqual(list(outbox.iterdir()), [])
        conn = sqlite3.connect(self.paths.messages_db)
        row = conn.execute(
            "SELECT from_me, sender_name, message_type, body, has_media, media_type, media_key, media_mime, media_name"
            " FROM messages WHERE message_id=?", (result["message_id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(row, (1, "Ana", "documentMessage", "segue o exame", 1, "document",
                               f"media/x/{result['message_id']}.pdf", "application/pdf", "exame.pdf"))
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        bubble = next(b for i in detail["timeline"] if i["type"] == "message" for b in i["bubbles"] if b["message_id"] == result["message_id"])
        self.assertEqual(bubble["media"]["kind"], "document")

    def test_without_media_key_the_message_is_kept_without_media(self):
        self.bridge.media_response = {"success": True, "messageId": "sem-r2"}
        self._send()
        conn = sqlite3.connect(self.paths.messages_db)
        row = conn.execute("SELECT has_media, media_type, media_key FROM messages WHERE message_id='sem-r2'").fetchone()
        conn.close()
        self.assertEqual(row, (1, "document", None))

    def test_refuses_bad_input_before_touching_the_bridge(self):
        for overrides in (
            {"data": b""},
            {"data": b"x" * (panel_actions.MEDIA_MAX_BYTES + 1)},
            {"mime": "application/x-msdownload"},
            {"chat_id": "grupo@g.us"},
            {"caption": "x" * 4097},
        ):
            with self.assertRaises(panel_actions.ActionError):
                self._send(**overrides)
        self.assertEqual(self.bridge.calls, [])

    def test_refuses_blocked_contact_and_other_humans_attendance(self):
        with self.assertRaises(panel_actions.ActionError):
            self._send(chat_id=BLOCKED)
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="atendente", responsavel_user="bia", aberto_at=NOW, now=NOW)
        with self.assertRaises(panel_actions.Forbidden):
            self._send()
        self.assertEqual(self.bridge.calls, [])
        self._send(is_admin=True)
        self.assertEqual(self.bridge.calls[0][0], "/send-media")

    def test_bridge_failure_persists_nothing_and_removes_the_file(self):
        self.bridge.down = True
        conn = sqlite3.connect(self.paths.messages_db)
        before = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (LEAD,)).fetchone()[0]
        with self.assertRaises(panel_actions.ActionError):
            self._send()
        outbox = self.paths.messages_db.parent / "panel_outbox"
        self.assertEqual(list(outbox.iterdir()), [])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (LEAD,)).fetchone()[0], before)
        conn.close()


class ReplyAtendimentoTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()

    def _reply(self, user="ana", **kw):
        return panel_actions.reply(
            self.paths, self.bridge, chat_id=LEAD, message="Oi!", sent_by=user.title(), sent_by_user=user,
            owner_number=OWNER_DIGITS, **kw,
        )

    def test_resposta_sem_atendimento_aberto_nao_inventa_um(self):
        result = self._reply("ana")
        self.assertIsNone(result["atendimento"])
        self.assertIs(result["silenced"], True)
        self.assertEqual(self.bridge.calls[-1], ("/chat-silence", {"chatId": LEAD, "minutes": 10}))
        self.assertIsNone(atendimento_store.aberto_do_contato(self.paths.panel_db, LEAD))

    def test_resposta_sem_humano_assume_com_hold(self):
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="nenhum", aberto_at=NOW, now=NOW)
        result = self._reply("ana")
        atd = result["atendimento"]
        self.assertEqual((atd["responsavel_tipo"], atd["responsavel_user"]), ("atendente", "ana"))
        self.assertEqual((atd["primeira_resposta_autor"], atd["primeira_resposta_user"]), ("painel", "ana"))
        self.assertIs(result["silenced"], True)
        self.assertEqual([c for c in self.bridge.calls if c[0] == "/chat-silence"],
                         [("/chat-silence", {"chatId": LEAD, "hold": True, "reason": "painel"})])
        # Segunda resposta minha: sem novo evento de assunção.
        self._reply("ana")
        eventos = [e["tipo"] for e in atendimento_store.eventos(self.paths.panel_db, atd["id"])]
        self.assertEqual(eventos, ["aberto", "assumido"])

    def test_resposta_com_ia_responsavel_assume_e_registra_evento(self):
        aberto = atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        result = self._reply("ana")
        self.assertEqual(result["atendimento"]["responsavel_user"], "ana")
        self.assertEqual([e["tipo"] for e in atendimento_store.eventos(self.paths.panel_db, aberto["id"])], ["aberto", "assumido"])

    def test_resposta_em_atendimento_de_outro_humano_recusa_antes_de_enviar(self):
        aberto = atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="atendente",
                                         responsavel_user="bruno", aberto_at=NOW, now=NOW)
        with self.assertRaises(panel_actions.Forbidden):
            self._reply("ana")
        self.assertEqual(self.bridge.calls, [], "nada vai para a ponte")
        atendimento_store.definir_responsavel(self.paths.panel_db, aberto["id"], tipo="dono", user=None, ator="dono", evento="assumido", now=NOW)
        with self.assertRaises(panel_actions.Forbidden):
            self._reply("ana")
        # Admin passa por cima e o evento diz de quem tirou.
        result = self._reply("dono", is_admin=True)
        self.assertEqual(result["atendimento"]["responsavel_user"], "dono")
        self.assertEqual(atendimento_store.eventos(self.paths.panel_db, aberto["id"])[-1]["detalhe"], "do Dono")

    def test_hold_que_falha_vira_aviso_e_nao_desfaz_o_envio(self):
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        self.bridge.silence_down = True
        result = self._reply("ana")
        self.assertIsNone(result["silenced"])
        self.assertIn("silenciar", result["warning"])
        self.assertEqual(result["atendimento"]["responsavel_user"], "ana")


class AtendimentoActionsTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.paths = dataclasses.replace(self.paths, users_json=Path(self.tmp.name) / "panel_users.json")
        users_store.create_user(self.paths.users_json, username="bruno", name="Bruno", password="SenhaForte#2026", role="atendente")
        self.bridge = FakeBridge()
        self.aberto = atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)

    def test_assumir_e_fail_closed_no_hold(self):
        self.bridge.silence_down = True
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD, username="ana")
        self.assertEqual(atendimento_store.obter(self.paths.panel_db, self.aberto["id"])["responsavel_tipo"], "ia")
        self.bridge.silence_down = False
        result = panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD, username="ana")
        self.assertEqual(result["atendimento"]["responsavel_user"], "ana")
        self.assertEqual(self.bridge.calls[-1], ("/chat-silence", {"chatId": LEAD, "hold": True, "reason": "painel"}))
        with self.assertRaises(panel_actions.Forbidden):
            panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD, username="bruno")
        result = panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD, username="bruno", is_admin=True)
        self.assertEqual(result["atendimento"]["responsavel_user"], "bruno")
        self.assertEqual(atendimento_store.eventos(self.paths.panel_db, self.aberto["id"])[-1]["detalhe"], "de ana")
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD2, username="ana")

    def test_devolver_exige_ia_ligada_e_libera_o_bridge(self):
        panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD, username="ana")
        contacts = json.loads(self.paths.contacts_json.read_text())
        contacts[LEAD]["ai_enabled"] = False
        self.paths.contacts_json.write_text(json.dumps(contacts))
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.devolver(self.paths, self.bridge, chat_id=LEAD, username="ana")
        contacts[LEAD]["ai_enabled"] = True
        self.paths.contacts_json.write_text(json.dumps(contacts))
        with self.assertRaises(panel_actions.Forbidden):
            panel_actions.devolver(self.paths, self.bridge, chat_id=LEAD, username="bruno")
        result = panel_actions.devolver(self.paths, self.bridge, chat_id=LEAD, username="ana")
        self.assertEqual(result["atendimento"]["responsavel_tipo"], "ia")
        self.assertIs(result["silenced"], False)
        self.assertEqual(self.bridge.calls[-1], ("/chat-unsilence", {"chatId": LEAD}))

    def test_resolver_grava_mesmo_com_ponte_fora_e_avisa(self):
        panel_actions.assumir(self.paths, self.bridge, chat_id=LEAD, username="ana")
        self.bridge.down = True
        result = panel_actions.resolver(self.paths, self.bridge, chat_id=LEAD, username="ana")
        self.assertEqual(result["atendimento"]["status"], "resolvido")
        self.assertEqual(result["atendimento"]["resolvido_motivo"], "manual")
        self.assertIsNone(result["silenced"])
        self.assertIn("liberar", result["warning"])
        self.assertIsNone(atendimento_store.aberto_do_contato(self.paths.panel_db, LEAD))

    def test_reatribuir_para_atendente_ativo(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reatribuir(self.paths, self.bridge, chat_id=LEAD, para="ninguem", username="dono")
        result = panel_actions.reatribuir(self.paths, self.bridge, chat_id=LEAD, para="bruno", username="dono")
        self.assertEqual(result["atendimento"]["responsavel_user"], "bruno")
        evento = atendimento_store.eventos(self.paths.panel_db, self.aberto["id"])[-1]
        self.assertEqual((evento["tipo"], evento["ator"], evento["detalhe"]), ("reatribuido", "dono", "sem responsável para bruno"))
        self.assertEqual(self.bridge.calls[-1][0], "/chat-silence")


class IniciarActionTest(PanelFixture):
    NOVO = "5511988887777@s.whatsapp.net"

    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()

    def _iniciar(self, user="ana", **kw):
        kw.setdefault("message", "Olá! Tudo bem?")
        return panel_actions.iniciar(
            self.paths, self.bridge, sent_by=user.title(), sent_by_user=user,
            owner_number=OWNER_DIGITS, **kw,
        )

    def test_numero_novo_cria_contato_e_abre_atendimento_com_hold(self):
        result = self._iniciar(phone="11 98888-7777", name="Novo Cliente")
        self.assertTrue(result["contact_created"])
        self.assertEqual(result["chat_id"], self.NOVO)
        self.assertIs(result["silenced"], True)
        self.assertEqual(self.bridge.calls[-1], ("/chat-silence", {"chatId": self.NOVO, "hold": True, "reason": "painel"}))
        atd = result["atendimento"]
        self.assertEqual((atd["responsavel_tipo"], atd["responsavel_user"]), ("atendente", "ana"))
        eventos = [e["tipo"] for e in atendimento_store.eventos(self.paths.panel_db, atd["id"])]
        self.assertEqual(eventos, ["aberto", "iniciado"])
        contacts = contacts_store.read_contacts(self.paths.contacts_json)
        self.assertEqual(contacts[self.NOVO]["name"], "Novo Cliente")
        self.assertEqual(contacts[self.NOVO]["relationship"], "Cliente")
        self.assertEqual(contacts[self.NOVO]["source"], "painel")
        self.assertEqual(contacts[self.NOVO]["created_by"], "ana")

    def test_numero_fora_do_whatsapp_recusa_antes_do_envio(self):
        self.bridge.number_exists = False
        with self.assertRaisesRegex(panel_actions.ActionError, "não está no WhatsApp"):
            self._iniciar(phone="11 98888-7777", name="Novo Cliente")
        self.assertEqual([c for c in self.bridge.calls if c[0] == "/send"], [])
        self.assertIsNone(atendimento_store.aberto_do_contato(self.paths.panel_db, self.NOVO))

    def test_numero_novo_usa_o_jid_canonico_da_ponte(self):
        # Conta BR antiga: o WhatsApp responde sem o nono dígito.
        self.bridge.number_jid = "551188887777@s.whatsapp.net"
        result = self._iniciar(phone="11 98888-7777", name="Novo Cliente")
        self.assertEqual(result["chat_id"], "551188887777@s.whatsapp.net")
        self.assertIn("551188887777@s.whatsapp.net", contacts_store.read_contacts(self.paths.contacts_json))

    def test_ponte_antiga_sem_number_exists_segue_com_o_numero_digitado(self):
        self.bridge.number_exists = None
        result = self._iniciar(phone="11 98888-7777", name="Novo Cliente")
        self.assertEqual(result["chat_id"], self.NOVO)

    def test_numero_novo_sem_nome_recusa(self):
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(phone="11988887777", name="")
        self.assertEqual(self.bridge.calls, [])
        self.assertNotIn(self.NOVO, contacts_store.read_contacts(self.paths.contacts_json))

    def test_contato_existente_sem_atendimento_abre_sem_recadastrar(self):
        result = self._iniciar(chat_id=LEAD)
        self.assertFalse(result["contact_created"])
        contacts = contacts_store.read_contacts(self.paths.contacts_json)
        self.assertEqual(contacts[LEAD]["name"], "Mariana Lopes")
        self.assertIsNotNone(result["atendimento"])
        self.assertEqual(result["atendimento"]["responsavel_user"], "ana")

    def test_contato_bloqueado_recusa_antes_do_bridge(self):
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(chat_id=BLOCKED)
        self.assertEqual(self.bridge.calls, [])

    def test_atendimento_de_outro_humano_recusa_antes_do_bridge(self):
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="atendente",
                                 responsavel_user="bruno", aberto_at=NOW, now=NOW)
        with self.assertRaises(panel_actions.Forbidden):
            self._iniciar(chat_id=LEAD)
        self.assertEqual(self.bridge.calls, [])

    def test_bridge_sem_message_id_nao_persiste_mensagem_nem_atendimento_mas_contato_fica_criado(self):
        self.bridge.send_response = {"success": True, "info": "blocked"}
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(phone="11988887777", name="Novo Cliente")
        self.assertIn(self.NOVO, contacts_store.read_contacts(self.paths.contacts_json))
        self.assertIsNone(atendimento_store.aberto_do_contato(self.paths.panel_db, self.NOVO))

    def test_limite_diario(self):
        result = self._iniciar(phone="11988887777", name="Cliente 1", daily_limit=1)
        self.assertIsNotNone(result["atendimento"])
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(phone="11988880000", name="Cliente 2", daily_limit=1)
        # Admin também respeita o limite.
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(phone="11988880001", name="Cliente 3", daily_limit=1, is_admin=True)

    def test_numero_do_dono_e_grupo_recusados(self):
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(phone=OWNER_DIGITS, name="Dono")
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(chat_id="120363012345678901@g.us")
        self.assertEqual(self.bridge.calls, [])

    def test_telefone_malformado_recusa(self):
        for ruim in ("123", "11999", "abcdefghijk"):
            with self.assertRaises(panel_actions.ActionError):
                self._iniciar(phone=ruim, name="Cliente")
        self.assertEqual(self.bridge.calls, [])

    def test_telefone_internacional_com_mais_vai_sem_regra_de_ddd(self):
        result = self._iniciar(phone="+351 912 345 678", name="Cliente PT")
        self.assertEqual(result["chat_id"], "351912345678@s.whatsapp.net")
        for ruim in ("+1 234", "+0123456789", "+55 999"):
            with self.assertRaises(panel_actions.ActionError):
                self._iniciar(phone=ruim, name="Cliente")

    def test_chat_id_e_phone_juntos_ou_nenhum_recusam(self):
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar(chat_id=LEAD, phone="11988887777")
        with self.assertRaises(panel_actions.ActionError):
            self._iniciar()

    def test_atendente_esta_na_lista_de_acoes_permitidas(self):
        self.assertIn("atendimento/iniciar", panel_server.ATTENDANT_ACTIONS)


class BridgeActionsTest(unittest.TestCase):
    def test_pause_and_silence_go_through_the_bridge(self):
        bridge = FakeBridge()
        self.assertEqual(panel_actions.pause(bridge, paused=True), {"paused": True})
        self.assertEqual(panel_actions.silence(bridge, chat_id=LEAD, minutes=20)["time_left_s"], 600)
        self.assertEqual(panel_actions.unsilence(bridge, chat_id=LEAD)["silenced"], False)
        self.assertEqual([c[0] for c in bridge.calls], ["/bot-pause", "/chat-silence", "/chat-unsilence"])
        self.assertEqual(bridge.calls[1][1], {"chatId": LEAD, "minutes": 20})
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.pause(bridge, paused="sim")
        bridge.down = True
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.pause(bridge, paused=False)

    def test_whatsapp_settings_are_validated_before_reaching_the_bridge(self):
        bridge = FakeBridge()
        result = panel_actions.whatsapp_settings(
            bridge, reject_calls=True, groups_enabled=False, debounce_seconds=12,
        )
        self.assertEqual(result, {
            "reject_calls": True, "groups_enabled": False, "debounce_seconds": 12, "save_client_media": False,
            "save_profile_photos": False,
        })
        self.assertEqual(bridge.calls[-1], ("/runtime-settings", {
            "rejectCalls": True, "groupsEnabled": False, "debounceInitialMs": 12000, "saveClientMedia": False,
            "saveProfilePhotos": False,
        }))
        self.assertTrue(panel_actions.whatsapp_settings(
            bridge, reject_calls=True, groups_enabled=False, debounce_seconds=12, save_profile_photos=True,
        )["save_profile_photos"])
        self.assertTrue(panel_actions.whatsapp_settings(
            bridge, reject_calls=True, groups_enabled=False, debounce_seconds=12, save_client_media=True,
        )["save_client_media"])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.whatsapp_settings(
                bridge, reject_calls=True, groups_enabled=False, debounce_seconds=12, save_client_media="sim",
            )
        for seconds in (-1, 1, 61, "oito"):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.whatsapp_settings(
                    bridge, reject_calls=True, groups_enabled=False, debounce_seconds=seconds,
                )
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.whatsapp_settings(
                bridge, reject_calls="sim", groups_enabled=False, debounce_seconds=8,
            )


class LiveServerFixture(PanelFixture):
    """Sobe o painel real numa porta livre contra os bancos temporários."""
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        config = panel_server.Config(
            username="dono", password="segredo-forte", bridge_url="http://127.0.0.1:1",
            bridge_host_header="", minutes_per_resolved=6, hourly_rate_brl=38, owner_number=OWNER_DIGITS,
            hermes_dashboard_url="http://127.0.0.1:1", whatsapp_mode="bot", whatsapp_allowed_users="*",
            google_client_id="", google_client_secret="", public_url="",
        )
        handler = panel_server.make_handler(config, self.paths, self.bridge)
        self.httpd = panel_server.PanelServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def _post(self, path, body, auth="dono:segredo-forte", raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            try:
                return exc.code, json.loads(raw_body or b"{}")
            except ValueError:
                return exc.code, {"text": raw_body.decode("utf-8", "replace")}

    def _get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        req.add_header("Authorization", "Basic " + base64.b64encode(b"dono:segredo-forte").decode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")


class ActionRoutesTest(LiveServerFixture):
    def test_routes_require_auth_and_validate(self):
        self.assertEqual(self._post("/api/actions/pause", {"paused": True}, auth=None)[0], 401)
        self.assertEqual(self._post("/api/actions/nada", {})[0], 404)
        self.assertEqual(self._post("/api/outra", {})[0], 404)
        status, body = self._post("/api/actions/stage", {}, raw=b"{nao json")
        self.assertEqual((status, body["error"]), (400, "bad_request"))
        status, body = self._post("/api/actions/stage", {"chat_id": LEAD, "stage": "ganho"})
        self.assertEqual((status, body["error"]), (400, "rejected"))

    def test_routes_apply_actions(self):
        status, body = self._post("/api/actions/block", {"query": "rafael"})
        self.assertEqual(status, 200)
        self.assertEqual(body["chat_id"], LEAD2)
        status, body = self._post("/api/actions/unblock", {"chat_id": LEAD2})
        self.assertTrue(body["pending_reset"])
        status, body = self._post("/api/actions/stage", {"chat_id": LEAD, "stage": "payment"})
        self.assertEqual(body["lead"]["stage"], "payment")
        status, body = self._post("/api/actions/value", {"chat_id": LEAD, "value_brl": "4.800,00"})
        self.assertEqual((status, body["estimated_value_cents"]), (200, 480_000))
        status, body = self._post("/api/actions/followup", {"chat_id": LEAD, "action": "pause"})
        self.assertFalse(body["automation_enabled"])
        status, body = self._post("/api/actions/pause", {"paused": True})
        self.assertEqual((status, body["paused"]), (200, True))
        self.assertEqual(self.bridge.calls[-1], ("/bot-pause", {"paused": True}))
        status, body = self._get("/api/whatsapp-settings")
        self.assertEqual((status, body["known"], body["debounce_seconds"]), (200, True, 8))
        status, body = self._post("/api/actions/whatsapp-settings", {
            "reject_calls": True, "groups_enabled": False, "debounce_seconds": 10,
        })
        self.assertEqual((status, body["reject_calls"], body["debounce_seconds"]), (200, True, 10))

    def test_rotas_de_atendimento(self):
        # A fixture tem mensagens de 8 dias atrás (fora da janela de bootstrap) e a rota
        # reconcilia com a hora real; abre-se direto no store, agora, para a rota listar.
        agora = datetime.now(timezone.utc)
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="ia", aberto_at=agora, now=agora)
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD2, responsavel_tipo="ia", aberto_at=agora, now=agora)
        status, body = self._get("/api/atendimentos?fila=todos")
        self.assertEqual(status, 200)
        self.assertEqual(body["fila"], "todos")
        self.assertEqual({i["contato"] for i in body["itens"]}, {LEAD, LEAD2})
        self.assertIn("com_ia", body["contagens"])
        self.assertFalse(body["bot_paused"])
        rev = body["rev"]
        status, body = self._get("/api/atendimentos?fila=x")
        self.assertEqual(status, 400)

        status, body = self._post("/api/actions/atendimento/assumir", {"chat_id": LEAD})
        self.assertEqual((status, body["atendimento"]["responsavel_user"]), (200, "dono"))
        status, body = self._get(f"/api/atendimentos?fila=meus&desde_rev={rev}")
        self.assertEqual([i["contato"] for i in body["itens"]], [LEAD])

        status, body = self._get("/api/lead/" + LEAD)
        self.assertEqual(status, 200)
        self.assertEqual(body["atendimento"]["responsavel_user"], "dono")
        self.assertEqual([e["tipo"] for e in body["atendimento"]["eventos"]], ["aberto", "assumido"])
        self.assertEqual(body["atendimento"]["sla"]["primeira"]["alvo_min"], 15)
        self.assertFalse(body["atendimento"]["sla"]["resolucao"]["estourado"])
        self.assertEqual(len(body["atendimentos"]), 1)

        status, body = self._post("/api/actions/atendimento/reatribuir", {"chat_id": LEAD, "para": "ninguem"})
        self.assertEqual((status, body["error"]), (400, "rejected"))
        status, body = self._post("/api/actions/atendimento/devolver", {"chat_id": LEAD})
        self.assertEqual((status, body["atendimento"]["responsavel_tipo"]), (200, "ia"))
        status, body = self._post("/api/actions/atendimento/resolver", {"chat_id": LEAD})
        self.assertEqual((status, body["atendimento"]["status"]), (200, "resolvido"))
        status, body = self._post("/api/actions/atendimento/resolver", {"chat_id": LEAD})
        self.assertEqual((status, body["error"]), (400, "rejected"))

    def test_route_reply_sends_authenticates_and_validates(self):
        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": "Oi!"}, auth=None)
        self.assertEqual(status, 401)

        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": "Oi!"}, raw=b"{nao json")
        self.assertEqual((status, body["error"]), (400, "bad_request"))

        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": "Oi!"})
        self.assertEqual(status, 200)
        self.assertEqual(body["chat_id"], LEAD)
        self.assertEqual(body["sent_by"], "dono")
        self.assertIs(body["silenced"], True)
        self.assertEqual(self.bridge.calls[0][0], "/send")

        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": ""})
        self.assertEqual((status, body["error"]), (400, "rejected"))


if __name__ == "__main__":
    unittest.main()
