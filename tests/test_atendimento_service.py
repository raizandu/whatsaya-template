"""Serviço de atendimento: Snapshot dos bancos reais, aplicação no store e no bridge, filas."""
from __future__ import annotations

import dataclasses
import sys
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import history_store  # noqa: E402
import atendimento_store as store  # noqa: E402
import panel_store  # noqa: E402
import users_store  # noqa: E402
from atendimento_service import AtendimentoService, canonical_contato  # noqa: E402
from tests.test_panel_data import BLOCKED, LEAD, LEAD2, LEAD_LID, NOW, PanelFixture  # noqa: E402

LEAD3 = "5521988887777@s.whatsapp.net"


class Bridge:
    """Só o que o serviço usa: estado, silenciados e as duas escritas de hold."""

    def __init__(self):
        self.down = False
        self.paused = False
        self.lid = {}
        self.silenced: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, path):
        if self.down:
            return None
        if path == "/bot-status":
            return {"botPaused": self.paused, "lidToPhone": dict(self.lid)}
        if path == "/chat-silence":
            return {"silencedChats": [
                {"chatId": chat, "hold": s["hold"], "reason": s["reason"], "silencedUntil": s.get("until", 0), "since": 1}
                for chat, s in self.silenced.items()
            ]}
        return None

    def post_json(self, path, body, timeout=None):
        self.calls.append((path, body))
        if self.down:
            return None
        if path == "/chat-silence":
            self.silenced[body["chatId"]] = {"hold": bool(body.get("hold")), "reason": body.get("reason", "painel"), "until": 0}
            return {"success": True, "chatId": body["chatId"], "hold": bool(body.get("hold"))}
        if path == "/chat-unsilence":
            self.silenced.pop(body["chatId"], None)
            return {"success": True, "chatId": body["chatId"]}
        return None


class ServiceFixture(PanelFixture):
    def setUp(self):
        super().setUp()
        self.paths = dataclasses.replace(self.paths, users_json=Path(self.tmp.name) / "panel_users.json")
        users_store.create_user(self.paths.users_json, username="ana", name="Ana", password="SenhaForte#2026", role="atendente")
        # A fixture do painel registra `sizes=[62]` para uma bolha de 60 caracteres, o que
        # faz a regra do log classificar m2 como Dono; aqui a AYA mandou m2 de verdade.
        log = self.paths.plugin_log.read_text(encoding="utf-8").replace("sizes=[62]", "sizes=[60]")
        self.paths.plugin_log.write_text(log, encoding="utf-8")
        self.bridge = Bridge()
        self.service = AtendimentoService(self.paths, self.bridge, usuarios_extra=("admin",))

    def _insert(self, chat_id, message_id, body, ts, from_me):
        conn = history_store.connect(str(self.paths.messages_db))
        conn.execute(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (chat_id, "x", "x", message_id, "text", body, ts, 1 if from_me else 0),
        )
        conn.commit()
        conn.close()


class BootstrapTest(ServiceFixture):
    def test_primeira_execucao_abre_para_quem_escreveu_na_janela_e_nao_para_bloqueado(self):
        resultado = self.service.reconciliar(NOW, force=True)
        self.assertFalse(resultado["skipped"])
        abertos = {a["contato"]: a for a in store.listar_abertos(self.paths.panel_db)}
        self.assertEqual(set(abertos), {LEAD, LEAD2})
        mariana = abertos[LEAD]
        self.assertEqual(mariana["responsavel_tipo"], "ia")
        self.assertEqual(mariana["aberto_utc"], (NOW - timedelta(hours=1)).isoformat())
        self.assertEqual((mariana["primeira_resposta_autor"], mariana["ultima_msg_autor"]), ("ia", "contato"))
        self.assertEqual(abertos[LEAD2]["ultima_msg_autor"], "ia")
        self.assertEqual(store.meta_get(self.paths.panel_db, "msg_cursor"), repr(NOW.timestamp() - 600))
        # Segunda rodada com o mesmo mundo: nada muda.
        self.assertEqual(self.service.reconciliar(NOW, force=True)["mudancas"], 0)

    def test_bridge_fora_do_ar_nao_reconcilia_nem_avanca_o_cursor(self):
        self.bridge.down = True
        resultado = self.service.reconciliar(NOW, force=True)
        self.assertEqual(resultado, {"skipped": True, "bridge": "unreachable"})
        self.assertEqual(store.listar_abertos(self.paths.panel_db), [])
        self.assertIsNone(store.meta_get(self.paths.panel_db, "msg_cursor"))

    def test_trava_de_cinco_segundos(self):
        self.assertFalse(self.service.reconciliar(NOW)["skipped"])
        self.assertTrue(self.service.reconciliar(NOW)["skipped"])

    def test_lid_e_telefone_sao_o_mesmo_contato(self):
        self.bridge.lid = {"236344165040241": "5547999414105"}
        self._insert(LEAD_LID, "m7", "Consigo ir de manhã?", NOW.timestamp() - 100, False)
        self.service.reconciliar(NOW, force=True)
        abertos = store.listar_abertos(self.paths.panel_db)
        self.assertEqual([a["contato"] for a in abertos if a["contato"] in (LEAD, LEAD_LID)], [LEAD])
        self.assertEqual(abertos[0]["ultima_msg_utc"], (NOW - timedelta(seconds=100)).isoformat())
        todos = self.service.listar(fila="todos", username="admin", ver_todos=True, now=NOW)
        self.assertEqual(next(i for i in todos["itens"] if i["contato"] == LEAD)["preview"], "Consigo ir de manhã?", "prévia vem do @lid")

    def test_canonical_resolve_lid_pelo_cadastro_quando_bridge_nao_sabe(self):
        contacts = {LEAD: {"lid": LEAD_LID}, LEAD_LID: {}}
        self.assertEqual(canonical_contato(LEAD_LID, contacts, {}), LEAD)
        self.assertEqual(canonical_contato("1@g.us", contacts, {}), None)
        self.assertEqual(canonical_contato("999@lid", {}, {}), "999@lid")


