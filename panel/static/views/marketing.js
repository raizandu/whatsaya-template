// Marketing: o funil das landing pages cruzado com quem de fato chegou no
// WhatsApp. Lê só GET /api/marketing (features.marketing). Sessão é aba do
// navegador; "chegou" é a primeira mensagem viva do contato com o id da LP ou
// com origem nativa de anúncio (Click-to-WhatsApp).
import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, Tile, Card, ErrorBox, Empty, BarChart, Menu, dateTime, isAdmin } from '../lib.js';
import Pages from './marketing-pages.js';

const PERIOD_LABEL = { hoje: 'hoje', '7d': 'nos últimos 7 dias', '30d': 'nos últimos 30 dias' };
const STEP_LABEL = { view: 'Viram', start: 'Começaram', complete: 'Terminaram', whatsapp_click: 'Clicaram no WhatsApp', arrived: 'Chegaram no WhatsApp' };

const dayLabel = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

function originLabel(origin) {
  if (origin.medium === 'nativa') return html`<span>${origin.source}</span><span class="tag">anúncio nativo</span>`;
  const parts = [origin.source, origin.medium, origin.campaign].filter(Boolean);
  return html`<span>${parts.join(' · ')}</span>`;
}

const SOURCES = [['all', 'Tudo'], ['lp', 'LP'], ['meta', 'Meta'], ['whatsapp', 'WhatsApp']];
const SOURCE_HINT = {
  all: 'Todas as origens juntas.',
  lp: 'Quem passou pela landing page: sessões, cliques e leads com o id da LP.',
  meta: 'Anúncio nativo Click-to-WhatsApp e sessões da LP vindas de Instagram ou Facebook.',
  whatsapp: 'Quem chegou direto no WhatsApp, sem LP: link, busca e anúncio.',
};
const SOURCE_KEY = 'mk_source';
// Status do lead da LP: quem terminou o quiz e o que aconteceu depois.
const LEAD_STATUS = {
  aguardando: ['Aguardando', 'warn'], na_fila: ['Na fila da AYA', 'warn'], aya_chamou: ['AYA chamou', 'ok'],
  chegou: ['Chegou no WhatsApp', 'ok'], bloqueado: ['Bloqueado', 'bad'], falhou: ['Falhou', 'bad'],
};
const phoneLabel = (digits) => digits && digits.length === 11 ? `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}` : digits || '';

