"""Leitores do painel contra fixtures dos três bancos, do JSON e do log."""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import history_store  # noqa: E402
from commercial_followups import FollowupEngine  # noqa: E402
from panel import data as panel_data  # noqa: E402
from panel import server as panel_server  # noqa: E402

LEAD = "5547999414105@s.whatsapp.net"
LEAD_LID = "236344165040241@lid"
LEAD2 = "5511952134536@s.whatsapp.net"
BLOCKED = "5562981151308@s.whatsapp.net"
OWNER = "5547999414100@s.whatsapp.net"
# Segunda-feira 10:00 em São Paulo — dentro do horário comercial do módulo de follow-up.
NOW = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
TODAY = NOW.astimezone(panel_data.daily_audit.business_tz()).date()


class PanelFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="whatsaya-panel-test-")
        root = Path(self.tmp.name)
        self.paths = panel_data.Paths(
            contacts_json=root / "personal_contacts.json",
            messages_db=root / "whatsapp_messages.db",
            followups_db=root / "commercial_followups.db",
            state_db=root / "state.db",
            plugin_log=root / "whatsapp_plugin.log",
            gateway_log=root / "gateway.log",
            pricing_json=root / "pricing.json",
            panel_db=root / "panel.db",
        )
        panel_data._DAY_CACHE.clear()
        self._write_contacts()
        self._write_messages()
        self._write_followups()
        self._write_state()
        self._write_logs()
        self.paths.pricing_json.write_text(json.dumps({
            "usd_brl": 5.0,
            "models": {"gpt-5.6-terra": {"input": 2.0, "cached_input": 0.5, "output": 8.0}},
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_contacts(self):
        self.paths.contacts_json.write_text(json.dumps({
            LEAD: {"name": "Mariana Lopes", "lid": LEAD_LID, "blocked": False, "ai_enabled": True},
            LEAD_LID: {"name": "Mariana Lopes", "blocked": False, "ai_enabled": True},
            LEAD2: {"name": "Rafael Nunes", "blocked": False, "ai_enabled": True},
            BLOCKED: {"name": "Ofertas Consórcio", "blocked": True, "ai_disabled_reason": "spam"},
            "corrompido@s.whatsapp.net": "texto solto",
        }), encoding="utf-8")

    def _write_messages(self):
        conn = history_store.connect(str(self.paths.messages_db))
        history_store.ensure_schema(conn)
        t0 = NOW.timestamp()
        rows = [
            (LEAD, LEAD, "Mariana", "m1", "text", "Queria saber como funciona a avaliação para implante.", t0 - 3600, 0),
            (LEAD, "bot", "AYA", "m2", "text", "Oi, Mariana! Claro. Você está buscando o implante para você?", t0 - 3500, 1),
            (LEAD, LEAD, "Mariana", "m3", "text", "Quinta. Vocês dão algum desconto?", t0 - 1800, 0),
            (LEAD2, LEAD2, "Rafael", "m4", "text", "Vocês fazem faceta? Quanto fica?", t0 - 900, 0),
            (LEAD2, "bot", "AYA", "m5", "text", "Fazemos sim. Me conta qual a sua expectativa?", t0 - 800, 1),
            (BLOCKED, BLOCKED, "Spam", "m6", "text", "Consórcio contemplado!", t0 - 600, 0),
        ]
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()

    def _write_followups(self):
        engine = FollowupEngine(self.paths.followups_db)
        earlier = NOW - timedelta(hours=2)
        engine.configure_lead(
            LEAD, automation_enabled=True, stage="pricing", cadence_kind="silence",
            context_kind="question", context_fact="parcelamento em 12x",
            context_source_message_id="m3", context_verified=True, now=earlier,
        )
        engine.note_outbound(LEAD, message_id="out-1", at=earlier)
        engine.configure_lead(
            LEAD2, automation_enabled=True, stage="new", cadence_kind="silence",
            context_kind="question", context_fact="o valor da faceta",
            context_source_message_id="m4", context_verified=True, now=earlier,
        )
        engine.note_outbound(LEAD2, message_id="out-2", at=earlier)
        # Primeiro toque da Mariana já saiu há 1 h e ela respondeu 20 min depois.
        con = sqlite3.connect(self.paths.followups_db)
        sent_at = (NOW - timedelta(hours=1)).isoformat()
        replied_at = (NOW - timedelta(minutes=40)).isoformat()
        con.execute(
            "UPDATE followup_jobs SET status='sent', updated_utc=?, bridge_message_id='fu-1'"
            " WHERE chat_id=? AND step_no=1", (sent_at, LEAD),
        )
        con.execute("UPDATE lead_state SET last_inbound_utc=? WHERE chat_id=?", (replied_at, LEAD))
        # Toque 1 do Rafael foi cancelado porque ele respondeu antes.
        con.execute(
            "UPDATE followup_jobs SET status='cancelled', last_error='lead_replied', updated_utc=?"
            " WHERE chat_id=? AND step_no=1", (sent_at, LEAD2),
        )
        con.commit()
        con.close()

    def _write_state(self):
        con = sqlite3.connect(self.paths.state_db)
        con.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, user_id TEXT, started_at REAL);"
            "CREATE TABLE session_model_usage (session_id TEXT, model TEXT, billing_provider TEXT,"
            " billing_base_url TEXT, billing_mode TEXT, task TEXT, api_call_count INTEGER,"
            " input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,"
            " cache_write_tokens INTEGER, reasoning_tokens INTEGER, estimated_cost_usd REAL,"
            " actual_cost_usd REAL, cost_status TEXT, cost_source TEXT, first_seen REAL, last_seen REAL);"
        )
        seen = NOW.timestamp() - 600
        con.execute("INSERT INTO sessions VALUES ('s1', 'whatsapp', ?, ?)", (LEAD, seen))
        con.execute("INSERT INTO sessions VALUES ('s2', 'whatsapp', ?, ?)", (LEAD2, seen))
        con.execute("INSERT INTO sessions VALUES ('s3', 'cli', NULL, ?)", (seen,))
        usage = [
            ("s1", "gpt-5.6-terra", "openai-codex", "", "subscription_included", "", 2, 10_000, 1_000, 4_000, 0, 500, 0.0, 0.0, "included", "none", seen, seen),
            ("s2", "deepseek/deepseek-v4-flash", "openrouter", "", "api_key", "", 1, 5_000, 400, 0, 0, 0, 0.0031, None, "estimated", "openrouter", seen, seen),
            ("s3", "gpt-5.6-terra", "openai-codex", "", "subscription_included", "", 9, 99_000, 9_000, 0, 0, 0, 0.0, 0.0, "included", "none", seen, seen),
        ]
        con.executemany("INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", usage)
        con.commit()
        con.close()

    def _write_logs(self):
        tz = panel_data.daily_audit.business_tz()
        stamp = lambda minutes: (NOW - timedelta(minutes=minutes)).astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")
        lines = [
            f"{stamp(58)} INFO [whatsapp-manager] [human-send] chat={LEAD!r} bubbles=1 sizes=[62] status=ok",
            f"{stamp(40)} INFO [whatsapp-manager] [handoff] dono avisado sobre {LEAD!r} motivo='pediu desconto' message_id='m3'",
            f"{stamp(13)} INFO [whatsapp-manager] [human-send] chat={LEAD2!r} bubbles=1 sizes=[45] status=ok",
            f"{stamp(5)} WARNING [whatsapp-manager] [inbound-watchdog] chat={LEAD2!r} message_id='m4' esperando=190s preview='Vocês fazem faceta?'",
        ]
        self.paths.plugin_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        gw = (NOW - timedelta(minutes=57)).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        self.paths.gateway_log.write_text(
            f"{gw},123 INFO gateway.run: response ready: platform=whatsapp chat={LEAD} time=4.2s api_calls=2\n",
            encoding="utf-8",
        )


class BlockedAndLeadsTest(PanelFixture):
    def test_blocked_contacts_lists_only_blocked_dict_records(self):
        blocked = panel_data.blocked_contacts(panel_data.load_contacts(self.paths.contacts_json))
        self.assertEqual([b["name"] for b in blocked], ["Ofertas Consórcio"])
        self.assertEqual(blocked[0]["phone"], "+55 62 9 8115-1308")
        self.assertEqual(blocked[0]["reason"], "spam")

    def test_blocked_phone_and_its_lid_mirror_are_one_row_with_readable_reason(self):
        contacts = panel_data.load_contacts(self.paths.contacts_json)
        contacts[LEAD]["blocked"] = True
        contacts[LEAD]["ai_disabled_reason"] = "legacy_sync_not_in_flow"
        contacts[LEAD_LID]["blocked"] = True
        contacts["777@lid"] = {"name": "Sem telefone", "blocked": True, "ai_disabled_reason": "personal_contact"}
        rows = panel_data.blocked_contacts(contacts)
        self.assertEqual([r["name"] for r in rows], ["Mariana Lopes", "Ofertas Consórcio", "Sem telefone"])
        self.assertEqual(rows[0]["reason"], "sync antigo, fora do fluxo")
        self.assertEqual(rows[2]["reason"], "contato pessoal")

    def test_lid_mirror_from_bridge_map_collapses_into_one_row(self):
        # Nenhum dos dois registros declara o campo `lid` — como em produção. Só o
        # mapa lidToPhone do bridge liga o espelho ao telefone.
        contacts = {
            "236344165040241@lid": {"name": "Contato 5511952134536", "blocked": True,
                                    "ai_disabled_reason": "legacy_sync_not_in_flow"},
            LEAD2: {"name": "5511952134536", "blocked": True, "ai_disabled_reason": "legacy_sync_not_in_flow"},
            "52536241344735@lid": {"name": "Ksksksksksks", "blocked": True},
            LEAD: {"name": "Schmidt", "blocked": True},
        }
        lid_map = {"236344165040241": "5511952134536", "52536241344735": "5547999414105"}
        rows = panel_data.blocked_contacts(contacts, lid_map)
        self.assertEqual(len(rows), 2, rows)
        by_phone = {r["phone"]: r for r in rows}
        # Placeholder dos dois lados: a linha cai para o telefone formatado.
        self.assertEqual(by_phone["+55 11 9 5213-4536"]["name"], "+55 11 9 5213-4536")
        self.assertEqual(by_phone["+55 47 9 9941-4105"]["chat_id"], LEAD, "a identidade é a do telefone")
        self.assertEqual(by_phone["+55 47 9 9941-4105"]["name"], "Schmidt", "nome do telefone vence o do espelho")

    def test_lid_only_contact_shows_the_resolved_phone(self):
        contacts = {"137915879399568@lid": {"name": "Izabella Freitas", "blocked": True,
                                            "ai_disabled_reason": "personal_contact"}}
        rows = panel_data.blocked_contacts(contacts, {"137915879399568": "556282779115"})
        self.assertEqual(rows[0]["phone"], "+55 62 8277-9115")
        self.assertEqual(rows[0]["reason"], "contato pessoal")
        # Sem o mapa não há como resolver: a linha continua existindo, sem inventar número.
        rows = panel_data.blocked_contacts(contacts, {})
        self.assertEqual(rows[0]["phone"], "identidade LID")

    def test_leads_grouped_by_stage_with_name_preview_and_next_followup(self):
        FollowupEngine(self.paths.followups_db).set_estimated_value(LEAD, 480_000, now=NOW)
        board = panel_data.leads(self.paths, now=NOW)
        by_stage = {col["id"]: col["cards"] for col in board["stages"]}
        self.assertEqual([c["name"] for c in by_stage["pricing"]], ["Mariana Lopes"])
        self.assertEqual([c["name"] for c in by_stage["new"]], ["Rafael Nunes"])
        mariana = by_stage["pricing"][0]
        self.assertEqual(mariana["preview"], "Quinta. Vocês dão algum desconto?")
        self.assertEqual(mariana["last"], "há 30 min")
        self.assertTrue(mariana["next_followup"].startswith(("hoje", "amanhã")), mariana["next_followup"])
        self.assertEqual(mariana["cadence"], "Silêncio")
        self.assertEqual(mariana["estimated_value_cents"], 480_000)
        self.assertEqual(board["total"], 2)

    def test_blocked_lead_never_appears_on_the_board(self):
        engine = FollowupEngine(self.paths.followups_db)
        engine.note_inbound(BLOCKED, message_id="m6", at=NOW)
        board = panel_data.leads(self.paths, now=NOW)
        self.assertNotIn(BLOCKED, [c["chat_id"] for col in board["stages"] for c in col["cards"]])


class ContactsAtendimentoTest(PanelFixture):
    def test_diretorio_le_o_atendimento_aberto(self):
        import atendimento_store
        atendimento_store.abrir(self.paths.panel_db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW, ultima_msg_autor="contato")
        b = atendimento_store.abrir(self.paths.panel_db, contato=LEAD2, responsavel_tipo="nenhum", aberto_at=NOW, now=NOW)
        atendimento_store.definir_responsavel(self.paths.panel_db, b["id"], tipo="atendente", user="ana", ator="ana", evento="assumido", now=NOW)
        data = panel_data.contacts_directory(self.paths, owner_number="5547999414100", now=NOW)
        rows = {row["chat_id"]: row for row in data["contacts"]}
        self.assertEqual(rows[LEAD]["atendimento"], {"protocolo": "20260907-001", "responsavel_tipo": "ia", "responsavel_user": None, "responsavel_nome": None, "aguardando_nos": True})
        self.assertFalse(rows[LEAD]["human"])
        self.assertEqual(rows[LEAD2]["atendimento"]["responsavel_user"], "ana")
        self.assertEqual(rows[LEAD2]["atendimento"]["responsavel_nome"], "ana", "sem cadastro, o username")
        self.assertTrue(rows[LEAD2]["human"], "humano vem do atendimento, não do takeover do funil")
        self.assertIsNone(rows[BLOCKED]["atendimento"])
        self.assertEqual((data["counts"]["aya"], data["counts"]["human"], data["counts"]["sem_responsavel"]), (1, 1, 0))


class FollowupsTest(PanelFixture):
    def test_queue_renders_real_copy_with_the_verified_fact(self):
        result = panel_data.followups(self.paths, "7d", now=NOW)
        queue = {(q["name"], q["step"]): q for q in result["queue"]}
        self.assertIn(("Mariana Lopes", 2), queue)
        self.assertIn("parcelamento em 12x", queue[("Mariana Lopes", 2)]["text"])
        self.assertEqual(queue[("Mariana Lopes", 2)]["cadence"], "Silêncio")
        self.assertEqual(queue[("Mariana Lopes", 2)]["stage"], "Preço")
        self.assertFalse(queue[("Mariana Lopes", 2)]["paused"])
        self.assertTrue(all(q["due"] for q in result["queue"]))

    def test_history_marks_reply_after_send_and_cancel_reason(self):
        result = panel_data.followups(self.paths, "7d", now=NOW)
        by_name = {(h["name"], h["step"]): h for h in result["history"]}
        self.assertEqual(by_name[("Mariana Lopes", 1)]["kind"], "replied")
        self.assertEqual(by_name[("Mariana Lopes", 1)]["result"], "Respondeu em 20 min")
        self.assertEqual(by_name[("Rafael Nunes", 1)]["result"], "Cancelado: lead respondeu antes")
        self.assertEqual(result["stats"], {"sent": 1, "replied": 1, "cancelled": 1, "cancelled_replied": 1})
        silence = next(c for c in result["cadences"] if c["id"] == "silence")
        self.assertEqual((silence["sent"], silence["replied"], silence["rate"]), (1, 1, 100))
        self.assertEqual(silence["steps"], "30 min · 1 d · 3 d úteis")

    def test_paused_lead_shows_as_paused_in_queue(self):
        FollowupEngine(self.paths.followups_db).configure_lead(LEAD2, automation_enabled=False, now=NOW)
        result = panel_data.followups(self.paths, "7d", now=NOW)
        # Desligar a automação cancela os jobs abertos do lead: a fila fica só com a Mariana.
        self.assertEqual({q["name"] for q in result["queue"]}, {"Mariana Lopes"})


class LeadMediaTest(PanelFixture):
    def _store_media(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.execute(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me,"
            " has_media, media_type, media_key, media_mime, media_name, media_size)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (LEAD_LID, LEAD_LID, "Mariana", "m7", "imageMessage", "", NOW.timestamp() - 100, 0,
             1, "image", "media/1/m7.jpg", "image/jpeg", None, 4096),
        )
        conn.execute(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me,"
            " has_media, media_type, media_key, media_mime, media_name, media_size)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (LEAD, LEAD, "Mariana", "m8", "documentMessage", "segue o exame", NOW.timestamp() - 50, 0,
             1, "document", "media/1/m8.pdf", "application/pdf", "exame.pdf", 90000),
        )
        conn.commit()
        conn.close()

    def test_bubble_carries_media_and_keeps_caption_only_as_body(self):
        self._store_media()
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        bubbles = {b["message_id"]: b for item in detail["timeline"] if item["type"] == "message" for b in item["bubbles"]}
        image = bubbles["m7"]
        self.assertEqual(image["body"], "")
        self.assertEqual(image["media"]["kind"], "image")
        self.assertEqual(image["media"]["url"], "/api/media/m7")
        doc = bubbles["m8"]
        self.assertEqual(doc["body"], "segue o exame")
        self.assertEqual(doc["media"], {
            "url": "/api/media/m8", "kind": "document", "mime": "application/pdf", "name": "exame.pdf", "size": 90000,
        })
        # Mídia antiga sem chave continua com o placeholder de sempre.
        self.assertNotIn("media", bubbles["m1"])

    def test_media_tab_crosses_lid_and_phone_newest_first(self):
        self._store_media()
        items = panel_data.lead_media(self.paths, LEAD)
        self.assertEqual([i["message_id"] for i in items], ["m8", "m7"])
        self.assertEqual(items[1]["kind"], "image")
        self.assertEqual(panel_data.lead_media(self.paths, LEAD2), [])

    def test_media_lookup_finds_key_and_chat_for_the_redirect(self):
        self._store_media()
        found = panel_data.media_lookup(self.paths.messages_db, "m7")
        self.assertEqual((found["chat_id"], found["media_key"]), (LEAD_LID, "media/1/m7.jpg"))
        self.assertIsNone(panel_data.media_lookup(self.paths.messages_db, "m1"))
        self.assertIsNone(panel_data.media_lookup(self.paths.messages_db, ""))

    def test_media_kind_prefers_mime_then_message_type(self):
        self.assertEqual(panel_data.media_kind("audio/ogg; codecs=opus"), "audio")
        self.assertEqual(panel_data.media_kind("", "ptt"), "audio")
        self.assertEqual(panel_data.media_kind("application/octet-stream", "video"), "video")
        self.assertEqual(panel_data.media_kind("", ""), "document")


