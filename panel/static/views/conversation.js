// Timeline da conversa + caixa de resposta, compartilhadas entre a tela Lead
// (#lead/<id>) e o mestre-detalhe de Contatos (#contacts/<id>). Nenhuma tela
// duplica isto: só importa `Conversation` e `Composer` daqui.
import { html, Fragment, post, api, useApi, Empty, Icon, dateTime, Avatar } from '../lib.js';
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

// "Hoje" / "Ontem" / data curta, para o chip de dia da espinha.
function dayLabel(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  const today = new Date();
  const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round((startOf(today) - startOf(date)) / 86400000);
  if (diffDays === 0) return 'Hoje';
  if (diffDays === 1) return 'Ontem';
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

function DayChip({ at }) {
  return html`<div class="conversation-day-chip"><span class="day-node"></span><b>${dayLabel(at)}</b><span class="day-rule"></span></div>`;
}

// Três vozes (Conversation Language v2): lead sem cor (bolha neutra), humano do
// painel/dono em preto (bolha invertida), IA num card de largura cheia com
// filete azul — nunca bolha, nunca gradiente. `owner` vem do backend como
// lead|aya|owner (painel/dono ficam sob "owner", diferenciados por `sent_by`).
function ConversationMessage({ item, leadName, leadAvatarUrl, assistantName = 'AYA' }) {
  const time = dateTime(item.last_at || item.at);
  if (item.owner === 'aya') {
    return html`<div class=${`conversation-row aya${item.historical ? ' historical' : ''}`}>
      <div class="conversation-ai-card">
        <div class="conversation-ai-head">
          <span class="conversation-ai-dot"></span>
          <span class="conversation-ai-name">${assistantName}</span>
          <span class="conversation-ai-time">${time}</span>
        </div>
        ${item.bubbles.map((bubble) => html`<div class="conversation-ai-body" key=${bubble.message_id}>
          ${bubble.media ? html`<${MediaAttachment} media=${bubble.media}/>` : null}
          ${bubble.body || ''}
        </div>`)}
      </div>
    </div>`;
  }
  const label = item.owner === 'lead' ? leadName : (item.sent_by || 'Você');
  const isRight = item.owner === 'owner';
  const avatar = html`<${Avatar} name=${label} url=${item.owner === 'lead' ? leadAvatarUrl : null} className="avatar conversation-avatar"/>`;
  const message = html`<div class="conversation-message">
    <div class="conversation-meta">
      ${isRight ? html`<span>${time}</span><span>${label}</span>` : html`<span>${label}</span><span>${time}</span>`}
    </div>
    <div class="conversation-bubbles">
      ${item.bubbles.map((bubble) => html`<div class=${`conversation-bubble ${bubble.media_type ? 'media' : ''}`} key=${bubble.message_id}>
        ${bubble.media ? html`<${MediaAttachment} media=${bubble.media}/>` : null}
        ${!bubble.media && /(audio|ptt)/i.test(bubble.media_type) ? html`<span class="audio-mark" aria-hidden="true">▶</span>` : null}
        ${bubble.body ? html`<span>${bubble.body}</span>` : null}
      </div>`)}
    </div>
  </div>`;
  return html`<div class=${`conversation-row ${item.owner}${item.historical ? ' historical' : ''}`}>
    ${isRight ? message : avatar}
    ${isRight ? avatar : message}
  </div>`;
}

// Nível do acontecimento (Conversation Language v2 · "Níveis de acontecimento"):
// preto = quem responde (assumir, reatribuir, devolver), verde = presença e
// continuidade (handoff concluído, resolvido), vermelho quadrado = automação
// (follow-up), vazado = registro (abertura, reunião marcada). Sem dado de
// SLA/janela de canal ainda, o nível "limite" (âmbar) fica sem uso por ora.
function eventLevel(item) {
  if (item.event === 'followup') return 'vermelho';
  if (item.event === 'booking') return 'vazado';
  if (item.event === 'handoff') return 'verde';
  if (item.event === 'atendimento') {
    if (item.tipo === 'resolvido') return 'verde';
    if (item.tipo === 'aberto') return 'vazado';
    return 'preto'; // assumido, devolvido(_auto), reatribuido, responsavel_removido
  }
  return 'preto';
}

function FlowEvent({ item }) {
  const detail = item.event === 'followup'
    ? `${item.cadence || 'Follow-up'}${item.step ? ` · toque ${item.step}` : ''}${item.reason ? ` · ${item.reason}` : ''}`
    : item.reason;
  return html`<div class=${`flow-event nivel-${eventLevel(item)}${item.historical ? ' historical' : ''}`}>
    <span class="flow-node"></span>
    <span class="flow-event-pill">
      <b>${item.label}</b>${detail ? html`<span class="detail">${detail}</span>` : null}
      <time>${dateTime(item.at)}</time>
    </span>
  </div>`;
}

function HistoricalDivider() {
  return html`<div class="conversation-historical-divider" key="historical-divider"><span>Histórico importado</span></div>`;
}

// Timeline com chip de dia a cada virada de data e o divisor "Histórico
// importado" antes da primeira mensagem legada.
function timelineRows(items, leadName, leadAvatarUrl, assistantName) {
  let dividerShown = false;
  let lastDay = null;
  return items.flatMap((item, index) => {
    const rows = [];
    const day = dayLabel(item.at);
    if (day && day !== lastDay) {
      lastDay = day;
      rows.push(html`<${DayChip} key=${`day-${item.at}-${index}`} at=${item.at}/>`);
    }
    if (item.historical && !dividerShown) {
      dividerShown = true;
      rows.push(html`<${HistoricalDivider}/>`);
    }
    rows.push(item.type === 'message'
      ? html`<${ConversationMessage} key=${item.at + index} item=${item} leadName=${leadName} leadAvatarUrl=${leadAvatarUrl} assistantName=${assistantName}/>`
      : html`<${FlowEvent} key=${item.at + index} item=${item}/>`);
    return rows;
  });
}

// Cabeçalho de busca + rolagem + rodapé. `detail` é o payload de /api/lead/<id>
// (mesmo formato usado pela tela Lead e pelo mestre-detalhe de Contatos).
export function Conversation({ chatId, detail, assistantName = 'AYA' }) {
  const timelineRef = useRef(null);
  const [query, setQuery] = useState('');
  const [newCount, setNewCount] = useState(0);
  const [atBottom, setAtBottom] = useState(true);
  const prevLenRef = useRef(0);

  const attachTimeline = useCallback((node) => {
    timelineRef.current = node;
    if (node) {
      requestAnimationFrame(() => {
        if (node.isConnected) node.scrollTop = node.scrollHeight;
      });
    }
  }, [chatId]);

  useEffect(() => { setQuery(''); setNewCount(0); setAtBottom(true); prevLenRef.current = 0; }, [chatId]);

  const timeline = detail ? detail.timeline : [];

  // Pílula "N novas mensagens": só quando o usuário não está no fim e chega
  // item novo (contado pelo tamanho da timeline entre renders).
  useEffect(() => {
    const grew = timeline.length - prevLenRef.current;
    if (prevLenRef.current > 0 && grew > 0 && !atBottom) setNewCount((n) => n + grew);
    prevLenRef.current = timeline.length;
  }, [timeline.length, atBottom]);

  const onScroll = () => {
    const node = timelineRef.current;
    if (!node) return;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    setAtBottom(nearBottom);
    if (nearBottom) setNewCount(0);
  };

  const leadName = detail ? detail.name : '';
  const leadAvatarUrl = detail ? detail.avatar_url : null;
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
    setNewCount(0);
  };

  return html`<${Fragment}>
    <div class="conversation-head">
      <div><b>Conversa</b><span>${timeline.length} ${timeline.length === 1 ? 'item' : 'itens'}</span></div>
      <label class="conversation-search"><${Icon.search}/><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Buscar na conversa" aria-label="Buscar na conversa"/></label>
    </div>
    <div class="conversation-body">
      <div class="conversation-timeline" ref=${attachTimeline} tabindex="0" onScroll=${onScroll}>
        ${timeline.length === 0 ? html`<${Empty}>Ainda não há mensagens desta conversa.</${Empty}>` : null}
        ${timeline.length > 0 && visibleTimeline.length === 0 ? html`<${Empty}>Nenhuma mensagem corresponde à busca.</${Empty}>` : null}
        ${timelineRows(visibleTimeline, leadName, leadAvatarUrl, assistantName)}
      </div>
      ${newCount > 0 ? html`<button type="button" class="conversation-new-messages" onClick=${scrollToLatest}><i class="fi fi-rr-arrow-down" aria-hidden="true"></i>${newCount} ${newCount === 1 ? 'nova mensagem' : 'novas mensagens'}</button>` : null}
    </div>
  </${Fragment}>`;
}

