"""Ritmo humano: gate de horário, esperas longas, categoria e delay de resposta."""
from __future__ import annotations

import contextlib
import datetime
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

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

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
BRT = ZoneInfo("America/Sao_Paulo")
CHAT = "556281405459@s.whatsapp.net"
DIAGNOSTICO = "de zero a dez, quanto isso te incomoda hoje?"

MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    sender_id TEXT,
    sender_name TEXT,
    message_id TEXT NOT NULL,
    message_type TEXT,
    body TEXT,
    timestamp REAL,
    from_me INTEGER NOT NULL DEFAULT 0,
    is_historical INTEGER NOT NULL DEFAULT 0,
    has_media INTEGER NOT NULL DEFAULT 0,
    media_type TEXT,
    sync_type TEXT,
    context_wamid TEXT,
    inserted_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
"""


def _brt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, tzinfo=BRT).astimezone(datetime.UTC)


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class _ImmediateThread:
    def __init__(self, *, target, args=(), daemon=None, name=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class RitmoTestCase(unittest.TestCase):
    """Perfil da Therapify, motor de follow-up em disco temporário e relógio fixo."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            "WHATSAPP_FOLLOWUP_ENABLED": "true",
        }))

        self.db_path = self.tmp / "whatsapp_messages.db"
        con = sqlite3.connect(self.db_path)
        con.executescript(MESSAGES_SCHEMA)
        con.commit()
        con.close()
        self.enterContext(mock.patch.object(wm, "_MSG_DB_PATH", self.db_path))

        self.enterContext(mock.patch.object(wm, "_FOLLOWUP_DB_PATH", self.tmp / "followups.db"))
        wm._FOLLOWUP_ENGINE = None
        self.addCleanup(setattr, wm, "_FOLLOWUP_ENGINE", None)

        self.record: dict = {}
        self.enterContext(mock.patch.object(
            wm, "_contact_record_for_chat", side_effect=lambda cid, contacts=None: dict(self.record)
        ))
        self.enterContext(mock.patch.object(
            wm, "_merge_contact_record_atomic", side_effect=lambda key, fields, **kw: self.record.update(fields)
        ))
        self.enterContext(mock.patch.object(wm, "_session_is_owner", return_value=False))
        self.enterContext(mock.patch.object(
            wm, "_contact_effect_identity_lock", side_effect=lambda *a, **k: contextlib.nullcontext()
        ))

    def freeze(self, moment: datetime.datetime):
        self.enterContext(mock.patch.object(wm, "_hum_now", return_value=moment))
        return moment

    def add_message(self, body: str, *, from_me: int, ts: float, message_id: str = "") -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO messages(chat_id, message_id, body, timestamp, from_me) VALUES (?, ?, ?, ?, ?)",
            (CHAT, message_id or f"m{ts}", body, ts, from_me),
        )
        con.commit()
        con.close()

    def jobs(self) -> list[dict]:
        if not (self.tmp / "followups.db").exists():
            return []
        con = sqlite3.connect(self.tmp / "followups.db")
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM followup_jobs ORDER BY id")]
        finally:
            con.close()

    def only_job(self) -> dict:
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1, jobs)
        return jobs[0]

    def due_of(self, job: dict) -> datetime.datetime:
        return datetime.datetime.fromisoformat(job["due_utc"])


