// Casca do painel: navegação, cabeçalho, período e status. As telas ficam em
// views/ e recebem {period, status, config, toast}. Para adicionar uma tela
// para um cliente: crie views/nome.js exportando default e registre em VIEWS.
import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { html, useApi, fmt, PERIODS } from './lib.js';
import { ShellHeader, ShellNav, ShellDock, SearchPalette, useShellNav } from './shell.js';
import Overview from './views/overview.js';
import Kanban from './views/kanban.js';
import Agenda from './views/agenda.js';
import Followups from './views/followups.js';
import Reactivation from './views/reactivation.js';
import Contacts from './views/contacts.js';
import Connection from './views/connection.js';
import Subscription from './views/subscription.js';
import Lead from './views/lead.js';
import Clients, { ClientDetail } from './views/clients.js';
import Finance from './views/finance.js';
import Tickets from './views/tickets.js';

const VIEWS = [
  { id: 'overview', label: 'Visão geral', title: 'Visão geral', icon: 'dashboard', view: Overview, period: true },
  { id: 'kanban', label: 'Kanban', title: 'Funil de leads', icon: 'layout-fluid', view: Kanban },
  { id: 'agenda', label: 'Agenda', title: 'Agenda', icon: 'calendar', view: Agenda },
  { id: 'followups', label: 'Follow-ups', title: 'Follow-ups automáticos', icon: 'clock', view: Followups, period: true },
  { id: 'reactivation', label: 'Reativação', title: 'Reativação manual', icon: 'refresh', view: Reactivation },
  { id: 'contacts', label: 'Contatos', title: 'Contatos', icon: 'address-book', view: Contacts },
  { id: 'connection', label: 'Configurações', title: 'Configurações', icon: 'settings', view: Connection },
  { id: 'subscription', label: 'Assinatura', title: 'Sua assinatura', icon: 'credit-card', view: Subscription },
  { id: 'clients', label: 'Clientes', title: 'Carteira de clientes', icon: 'briefcase', view: Clients },
  { id: 'finance', label: 'Financeiro', title: 'Financeiro da carteira', icon: 'chart-line-up', view: Finance },
  { id: 'tickets', label: 'Tickets', title: 'Tickets de suporte', icon: 'ticket', view: Tickets },
];

const NAV_GROUPS = [
  { label: 'Operação', ids: ['overview', 'kanban', 'agenda'] },
  { label: 'Relacionamento', ids: ['followups', 'reactivation', 'contacts'] },
  { label: 'Conta', ids: ['connection', 'subscription'] },
  // Só na instância: `features.management` no panel.config.json.
  { label: 'Gestão', ids: ['clients', 'tickets', 'finance'], feature: 'management' },
];

function connTone(status) {
  if (!status || status.bridge !== 'up') return { tone: 'bad', label: 'Ponte fora do ar', sub: 'A AYA não recebe mensagens' };
  if (status.connection === 'connected') {
    const phone = status.connected_phone || status.connected_number || null;
    return status.paused
      ? { tone: 'warn', label: 'Conectado · IA pausada', phone, sub: 'Clientes sem resposta automática' }
      : { tone: 'ok', label: 'Conectado', phone, sub: `sessão ${fmt.uptime(status.uptime_s)}` };
  }
  if (status.qr_available) return { tone: 'warn', label: 'Aguardando QR', sub: 'Escaneie no seu WhatsApp' };
  return { tone: 'bad', label: 'Desconectado', sub: 'A AYA não recebe mensagens' };
}

function applyTheme(theme) {
  if (!theme) return;
  for (const [key, value] of Object.entries(theme)) {
    if (typeof value === 'string') document.documentElement.style.setProperty(`--${key}`, value);
  }
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Bom dia.';
  if (hour < 18) return 'Boa tarde.';
  return 'Boa noite.';
}

function getInitialTheme() {
  try {
    const stored = localStorage.getItem('whatsaya_theme');
    if (stored === 'dark' || stored === 'light') return stored;
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
  } catch (e) {}
  return 'light';
}

