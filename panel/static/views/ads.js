import { html, useApi, fmt, Card, ErrorBox, Empty, Icon } from '../lib.js';
import { useState } from 'preact/hooks';

const dateTime = (value) => value
  ? new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '—';

export default function AdsReport({ go }) {
  const resource = useApi('/api/ads-report', { every: 30000 });
  const [search, setSearch] = useState('');
  const data = resource.data;
  const summary = data ? data.summary : null;
  const byAd = data ? data.by_ad : [];
  const byChannel = data ? data.by_channel : [];
  const leads = data ? data.leads : [];

  const filteredLeads = leads.filter((lead) => {
    if (!search.trim()) return true;
    const term = search.toLowerCase();
    return (
      (lead.name || '').toLowerCase().includes(term)
      || (lead.phone || '').toLowerCase().includes(term)
      || (lead.ad_title || '').toLowerCase().includes(term)
      || (lead.channel || '').toLowerCase().includes(term)
    );
  });

  return html`<div class="overview-page">
    <${ErrorBox} error=${resource.error}/>

    <section class="overview-action" aria-label="Resumo do Tráfego Pago">
      <div class="overview-action-summary">
        <span class="kpi-eyebrow">Tráfego Meta Ads</span>
        <strong>${summary ? fmt.int(summary.total_ad_leads) : '…'}</strong>
        <p>leads originados de anúncios Click-to-WhatsApp</p>
      </div>

      <div class="overview-action-impact">
        <span class="kpi-eyebrow">Atribuição de Vendas</span>
        <div class="overview-impact-list">
          <div><b>${summary ? fmt.int(summary.total_booked) : '…'}</b><span>sessões agendadas</span></div>
          <div><b>${summary ? `${summary.conversion_rate_pct}%` : '…'}</b><span>taxa de conversão</span></div>
          <div><b>${summary ? fmt.brl(summary.total_revenue_brl) : '…'}</b><span>receita gerada estimada</span></div>
        </div>
      </div>

      <div class="overview-next">
        <span class="kpi-eyebrow">Ticket da Sessão</span>
        <b>${summary ? fmt.brl(summary.session_ticket_brl) : 'R$ 247,00'}</b>
        <small>Atendimento individual de 1h via Google Meet com Dr. Rodrigo Melo</small>
        <button type="button" onClick=${() => go('agenda')}>Ver horários na agenda <span aria-hidden="true">→</span></button>
      </div>
    </section>

    <section class="overview-metrics" aria-label="Canais do Tráfego">
      ${byChannel.map((ch) => html`<div class="overview-metric" key=${ch.channel}>
        <span>${ch.channel}</span>
        <b>${fmt.int(ch.leads_count)} leads</b>
        <small>${fmt.int(ch.booked_count)} agendamentos (${ch.conversion_rate_pct}% conv.) · ${fmt.brl(ch.revenue_brl)}</small>
      </div>`)}
    </section>

    <${Card} title="Desempenho por Anúncio / Criativo" sub="Métricas de conversão agrupadas por criativo do Meta Ads">
      ${byAd.length === 0 ? html`<${Empty}>Nenhum lead com criativo identificado ainda.</${Empty}>` : html`
        <div class="table-wrap" style="overflow-x:auto">
          <table class="contacts-table" style="width:100%;text-align:left">
            <thead>
              <tr>
                <th style="padding:10px">Criativo / Anúncio</th>
                <th style="padding:10px">Canal</th>
                <th style="padding:10px;text-align:center">Leads</th>
                <th style="padding:10px;text-align:center">Agendados</th>
                <th style="padding:10px;text-align:center">Conversão</th>
                <th style="padding:10px;text-align:right">Receita Gerada</th>
              </tr>
            </thead>
            <tbody>
              ${byAd.map((ad, idx) => html`<tr key=${idx} style="border-top:1px solid var(--border)">
                <td style="padding:12px 10px">
                  <b>${ad.ad_title}</b>
                  ${ad.ad_id && ad.ad_id !== '—' ? html`<div style="font-size:11px;color:var(--text-muted)">ID: ${ad.ad_id}</div>` : null}
                </td>
                <td style="padding:12px 10px"><span class="tag ${ad.channel.includes('Instagram') ? 'purple' : 'blue'}">${ad.channel}</span></td>
                <td style="padding:12px 10px;text-align:center"><b>${fmt.int(ad.leads_count)}</b></td>
                <td style="padding:12px 10px;text-align:center"><b style="color:var(--green)">${fmt.int(ad.booked_count)}</b></td>
                <td style="padding:12px 10px;text-align:center"><span class="chip">${ad.conversion_rate_pct}%</span></td>
                <td style="padding:12px 10px;text-align:right"><b style="color:var(--green)">${fmt.brl(ad.revenue_brl)}</b></td>
              </tr>`)}
            </tbody>
          </table>
        </div>
      `}
    </${Card}>

    <${Card}
      title="Leads de Anúncios Recentes"
      sub=${`${filteredLeads.length} leads encontrados`}
      action=${html`<label class="conversation-search" style="margin:0"><${Icon.search}/><input type="search" value=${search} onInput=${(e) => setSearch(e.target.value)} placeholder="Buscar lead ou anúncio" aria-label="Buscar lead"/></label>`}>
      ${filteredLeads.length === 0 ? html`<${Empty}>Nenhum lead encontrado.</${Empty}>` : html`
        <div class="table-wrap" style="overflow-x:auto">
          <table class="contacts-table" style="width:100%;text-align:left">
            <thead>
              <tr>
                <th style="padding:10px">Lead</th>
                <th style="padding:10px">Telefone</th>
                <th style="padding:10px">Anúncio</th>
                <th style="padding:10px">Canal</th>
                <th style="padding:10px">Primeiro Contato</th>
                <th style="padding:10px;text-align:center">Status</th>
                <th style="padding:10px;text-align:right">Ação</th>
              </tr>
            </thead>
            <tbody>
              ${filteredLeads.map((lead) => html`<tr key=${lead.chat_id} style="border-top:1px solid var(--border)">
                <td style="padding:12px 10px"><b>${lead.name}</b></td>
                <td style="padding:12px 10px"><code>${lead.phone}</code></td>
                <td style="padding:12px 10px"><span>${lead.ad_title}</span></td>
                <td style="padding:12px 10px"><span class="tag sm">${lead.channel}</span></td>
                <td style="padding:12px 10px"><small>${dateTime(lead.created_at)}</small></td>
                <td style="padding:12px 10px;text-align:center">
                  ${lead.booked
                    ? html`<span class="tag mint">Sessão Agendada</span>`
                    : html`<span class="tag orange">Em atendimento</span>`}
                </td>
                <td style="padding:12px 10px;text-align:right">
                  <button type="button" class="btn sm" onClick=${() => go(`lead/${encodeURIComponent(lead.chat_id)}`)}>Ver conversa</button>
                </td>
              </tr>`)}
            </tbody>
          </table>
        </div>
      `}
    </${Card}>
  </div>`;
}
