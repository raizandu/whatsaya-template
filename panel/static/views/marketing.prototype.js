// PROTÓTIPO — descartável. Três variantes de "Páginas" como ambiente próprio da
// aba Marketing, trocadas por `#marketing?variant=A|B|C` e pela barra flutuante.
// Lê dados reais (/api/marketing/pages e /api/marketing) e não grava nada:
// toda ação de escrita vira toast "protótipo". Some quando o param não existe.
import { useEffect, useState } from 'preact/hooks';
import { html, useApi, fmt, Empty, isAdmin } from '../lib.js';

export const VARIANTS = [
  ['A', 'Estúdio: lista + wizard + preview'],
  ['B', 'Tabela de desempenho + gaveta'],
  ['C', 'Cards de campanha + stepper em tela cheia'],
];

export function variantFromHash() {
  const query = location.hash.split('?')[1] || '';
  const value = new URLSearchParams(query).get('variant');
  return value && VARIANTS.some(([key]) => key === value) ? value : null;
}

function setVariant(key) {
  location.hash = `marketing?variant=${key}`;
}

const STEPS = [
  ['identidade', 'Identidade', ['slug', 'niche', 'title', 'description']],
  ['abertura', 'Abertura', ['h1', 'sub']],
  ['nicho', 'Bloco do nicho', ['niche_intro', 'niche_pains']],
  ['quiz', 'Pergunta do quiz', ['question', 'question_sub', 'options']],
  ['prova', 'Prova social', ['proofs']],
  ['publicar', 'Pixel e publicação', ['pixel_id', 'enabled']],
];
const LABEL = {
  slug: 'Slug', niche: 'Nicho', title: 'Título SEO', description: 'Descrição (meta)', h1: 'Título da abertura',
  sub: 'Subtítulo', niche_intro: 'Texto do nicho', niche_pains: 'Dores (uma por linha)', question: 'Pergunta',
  question_sub: 'Complemento', options: 'Opções (uma por linha)', proofs: 'Provas sociais (uma por linha)',
  pixel_id: 'Pixel da Meta', enabled: 'Página no ar',
};
const MULTILINE = new Set(['description', 'sub', 'niche_intro', 'niche_pains', 'options', 'proofs']);
const asText = (value) => Array.isArray(value)
  ? value.map((v) => (typeof v === 'object' ? [v.option, v.who, v.quote].filter(Boolean).join(' | ') : v)).join('\n')
  : value == null ? '' : String(value);

// Números por página vindos do relatório: `lps[]` usa o slug como id e `home` para a raiz.
function statsFor(report, page) {
  const id = page.slug || 'home';
  const row = (report && report.lps || []).find((lp) => lp.lp === id) || { view: 0, start: 0, complete: 0, whatsapp_click: 0, arrived: 0 };
  const rate = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  return { ...row, clickRate: rate(row.whatsapp_click, row.view), arriveRate: rate(row.arrived, row.whatsapp_click), completeRate: rate(row.complete, row.start) };
}

// Insight determinístico: a maior queda do funil vira a frase de diagnóstico.
function insightFor(s, page) {
  if (!s.view) return { tone: 'off', text: 'Sem sessões no período. Ainda não há o que otimizar: mande tráfego.' };
  if (s.start / s.view < 0.4) return { tone: 'warn', text: `Só ${s.start ? Math.round((s.start / s.view) * 100) : 0}% começam o quiz. A abertura não está segurando: revise H1 e subtítulo.` };
  if (s.completeRate < 50) return { tone: 'warn', text: `${s.completeRate}% terminam o quiz. Pergunta do nicho ou volume de passos está pesando.` };
  if (s.clickRate < 20) return { tone: 'warn', text: `${s.clickRate}% clicam no WhatsApp ao final. Tela final e CTA precisam de trabalho.` };
  if (s.arriveRate < 60) return { tone: 'warn', text: `${s.arriveRate}% dos cliques viram mensagem. Gente abre o WhatsApp e não envia: mensagem pré-preenchida longa demais.` };
  return { tone: 'ok', text: `Funil saudável: ${s.clickRate}% de clique e ${s.arriveRate}% chegam. ${page.proofs && page.proofs.length ? '' : 'Falta prova social real.'}` };
}

