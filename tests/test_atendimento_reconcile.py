"""Reconciliação pura do atendimento: mensagens + bridge + contatos + usuários → mudanças."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import atendimento_reconcile as rec  # noqa: E402

LEAD = "5547999414105@s.whatsapp.net"
LEAD2 = "5511952134536@s.whatsapp.net"
NOW = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def msg(contato, at, autor, user=None, mid=""):
    return rec.Mensagem(contato=contato, at=at, autor=autor, user=user, message_id=mid)


def aberto(contato, tipo="ia", user=None, **extra):
    row = {
        "id": extra.pop("id", 1), "contato": contato, "status": "aberto", "responsavel_tipo": tipo,
        "responsavel_user": user, "aberto_utc": (NOW - 2 * H).isoformat(), "primeira_resposta_utc": None,
        "primeira_resposta_autor": None, "assumido_utc": None, "handoff_utc": None,
        "resolvido_utc": None, "resolvido_motivo": None, "ultima_msg_utc": (NOW - H).isoformat(),
        "ultima_msg_autor": "ia",
    }
    row.update(extra)
    return row


def snap(**kw):
    base = dict(
        now=NOW, abertos=[], mensagens=[], silenciados={},
        contatos={LEAD: {"blocked": False, "ai_enabled": True}, LEAD2: {"blocked": False, "ai_enabled": True}},
        usuarios_ativos={"ana", "bruno"},
    )
    base.update(kw)
    return rec.Snapshot(**base)


def ops(changes, op):
    return [c for c in changes if c["op"] == op]


class AbrirTest(unittest.TestCase):
    def test_mensagem_recebida_sem_aberto_abre_na_hora_da_mensagem_com_ia(self):
        t = NOW - timedelta(minutes=10)
        changes = rec.reconciliar(snap(mensagens=[msg(LEAD, t, "contato", mid="m1")]))
        self.assertEqual(changes, [
            {"op": "abrir", "contato": LEAD, "responsavel_tipo": "ia", "aberto_at": t, "ultima_msg_autor": "contato"},
        ])

    def test_ia_desligada_abre_sem_responsavel(self):
        t = NOW - timedelta(minutes=10)
        changes = rec.reconciliar(snap(
            mensagens=[msg(LEAD, t, "contato")],
            contatos={LEAD: {"blocked": False, "ai_enabled": False}},
        ))
        self.assertEqual(ops(changes, "abrir")[0]["responsavel_tipo"], "nenhum")

    def test_bloqueado_nunca_abre(self):
        changes = rec.reconciliar(snap(
            mensagens=[msg(LEAD, NOW, "contato")],
            contatos={LEAD: {"blocked": True, "ai_enabled": True}},
        ))
        self.assertEqual(changes, [])

    def test_mensagem_enviada_sem_aberto_nao_abre(self):
        changes = rec.reconciliar(snap(mensagens=[msg(LEAD, NOW, "ia"), msg(LEAD, NOW, "dono")]))
        self.assertEqual(changes, [])

    def test_mensagem_anterior_a_ultima_resolucao_nao_reabre(self):
        t = NOW - H
        changes = rec.reconciliar(snap(
            mensagens=[msg(LEAD, t, "contato")],
            ultima_resolucao={LEAD: NOW - timedelta(minutes=30)},
        ))
        self.assertEqual(changes, [])

    def test_mensagem_depois_de_resolvido_abre_outro(self):
        t = NOW - timedelta(minutes=5)
        changes = rec.reconciliar(snap(
            mensagens=[msg(LEAD, t, "contato")],
            ultima_resolucao={LEAD: NOW - timedelta(minutes=30)},
        ))
        self.assertEqual(len(ops(changes, "abrir")), 1)

    def test_primeira_execucao_janela_de_sete_dias_abre_e_registra_a_conversa(self):
        """Bootstrap: o chamador passa 7 dias de mensagens; a conversa inteira vira um
        atendimento aberto na primeira mensagem do contato, com primeira resposta e última."""
        t0 = NOW - timedelta(days=3)
        changes = rec.reconciliar(snap(mensagens=[
            msg(LEAD, t0, "contato"),
            msg(LEAD, t0 + timedelta(minutes=1), "ia"),
            msg(LEAD, t0 + timedelta(minutes=5), "contato"),
            msg(LEAD2, NOW - timedelta(days=9), "contato"),  # fora da janela: o chamador não passaria, mas se passar abre também
        ]))
        self.assertEqual([c["contato"] for c in ops(changes, "abrir")], [LEAD2, LEAD], "ordem cronológica")
        registros = ops(changes, "mensagem")
        self.assertEqual([(r["autor"], r["at"]) for r in registros], [
            ("ia", t0 + timedelta(minutes=1)), ("contato", t0 + timedelta(minutes=5)),
        ])


class DonoTest(unittest.TestCase):
    def test_mensagem_do_dono_assume_se_nao_havia_humano_e_pede_hold(self):
        t = NOW - timedelta(minutes=2)
        changes = rec.reconciliar(snap(abertos=[aberto(LEAD, "ia")], mensagens=[msg(LEAD, t, "dono")]))
        self.assertEqual([c["op"] for c in changes], ["mensagem", "responsavel", "hold"])
        self.assertEqual(changes[1], {"op": "responsavel", "contato": LEAD, "tipo": "dono", "user": None,
                                      "ator": "dono", "evento": "assumido", "detalhe": None})
        self.assertEqual(changes[2], {"op": "hold", "contato": LEAD, "ligado": True})

    def test_mensagem_do_dono_nao_rouba_de_atendente(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "atendente", "ana")], mensagens=[msg(LEAD, NOW, "dono")],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
        ))
        self.assertEqual([c["op"] for c in changes], ["mensagem"])

    def test_dono_e_ia_resolvem_por_inatividade_e_liberam_hold(self):
        antigo = (NOW - 25 * H).isoformat()
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "dono", ultima_msg_utc=antigo, id=1), aberto(LEAD2, "ia", ultima_msg_utc=antigo, id=2)],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
            inatividade_h=24,
        ))
        self.assertEqual(changes, [
            {"op": "resolver", "contato": LEAD, "motivo": "inatividade"},
            {"op": "hold", "contato": LEAD, "ligado": False},
            {"op": "resolver", "contato": LEAD2, "motivo": "inatividade"},
        ])

    def test_atendente_nao_resolve_por_inatividade(self):
        antigo = (NOW - 48 * H).isoformat()
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "atendente", "ana", ultima_msg_utc=antigo)],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
        ))
        self.assertEqual(changes, [])


class HandoffTest(unittest.TestCase):
    def test_silencio_por_handoff_tira_da_ia(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "ia")],
            silenciados={LEAD: {"hold": False, "reason": "handoff", "until": NOW + 20 * H}},
        ))
        self.assertEqual(changes, [{"op": "handoff", "contato": LEAD}])

    def test_prazo_expirado_sem_humano_devolve_a_ia_com_evento_automatico(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "nenhum", handoff_utc=(NOW - 25 * H).isoformat())],
        ))
        self.assertEqual(changes, [{"op": "responsavel", "contato": LEAD, "tipo": "ia", "user": None,
                                    "ator": "sistema", "evento": "devolvido_auto", "detalhe": "prazo do handoff expirou"}])

    def test_prazo_expirado_com_ia_desligada_fica_sem_responsavel(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "nenhum", handoff_utc=(NOW - 25 * H).isoformat())],
            contatos={LEAD: {"blocked": False, "ai_enabled": False}},
        ))
        self.assertEqual(changes, [])

    def test_handoff_ja_registrado_nao_repete(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "nenhum", handoff_utc=(NOW - H).isoformat())],
            silenciados={LEAD: {"hold": False, "reason": "handoff", "until": NOW + 20 * H}},
        ))
        self.assertEqual(changes, [])


class HoldTest(unittest.TestCase):
    def test_humano_sem_hold_recebe_hold(self):
        changes = rec.reconciliar(snap(abertos=[aberto(LEAD, "atendente", "ana")]))
        self.assertEqual(changes, [{"op": "hold", "contato": LEAD, "ligado": True}])

    def test_hold_do_painel_sem_humano_e_liberado(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "ia")],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
        ))
        self.assertEqual(changes, [{"op": "hold", "contato": LEAD, "ligado": False}])

    def test_hold_com_outro_motivo_nao_e_tocado(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "ia")],
            silenciados={LEAD: {"hold": True, "reason": "dono", "until": None}},
        ))
        self.assertEqual(changes, [])

    def test_silencio_temporizado_de_leitura_nao_e_hold(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "ia")],
            silenciados={LEAD: {"hold": False, "reason": "leitura", "until": NOW + timedelta(minutes=9)}},
        ))
        self.assertEqual(changes, [])


class UsuariosEBloqueioTest(unittest.TestCase):
    def test_atendente_desativado_perde_o_atendimento(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "atendente", "carla")],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
            usuarios_ativos={"ana"},
        ))
        self.assertEqual(changes, [
            {"op": "responsavel", "contato": LEAD, "tipo": "nenhum", "user": None, "ator": "sistema",
             "evento": "responsavel_removido", "detalhe": "carla"},
            {"op": "hold", "contato": LEAD, "ligado": False},
        ])

    def test_bloqueio_resolve_e_libera_hold(self):
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "atendente", "ana")],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
            contatos={LEAD: {"blocked": True, "ai_enabled": True}},
        ))
        self.assertEqual(changes, [
            {"op": "resolver", "contato": LEAD, "motivo": "bloqueio"},
            {"op": "hold", "contato": LEAD, "ligado": False},
        ])


class MensagensTest(unittest.TestCase):
    def test_mensagens_registram_primeira_resposta_e_ultima_em_ordem(self):
        t1, t2 = NOW - timedelta(minutes=3), NOW - timedelta(minutes=2)
        changes = rec.reconciliar(snap(
            abertos=[aberto(LEAD, "ia", primeira_resposta_utc=None, ultima_msg_utc=(NOW - H).isoformat(), ultima_msg_autor="contato")],
            mensagens=[msg(LEAD, t2, "contato"), msg(LEAD, t1, "painel", user="ana")],
        ))
        self.assertEqual(changes, [
            {"op": "mensagem", "contato": LEAD, "at": t1, "autor": "painel", "user": "ana"},
            {"op": "mensagem", "contato": LEAD, "at": t2, "autor": "contato", "user": None},
        ])

    def test_segunda_rodada_com_estado_aplicado_nao_gera_nada(self):
        """Idempotência: aplicar as mudanças e rodar de novo com o mesmo mundo é um no-op."""
        t = NOW - timedelta(minutes=2)
        primeira = rec.reconciliar(snap(abertos=[aberto(LEAD, "ia")], mensagens=[msg(LEAD, t, "dono")]))
        self.assertTrue(primeira)
        depois = aberto(LEAD, "dono", ultima_msg_utc=t.isoformat(), ultima_msg_autor="dono", assumido_utc=t.isoformat())
        segunda = rec.reconciliar(snap(
            abertos=[depois], mensagens=[],
            silenciados={LEAD: {"hold": True, "reason": "painel", "until": None}},
        ))
        self.assertEqual(segunda, [])


if __name__ == "__main__":
    unittest.main()
