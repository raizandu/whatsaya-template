import { html, useApi, post, fmt, ErrorBox, Empty, Icon } from '../lib.js';
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';

// Usado só até o /api/config responder na primeira carga.
const DEFAULT_STAGES = [
  { id: 'new', label: 'Novo' },
  { id: 'qualification', label: 'Qualificação' },
  { id: 'pricing', label: 'Preço' },
  { id: 'proposal', label: 'Proposta' },
  { id: 'payment', label: 'Pagamento' },
];

const MEETING_OUTCOMES = {
  attended: 'Comparecida',
  no_show: 'No Show',
  no_status: 'Sem status',
  rescheduled: 'Remarcada',
};

const dateTime = (value, options = {}) => value
  ? new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', ...options })
  : '—';

// Mesmo enum de panel/data.py (triage.stage).
const TRIAGE_STAGE_LABELS = {
  pessoal: 'Pessoal',
  lead_novo: 'Lead novo',
  lead_qualificado: 'Lead qualificado',
  proposta: 'Proposta',
  cliente: 'Cliente',
  fornecedor: 'Fornecedor',
  incerto: 'Incerto',
  spam: 'Spam',
};

const CONFIDENCE_LABELS = { alta: 'Alta', media: 'Média', baixa: 'Baixa' };
const triageConfidence = (value) => {
  if (typeof value === 'string') return CONFIDENCE_LABELS[value.trim().toLowerCase()] || value;
  if (typeof value !== 'number') return null;
  const pct = value <= 1 ? value * 100 : value;
  return `${Math.round(pct)}%`;
};

function ConversationMessage({ item, leadName, assistantName = 'AYA' }) {
  const label = item.owner === 'lead' ? leadName : item.owner === 'owner' ? 'Você' : assistantName;
  const count = item.bubbles.length;
  return html`<div class=${`conversation-row ${item.owner}${item.historical ? ' historical' : ''}`}>
    <div class="conversation-message">
      <div class="conversation-meta">
        <span>${label}</span>
        ${count > 1 ? html`<span>${count} bolhas</span>` : null}
        <time>${dateTime(item.at)}</time>
      </div>
      <div class="conversation-bubbles">
        ${item.bubbles.map((bubble) => html`<div class=${`conversation-bubble ${bubble.media_type ? 'media' : ''}`} key=${bubble.message_id}>
          ${/(audio|ptt)/i.test(bubble.media_type) ? html`<span class="audio-mark" aria-hidden="true">▶</span>` : null}
          <span>${bubble.body}</span>
        </div>`)}
      </div>
    </div>
  </div>`;
}

function FlowEvent({ item }) {
  const detail = item.event === 'followup'
    ? `${item.cadence || 'Follow-up'}${item.step ? ` · toque ${item.step}` : ''}${item.reason ? ` · ${item.reason}` : ''}`
    : item.reason;
  return html`<div class=${`flow-event ${item.event}${item.historical ? ' historical' : ''}`}>
    <span class="flow-dot"></span>
    <div><b>${item.label}</b>${detail ? html`<span>${detail}</span>` : null}</div>
    <time>${dateTime(item.at)}</time>
  </div>`;
}

function HistoricalDivider() {
  return html`<div class="conversation-historical-divider" key="historical-divider"><span>Histórico importado</span></div>`;
}

// Timeline com o divisor "Histórico importado" antes da primeira mensagem legada.
function timelineRows(items, leadName, assistantName) {
  let dividerShown = false;
  return items.flatMap((item, index) => {
    const rows = [];
    if (item.historical && !dividerShown) {
      dividerShown = true;
      rows.push(html`<${HistoricalDivider}/>`);
    }
    rows.push(item.type === 'message'
      ? html`<${ConversationMessage} key=${item.at + index} item=${item} leadName=${leadName} assistantName=${assistantName}/>`
      : html`<${FlowEvent} key=${item.at + index} item=${item}/>`);
    return rows;
  });
}

