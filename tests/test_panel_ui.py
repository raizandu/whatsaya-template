"""Contratos estáticos para não expor custos técnicos no painel do cliente."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent


class PanelUiContractTest(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_navigation_exposes_subscription_instead_of_technical_costs(self):
        app = self._read("panel/static/app.js")
        self.assertIn("./views/subscription.js", app)
        self.assertIn("id: 'subscription'", app)
        self.assertIn("label: 'Assinatura'", app)
        self.assertNotIn("./views/costs.js", app)
        self.assertNotIn("id: 'costs'", app)
        self.assertFalse((ROOT / "panel/static/views/costs.js").exists())

    def test_customer_views_do_not_render_provider_usage_or_tokens(self):
        overview = self._read("panel/static/views/overview.js")
        connection = self._read("panel/static/views/connection.js")
        lead = self._read("panel/static/views/lead.js")
        for source in (overview, connection, lead):
            self.assertNotIn("/api/usage", source)
            self.assertNotIn("Custo em API", source)
            self.assertNotIn("Consumo da sessão", source)

    def test_whatsapp_settings_and_commercial_subscription_are_visible(self):
        connection = self._read("panel/static/views/connection.js")
        subscription = self._read("panel/static/views/subscription.js")
        self.assertIn("/api/whatsapp-settings", connection)
        self.assertIn("Recusar ligações automaticamente", connection)
        self.assertIn("Ler mensagens de grupos", connection)
        self.assertIn("Agrupar mensagens por", connection)
        self.assertIn("O que está incluído", subscription)
        self.assertNotIn("/api/usage", subscription)

    def test_frontend_uses_only_the_aya_palette(self):
        theme = self._read("panel/static/theme.css")
        expected_tokens = {
            "--aya-orange: #F26E22",
            "--aya-beige: #F0E7DD",
            "--aya-green: #4CDE59",
            "--aya-black: #070B0D",
        }
        for token in expected_tokens:
            self.assertIn(token, theme)

        sources = [theme, self._read("panel/panel.config.example.json")]
        sources.extend(path.read_text(encoding="utf-8") for path in (ROOT / "panel/static").rglob("*.js"))
        colors = set(re.findall(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\b", "\n".join(sources)))
        bases = {color[:7].upper() for color in colors}
        self.assertLessEqual(bases, {"#F26E22", "#F0E7DD", "#4CDE59", "#070B0D", "#FFFFFF"})


if __name__ == "__main__":
    unittest.main()
