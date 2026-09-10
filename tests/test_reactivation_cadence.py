"""Fase 7: reativação com texto do playbook, downsell do método gravado e toque final."""
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

from commercial_followups import BusinessHours, add_business_days, is_business_time  # noqa: E402

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
THERAPIFY_PROFILE = json.loads(THERAPIFY_PROFILE_PATH.read_text(encoding="utf-8"))
HOURS = BusinessHours.from_profile(THERAPIFY_PROFILE)
BRT = ZoneInfo("America/Sao_Paulo")
CHAT = "556281405459@s.whatsapp.net"
CADENCE = "reactivation"
DOWNSELL_FIELD = "downsell_metodo_gravado_at"
# Terça dentro do expediente: os três toques caem em quarta, quinta e sexta.
BASE = datetime.datetime(2026, 9, 8, 10, 0, tzinfo=BRT).astimezone(datetime.UTC)

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


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class ReactivationTestCase(unittest.TestCase):
    """Perfil da Therapify, motor em disco temporário e bridge de mentira."""

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

        self.msg_db = self.tmp / "whatsapp_messages.db"
        con = sqlite3.connect(self.msg_db)
        con.executescript(MESSAGES_SCHEMA)
        con.commit()
        con.close()
        self.enterContext(mock.patch.object(wm, "_MSG_DB_PATH", self.msg_db))

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
        self.enterContext(mock.patch.object(wm, "_assert_delivery_allowed"))
        self.enterContext(mock.patch.object(wm.time, "sleep"))

        self.media_file = self.tmp / "downsell.jpeg"
        self.media_file.write_bytes(b"jpeg")
        manifest = self.tmp / "media-manifest.json"
        manifest.write_text(json.dumps({
            "purchase_feedback_print": {"items": [{"type": "image", "path": str(self.media_file)}]}
        }), encoding="utf-8")
        self.enterContext(mock.patch.object(wm, "_MEDIA_MANIFEST_PATH", manifest))

        self.posts: list[dict] = []
        self.enterContext(mock.patch.object(
            wm.urllib.request, "urlopen", side_effect=self._urlopen
        ))

    def _urlopen(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8")) if req.data else {}
        self.posts.append({"url": req.full_url, "body": body})
        return _FakeResponse(json.dumps({"messageId": f"wamid.{len(self.posts)}"}).encode())

    def sent_messages(self) -> list[str]:
        return [p["body"]["message"] for p in self.posts if p["url"].endswith("/send")]

    def sent_media(self) -> list[str]:
        return [p["body"]["filePath"] for p in self.posts if p["url"].endswith("/send-media")]

    def arm(self, at: datetime.datetime = BASE):
        """Estado de quem recebeu uma mensagem do bot e ainda não respondeu."""
        engine = wm._followup_engine()
        engine.configure_lead(
            CHAT, automation_enabled=True, stage="qualification", cadence_kind=CADENCE, now=at
        )
        engine.note_outbound(CHAT, message_id="bridge-out", at=at)
        return engine

    def step_job(self, engine, step_no: int) -> tuple[dict, datetime.datetime]:
        job = next(
            j for j in engine.get_jobs(CHAT)
            if j["cadence_kind"] == CADENCE and j["step_no"] == step_no
        )
        return job, datetime.datetime.fromisoformat(job["due_utc"])

    def claim_step(self, engine, step_no: int) -> tuple[dict, datetime.datetime]:
        """Leva a cadência até o passo pedido; os anteriores saem como enviados."""
        for earlier in range(1, step_no):
            job, due = self.step_job(engine, earlier)
            if job["status"] != "pending":
                continue
            claimed = next(
                c for c in engine.claim_due(now=due, worker_id="test") if c["step_no"] == earlier
            )
            engine.mark_sent(claimed["id"], f"bridge-d{earlier}", claimed["lease_token"], at=due)
        _job, due = self.step_job(engine, step_no)
        claimed = [c for c in engine.claim_due(now=due, worker_id="test") if c["step_no"] == step_no]
        self.assertEqual(len(claimed), 1, claimed)
        return claimed[0], due


class RegistroDoTurnoTest(ReactivationTestCase):
    def test_oi_sem_sinal_comercial_agenda_os_tres_toques(self):
        token = ("m1", 1.0)
        wm._followup_remember_turn(CHAT, "oi", "m1", inbound_token=token)
        # O motor grava o vencimento com precisão de segundo.
        antes = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
        ids = wm._followup_register_outbound(
            CHAT, "wamid.1", expected_token=token, expected_source_message_id="m1"
        )
        depois = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
        self.assertEqual(len(ids), 3)

        engine = wm._followup_engine()
        jobs = [j for j in engine.get_jobs(CHAT) if j["cadence_kind"] == CADENCE]
        self.assertEqual([j["step_no"] for j in jobs], [1, 2, 3])
        for job, days in zip(jobs, (1, 2, 3)):
            due = datetime.datetime.fromisoformat(job["due_utc"])
            self.assertGreaterEqual(due, add_business_days(antes, days, HOURS))
            self.assertLessEqual(due, add_business_days(depois, days, HOURS))
            self.assertTrue(is_business_time(due, HOURS))
            # Texto literal do profile: nenhum passo depende do gate de contexto.
            self.assertIsNone(job["context_kind"])
            self.assertEqual(job["context_verified"], 0)
        self.assertEqual(engine.get_lead(CHAT)["cadence_kind"], CADENCE)

    def test_mensagem_do_lead_cancela_os_toques_abertos(self):
        engine = self.arm()
        wm._followup_note_activity(CHAT, inbound=True, message_id="m2", text="desculpa, sumi")
        jobs = [j for j in engine.get_jobs(CHAT) if j["cadence_kind"] == CADENCE]
        self.assertTrue(all(j["status"] == "cancelled" for j in jobs), jobs)

    def test_pedido_de_humano_continua_virando_takeover(self):
        token = ("m3", 3.0)
        wm._followup_remember_turn(CHAT, "quero falar com uma pessoa", "m3", inbound_token=token)
        ids = wm._followup_register_outbound(
            CHAT, "wamid.2", expected_token=token, expected_source_message_id="m3"
        )
        self.assertEqual(ids, [])
        lead = wm._followup_engine().get_lead(CHAT)
        self.assertTrue(bool(lead["takeover"]))

    def test_chat_do_dono_nunca_entra_na_fase_7(self):
        with mock.patch.object(wm, "_session_is_owner", return_value=True):
            wm._followup_remember_turn(CHAT, "oi", "m4", inbound_token=("m4", 4.0))
        self.assertEqual(
            wm._followup_register_outbound(
                CHAT, "wamid.4", expected_token=("m4", 4.0), expected_source_message_id="m4"
            ),
            [],
        )

    def test_turno_de_retomada_tambem_registra_a_cadencia(self):
        # O replay volta pelo bridge com `resume:<uuid>` como message_id do inbound; o
        # snapshot precisa sobreviver ao CAS de token para o lead não ficar sem Fase 7.
        token = ("resume:abc", 4.0)
        wm._followup_remember_turn(CHAT, "oi", "resume:abc", inbound_token=token)
        ids = wm._followup_register_outbound(
            CHAT, "wamid.3", expected_token=token, expected_source_message_id="resume:abc"
        )
        self.assertEqual(len(ids), 3)


class ToquesDaFase7Test(ReactivationTestCase):
    def test_d1_sai_em_duas_bolhas(self):
        engine = self.arm()
        job, due = self.claim_step(engine, 1)
        with mock.patch.object(wm, "_hum_now", return_value=due):
            self.assertTrue(wm._send_reactivation_step(engine, job))
        self.assertEqual(self.sent_messages(), ["Olá 👋", "Desistiu do tratamento?"])
        self.assertEqual(self.sent_media(), [])
        self.assertEqual(self.step_job(engine, 1)[0]["status"], "sent")

    def test_d2_manda_o_bloco_do_metodo_gravado_com_o_print(self):
        engine = self.arm()
        job, due = self.claim_step(engine, 2)
        with mock.patch.object(wm, "_hum_now", return_value=due):
            self.assertTrue(wm._send_reactivation_step(engine, job))

        mensagens = self.sent_messages()
        self.assertEqual(len(mensagens), 9)
        self.assertEqual(mensagens[0].split()[0], "Já")
        self.assertEqual(mensagens[5], "https://pay.kiwify.com.br/GuPTgV6")
        self.assertEqual(mensagens[6], "Veja o feedback dessa paciente")
        self.assertEqual(mensagens[7], "Qual opção faria mais sentido agora, para seu momento atual?")
        self.assertEqual(mensagens[8], "A sessão premium ou método gravado?")
        self.assertEqual(self.sent_media(), [str(self.media_file)])
        # O print entra entre a sétima e a oitava bolha, não no fim.
        ordem = [p["url"].rsplit("/", 1)[-1] for p in self.posts]
        self.assertEqual(ordem.index("send-media"), 7)
        self.assertIn(DOWNSELL_FIELD, self.record)

    def test_d2_e_pulado_quando_o_r47_ja_foi_oferecido(self):
        self.record[DOWNSELL_FIELD] = 1757000000.0
        engine = self.arm()
        job, due = self.claim_step(engine, 2)
        with mock.patch.object(wm, "_hum_now", return_value=due):
            self.assertFalse(wm._send_reactivation_step(engine, job))
        self.assertEqual(self.posts, [])
        pulado = self.step_job(engine, 2)[0]
        self.assertEqual(pulado["status"], "skipped")
        self.assertEqual(pulado["last_error"], "downsell_ja_oferecido")

        # O toque final continua saindo no vencimento dele.
        final, due_final = self.step_job(engine, 3)
        self.assertEqual(final["status"], "pending")
        claimed = engine.claim_due(now=due_final, worker_id="test")
        self.assertEqual([c["step_no"] for c in claimed], [3])

    def test_toque_final_deixa_o_lead_terminal(self):
        engine = self.arm()
        job, due = self.claim_step(engine, 3)
        with mock.patch.object(wm, "_hum_now", return_value=due):
            self.assertTrue(wm._send_reactivation_step(engine, job))
        self.assertEqual(self.sent_messages()[-1], "https://protocolo.therapify.com.br")
        self.assertTrue(bool(engine.get_lead(CHAT)["terminal"]))

        # Depois do toque final o bot não inicia mais nada por conta própria...
        token = ("m9", 9.0)
        wm._followup_remember_turn(CHAT, "oi", "m9", inbound_token=token)
        self.assertEqual(
            wm._followup_register_outbound(CHAT, "wamid.90", expected_token=token,
                                           expected_source_message_id="m9"),
            [],
        )
        self.assertEqual(
            [j for j in engine.get_jobs(CHAT) if j["status"] == "pending"], []
        )
        # ...mas responder o lead continua valendo: a retomada ignora `terminal`.
        depois = due + datetime.timedelta(hours=1)
        self.assertIsNotNone(
            engine.schedule_resume(CHAT, due=depois, reason="fila_manha", at=due)
        )
        claimed = engine.claim_due(now=depois, worker_id="test")
        self.assertEqual([c["cadence_kind"] for c in claimed], ["resume"])

    def test_passo_sem_texto_no_profile_cancela_sem_enviar(self):
        engine = self.arm()
        job, due = self.claim_step(engine, 1)
        with mock.patch.object(wm, "_profile_lookup", return_value=None), \
             mock.patch.object(wm, "_hum_now", return_value=due):
            self.assertFalse(wm._send_reactivation_step(engine, job))
        self.assertEqual(self.posts, [])
        self.assertEqual(self.step_job(engine, 1)[0]["status"], "cancelled")

    def test_tick_roteia_a_reativacao_para_a_fase_7(self):
        engine = self.arm()
        _job, due = self.step_job(engine, 1)
        with mock.patch.object(wm.datetime, "datetime", wraps=datetime.datetime) as fake, \
             mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_tick_crm_outbox", return_value=0), \
             mock.patch.object(wm, "render_contextual_message") as render, \
             mock.patch.object(wm, "_send_reactivation_step", return_value=True) as fase7:
            fake.now.return_value = due
            self.assertEqual(wm._tick_followups(), 1)
        render.assert_not_called()
        self.assertEqual(fase7.call_args[0][1]["cadence_kind"], CADENCE)


class MarcaDoDownsellTest(ReactivationTestCase):
    def test_resposta_do_modelo_com_o_link_marca_uma_vez(self):
        wm._maybe_mark_downsell(CHAT, "Segue o link abaixo 🔗✅👇🏼 https://pay.kiwify.com.br/GuPTgV6")
        primeiro = self.record[DOWNSELL_FIELD]
        wm._maybe_mark_downsell(CHAT, "https://pay.kiwify.com.br/GuPTgV6")
        self.assertEqual(self.record[DOWNSELL_FIELD], primeiro)

    def test_texto_do_metodo_gravado_tambem_marca(self):
        wm._maybe_mark_downsell(CHAT, "Você pode aplicar o método auto aplicável por 47,00")
        self.assertIn(DOWNSELL_FIELD, self.record)

    def test_resposta_comum_nao_marca(self):
        wm._maybe_mark_downsell(CHAT, "A sessão com o Dr. Rodrigo é R$ 247,00")
        self.assertEqual(self.record, {})

    def test_entrega_confirmada_ao_lead_carimba_o_downsell(self):
        with mock.patch.object(wm, "_human_send", return_value="wamid.7"), \
             mock.patch.object(wm, "_followup_remember_turn"), \
             mock.patch.object(wm, "_followup_register_outbound"), \
             mock.patch.object(wm, "_current_inbound_record", return_value={}), \
             mock.patch.object(wm, "_voice_reply_allowed_for", return_value=False):
            wm._deliver_contact_reply(CHAT, "Segue o link 🔗 https://pay.kiwify.com.br/GuPTgV6")
        self.assertIn(DOWNSELL_FIELD, self.record)


class SemFase7Test(ReactivationTestCase):
    """Perfil sem `reactivation.enabled`: o follow genérico volta a valer."""

    def setUp(self):
        super().setUp()
        profile = json.loads(json.dumps(THERAPIFY_PROFILE))
        profile["reactivation"]["enabled"] = False
        path = self.tmp / "business_profile.json"
        path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        self.enterContext(mock.patch.dict(
            os.environ, {"WHATSAPP_BUSINESS_PROFILE_FILE": str(path)}
        ))
        _reset_profile_cache()

    def test_saudacao_nao_arma_cadencia_nenhuma(self):
        wm._followup_remember_turn(CHAT, "oi", "m1", inbound_token=("m1", 1.0))
        self.assertEqual(
            wm._followup_register_outbound(
                CHAT, "wamid.1", expected_token=("m1", 1.0), expected_source_message_id="m1"
            ),
            [],
        )

    def test_sinal_comercial_volta_a_armar_a_cadencia_generica(self):
        token = ("m2", 2.0)
        wm._followup_remember_turn(CHAT, "quero saber o preço do atendimento", "m2", inbound_token=token)
        ids = wm._followup_register_outbound(
            CHAT, "wamid.2", expected_token=token, expected_source_message_id="m2"
        )
        self.assertEqual(len(ids), 3)
        engine = wm._followup_engine()
        self.assertEqual(engine.get_lead(CHAT)["cadence_kind"], "proposal")
        self.assertEqual(engine.get_lead(CHAT)["context_fact"], "quero saber o preço do atendimento")

    def test_entrega_nao_carimba_downsell(self):
        wm._maybe_mark_downsell(CHAT, "https://pay.kiwify.com.br/GuPTgV6")
        self.assertEqual(self.record, {})


if __name__ == "__main__":
    unittest.main()
