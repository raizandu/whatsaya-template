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

    def test_contacts_master_detail_has_composer_and_short_polling(self):
        app = self._read("panel/static/app.js")
        contacts = self._read("panel/static/views/contacts.js")
        conversation = self._read("panel/static/views/conversation.js")
        contacts_css = self._read("panel/static/contacts.css")

        # Roteamento: #contacts/<chat_id> vira a mesma tela Contacts, com chatId.
        self.assertIn("contactsRoute = view.startsWith('contacts/')", app)
        self.assertIn("contacts-page-main", app)

        # A tela reaproveita a timeline e a caixa de resposta de conversation.js,
        # nunca duplica lógica de mensagem.
        self.assertIn("import { Conversation, Composer } from './conversation.js'", contacts)
        self.assertNotIn("function ConversationMessage", contacts)

        # Polling de 5s só com um chat selecionado; sem seleção não fica preso
        # repetindo request.
        self.assertIn("every: chatId ? 5000 : 0", contacts)

        # Seleção no hash, mestre-detalhe some numa coluna só no mobile.
        self.assertIn("go(`contacts/${encodeURIComponent(contact.chat_id)}`)", contacts)
        self.assertIn(".contacts-master-detail.has-selection .contacts-master { display: none; }", contacts_css)

        # Composer nunca finge envio: só chama /api/actions/reply e só limpa a
        # caixa depois do 200; fica desabilitado com explicação quando bloqueado
        # ou com a ponte fora do ar.
        self.assertIn("post('/api/actions/reply'", conversation)
        self.assertIn("blocked", conversation)
        self.assertIn("status.bridge === 'up'", conversation)
        self.assertIn("Ponte do WhatsApp fora do ar", conversation)

    def test_shell_has_sticky_header_hybrid_drawer_search_and_dock(self):
        app = self._read("panel/static/app.js")
        shell = self._read("panel/static/shell.js")
        index = self._read("panel/static/index.html")
        theme = self._read("panel/static/theme.css")

        self.assertIn("const NAV_GROUPS", app)
        self.assertIn("from './shell.js'", app)
        self.assertIn("event.key.toLowerCase() === 'k'", app)   # Ctrl/Cmd+K abre a busca
        self.assertIn("event.key.toLowerCase() === 'b'", app)   # Ctrl/Cmd+B fixa o menu
        self.assertIn('class="shell-header"', shell)
        self.assertIn('aria-label="Localização atual"', shell)
        self.assertIn('class="shell-search-trigger"', shell)
        self.assertIn("aria-current=${isActive ? 'page' : null}", shell)
        self.assertIn("whatsaya_nav_width", shell)
        self.assertIn("whatsaya_nav_pinned", shell)
        self.assertIn("NAV_MIN_WIDTH = 200", shell)
        self.assertIn("NAV_MAX_WIDTH = 420", shell)
        self.assertIn('class="shell-nav-resize"', shell)
        self.assertIn('class="shell-dock"', shell)
        self.assertIn("flaticon-uicons@3.3.1", index)
        self.assertIn("--shell-h: 48px", theme)
        self.assertIn("translate3d(-100%, 0, 0)", theme)
        self.assertIn("overflow-y: auto; overscroll-behavior: contain", theme)
        self.assertIn("padding-left: calc(var(--nav-width) + 20px)", theme)
        self.assertIn("repeat(6, minmax(44px, 1fr))", theme)

    def test_sidebar_connection_card_shows_the_live_whatsapp_number(self):
        app = self._read("panel/static/app.js")
        shell = self._read("panel/static/shell.js")
        theme = self._read("panel/static/theme.css")

        self.assertIn("status.connected_phone", app)
        self.assertIn('class="conn-phone"', shell)
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
        self.assertIn(".dark .btn.primary", theme)
        # A casca (header e gaveta) é preta nos dois temas, por token fixo.
        self.assertIn("--shell-bg: #070B0D", theme)

        # App.js theme management and persistence; o botão de tema vive no header (shell.js)
        self.assertIn("whatsaya_theme", app)
        self.assertIn("toggleTheme", app)
        self.assertIn("onToggleTheme", self._read("panel/static/shell.js"))

        # Anti-FOUC inline script in index.html
        self.assertIn("whatsaya_theme", index)
        self.assertIn("classList.add('dark')", index)