class AvatarUrlTest(PanelFixture):
    def test_avatar_url_resolves_by_any_alias_and_is_absent_without_photo(self):
        avatars = {panel_data._digits(LEAD): "avatars/x.jpg"}
        self.assertEqual(panel_data.avatar_url(avatars, LEAD_LID, LEAD), "/api/avatar/" + panel_data._digits(LEAD))
        self.assertIsNone(panel_data.avatar_url(avatars, LEAD2))
        self.assertIsNone(panel_data.avatar_url(None, LEAD))
        self.assertIsNone(panel_data.avatar_url({}, ""))

    def test_directory_and_detail_carry_avatar_url(self):
        avatars = {panel_data._digits(LEAD): "avatars/x.jpg"}
        rows = panel_data.contacts_directory(self.paths, now=NOW, avatars=avatars)["contacts"]
        by_id = {r["chat_id"]: r for r in rows}
        self.assertEqual(by_id[LEAD]["avatar_url"], f"/api/avatar/{panel_data._digits(LEAD)}")
        self.assertIsNone(by_id[LEAD2]["avatar_url"])
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW, avatars=avatars)
        self.assertEqual(detail["avatar_url"], f"/api/avatar/{panel_data._digits(LEAD)}")
        self.assertIsNone(panel_data.lead_detail(self.paths, LEAD, now=NOW)["avatar_url"])