class GateDeRitmoTest(RitmoTestCase):
    def test_sem_bloco_humanization_nada_liga(self):
        with mock.patch.object(wm, "_humanization", return_value=None), \
             mock.patch.object(wm.time, "sleep") as sleep:
            self.assertIsNone(wm._ritmo_gate(CHAT, is_replay=False))
            self.assertTrue(wm._ritmo_wait_before_send(CHAT, "objecao", ("m1", 1.0)))
            self.assertTrue(wm._ritmo_send_window_ok(CHAT))
        sleep.assert_not_called()
        self.assertEqual(self.jobs(), [])

    def test_lead_novo_na_terca_responde_na_hora_sem_job(self):
        self.freeze(_brt(2026, 9, 8, 10, 0))
        self.assertIsNone(wm._ritmo_gate(CHAT, is_replay=False))
        self.assertEqual(self.jobs(), [])

    def test_lead_novo_na_sexta_20h50_responde_na_hora(self):
        # Ainda dentro da janela: sem a espera de 12–35 min a Fase 1 sai agora.
        self.freeze(_brt(2026, 9, 11, 20, 50))
        self.assertIsNone(wm._ritmo_gate(CHAT, is_replay=False))
        self.assertEqual(self.jobs(), [])

    def test_lead_novo_na_sexta_a_noite_cai_na_segunda_as_9h(self):
        self.freeze(_brt(2026, 9, 11, 21, 30))
        self.assertEqual(wm._ritmo_gate(CHAT, is_replay=False), "ritmo-lead-novo")
        job = self.only_job()
        self.assertEqual(job["off_days_ok"], 0)
        self.assertEqual(self.due_of(job), _brt(2026, 9, 14, 9, 0))

    def test_bot_ja_falou_no_sabado_espera_o_proximo_dia_util(self):
        self.add_message("oi, tudo bem?", from_me=1, ts=_brt(2026, 9, 4, 18, 0).timestamp())
        self.freeze(_brt(2026, 9, 5, 10, 0))
        self.assertEqual(wm._ritmo_gate(CHAT, is_replay=False), "ritmo-fora-de-hora")
        job = self.only_job()
        # Segunda 2026-09-07 é feriado no profile: a fila da manhã é na terça.
        terca = _brt(2026, 9, 8, 9, 0)
        self.assertEqual(job["off_days_ok"], 0)
        self.assertEqual(job["basis_outbound_id"], "resume:fila_manha")
        self.assertEqual(self.due_of(job), terca)

    def test_debounce_de_sintomas_estende_ate_o_teto(self):
        base = _brt(2026, 9, 8, 15, 0)
        self.add_message(DIAGNOSTICO, from_me=1, ts=base.timestamp() - 60)
        with mock.patch.object(wm, "_hum_now", return_value=base):
            self.assertEqual(wm._ritmo_gate(CHAT, is_replay=False), "ritmo-debounce-sintomas")
        primeiro = self.due_of(self.only_job())
        self.assertGreaterEqual(primeiro, base + datetime.timedelta(seconds=120))
        self.assertLessEqual(primeiro, base + datetime.timedelta(seconds=180))

        depois = base + datetime.timedelta(seconds=170)
        with mock.patch.object(wm, "_hum_now", return_value=depois):
            self.assertEqual(wm._ritmo_gate(CHAT, is_replay=False), "ritmo-debounce-sintomas")
        segundo = self.due_of(self.only_job())
        self.assertGreater(segundo, primeiro)
        self.assertLessEqual(segundo, base + datetime.timedelta(seconds=300))

    def test_bolha_comum_segue_para_o_modelo(self):
        self.add_message("show, vamos lá", from_me=1, ts=_brt(2026, 9, 8, 14, 50).timestamp())
        self.freeze(_brt(2026, 9, 8, 15, 0))
        self.assertIsNone(wm._ritmo_gate(CHAT, is_replay=False))
        self.assertEqual(self.jobs(), [])

    def test_adiar_descarta_o_registro_do_inbound_para_o_replay_ser_reservado(self):
        # Uma mensagem só à noite: o replay traz o mesmo texto. Sem descartar o registro
        # original, a reserva do turno pegaria o mais antigo e a entrega cairia em stale.
        self.add_message("oi, tudo bem?", from_me=1, ts=_brt(2026, 9, 7, 18, 0).timestamp())
        self.freeze(_brt(2026, 9, 8, 22, 30))
        wm._track_inbound(CHAT, "orig-1", "quero saber mais")
        self.assertEqual(wm._ritmo_gate(CHAT, is_replay=False), "ritmo-fora-de-hora")
        self.assertEqual(wm._current_inbound_record(CHAT), {})

        wm._track_inbound(CHAT, "resume:abc", "quero saber mais")
        claimed = wm._claim_pending_inbound_for_turn(CHAT, CHAT, "quero saber mais")
        self.assertEqual(claimed.get("message_id"), "resume:abc")
        token = wm._inbound_record_token(claimed)
        self.assertFalse(wm._newer_inbound_arrived(CHAT, token))

    def test_lead_em_takeover_nao_fura_janela_de_envio(self):
        # Takeover não autoriza automação fora do expediente. Mesmo se o motor recusar
        # a retomada, a janela final permanece fail-closed.
        self.freeze(_brt(2026, 9, 8, 22, 30))
        self.add_message("oi, tudo bem?", from_me=1, ts=_brt(2026, 9, 7, 18, 0).timestamp())
        wm._followup_engine().note_human_takeover(CHAT)
        self.assertEqual(wm._ritmo_gate(CHAT, is_replay=False), "ritmo-fora-de-hora")
        self.assertEqual([j for j in self.jobs() if j["status"] == "pending"], [])
        self.assertFalse(wm._ritmo_send_window_ok(CHAT))

    def test_evento_de_replay_passa_direto(self):
        self.freeze(_brt(2026, 9, 8, 10, 0))
        self.assertIsNone(wm._ritmo_gate(CHAT, is_replay=True))
        self.assertEqual(self.jobs(), [])


