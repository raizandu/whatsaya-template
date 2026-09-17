// shell.js — casca do painel: header preto fixo com trilha de localização,
// busca global (Ctrl+K), gaveta de navegação híbrida (hover → gaveta;
// alfinete → fixa e redimensiona) e dock inferior no celular.
// app.js decide as rotas e o estado; aqui só a casca. Nenhuma tela importa isto.
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { html, api, fmt, Dot, Menu } from './lib.js';

export const NAV_MIN_WIDTH = 200;
export const NAV_MAX_WIDTH = 420;
const NAV_DEFAULT_WIDTH = 264;
const KEY_WIDTH = 'whatsaya_nav_width';
const KEY_PINNED = 'whatsaya_nav_pinned';

const clamp = (n) => Math.min(NAV_MAX_WIDTH, Math.max(NAV_MIN_WIDTH, Number(n) || NAV_DEFAULT_WIDTH));
const stored = (key, fallback) => { try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch { return fallback; } };
const remember = (key, value) => { try { localStorage.setItem(key, String(value)); } catch {} };

// Estado da gaveta: modo (gaveta ou fixa), largura, aberta, grupo em foco.
export function useShellNav() {
  const [pinned, setPinned] = useState(() => stored(KEY_PINNED, '0') === '1');
  const [width, setWidthState] = useState(() => clamp(stored(KEY_WIDTH, NAV_DEFAULT_WIDTH)));
  const [open, setOpen] = useState(false);
  const [focusGroup, setFocusGroup] = useState(null);
  const closeTimer = useRef(null);
  const cancelClose = () => { if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; } };
  const openDrawer = (group = null) => { cancelClose(); setFocusGroup(group); setOpen(true); };
  const closeDrawer = () => { cancelClose(); setOpen(false); };
  const closeSoon = () => { cancelClose(); closeTimer.current = setTimeout(() => setOpen(false), 220); };
  const togglePin = () => setPinned((value) => { remember(KEY_PINNED, value ? '0' : '1'); if (value) setOpen(false); return !value; });
  const setWidth = (next) => { const value = clamp(next); setWidthState(value); return value; };
  const commitWidth = () => remember(KEY_WIDTH, width);
  useEffect(() => () => cancelClose(), []);
  return { pinned, togglePin, width, setWidth, commitWidth, open, openDrawer, closeDrawer, closeSoon, cancelClose, focusGroup };
}

// Glifo de painel dividido (alça do menu e botões de fixar/recolher).
export function NavGlyph({ mirrored = false }) {
  return html`<svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true" style=${mirrored ? 'transform:scaleX(-1)' : ''}>
    <rect x="1.5" y="2.5" width="15" height="13" rx="2.5" stroke="currentColor" stroke-width="1.5"/>
    <path d="M6.5 2.5v13" stroke="currentColor" stroke-width="1.5"/>
    <path d="M3.5 5.5h1M3.5 7.5h1M3.5 9.5h1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
  </svg>`;
}

function Kbd({ children }) { return html`<kbd class="shell-kbd">${children}</kbd>`; }

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent || '');
export const MOD_KEY = IS_MAC ? '⌘' : 'Ctrl';