# Blocos de tokens do theme.css: `:root`, `.dark`/`[data-theme="dark"]` e o
# `@media (prefers-color-scheme: dark)`. Só ali um valor cru (hex, rgb, hsl,
# duração, cubic-bezier) pode nascer; o resto do CSS consome via var().
TOKEN_BLOCK_PREFIXES = (":root", "[data-theme=\"dark\"]", ".dark", "@media (prefers-color-scheme: dark)")
PANEL_STATIC = ROOT / "panel/static"
DESIGN_SYSTEM = ROOT / "Aya Design System"

# Paleta fechada: 4 cores de marca + branco + os tons derivados fixados no
# token layer (sombreamento OKLCH das cores de marca) + superfícies tonais do
# tema escuro. Qualquer hex fora daqui é regressão, no painel e no kit.
BRAND_HEX = {"#F26E22", "#F0E7DD", "#4CDE59", "#070B0D", "#FFFFFF"}
DERIVED_HEX = {
    "#DF651E", "#CC5C1B", "#B45016", "#A84A14",   # --primary-hover/active/edge/deep
    "#9B4412", "#86390F",                         # --deep-hover/--deep-edge
    "#45CC51", "#3EB948", "#36A63F", "#226F28",   # --green-hover/active/edge/deep
    "#182026",                                    # --ink-hover
    "#222628", "#25282A", "#2A2D2F",              # --surface-2/3/4 (escuro)
    "#352A1D", "#1A1E20",                         # só em comentário: tint da sombra e surface-1 resolvida
}


def css_rules(text: str):
    """Blocos folha `seletor { declarações }`, com número da linha de abertura.

    Regex de bloco mais interno: dentro de um @media os blocos filhos aparecem
    como regras normais, e o próprio @media (já sem filhos) some por não ter
    declaração.
    """
    rules = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        selector = match.group(1).strip().split("\n")[-1].strip()
        line = text.count("\n", 0, match.start(2)) + 1
        rules.append((selector, match.group(2), line))
    return rules


def declarations(body: str):
    for raw in body.split(";"):
        if ":" in raw:
            prop, value = raw.split(":", 1)
            yield prop.strip().lstrip("/*").strip(), value.strip()


def is_token_block(selector: str) -> bool:
    return selector.startswith(TOKEN_BLOCK_PREFIXES) and not selector.startswith((".dark .", ".dark body"))


def panel_css_files():
    return sorted(PANEL_STATIC.rglob("*.css"))


