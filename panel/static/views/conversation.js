// Timeline da conversa + caixa de resposta, compartilhadas entre a tela Lead
// (#lead/<id>) e o mestre-detalhe de Contatos (#contacts/<id>). Nenhuma tela
// duplica isto: só importa `Conversation` e `Composer` daqui.
import { html, Fragment, post, api, useApi, Empty, Icon, dateTime } from '../lib.js';
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';

const REPLY_MAX_LENGTH = 4096;
const COUNTER_THRESHOLD = 3900;
const MEDIA_MAX_BYTES = 25 * 1024 * 1024;
const MEDIA_ACCEPT = 'image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/3gpp,audio/ogg,audio/mpeg,audio/mp4,audio/wav,application/pdf,.doc,.docx,.xlsx';

// Arquivo no corpo cru e metadados percent-encoded nos headers: o painel é stdlib
// puro e não tem parser multipart.
function postMedia(chatId, file, caption) {
  return api('/api/actions/reply-media', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': file.type || 'application/octet-stream',
      'X-Chat-Id': encodeURIComponent(chatId),
      'X-File-Name': encodeURIComponent(file.name || ''),
      'X-Caption': encodeURIComponent(caption || ''),
    },
    body: file,
  });
}

export function formatBytes(size) {
  if (!size) return '';
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

// Mídia guardada no R2: o <img>/<audio>/<video> aponta para /api/media/<id>, que
// redireciona para a URL assinada. Documento vira link com nome e tamanho.
export function MediaAttachment({ media }) {
  if (media.kind === 'image') return html`<a class="media-image" href=${media.url} target="_blank" rel="noopener"><img src=${media.url} alt=${media.name || 'imagem'} loading="lazy"/></a>`;
  if (media.kind === 'audio') return html`<audio class="media-audio" controls preload="none" src=${media.url}></audio>`;
  if (media.kind === 'video') return html`<video class="media-video" controls preload="metadata" src=${media.url}></video>`;
  return html`<a class="media-file" href=${media.url} target="_blank" rel="noopener">
    <${Icon.document}/><span>${media.name || 'documento'}</span><small>${formatBytes(media.size)}</small>
  </a>`;
}

// Aba Mídias: tudo que o chat tem guardado no R2, mais recente primeiro. Usada no
// painel do contato (Atendimento) e na ficha do Lead; nenhuma tela reimplementa.
export function MediaGallery({ chatId }) {
  const resource = useApi(`/api/lead/${encodeURIComponent(chatId)}/media`, { every: 60000, deps: [chatId] });
  const items = (resource.data && resource.data.items) || [];
  if (resource.error) return html`<p class="media-gallery-note">Não consegui listar as mídias: ${resource.error}</p>`;
  if (!resource.data) return html`<p class="media-gallery-note">Carregando…</p>`;
  if (!items.length) return html`<p class="media-gallery-note">Nenhuma mídia guardada nesta conversa.</p>`;
  return html`<div class="media-gallery">
    ${items.map((item) => html`<figure class=${`media-item ${item.kind}`} key=${item.message_id} title=${`${item.from_me ? 'Enviado' : 'Recebido'} em ${dateTime(item.at)}`}>
      ${item.kind === 'image' ? html`<a href=${item.url} target="_blank" rel="noopener"><img src=${item.url} alt=${item.caption || ''} loading="lazy"/></a>`
        : item.kind === 'video' ? html`<video controls preload="metadata" src=${item.url}></video>`
        : item.kind === 'audio' ? html`<audio controls preload="none" src=${item.url}></audio>`
        : html`<a class="media-file" href=${item.url} target="_blank" rel="noopener"><${Icon.document}/><span>${item.name || 'documento'}</span><small>${formatBytes(item.size)}</small></a>`}
      <figcaption>${dateTime(item.at)}${item.caption ? ` · ${item.caption}` : ''}</figcaption>
    </figure>`)}
  </div>`;
}

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
          ${bubble.media ? html`<${MediaAttachment} media=${bubble.media}/>` : null}
          ${!bubble.media && /(audio|ptt)/i.test(bubble.media_type) ? html`<span class="audio-mark" aria-hidden="true">▶</span>` : null}
          ${bubble.body ? html`<span>${bubble.body}</span>` : null}
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
  const [file, setFile] = useState(null);
  const areaRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    setText('');
    setFile(null);
    setError(null);
    setWarning(null);
  }, [chatId]);

  const pickFile = (event) => {
    const picked = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!picked) return;
    if (picked.size > MEDIA_MAX_BYTES) {
      setError('Arquivo acima de 25 MB.');
      return;
    }
    setError(null);
    setFile(picked);
  };

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
    if ((!message && !file) || sending || disabledReason) return;
    setSending(true);
    setError(null);
    setWarning(null);
    try {
      const result = file
        ? await postMedia(chatId, file, message)
        : await post('/api/actions/reply', { chat_id: chatId, message });
      setText('');
      setFile(null);
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
    ${file ? html`<div class="composer-attachment">
      <${Icon.attach}/><span>${file.name}</span><small>${formatBytes(file.size)}</small>
      <button type="button" class="btn sm" aria-label="Remover anexo" disabled=${sending} onClick=${() => setFile(null)}><${Icon.close}/></button>
    </div>` : null}
    <div class="composer-row">
      <input ref=${fileRef} type="file" accept=${MEDIA_ACCEPT} hidden onChange=${pickFile}/>
      <button type="button" class="btn sm composer-attach" aria-label="Anexar arquivo" title="Anexar arquivo (até 25 MB)" disabled=${!!disabledReason || sending} onClick=${() => fileRef.current && fileRef.current.click()}><${Icon.attach}/></button>
      <textarea ref=${areaRef} class="composer-input" rows="1" value=${text} maxlength=${REPLY_MAX_LENGTH}
        placeholder=${file ? 'Legenda (opcional)' : 'Escreva uma mensagem'} disabled=${!!disabledReason || sending}
        onInput=${(event) => { setText(event.target.value); autoGrow(event.target); }}
        onKeyDown=${onKeyDown}></textarea>
      <button type="button" class="btn primary composer-send" disabled=${!!disabledReason || sending || (!text.trim() && !file)} onClick=${send}>${sending ? 'Enviando…' : 'Enviar'}</button>
    </div>
    ${count >= COUNTER_THRESHOLD ? html`<span class="composer-count">${count}/${REPLY_MAX_LENGTH}</span>` : null}
  </div>`;
}
