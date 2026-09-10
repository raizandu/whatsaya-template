// Casca do painel: navegação, cabeçalho, período e status. As telas ficam em
// views/ e recebem {period, status, config, toast}. Para adicionar uma tela
// para um cliente: crie views/nome.js exportando default e registre em VIEWS.
import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { html, useApi, fmt, PERIODS, Dot } from './lib.js';
import Overview from './views/overview.js';
import Kanban from './views/kanban.js';
import Agenda from './views/agenda.js';
import Followups from './views/followups.js';
import Reactivation from './views/reactivation.js';
import Contacts from './views/contacts.js';
import Connection from './views/connection.js';
import Subscription from './views/subscription.js';
import Lead from './views/lead.js';

const VIEWS = [
  { id: 'overview', label: 'Visão geral', title: 'Visão geral', icon: 'dashboard', view: Overview, period: true },
  { id: 'kanban', label: 'Kanban', title: 'Funil de leads', icon: 'layout-fluid', view: Kanban },
  { id: 'agenda', label: 'Agenda', title: 'Agenda', icon: 'calendar', view: Agenda },
  { id: 'followups', label: 'Follow-ups', title: 'Follow-ups automáticos', icon: 'clock', view: Followups, period: true },
  { id: 'reactivation', label: 'Reativação', title: 'Reativação manual', icon: 'refresh', view: Reactivation },
  { id: 'contacts', label: 'Contatos', title: 'Contatos', icon: 'address-book', view: Contacts },
  { id: 'connection', label: 'Conexão', title: 'Conexão do WhatsApp', icon: 'signal-alt', view: Connection },
  { id: 'subscription', label: 'Assinatura', title: 'Sua assinatura', icon: 'credit-card', view: Subscription },
];

