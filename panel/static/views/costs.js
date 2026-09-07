import { html, useApi, fmt, Tile, Card, ErrorBox, BarChart } from '../lib.js';

export default function Costs({ period, config }) {
  const usage = useApi(`/api/usage?period=${period}`, { every: 120000 });
  const metrics = useApi(`/api/metrics?period=${period}`, { every: 60000 }).data;
  const u = usage.data;
  const rate = (config && config.hourly_rate_brl) || 0;
  const total = u ? u.input + u.output + u.reasoning : 0;
  const maxTokens = u ? Math.max(1, ...u.models.map((m) => m.tokens)) : 1;

  return html`
    <${ErrorBox} error=${usage.error}/>
    <div class="grid c3">
      <${Tile} dark label="Custo no período" value=${u ? (u.unpriced && !u.usd ? 'sem preço' : fmt.brl(u.brl)) : '…'} sub=${u && metrics ? `${metrics.total ? fmt.brl(u.brl / metrics.total) : fmt.brl(0)} por atendimento · ${fmt.usd(u.usd)} · câmbio ${u.usd_brl.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : ''}/>
      <${Tile} label="Tokens processados" value=${u ? fmt.tokens(total) : '…'} sub=${u ? `${fmt.tokens(u.input)} entrada · ${fmt.tokens(u.output)} saída · ${fmt.tokens(u.cache_read)} em cache` : ''}/>
      <${Tile} label="Tempo economizado" value=${metrics ? fmt.duration(metrics.minutes_saved) : '…'} sub=${metrics ? `${fmt.brl((metrics.minutes_saved / 60) * rate)} em hora de atendente` : ''}/>
    </div>

    <div class="grid start" style="grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr)">
      <${Card} title="Custo por dia" sub="Tokens de entrada, saída e cache vezes a tabela de preços. Modelo incluso na assinatura entra como custo equivalente.">
        ${u ? html`<${BarChart} series=${u.series.map((d) => ({ label: d.label, a: d.brl, tokens: d.tokens }))} colorA="#0b0d0c" gutter=64 format=${(v) => fmt.brl(v)} tip=${(s) => `${fmt.brl(s.a)} · ${fmt.tokens(s.tokens)} tokens`}/>` : null}
      </${Card}>
      <${Card} title="Por modelo">
        ${u && u.models.length === 0 ? html`<div class="empty">Nenhuma chamada de modelo no período.</div>` : null}
        <div class="row-list">${u ? u.models.map((m) => html`<div key=${m.model} style="display:flex;flex-direction:column;gap:8px;padding:12px 0">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
            <div style="display:flex;flex-direction:column;gap:1px;min-width:0"><span class="mono" style="font-size:14px;font-weight:600">${m.model}</span>
              <span style="font-size:12px;color:var(--muted)">${m.provider}${m.included ? ' · incluso na assinatura' : ''}</span></div>
            <span style="font-size:14px;font-weight:700;white-space:nowrap">${m.priced ? fmt.brl(m.usd * u.usd_brl) : 'sem preço'}</span>
          </div>
          <div style="height:8px;border-radius:4px;background:var(--soft-2);overflow:hidden"><div style=${`height:100%;border-radius:4px;background:${m.included ? 'var(--ink)' : 'var(--orange)'};width:${Math.round((m.tokens / maxTokens) * 100)}%`}></div></div>
          <span style="font-size:12px;color:var(--muted)">${fmt.int(m.calls)} chamadas · ${fmt.tokens(m.input)} entrada · ${fmt.tokens(m.output)} saída${m.cache_read ? ` · ${fmt.tokens(m.cache_read)} cache` : ''}${m.reasoning ? ` · ${fmt.tokens(m.reasoning)} raciocínio` : ''}</span>
        </div>`) : null}</div>
        ${u && u.unpriced ? html`<div class="banner warn"><span class="dot warn"></span><span class="grow">Há modelo sem preço em <span class="code">panel/pricing.json</span>. Preencha entrada, saída e cache por milhão de tokens.</span></div>` : null}
        ${u && u.subscription_brl_month ? html`<span class="card-sub">Assinatura do Codex: ${fmt.brl(u.subscription_brl_month)} por mês, fora deste cálculo.</span>` : null}
      </${Card}>
    </div>`;
}