class LeadDetailTest(PanelFixture):
    def test_live_outbound_without_send_log_does_not_claim_aya_authorship(self):
        chat_id = "5521988887777@s.whatsapp.net"
        conn = sqlite3.connect(self.paths.messages_db)
        conn.execute(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (chat_id, OWNER, "Equipe", "live-human-send", "text", "Mensagem enviada pelo celular", NOW.timestamp() - 120, 1),
        )
        conn.commit()
        conn.close()

        detail = panel_data.lead_detail(self.paths, chat_id, now=NOW)
        message = next(item for item in detail["timeline"] if item["type"] == "message")
        self.assertEqual(message["owner"], "outbound")

    def test_historical_outbound_does_not_claim_aya_authorship(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.execute(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me, is_historical)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (LEAD, OWNER, "Equipe", "old-human-send", "text", "Mensagem antiga da equipe", NOW.timestamp() - 100000, 1, 1),
        )
        conn.commit()
        conn.close()

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        owner = next(
            item["owner"] for item in detail["timeline"] if item["type"] == "message"
            for bubble in item["bubbles"] if bubble["message_id"] == "old-human-send"
        )
        self.assertEqual(owner, "outbound")

    def test_conversation_crosses_days_in_chronological_order(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me, is_historical)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (LEAD, LEAD, "Mariana", "old-live", "text", "Mensagem de ontem", NOW.timestamp() - 90000, 0, 0),
                (LEAD, LEAD, "Mariana", "old-import", "text", "Importada do histórico", NOW.timestamp() - 100000, 0, 1),
            ],
        )
        conn.commit()
        conn.close()

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        bodies = [bubble["body"] for item in detail["timeline"] if item["type"] == "message" for bubble in item["bubbles"]]
        # A importação histórica entra na timeline, antes das mensagens vivas e
        # marcada como historical (painel do template, diretório de contatos).
        self.assertEqual(
            bodies,
            [
                "Importada do histórico",
                "Mensagem de ontem",
                "Queria saber como funciona a avaliação para implante.",
                "Oi, Mariana! Claro. Você está buscando o implante para você?",
                "Quinta. Vocês dão algum desconto?",
            ],
        )

    def test_owner_and_aya_are_split_from_logs_across_days(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (LEAD, "bot", "AYA", "aya-yesterday", "text", "A" * 21, NOW.timestamp() - 90000, 1),
                (LEAD, OWNER, "Dono", "owner-yesterday", "text", "D" * 29, NOW.timestamp() - 89900, 1),
            ],
        )
        conn.commit()
        conn.close()
        yesterday = (NOW - timedelta(seconds=90000)).astimezone(panel_data.daily_audit.business_tz())
        with self.paths.plugin_log.open("a", encoding="utf-8") as log:
            log.write(
                f"{yesterday.strftime('%Y-%m-%dT%H:%M:%S')} INFO [whatsapp-manager] "
                f"[human-send] chat={LEAD!r} bubbles=1 sizes=[21] status=ok\n"
            )

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        owner_by_message = {
            bubble["message_id"]: item["owner"]
            for item in detail["timeline"] if item["type"] == "message"
            for bubble in item["bubbles"]
        }
        self.assertEqual(owner_by_message["aya-yesterday"], "aya")
        self.assertEqual(owner_by_message["owner-yesterday"], "owner")

    def test_handoff_and_followup_are_interleaved_in_the_timeline(self):
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        events = [item for item in detail["timeline"] if item["type"] == "event"]
        self.assertEqual([item["event"] for item in events], ["followup", "handoff"])
        self.assertEqual(events[0]["status"], "sent")
        self.assertEqual(events[0]["step"], 1)
        self.assertEqual(events[1]["reason"], "pediu desconto")
        self.assertEqual(
            [item["at"] for item in detail["timeline"]],
            sorted(item["at"] for item in detail["timeline"]),
        )

    def test_detail_includes_profile_funnel_and_session_usage(self):
        contacts = json.loads(self.paths.contacts_json.read_text(encoding="utf-8"))
        contacts[LEAD].update({
            "relationship": "Cliente",
            "manual_relationship": "Paciente de implante",
            "notes": "Prefere atendimento à tarde.",
            "summary": "Busca implante e perguntou sobre desconto.",
            "tone": "polido e profissional",
        })
        self.paths.contacts_json.write_text(json.dumps(contacts), encoding="utf-8")
        FollowupEngine(self.paths.followups_db).set_estimated_value(LEAD, 480_000, now=NOW)

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        self.assertEqual(detail["profile"]["relationship"], "Paciente de implante")
        self.assertEqual(detail["profile"]["notes"], "Prefere atendimento à tarde.")
        self.assertEqual(detail["lead"]["stage"], "pricing")
        self.assertEqual(detail["lead"]["stage_label"], "Preço")
        self.assertEqual(detail["lead"]["estimated_value_cents"], 480_000)
        self.assertEqual(detail["lead"]["cadence"], "Silêncio")
        self.assertTrue(detail["lead"]["next_followup_utc"])
        self.assertEqual(detail["usage"], {
            "sessions": 1,
            "calls": 2,
            "tokens": 11_500,
            "model": "gpt-5.6-terra",
        })

    def test_phone_detail_includes_lid_messages_without_duplicates(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (LEAD_LID, LEAD_LID, "Mariana", "lid-only", "text", "Cheguei pelo LID", NOW.timestamp() - 1200, 0),
                (LEAD_LID, LEAD_LID, "Mariana", "m3", "text", "Quinta. Vocês dão algum desconto?", NOW.timestamp() - 1800, 0),
            ],
        )
        conn.commit()
        conn.close()

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        ids = [
            bubble["message_id"]
            for item in detail["timeline"] if item["type"] == "message"
            for bubble in item["bubbles"]
        ]
        self.assertIn("lid-only", ids)
        self.assertEqual(ids.count("m3"), 1)

    def test_phone_log_splits_owner_messages_stored_under_lid(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (LEAD_LID, "bot", "AYA", "lid-aya", "text", "A" * 17, NOW.timestamp() - 1200, 1),
                (LEAD_LID, OWNER, "Dono", "lid-owner", "text", "D" * 19, NOW.timestamp() - 1100, 1),
            ],
        )
        conn.commit()
        conn.close()
        stamp = (NOW - timedelta(seconds=1200)).astimezone(panel_data.daily_audit.business_tz())
        with self.paths.plugin_log.open("a", encoding="utf-8") as log:
            log.write(
                f"{stamp.strftime('%Y-%m-%dT%H:%M:%S')} INFO [whatsapp-manager] "
                f"[human-send] chat={LEAD!r} bubbles=1 sizes=[17] status=ok\n"
            )

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        owner_by_message = {
            bubble["message_id"]: item["owner"]
            for item in detail["timeline"] if item["type"] == "message"
            for bubble in item["bubbles"]
        }
        self.assertEqual(owner_by_message["lid-aya"], "aya")
        self.assertEqual(owner_by_message["lid-owner"], "owner")

    def test_bubble_sizes_are_consumed_per_day_not_across_the_conversation(self):
        yesterday_at = NOW - timedelta(days=1)
        conn = sqlite3.connect(self.paths.messages_db)
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (LEAD, "bot", "AYA", "aya-day-one", "text", "A" * 21, (yesterday_at - timedelta(minutes=5)).timestamp(), 1),
                (LEAD, OWNER, "Dono", "owner-day-one", "text", "D" * 17, yesterday_at.timestamp(), 1),
                (LEAD, "bot", "AYA", "aya-day-two", "text", "B" * 17, (NOW - timedelta(minutes=10)).timestamp(), 1),
            ],
        )
        conn.commit()
        conn.close()
        tz = panel_data.daily_audit.business_tz()
        with self.paths.plugin_log.open("a", encoding="utf-8") as log:
            log.write(
                f"{(yesterday_at - timedelta(minutes=5)).astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S')} "
                f"INFO [whatsapp-manager] [human-send] chat={LEAD!r} bubbles=1 sizes=[21] status=ok\n"
            )
            log.write(
                f"{(NOW - timedelta(minutes=10)).astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S')} "
                f"INFO [whatsapp-manager] [human-send] chat={LEAD!r} bubbles=1 sizes=[17] status=ok\n"
            )

        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)

        owner_by_message = {
            bubble["message_id"]: item["owner"]
            for item in detail["timeline"] if item["type"] == "message"
            for bubble in item["bubbles"]
        }
        self.assertEqual(owner_by_message["owner-day-one"], "owner")
        self.assertEqual(owner_by_message["aya-day-two"], "aya")

    def test_flow_event_between_messages_breaks_the_bubble_group(self):
        conn = sqlite3.connect(self.paths.messages_db)
        conn.executemany(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (LEAD, LEAD, "Mariana", "before-event", "text", "Antes do evento", NOW.timestamp() - 1500, 0),
                (LEAD, LEAD, "Mariana", "after-event", "text", "Depois do evento", NOW.timestamp() - 1300, 0),
            ],
        )
        conn.commit()
        conn.close()
        event_at = (NOW - timedelta(seconds=1400)).astimezone(panel_data.daily_audit.business_tz())
        with self.paths.plugin_log.open("a", encoding="utf-8") as log:
            log.write(
                f"{event_at.strftime('%Y-%m-%dT%H:%M:%S')} INFO [whatsapp-manager] "
                f"[handoff] dono avisado sobre {LEAD!r} motivo='evento entre bolhas' message_id='before-event'\n"
            )

        timeline = panel_data.lead_detail(self.paths, LEAD, now=NOW)["timeline"]

        before = next(i for i, item in enumerate(timeline) if any(b["message_id"] == "before-event" for b in item.get("bubbles", [])))
        event = next(i for i, item in enumerate(timeline) if item.get("reason") == "evento entre bolhas")
        after = next(i for i, item in enumerate(timeline) if any(b["message_id"] == "after-event" for b in item.get("bubbles", [])))
        self.assertLess(before, event)
        self.assertLess(event, after)