const NAV_GROUPS = [
  { label: 'Operação', ids: ['overview', 'kanban', 'agenda'] },
  { label: 'Relacionamento', ids: ['followups', 'reactivation', 'contacts'] },
  { label: 'Conta', ids: ['connection', 'subscription'] },
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

function App() {
  const [view, setView] = useState(() => location.hash.replace('#', '').split('?')[0] || 'overview');
  const [period, setPeriod] = useState('7d');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [toast, setToastText] = useState(null);
  const config = useApi('/api/config').data;
  const status = useApi('/api/status', { every: 10000 }).data;
  const leads = useApi('/api/leads', { every: 60000 }).data;
  const followups = useApi('/api/followups?period=hoje', { every: 60000 }).data;
  const reactivation = useApi('/api/reactivation', { every: 60000 }).data;
  const contactsDirectory = useApi('/api/contacts', { every: 60000 }).data;

  useEffect(() => { applyTheme(config && config.theme); }, [config]);
  useEffect(() => { if (config && config.brand) document.title = `Painel ${config.brand}`; }, [config]);
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
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault();
        setSidebarOpen((open) => !open);
      }
    };
    addEventListener('keydown', onSidebarShortcut);
    return () => removeEventListener('keydown', onSidebarShortcut);
  }, []);

  const setToast = (text) => { setToastText(text); setTimeout(() => setToastText(null), 3200); };
  const leadRoute = view.startsWith('lead/');
  const current = leadRoute
    ? { id: 'lead', title: 'Detalhe do lead', view: Lead }
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
  }

  return html`<div class=${'shell' + (sidebarOpen ? '' : ' sidebar-collapsed')}>
    <aside class="sidebar" data-state=${sidebarOpen ? 'expanded' : 'collapsed'} aria-label="Navegação do painel">
      <header class="sidebar-header">
        <div class="brand">
          <div class="brand-mark">${config && config.theme && config.theme.logo
            ? html`<img src=${config.theme.logo} alt=""/>`
            : html`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 20L7.5 4l5.5 16" stroke="#070B0D" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M4.4 14.5h6.2" stroke="#070B0D" stroke-width="2.4" stroke-linecap="round"/><path d="M18.2 12.2V20" stroke="#070B0D" stroke-width="2.4" stroke-linecap="round"/><path d="M22 4l-3.8 8.2" stroke="#070B0D" stroke-width="2.4" stroke-linecap="round"/><path d="M14.4 4l3.8 8.2" stroke="#F26E22" stroke-width="2.4" stroke-linecap="round"/></svg>`}</div>
          <div class="brand-name">${brand.includes('.')
            ? html`${brand.split('.')[0]}<span class="dot">.</span><span class="light">${brand.split('.').slice(1).join('.')}</span>`
            : brand}</div>
        </div>
      </header>
      <div class="sidebar-content">
        <nav class="primary-nav" aria-label="Navegação principal">
          ${NAV_GROUPS.map((group) => html`<section class="sidebar-group" key=${group.label} aria-labelledby=${`sidebar-group-${group.label}`}>
            <span class="sidebar-group-label" id=${`sidebar-group-${group.label}`}>${group.label}</span>
            <div class="sidebar-group-content">
              ${group.ids.map((id) => {
                const item = VIEWS.find((candidate) => candidate.id === id);
                const active = item.id === view;
                return html`<button
                  key=${item.id}
                  class=${'nav-item' + (active ? ' active' : '')}
                  aria-label=${item.label}
                  aria-current=${active ? 'page' : null}
                  title=${sidebarOpen ? null : item.label}
                  onClick=${() => setView(item.id)}
                >
                  <i class=${`fi fi-rr-${item.icon}`} aria-hidden="true"></i>
                  <span class="label">${item.label}</span>
                  ${badges[item.id] ? html`<span class=${'badge' + (item.id === 'followups' ? ' hot' : '')}>${badges[item.id]}</span>` : null}
                </button>`;
              })}
            </div>
          </section>`)}
        </nav>
      </div>
      <footer class="sidebar-footer">
        <div class="conn-card" title=${[conn.label, conn.phone, conn.sub].filter(Boolean).join(' · ')}><${Dot} tone=${conn.tone}/><div class="conn-copy"><span class="l1">${conn.label}</span>${conn.phone ? html`<span class="conn-phone">${conn.phone}</span>` : null}<span class="l2">${conn.sub}</span></div></div>
        <a href="/logout" class="sidebar-logout" aria-label="Sair" title="Encerrar sessão"><i class="fi fi-rr-sign-out-alt" aria-hidden="true"></i><span class="label">Sair</span></a>
      </footer>
      <button
        class="sidebar-rail"
        type="button"
        aria-label=${sidebarOpen ? 'Recolher menu lateral' : 'Expandir menu lateral'}
        aria-expanded=${sidebarOpen}
        title=${sidebarOpen ? 'Recolher menu (⌘/Ctrl+B)' : 'Expandir menu (⌘/Ctrl+B)'}
        onClick=${() => setSidebarOpen((open) => !open)}
      ><i class=${`fi fi-rr-angle-small-${sidebarOpen ? 'left' : 'right'}`} aria-hidden="true"></i></button>
    </aside>
    <main class=${'main' + (leadRoute ? ' lead-page-main' : '')}>
      ${!leadRoute ? html`<header class=${'page-head' + (overview ? ' overview-head' : '')}>
        <div class="page-title"><span class="eyebrow">${overview ? `Visão geral · ${brand}` : `${brand} · painel de operação`}</span><h1>${overview ? greeting() : current.title}</h1>${overview ? html`<p>${assistantName} mantém a operação fluindo. Veja o que precisa da sua atenção agora.</p>` : current.id === 'contacts' ? html`<p>Encontre contexto comercial antes de abrir cada conversa.</p>` : null}</div>
        <div class="head-tools">
          ${current.period ? html`<div class="segment">${PERIODS.map(([id, label]) => html`<button key=${id} class=${id === period ? 'active' : ''} onClick=${() => setPeriod(id)}>${label}</button>`)}</div>` : null}
          <button class="pill" onClick=${() => setView('connection')}><${Dot} tone=${conn.tone}/>${conn.label}</button>
        </div>
      </header>` : null}
      <${View} period=${period} status=${status} config=${config} assistantName=${assistantName} setToast=${setToast} go=${setView} chatId=${chatId}/>
    </main>
    ${toast ? html`<div class="toast">${toast}</div>` : null}
  </div>`;
}

render(html`<${App}/>`, document.getElementById('app'));
