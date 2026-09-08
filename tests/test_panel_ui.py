"""Contratos estáticos para não expor custos técnicos no painel do cliente."""
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