class ReplayResumeTest(RitmoTestCase):
    def _claim(self, now: datetime.datetime) -> tuple[object, dict]:
        engine = wm._followup_engine()
        engine.schedule_resume(
            CHAT, due=now - datetime.timedelta(seconds=60), reason="fila_manha",
            at=now - datetime.timedelta(seconds=120), off_days_ok=False,
        )
        claimed = engine.claim_due(now=now, worker_id="test")
        self.assertEqual(len(claimed), 1)
        return engine, claimed[0]

    def test_replay_junta_as_mensagens_pendentes_do_lead(self):
        now = self.freeze(_brt(2026, 9, 8, 9, 20))
        self.add_message("oi", from_me=1, ts=now.timestamp() - 900, message_id="bot1")
        self.add_message("bom dia", from_me=0, ts=now.timestamp() - 600, message_id="lead1")
        self.add_message("posso marcar?", from_me=0, ts=now.timestamp() - 300, message_id="lead2")
        engine, job = self._claim(now)

        posted: list[dict] = []

        def _urlopen(req, timeout=None):
            posted.append({"url": req.full_url, "body": json.loads(req.data.decode("utf-8"))})
            return _FakeResponse(json.dumps({"success": True, "messageId": "resume:abc"}).encode())

        with mock.patch.object(wm.urllib.request, "urlopen", side_effect=_urlopen):
            self.assertTrue(wm._replay_resume(engine, job))

        self.assertEqual(len(posted), 1)
        self.assertTrue(posted[0]["url"].endswith("/requeue"))
        self.assertEqual(posted[0]["body"]["bodyParts"], ["bom dia", "posso marcar?"])
        self.assertEqual(posted[0]["body"]["messageIds"], ["lead1", "lead2"])
        self.assertEqual(posted[0]["body"]["reason"], "fila_manha")
        self.assertEqual(self.only_job()["status"], "sent")

    def test_replay_sem_pendencia_cancela_sem_post(self):
        now = self.freeze(_brt(2026, 9, 8, 9, 20))
        self.add_message("bom dia", from_me=0, ts=now.timestamp() - 900, message_id="lead1")
        self.add_message("já te respondi por aqui", from_me=1, ts=now.timestamp() - 300, message_id="bot1")
        engine, job = self._claim(now)

        with mock.patch.object(wm.urllib.request, "urlopen") as urlopen:
            self.assertFalse(wm._replay_resume(engine, job))
        urlopen.assert_not_called()
        cancelado = self.only_job()
        self.assertEqual(cancelado["status"], "cancelled")
        self.assertEqual(cancelado["last_error"], "nothing_pending")

    def test_tick_roteia_resume_para_o_replay(self):
        now = self.freeze(_brt(2026, 9, 8, 9, 20))
        self.add_message("bom dia", from_me=0, ts=now.timestamp() - 600, message_id="lead1")
        engine = wm._followup_engine()
        engine.schedule_resume(
            CHAT, due=now - datetime.timedelta(seconds=60), reason="lead_novo",
            at=now - datetime.timedelta(seconds=120), off_days_ok=True,
        )
        with mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_replay_resume", return_value=True) as replay, \
             mock.patch.object(wm, "_tick_crm_outbox", return_value=0), \
             mock.patch.object(wm, "render_contextual_message") as render:
            self.assertEqual(wm._tick_followups(), 1)
        render.assert_not_called()
        self.assertEqual(replay.call_args[0][1]["cadence_kind"], "resume")