function Funnel({ s, compact = false }) {
  const steps = [['Viram', s.view], ['Começaram', s.start], ['Terminaram', s.complete], ['Clicaram', s.whatsapp_click], ['Chegaram', s.arrived]];
  const max = Math.max(1, s.view);
  return html`<div class=${'pt-funnel' + (compact ? ' compact' : '')}>${steps.map(([label, value]) => html`<div class="pt-funnel-row" key=${label}>
    <span>${label}</span><i><b style=${`width:${Math.max(2, (value / max) * 100)}%`}></b></i><em>${fmt.int(value)}</em>
  </div>`)}</div>`;
}

function Preview({ page }) {
  return html`<div class="pt-phone"><div class="pt-phone-bar"><b>AYA</b><span>Passo 1 de 6</span></div>
    <h3>${page.h1 || 'Título da abertura'}</h3>
    <p>${(page.sub || '').replace(/\*\*/g, '')}</p>
    ${page.niche_intro ? html`<p class="pt-phone-niche">${page.niche_intro}</p>` : null}
    ${(page.niche_pains || []).length ? html`<ul>${page.niche_pains.map((p) => html`<li key=${p}>${p}</li>`)}</ul>` : null}
    <div class="pt-phone-cta">Ver como funcionaria no meu negócio</div>
    <div class="pt-phone-q">${page.question}</div>
    ${(page.options || []).slice(0, 3).map((o) => html`<div class="pt-phone-opt" key=${o}>${o}</div>`)}
  </div>`;
}

function Field({ name, value, onInput }) {
  if (name === 'enabled') return html`<label class="field-label settings-check"><span>${LABEL[name]}</span><input type="checkbox" class="switch" checked=${!!value} onChange=${onInput}/></label>`;
  return html`<label class="field-label">${LABEL[name]}${MULTILINE.has(name)
    ? html`<textarea class="input" value=${asText(value)} onInput=${onInput}></textarea>`
    : html`<input class="input" value=${asText(value)} onInput=${onInput}/>`}</label>`;
}

function useDraft(initial) {
  const [draft, setDraft] = useState(initial);
  useEffect(() => { setDraft(initial); }, [initial && initial.slug]);
  const set = (name) => (event) => setDraft((d) => ({ ...d, [name]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }));
  return [draft || initial, set];
}

// ── A · Estúdio: lista à esquerda com semáforo, wizard no meio, preview à direita ──
function VariantA({ pages, report, setToast }) {
  const [slug, setSlug] = useState(pages[0] ? pages[0].slug : '');
  const [step, setStep] = useState(0);
  const page = pages.find((p) => p.slug === slug) || pages[0];
  const [draft, set] = useDraft(page);
  if (!page) return html`<${Empty}>Nenhuma página.</${Empty}>`;
  const [, stepLabel, fields] = STEPS[step];
  const s = statsFor(report, page);
  const insight = insightFor(s, page);
  return html`<div class="pt-studio">
    <aside class="pt-studio-list">
      <header><span class="kpi-eyebrow">Páginas</span><button class="btn primary sm" onClick=${() => setToast('Protótipo: criar página abre o wizard vazio')}>Nova</button></header>
      ${pages.map((p) => { const ps = statsFor(report, p); const ins = insightFor(ps, p); return html`<button key=${p.slug || '/'} class=${'pt-studio-item' + (p.slug === page.slug ? ' active' : '')} onClick=${() => { setSlug(p.slug); setStep(0); }}>
        <span class=${'dot ' + ins.tone}></span>
        <span class="grow"><b>${p.slug ? `/${p.slug}/` : '/ (raiz)'}</b><small>${p.niche || 'Geral'}</small></span>
        <em>${fmt.int(ps.arrived)}</em>
      </button>`; })}
    </aside>
    <section class="pt-studio-editor">
      <div class=${'pt-insight ' + insight.tone}><span class="kpi-eyebrow">Insight</span><p>${insight.text}</p></div>
      <${Funnel} s=${s} compact/>
      <ol class="pt-steps">${STEPS.map(([id, label], i) => html`<li key=${id} class=${i === step ? 'current' : i < step ? 'done' : ''} onClick=${() => setStep(i)}><i>${i < step ? '✓' : i + 1}</i>${label}</li>`)}</ol>
      <div class="pt-step-body">
        <h3>${stepLabel}</h3>
        ${fields.map((f) => html`<${Field} key=${f} name=${f} value=${draft[f]} onInput=${set(f)}/>`)}
      </div>
      <div class="form-row">
        <button class="btn" disabled=${step === 0} onClick=${() => setStep(step - 1)}>Voltar</button>
        ${step < STEPS.length - 1
          ? html`<button class="btn primary" onClick=${() => setStep(step + 1)}>Próximo</button>`
          : html`<button class="btn primary" onClick=${() => setToast('Protótipo: não publica')}>Salvar e publicar</button>`}
        <a class="btn sm" style="margin-left:auto" href=${`/${page.slug ? page.slug + '/' : ''}`} target="_blank" rel="noopener">Abrir no ar</a>
      </div>
    </section>
    <aside class="pt-studio-preview"><span class="kpi-eyebrow">Prévia</span><${Preview} page=${{ ...draft, niche_pains: asText(draft.niche_pains).split('\n').filter(Boolean), options: asText(draft.options).split('\n').filter(Boolean) }}/></aside>
  </div>`;
}