class LeadPatientDirectoryTest(PanelFixture):
    def _configure_directory(self, *, patient_id="123456", generated_at=None):
        import dataclasses
        snapshot_path = Path(self.tmp.name) / "patient_directory.json"
        snapshot_path.write_text(json.dumps({
            "schema_version": 1, "source": "prontuario_verde", "clinic_id": "cuidar-odontologia",
            "source_clinic_hash": "a" * 64,
            "generated_at": (generated_at or NOW).isoformat(), "complete": True,
            "patients": [{"id": patient_id, "phones": [LEAD]}],
        }), encoding="utf-8")
        self.paths = dataclasses.replace(self.paths, patient_directory_json=snapshot_path)
        return {
            "enabled": True, "clinic_id": "cuidar-odontologia", "source_clinic_hash": "a" * 64,
        }

    def test_detail_returns_numeric_id_only_for_one_fresh_match(self):
        config = self._configure_directory()
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW, patient_directory_config=config)
        self.assertEqual(detail["patient_directory"], {
            "status": "matched", "count": 1, "updated_at": "2026-09-07 13:00 UTC", "patient_id": "123456",
        })

    def test_invalid_matched_id_fails_closed_and_stale_snapshot_is_unavailable(self):
        for patient_id in ("private-id", "0", "000123", "1" * 32, "1/evil"):
            with self.subTest(patient_id=patient_id):
                config = self._configure_directory(patient_id=patient_id)
                invalid = panel_data.lead_detail(self.paths, LEAD, now=NOW, patient_directory_config=config)
                self.assertEqual(invalid["patient_directory"], {
                    "status": "unavailable", "count": None, "updated_at": None, "patient_id": None,
                })
        config = self._configure_directory(generated_at=NOW - timedelta(hours=25))
        stale = panel_data.lead_detail(self.paths, LEAD, now=NOW, patient_directory_config=config)
        self.assertEqual(stale["patient_directory"]["status"], "unavailable")
        self.assertIsNone(stale["patient_directory"]["patient_id"])

    def test_lid_alias_resolves_to_phone_but_conflicting_phone_aliases_fail_closed(self):
        config = self._configure_directory()
        mapped = panel_data.lead_detail(
            self.paths, LEAD_LID, now=NOW, patient_directory_config=config,
        )
        self.assertEqual(mapped["patient_directory"]["patient_id"], "123456")
        with patch.object(panel_data, "_contact_aliases", return_value=[LEAD, LEAD2]):
            conflicting = panel_data.lead_detail(
                self.paths, LEAD, now=NOW, patient_directory_config=config,
            )
        self.assertEqual(conflicting["patient_directory"]["status"], "unavailable")
        self.assertIsNone(conflicting["patient_directory"]["patient_id"])

    def test_unresolved_lid_and_disabled_config_return_null_or_unavailable(self):
        config = self._configure_directory()
        unresolved = panel_data.lead_detail(
            self.paths, "123456789@lid", now=NOW, patient_directory_config=config,
        )
        self.assertEqual(unresolved["patient_directory"]["status"], "unavailable")
        disabled = panel_data.lead_detail(
            self.paths, LEAD, now=NOW, patient_directory_config={"enabled": False},
        )
        self.assertIsNone(disabled["patient_directory"])


