import { html, useApi, fmt, Card, ErrorBox, Empty, BarChart } from '../lib.js';

const PERIOD_LABEL = { hoje: 'hoje', '7d': 'nos últimos 7 dias', '30d': 'nos últimos 30 dias' };

function waitSince(value) {
  const timestamp = Date.parse(value || '');
  if (!Number.isFinite(timestamp)) return '';
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return 'agora';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${String(minutes % 60).padStart(2, '0')} min`;
  return `${Math.floor(hours / 24)} d`;
}

function Metric({ label, value, detail }) {
  return html`<div class="overview-metric"><span>${label}</span><b>${value}</b><small>${detail}</small></div>`;
}

export default function Overview({ period, config, go }) {
  const metrics = useApi(`/api/metrics?period=${period}`, { every: 60000 });
  const leads = useApi('/api/leads', { every: 60000 });
  const followups = useApi(`/api/followups?period=${period}`, { every: 60000 });
  const blocked = useApi('/api/blocked', { every: 120000 });
  const m = metrics.data, l = leads.data, f = followups.data, b = blocked.data;
  const rate = (config && config.hourly_rate_brl) || 0;
  const assistantName = (config && config.assistant_name) || 'Atendimento';
  const pending = m ? m.handoffs_pending : [];
  const pendingTotal = m ? (m.handoffs_pending_total ?? pending.length) : null;
  const priority = pending[0] || null;
  const oldestWait = priority ? waitSince(priority.at) : '';
  const soonFollowups = f ? f.queue.filter((job) => job.soon && !job.paused).length : null;
  const autonomy = m ? fmt.pct(m.ai_resolved, m.total) : '…';
  const maxCount = l ? Math.max(1, ...l.stages.map((stage) => stage.cards.length)) : 1;
  const periodLabel = PERIOD_LABEL[period] || PERIOD_LABEL['7d'];
  const errors = [metrics.error, leads.error, followups.error, blocked.error].filter(Boolean);

  const openPriority = () => {
    if (priority) go(`lead/${encodeURIComponent(priority.chat_id)}`);
    else go('kanban');
  };

  return html`<div class="overview-page">
    ${errors.map((error) => html`<${ErrorBox} key=${error} error=${error}/> `)}

    <section class="overview-action" aria-label="Prioridade da operação" aria-busy=${!m || !f}>
      <div class="overview-action-summary">
        <span class="kpi-eyebrow">Gargalo agora</span>
        <strong>${pendingTotal === null ? '…' : fmt.int(pendingTotal)}</strong>
        <p>${pendingTotal === 1 ? 'conversa aguarda uma decisão humana' : 'conversas aguardam uma decisão humana'}</p>
      </div>

      <div class="overview-action-impact">
        <span class="kpi-eyebrow">Impacto se agir agora</span>
        <div class="overview-impact-list">
          <div><b>${pendingTotal === null ? '…' : fmt.int(pendingTotal)}</b><span>atendimentos voltam a andar</span></div>
          <div><b>${m ? fmt.int(m.unanswered.length) : '…'}</b><span>mensagens acima do limite hoje</span></div>
          <div><b>${oldestWait || (soonFollowups === null ? '…' : fmt.int(soonFollowups))}</b><span>${oldestWait ? 'é a maior espera da fila' : 'follow-ups nas próximas 4 h'}</span></div>
        </div>
      </div>

      <div class="overview-next">
        <span class="kpi-eyebrow">Próxima melhor ação</span>
        <b>${priority ? `Responder ${priority.name}` : m ? 'Fila de handoffs em dia' : 'Carregando prioridade'}</b>
        <small>${priority ? `${priority.reason || 'Atendimento humano solicitado'}${oldestWait ? ` · esperando ${oldestWait}` : ''}` : m ? 'Acompanhe os leads que estão avançando no pipeline.' : `Aguarde enquanto ${assistantName} organiza a operação.`}</small>
        <button type="button" onClick=${openPriority} disabled=${!m}>${priority ? 'Resolver fila priorizada' : 'Ver pipeline'} <span aria-hidden="true">→</span></button>
      </div>
    </section>

    <section class="overview-metrics" aria-label="Indicadores do período">
      <${Metric} label="Atendimentos" value=${m ? fmt.int(m.total) : '…'} detail=${periodLabel}/>
      <${Metric} label=${`Autonomia de ${assistantName}`} value=${autonomy} detail=${m ? `${fmt.int(m.ai_resolved)} resolvidos sem intervenção` : 'carregando'}/>
      <${Metric} label="Tempo recuperado" value=${m ? fmt.duration(m.minutes_saved) : '…'} detail=${m ? `${fmt.brl((m.minutes_saved / 60) * rate)} em operação` : 'carregando'}/>
      <${Metric} label="Follow-ups" value=${f ? fmt.int(f.queue.length) : '…'} detail=${f && f.stats.sent ? `${fmt.pct(f.stats.replied, f.stats.sent)} trouxeram resposta` : 'nenhum envio no período'}/>
    </section>

    <section class="overview-primary-grid">
      <article class="overview-panel overview-queue">
        <header><div><span class="kpi-eyebrow">Fila priorizada</span><h2>Quem precisa de você</h2></div>${pending.length ? html`<button type="button" class="text-action" onClick=${() => go('kanban')}>Ver pipeline</button>` : null}</header>
        ${m && pending.length === 0 ? html`<${Empty}>Nenhum handoff aberto. ${assistantName} está dando conta.</${Empty}>` : null}
        <div class="overview-list">${pending.slice(0, 4).map((handoff) => html`<button type="button" class="overview-lead" key=${handoff.chat_id + handoff.at} onClick=${() => go(`lead/${encodeURIComponent(handoff.chat_id)}`)}>
          <span class="avatar">${fmt.initials(handoff.name)}</span>
          <span class="overview-lead-copy"><b>${handoff.name}</b><small>${handoff.reason || 'Atendimento humano solicitado'}</small></span>
          <span class="overview-lead-meta"><em>Handoff</em><small>${waitSince(handoff.at)}</small></span>
        </button>`)}</div>
        ${m && m.unanswered.length ? html`<div class="overview-warning"><span class="dot bad"></span><span><b>${m.unanswered.length} ${m.unanswered.length === 1 ? 'mensagem passou' : 'mensagens passaram'} do limite</b><small>Revise a fila para evitar perda de contexto.</small></span></div>` : null}
      </article>

      <article class="overview-panel overview-tasks">
        <header><div><span class="kpi-eyebrow">Próximas ações</span><h2>Depois da fila</h2></div></header>
        <button type="button" onClick=${() => go('followups')}><b>${soonFollowups === null ? '…' : fmt.int(soonFollowups)}</b><span>Follow-ups próximos<small>previstos para as próximas 4 h</small></span><i aria-hidden="true">→</i></button>
        <button type="button" onClick=${() => go('kanban')}><b>${l ? fmt.int(l.total) : '…'}</b><span>Leads ativos no pipeline<small>${l ? `${l.terminal.won} ganhos · ${l.terminal.lost} encerrados` : 'carregando'}</small></span><i aria-hidden="true">→</i></button>
        <button type="button" onClick=${() => go('contacts')}><b>${b ? fmt.int(b.blocked.length) : '…'}</b><span>Contatos bloqueados<small>ignorados sem visto nem resposta</small></span><i aria-hidden="true">→</i></button>
      </article>
    </section>

    <section class="overview-secondary-grid">
      <${Card} title="Movimento do período" sub=${period === 'hoje' ? 'Hoje' : period === '7d' ? 'Últimos 7 dias' : 'Últimos 30 dias'}
        action=${html`<div class="legend"><span><i class="swatch" style="background:var(--green)"></i>${assistantName} resolveu</span><span><i class="swatch" style="background:var(--orange)"></i>Humano assumiu</span></div>`}>
        ${m ? html`<${BarChart} series=${m.series.map((day) => ({ label: day.label, a: day.ai, b: day.human }))} tip=${(series) => `${series.a} por ${assistantName} · ${series.b} humano`}/>` : null}
      </${Card}>
      <${Card} title="Pipeline" action=${html`<button class="btn sm" onClick=${() => go('kanban')}>Abrir kanban</button>`}>
        ${l ? l.stages.map((stage) => html`<div class="bar-row" key=${stage.id}>
          <span class="lbl">${stage.label}</span>
          <div class="track"><div class="fill" style=${`width:${Math.round((stage.cards.length / maxCount) * 100)}%`}></div></div>
          <span class="n">${stage.cards.length}</span>
        </div>`) : null}
      </${Card}>
    </section>
  </div>`;
}
