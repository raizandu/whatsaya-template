// Timeline da conversa + caixa de resposta, compartilhadas entre a tela Lead
// (#lead/<id>) e o mestre-detalhe de Contatos (#contacts/<id>). Nenhuma tela
// duplica isto: só importa `Conversation` e `Composer` daqui.
import { html, Fragment, post, Empty, Icon } from '../lib.js';
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';

const REPLY_MAX_LENGTH = 4096;
const COUNTER_THRESHOLD = 3900;

const dateTime = (value, options = {}) => value
  ? new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', ...options })
  : '—';

function ConversationMessage({ item, leadName, assistantName = 'AYA' }) {
  const label = item.owner === 'lead' ? leadName : item.owner === 'owner' ? (item.sent_by || 'Você') : assistantName;
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

// Cabeçalho de busca + rolagem + rodapé. `detail` é o payload de /api/lead/<id>
// (mesmo formato usado pela tela Lead e pelo mestre-detalhe de Contatos).
export function Conversation({ chatId, detail, assistantName = 'AYA' }) {
  const timelineRef = useRef(null);
  const [query, setQuery] = useState('');
  const attachTimeline = useCallback((node) => {
    timelineRef.current = node;
    if (node) {
      requestAnimationFrame(() => {
        if (node.isConnected) node.scrollTop = node.scrollHeight;
      });
    }
  }, [chatId]);

  useEffect(() => setQuery(''), [chatId]);

  const timeline = detail ? detail.timeline : [];
  const leadName = detail ? detail.name : '';
  const normalizedQuery = query.trim().toLocaleLowerCase('pt-BR');
  const visibleTimeline = normalizedQuery
    ? timeline.filter((item) => {
      const fields = item.type === 'message'
        ? item.bubbles.map((bubble) => bubble.body)
        : [item.label, item.reason, item.cadence];
      return fields.some((field) => String(field || '').toLocaleLowerCase('pt-BR').includes(normalizedQuery));
    })
    : timeline;

  const scrollToLatest = () => {
    const timelineNode = timelineRef.current;
    if (timelineNode) timelineNode.scrollTo({ top: timelineNode.scrollHeight, behavior: 'smooth' });
  };

  return html`<${Fragment}>
    <div class="conversation-head">
      <div><b>Conversa</b><span>${timeline.length} ${timeline.length === 1 ? 'item' : 'itens'}</span></div>
      <label class="conversation-search"><${Icon.search}/><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Buscar na conversa" aria-label="Buscar na conversa"/></label>
    </div>
    <div class="conversation-timeline" ref=${attachTimeline} tabindex="0">
      ${timeline.length === 0 ? html`<${Empty}>Ainda não há mensagens desta conversa.</${Empty}>` : null}
      ${timeline.length > 0 && visibleTimeline.length === 0 ? html`<${Empty}>Nenhuma mensagem corresponde à busca.</${Empty}>` : null}
      ${timelineRows(visibleTimeline, leadName, assistantName)}
    </div>
    <footer class="conversation-footer"><span>${leadName || 'Conversa'}</span><button class="btn sm" onClick=${scrollToLatest}>Ir para a mais recente ↓</button></footer>
  </${Fragment}>`;
}

// Caixa de resposta: envia pelo bridge via /api/actions/reply, nunca finge
// sucesso — sem 200 o texto fica na caixa para o atendente tentar de novo.
// `lockedReason`: a tela de Atendimento trava a caixa quando o atendimento é de
// outro humano — o servidor recusa com 403 de qualquer forma.
export function Composer({ chatId, detail, status, onSent, me, lockedReason = null }) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const areaRef = useRef(null);

  useEffect(() => {
    setText('');
    setError(null);
    setWarning(null);
  }, [chatId]);

  const autoGrow = (el) => {
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  const blocked = !!(detail && detail.lead && detail.lead.blocked);
  const bridgeUp = !!(status && status.bridge === 'up');
  const disabledReason = lockedReason ? lockedReason : blocked
    ? 'Contato bloqueado: desbloqueie para responder pelo painel.'
    : !bridgeUp ? 'Ponte do WhatsApp fora do ar: não é possível enviar agora.' : null;

  const send = async () => {
    const message = text.trim();
    if (!message || sending || disabledReason) return;
    setSending(true);
    setError(null);
    setWarning(null);
    try {
      const result = await post('/api/actions/reply', { chat_id: chatId, message });
      setText('');
      if (areaRef.current) areaRef.current.style.height = 'auto';
      if (result && result.warning) setWarning(result.warning);
      if (onSent) onSent(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  const count = text.length;
  return html`<div class="composer">
    ${me && me.name ? html`<div class="composer-meta">Respondendo como ${me.name}</div>` : null}
    ${disabledReason ? html`<div class="composer-disabled">${disabledReason}</div>` : null}
    ${error ? html`<div class="composer-error">${error}</div>` : null}
    ${warning ? html`<div class="composer-warning">${warning}</div>` : null}
    <div class="composer-row">
      <textarea ref=${areaRef} class="composer-input" rows="1" value=${text} maxlength=${REPLY_MAX_LENGTH}
        placeholder="Escreva uma mensagem" disabled=${!!disabledReason || sending}
        onInput=${(event) => { setText(event.target.value); autoGrow(event.target); }}
        onKeyDown=${onKeyDown}></textarea>
      <button type="button" class="btn primary composer-send" disabled=${!!disabledReason || sending || !text.trim()} onClick=${send}>${sending ? 'Enviando…' : 'Enviar'}</button>
    </div>
    ${count >= COUNTER_THRESHOLD ? html`<span class="composer-count">${count}/${REPLY_MAX_LENGTH}</span>` : null}
  </div>`;
}