// ── B · Tabela: desempenho lado a lado, ordenável; editor em gaveta lateral com seções ──
function VariantB({ pages, report, setToast }) {
  const [sort, setSort] = useState('arrived');
  const [open, setOpen] = useState(null);
  const rows = pages.map((p) => ({ page: p, s: statsFor(report, p), insight: insightFor(statsFor(report, p), p) }))
    .sort((a, b) => (b.s[sort] || 0) - (a.s[sort] || 0));
  const th = (key, label) => html`<th class="num"><button class=${'pt-sort' + (sort === key ? ' active' : '')} onClick=${() => setSort(key)}>${label}</button></th>`;
  const [draft, set] = useDraft(open);
  return html`<div class="pt-table-wrap">
    <div class="card">
      <div class="card-head"><div><span class="card-title">Páginas</span><span class="card-sub">Últimos 30 dias · clique no cabeçalho para ordenar</span></div>
        <button class="btn primary sm" onClick=${() => setToast('Protótipo: nova página abre a gaveta vazia')}>Nova página</button></div>
      <div style="overflow-x:auto"><table class="plain pt-table">
        <thead><tr><th>Página</th><th>Status</th>${th('view', 'Sessões')}${th('whatsapp_click', 'Cliques')}${th('clickRate', '% clique')}${th('arrived', 'Chegaram')}${th('arriveRate', '% chegada')}<th>Diagnóstico</th><th></th></tr></thead>
        <tbody>${rows.map(({ page, s, insight }) => html`<tr key=${page.slug || '/'} class=${open && open.slug === page.slug ? 'active' : ''}>
          <td><b>${page.slug ? `/${page.slug}/` : '/ (raiz)'}</b><br/><small style="color:var(--muted)">${page.niche || 'Geral'}</small></td>
          <td><span class=${'status-pill ' + (page.enabled ? 'ok' : 'warn')}>${page.enabled ? 'No ar' : 'Pausada'}</span></td>
          <td class="num">${fmt.int(s.view)}</td><td class="num">${fmt.int(s.whatsapp_click)}</td><td class="num">${s.clickRate}%</td>
          <td class="num"><b>${fmt.int(s.arrived)}</b></td><td class="num">${s.arriveRate}%</td>
          <td><span class=${'dot ' + insight.tone}></span> <small>${insight.text}</small></td>
          <td><button class="btn sm" onClick=${() => setOpen(page)}>Editar</button></td>
        </tr>`)}</tbody>
      </table></div>
    </div>
    ${open ? html`<div class="pt-backdrop" onClick=${() => setOpen(null)}></div>
    <aside class="pt-drawer" role="dialog" aria-label="Editar página">
      <header><div><span class="kpi-eyebrow">Editar</span><h3>${open.slug ? `/${open.slug}/` : 'Raiz'}</h3></div><button class="btn sm" onClick=${() => setOpen(null)}>Fechar</button></header>
      <${Funnel} s=${statsFor(report, open)} compact/>
      <div class="pt-drawer-body">${STEPS.map(([id, label, fields]) => html`<details key=${id} open=${id === 'identidade'}><summary>${label}</summary>
        ${fields.map((f) => html`<${Field} key=${f} name=${f} value=${draft[f]} onInput=${set(f)}/>`)}
      </details>`)}</div>
      <footer class="form-row"><button class="btn primary" onClick=${() => setToast('Protótipo: não publica')}>Salvar e publicar</button><button class="btn" onClick=${() => setToast('Protótipo: não pausa')}>${open.enabled ? 'Pausar' : 'Colocar no ar'}</button></footer>
    </aside>` : null}
  </div>`;
}