// ── Header ─────────────────────────────────────────────────────────────
export function ShellHeader({ brand, logo, trail, nav, conn, theme, onToggleTheme, onOpenSearch, go, me }) {
  const roleLabel = me ? (me.role === 'admin' ? 'Administrador' : 'Atendente') : '';
  const account = [
    { label: 'Configurações', icon: 'settings', onClick: () => go('connection') },
    { label: 'Assinatura', icon: 'credit-card', onClick: () => go('subscription') },
    'separator',
    { label: theme === 'dark' ? 'Tema claro' : 'Tema escuro', icon: theme === 'dark' ? 'sun' : 'moon', hint: `${MOD_KEY}⇧L`, onClick: onToggleTheme },
    'separator',
    ...(me ? [{ heading: `${me.name} · ${roleLabel}` }] : []),
    { label: 'Sair', icon: 'sign-out-alt', href: '/logout', danger: true },
  ];
  return html`<header class="shell-header">
    <button type="button" class="shell-icon-btn shell-menu-btn" aria-label="Abrir menu" title="Abrir menu" onClick=${() => nav.openDrawer()}><i class="fi fi-rr-menu-burger" aria-hidden="true"></i></button>
    <button type="button" class=${'shell-handle' + (nav.pinned ? ' is-dim' : '')} aria-label=${nav.pinned ? 'Menu fixado' : 'Abrir menu'} title=${nav.pinned ? 'Menu fixado (⌘/Ctrl+B solta)' : 'Abrir menu (⌘/Ctrl+B fixa)'}
      onMouseEnter=${() => !nav.pinned && nav.openDrawer()} onFocus=${() => !nav.pinned && nav.openDrawer()} onClick=${() => (nav.pinned ? nav.togglePin() : nav.openDrawer())}>
      <${NavGlyph}/>
    </button>
    <a class="shell-brand" href="#overview" onClick=${(event) => { event.preventDefault(); go('overview'); }} aria-label=${`${brand}, início`}>
      <span class="brand-mark">${logo ? html`<img src=${logo} alt=""/>` : html`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 20L7.5 4l5.5 16" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M4.4 14.5h6.2" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M18.2 12.2V20" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M22 4l-3.8 8.2" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M14.4 4l3.8 8.2" stroke="#F26E22" stroke-width="2.4" stroke-linecap="round"/></svg>`}</span>
      <span class="brand-name">${brand.includes('.') ? html`${brand.split('.')[0]}<span class="dot">.</span><span class="light">${brand.split('.').slice(1).join('.')}</span>` : brand}</span>
    </a>
    <section class="shell-trail" aria-label="Localização atual">
      ${trail.group ? html`<button type="button" class="shell-trail-group" onClick=${() => nav.openDrawer(trail.group.label)} title="Abrir o grupo no menu">${trail.group.label}</button>
        <i class="fi fi-rr-angle-small-right shell-trail-sep" aria-hidden="true"></i>` : null}
      <span class="shell-trail-current" aria-current="page">${trail.title}</span>
    </section>
    <button type="button" class="shell-search-trigger" onClick=${onOpenSearch} aria-label="Buscar no painel" aria-keyshortcuts="Control+K Meta+K">
      <i class="fi fi-rr-search" aria-hidden="true"></i>
      <span>Buscar lead, contato ou telefone…</span>
      <${Kbd}>${MOD_KEY} K</${Kbd}>
    </button>
    <div class="shell-actions">
      <button type="button" class="shell-icon-btn" onClick=${onToggleTheme} aria-label=${theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'} title="Alternar tema (⌘/Ctrl+Shift+L)"><i class=${`fi fi-rr-${theme === 'dark' ? 'sun' : 'moon'}`} aria-hidden="true"></i></button>
      <button type="button" class="shell-conn" onClick=${() => go('connection')} title=${[conn.label, conn.phone, conn.sub].filter(Boolean).join(' · ')}><${Dot} tone=${conn.tone}/><span>${conn.label}</span></button>
      <${Menu} label="Conta" icon="user" className="shell-account" items=${account}/>
    </div>
  </header>`;
}

// ── Gaveta / sidebar fixa ──────────────────────────────────────────────
export function ShellNav({ brand, groups, views, badges, active, go, nav, conn }) {
  const [expanded, setExpanded] = useState(() => new Set(groups.map((group) => group.label)));
  const dragging = useRef(false);
  const asideRef = useRef(null);
  useEffect(() => {
    if (!nav.focusGroup) return;
    setExpanded((set) => new Set([...set, nav.focusGroup]));
    const target = asideRef.current && asideRef.current.querySelector(`[data-group="${CSS.escape(nav.focusGroup)}"] .shell-nav-link`);
    if (target) target.focus();
  }, [nav.focusGroup, nav.open]);
  useEffect(() => {
    if (!nav.open || nav.pinned) return;
    const onKey = (event) => { if (event.key === 'Escape') nav.closeDrawer(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [nav.open, nav.pinned]);

  const startResize = (event) => {
    event.preventDefault();
    dragging.current = true;
    document.body.classList.add('is-resizing-nav');
    const move = (e) => { if (dragging.current) nav.setWidth(e.clientX); };
    const stop = () => { dragging.current = false; document.body.classList.remove('is-resizing-nav'); nav.commitWidth(); document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', stop); };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', stop);
  };
  const toggleGroup = (label) => setExpanded((set) => { const next = new Set(set); next.has(label) ? next.delete(label) : next.add(label); return next; });
  const navigate = (id) => { go(id); if (!nav.pinned) nav.closeDrawer(); };
  const visible = nav.pinned || nav.open;

  return html`<${'div'} class="shell-nav-root">
    ${!nav.pinned && nav.open ? html`<div class="shell-backdrop" onClick=${nav.closeDrawer} aria-hidden="true"></div>` : null}
    <aside ref=${asideRef} class="shell-nav" data-mode=${nav.pinned ? 'pinned' : 'drawer'} data-open=${visible ? 'true' : 'false'} aria-label="Navegação do painel" aria-hidden=${visible ? 'false' : 'true'}
      style=${`--nav-width:${nav.width}px`} onMouseEnter=${() => !nav.pinned && nav.cancelClose()} onMouseLeave=${() => !nav.pinned && nav.closeSoon()}>
      <div class="shell-nav-top">
        <span class="shell-nav-title">${brand}</span>
        <div class="shell-nav-tools">
          <button type="button" class=${'shell-icon-btn' + (nav.pinned ? ' is-on' : '')} onClick=${nav.togglePin} aria-pressed=${nav.pinned} aria-label=${nav.pinned ? 'Soltar menu' : 'Fixar menu'} title=${nav.pinned ? 'Soltar menu (⌘/Ctrl+B)' : 'Fixar menu (⌘/Ctrl+B)'}><i class="fi fi-rr-thumbtack" aria-hidden="true"></i></button>
          <button type="button" class="shell-icon-btn" onClick=${nav.pinned ? nav.togglePin : nav.closeDrawer} aria-label="Recolher menu" title="Recolher menu"><${NavGlyph} mirrored=${true}/></button>
        </div>
      </div>
      <nav class="shell-nav-groups" aria-label="Navegação principal">
        ${groups.map((group) => {
          const isOpen = expanded.has(group.label);
          return html`<section class="shell-nav-group" data-group=${group.label} key=${group.label}>
            <button type="button" class="shell-nav-group-head" aria-expanded=${isOpen} onClick=${() => toggleGroup(group.label)}>
              <span>${group.label}</span><i class=${`fi fi-rr-angle-small-${isOpen ? 'up' : 'down'}`} aria-hidden="true"></i>
            </button>
            ${isOpen ? html`<div class="shell-nav-card">${group.ids.map((id) => {
              const item = views.find((candidate) => candidate.id === id);
              const isActive = item.id === active;
              return html`<button type="button" key=${item.id} data-id=${item.id} class=${'shell-nav-link' + (isActive ? ' active' : '')} aria-current=${isActive ? 'page' : null} onClick=${() => navigate(item.id)}>
                <i class=${`fi fi-rr-${item.icon}`} aria-hidden="true"></i><span class="label">${item.label}</span>
                ${badges[item.id] ? html`<span class=${'badge' + (item.id === 'followups' ? ' hot' : '')}>${badges[item.id]}</span>` : null}
              </button>`;
            })}</div>` : null}
          </section>`;
        })}
      </nav>
      <footer class="shell-nav-footer">
        <div class="conn-card" title=${[conn.label, conn.phone, conn.sub].filter(Boolean).join(' · ')}><${Dot} tone=${conn.tone}/><div class="conn-copy"><span class="l1">${conn.label}</span>${conn.phone ? html`<span class="conn-phone">${conn.phone}</span>` : null}<span class="l2">${conn.sub}</span></div></div>
        <button type="button" class=${'shell-nav-link' + (active === 'connection' ? ' active' : '')} onClick=${() => navigate('connection')}><i class="fi fi-rr-settings" aria-hidden="true"></i><span class="label">Configurações</span></button>
      </footer>
      ${nav.pinned ? html`<div class="shell-nav-resize" role="separator" aria-orientation="vertical" aria-label="Redimensionar menu" aria-valuemin=${NAV_MIN_WIDTH} aria-valuemax=${NAV_MAX_WIDTH} aria-valuenow=${nav.width} tabindex="0"
        onMouseDown=${startResize} onKeyDown=${(event) => { if (event.key === 'ArrowLeft') { nav.setWidth(nav.width - 16); nav.commitWidth(); } if (event.key === 'ArrowRight') { nav.setWidth(nav.width + 16); nav.commitWidth(); } }}></div>` : null}
    </aside>
  </${'div'}>`;
}

// ── Dock inferior (celular) ────────────────────────────────────────────
// Doca do celular: poucos atalhos e um "Menu" que abre a gaveta completa, a mesma do desktop.
// Sem isso a doca vira uma fila de ícones pequenos conforme o painel ganha telas.
export function ShellDock({ views, ids, badges, active, go, onMenu }) {
  return html`<nav class="shell-dock" aria-label="Navegação principal">
    ${ids.map((id) => { const item = views.find((candidate) => candidate.id === id); if (!item) return null; const isActive = item.id === active;
      return html`<button type="button" key=${id} class=${'shell-dock-item' + (isActive ? ' active' : '')} aria-current=${isActive ? 'page' : null} onClick=${() => go(item.id)}>
        <i class=${`fi fi-rr-${item.icon}`} aria-hidden="true"></i><span>${item.label}</span>${badges[item.id] ? html`<b class="badge">${badges[item.id]}</b>` : null}
      </button>`; })}
    ${onMenu ? html`<button type="button" class="shell-dock-item" onClick=${onMenu} aria-haspopup="dialog"><i class="fi fi-rr-menu-burger" aria-hidden="true"></i><span>Menu</span></button>` : null}
  </nav>`;
}

// ── Busca global ───────────────────────────────────────────────────────
const normalize = (value) => String(value || '').normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('pt-BR');
const digitsOf = (value) => String(value || '').replace(/\D/g, '');

function highlight(text, needle) {
  const source = String(text || '');
  if (!needle) return source;
  const idx = normalize(source).indexOf(normalize(needle));
  if (idx < 0) return source;
  return html`${source.slice(0, idx)}<mark>${source.slice(idx, idx + needle.length)}</mark>${source.slice(idx + needle.length)}`;
}

const TABS = [['leads', 'Leads'], ['contacts', 'Contatos'], ['followups', 'Follow-ups'], ['shortcuts', 'Atalhos']];

export function SearchPalette({ open, onClose, views, groups, leads, followups, go, assistantName = 'AYA' }) {
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [tab, setTab] = useState('leads');
  const [cursor, setCursor] = useState(0);
  const [contacts, setContacts] = useState(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setQuery(''); setDebounced(''); setCursor(0);
    const t = setTimeout(() => inputRef.current && inputRef.current.focus(), 30);
    if (contacts === null) api('/api/contacts').then((data) => setContacts(data && data.contacts ? data.contacts : [])).catch(() => setContacts([]));
    return () => clearTimeout(t);
  }, [open]);
  useEffect(() => { const t = setTimeout(() => setDebounced(query.trim()), 250); return () => clearTimeout(t); }, [query]);

  const needle = normalize(debounced);
  const needleDigits = digitsOf(debounced);
  const matches = (fields) => !needle || fields.some((f) => normalize(f).includes(needle) || (needleDigits.length >= 3 && digitsOf(f).includes(needleDigits)));

  const results = useMemo(() => {
    const leadItems = (leads ? leads.stages.flatMap((stage) => stage.cards.map((card) => ({ ...card, stage_label: stage.label }))) : [])
      .filter((card) => matches([card.name, card.phone, card.chat_id, card.stage_label, card.preview]))
      .map((card) => ({ id: `lead:${card.chat_id}`, kind: 'lead', title: card.name, sub: [card.phone, card.stage_label].filter(Boolean).join(' · '), status: card.human ? { tone: 'warn', label: 'Com humano' } : { tone: 'ok', label: `${assistantName} atendendo` }, chat_id: card.chat_id, run: () => go(`lead/${encodeURIComponent(card.chat_id)}`) }));
    const contactItems = (contacts || [])
      .filter((c) => matches([c.name, c.phone, c.chat_id, c.stage_label]))
      .map((c) => ({ id: `contact:${c.chat_id}`, kind: 'contact', title: c.name, sub: [c.phone, c.stage_label].filter(Boolean).join(' · '), status: c.kind === 'blocked' ? { tone: 'bad', label: 'Bloqueado' } : c.ai && c.ai.enabled === false ? { tone: 'off', label: 'IA desligada' } : null, chat_id: c.chat_id, run: () => go(`lead/${encodeURIComponent(c.chat_id)}`) }));
    const followupItems = (followups ? followups.queue : [])
      .filter((job) => matches([job.name, job.chat_id, job.stage, job.due_rel]))
      .map((job) => ({ id: `fu:${job.id}`, kind: 'followup', title: job.name, sub: [job.due_rel ? `próximo ${job.due_rel}` : null, job.stage].filter(Boolean).join(' · '), status: job.paused ? { tone: 'off', label: 'Pausado' } : { tone: 'warn', label: 'Na fila' }, chat_id: job.chat_id, run: () => go('followups') }));
    const shortcutItems = views.filter((view) => matches([view.label, view.title])).map((view) => {
      const group = groups.find((g) => g.ids.includes(view.id));
      return { id: `view:${view.id}`, kind: 'shortcut', icon: view.icon, title: view.title, sub: group ? `Ir para ${group.label} › ${view.label}` : `Ir para ${view.label}`, status: null, run: () => go(view.id) };
    });
    return { leads: leadItems, contacts: contactItems, followups: followupItems, shortcuts: shortcutItems };
  }, [leads, contacts, followups, views, groups, needle, needleDigits]);

  const list = results[tab] || [];
  useEffect(() => { setCursor(0); }, [tab, debounced]);
  useEffect(() => {
    if (!open) return;
    const onKey = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
      if (event.key === 'ArrowDown') { event.preventDefault(); setCursor((c) => Math.min(list.length - 1, c + 1)); }
      if (event.key === 'ArrowUp') { event.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
      if (event.key === 'Enter' && list[cursor]) { event.preventDefault(); list[cursor].run(); onClose(); }
      if (event.key === 'Tab') { event.preventDefault(); const ids = TABS.map(([id]) => id); const i = ids.indexOf(tab); setTab(ids[(i + (event.shiftKey ? -1 : 1) + ids.length) % ids.length]); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, list, cursor, tab]);
  useEffect(() => {
    const el = listRef.current && listRef.current.querySelector('.is-cursor');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  if (!open) return null;
  const empty = !list.length;
  return html`<div class="shell-search-backdrop" onMouseDown=${(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div class="shell-search" role="dialog" aria-modal="true" aria-label="Busca no painel">
      <div class="shell-search-input">
        <i class="fi fi-rr-search" aria-hidden="true"></i>
        <input ref=${inputRef} value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone, etapa ou tela" autocomplete="off" spellcheck="false" aria-label="Buscar"/>
        ${query ? html`<button type="button" class="shell-search-clear" onClick=${() => { setQuery(''); inputRef.current && inputRef.current.focus(); }} aria-label="Limpar busca"><i class="fi fi-rr-cross-small" aria-hidden="true"></i></button>` : null}
        <${Kbd}>Esc</${Kbd}>
      </div>
      <div class="shell-search-tabs" role="tablist">
        ${TABS.map(([id, label]) => html`<button type="button" role="tab" key=${id} aria-selected=${tab === id} class=${tab === id ? 'active' : ''} onClick=${() => setTab(id)}>${label}<b>${results[id].length}</b></button>`)}
      </div>
      <div class="shell-search-results" ref=${listRef} role="listbox">
        ${empty ? html`<div class="shell-search-empty"><strong>${debounced ? `Nada com "${debounced}" em ${TABS.find(([id]) => id === tab)[1].toLowerCase()}` : 'Comece a digitar'}</strong>${debounced ? 'Tente outra aba, o telefone ou parte do nome.' : 'Nome, telefone, etapa do funil ou o nome de uma tela.'}${tab === 'contacts' && contacts === null ? html`<small>Carregando contatos…</small>` : null}</div>` : null}
        ${list.map((item, index) => html`<button type="button" role="option" key=${item.id} aria-selected=${index === cursor} class=${'shell-search-item' + (index === cursor ? ' is-cursor' : '')} onMouseEnter=${() => setCursor(index)} onClick=${() => { item.run(); onClose(); }}>
          ${item.kind === 'shortcut' ? html`<span class="shell-search-glyph"><i class=${`fi fi-rr-${item.icon}`} aria-hidden="true"></i></span>` : html`<span class="shell-search-avatar">${fmt.initials(item.title)}</span>`}
          <span class="shell-search-copy"><b>${highlight(item.title, debounced)}</b><small>${highlight(item.sub, debounced)}</small></span>
          ${item.status ? html`<span class=${'status-pill ' + item.status.tone}><${Dot} tone=${item.status.tone}/>${item.status.label}</span>` : null}
          ${item.chat_id ? html`<a class="shell-search-quick" href=${`https://wa.me/${digitsOf(item.chat_id.split('@')[0])}`} target="_blank" rel="noopener" onClick=${(event) => event.stopPropagation()} title="Abrir no WhatsApp"><i class="fi fi-rr-paper-plane" aria-hidden="true"></i></a>` : null}
          <${Kbd}>↵</${Kbd}>
        </button>`)}
      </div>
      <div class="shell-search-foot"><span><${Kbd}>↑</${Kbd}> <${Kbd}>↓</${Kbd}> navegar</span><span><${Kbd}>↵</${Kbd}> abrir</span><span><${Kbd}>Tab</${Kbd}> trocar aba</span><span><${Kbd}>Esc</${Kbd}> fechar</span></div>
    </div>
  </div>`;
}