// Quem terminou o quiz: nome, WhatsApp e respostas, com o que a AYA fez com isso.
function QuizLeads({ period, go, setToast }) {
  const leads = useApi(`/api/marketing/leads?period=${period}`, { every: 60000 });
  const l = leads.data;
  const contact = async (lead) => {
    try {
      await post('/api/actions/marketing/lead-contact', { session_id: lead.session_id });
      setToast(`AYA chamou ${lead.name}`); leads.reload();
    } catch (err) { setToast(`Não consegui: ${err.message}`); }
  };
  const menu = (lead) => [
    { label: 'Ver conversa', icon: 'comment-alt', onClick: () => go(`lead/${encodeURIComponent(lead.chat_id)}`) },
    { label: 'Abrir no WhatsApp', icon: 'paper-plane', href: `https://wa.me/55${lead.phone}` },
    ...(['aguardando', 'na_fila', 'falhou'].includes(lead.status) ? ['separator', { label: 'AYA chama agora', icon: 'bolt', onClick: () => contact(lead) }] : []),
  ];
  return html`<${Card} title="Quem terminou o quiz" sub=${l ? (l.outreach_enabled ? `A AYA chama sozinha quem não escreve em ${l.delay_min} min.` : 'Contato automático desligado: chame pelo menu.') : 'carregando'}>
    <${ErrorBox} error=${leads.error}/>
    ${l && l.leads.length === 0 ? html`<${Empty}>Ninguém terminou o quiz no período.</${Empty}>` : null}
    <div class="row-list">${l ? l.leads.map((lead) => { const [label, tone] = LEAD_STATUS[lead.status] || [lead.status, 'warn']; return html`<div class="item mk-lead" key=${lead.session_id}>
      <span class="avatar">${fmt.initials(lead.name)}</span>
      <div class="grow">
        <span class="name">${lead.name} <span class="mk-lead-phone">${phoneLabel(lead.phone)}</span></span>
        <span class="meta">${[lead.answers.niche, lead.answers.negocio].filter(Boolean).join(' · ') || lead.lp}${lead.answers.problema ? ` · ${lead.answers.problema}` : ''}</span>
      </div>
      <span class=${'status-pill ' + tone}>${label}</span>
      <span class="when">${dateTime(lead.completed_at || lead.clicked_at, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
      <${Menu} label=${`Ações para ${lead.name}`} size="sm" items=${menu(lead)}/>
    </div>`; }) : null}</div>
  </${Card}>`;
}

export default function Marketing({ period, config, me, go, setToast, subview }) {
  // Hooks antes de qualquer retorno: a sub-rota troca sem remontar o componente.
  const [source, setSource] = useState(() => { try { return localStorage.getItem(SOURCE_KEY) || 'all'; } catch { return 'all'; } });
  const chooseSource = (next) => { setSource(next); try { localStorage.setItem(SOURCE_KEY, next); } catch { /* sem storage */ } };
  const report = useApi(`/api/marketing?period=${period}&source=${source}`, { every: 60000, deps: [source] });
  if (subview === 'paginas') {
    if (!isAdmin(me)) return html`<${Empty}>Só admin vê as páginas de nicho.</${Empty}>`;
    return html`<${Pages} setToast=${setToast} back=${() => go('marketing')}/>`;
  }
  const r = report.data;
  const t = r ? r.totals : null;
  const periodLabel = PERIOD_LABEL[period] || PERIOD_LABEL['7d'];
  const stages = (config && config.pipeline && config.pipeline.stages) || [];
  const phoneOf = (chatId) => String(chatId || '').split('@')[0].replace(/\D/g, '');
  const copyNumber = async (chatId) => {
    try { await navigator.clipboard.writeText(phoneOf(chatId)); setToast && setToast('Número copiado'); }
    catch { setToast && setToast('Não consegui copiar o número'); }
  };
  const leadMenu = (a) => [
    { label: 'Ver conversa', icon: 'comment-alt', onClick: () => go(`lead/${encodeURIComponent(a.chat_id)}`) },
    { label: 'Abrir no WhatsApp', icon: 'paper-plane', href: `https://wa.me/${phoneOf(a.chat_id)}` },
    { label: 'Copiar número', icon: 'copy', onClick: () => copyNumber(a.chat_id) },
  ];
  const stageLabel = (id) => (stages.find((s) => s.id === id) || {}).label || id || 'sem etapa';

  return html`
    <${ErrorBox} error=${report.error}/>
    <div class="mk-filter">
      <div class="segment" role="tablist" aria-label="Origem">${SOURCES.map(([id, label]) => html`<button key=${id} type="button" role="tab" class=${id === source ? 'active' : ''} aria-selected=${id === source} onClick=${() => chooseSource(id)}>${label}</button>`)}</div>
      <span class="mk-filter-hint">${SOURCE_HINT[source]}</span>
      ${isAdmin(me) ? html`<button type="button" class="btn sm mk-filter-pages" onClick=${() => go('marketing/paginas')}>Páginas de nicho <i class="fi fi-rr-arrow-right" aria-hidden="true"></i></button>` : null}
    </div>
    <div class="grid c4">
      <${Tile} dark label="Sessões na LP" value=${t ? fmt.int(t.sessions) : '…'} sub=${periodLabel}/>
      <${Tile} label="Clicaram no WhatsApp" value=${t ? fmt.int(t.clicks) : '…'} pct=${t ? fmt.pct(t.clicks, t.sessions) : ''} sub="das sessões"/>
      <${Tile} label="Chegaram no WhatsApp" green value=${t ? fmt.int(t.arrived) : '…'} sub=${t ? `${fmt.int(t.arrived_lp)} pela LP · ${fmt.int(t.arrived_native)} por anúncio nativo` : 'carregando'}/>
      <${Tile} label="No funil de leads" value=${t ? fmt.int(t.in_funnel) : '…'} sub=${t ? `${fmt.int(t.won)} ${t.won === 1 ? 'ganho' : 'ganhos'}` : 'carregando'}/>
    </div>

    <div class="grid wide-15 start">
      <div class="mk-col">
        <${Card} title="Funil da landing page" sub="Sessões únicas em cada passo. Chegou no WhatsApp é a primeira mensagem com o id da sessão.">
          ${r && r.lps.length === 0 ? html`<${Empty}>Nenhuma sessão na LP ${periodLabel}. O beacon da página grava aqui assim que alguém abrir.</${Empty}>` : null}
          ${r && r.lps.length ? html`<table class="plain">
            <thead><tr><th>Landing page</th>${Object.values(STEP_LABEL).map((label) => html`<th class="num" key=${label}>${label}</th>`)}</tr></thead>
            <tbody>${r.lps.map((lp) => html`<tr key=${lp.lp}>
              <td><b>${lp.lp}</b></td>
              ${Object.keys(STEP_LABEL).map((step) => html`<td class="num" key=${step}>${fmt.int(lp[step])}${step !== 'view' && lp.view ? html`<small class="mk-pct"> · ${fmt.pct(lp[step], lp.view)}</small>` : null}</td>`)}
            </tr>`)}</tbody>
          </table>` : null}
        </${Card}>

        <${Card} title="Por origem" sub="UTM da sessão da LP, ou o referral que o WhatsApp entrega quando o lead vem de anúncio.">
          ${r && r.origins.length === 0 ? html`<${Empty}>Nenhuma origem registrada ${periodLabel}.</${Empty}>` : null}
          ${r && r.origins.length ? html`<table class="plain">
            <thead><tr><th>Origem</th><th class="num">Sessões</th><th class="num">Cliques</th><th class="num">Chegaram</th><th class="num">No funil</th><th class="num">Ganhos</th></tr></thead>
            <tbody>${r.origins.map((o) => html`<tr key=${`${o.source}|${o.medium}|${o.campaign}`}>
              <td><div class="mk-origin">${originLabel(o)}</div></td>
              <td class="num">${o.medium === 'nativa' ? '—' : fmt.int(o.sessions)}</td>
              <td class="num">${o.medium === 'nativa' ? '—' : fmt.int(o.clicks)}</td>
              <td class="num"><b>${fmt.int(o.arrived)}</b></td>
              <td class="num">${fmt.int(o.in_funnel)}</td>
              <td class="num">${fmt.int(o.won)}</td>
            </tr>`)}</tbody>
          </table>` : null}
        </${Card}>
      </div>

      <div class="mk-col">
        <${Card} title="Movimento do período" sub=${period === 'hoje' ? 'Hoje' : period === '7d' ? 'Últimos 7 dias' : 'Últimos 30 dias'}
          action=${html`<div class="legend"><span><i class="swatch mk-swatch-green"></i>Chegaram no WhatsApp</span><span><i class="swatch mk-swatch-orange"></i>Clicaram na LP</span></div>`}>
          ${r ? html`<${BarChart} series=${r.days.map((d) => ({ label: dayLabel(d.date), a: d.arrived, b: d.clicks }))} tip=${(s) => `${s.a} chegaram · ${s.b} clicaram`}/>` : null}
        </${Card}>

        ${isAdmin(me) ? html`<${QuizLeads} period=${period} go=${go} setToast=${setToast}/>` : null}

        <${Card} title="Leads com origem" sub="Quem chegou no período e de onde veio.">
          ${r && r.arrivals.length === 0 ? html`<${Empty}>Nenhum lead com origem ${periodLabel}.</${Empty}>` : null}
          <div class="row-list">${r ? r.arrivals.slice(0, 30).map((a) => html`<div class="item mk-lead" key=${a.chat_id}>
            <span class="avatar">${fmt.initials(a.name || a.chat_id)}</span>
            <div class="grow">
              <span class="name">${a.name || a.chat_id.split('@')[0]}</span>
              <span class="meta">${a.kind === 'lp' ? `LP · ${[a.source, a.medium].filter(Boolean).join(' / ')}` : `anúncio · ${a.source}`} · ${stageLabel(a.stage)}</span>
            </div>
            <span class="when">${dateTime(a.arrived_at, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
            <${Menu} label=${`Ações para ${a.name || a.chat_id}`} size="sm" items=${leadMenu(a)}/>
          </div>`) : null}</div>
        </${Card}>
      </div>
    </div>`;
}
