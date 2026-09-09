// Utilidades compartilhadas pelas telas: html (htm+preact), acesso à API,
// formatação pt-BR, ícones e componentes pequenos. Nenhuma tela importa outra.
import { h, Fragment } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import htm from 'htm';

export const html = htm.bind(h);
export { Fragment };

// ── API ──────────────────────────────────────────────────────────────
export async function api(path, options = {}) {
  const res = await fetch(path, { headers: { Accept: 'application/json' }, ...options });
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

export function post(path, body) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body || {}) });
}

// Busca e re-busca a cada `every` ms. Devolve {data, error, loading, reload}.
export function useApi(path, { every = 0, deps = [] } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const alive = useRef(true);
  const load = async () => {
    try {
      const data = await api(path);
      if (alive.current) setState({ data, error: null, loading: false });
    } catch (err) {
      if (alive.current) setState((s) => ({ data: s.data, error: err.message, loading: false }));
    }
  };
  useEffect(() => {
    alive.current = true;
    setState((s) => ({ ...s, loading: s.data === null }));
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
  left: () => svg('<path d="M15 6l-6 6 6 6"/>', 16),
  right: () => svg('<path d="M9 6l6 6-6 6"/>', 16),
  check: () => svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 44),
  power: () => svg('<path d="M12 3v9"/><path d="M6.6 7.2a8 8 0 1010.8 0"/>', 44),
  user: () => svg('<path d="M20 21a8 8 0 10-16 0"/><circle cx="12" cy="8" r="4"/>', 16),
};

// ── componentes pequenos ─────────────────────────────────────────────
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
      <line x1="0" y1="180" x2=${W} y2="180" stroke="#070B0D29" stroke-width="1"/>
      <line x1="0" y1="120" x2=${W} y2="120" stroke="#070B0D0F" stroke-width="1"/>
      <line x1="0" y1="60" x2=${W} y2="60" stroke="#070B0D0F" stroke-width="1"/>
      ${series.map((s, i) => {
        const cx = slot * i + slot / 2, x = cx - bw / 2;
        const ha = scale(s.a || 0), hb = scale(s.b || 0);
        const aTop = H - ha, bBottom = aTop - 2, bTop = bBottom - hb;
        return html`<g key=${i}>
          <path d=${path(x, aTop, bw, H)} fill=${colorA}/>
          ${hb > 0 ? html`<path d=${path(x, bTop, bw, bBottom)} fill=${colorB}/>` : null}
          <rect x=${slot * i} y="0" width=${slot} height="180" fill=${hover === i ? 'rgba(7,11,13,0.04)' : 'transparent'} onMouseEnter=${() => setHover(i)} onMouseLeave=${() => setHover(null)}/>
        </g>`;
      })}
    </svg>
    <div class="x" style=${`grid-template-columns: repeat(${n}, minmax(0, 1fr))`}>${series.map((s, i) => html`<span>${i % labelStep ? '' : s.label}</span>`)}</div>
  </div>`;
}