class MetricsTest(PanelFixture):
    def test_day_metrics_counts_chats_and_splits_ai_from_human(self):
        day = panel_data.day_metrics(self.paths, TODAY, today=TODAY)
        self.assertEqual(day["chats"], 3)
        # Mariana teve handoff → humano; Rafael e o spam ficaram só com a IA.
        self.assertEqual(day["ai_resolved"], 2)
        self.assertEqual(day["human"], 1)
        self.assertEqual(len(day["handoffs"]), 1)
        self.assertFalse(day["handoffs"][0]["answered"])
        self.assertEqual(day["unanswered"], [{"chat_id": LEAD2, "waited_s": 190}])
        self.assertEqual(day["api_calls"], 2)
        self.assertEqual(day["model_seconds"], 4.2)

    def test_metrics_period_series_and_time_saved(self):
        result = panel_data.metrics(self.paths, "7d", now=NOW, minutes_per_resolved=6)
        self.assertEqual(len(result["series"]), 7)
        self.assertEqual(result["series"][-1]["ai"], 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["minutes_saved"], 12)
        self.assertEqual(result["handoffs_pending_total"], 1)
        self.assertEqual(result["handoffs_pending"][0]["name"], "Mariana Lopes")
        self.assertEqual(result["handoffs_pending"][0]["reason"], "pediu desconto")

    def test_past_days_are_cached_but_today_is_not(self):
        yesterday = TODAY - timedelta(days=1)
        panel_data.day_metrics(self.paths, yesterday, today=TODAY)
        self.assertIn((str(self.paths.messages_db), yesterday.isoformat()), panel_data._DAY_CACHE)
        panel_data.day_metrics(self.paths, TODAY, today=TODAY)
        self.assertNotIn((str(self.paths.messages_db), TODAY.isoformat()), panel_data._DAY_CACHE)


