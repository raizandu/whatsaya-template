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
        self.assertIn("Recusar ligações", connection)
        self.assertIn("Ler mensagens de grupos", connection)
        self.assertIn("Espera inicial", connection)
        self.assertIn("O que está incluído", subscription)
        self.assertNotIn("/api/usage", subscription)

    def test_customer_identity_is_configurable_and_examples_are_neutral(self):
        app = self._read("panel/static/app.js")
        server = self._read("panel/server.py")
        example = self._read("panel/panel.config.example.json")
        views = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "panel/static/views").glob("*.js")
        )
        self.assertIn("assistant_name", server)
        self.assertIn("assistant_name", example)
        self.assertIn("assistantName", app)
        self.assertNotIn("Plano WhatsAYA", server + example + views)
        self.assertNotIn("AYA atendendo", views)

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
        # Quatro cores de marca + branco + os tons derivados fixados no token layer do
        # Aya Design System (sombreamento OKLCH das cores de marca) e as superfícies
        # tonais do tema escuro. Nenhum outro hex entra no painel.
        brand = {"#F26E22", "#F0E7DD", "#4CDE59", "#070B0D", "#FFFFFF"}
        derived = {
            "#DF651E", "#CC5C1B", "#B45016", "#A84A14",   # --orange-hover/active/edge/deep
            "#45CC51", "#3EB948", "#36A63F", "#226F28",   # --green-hover/active/edge/deep
            "#182026",                                    # --ink-hover
            "#222628", "#25282A", "#2A2D2F",              # --surface-2/3/4 (escuro)
        }
        self.assertLessEqual(bases, brand | derived)

    def test_agenda_can_refresh_now_and_when_the_tab_becomes_visible(self):
        agenda = self._read("panel/static/views/agenda.js")
        lib = self._read("panel/static/lib.js")
        self.assertIn("Atualizar", agenda)
        self.assertIn("visibilitychange", agenda)
        self.assertIn("addEventListener('focus'", agenda)
        self.assertIn("cache: 'no-store'", lib)

    def test_short_agenda_events_keep_time_title_and_badge_legible(self):
        agenda = self._read("panel/static/views/agenda.js")
        theme = self._read("panel/static/theme.css")
        self.assertIn("MIN_EVENT_HEIGHT = 36", agenda)
        self.assertIn("naturalHeight < MIN_EVENT_HEIGHT", agenda)
        self.assertIn("compact ? ' compact'", agenda)
        self.assertIn(".agenda-event.compact", theme)

    def test_lead_workspace_keeps_chat_scroll_and_controls_in_header(self):
        app = self._read("panel/static/app.js")
        lead = self._read("panel/static/views/lead.js")
        theme = self._read("panel/static/theme.css")

        self.assertIn("lead-page-main", app)
        self.assertIn('class="lead-header-actions"', lead)
        self.assertIn("Pausar follow-up", lead)
        self.assertIn("Silenciar 10 min", lead)
        self.assertIn("Desligar IA", lead)
        self.assertIn("overflow-y: auto; overscroll-behavior: contain", theme)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto", theme)

    def test_sidebar_groups_navigation_and_collapses_to_an_icon_rail(self):
        app = self._read("panel/static/app.js")
        index = self._read("panel/static/index.html")
        theme = self._read("panel/static/theme.css")

        self.assertIn("const NAV_GROUPS", app)
        self.assertIn('class="sidebar-content"', app)
        self.assertIn('class="sidebar-footer"', app)
        self.assertIn('class="sidebar-rail"', app)
        self.assertIn("event.key.toLowerCase() === 'b'", app)
        self.assertIn("aria-current=${active ? 'page' : null}", app)
        self.assertIn("flaticon-uicons@3.3.1", index)
        self.assertIn("--sidebar-width: 240px", theme)
        self.assertIn("overflow-y: auto; overscroll-behavior: contain", theme)
        self.assertIn("repeat(8, minmax(44px, 1fr))", theme)

    def test_sidebar_connection_card_shows_the_live_whatsapp_number(self):
        app = self._read("panel/static/app.js")
        theme = self._read("panel/static/theme.css")

        self.assertIn("status.connected_phone", app)
        self.assertIn('class="conn-phone"', app)
        self.assertIn(".conn-card .conn-phone", theme)

    def test_client_detail_promotes_onboarding_into_the_operational_dossier(self):
        app = self._read("panel/static/app.js")
        clients = self._read("panel/static/views/clients.js")
        management = self._read("panel/static/management.css")

        self.assertIn("client-page-main", app)
        self.assertIn("ONBOARDING_STATUSES", clients)
        self.assertIn('class="mg-client-dossier"', clients)
        self.assertIn('class="mg-client-profile"', clients)
        self.assertIn('role="tablist"', clients)
        self.assertIn("Finalizar onboarding", clients)
        self.assertIn("status: 'active'", clients)
        self.assertIn(".mg-client-tabs { position: sticky", management)
        self.assertIn(".mg-client-stage summary > i", management)

    def test_client_edit_promotes_installation_and_health_credentials(self):
        clients = self._read("panel/static/views/clients.js")
        management = self._read("panel/static/management.css")

        installation = clients.index("Ambiente e monitoramento")
        contact = clients.index("Nome do contato")
        self.assertLess(installation, contact)
        self.assertIn("Link do ambiente", clients)
        self.assertIn("Chave da API de health", clients)
        self.assertIn("não use API_SERVER_KEY", clients)
        self.assertIn("!initial.id", clients)
        self.assertIn('class="mg-dossier-history mg-health-section"', clients)
        self.assertIn("polling automático a cada ${pollMinutes} min", clients)
        self.assertIn("MONITORING_SHORT_LABEL", clients)
        self.assertIn('class="mg-client-state-row"', clients)
        self.assertIn('class="mg-client-row-status"', clients)
        self.assertIn("<${InstallationStatusTag} client=${c}/>", clients)
        self.assertIn("<th>Pós-venda</th>", clients)
        self.assertIn("Abrir painel", clients)
        self.assertIn(".mg-installation-setup", management)

    def test_management_module_is_gated_and_reachable_from_the_lead(self):
        app = self._read("panel/static/app.js")
        lead = self._read("panel/static/views/lead.js")
        clients = self._read("panel/static/views/clients.js")
        index = self._read("panel/static/index.html")
        self.assertIn("import Clients, { ClientDetail } from './views/clients.js'", app)
        self.assertIn("group.feature === 'management' && managementOn", app)
        self.assertIn("view.startsWith('client/')", app)
        self.assertIn("/api/actions/management/client-from-lead", lead)
        self.assertIn("Virou cliente", lead)
        self.assertIn("detail.client", lead)
        self.assertIn("/api/management/clients", clients)
        self.assertIn("client-status", clients)
        self.assertIn("onboarding-step", clients)
        self.assertNotIn("/api/usage", clients)
        self.assertIn('href="/static/management.css"', index)
        finance = self._read("panel/static/views/finance.js")
        self.assertIn("import Finance from './views/finance.js'", app)
        self.assertIn("/api/management/finance?period=", finance)
        for action in ("charge-pay", "charge-reopen", "charge-adhoc", "cost-upsert", "cost-plan-upsert", "cost-plan-end"):
            self.assertIn(action, finance)
        self.assertNotIn("/api/usage", finance)
        self.assertIn("Senha SSH", clients)
        tickets = self._read("panel/static/views/tickets.js")
        self.assertIn("import Tickets from './views/tickets.js'", app)
        self.assertIn("{ label: 'Gestão', ids: ['clients', 'tickets', 'finance'], feature: 'management' }", app)
        self.assertIn("/api/management/tickets", tickets)
        for action in ("ticket-create", "ticket-status", "ticket-comment", "ticket-update"):
            self.assertIn(action, tickets)
        self.assertNotIn("/api/usage", tickets)
        self.assertIn("type=\"password\"", clients)
        self.assertNotIn("#", self._read("panel/static/management.css").replace("#app", ""))

    def test_dark_mode_contract_and_theme_toggle(self):
        theme = self._read("panel/static/theme.css")
        app = self._read("panel/static/app.js")
        index = self._read("panel/static/index.html")

        # CSS Dark mode variables and rules
        self.assertIn(":root.dark,", theme)
        self.assertIn('[data-theme="dark"]', theme)
        self.assertIn("color-scheme: dark", theme)
        self.assertIn(".dark .sidebar", theme)
        self.assertIn(".dark .btn.primary", theme)

        # App.js theme management and persistence
        self.assertIn("whatsaya_theme", app)
        self.assertIn("toggleTheme", app)
        self.assertIn('class="theme-toggle"', app)
        self.assertIn('class="theme-toggle-btn"', app)

        # Anti-FOUC inline script in index.html
        self.assertIn("whatsaya_theme", index)
        self.assertIn("classList.add('dark')", index)


if __name__ == "__main__":
    unittest.main()

