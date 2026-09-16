// Utilidades compartilhadas pelas telas: html (htm+preact), acesso à API,
// formatação pt-BR, ícones e componentes pequenos. Nenhuma tela importa outra.
import { h, Fragment } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import htm from 'htm';

export const html = htm.bind(h);
export { Fragment };

// ── API ──────────────────────────────────────────────────────────────
export async function api(path, options = {}) {
  const res = await fetch(path, { cache: 'no-store', headers: { Accept: 'application/json' }, ...options });
  if (res.status === 401) {
    if (typeof location !== 'undefined' && location.pathname !== '/login') {
      location.href = '/login?expired=1';
    }
    throw new Error('Sessão expirou. Recarregue a página e entre de novo.');
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) throw new Error((body && (body.detail || body.error)) || `HTTP ${res.status}`);
  return body;
}

// Foto de perfil quando o bridge guardou uma; iniciais em qualquer outro caso,
// inclusive quando a imagem falha (URL assinada vencida, R2 fora).
export function Avatar({ name, url, className = 'avatar' }) {
  const [failed, setFailed] = useState(false);
  const [preview, setPreview] = useState(null);
  useEffect(() => { setFailed(false); setPreview(null); }, [url]);
  if (url && !failed) {
    // Preview grande ao passar o mouse (ou focar), posicionado ao lado da foto em
    // coordenadas fixas para não ser cortado por listas com overflow.
    const show = (event) => {
      const r = event.currentTarget.getBoundingClientRect();
      const size = 240;
      const gap = 10;
      const fitsRight = r.right + gap + size <= window.innerWidth;
      const left = fitsRight ? r.right + gap : Math.max(8, r.left - gap - size);
      const top = Math.min(Math.max(8, r.top), Math.max(8, window.innerHeight - size - 48));
      setPreview({ left, top });
    };
    const hide = () => setPreview(null);
    return html`<${Fragment}>
      <span class=${`${className} avatar-photo-wrap`} tabindex="0" aria-label=${`Foto de ${name || 'contato'}`}
        onMouseEnter=${show} onMouseLeave=${hide} onFocus=${show} onBlur=${hide}>
        <img class="avatar-photo" src=${url} alt="" loading="lazy" onError=${() => setFailed(true)}/>
        <span class="avatar-zoom" aria-hidden="true"><${Icon.search}/></span>
      </span>
      ${preview ? html`<div class="avatar-preview" role="presentation" style=${`left:${preview.left}px;top:${preview.top}px`}>
        <img src=${url} alt=""/>
        ${name ? html`<span>${name}</span>` : null}
      </div>` : null}
    </${Fragment}>`;
  }
  return html`<span class=${className}>${fmt.initials(name)}</span>`;
}

// Papel vem de /api/me; até responder, a UI não oferece nada de admin (o servidor
// nega de qualquer forma — isto só evita botão que sempre falha com 403).
export const isAdmin = (me) => !!me && me.role === 'admin';

export function post(path, body) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body || {}) });
}

// Busca e re-busca a cada `every` ms. Devolve {data, error, loading, reload}.
export function useApi(path, { every = 0, deps = [] } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const alive = useRef(true);
  const lastPath = useRef(path);
  const load = async () => {
    try {
      const data = await api(path);
      if (alive.current) setState({ data, error: null, loading: false });
      return true;
    } catch (err) {
      if (alive.current) setState((s) => ({ data: s.data, error: err.message, loading: false }));
      return false;
    }
  };
  useEffect(() => {
    alive.current = true;
    // Caminho novo é recurso novo: nunca mostrar o dado do anterior enquanto o
    // atual carrega ou falha (um 403 no detalhe de outro contato exibiria a
    // conversa errada). Re-busca do mesmo caminho mantém o dado na tela.
    if (lastPath.current !== path) {
      lastPath.current = path;
      setState({ data: null, error: null, loading: true });
    } else {
      setState((s) => ({ ...s, loading: s.data === null }));
    }
    load();
    const timer = every > 0 ? setInterval(load, every) : null;
    return () => { alive.current = false; if (timer) clearInterval(timer); };
  }, [path, ...deps]);
  return { ...state, reload: load };
}