class UsageTest(PanelFixture):
    def test_usage_sums_whatsapp_sessions_only_and_prices_by_table(self):
        result = panel_data.usage(self.paths, "7d", now=NOW)
        models = {m["model"]: m for m in result["models"]}
        self.assertEqual(set(models), {"gpt-5.6-terra", "deepseek/deepseek-v4-flash"})
        terra = models["gpt-5.6-terra"]
        self.assertEqual((terra["input"], terra["output"], terra["cache_read"], terra["reasoning"]), (10_000, 1_000, 4_000, 500))
        self.assertTrue(terra["included"])
        # 6.000 entrada fresca × 2 + 4.000 cache × 0,5 + 1.500 saída × 8 = 0,012 + 0,002 + 0,012
        self.assertAlmostEqual(terra["usd"], 0.026, places=4)
        deepseek = models["deepseek/deepseek-v4-flash"]
        self.assertFalse(deepseek["included"])
        # Sem preço na tabela, vale o custo que o provider reportou.
        self.assertAlmostEqual(deepseek["usd"], 0.0031, places=4)
        self.assertTrue(deepseek["priced"])
        self.assertAlmostEqual(result["usd"], 0.0291, places=4)
        self.assertAlmostEqual(result["brl"], 0.15, places=2)
        self.assertEqual(result["calls"], 3)
        self.assertEqual(len(result["series"]), 7)
        self.assertEqual(result["series"][-1]["tokens"], 10_000 + 1_000 + 500 + 5_000 + 400)

    def test_billed_separates_from_api_equivalent(self):
        # gpt-5.6-terra entra na assinatura: conta no equivalente, não no pago.
        self.paths.pricing_json.write_text(json.dumps({
            "usd_brl": 5.0, "updated_at": "2026-09-07", "subscription_usd_month": 20,
            "models": {
                "gpt-5.6-terra": {"input": 2.0, "cached_input": 0.2, "output": 12.0},
                "deepseek/deepseek-v4-flash": {"input": 0.09, "cached_input": 0.02, "output": 0.18},
            },
        }), encoding="utf-8")
        result = panel_data.usage(self.paths, "7d", now=NOW)
        # terra (assinatura): 6.000 frescos × 2 + 4.000 cache × 0,2 + 1.500 saída × 12
        # deepseek (por token): 5.000 × 0,09 + 400 × 0,18
        terra = (6_000 * 2.0 + 4_000 * 0.2 + 1_500 * 12.0) / 1_000_000
        deepseek = (5_000 * 0.09 + 400 * 0.18) / 1_000_000
        self.assertEqual(result["usd"], round(terra + deepseek, 4))
        self.assertEqual(result["usd_billed"], round(deepseek, 4))
        self.assertLess(result["usd_billed"], result["usd"], "assinatura fica fora do que se paga")
        self.assertEqual(result["brl"], round((terra + deepseek) * 5, 2))
        self.assertEqual(result["brl_billed"], round(deepseek * 5, 2))
        self.assertEqual(result["pricing_updated_at"], "2026-09-07")
        # A assinatura acompanha o câmbio do arquivo, sem número duplicado.
        self.assertEqual(result["subscription_usd_month"], 20)
        self.assertEqual(result["subscription_brl_month"], 100.0)
        self.assertFalse(result["unpriced"])
        dia = result["series"][-1]
        self.assertEqual(dia["brl"], round((terra + deepseek) * 5, 2))
        self.assertEqual(dia["brl_billed"], round(deepseek * 5, 2))

    def test_missing_state_db_yields_empty_usage(self):
        self.paths.state_db.unlink()
        result = panel_data.usage(self.paths, "hoje", now=NOW)
        self.assertEqual(result["models"], [])
        self.assertEqual(result["usd"], 0)


