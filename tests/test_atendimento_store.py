"""Store de atendimento no `panel.db`: protocolo, responsável, eventos e cursor."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import atendimento_store as store  # noqa: E402

LEAD = "5547999414105@s.whatsapp.net"
LEAD2 = "5511952134536@s.whatsapp.net"
# 15/09/2026 13:00 UTC = 10:00 em São Paulo; protocolo usa o dia comercial.
NOW = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)


class AtendimentoStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="whatsaya-atd-")
        self.db = Path(self.tmp.name) / "panel.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_abrir_gera_protocolo_sequencial_por_dia_e_evento(self):
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        b = store.abrir(self.db, contato=LEAD2, responsavel_tipo="nenhum", aberto_at=NOW, now=NOW)
        self.assertEqual(a["protocolo"], "20260915-001")
        self.assertEqual(b["protocolo"], "20260915-002")
        self.assertEqual(a["status"], "aberto")
        self.assertEqual(a["canal"], "whatsapp")
        self.assertEqual(a["responsavel_tipo"], "ia")
        self.assertIsNone(a["responsavel_user"])
        self.assertEqual([e["tipo"] for e in store.eventos(self.db, a["id"])], ["aberto"])
        # Dia seguinte recomeça a numeração.
        amanha = NOW + timedelta(days=1)
        c = store.abrir(self.db, contato="5511900000000@s.whatsapp.net", responsavel_tipo="ia", aberto_at=amanha, now=amanha)
        self.assertEqual(c["protocolo"], "20260916-001")

    def test_um_aberto_por_contato(self):
        store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        with self.assertRaises(store.AtendimentoAberto):
            store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        self.assertEqual(len(store.listar_abertos(self.db)), 1)

    def test_assumir_devolver_resolver_gravam_carimbos_e_eventos(self):
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        t1 = NOW + timedelta(minutes=5)
        a = store.definir_responsavel(self.db, a["id"], tipo="atendente", user="ana", ator="ana", evento="assumido", now=t1)
        self.assertEqual((a["responsavel_tipo"], a["responsavel_user"]), ("atendente", "ana"))
        self.assertEqual(a["assumido_utc"], t1.isoformat())
        t2 = NOW + timedelta(minutes=9)
        a = store.definir_responsavel(self.db, a["id"], tipo="ia", user=None, ator="ana", evento="devolvido", now=t2)
        self.assertEqual(a["responsavel_tipo"], "ia")
        self.assertIsNone(a["assumido_utc"])
        t3 = NOW + timedelta(minutes=20)
        a = store.resolver(self.db, a["id"], motivo="manual", ator="ana", now=t3)
        self.assertEqual((a["status"], a["resolvido_motivo"], a["resolvido_utc"]), ("resolvido", "manual", t3.isoformat()))
        self.assertEqual(store.aberto_do_contato(self.db, LEAD), None)
        self.assertEqual(
            [(e["tipo"], e["ator"]) for e in store.eventos(self.db, a["id"])],
            [("aberto", "sistema"), ("assumido", "ana"), ("devolvido", "ana"), ("resolvido", "ana")],
        )
        # Resolver de novo é idempotente.
        self.assertEqual(store.resolver(self.db, a["id"], motivo="manual", ator="ana", now=t3)["resolvido_utc"], t3.isoformat())

    def test_registrar_mensagem_marca_primeira_resposta_e_ultima(self):
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        t1 = NOW + timedelta(minutes=1)
        a = store.registrar_mensagem(self.db, a["id"], at=t1, autor="ia", user=None, now=t1)
        self.assertEqual(a["primeira_resposta_utc"], t1.isoformat())
        self.assertEqual((a["primeira_resposta_autor"], a["primeira_resposta_user"]), ("ia", None))
        self.assertEqual((a["ultima_msg_utc"], a["ultima_msg_autor"]), (t1.isoformat(), "ia"))
        t2 = NOW + timedelta(minutes=2)
        a = store.registrar_mensagem(self.db, a["id"], at=t2, autor="contato", user=None, now=t2)
        self.assertEqual(a["primeira_resposta_autor"], "ia", "primeira resposta não muda depois de marcada")
        self.assertEqual(a["ultima_msg_autor"], "contato")
        # Mensagem antiga (replay) não retrocede a última.
        a = store.registrar_mensagem(self.db, a["id"], at=t1, autor="ia", user=None, now=t2)
        self.assertEqual(a["ultima_msg_autor"], "contato")

    def test_primeira_resposta_do_painel_guarda_autor_e_usuario(self):
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="nenhum", aberto_at=NOW, now=NOW)
        a = store.registrar_mensagem(self.db, a["id"], at=NOW, autor="painel", user="ana", now=NOW)
        self.assertEqual((a["primeira_resposta_autor"], a["primeira_resposta_user"]), ("painel", "ana"))

    def test_marcar_handoff_tira_responsavel_e_evento_extra(self):
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        t1 = NOW + timedelta(minutes=3)
        a = store.marcar_handoff(self.db, a["id"], detalhe="quer falar com uma pessoa", now=t1)
        self.assertEqual((a["responsavel_tipo"], a["handoff_utc"]), ("nenhum", t1.isoformat()))
        # Assumir limpa o handoff; tirar responsável (sem humano) preserva.
        a = store.definir_responsavel(self.db, a["id"], tipo="atendente", user="ana", ator="ana", evento="assumido", now=t1)
        self.assertIsNone(a["handoff_utc"])
        rev_antes = store.rev(self.db)
        store.adicionar_evento(self.db, a["id"], tipo="reatribuido", ator="admin", detalhe="ana → bruno", now=t1)
        self.assertGreater(store.rev(self.db), rev_antes)
        self.assertEqual(
            [(e["tipo"], e["ator"], e["detalhe"]) for e in store.eventos(self.db, a["id"])][1:],
            [("handoff", "ia", "quer falar com uma pessoa"), ("assumido", "ana", None), ("reatribuido", "admin", "ana → bruno")],
        )

    def test_meta_set_nao_avanca_rev(self):
        store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        antes = store.rev(self.db)
        store.meta_set(self.db, "cursor", "1")
        self.assertEqual(store.rev(self.db), antes)

    def test_rev_avanca_a_cada_escrita_e_listagem_filtra_por_rev(self):
        self.assertEqual(store.rev(self.db), 0)
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        r1 = store.rev(self.db)
        self.assertGreater(r1, 0)
        store.abrir(self.db, contato=LEAD2, responsavel_tipo="nenhum", aberto_at=NOW, now=NOW)
        r2 = store.rev(self.db)
        self.assertGreater(r2, r1)
        mudados = store.listar_abertos(self.db, desde_rev=r1)
        self.assertEqual([m["contato"] for m in mudados], [LEAD2])
        store.definir_responsavel(self.db, a["id"], tipo="atendente", user="ana", ator="ana", evento="assumido", now=NOW)
        self.assertEqual({m["contato"] for m in store.listar_abertos(self.db, desde_rev=r2)}, {LEAD})

    def test_meta_guarda_cursor(self):
        self.assertIsNone(store.meta_get(self.db, "cursor"))
        store.meta_set(self.db, "cursor", "123.5")
        self.assertEqual(store.meta_get(self.db, "cursor"), "123.5")

    def test_historico_do_contato_inclui_resolvidos(self):
        a = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW, now=NOW)
        store.resolver(self.db, a["id"], motivo="inatividade", ator="sistema", now=NOW + timedelta(hours=25))
        b = store.abrir(self.db, contato=LEAD, responsavel_tipo="ia", aberto_at=NOW + timedelta(hours=26), now=NOW + timedelta(hours=26))
        historico = store.listar_do_contato(self.db, LEAD)
        self.assertEqual([h["id"] for h in historico], [b["id"], a["id"]], "mais recente primeiro")
        self.assertEqual(store.aberto_do_contato(self.db, LEAD)["id"], b["id"])


if __name__ == "__main__":
    unittest.main()