class AutoriaTest(ServiceFixture):
    def test_resposta_do_painel_e_primeira_resposta_com_usuario(self):
        self._insert(LEAD3, "n1", "Oi, vocês atendem sábado?", NOW.timestamp() - 300, False)
        self._insert(LEAD3, "n2", "Atendemos sim, até 13h.", NOW.timestamp() - 200, True)
        panel_store.record_outbound(
            self.paths.panel_db, message_id="n2", chat_id=LEAD3, body="Atendemos sim, até 13h.",
            sent_by="human", sent_by_user="ana", sent_utc=NOW.isoformat(),
        )
        self.service.reconciliar(NOW, force=True)
        row = store.aberto_do_contato(self.paths.panel_db, LEAD3)
        self.assertEqual((row["primeira_resposta_autor"], row["primeira_resposta_user"]), ("painel", "ana"))
        self.assertEqual(row["responsavel_tipo"], "ia", "quem assume ao responder é a ação de resposta, não a reconciliação")

    def test_dono_pelo_celular_assume_e_recebe_hold_uma_vez(self):
        self.service.reconciliar(NOW, force=True)
        # Mensagem própria sem `[human-send]` correspondente no log: é o Dono.
        self._insert(LEAD2, "d1", "Rafael, sou eu, o doutor. Te ligo já.", NOW.timestamp() - 30, True)
        depois = NOW + timedelta(seconds=10)
        self.service.reconciliar(depois, force=True)
        row = store.aberto_do_contato(self.paths.panel_db, LEAD2)
        self.assertEqual(row["responsavel_tipo"], "dono")
        self.assertEqual([c for c in self.bridge.calls if c[0] == "/chat-silence"],
                         [("/chat-silence", {"chatId": LEAD2, "hold": True, "reason": "painel"})])
        self.service.reconciliar(depois + timedelta(seconds=10), force=True)
        self.assertEqual(len(self.bridge.calls), 1, "hold já casado não é reenviado")
        self.assertEqual([e["tipo"] for e in store.eventos(self.paths.panel_db, row["id"])], ["aberto", "assumido"])


class HandoffTest(ServiceFixture):
    def test_handoff_no_bridge_tira_da_ia_e_o_fim_do_prazo_devolve(self):
        self.service.reconciliar(NOW, force=True)
        self.bridge.silenced[LEAD] = {"hold": False, "reason": "handoff", "until": int((NOW.timestamp() + 3600) * 1000)}
        self.service.reconciliar(NOW + timedelta(seconds=10), force=True)
        row = store.aberto_do_contato(self.paths.panel_db, LEAD)
        self.assertEqual(row["responsavel_tipo"], "nenhum")
        self.assertIsNotNone(row["handoff_utc"])
        self.bridge.silenced.pop(LEAD)
        self.service.reconciliar(NOW + timedelta(seconds=20), force=True)
        row = store.aberto_do_contato(self.paths.panel_db, LEAD)
        self.assertEqual(row["responsavel_tipo"], "ia")
        self.assertEqual([e["tipo"] for e in store.eventos(self.paths.panel_db, row["id"])], ["aberto", "handoff", "devolvido_auto"])

    def test_bloqueio_resolve(self):
        self.service.reconciliar(NOW, force=True)
        contacts = __import__("json").loads(self.paths.contacts_json.read_text())
        contacts[LEAD2]["blocked"] = True
        self.paths.contacts_json.write_text(__import__("json").dumps(contacts))
        self.service.reconciliar(NOW + timedelta(seconds=10), force=True)
        self.assertIsNone(store.aberto_do_contato(self.paths.panel_db, LEAD2))
        self.assertEqual(store.listar_do_contato(self.paths.panel_db, LEAD2)[0]["resolvido_motivo"], "bloqueio")