// Caixa de resposta: envia pelo bridge via /api/actions/reply, nunca finge
// sucesso — sem 200 o texto fica na caixa para o atendente tentar de novo.
// `lockedReason`: a tela de Atendimento trava a caixa quando o atendimento é de
// outro humano — o servidor recusa com 403 de qualquer forma. `config` só é
// usado pelo chip de canal (nome do negócio); Composer funciona sem ele.
export function Composer({ chatId, detail, status, onSent, me, lockedReason = null, config = null }) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const [file, setFile] = useState(null);
  const [focused, setFocused] = useState(false);
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
  const expanded = focused || sending || !!text || !!file;
  const businessName = (config && config.brand) || 'WhatsApp';
  return html`<div class="composer">
    ${me && me.name ? html`<div class="composer-meta">Respondendo como ${me.name}</div>` : null}
    <div class="composer-toolbar">
      <div class="composer-tabs">
        <button type="button" class="composer-tab active" disabled>Responder</button>
        <button type="button" class="composer-tab" disabled title="Em breve">Nota interna</button>
      </div>
      <span class="composer-channel"><i class="fi fi-brands-whatsapp" aria-hidden="true"></i>${businessName}</span>
    </div>
    ${disabledReason ? html`<div class="composer-disabled">${disabledReason}</div>` : null}
    ${error ? html`<div class="composer-error">${error}</div>` : null}
    ${warning ? html`<div class="composer-warning">${warning}</div>` : null}
    <div class=${`composer-box${expanded ? ' expanded' : ''}${disabledReason ? ' locked' : ''}`}>
      ${file ? html`<div class="composer-attachment">
        <${Icon.attach}/><span>${file.name}</span><small>${formatBytes(file.size)}</small>
        <button type="button" class="btn sm" aria-label="Remover anexo" disabled=${sending} onClick=${() => setFile(null)}><${Icon.close}/></button>
      </div>` : null}
      <textarea ref=${areaRef} class="composer-input" rows="1" value=${text} maxlength=${REPLY_MAX_LENGTH}
        placeholder=${file ? 'Legenda (opcional)' : 'Escreva sua resposta'} disabled=${!!disabledReason || sending}
        onInput=${(event) => { setText(event.target.value); autoGrow(event.target); }}
        onFocus=${() => setFocused(true)} onBlur=${() => setFocused(false)}
        onKeyDown=${onKeyDown}></textarea>
      <div class="composer-actions">
        <input ref=${fileRef} type="file" accept=${MEDIA_ACCEPT} hidden onChange=${pickFile}/>
        <button type="button" class="btn sm composer-attach" aria-label="Anexar arquivo" title="Anexar arquivo (até 25 MB)" disabled=${!!disabledReason || sending} onClick=${() => fileRef.current && fileRef.current.click()}><${Icon.attach}/></button>
        <span class="grow"></span>
        ${count >= COUNTER_THRESHOLD ? html`<span class="composer-count">${count}/${REPLY_MAX_LENGTH}</span>` : null}
        <button type="button" class="btn composer-send" disabled=${!!disabledReason || sending || (!text.trim() && !file)} onClick=${send}>${sending ? 'Enviando…' : 'Enviar'}</button>
      </div>
    </div>
    <div class="composer-hint">Enter envia · Shift+Enter quebra linha</div>
  </div>`;
}
