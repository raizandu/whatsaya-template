import { html, useApi, post, fmt, ErrorBox, Empty, Icon } from '../lib.js';

// Usado só até o /api/config responder na primeira carga.
const DEFAULT_STAGES = [
  { id: 'new', label: 'Novo' },
  { id: 'qualification', label: 'Qualificação' },
  { id: 'pricing', label: 'Preço' },
  { id: 'proposal', label: 'Proposta' },
  { id: 'payment', label: 'Pagamento' },
];

const dateTime = (value, options = {}) => value
  ? new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', ...options })
  : '—';

function ConversationMessage({ item, leadName, assistantName = 'AYA' }) {
  const label = item.owner === 'lead' ? leadName : item.owner === 'owner' ? 'Você' : assistantName;
  const count = item.bubbles.length;
  return html`<div class=${`conversation-row ${item.owner}`}>
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
  return html`<div class=${`flow-event ${item.event}`}>
    <span class="flow-dot"></span>
    <div><b>${item.label}</b>${detail ? html`<span>${detail}</span>` : null}</div>
    <time>${dateTime(item.at)}</time>
  </div>`;
}

export default function Lead({ chatId, config, assistantName = 'AYA', setToast, go }) {
  const resource = useApi(`/api/lead/${encodeURIComponent(chatId)}`, { every: 30000 });
  const detail = resource.data;
  const stages = (config && config.pipeline && config.pipeline.stages) || DEFAULT_STAGES;

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

  const toggleBlock = async () => {
    const blocked = detail.lead.blocked;
    try {
      await post(blocked ? '/api/actions/unblock' : '/api/actions/block', { chat_id: chatId });
      setToast(blocked
        ? `${assistantName} volta a atender este contato na próxima mensagem dele`
        : `${assistantName} desligada para este contato`);
      resource.reload();
    } catch (err) {
      setToast(`Não alterei o atendimento deste contato: ${err.message}`);
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

  return html`
    <${ErrorBox} error=${resource.error}/>
    <button class="back-link" onClick=${() => history.length > 1 ? history.back() : go('contacts')}><${Icon.left}/> Voltar</button>
    ${detail ? html`<div class="lead-detail-grid">
      <section class="card conversation-card">
        <div class="lead-identity">
          <span class="avatar mint large">${fmt.initials(detail.name)}</span>
          <div class="grow"><h2>${detail.name}</h2><span>${detail.phone}</span></div>
          <span class=${`tag ${detail.lead.takeover ? 'orange' : 'mint'}`}>${detail.lead.takeover ? 'Atendimento humano' : `${assistantName} atendendo`}</span>
        </div>
        <div class="conversation-head">
          <div><b>Conversa</b><span>Mensagens reais do WhatsApp · somente leitura</span></div>
          <span class="conversation-legend"><i class="lead"></i>Lead <i class="aya"></i>AYA <i class="owner"></i>Você</span>
        </div>
        <div class="conversation-timeline">
          ${detail.timeline.length === 0 ? html`<${Empty}>Ainda não há mensagens desta conversa no histórico vivo.</${Empty}>` : null}
          ${detail.timeline.map((item, index) => item.type === 'message'
            ? html`<${ConversationMessage} key=${item.at + index} item=${item} leadName=${detail.name} assistantName=${assistantName}/>`
            : html`<${FlowEvent} key=${item.at + index} item=${item}/>`)}
        </div>
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
          <div class="detail-pair"><span>Reunião</span><b>${detail.meeting ? dateTime(detail.meeting.start) : 'Nenhuma marcada'}</b></div>
          ${detail.meeting && detail.meeting.meet_link ? html`<a class="btn" href=${detail.meeting.meet_link} target="_blank" rel="noopener">Abrir no Meet</a>` : null}
          <button class="btn" onClick=${toggleFollowup}>${detail.lead.automation_enabled ? 'Pausar follow-up' : 'Retomar follow-up'}</button>
          <button class=${`btn ${detail.silence && detail.silence.silenced ? 'green' : ''}`} onClick=${toggleSilence} disabled=${detail.silence && !detail.silence.known}>
            ${detail.silence && detail.silence.silenced ? `Reativar ${assistantName} agora` : detail.silence && detail.silence.known ? `Silenciar ${assistantName} por 10 min` : 'Ponte indisponível'}
          </button>
          <button class=${`btn ${detail.lead.blocked ? 'green' : 'danger'}`} onClick=${toggleBlock}>
            ${detail.lead.blocked ? `Ligar ${assistantName} neste contato` : `Desligar ${assistantName} neste contato`}
          </button>
          <small class="card-sub">${detail.lead.blocked
            ? 'Desligada: as mensagens dele não são lidas nem respondidas pela IA. Você continua vendo tudo no seu WhatsApp.'
            : 'Desligar vale até você ligar de novo; o silêncio de 10 min é só uma pausa curta.'}</small>
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
    </div>` : html`<div class="card"><${Empty}>Carregando conversa…</${Empty}></div>`}
  `;
}