export default function Lead({ chatId, config, assistantName = 'AYA', setToast, go }) {
  const resource = useApi(`/api/lead/${encodeURIComponent(chatId)}`, { every: 30000 });
  const detail = resource.data;
  const stages = (config && config.pipeline && config.pipeline.stages) || DEFAULT_STAGES;
  const timelineRef = useRef(null);
  const [conversationQuery, setConversationQuery] = useState('');
  const attachTimeline = useCallback((node) => {
    timelineRef.current = node;
    if (node) {
      requestAnimationFrame(() => {
        if (node.isConnected) node.scrollTop = node.scrollHeight;
      });
    }
  }, [chatId]);

  useEffect(() => setConversationQuery(''), [chatId]);

  const updateStage = async (stage) => {
    try {
      await post('/api/actions/stage', { chat_id: chatId, stage });
      setToast(`Etapa alterada para ${(stages.find((s) => s.id === stage) || {}).label || stage}`);
      resource.reload();
    } catch (err) {
      setToast(`Não alterei a etapa: ${err.message}`);
    }
  };

  const toggleFollowup = async () => {
    const action = detail.lead.automation_enabled ? 'pause' : 'resume';
    try {
      await post('/api/actions/followup', { chat_id: chatId, action });
      setToast(action === 'pause' ? 'Follow-up pausado' : 'Follow-up retomado');
      resource.reload();
    } catch (err) {
      setToast(`Não alterei o follow-up: ${err.message}`);
    }
  };

  const handBack = async () => {
    try {
      await post('/api/actions/followup', { chat_id: chatId, action: 'handback' });
      setToast(`Conversa devolvida para ${assistantName}`);
      resource.reload();
    } catch (err) {
      setToast(`Não devolvi a conversa: ${err.message}`);
    }
  };

  const toggleSilence = async () => {
    const silenced = detail.silence && detail.silence.silenced;
    try {
      await post(silenced ? '/api/actions/unsilence' : '/api/actions/silence', silenced
        ? { chat_id: chatId }
        : { chat_id: chatId, minutes: 10 });
      setToast(silenced ? `${assistantName} reativada nesta conversa` : `${assistantName} silenciada por 10 minutos`);
      resource.reload();
    } catch (err) {
      setToast(`Não alterei o silêncio: ${err.message}`);
    }
  };

  const toggleAiAccess = async () => {
    const enabled = !(detail.ai && detail.ai.enabled);
    try {
      await post('/api/actions/ai-access', { chat_id: chatId, enabled });
      setToast(enabled ? 'IA liberada para este contato' : 'IA desligada para este contato');
      resource.reload();
    } catch (err) {
      setToast(`Não alterei o acesso da IA: ${err.message}`);
    }
  };

  const saveEstimatedValue = async (event) => {
    event.preventDefault();
    const value = event.currentTarget.elements.value_brl.value;
    try {
      await post('/api/actions/value', { chat_id: chatId, value_brl: value });
      setToast(value.trim() ? 'Valor estimado atualizado' : 'Valor estimado removido');
      resource.reload();
    } catch (err) {
      setToast(`Não alterei o valor: ${err.message}`);
    }
  };

  const updateMeetingOutcome = async (outcome) => {
    try {
      await post('/api/actions/meeting-outcome', {
        event_id: detail.meeting.event_id,
        start: detail.meeting.start,
        outcome,
      });
      setToast(`Reunião marcada como ${MEETING_OUTCOMES[outcome]}`);
      resource.reload();
    } catch (err) {
      setToast(`Não alterei o status: ${err.message}`);
    }
  };

  const normalizedQuery = conversationQuery.trim().toLocaleLowerCase('pt-BR');
  const visibleTimeline = detail && normalizedQuery
    ? detail.timeline.filter((item) => {
      const fields = item.type === 'message'
        ? item.bubbles.map((bubble) => bubble.body)
        : [item.label, item.reason, item.cadence];
      return fields.some((field) => String(field || '').toLocaleLowerCase('pt-BR').includes(normalizedQuery));
    })
    : detail ? detail.timeline : [];

  const scrollToLatest = () => {
    const timeline = timelineRef.current;
    if (timeline) timeline.scrollTo({ top: timeline.scrollHeight, behavior: 'smooth' });
  };

  const aiEnabled = !detail || !detail.ai || detail.ai.enabled;

  return html`<div class="lead-workspace">
    <${ErrorBox} error=${resource.error}/>
    ${detail ? html`
      <header class="lead-workspace-header">
        <div class="lead-header-identity">
          <button class="lead-back-button" onClick=${() => history.length > 1 ? history.back() : go('contacts')} aria-label="Voltar para contatos"><${Icon.left}/></button>
          <span class="avatar mint large">${fmt.initials(detail.name)}</span>
          <div class="grow"><span class="eyebrow">${(config && config.brand) || 'WhatsAYA'} · painel de operação</span><h1>${detail.name}</h1><span>${detail.phone}</span></div>
          ${(() => {
            if (detail.lead.takeover) return html`<span class="tag orange">Atendimento humano</span>`;
            if (detail.ai && !detail.ai.enabled) return html`<span class="tag">${detail.ai.label}</span>`;
            return html`<span class="tag mint">${assistantName} atendendo</span>`;
          })()}
        </div>
        <div class="lead-header-actions" aria-label="Controles da conversa">
          ${detail.lead.takeover ? html`<button class="lead-header-action green" onClick=${handBack}><${Icon.reactivation}/><span class="lead-action-label">Devolver para ${assistantName}</span></button>` : null}
          <button class=${`lead-header-action ${detail.lead.automation_enabled ? '' : 'green'}`} onClick=${toggleFollowup} title=${detail.lead.automation_enabled ? 'Pausar follow-up' : 'Retomar follow-up'}>
            <${Icon.followups}/><span class="lead-action-label">${detail.lead.automation_enabled ? 'Pausar follow-up' : 'Retomar follow-up'}</span>
          </button>
          <button class=${`lead-header-action ${detail.silence && detail.silence.silenced ? 'green' : ''}`} onClick=${toggleSilence} disabled=${detail.silence && !detail.silence.known} title=${detail.silence && detail.silence.silenced ? `Reativar ${assistantName}` : 'Silenciar por 10 minutos'}>
            <${Icon.reactivation}/><span class="lead-action-label">${detail.silence && detail.silence.silenced ? `Reativar ${assistantName}` : detail.silence && detail.silence.known ? 'Silenciar 10 min' : 'Ponte indisponível'}</span>
          </button>
          <button class=${`lead-header-action ${aiEnabled ? 'danger' : 'green'}`} onClick=${toggleAiAccess} disabled=${!detail.ai} title=${aiEnabled ? 'Desligar IA para este contato' : 'Liberar IA para este contato'}>
            <${Icon.blocked}/><span class="lead-action-label">${aiEnabled ? 'Desligar IA' : 'Liberar IA'}</span>
          </button>
        </div>
      </header>

      <section class="lead-summary-strip" aria-label="Resumo comercial">
        <div><span>Etapa</span><b>${(stages.find((stage) => stage.id === detail.lead.stage) || {}).label || detail.lead.stage}</b></div>
        <div><span>Valor</span><b>${detail.lead.estimated_value_cents == null ? 'Não informado' : fmt.brl(detail.lead.estimated_value_cents / 100)}</b></div>
        <div><span>Cadência</span><b>${detail.lead.cadence || 'Sem cadência'}</b></div>
        <div><span>Próximo toque</span><b>${detail.lead.next_followup_utc ? dateTime(detail.lead.next_followup_utc) : 'Não agendado'}</b></div>
      </section>

      <div class="lead-detail-grid">
      <section class="card conversation-card">
        <div class="conversation-head">
          <div><b>Conversa</b><span>Somente leitura · ${detail.timeline.length} itens</span></div>
          <label class="conversation-search"><${Icon.search}/><input type="search" value=${conversationQuery} onInput=${(event) => setConversationQuery(event.target.value)} placeholder="Buscar na conversa" aria-label="Buscar na conversa"/></label>
        </div>
        <div class="conversation-timeline" ref=${attachTimeline} tabindex="0">
          ${detail.timeline.length === 0 ? html`<${Empty}>Ainda não há mensagens desta conversa.</${Empty}>` : null}
          ${detail.timeline.length > 0 && visibleTimeline.length === 0 ? html`<${Empty}>Nenhuma mensagem corresponde à busca.</${Empty}>` : null}
          ${timelineRows(visibleTimeline, detail.name, assistantName)}
        </div>
        <footer class="conversation-footer"><span>Histórico completo disponível nesta área</span><button class="btn sm" onClick=${scrollToLatest}>Ir para a mais recente ↓</button></footer>
      </section>

      <aside class="lead-side">
        <section class="card lead-control-card">
          <div class="card-head"><div><span class="card-title">Fluxo comercial</span><span class="card-sub">Estado atual, não histórico</span></div></div>
          <label class="field-label">Etapa
            <select class="input" value=${detail.lead.stage} onChange=${(event) => updateStage(event.target.value)}>
              ${stages.map((stage) => html`<option value=${stage.id}>${stage.label}</option>`)}
            </select>
          </label>
          <form class="lead-value-form" key=${detail.lead.estimated_value_cents} onSubmit=${saveEstimatedValue}>
            <label class="field-label"><span>Valor estimado</span>
              <input class="input" name="value_brl" inputmode="decimal" defaultValue=${detail.lead.estimated_value_cents == null ? '' : (detail.lead.estimated_value_cents / 100).toFixed(2).replace('.', ',')} placeholder="Ex.: 4.800,00"/>
              <small>Em reais. Deixe vazio para remover.</small>
            </label>
            <button class="btn primary" type="submit">Salvar valor</button>
          </form>
          <div class="detail-pair"><span>Cadência</span><b>${detail.lead.cadence || 'Sem cadência'}</b></div>
          <div class="detail-pair"><span>Próximo toque</span><b>${detail.lead.next_followup_utc ? dateTime(detail.lead.next_followup_utc) : 'Não agendado'}</b></div>
          <div class="detail-pair"><span>Acesso da IA</span><b>${detail.ai ? detail.ai.label : '…'}</b></div>
          ${detail.meeting ? html`<div class="lead-meeting-card">
            <div class="detail-pair"><span>Reunião</span><b>${dateTime(detail.meeting.start)}</b></div>
            <div class="detail-pair"><span>Resultado</span><em class=${`meeting-status ${(detail.meeting.outcome || 'no_status').replace('_', '-')}`}>${MEETING_OUTCOMES[detail.meeting.outcome || 'no_status']}</em></div>
            <div class="lead-meeting-status-actions">${Object.entries(MEETING_OUTCOMES).filter(([id]) => id !== 'rescheduled' || detail.meeting.outcome === id).map(([id, label]) => html`<button type="button" class=${detail.meeting.outcome === id ? 'active' : ''} onClick=${() => updateMeetingOutcome(id)}>${label}</button>`)}</div>
            ${detail.meeting.outcome_followup_sent ? html`<small class="card-sub">${assistantName} já pediu a confirmação após a reunião.</small>` : null}
            ${detail.meeting.meet_link ? html`<a class="btn" href=${detail.meeting.meet_link} target="_blank" rel="noopener">Abrir no Meet</a>` : null}
          </div>` : html`<div class="detail-pair"><span>Reunião</span><b>Nenhuma marcada</b></div>`}
          <small class="card-sub">${detail.ai && !detail.ai.enabled
            ? 'IA desligada: as mensagens dele não são lidas nem respondidas. Você continua vendo tudo no seu WhatsApp.'
            : 'Os controles de atendimento e follow-up ficam sempre disponíveis no cabeçalho.'}</small>
        </section>

        <section class="card lead-profile-card">
          <span class="card-title">Sobre o lead</span>
          <div><span>Relação</span><p>${detail.profile.relationship || 'Sem classificação'}</p></div>
          <div><span>Qualificação</span>${detail.qualification && detail.qualification.length
            ? html`<ul class="lead-facts">${detail.qualification.map((fact) => html`<li key=${fact}>${fact}</li>`)}</ul>`
            : html`<p>Ainda sem falas do lead sobre o caso dele.</p>`}</div>
          <div><span>Resumo</span><p>${detail.profile.summary || 'Ainda sem resumo acumulado.'}</p></div>
          <div><span>Notas</span><p>${detail.profile.notes || 'Nenhuma nota manual.'}</p></div>
          ${detail.profile.tone ? html`<span class="chip">Tom: ${detail.profile.tone}</span>` : null}
        </section>

        ${detail.triage ? html`<section class="card lead-profile-card">
          <span class="card-title">Classificação da triagem</span>
          <div class="detail-pair"><span>Classificação</span><b>${detail.triage.flag || 'Revisar'}</b></div>
          <div class="detail-pair"><span>Estágio sugerido</span><b>${TRIAGE_STAGE_LABELS[detail.triage.stage] || detail.triage.stage || '—'}</b></div>
          ${triageConfidence(detail.triage.confidence) ? html`<div class="detail-pair"><span>Confiança</span><b>${triageConfidence(detail.triage.confidence)}</b></div>` : null}
          <div><span>Resumo</span><p>${detail.triage.summary || 'Sem resumo da triagem.'}</p></div>
          <div><span>Ação recomendada</span><p>${detail.triage.next_action || 'Nenhuma ação sugerida.'}</p></div>
          ${detail.triage.evidence && detail.triage.evidence.length ? html`<div class="triage-evidence">
            <span>Evidências</span>
            ${detail.triage.evidence.map((quote, index) => html`<blockquote key=${index}>"${quote}"</blockquote>`)}
          </div>` : null}
        </section>` : null}

        ${detail.imported_history && detail.imported_history.status ? html`<section class="card lead-profile-card">
          <span class="card-title">Histórico importado</span>
          <div class="detail-pair"><span>Status de origem</span><b>${detail.imported_history.status}</b></div>
          <div class="detail-pair"><span>Agendamentos</span><b>${detail.imported_history.appointments.length}</b></div>
          <div class="detail-pair"><span>Compras</span><b>${detail.imported_history.purchases.length}</b></div>
          <div class="detail-pair"><span>Escalonamentos</span><b>${detail.imported_history.escalations.length}</b></div>
          <div class="detail-pair"><span>Mensagens históricas</span><b>${detail.imported_history.historical_messages}</b></div>
          ${detail.imported_history.reactivation_stage !== null ? html`<div class="detail-pair"><span>Reativação</span><b>Fase ${detail.imported_history.reactivation_stage}</b></div>` : null}
          <small>Dados de um sistema anterior, somente leitura. As ações novas usam os dados do painel.</small>
        </section>` : null}

      </aside>
    </div>` : html`<div class="card lead-loading"><${Empty}>Carregando conversa…</${Empty}></div>`}
  </div>`;
}