// ── formatação ───────────────────────────────────────────────────────
const nfInt = new Intl.NumberFormat('pt-BR');
const nfBRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const nfUSD = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 });
export const fmt = {
  int: (n) => nfInt.format(Math.round(Number(n) || 0)),
  brl: (n) => nfBRL.format(Number(n) || 0),
  usd: (n) => nfUSD.format(Number(n) || 0),
  pct: (a, b) => (b ? Math.round((a / b) * 100) + '%' : '0%'),
  tokens: (n) => {
    n = Number(n) || 0;
    if (n >= 1e6) return (n / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi';
    if (n >= 1e3) return (n / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' mil';
    return nfInt.format(n);
  },
  duration: (minutes) => {
    minutes = Math.round(Number(minutes) || 0);
    const h = Math.floor(minutes / 60), m = minutes % 60;
    return h > 0 ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`;
  },
  uptime: (s) => {
    s = Number(s) || 0;
    if (s < 3600) return `há ${Math.floor(s / 60)} min`;
    if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
    return `há ${Math.floor(s / 86400)} dias`;
  },
  // Nome que é telefone não tem inicial: vira o marcador de contato sem nome.
  initials: (name) => {
    const clean = String(name || '').trim();
    const letters = clean.split(/\s+/).filter((w) => /\p{L}/u.test(w)).slice(0, 2).map((w) => w.match(/\p{L}/u)[0]);
    return letters.length ? letters.join('').toUpperCase() : '#';
  },
};

export const PERIODS = [['hoje', 'Hoje'], ['7d', '7 dias'], ['30d', '30 dias']];

// Compartilhados pelas telas de conversa (Lead, Contatos, Atendimento).
export const dateTime = (value, options = {}) => value
  ? new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', ...options })
  : '—';
export const normalize = (value) => String(value || '')
  .normalize('NFD')
  .replace(/\p{M}/gu, '')
  .toLocaleLowerCase('pt-BR');
export const VER_TODOS = 'atendimentos.ver_todos';
// Mesmo enum de panel/data.py (triage.stage).
export const TRIAGE_STAGE_LABELS = {
  pessoal: 'Pessoal',
  lead_novo: 'Lead novo',
  lead_qualificado: 'Lead qualificado',
  proposta: 'Proposta',
  cliente: 'Cliente',
  fornecedor: 'Fornecedor',
  incerto: 'Incerto',
  spam: 'Spam',
};
// Usado só até o /api/config responder na primeira carga.
export const DEFAULT_STAGES = [
  { id: 'new', label: 'Novo' },
  { id: 'qualification', label: 'Qualificação' },
  { id: 'pricing', label: 'Preço' },
  { id: 'proposal', label: 'Proposta' },
  { id: 'payment', label: 'Pagamento' },
];
export const MEETING_OUTCOMES = {
  attended: 'Comparecida',
  no_show: 'No Show',
  no_status: 'Sem status',
  rescheduled: 'Remarcada',
};

// ── ícones (traço, 24 grid) ──────────────────────────────────────────
const svg = (paths, size = 20) => html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" dangerouslySetInnerHTML=${{ __html: paths }}></svg>`;
export const Icon = {
  overview: () => svg('<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="12" width="8" height="9" rx="2"/><rect x="3" y="15" width="8" height="6" rx="2"/>'),
  kanban: () => svg('<rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="9.5" y="4" width="5" height="11" rx="1.5"/><rect x="16" y="4" width="5" height="8" rx="1.5"/>'),
  followups: () => svg('<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/><path d="M19.5 5.5v3h-3"/>'),
  contacts: () => svg('<circle cx="9" cy="8" r="3"/><path d="M3.5 18.5a5.5 5.5 0 0111 0"/><path d="M16 7h5M16 11h5M17 15h4"/>'),
  blocked: () => svg('<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>'),
  connection: () => svg('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14 14h3v3h-3zM20 14v1M17 20h4M14 20h1"/>'),
  costs: () => svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h3.75a1.75 1.75 0 010 3.5h-2.5a1.75 1.75 0 000 3.5H15"/>'),
  reactivation: () => svg('<path d="M4.5 12a7.5 7.5 0 0113-5.2M19.5 12a7.5 7.5 0 01-13 5.2"/><path d="M17.3 3.8v3.4h-3.4M6.7 20.2v-3.4h3.4"/>'),
  agenda: () => svg('<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M3 9.5h18"/><path d="M8 3v4M16 3v4"/><path d="M7.5 13.5h2M11 13.5h2M14.5 13.5h2M7.5 17h2M11 17h2"/>'),
  refresh: () => svg('<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M6.1 8.5A7 7 0 0118.8 7L20 12M4 12l1.2 5A7 7 0 0017.9 15.5"/>', 16),
  search: () => svg('<circle cx="11" cy="11" r="7"/><path d="M16.5 16.5l4 4"/>', 16),
  left: () => svg('<path d="M15 6l-6 6 6 6"/>', 16),
  right: () => svg('<path d="M9 6l6 6-6 6"/>', 16),
  check: () => svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 44),
  power: () => svg('<path d="M12 3v9"/><path d="M6.6 7.2a8 8 0 1010.8 0"/>', 44),
  user: () => svg('<path d="M20 21a8 8 0 10-16 0"/><circle cx="12" cy="8" r="4"/>', 16),
  document: () => svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h6"/>'),
  attach: () => svg('<path d="M20 11.5 12.3 19.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4L15 7"/>'),
  close: () => svg('<path d="M6 6l12 12"/><path d="M18 6L6 18"/>'),
};

// ── componentes pequenos ─────────────────────────────────────────────
// Switch do Aya Design System: input nativo com papel de switch, estilizado por `.switch`.
export function Switch({ checked, disabled, label, onChange }) {
  return html`<input type="checkbox" role="switch" class="switch" checked=${Boolean(checked)} disabled=${disabled} aria-label=${label} onChange=${onChange}/>`;
}

export function Tile({ label, value, sub, dark, green, pct }) {
  return html`<div class=${'card tile' + (dark ? ' dark' : '')}>
    <span class="k">${label}</span>
    ${pct
      ? html`<div class="row"><span class=${'v' + (green ? ' green' : '')}>${value}</span><span class="pct">${pct}</span></div>`
      : html`<span class=${'v' + (green ? ' green' : '')}>${value}</span>`}
    ${sub ? html`<span class="s">${sub}</span>` : null}
  </div>`;
}

export function Card({ title, sub, action, children, className = '' }) {
  return html`<div class=${'card ' + className}>
    ${title ? html`<div class="card-head">
      <div style="display:flex;flex-direction:column;gap:2px"><span class="card-title">${title}</span>${sub ? html`<span class="card-sub">${sub}</span>` : null}</div>
      ${action || null}
    </div>` : null}
    ${children}
  </div>`;
}

export function ErrorBox({ error }) {
  return error ? html`<div class="error-box">${error}</div>` : null;
}

export function Empty({ children }) { return html`<div class="empty">${children}</div>`; }

export function Dot({ tone }) { return html`<span class=${'dot ' + tone}></span>`; }

// Gráfico de barras (uma ou duas séries empilhadas), com tooltip por coluna.
// series: [{label, a, b?}]; cores: a = principal, b = secundária.
export function BarChart({ series, colorA = '#4CDE59', colorB = '#F26E22', gutter = 36, format = (v) => v, tip }) {
  const [hover, setHover] = useState(null);
  const W = 760, H = 180, n = Math.max(1, series.length), slot = W / n, bw = Math.min(56, slot * 0.5);
  const peak = Math.max(0, ...series.map((s) => (s.a || 0) + (s.b || 0)));
  const integer = series.every((s) => Number.isInteger(s.a || 0) && Number.isInteger(s.b || 0));
  const max = peak > 0 ? peak : 1;
  const mid = integer ? Math.round(max / 2) : max / 2;
  const scale = (v) => (v / max) * 120;
  // Trinta colunas não cabem trinta rótulos: mostra no máximo ~8, espaçados.
  const labelStep = Math.ceil(n / 8);
  const path = (x, top, w, bottom, r = 4) => {
    const h = bottom - top; if (h <= 0) return '';
    const rr = Math.min(r, h, w / 2);
    return `M${x} ${bottom} V${top + rr} Q${x} ${top} ${x + rr} ${top} H${x + w - rr} Q${x + w} ${top} ${x + w} ${top + rr} V${bottom} Z`;
  };
  return html`<div class="chart" style=${`padding-left:${gutter}px`}>
    <span class="ticks" style="top:46px">${format(max)}</span>
    <span class="ticks" style="top:106px">${format(mid)}</span>
    ${hover !== null ? html`<div class="tooltip" style=${`left:calc(${gutter}px + ${(slot * hover + slot / 2) / W * 100}%)`}>
      <b>${series[hover].label}</b><span>${tip ? tip(series[hover]) : format(series[hover].a)}</span>
    </div>` : null}
    <svg width="100%" viewBox=${`0 0 ${W} ${H}`}>
      <line x1="0" y1="180" x2=${W} y2="180" stroke="var(--line-2)" stroke-width="1"/>
      <line x1="0" y1="120" x2=${W} y2="120" stroke="var(--line)" stroke-width="1"/>
      <line x1="0" y1="60" x2=${W} y2="60" stroke="var(--line)" stroke-width="1"/>
      ${series.map((s, i) => {
        const cx = slot * i + slot / 2, x = cx - bw / 2;
        const ha = scale(s.a || 0), hb = scale(s.b || 0);
        const aTop = H - ha, bBottom = aTop - 2, bTop = bBottom - hb;
        return html`<g key=${i}>
          <path d=${path(x, aTop, bw, H)} fill=${colorA}/>
          ${hb > 0 ? html`<path d=${path(x, bTop, bw, bBottom)} fill=${colorB}/>` : null}
          <rect x=${slot * i} y="0" width=${slot} height="180" fill=${hover === i ? 'var(--soft-2)' : 'transparent'} onMouseEnter=${() => setHover(i)} onMouseLeave=${() => setHover(null)}/>
        </g>`;
      })}
    </svg>
    <div class="x" style=${`grid-template-columns: repeat(${n}, minmax(0, 1fr))`}>${series.map((s, i) => html`<span>${i % labelStep ? '' : s.label}</span>`)}</div>
  </div>`;
}

// ── menu suspenso ────────────────────────────────────────────────────
// Receita do Aya Design System (preview/menu.html): superfície overlay,
// item com ícone que acende no hover, atalho à direita, separador, item
// destrutivo. Fecha por Esc e clique fora; setas navegam; abre para cima
// quando não cabe embaixo.
// items: [{ label, icon?, onClick?, href?, hint?, danger?, disabled? } | { heading } | 'separator']
// Select do DS (preview/select.html): gatilho com a receita do .input e listbox em
// popover fixo (mesma superfície do Menu), check no selecionado, teclado completo.
// `options` aceita lista [{ value, label, hint?, disabled? }] ou mapa { id: label }.
// `onChange(value)` recebe o valor, não o evento. Sem `<select>` nativo: o popup do
// sistema não tem a personalidade do kit e ignora o tema.
export function Select({ value, options = [], onChange, placeholder = '—', allowEmpty = false, emptyLabel = '—', disabled = false, size = '', className = '', title, ariaLabel }) {
  const list = (Array.isArray(options) ? options : Object.entries(options || {}).map(([v, label]) => ({ value: v, label })))
    .map((o) => ({ ...o, value: String(o.value) }));
  const all = allowEmpty ? [{ value: '', label: emptyLabel }, ...list] : list;
  const current = value == null ? '' : String(value);
  const selectedIndex = all.findIndex((o) => o.value === current);
  const selected = selectedIndex >= 0 ? all[selectedIndex] : null;
  const [open, setOpen] = useState(false);
  const [hl, setHl] = useState(0);
  const [pos, setPos] = useState(null);
  const ref = useRef(null);
  const listRef = useRef(null);
  const typed = useRef({ text: '', at: 0 });

  const close = () => setOpen(false);
  const openList = () => {
    if (disabled || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const up = window.innerHeight - rect.bottom < 240 && rect.top > 240;
    const style = { left: `${rect.left}px`, minWidth: `${rect.width}px` };
    if (up) style.bottom = `${window.innerHeight - rect.top + 4}px`; else style.top = `${rect.bottom + 4}px`;
    setPos({ up, style });
    setHl(Math.max(0, selectedIndex));
    setOpen(true);
  };
  const choose = (index) => {
    const option = all[index];
    if (!option || option.disabled) return;
    close();
    if (option.value !== current && onChange) onChange(option.value);
    if (ref.current) ref.current.focus();
  };
  const move = (from, step) => {
    if (!all.length) return from;
    let next = from;
    for (let i = 0; i < all.length; i += 1) {
      next = (next + step + all.length) % all.length;
      if (!all[next].disabled) return next;
    }
    return from;
  };
  const onKey = (event) => {
    if (disabled) return;
    const { key } = event;
    if (!open) {
      if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') { event.preventDefault(); openList(); }
      return;
    }
    if (key === 'Escape') { event.preventDefault(); close(); return; }
    if (key === 'Tab') { close(); return; }
    if (key === 'ArrowDown') { event.preventDefault(); setHl((i) => move(i, 1)); return; }
    if (key === 'ArrowUp') { event.preventDefault(); setHl((i) => move(i, -1)); return; }
    if (key === 'Home') { event.preventDefault(); setHl(move(-1, 1)); return; }
    if (key === 'End') { event.preventDefault(); setHl(move(0, -1)); return; }
    if (key === 'Enter' || key === ' ') { event.preventDefault(); choose(hl); return; }
    if (key.length === 1 && !event.metaKey && !event.ctrlKey) {
      // type-ahead: acumula letras por 600 ms e pula para o primeiro rótulo que casa
      const now = Date.now();
      typed.current = { text: (now - typed.current.at < 600 ? typed.current.text : '') + key.toLowerCase(), at: now };
      const hit = all.findIndex((o, i) => i > hl && !o.disabled && String(o.label).toLowerCase().startsWith(typed.current.text));
      const wrap = hit < 0 ? all.findIndex((o) => !o.disabled && String(o.label).toLowerCase().startsWith(typed.current.text)) : hit;
      if (wrap >= 0) setHl(wrap);
    }
  };
  useEffect(() => {
    if (!open) return;
    const onDoc = (event) => {
      if (ref.current && ref.current.contains(event.target)) return;
      if (listRef.current && listRef.current.contains(event.target)) return;
      close();
    };
    const onScroll = (event) => { if (listRef.current && listRef.current.contains(event.target)) return; close(); };
    document.addEventListener('mousedown', onDoc);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', close);
    return () => { document.removeEventListener('mousedown', onDoc); window.removeEventListener('scroll', onScroll, true); window.removeEventListener('resize', close); };
  }, [open]);
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector('.option.is-hl');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }, [open, hl]);

  const label = selected ? selected.label : placeholder;
  return html`<div class=${'select-anchor' + (size ? ' ' + size : '') + (className ? ' ' + className : '')}>
    <button type="button" ref=${ref} class=${'select' + (size ? ' ' + size : '')} role="combobox" aria-haspopup="listbox" aria-expanded=${open}
      aria-label=${ariaLabel} title=${title} disabled=${disabled} onClick=${() => (open ? close() : openList())} onKeyDown=${onKey}>
      <span class=${'val' + (selected && selected.value !== '' ? '' : ' ph')}>${label}</span>
      <i class="fi fi-rr-angle-small-down" aria-hidden="true"></i>
    </button>
    ${open ? html`<ul ref=${listRef} class=${'listbox' + (pos && pos.up ? ' up' : '')} style=${pos ? pos.style : null} role="listbox" aria-label=${ariaLabel || title}>
      ${all.map((option, index) => html`<li key=${option.value} class=${'option' + (index === hl ? ' is-hl' : '')} role="option"
          aria-selected=${option.value === current} aria-disabled=${option.disabled ? 'true' : undefined}
          onMouseEnter=${() => setHl(index)} onMouseDown=${(event) => event.preventDefault()} onClick=${() => choose(index)}>
        <span>${option.label}</span>${option.hint ? html`<small>${option.hint}</small>` : null}
        ${option.value === current ? html`<i class="fi fi-rr-check check" aria-hidden="true"></i>` : null}
      </li>`)}
    </ul>` : null}
  </div>`;
}

export function Menu({ label = 'Mais ações', icon = 'menu-dots', items = [], align = 'end', className = '', size = 'md' }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (event) => { if (ref.current && !ref.current.contains(event.target)) setOpen(false); };
    const onKey = (event) => {
      if (event.key === 'Escape') { setOpen(false); const t = ref.current && ref.current.querySelector('.menu-trigger'); if (t) t.focus(); return; }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      const focusables = ref.current ? [...ref.current.querySelectorAll('.menu-item:not(:disabled)')] : [];
      if (!focusables.length) return;
      event.preventDefault();
      const index = focusables.indexOf(document.activeElement);
      const next = event.key === 'ArrowDown' ? (index + 1) % focusables.length : (index - 1 + focusables.length) % focusables.length;
      focusables[next].focus();
    };
    const onScroll = () => setOpen(false);
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    const first = ref.current && ref.current.querySelector('.menu-item:not(:disabled)');
    if (first) first.focus();
    return () => {
      document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true); window.removeEventListener('resize', onScroll);
    };
  }, [open]);
  // Posição fixa a partir do gatilho: o menu nunca é cortado por overflow de card ou tabela.
  const toggle = (event) => {
    event.stopPropagation();
    if (!open && ref.current) {
      const rect = ref.current.getBoundingClientRect();
      const up = window.innerHeight - rect.bottom < 280 && rect.top > 280;
      const style = up ? { bottom: `${window.innerHeight - rect.top + 4}px` } : { top: `${rect.bottom + 4}px` };
      if (align === 'start') style.left = `${rect.left}px`; else style.right = `${window.innerWidth - rect.right}px`;
      setPos({ up, style });
    }
    setOpen(!open);
  };
  const pick = (item) => (event) => { event.stopPropagation(); setOpen(false); if (item.onClick) item.onClick(); };
  return html`<div class=${'menu-anchor ' + className} ref=${ref} onClick=${(event) => event.stopPropagation()}>
    <button type="button" class=${'icon-btn menu-trigger' + (size === 'sm' ? ' sm' : '')} aria-haspopup="menu" aria-expanded=${open} aria-label=${label} title=${label} onClick=${toggle}><i class=${`fi fi-rr-${icon}`} aria-hidden="true"></i></button>
    ${open ? html`<ul class=${'menu' + (pos && pos.up ? ' up' : '') + (align === 'start' ? ' start' : '')} style=${pos ? pos.style : null} role="menu" aria-label=${label}>
      ${items.map((item, index) => item === 'separator'
        ? html`<li class="menu-separator" role="separator" key=${'sep' + index}></li>`
        : item.heading
          ? html`<li class="menu-heading" key=${'h' + index}>${item.heading}</li>`
          : html`<li key=${item.label} role="none">${item.href
            ? html`<a class=${'menu-item' + (item.danger ? ' danger' : '')} role="menuitem" href=${item.href} target="_blank" rel="noopener" onClick=${pick(item)}>${item.icon ? html`<i class=${`fi fi-rr-${item.icon}`} aria-hidden="true"></i>` : html`<i class="menu-gap"></i>`}<span>${item.label}</span>${item.hint ? html`<kbd>${item.hint}</kbd>` : null}</a>`
            : html`<button type="button" class=${'menu-item' + (item.danger ? ' danger' : '')} role="menuitem" disabled=${item.disabled} onClick=${pick(item)}>${item.icon ? html`<i class=${`fi fi-rr-${item.icon}`} aria-hidden="true"></i>` : html`<i class="menu-gap"></i>`}<span>${item.label}</span>${item.hint ? html`<kbd>${item.hint}</kbd>` : null}</button>`}</li>`)}
    </ul>` : null}
  </div>`;
}