// ── C · Cards de campanha com funil visual; editar é um stepper em tela cheia, uma seção por tela ──
function VariantC({ pages, report, setToast }) {
  const [editing, setEditing] = useState(null);
  const [step, setStep] = useState(0);
  const [draft, set] = useDraft(editing);
  if (editing) {
    const [, stepLabel, fields] = STEPS[step];
    return html`<div class="pt-fullscreen">
      <header><button class="btn sm" onClick=${() => setEditing(null)}>‹ Páginas</button><span class="kpi-eyebrow">${editing.slug ? `/${editing.slug}/` : 'Raiz'} · passo ${step + 1} de ${STEPS.length}</span>
        <i class="pt-progress"><b style=${`width:${((step + 1) / STEPS.length) * 100}%`}></b></i></header>
      <section><h2>${stepLabel}</h2>${fields.map((f) => html`<${Field} key=${f} name=${f} value=${draft[f]} onInput=${set(f)}/>`)}</section>
      <footer class="form-row"><button class="btn" disabled=${step === 0} onClick=${() => setStep(step - 1)}>Voltar</button>
        ${step < STEPS.length - 1 ? html`<button class="btn primary" onClick=${() => setStep(step + 1)}>Continuar</button>` : html`<button class="btn primary" onClick=${() => setToast('Protótipo: não publica')}>Publicar</button>`}</footer>
    </div>`;
  }
  return html`<div class="pt-cards">
    <button class="pt-card pt-card-new" onClick=${() => setToast('Protótipo: nova página abre o stepper vazio')}><b>+</b><span>Nova página de nicho</span></button>
    ${pages.map((page) => { const s = statsFor(report, page); const insight = insightFor(s, page); return html`<article class="pt-card" key=${page.slug || '/'}>
      <header><div><b>${page.niche || 'Página raiz'}</b><small>${page.slug ? `/${page.slug}/` : '/'}</small></div><span class=${'status-pill ' + (page.enabled ? 'ok' : 'warn')}>${page.enabled ? 'No ar' : 'Pausada'}</span></header>
      <div class="pt-card-kpis"><div><b>${fmt.int(s.view)}</b><span>sessões</span></div><div><b>${s.clickRate}%</b><span>clicam</span></div><div><b>${fmt.int(s.arrived)}</b><span>chegaram</span></div></div>
      <${Funnel} s=${s} compact/>
      <p class=${'pt-card-insight ' + insight.tone}>${insight.text}</p>
      <footer><button class="btn sm primary" onClick=${() => { setEditing(page); setStep(0); }}>Editar</button><a class="btn sm" href=${`/${page.slug ? page.slug + '/' : ''}`} target="_blank" rel="noopener">Abrir</a></footer>
    </article>`; })}
  </div>`;
}

