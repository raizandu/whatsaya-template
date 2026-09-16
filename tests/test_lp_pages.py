"""Páginas de nicho: validação, renderização do template e publicação no volume."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))
import lp_pages  # noqa: E402

MINI_TEMPLATE = """<title>{{title}}</title><meta name="description" content="{{description}}">
<link rel="canonical" href="{{canonical}}"><h1>{{h1}}</h1><p class="sub">{{!sub_html}}</p>
{{!niche_block}}
<h1 class="compact">{{question}}</h1><p>{{question_sub}}</p><div id="opts-negocio">
{{!options}}
</div><script>const CONFIG = { lpId: {{js:lp_id}}, niche: {{js:niche}}, eventsEndpoint: "/api/lp/event", metaPixelId: {{js:pixel_id}} };</script>
"""
REAL_TEMPLATE = ROOT / "LP" / "quiz.template.html"
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

PSICO = {
    "slug": "psicologos",
    "niche": "Clínica de psicologia",
    "title": "AYA para psicólogos — atendimento no WhatsApp",
    "description": "Veja como a AYA responde, agenda e faz follow-up com pacientes pelo WhatsApp.",
    "h1": "Seu consultório perde paciente enquanto você está em sessão?",
    "sub": "A AYA responde **em segundos** e organiza a agenda.",
    "niche_intro": "Quem procura terapia decide rápido & some se ninguém responde.",
    "niche_pains": "Mensagem chega durante a sessão\nPaciente pergunta valor e some\n",
    "question": "Qual é a sua atuação?",
    "question_sub": "Isso muda o jeito da AYA falar com quem chega.",
    "options": ["Clínico", "Organizacional", "Escolar", "Outro"],
    "pixel_id": "123456789012345",
}


class LpPagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.db = base / "panel.db"
        self.www = base / "www"
        (self.www / "bio").mkdir(parents=True)
        (self.www / "bio" / "index.html").write_text('<meta http-equiv="refresh" content="0; url=/">')
        self.template = base / "quiz.template.html"
        self.template.write_text(MINI_TEMPLATE, encoding="utf-8")
        lp_pages.save_page(self.db, lp_pages.ROOT_PAGE, now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def _publish(self):
        return lp_pages.publish(self.db, www_dir=self.www, template_path=self.template,
                                base_url="https://agenteaya.com", now=NOW)

    def test_clean_page_rejects_bad_slug_pixel_and_options(self):
        for bad in (
            {**PSICO, "slug": "Psicólogos"},
            {**PSICO, "slug": "api"},
            {**PSICO, "slug": "../x"},
            {**PSICO, "pixel_id": "abc"},
            {**PSICO, "options": ["Só uma"]},
            {**PSICO, "title": ""},
        ):
            with self.assertRaises(ValueError, msg=bad):
                lp_pages.clean_page(bad)

    def test_render_escapes_and_fills_everything(self):
        page = lp_pages.save_page(self.db, {**PSICO, "title": "AYA <b>x</b>"}, now=NOW)
        out = lp_pages.render(MINI_TEMPLATE, page, base_url="https://agenteaya.com")
        self.assertNotIn("{{", out)
        self.assertIn("<title>AYA &lt;b&gt;x&lt;/b&gt;</title>", out)
        self.assertIn('href="https://agenteaya.com/psicologos/"', out)
        self.assertIn('<span class="highlight">em segundos</span>', out)
        self.assertIn("decide rápido &amp; some", out)
        self.assertIn("<li>Paciente pergunta valor e some</li>", out)
        self.assertIn('data-value="Organizacional">Organizacional</button>', out)
        self.assertIn('lpId: "psicologos", niche: "Clínica de psicologia"', out)
        self.assertIn('metaPixelId: "123456789012345"', out)

    def test_root_page_has_no_niche_block_and_lp_id_home(self):
        out = lp_pages.render(MINI_TEMPLATE, lp_pages.get_page(self.db, ""), base_url="https://agenteaya.com")
        self.assertNotIn('class="niche"', out)
        self.assertIn('lpId: "home", niche: ""', out)
        self.assertIn('metaPixelId: ""', out)

    def test_publish_writes_pages_sitemap_and_robots(self):
        lp_pages.save_page(self.db, PSICO, now=NOW)
        lp_pages.save_page(self.db, {**PSICO, "slug": "advogados", "niche": "Escritório de advocacia", "enabled": False}, now=NOW)
        written = self._publish()
        self.assertIn("Qual é o seu negócio?", (self.www / "index.html").read_text())
        self.assertIn("Qual é a sua atuação?", (self.www / "psicologos" / "index.html").read_text())
        disabled = (self.www / "advogados" / "index.html").read_text()
        self.assertIn('http-equiv="refresh"', disabled)
        self.assertIn("noindex", disabled)
        sitemap = (self.www / "sitemap.xml").read_text()
        self.assertIn("<loc>https://agenteaya.com/</loc>", sitemap)
        self.assertIn("<loc>https://agenteaya.com/psicologos/</loc>", sitemap)
        self.assertNotIn("advogados", sitemap)
        self.assertIn("Sitemap: https://agenteaya.com/sitemap.xml", (self.www / "robots.txt").read_text())
        self.assertTrue((self.www / "bio" / "index.html").exists(), "bio/ é do redirect, não é página")
        self.assertEqual(len(written), 5)

    def test_deleted_page_leaves_disk_on_next_publish(self):
        lp_pages.save_page(self.db, PSICO, now=NOW)
        self._publish()
        self.assertTrue((self.www / "psicologos").is_dir())
        self.assertTrue(lp_pages.delete_page(self.db, "psicologos"))
        self._publish()
        self.assertFalse((self.www / "psicologos").exists())
        with self.assertRaises(ValueError):
            lp_pages.delete_page(self.db, "")

    @unittest.skipUnless(REAL_TEMPLATE.is_file(), "template mestre só no repositório privado")
    def test_real_template_renders_root_identical_to_the_shipped_lp(self):
        template = REAL_TEMPLATE.read_text(encoding="utf-8")
        out = lp_pages.render(template, lp_pages.get_page(self.db, ""), base_url="https://agenteaya.com")
        self.assertNotIn("{{", out)
        self.assertIn('lpId: "home"', out)
        self.assertIn('data-value="Clínica ou consultório"', out)
        self.assertIn('<link rel="canonical" href="https://agenteaya.com/">', out)


if __name__ == "__main__":
    unittest.main()
