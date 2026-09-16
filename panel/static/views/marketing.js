// Marketing: o funil das landing pages cruzado com quem de fato chegou no
// WhatsApp. Lê só GET /api/marketing (features.marketing). Sessão é aba do
// navegador; "chegou" é a primeira mensagem viva do contato com o id da LP ou
// com origem nativa de anúncio (Click-to-WhatsApp).
import { html, useApi, fmt, Tile, Card, ErrorBox, Empty, BarChart, dateTime } from '../lib.js';

const PERIOD_LABEL = { hoje: 'hoje', '7d': 'nos últimos 7 dias', '30d': 'nos últimos 30 dias' };
const STEP_LABEL = { view: 'Viram', start: 'Começaram', complete: 'Terminaram', whatsapp_click: 'Clicaram no WhatsApp', arrived: 'Chegaram no WhatsApp' };

const dayLabel = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

function originLabel(origin) {
  if (origin.medium === 'nativa') return html`<span>${origin.source}</span><span class="tag">anúncio nativo</span>`;
  const parts = [origin.source, origin.medium, origin.campaign].filter(Boolean);
  return html`<span>${parts.join(' · ')}</span>`;
}

export default function Marketing({ period, config, go }) {
  const report = useApi(`/api/marketing?period=${period}`, { every: 60000 });
  const r = report.data;
  const t = r ? r.totals : null;
  const periodLabel = PERIOD_LABEL[period] || PERIOD_LABEL['7d'];
  const stages = (config && config.pipeline && config.pipeline.stages) || [];
  const stageLabel = (id) => (stages.find((s) => s.id === id) || {}).label || id || 'sem etapa';

  return html`
    <${ErrorBox} error=${report.error}/>
    <div class="grid c4">
      <${Tile} dark label="Sessões na LP" value=${t ? fmt.int(t.sessions) : '…'} sub=${periodLabel}/>
      <${Tile} label="Clicaram no WhatsApp" value=${t ? fmt.int(t.clicks) : '…'} pct=${t ? fmt.pct(t.clicks, t.sessions) : ''} sub="das sessões"/>
      <${Tile} label="Chegaram no WhatsApp" green value=${t ? fmt.int(t.arrived) : '…'} sub=${t ? `${fmt.int(t.arrived_lp)} pela LP · ${fmt.int(t.arrived_native)} por anúncio nativo` : 'carregando'}/>
      <${Tile} label="No funil de leads" value=${t ? fmt.int(t.in_funnel) : '…'} sub=${t ? `${fmt.int(t.won)} ${t.won === 1 ? 'ganho' : 'ganhos'}` : 'carregando'}/>
    </div>

    <div class="grid wide-15 start">
      <div style="display:flex;flex-direction:column;gap:16px">
        <${Card} title="Funil da landing page" sub="Sessões únicas em cada passo. Chegou no WhatsApp é a primeira mensagem com o id da sessão.">
          ${r && r.lps.length === 0 ? html`<${Empty}>Nenhuma sessão na LP ${periodLabel}. O beacon da página grava aqui assim que alguém abrir.</${Empty}>` : null}
          ${r && r.lps.length ? html`<table class="plain">
            <thead><tr><th>Landing page</th>${Object.values(STEP_LABEL).map((label) => html`<th class="num" key=${label}>${label}</th>`)}</tr></thead>
            <tbody>${r.lps.map((lp) => html`<tr key=${lp.lp}>
              <td><b>${lp.lp}</b></td>
              ${Object.keys(STEP_LABEL).map((step) => html`<td class="num" key=${step}>${fmt.int(lp[step])}${step !== 'view' && lp.view ? html`<small style="color:var(--muted-2)"> · ${fmt.pct(lp[step], lp.view)}</small>` : null}</td>`)}
            </tr>`)}</tbody>
          </table>` : null}
        </${Card}>

        <${Card} title="Por origem" sub="UTM da sessão da LP, ou o referral que o WhatsApp entrega quando o lead vem de anúncio.">
          ${r && r.origins.length === 0 ? html`<${Empty}>Nenhuma origem registrada ${periodLabel}.</${Empty}>` : null}
          ${r && r.origins.length ? html`<table class="plain">
            <thead><tr><th>Origem</th><th class="num">Sessões</th><th class="num">Cliques</th><th class="num">Chegaram</th><th class="num">No funil</th><th class="num">Ganhos</th></tr></thead>
            <tbody>${r.origins.map((o) => html`<tr key=${`${o.source}|${o.medium}|${o.campaign}`}>
              <td><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${originLabel(o)}</div></td>
              <td class="num">${o.medium === 'nativa' ? '—' : fmt.int(o.sessions)}</td>
              <td class="num">${o.medium === 'nativa' ? '—' : fmt.int(o.clicks)}</td>
              <td class="num"><b>${fmt.int(o.arrived)}</b></td>
              <td class="num">${fmt.int(o.in_funnel)}</td>
              <td class="num">${fmt.int(o.won)}</td>
            </tr>`)}</tbody>
          </table>` : null}
        </${Card}>
      </div>

      <div style="display:flex;flex-direction:column;gap:16px">
        <${Card} title="Movimento do período" sub=${period === 'hoje' ? 'Hoje' : period === '7d' ? 'Últimos 7 dias' : 'Últimos 30 dias'}
          action=${html`<div class="legend"><span><i class="swatch" style="background:var(--green)"></i>Chegaram no WhatsApp</span><span><i class="swatch" style="background:var(--orange)"></i>Clicaram na LP</span></div>`}>
          ${r ? html`<${BarChart} series=${r.days.map((d) => ({ label: dayLabel(d.date), a: d.arrived, b: d.clicks }))} tip=${(s) => `${s.a} chegaram · ${s.b} clicaram`}/>` : null}
        </${Card}>

        <${Card} title="Leads com origem" sub="Quem chegou no período e de onde veio.">
          ${r && r.arrivals.length === 0 ? html`<${Empty}>Nenhum lead com origem ${periodLabel}.</${Empty}>` : null}
          <div class="row-list">${r ? r.arrivals.slice(0, 30).map((a) => html`<div class="item" key=${a.chat_id} style="padding:10px 0">
            <span class="avatar">${fmt.initials(a.name || a.chat_id)}</span>
            <div class="grow">
              <span class="name" style="font-size:13px">${a.name || a.chat_id.split('@')[0]}</span>
              <span class="meta">${a.kind === 'lp' ? `LP · ${[a.source, a.medium].filter(Boolean).join(' / ')}` : `anúncio · ${a.source}`} · ${stageLabel(a.stage)}</span>
            </div>
            <span class="when">${dateTime(a.arrived_at, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
            <button type="button" class="btn sm" onClick=${() => go(`lead/${encodeURIComponent(a.chat_id)}`)}>Ver lead</button>
          </div>`) : null}</div>
        </${Card}>
      </div>
    </div>`;
}
