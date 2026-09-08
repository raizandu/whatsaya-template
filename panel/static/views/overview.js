import { html, useApi, fmt, Tile, Card, ErrorBox, Empty, BarChart } from '../lib.js';

export default function Overview({ period, config, go }) {
  const metrics = useApi(`/api/metrics?period=${period}`, { every: 60000 });
  const leads = useApi('/api/leads', { every: 60000 });
  const followups = useApi(`/api/followups?period=${period}`, { every: 60000 });
  const blocked = useApi('/api/blocked', { every: 120000 });
  const m = metrics.data, l = leads.data, f = followups.data, b = blocked.data;
  const rate = (config && config.hourly_rate_brl) || 0;
  const maxCount = l ? Math.max(1, ...l.stages.map((s) => s.cards.length)) : 1;

  return html`
    <${ErrorBox} error=${metrics.error}/>
    <div class="grid c3">
      <${Tile} label="Atendimentos" value=${m ? fmt.int(m.total) : '…'} sub="conversas com lead no período"/>
      <${Tile} label="Resolvidos pela IA" green value=${m ? fmt.int(m.ai_resolved) : '…'} pct=${m ? fmt.pct(m.ai_resolved, m.total) : ''} sub=${m ? `${fmt.int(m.human)} passaram para atendimento humano` : ''}/>
      <${Tile} label="Tempo economizado" value=${m ? fmt.duration(m.minutes_saved) : '…'} sub=${m ? `≈ ${config ? config.minutes_per_resolved : 6} min por atendimento · ${fmt.brl((m.minutes_saved / 60) * rate)}` : ''}/>
    </div>

    <div class="grid wide">
      <${Card} title="Atendimentos por dia" sub=${period === 'hoje' ? 'Hoje' : period === '7d' ? 'Últimos 7 dias' : 'Últimos 30 dias'}
        action=${html`<div class="legend"><span><i class="swatch" style="background:var(--green)"></i>IA resolveu</span><span><i class="swatch" style="background:var(--orange)"></i>Humano assumiu</span></div>`}>
        ${m ? html`<${BarChart} series=${m.series.map((d) => ({ label: d.label, a: d.ai, b: d.human }))} tip=${(s) => `${s.a} pela IA · ${s.b} humano`}/>` : null}
      </${Card}>
      <${Card} title="Funil agora" action=${html`<button class="btn sm" onClick=${() => go('kanban')}>Abrir kanban</button>`}>
        ${l ? l.stages.map((s) => html`<div class="bar-row" key=${s.id}>
          <span class="lbl">${s.label}</span>
          <div class="track"><div class="fill" style=${`width:${Math.round((s.cards.length / maxCount) * 100)}%`}></div></div>
          <span class="n">${s.cards.length}</span>
        </div>`) : null}
        <div class="item" style="background:var(--soft);border-radius:12px;padding:10px 12px;margin-top:4px">
          <div class="grow"><span class="name" style="font-size:13px">Follow-ups</span>
            <span class="meta">${f ? `${f.queue.length} na fila · ${f.stats.sent} enviados · ${f.stats.replied} responderam` : '…'}</span></div>
          <button class="btn sm" style="background:#fff;border:1px solid var(--line-2)" onClick=${() => go('followups')}>Ver fila</button>
        </div>
        ${l ? html`<div style="display:flex;gap:8px"><span class="chip mint">${l.terminal.won} ganhos</span><span class="chip">${l.terminal.lost} perdidos</span></div>` : null}
      </${Card}>
    </div>

    <div class="grid wide start">
      <${Card} title="Precisam de você" sub="Handoffs que a AYA passou e ainda não tiveram resposta humana">
        ${m && m.handoffs_pending.length === 0 ? html`<${Empty}>Nenhum handoff aberto. A AYA está dando conta.</${Empty}>` : null}
        ${m ? m.handoffs_pending.map((h) => html`<button class="item handoff-link" key=${h.chat_id + h.at} onClick=${() => go(`lead/${encodeURIComponent(h.chat_id)}`)}>
          <span class="avatar hot">${fmt.initials(h.name)}</span>
          <div class="grow"><span class="name">${h.name}</span><span class="meta">${h.reason}</span></div>
          <span class="when" style="color:var(--orange);font-weight:600">${h.at ? new Date(h.at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''}</span>
        </button>`) : null}
        ${m && m.unanswered.length ? html`<div class="banner bad"><span class="dot bad"></span><span class="grow"><b>${m.unanswered.length} mensagem(ns) sem resposta</b> passaram do limite do watchdog hoje.</span></div>` : null}
      </${Card}>
      <${Card} title="Bloqueados" action=${html`<button class="btn sm" onClick=${() => go('contacts')}>Gerenciar</button>`}>
        <span class="card-sub" style="margin-top:-8px">${b ? `${b.blocked.length} contatos ignorados na entrada, sem visto nem resposta` : '…'}</span>
        <div class="row-list">${b ? b.blocked.slice(0, 4).map((c) => html`<div class="item" key=${c.chat_id} style="padding:8px 0">
          <div class="grow"><span class="name" style="font-size:13px">${c.name}</span><span class="meta">${c.phone}</span></div>
          <span class="when">${c.reason}</span>
        </div>`) : null}</div>
      </${Card}>
    </div>`;
}
