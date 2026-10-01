"""Regressões do auditor por fase e da atribuição de autoria por message ID."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPEC = importlib.util.spec_from_file_location("daily_audit_under_test", REPO_ROOT / "daily_audit.py")
assert SPEC and SPEC.loader
da = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = da
SPEC.loader.exec_module(da)

CHAT = "5511999999999@s.whatsapp.net"
AT = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
OPENING = [
    "Olá! Atendimento 100% online, do conforto da sua casa.",
    "O Dr. Rodrigo Melo é especialista em dependência emocional, com 8 anos de experiência.",
    "A sessão inicial inclui liberação emocional, protocolo para descobrir a raiz do sofrimento e um plano de autocuidado – tudo por R$ 247,00.",
    "Após a primeira sessão, você já percebe os primeiros resultados.",
    "O tempo estimado até o agendamento da sua consulta é de 4 a 6 minutos.",
    "Para entender melhor o seu caso: tem quanto tempo que terminaram? Como você vem lidando com tudo isso?",
]


class DailyAuditTests(unittest.TestCase):
    def test_literal_therapify_opening_is_exempt_from_common_chat_limits(self):
        reply = da.Reply(chat_id=CHAT, at=AT, bubbles=OPENING)

        found = da.find_format_violations(reply, phase_exceptions={"first_outbound": OPENING})

        self.assertFalse({"bolhas_demais", "perguntas_demais", "frases_demais"} & {v.kind for v in found})

    def test_literal_fixed_phase_reply_can_have_multiple_questions(self):
        reply = da.Reply(chat_id=CHAT, at=AT, bubbles=["Pergunta A?", "Pergunta B?"])

        found = da.find_format_violations(
            reply,
            phase_exceptions={"fixed_responses": [["Pergunta A?", "Pergunta B?"]]},
        )

        self.assertFalse({"bolhas_demais", "perguntas_demais", "frases_demais"} & {v.kind for v in found})

    def test_diagnostic_reaction_template_accepts_full_phase_with_variable_name(self):
        questions = [
            "Você percebe isso refletindo em problema de ansiedade, desanimo, insônia?",
            'Sua alimentação está "ok"?',
            "De zero a dez em que nível anda a ansiedade?",
            "Isso vem te afetando no trabalho em outros momento também?",
        ]
        phase = [
            "Ok✅",
            "Tudo bem",
            "Não se preocupe, rapidamente resolvemos o que vem sentindo Anthony",
            *questions,
        ]
        found = da.find_format_violations(
            da.Reply(chat_id=CHAT, at=AT, bubbles=phase),
            phase_exceptions={"diagnostic_reaction": {
                "prefix": ["Ok✅", "Tudo bem"],
                "intro_prefix": "Não se preocupe, rapidamente resolvemos o que vem sentindo",
                "questions": questions,
            }},
        )

        self.assertFalse({"bolhas_demais", "perguntas_demais", "frases_demais"} & {v.kind for v in found})

    def test_diagnostic_questions_alone_do_not_exempt_arbitrary_reply(self):
        questions = [
            "Você percebe isso refletindo em problema de ansiedade, desanimo, insônia?",
            'Sua alimentação está "ok"?',
            "De zero a dez em que nível anda a ansiedade?",
            "Isso vem te afetando no trabalho em outros momento também?",
        ]
        phase = ["Introdução arbitrária", "Segue outro conteúdo?", *questions]
        found = da.find_format_violations(
            da.Reply(chat_id=CHAT, at=AT, bubbles=phase),
            phase_exceptions={"diagnostic_reaction": {
                "prefix": ["Ok✅", "Tudo bem"],
                "intro_prefix": "Não se preocupe, rapidamente resolvemos o que vem sentindo",
                "questions": questions,
            }},
        )

        self.assertIn("perguntas_demais", {v.kind for v in found})

    def test_manual_short_message_is_attributed_by_send_id_when_available(self):
        turns = [
            da.Turn(CHAT, AT, True, "feito", "bot-id"),
            da.Turn(CHAT, AT, True, "feito", "owner-id"),
        ]
        events = [da.AuditEvent(
            tag="human-send",
            fields={"message_ids": "['bot-id']", "sizes": "[5]"},
            chat_id=CHAT,
        )]

        bot, owner = da.split_owner_manual(turns, events)

        self.assertEqual([turn.message_id for turn in bot], ["bot-id"])
        self.assertEqual([turn.message_id for turn in owner], ["owner-id"])

    def test_mixed_legacy_and_id_logs_leave_unmatched_messages_uncertain(self):
        old_bot = da.Turn(CHAT, AT, True, "resposta antiga", "old-bot-id")
        new_bot = da.Turn(CHAT, AT, True, "resposta atual", "new-bot-id")
        events = [
            da.AuditEvent(tag="human-send", fields={"sizes": "[15]"}, chat_id=CHAT),
            da.AuditEvent(
                tag="human-send",
                fields={"message_ids": "['new-bot-id']", "sizes": "[14]"},
                chat_id=CHAT,
            ),
        ]

        bot, owner = da.split_owner_manual([old_bot, new_bot], events)
        day = da.build_day_audit(AT.date(), events, [old_bot, new_bot], lambda _text: None)

        self.assertEqual([turn.message_id for turn in bot], ["new-bot-id"])
        self.assertEqual([turn.message_id for turn in owner], ["old-bot-id"])
        self.assertTrue(old_bot.attribution_uncertain)
        self.assertEqual(day.owner_manual, 0)
        self.assertEqual(day.replies_author_uncertain, 1)
        self.assertEqual(day.replies_format_checked, 1)

    def test_send_log_parses_confirmed_message_ids(self):
        events = da.parse_log_lines([
            "2026-10-01T12:00:00 INFO [whatsapp-manager] [human-send] "
            f"chat={CHAT!r} bubbles=1 sizes=[5] message_ids=['bot-id'] status=ok"
        ])

        self.assertEqual(events[0].fields["message_ids"], "['bot-id']")
        self.assertEqual(events[0].fields["status"], "ok")

    def test_reply_origin_and_format_findings_are_reported_separately(self):
        day = da.build_day_audit(
            AT.date(), [],
            [da.Turn(CHAT, AT, False, "Oi", "lead-id"), da.Turn(CHAT, AT, True, "Olá", "bot-id")],
            lambda _text: None,
            phase_exceptions={"first_outbound": OPENING},
        )
        report = da.compile_material(day, [])

        self.assertIn("origem indeterminada fora do catálogo de fallback", report)
        self.assertNotIn("modelo acertou", report)
        self.assertIn("conformidade semântica não avaliada", report)

    def test_legacy_length_match_does_not_claim_human_or_bot_conformity(self):
        turns = [
            da.Turn(CHAT, AT, False, "Oi", "lead-id"),
            da.Turn(CHAT, AT, True, "curto"),
        ]
        events = [da.AuditEvent(tag="human-send", fields={"sizes": "[5]"}, chat_id=CHAT)]

        day = da.build_day_audit(AT.date(), events, turns, lambda _text: None)
        report = da.compile_material(day, turns)

        self.assertEqual(day.owner_manual, 0)
        self.assertEqual(day.replies_author_uncertain, 1)
        self.assertEqual(day.replies_format_checked, 0)
        self.assertIn("excluídas da conformidade", report)