class CategoriaTest(unittest.TestCase):
    def test_extrai_e_corta_o_marcador(self):
        categoria, texto = wm._extract_reply_category("bolha 1\n\nbolha 2\n\n[cat:objecao]")
        self.assertEqual(categoria, "objecao")
        self.assertEqual(texto, "bolha 1\n\nbolha 2")

    def test_variacoes_de_escrita(self):
        self.assertEqual(wm._extract_reply_category("ok\n\n[[ CAT : Intencao ]]")[0], "intencao")
        self.assertEqual(wm._extract_reply_category("ok\n\n[cat:intenção]")[0], "intencao")

    def test_ausente_ou_invalido_vira_comum(self):
        self.assertEqual(wm._extract_reply_category("só o texto"), ("comum", "só o texto"))
        categoria, texto = wm._extract_reply_category("texto\n\n[cat:banana]")
        self.assertEqual(categoria, "comum")
        self.assertEqual(texto, "texto")

    def test_marcador_nunca_chega_ao_lead(self):
        enviados: list[dict] = []

        def _urlopen(req, timeout=None):
            enviados.append(json.loads(req.data.decode("utf-8")))
            return _FakeResponse(json.dumps({"messageId": "wamid.1"}).encode())

        with mock.patch.object(wm.urllib.request, "urlopen", side_effect=_urlopen):
            wm._human_send(CHAT, "quer marcar?\n\n[cat:intencao]")
        self.assertEqual([m["message"] for m in enviados], ["quer marcar?"])


class DelayDeRespostaTest(RitmoTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True))
        self.enterContext(mock.patch.object(wm, "_complete_contact_send"))
        self.enterContext(mock.patch.object(wm, "_maybe_start_playbook_completion"))
        self.enterContext(mock.patch.object(wm, "_hum_typing"))
        self.sleeps: list[float] = []
        self.enterContext(mock.patch.object(wm.time, "sleep", side_effect=self.sleeps.append))
        self.deliver = self.enterContext(
            mock.patch.object(wm, "_deliver_contact_reply", return_value="wamid.1")
        )

    def test_intencao_espera_entre_5_e_75_segundos(self):
        self.add_message("oi", from_me=1, ts=_brt(2026, 9, 8, 14, 0).timestamp())
        self.freeze(_brt(2026, 9, 8, 15, 0))
        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=False):
            self.assertTrue(wm._schedule_contact_reply(CHAT, "beleza", "t1", ("m1", 1.0), category="intencao"))
        self.deliver.assert_called_once()
        total = sum(self.sleeps)
        self.assertGreaterEqual(total, 5.0)
        self.assertLessEqual(total, 75.0)
        self.assertTrue(all(s <= wm._HUM_WAIT_STEP_S for s in self.sleeps))

    def test_mensagem_nova_descarta_a_resposta(self):
        self.add_message("oi", from_me=1, ts=_brt(2026, 9, 8, 14, 0).timestamp())
        self.freeze(_brt(2026, 9, 8, 15, 0))
        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=True):
            self.assertFalse(wm._schedule_contact_reply(CHAT, "beleza", "t1", ("m1", 1.0), category="comum"))
        self.deliver.assert_not_called()
        self.assertEqual(self.jobs(), [])

    def test_delay_que_atravessa_as_21h_vira_retomada(self):
        self.add_message("oi", from_me=1, ts=_brt(2026, 9, 8, 14, 0).timestamp())
        now = self.freeze(_brt(2026, 9, 8, 21, 5))
        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=False):
            self.assertFalse(wm._schedule_contact_reply(CHAT, "beleza", "t1", ("m1", 1.0), category="intencao"))
        self.deliver.assert_not_called()
        job = self.only_job()
        quarta = _brt(2026, 9, 9, 9, 0)
        self.assertEqual(job["basis_outbound_id"], "resume:fila_manha")
        self.assertEqual(job["off_days_ok"], 0)
        self.assertEqual(self.due_of(job), quarta)
        self.assertGreater(self.due_of(job), now)


class WatchdogEStaleTest(RitmoTestCase):
    def setUp(self):
        super().setUp()
        with wm._pending_inbound_lock:
            wm._pending_inbound.clear()
            wm._pending_inbound_queue.clear()

    def test_watchdog_espera_o_delay_maximo_do_ritmo(self):
        # objecao vai até 360 s: alerta só depois disso (+ margem), não aos 180 s
        self.assertEqual(wm._unanswered_alert_seconds(), 360 + 120)
        with mock.patch.object(wm, "_humanization", return_value=None):
            self.assertEqual(wm._unanswered_alert_seconds(), 180)
        wm._track_inbound(CHAT, "m-200s", "tá caro")
        with wm._pending_inbound_lock:
            wm._pending_inbound[CHAT]["at"] -= 200
        self.assertEqual(wm._sweep_unanswered(), [])
        self.assertEqual(wm._current_inbound_record(CHAT).get("message_id"), "m-200s")

    def test_registro_removido_pelo_watchdog_nao_e_inbound_novo(self):
        wm._track_inbound(CHAT, "m1", "quero marcar")
        token = wm._inbound_record_token(wm._current_inbound_record(CHAT))
        wm._clear_inbound(CHAT, token)  # o que o watchdog faz ao apagar
        self.assertEqual(wm._current_inbound_record(CHAT), {})
        self.assertFalse(wm._newer_inbound_arrived(CHAT, token))
        wm._track_inbound(CHAT, "m2", "e o preço?")
        self.assertTrue(wm._newer_inbound_arrived(CHAT, token))