function updateThemeDom(theme) {
  if (theme === 'dark') {
    document.documentElement.classList.add('dark');
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.classList.remove('dark');
    document.documentElement.setAttribute('data-theme', 'light');
  }
}

function App() {
  const [view, setView] = useState(() => location.hash.replace('#', '').split('?')[0] || 'overview');
  const [period, setPeriod] = useState('7d');
  const nav = useShellNav();
  const [searchOpen, setSearchOpen] = useState(false);
  const [theme, setTheme] = useState(getInitialTheme);
  const [toast, setToastText] = useState(null);
  const config = useApi('/api/config').data;
  const me = useApi('/api/me').data;
  const status = useApi('/api/status', { every: 10000 }).data;
  const leads = useApi('/api/leads', { every: 60000 }).data;
  const followups = useApi('/api/followups?period=hoje', { every: 60000 }).data;
  const reactivation = useApi('/api/reactivation', { every: 60000 }).data;
  const contactsDirectory = useApi('/api/contacts', { every: 60000 }).data;

  useEffect(() => { applyTheme(config && config.theme); }, [config]);
  useEffect(() => { if (config && config.brand) document.title = `Painel ${config.brand}`; }, [config]);
  useEffect(() => {
    updateThemeDom(theme);
    try {
      localStorage.setItem('whatsaya_theme', theme);
    } catch (e) {}
  }, [theme]);
  useEffect(() => {
    const mq = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    if (!mq) return;
    const onChange = (e) => {
      try {
        if (!localStorage.getItem('whatsaya_theme')) {
          setTheme(e.matches ? 'dark' : 'light');
        }
      } catch (err) {}
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', onChange);
    };
  }, []);
  useEffect(() => {
    // Só reescreve o hash quando a view realmente muda — se não, apaga uma
    // query string (ex.: #agenda?connected=1) antes da tela lê-la e limpá-la.
    const currentBase = location.hash.replace('#', '').split('?')[0] || 'overview';
    if (currentBase !== view) location.hash = view;
  }, [view]);
  useEffect(() => {
    const onHash = () => setView(location.hash.replace('#', '').split('?')[0] || 'overview');
    addEventListener('hashchange', onHash);
    return () => removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => {
    const onSidebarShortcut = (event) => {
      const isMod = event.metaKey || event.ctrlKey;
      if (isMod && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen((open) => !open);
      } else if (isMod && event.key.toLowerCase() === 'b') {
        event.preventDefault();
        nav.togglePin();
      } else if (isMod && event.shiftKey && (event.key.toLowerCase() === 'l' || event.key.toLowerCase() === 'd')) {
        event.preventDefault();
        setTheme((prev) => {
          const next = prev === 'dark' ? 'light' : 'dark';
          setToast(next === 'dark' ? 'Tema escuro ativado' : 'Tema claro ativado');
          return next;
        });
      }
    };
    addEventListener('keydown', onSidebarShortcut);
    return () => removeEventListener('keydown', onSidebarShortcut);
  }, []);

  const setToast = (text) => { setToastText(text); setTimeout(() => setToastText(null), 3200); };
  const toggleTheme = () => {
    setTheme((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark';
      setToast(next === 'dark' ? 'Tema escuro ativado' : 'Tema claro ativado');
      return next;
    });
  };
  const leadRoute = view.startsWith('lead/');
  const clientRoute = view.startsWith('client/');
  const contactsRoute = view.startsWith('contacts/');
  const managementOn = !!(config && config.management && config.management.enabled);
  const navGroups = NAV_GROUPS.filter((group) => !group.feature || (group.feature === 'management' && managementOn));
  const current = leadRoute
    ? { id: 'lead', title: 'Detalhe do lead', view: Lead }
    : clientRoute ? { id: 'client', title: 'Cliente', view: ClientDetail }
    : contactsRoute ? VIEWS.find((v) => v.id === 'contacts')
    : VIEWS.find((v) => v.id === view) || VIEWS[0];
  const conn = connTone(status);
  const brand = (config && config.brand) || 'WhatsAYA';
  const assistantName = (config && config.assistant_name) || 'AYA';
  const badges = {
    kanban: leads ? leads.total : 0,
    followups: followups ? followups.queue.filter((j) => j.soon && !j.paused).length : 0,
    reactivation: reactivation ? reactivation.counts.pending : 0,
    contacts: contactsDirectory ? contactsDirectory.counts.attention : 0,
  };
  const View = current.view;
  const overview = current.id === 'overview';
  let chatId = '';
  if (leadRoute) {
    try { chatId = decodeURIComponent(view.slice(5)); } catch { chatId = view.slice(5); }
  } else if (contactsRoute) {
    try { chatId = decodeURIComponent(view.slice(9)); } catch { chatId = view.slice(9); }
  }

  const navKey = leadRoute ? 'kanban' : clientRoute ? 'clients' : contactsRoute ? 'contacts' : view;
  const group = navGroups.find((candidate) => candidate.ids.includes(navKey)) || null;
  const trail = { group, title: current.title };
  const navActive = navKey;
  const dockIds = ['overview', 'kanban', 'agenda', 'followups', 'contacts', 'connection'];
  const searchViews = VIEWS.filter((item) => navGroups.some((candidate) => candidate.ids.includes(item.id)));

  return html`<div class=${'shell' + (nav.pinned ? ' nav-pinned' : '')} style=${`--nav-width:${nav.width}px`}>
    <${ShellHeader} brand=${brand} logo=${config && config.theme && config.theme.logo} trail=${trail} nav=${nav} conn=${conn} theme=${theme} me=${me}
      onToggleTheme=${toggleTheme} onOpenSearch=${() => setSearchOpen(true)} go=${setView}/>
    <${ShellNav} brand=${brand} groups=${navGroups} views=${VIEWS} badges=${badges} active=${navActive} go=${setView} nav=${nav} conn=${conn}/>
    <main class=${'main' + (leadRoute ? ' lead-page-main' : clientRoute ? ' client-page-main' : current.id === 'contacts' ? ' contacts-page-main' : '')}>
      ${!leadRoute && !clientRoute ? html`<header class=${'page-head' + (overview ? ' overview-head' : '')}>
        <div class="page-title"><span class="eyebrow">${overview ? `Visão geral · ${brand}` : `${group ? group.label : brand} · ${current.title}`}</span><h1>${overview ? greeting() : current.title}</h1>${overview ? html`<p>${assistantName} mantém a operação fluindo. Veja o que precisa da sua atenção agora.</p>` : current.id === 'contacts' ? html`<p>Encontre contexto comercial antes de abrir cada conversa.</p>` : current.id === 'connection' ? html`<p>Conexão do WhatsApp, pausa global e comportamento da ponte. Cada opção é aplicada na hora.</p>` : null}</div>
        ${current.period ? html`<div class="head-tools"><div class="segment">${PERIODS.map(([id, label]) => html`<button key=${id} class=${id === period ? 'active' : ''} onClick=${() => setPeriod(id)}>${label}</button>`)}</div></div>` : null}
      </header>` : null}
      <${View} period=${period} status=${status} config=${config} me=${me} assistantName=${assistantName} setToast=${setToast} go=${setView} chatId=${chatId} clientId=${clientRoute ? view.slice(7) : ''}/>
    </main>
    <${ShellDock} views=${VIEWS} ids=${dockIds} badges=${badges} active=${navActive} go=${setView}/>
    <${SearchPalette} open=${searchOpen} onClose=${() => setSearchOpen(false)} views=${searchViews} groups=${navGroups} leads=${leads} followups=${followups} go=${setView} assistantName=${assistantName}/>
    ${toast ? html`<div class="toast">${toast}</div>` : null}
  </div>`;
}

render(html`<${App}/>`, document.getElementById('app'));