class PanelMaterialityContractTest(unittest.TestCase):
    """O CSS do painel consome o token layer do Aya Design System; nunca cria valor cru.

    É a camada automatizada da regra "nada de slop": cor, sombra, movimento,
    camada e tipografia vêm dos tokens definidos no theme.css. Um valor literal
    fora dos blocos de token quebra aqui antes de chegar ao commit e ao CI.
    """

    def _violations(self, check):
        found = []
        for path in panel_css_files():
            text = path.read_text(encoding="utf-8")
            for selector, body, line in css_rules(text):
                token_block = path.name == "theme.css" and is_token_block(selector)
                for prop, value in declarations(body):
                    reason = check(prop, value, token_block, selector)
                    if reason:
                        found.append(f"{path.name}:{line} {selector} -> {prop}: {value[:80]} ({reason})")
        return found

    def test_colors_come_from_tokens_not_raw_rgb_or_hsl(self):
        raw = re.compile(r"\b(?:rgba?|hsla?)\(")
        tinted = re.compile(r"hsla?\(\s*var\(--shadow-tint\)")

        def check(prop, value, token_block, _selector):
            if token_block:
                return None
            if raw.search(tinted.sub("", value)):
                return "cor crua; use um token ou hsl(var(--shadow-tint) / a)"
            return None

        self.assertEqual(self._violations(check), [])

    def test_motion_uses_duration_and_easing_tokens(self):
        literal_time = re.compile(r"(?<![\w.-])(?!0m?s\b)\d*\.?\d+m?s\b")
        keyword_ease = re.compile(r"(?<![\w-])ease(?:-in|-out|-in-out)?\b")

        def check(prop, value, token_block, _selector):
            if token_block or not prop.startswith(("transition", "animation")):
                return None
            if prop == "animation" and "infinite" in value:
                return None  # indicadores em loop (spinner, pulso) têm ritmo próprio
            if literal_time.search(value):
                return "duração literal; use var(--duration-*)"
            if "cubic-bezier(" in value or keyword_ease.search(value):
                return "easing literal; use var(--ease-*)"
            return None

        self.assertEqual(self._violations(check), [])

    def test_shadows_and_layers_use_tokens(self):
        hex_color = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
        # camada global (>= 10) só por token; empilhamento local dentro de um componente pode usar 0-9
        z_ok = re.compile(r"^(?:var\(--z-[a-z-]+\)|calc\(var\(--z-[a-z-]+\)[^)]*\)|auto|-?[0-9])$")

        def check(prop, value, token_block, _selector):
            if token_block:
                return None
            if prop == "box-shadow" or ("shadow" in prop and prop.startswith("--")):
                if hex_color.search(value):
                    return "hex dentro de sombra; use --shadow-*, --inset-highlight ou hsl(var(--shadow-tint) / a)"
            if prop == "z-index" and not z_ok.match(value):
                return "z-index de camada global sem token; use var(--z-*)"
            return None

        self.assertEqual(self._violations(check), [])

    def test_no_gradients_and_important_only_for_reduced_motion(self):
        def check(prop, value, _token_block, _selector):
            if re.search(r"(?<!repeating-)(?:linear|radial|conic)-gradient\(", value):
                return "gradiente; o DS é chapado (hachura repeating-* é a única exceção)"
            if "!important" in value and not prop.startswith(("transition", "animation")):
                return "!important fora do bloco de prefers-reduced-motion"
            return None

        self.assertEqual(self._violations(check), [])

    def test_uppercase_is_reserved_for_small_labels(self):
        # Título nunca em caixa alta. Só rótulo/eyebrow (≤ 11px) pode usar uppercase.
        found = []
        for path in panel_css_files():
            for selector, body, line in css_rules(path.read_text(encoding="utf-8")):
                decls = dict(declarations(body))
                if decls.get("text-transform") != "uppercase":
                    continue
                size = re.match(r"(\d+(?:\.\d+)?)px", decls.get("font-size", ""))
                if not size or float(size.group(1)) > 11:
                    found.append(f"{path.name}:{line} {selector} (font-size {decls.get('font-size', 'herdado')})")
        self.assertEqual(found, [])

    def test_fonts_come_from_the_token_layer(self):
        allowed = re.compile(r'^(?:var\(--(?:font|mono)\)|inherit|"Open Sans"|"Geist")')

        def check(prop, value, _token_block, _selector):
            if prop == "font-family" and not allowed.match(value):
                return "fonte fora do DS; use var(--font) ou var(--mono)"
            return None

        self.assertEqual(self._violations(check), [])

    def test_every_css_variable_used_is_defined(self):
        defined, used = set(), {}
        for path in panel_css_files():
            defined |= set(re.findall(r"(--[a-z0-9-]+)\s*:", path.read_text(encoding="utf-8")))
        for path in PANEL_STATIC.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            defined |= set(re.findall(r"[\'\"`](--[a-z0-9-]+)", text)) | set(re.findall(r"(--[a-z0-9-]+):", text))
        for path in list(panel_css_files()) + list(PANEL_STATIC.rglob("*.js")):
            for match in re.finditer(r"var\((--[a-z0-9-]+)", path.read_text(encoding="utf-8")):
                used.setdefault(match.group(1), set()).add(path.name)
        missing = {name: sorted(files) for name, files in used.items() if name not in defined}
        self.assertEqual(missing, {})

    def test_design_system_sources_stay_in_the_brand_palette(self):
        sources = [DESIGN_SYSTEM / "colors_and_type.css"]
        sources += sorted((DESIGN_SYSTEM / "preview").rglob("*.html"))
        sources += sorted((DESIGN_SYSTEM / "ui_kits").rglob("*.jsx"))
        offenders = {}
        for path in sources:
            for color in set(re.findall(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\b", path.read_text(encoding="utf-8"))):
                if color[:7].upper() not in BRAND_HEX | DERIVED_HEX:
                    offenders.setdefault(path.name, set()).add(color)
        self.assertEqual(offenders, {})

    def test_design_system_tokens_do_not_hardcode_motion_outside_the_token_layer(self):
        text = (DESIGN_SYSTEM / "colors_and_type.css").read_text(encoding="utf-8")
        for selector, body, line in css_rules(text):
            if is_token_block(selector):
                continue
            for prop, value in declarations(body):
                if prop.startswith(("transition", "animation")) and re.search(r"\d+m?s\b|cubic-bezier\(", value):
                    self.fail(f"colors_and_type.css:{line} {selector} -> {prop}: {value}")


if __name__ == "__main__":
    unittest.main()