function Switcher({ current }) {
  const index = VARIANTS.findIndex(([key]) => key === current);
  const go = (delta) => setVariant(VARIANTS[(index + delta + VARIANTS.length) % VARIANTS.length][0]);
  useEffect(() => {
    const onKey = (event) => {
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      if (['INPUT', 'TEXTAREA'].includes(tag) || (document.activeElement && document.activeElement.isContentEditable)) return;
      if (event.key === 'ArrowLeft') go(-1);
      if (event.key === 'ArrowRight') go(1);
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  });
  return html`<div class="pt-switcher"><button onClick=${() => go(-1)} aria-label="Variante anterior">←</button><span><b>${current}</b> — ${VARIANTS[index][1]}</span><button onClick=${() => go(1)} aria-label="Próxima variante">→</button><a href="#marketing">sair</a></div>`;
}

const CSS = `
.pt-switcher{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:var(--z-sticky);display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:999px;background:var(--ink);color:var(--card);box-shadow:var(--shadow-lg);font-size:13px}
.pt-switcher button{width:28px;height:28px;border:0;border-radius:999px;background:var(--ink-2);color:var(--card);cursor:pointer}
.pt-switcher a{color:var(--orange);font-weight:700;text-decoration:none;margin-left:4px}
.pt-funnel{display:flex;flex-direction:column;gap:6px}
.pt-funnel-row{display:grid;grid-template-columns:78px 1fr 40px;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
.pt-funnel-row i{display:block;height:8px;border-radius:4px;background:var(--soft-2);overflow:hidden}
.pt-funnel-row b{display:block;height:100%;background:var(--green);border-radius:4px}
.pt-funnel-row em{font-style:normal;text-align:right;font-weight:700;color:var(--ink);font-family:var(--mono)}
.pt-funnel.compact .pt-funnel-row{grid-template-columns:70px 1fr 36px;font-size:11px}
.pt-insight{padding:12px 14px;border-radius:var(--radius);background:var(--soft);border-left:3px solid var(--line-2);margin-bottom:12px}
.pt-insight.warn{border-left-color:var(--orange);background:var(--orange-wash)}
.pt-insight.ok{border-left-color:var(--green);background:var(--green-wash)}
.pt-insight p{margin:4px 0 0;font-size:13px;color:var(--ink)}
.pt-studio{display:grid;grid-template-columns:240px minmax(0,1fr) 260px;gap:16px;align-items:start}
.pt-studio-list{display:flex;flex-direction:column;gap:4px;max-height:70vh;overflow:auto;padding:12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card)}
.pt-studio-list header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.pt-studio-item{display:flex;align-items:center;gap:8px;width:100%;text-align:left;padding:8px;border:0;border-radius:var(--radius-sm);background:transparent;cursor:pointer;color:var(--ink)}
.pt-studio-item.active{background:var(--soft-2)}
.pt-studio-item .grow{display:flex;flex-direction:column;min-width:0}
.pt-studio-item b{font-size:13px}.pt-studio-item small{color:var(--muted);font-size:11px}
.pt-studio-item em{font-style:normal;font-family:var(--mono);font-weight:700;font-size:12px}
.pt-studio-editor{padding:16px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card);display:flex;flex-direction:column;gap:14px}
.pt-steps{display:flex;gap:6px;list-style:none;margin:0;padding:0;flex-wrap:wrap}
.pt-steps li{display:flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;background:var(--soft);font-size:12px;font-weight:600;color:var(--muted);cursor:pointer}
.pt-steps li i{width:18px;height:18px;border-radius:50%;background:var(--card);display:inline-flex;align-items:center;justify-content:center;font-style:normal;font-size:11px;box-shadow:inset 0 0 0 1px var(--hairline-strong)}
.pt-steps li.current{background:var(--ink);color:var(--card)}.pt-steps li.current i{background:var(--orange);color:var(--ink);box-shadow:none}
.pt-steps li.done i{background:var(--green);color:var(--ink);box-shadow:none}
.pt-step-body{display:flex;flex-direction:column;gap:10px}.pt-step-body h3{margin:0;font-size:16px}
.pt-studio-preview{position:sticky;top:72px;display:flex;flex-direction:column;gap:8px}
.pt-phone{border:1px solid var(--line);border-radius:22px;padding:14px;background:var(--soft);font-size:12px;line-height:1.35}
.pt-phone-bar{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:10px}
.pt-phone h3{margin:0 0 6px;font-size:17px;line-height:1.1;letter-spacing:-.02em}
.pt-phone p{margin:0 0 8px;color:var(--muted)}.pt-phone-niche{color:var(--ink)}
.pt-phone ul{margin:0 0 8px;padding-left:16px;color:var(--ink)}
.pt-phone-cta{padding:10px;border-radius:12px;background:var(--ink);color:var(--card);text-align:center;font-weight:700;margin-bottom:12px}
.pt-phone-q{font-weight:700;margin-bottom:6px}.pt-phone-opt{padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--card);margin-bottom:6px}
.pt-table tr.active td{background:var(--soft)}
.pt-sort{border:0;background:transparent;font:inherit;color:var(--muted);cursor:pointer}.pt-sort.active{color:var(--ink);font-weight:700}
.pt-backdrop{position:fixed;inset:0;background:hsl(var(--shadow-tint) / .35);z-index:var(--z-sticky)}
.pt-drawer{position:fixed;top:0;right:0;bottom:0;width:min(520px,100%);z-index:calc(var(--z-sticky) + 1);background:var(--card);box-shadow:var(--shadow-xl);display:flex;flex-direction:column;gap:12px;padding:16px;overflow:auto}
.pt-drawer header{display:flex;justify-content:space-between;align-items:center}.pt-drawer h3{margin:2px 0 0;font-size:18px}
.pt-drawer-body details{border:1px solid var(--line);border-radius:var(--radius-sm);padding:8px 12px;margin-bottom:8px}
.pt-drawer-body summary{cursor:pointer;font-weight:700;font-size:13px}.pt-drawer-body details[open] summary{margin-bottom:8px}
.pt-drawer-body .field-label{margin-bottom:8px}
.pt-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.pt-card{display:flex;flex-direction:column;gap:12px;padding:16px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card);box-shadow:var(--shadow-lift)}
.pt-card header{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}.pt-card header div{display:flex;flex-direction:column}.pt-card header small{color:var(--muted);font-size:11px}
.pt-card-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.pt-card-kpis div{display:flex;flex-direction:column}.pt-card-kpis b{font:700 20px/1.1 var(--mono)}.pt-card-kpis span{font-size:11px;color:var(--muted)}
.pt-card-insight{margin:0;font-size:12px;color:var(--muted);padding-left:10px;border-left:3px solid var(--line-2)}.pt-card-insight.warn{border-left-color:var(--orange);color:var(--ink)}.pt-card-insight.ok{border-left-color:var(--green)}
.pt-card footer{display:flex;gap:6px;margin-top:auto}
.pt-card-new{align-items:center;justify-content:center;border-style:dashed;cursor:pointer;color:var(--muted);min-height:180px}.pt-card-new b{font-size:32px;color:var(--orange)}
.pt-fullscreen{position:fixed;inset:0;z-index:calc(var(--z-sticky) + 1);background:var(--soft);display:flex;flex-direction:column;padding:24px;gap:20px;overflow:auto}
.pt-fullscreen header{display:flex;align-items:center;gap:14px}.pt-fullscreen header .pt-progress{flex:1;height:3px;border-radius:2px;background:var(--soft-2);overflow:hidden}.pt-progress b{display:block;height:100%;background:var(--orange)}
.pt-fullscreen section{max-width:620px;width:100%;margin:0 auto;display:flex;flex-direction:column;gap:12px}.pt-fullscreen h2{margin:0;font-size:26px;letter-spacing:-.02em}
.pt-fullscreen footer{max-width:620px;width:100%;margin:0 auto}
@media (max-width:1100px){.pt-studio{grid-template-columns:220px minmax(0,1fr)}.pt-studio-preview{display:none}}
@media (max-width:760px){.pt-studio{grid-template-columns:1fr}.pt-studio-list{max-height:220px}}
`;

export default function PagesPrototype({ variant, me, setToast }) {
  const pages = useApi('/api/marketing/pages', { every: 0 });
  const report = useApi('/api/marketing?period=30d', { every: 0 });
  useEffect(() => {
    const style = document.createElement('style'); style.textContent = CSS; document.head.appendChild(style);
    return () => style.remove();
  }, []);
  if (!isAdmin(me)) return html`<${Empty}>Só admin vê o ambiente de páginas.</${Empty}>`;
  const list = pages.data ? pages.data.pages : [];
  const props = { pages: list, report: report.data, setToast };
  return html`<div class="pt-root">
    ${variant === 'A' ? html`<${VariantA} ...${props}/>` : variant === 'B' ? html`<${VariantB} ...${props}/>` : html`<${VariantC} ...${props}/>`}
    <${Switcher} current=${variant}/>
  </div>`;
}