class ServerTest(PanelFixture):
    def setUp(self):
        super().setUp()
        config = panel_server.Config(
            username="dono", password="segredo-forte", bridge_url="http://127.0.0.1:1",
            bridge_host_header="", minutes_per_resolved=6, hourly_rate_brl=38, owner_number="5547999414100",
            hermes_dashboard_url="http://127.0.0.1:1", whatsapp_mode="bot", whatsapp_allowed_users="*",
            google_client_id="", google_client_secret="", public_url="",
        )
        handler = panel_server.make_handler(config, self.paths, panel_server.BridgeClient(config.bridge_url, timeout=0.2))
        self.httpd = panel_server.PanelServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def _get(self, path: str, auth: str | None = "dono:segredo-forte"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_requires_basic_auth(self):
        self.assertEqual(self._get("/api/health", auth=None)[0], 401)
        self.assertEqual(self._get("/api/health", auth="dono:errada")[0], 401)
        self.assertEqual(self._get("/api/health")[0], 200)

    def test_api_routes_return_json(self):
        status, body = self._get("/api/leads")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["total"], 2)
        status, body = self._get("/api/blocked")
        payload = json.loads(body)
        self.assertEqual([b["name"] for b in payload["blocked"]], ["Ofertas Consórcio"])
        self.assertNotIn(BLOCKED, [r["chat_id"] for r in payload["recent"]])
        status, body = self._get("/api/status")
        self.assertEqual(json.loads(body)["bridge"], "unreachable")

    def test_config_returns_only_sanitized_commercial_subscription(self):
        config_path = Path(self.tmp.name) / "panel.config.json"
        config_path.write_text(json.dumps({
            "subscription": {
                "name": "Plano Crescer",
                "price_brl": 1499.9,
                "billing": "por mês",
                "included": ["Atendimento no WhatsApp", "Funil comercial"],
                "internal_provider_cost": 20,
            },
            "api_key": "não pode sair",
        }), encoding="utf-8")
        with patch.object(panel_server, "CONFIG_PATH", config_path):
            status, body = self._get("/api/config")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["subscription"], {
            "name": "Plano Crescer",
            "price_brl": 1499.9,
            "billing": "por mês",
            "included": ["Atendimento no WhatsApp", "Funil comercial"],
        })
        self.assertNotIn("api_key", payload)
        self.assertNotIn("internal_provider_cost", json.dumps(payload))

    def test_lead_detail_shows_meeting_and_qualification(self):
        """QA 09/09: a AYA agendou e a ficha não mostrava a reunião nem o que o lead disse."""
        import dataclasses
        import calendar_booking as cb
        root = Path(self.tmp.name)
        bookings = root / "calendar_bookings.db"
        con = sqlite3.connect(bookings)
        con.execute(
            "CREATE TABLE current_bookings (chat_key TEXT PRIMARY KEY, event_id TEXT NOT NULL, start TEXT NOT NULL, "
            "end TEXT NOT NULL, timezone TEXT NOT NULL, meet_link TEXT NOT NULL, html_link TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO current_bookings VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cb._booking_chat_key(LEAD), "evt-1", "2026-09-09T16:30:00-03:00", "2026-09-09T17:00:00-03:00",
             "America/Sao_Paulo", "https://meet.google.com/abc-defg-hij", "", "active", NOW.timestamp(), NOW.timestamp()),
        )
        con.commit(); con.close()
        paths = dataclasses.replace(self.paths, bookings_db=bookings)

        detail = panel_data.lead_detail(paths, LEAD)

        self.assertEqual(detail["meeting"]["meet_link"], "https://meet.google.com/abc-defg-hij")
        self.assertTrue(any(item.get("event") == "booking" for item in detail["timeline"]))
        self.assertEqual(detail["qualification"][0], "Queria saber como funciona a avaliação para implante.")

    def test_lead_detail_route_returns_the_conversation(self):
        status, body = self._get("/api/lead/" + quote(LEAD, safe=""))

        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "Mariana Lopes")
        self.assertEqual(payload["lead"]["stage"], "pricing")
        self.assertTrue(payload["timeline"])
        self.assertEqual(payload["silence"], {"known": False, "silenced": False, "hold": False, "reason": None, "time_left_s": 0})
        self.assertIsNone(payload["patient_directory"])

    def test_lead_detail_route_includes_private_patient_id_only_when_enabled(self):
        config_path = Path(self.tmp.name) / "panel.config.json"
        snapshot_path = Path(self.tmp.name) / "patient_directory.json"
        generated_at = datetime.now(timezone.utc).replace(microsecond=0)
        config_path.write_text(json.dumps({"patient_directory": {
            "enabled": True, "clinic_id": "cuidar-odontologia", "source_clinic_hash": "a" * 64,
        }}), encoding="utf-8")
        snapshot_path.write_text(json.dumps({
            "schema_version": 1, "source": "prontuario_verde", "clinic_id": "cuidar-odontologia",
            "source_clinic_hash": "a" * 64, "generated_at": generated_at.isoformat(), "complete": True,
            "patients": [{"id": "123456", "phones": [LEAD]}],
        }), encoding="utf-8")
        import dataclasses
        paths = dataclasses.replace(self.paths, patient_directory_json=snapshot_path)
        with patch.object(panel_server, "CONFIG_PATH", config_path):
            handler = panel_server.make_handler(
                panel_server.Config(
                    username="dono", password="segredo-forte", bridge_url="http://127.0.0.1:1",
                    bridge_host_header="", minutes_per_resolved=6, hourly_rate_brl=38,
                    owner_number="5547999414100", hermes_dashboard_url="http://127.0.0.1:1",
                    whatsapp_mode="bot", whatsapp_allowed_users="*", google_client_id="",
                    google_client_secret="", public_url="",
                ), paths, panel_server.BridgeClient("http://127.0.0.1:1", timeout=0.2),
            )
            server = panel_server.PanelServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/lead/{quote(LEAD, safe='')}"
                )
                request.add_header("Authorization", "Basic " + base64.b64encode(b"dono:segredo-forte").decode())
                with opener.open(request, timeout=5) as response:
                    payload = json.loads(response.read())
                self.assertEqual(payload["patient_directory"], {
                    "status": "matched", "count": 1,
                    "updated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
                    "patient_id": "123456",
                })
            finally:
                server.shutdown()
                server.server_close()

    def test_weak_password_refuses_to_start(self):
        env = {"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "admin123"}
        self.assertIn(panel_server.Config.from_env(env).password, panel_server.WEAK_PASSWORDS)

    def test_health_poll_interval_comes_from_environment(self):
        env = {
            "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "segredo-forte",
            "WHATSAPP_HEALTH_POLL_INTERVAL_MINUTES": "10",
        }
        self.assertEqual(panel_server.Config.from_env(env).health_poll_interval_minutes, 10.0)


if __name__ == "__main__":
    unittest.main()