class RespostasNaoEnviadasTest(RitmoTestCase):
    def setUp(self):
        super().setUp()
        wm._clear_unsent_replies(CHAT)

    def test_descarte_entra_no_contexto_e_some_na_entrega(self):
        self.assertEqual(wm._unsent_replies_block(CHAT), "")
        wm._note_unsent_reply(CHAT, "Olá! Atendimento 100% online\n\nO Dr. Rodrigo...", "obsoleta")
        block = wm._unsent_replies_block(CHAT)
        self.assertIn("NÃO chegaram ao lead", block)
        self.assertIn("Olá! Atendimento 100% online O Dr. Rodrigo...", block)
        wm._clear_unsent_replies(CHAT)
        self.assertEqual(wm._unsent_replies_block(CHAT), "")

    def test_guarda_so_as_ultimas_tres(self):
        for i in range(5):
            wm._note_unsent_reply(CHAT, f"resposta {i}", "teste")
        block = wm._unsent_replies_block(CHAT)
        self.assertNotIn("resposta 1", block)
        self.assertIn("resposta 4", block)

    def test_mensagem_nova_durante_o_delay_registra_a_resposta(self):
        # Só respostas depois da Fase 1 esperam pelo delay; a primeira saída sai na hora.
        self.add_message("abertura já enviada", from_me=1, ts=_brt(2026, 9, 8, 10, 0).timestamp())
        with mock.patch.object(wm, "_newer_inbound_arrived", return_value=True), \
             mock.patch.object(wm.time, "sleep"), \
             mock.patch.object(wm, "_complete_contact_send"), \
             mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_human_send") as send:
            wm._schedule_contact_reply(CHAT, "Bolha que morreu", "tk-1", ("m1", 1.0), category="comum")
        send.assert_not_called()
        self.assertIn("Bolha que morreu", wm._unsent_replies_block(CHAT))


class PrimeiroEnvioTest(RitmoTestCase):
    def test_followup_carimba_o_primeiro_envio_ao_lead(self):
        with mock.patch.object(wm, "_assert_delivery_allowed"), \
             mock.patch.object(
                 wm.urllib.request, "urlopen",
                 return_value=_FakeResponse(json.dumps({"messageId": "wamid.9"}).encode()),
             ):
            wm._followup_bridge_send(CHAT, "ainda tá por aí?")
        self.assertIn(wm._BOT_FIRST_OUTBOUND_FIELD, self.record)
        self.assertFalse(wm._ritmo_gate(CHAT, is_replay=False) == "ritmo-lead-novo")

    def test_notificacao_ao_dono_nao_carimba(self):
        with mock.patch.object(wm, "_session_is_owner", return_value=True):
            wm._mark_bot_spoke("5511999999999@s.whatsapp.net")
        self.assertEqual(self.record, {})

    def test_historico_antigo_marca_o_lead_como_ja_atendido(self):
        self.add_message("oi", from_me=1, ts=_brt(2026, 9, 1, 10, 0).timestamp())
        self.assertTrue(wm._bot_has_spoken(CHAT))
        self.assertEqual(self.record[wm._BOT_FIRST_OUTBOUND_FIELD], "legacy")

    def test_sem_banco_de_mensagens_cai_no_historico_http(self):
        with mock.patch.object(wm, "_MSG_DB_PATH", self.tmp / "nao-existe.db"), \
             mock.patch.object(wm, "_chat_bot_sent_matching", return_value=False) as scan:
            self.assertFalse(wm._bot_has_spoken(CHAT))
        scan.assert_called_once()
        self.assertEqual(self.record, {})


if __name__ == "__main__":
    unittest.main()