class ListarTest(ServiceFixture):
    def test_filas_contagens_permissao_e_cursor(self):
        self.service.reconciliar(NOW, force=True)
        rafael = store.aberto_do_contato(self.paths.panel_db, LEAD2)
        store.definir_responsavel(self.paths.panel_db, rafael["id"], tipo="atendente", user="ana", ator="ana", evento="assumido", now=NOW)
        rev_apos_assumir = store.rev(self.paths.panel_db)

        meus = self.service.listar(fila="meus", username="ana", ver_todos=False, now=NOW)
        self.assertEqual([i["contato"] for i in meus["itens"]], [LEAD2])
        self.assertEqual(meus["contagens"], {"meus": 1, "sem_responsavel": 0})
        self.assertEqual(meus["aguardando"], 0)
        self.assertFalse(meus["bot_paused"])
        item = meus["itens"][0]
        self.assertEqual(item["nome"], "Rafael Nunes")
        self.assertEqual(item["preview"], "Fazemos sim. Me conta qual a sua expectativa?")
        self.assertEqual(item["responsavel"], {"tipo": "atendente", "user": "ana"})
        self.assertFalse(item["aguardando_nos"])
        self.assertTrue(item["sla"]["primeira"]["cumprida"])

        with self.assertRaises(PermissionError):
            self.service.listar(fila="todos", username="ana", ver_todos=False, now=NOW)
        with self.assertRaises(ValueError):
            self.service.listar(fila="x", username="ana", ver_todos=True, now=NOW)

        todos = self.service.listar(fila="todos", username="admin", ver_todos=True, now=NOW)
        self.assertEqual(todos["contagens"], {"meus": 0, "sem_responsavel": 0, "com_ia": 1, "todos": 3})
        historico = next(i for i in todos["itens"] if i["contato"] == BLOCKED)
        self.assertFalse(historico["atendimento_aberto"])
        self.assertIsNone(historico["sla"])
        self.assertEqual(historico["preview"], "Consórcio contemplado!")
        mariana = next(i for i in todos["itens"] if i["contato"] == LEAD)
        self.assertTrue(mariana["aguardando_nos"])
        self.assertEqual(mariana["espera_s"], 1800)
        self.assertTrue(mariana["sla"]["resolucao"]["estourado"] is False)
        self.assertEqual(todos["itens"][0]["contato"], LEAD, "aguardando nós vem primeiro")

        nada = self.service.listar(fila="todos", username="admin", ver_todos=True, desde_rev=rev_apos_assumir, now=NOW)
        self.assertEqual(nada["itens"], [])
        self.assertEqual(nada["contagens"]["todos"], 3, "contagens sempre completas")

    def test_historico_importado_aparece_sem_abrir_atendimento(self):
        import json
        contacts = json.loads(self.paths.contacts_json.read_text(encoding="utf-8"))
        contacts[LEAD3] = {"name": "Contato antigo", "ai_enabled": False}
        self.paths.contacts_json.write_text(json.dumps(contacts), encoding="utf-8")
        conn = history_store.connect(str(self.paths.messages_db))
        conn.execute(
            "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me, is_historical)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (LEAD3, LEAD3, "Contato antigo", "historico-1", "text", "Mensagem antiga", NOW.timestamp() - 86400, 0, 1),
        )
        conn.commit()
        conn.close()

        self.service.reconciliar(NOW, force=True)
        self.assertIsNone(store.aberto_do_contato(self.paths.panel_db, LEAD3))
        todos = self.service.listar(fila="todos", username="admin", ver_todos=True, now=NOW)
        item = next(i for i in todos["itens"] if i["contato"] == LEAD3)
        self.assertFalse(item["atendimento_aberto"])
        self.assertEqual(item["preview"], "Mensagem antiga")
        self.assertEqual(todos["contagens"]["todos"], 4)

    def test_badge_conta_aguardando_em_meus_e_sem_responsavel(self):
        self.service.reconciliar(NOW, force=True)
        mariana = store.aberto_do_contato(self.paths.panel_db, LEAD)
        store.definir_responsavel(self.paths.panel_db, mariana["id"], tipo="nenhum", user=None, ator="sistema", evento="handoff", now=NOW)
        sem = self.service.listar(fila="sem_responsavel", username="ana", ver_todos=False, now=NOW)
        self.assertEqual(sem["aguardando"], 1)
        self.assertEqual(sem["itens"][0]["silencio"], {"ativo": False, "hold": False, "motivo": None, "ate_utc": None})
        self.bridge.silenced[LEAD] = {"hold": False, "reason": "leitura", "until": int((NOW.timestamp() + 540) * 1000)}
        self.service.reconciliar(NOW + timedelta(seconds=10), force=True)
        sem = self.service.listar(fila="sem_responsavel", username="ana", ver_todos=False, now=NOW)
        self.assertEqual(sem["itens"][0]["silencio"]["motivo"], "leitura")
        self.assertEqual(sem["itens"][0]["silencio"]["ate_utc"], (NOW + timedelta(seconds=540)).isoformat())


if __name__ == "__main__":
    import unittest
    unittest.main()
