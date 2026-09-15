import { useEffect, useState } from 'preact/hooks';
import { html, Fragment, useApi, post, fmt, ErrorBox, Empty, Menu, Icon } from '../lib.js';
import { Conversation, Composer } from './conversation.js';

const PAGE_SIZE = 100;

const scopes = (assistantName) => [
  ['all', 'Todos'],
  ['attention', 'Pedem atenção'],
  ['aya', `${assistantName} atendendo`],
  ['legacy', 'Legado (IA desligada)'],
  ['reactivation', 'Reativação'],
  ['blocked', 'Bloqueados'],
];

const FLAGS = ['Lead', 'Cliente', 'Pessoal', 'Fornecedor/parceiro', 'Spam/irrelevante', 'Revisar'];

const normalize = (value) => String(value || '')
  .normalize('NFD')
  .replace(/\p{M}/gu, '')
  .toLocaleLowerCase('pt-BR');

const meetingPending = (contact) => Boolean(contact.meeting && contact.meeting.outcome_pending);
const needsAttention = (contact) => contact.human || contact.next_followup_rel === 'atrasado' || meetingPending(contact);

const inScope = (contact, scope) => {
  if (scope === 'attention') return needsAttention(contact);
  if (scope === 'aya') return contact.automation && !contact.human;
  if (scope === 'legacy') return contact.kind === 'legacy';
  if (scope === 'reactivation') return contact.kind === 'reactivation';
  if (scope === 'blocked') return contact.kind === 'blocked';
  return true;
};

const aiTone = (contact) => {
  if (contact.kind === 'blocked') return 'blocked';
  if (contact.human) return 'human';
  if (meetingPending(contact)) return 'attention';
  if (contact.ai && contact.ai.enabled) return 'aya';
  return 'paused';
};

const aiLabel = (contact) => {
  if (meetingPending(contact)) return 'Reunião sem status';
  return contact.ai ? contact.ai.label : '…';
};

function Avatar({ contact }) {
  return html`<span class="contacts-avatar">${fmt.initials(contact.name)}</span>`;
}

function AiStatus({ contact }) {
  return html`<span class=${`contacts-status ${aiTone(contact)}`}><span></span>${aiLabel(contact)}</span>`;
}

function ScopeTabs({ scope, setScope, counts, assistantName }) {
  return html`<div class="contacts-scopes" role="group" aria-label="Filtrar por situação">
    ${scopes(assistantName).map(([id, label]) => html`<button key=${id} type="button" class=${scope === id ? 'active' : ''} onClick=${() => setScope(id)}>
      ${label}<b>${counts[id] || 0}</b>
    </button>`)}
  </div>`;
}

function FlagChips({ flag, setFlag, counts }) {
  return html`<div class="contacts-scopes" role="group" aria-label="Filtrar por classificação da triagem">
    <button type="button" class=${!flag ? 'active' : ''} onClick=${() => setFlag('')}>Todas</button>
    ${FLAGS.map((name) => html`<button key=${name} type="button" class=${flag === name ? 'active' : ''} onClick=${() => setFlag(flag === name ? '' : name)}>
      ${name}<b>${counts[name] || 0}</b>
    </button>`)}
  </div>`;
}

const phoneOf = (chatId) => String(chatId || '').split('@')[0].replace(/\D/g, '');

// Menu de ações (receita do DS): o mesmo conjunto atende a linha da lista (via
// cabeçalho da conversa) e é reaproveitado ali com "Abrir ficha completa".
function rowActions({ contact, go, unblock, toggleAiAccess, blockOne, copyNumber }) {
  if (contact.kind === 'blocked') {
    return [
      { label: 'Copiar número', icon: 'copy', onClick: () => copyNumber(contact) },
      'separator',
      { label: 'Desbloquear contato', icon: 'unlock', onClick: () => unblock(contact) },
    ];
  }
  const aiOn = Boolean(contact.ai && contact.ai.enabled);
  return [
    { label: 'Abrir no WhatsApp', icon: 'paper-plane', href: `https://wa.me/${phoneOf(contact.chat_id)}` },
    { label: 'Copiar número', icon: 'copy', onClick: () => copyNumber(contact) },
    'separator',
    { label: aiOn ? 'Desligar IA neste contato' : 'Liberar IA neste contato', icon: aiOn ? 'pause' : 'play', onClick: () => toggleAiAccess(contact) },
    'separator',
    { label: 'Bloquear contato', icon: 'ban', danger: true, onClick: () => blockOne(contact) },
  ];
}

// Linha compacta da coluna esquerda: avatar, nome, prévia em uma linha, hora
// da última conversa, status da IA e marca de atenção — nunca a tabela cheia.
function ContactRow({ contact, active, onSelect }) {
  const urgent = needsAttention(contact) && contact.kind !== 'blocked';
  return html`<button type="button" class=${`contacts-row${active ? ' active' : ''}${urgent ? ' urgent' : ''}`} onClick=${() => onSelect(contact)} aria-current=${active ? 'true' : null}>
    <${Avatar} contact=${contact}/>
    <span class="contacts-row-main">
      <span class="contacts-row-top"><b>${contact.name}</b><time>${contact.last || '—'}</time></span>
      <span class="contacts-row-bottom"><span class="contacts-row-preview">${contact.preview || 'Sem mensagem recente'}</span><${AiStatus} contact=${contact}/></span>
    </span>
  </button>`;
}

// Mesma tag de estado do cabeçalho da tela Lead (#lead/<id>).
function stateTag(detail, assistantName) {
  if (detail.lead && detail.lead.takeover) return html`<span class="tag orange">Atendimento humano</span>`;
  if (detail.ai && !detail.ai.enabled) return html`<span class="tag">${detail.ai.label}</span>`;
  return html`<span class="tag mint">${assistantName} atendendo</span>`;
}

function ContactDetail({ chatId, status, assistantName, go, unblock, toggleAiAccess, blockOne, copyNumber, onDeselect }) {
  const leadResource = useApi(`/api/lead/${encodeURIComponent(chatId)}`, { every: chatId ? 5000 : 0, deps: [chatId] });
  const detail = leadResource.data;

  if (!chatId) {
    return html`<div class="contacts-detail-empty"><${Empty}>Escolha um contato para ver a conversa.</${Empty}></div>`;
  }
  if (!detail) {
    return html`<div class="contacts-detail-empty"><${Empty}>Carregando conversa…</${Empty}></div>`;
  }

  const contact = { chat_id: chatId, name: detail.name, ai: detail.ai, kind: detail.lead && detail.lead.blocked ? 'blocked' : 'active' };
  const items = rowActions({ contact, go, unblock, toggleAiAccess, blockOne, copyNumber });
  items.push('separator', { label: 'Abrir ficha completa', icon: 'expand', onClick: () => go(`lead/${encodeURIComponent(chatId)}`) });

  return html`<${Fragment}>
    <header class="contacts-detail-header">
      <button class="lead-back-button" onClick=${onDeselect} aria-label="Voltar para a lista"><${Icon.left}/></button>
      <span class="avatar mint">${fmt.initials(detail.name)}</span>
      <div class="grow"><b>${detail.name}</b><span>${detail.phone}</span></div>
      ${stateTag(detail, assistantName)}
      <${Menu} label=${`Ações para ${detail.name}`} items=${items}/>
    </header>
    <section class="card conversation-card contacts-conversation-card">
      <${Conversation} chatId=${chatId} detail=${detail} assistantName=${assistantName}/>
      <${Composer} chatId=${chatId} detail=${detail} status=${status} onSent=${() => leadResource.reload()}/>
    </section>
  </${Fragment}>`;
}

export default function Contacts({ assistantName = 'AYA', setToast, go, status, chatId = '' }) {
  const resource = useApi('/api/contacts', { every: 30000 });
  const data = resource.data;
  const contacts = data ? data.contacts : [];
  const counts = (data && data.counts) || {};
  const flagCounts = (data && data.flags) || {};

  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('all');
  const [flag, setFlag] = useState('');
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [blockOpen, setBlockOpen] = useState(false);
  const [blockQuery, setBlockQuery] = useState('');

  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [scope, flag, query]);

  const needle = normalize(query.trim());
  const filtered = contacts.filter((contact) => {
    if (!inScope(contact, scope)) return false;
    if (flag && !(contact.triage && contact.triage.flag === flag)) return false;
    if (!needle) return true;
    return normalize([
      contact.name, contact.phone, contact.preview, contact.triage && contact.triage.summary,
    ].join(' ')).includes(needle);
  });
  const visible = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > visible.length;

  const blockContact = async (event) => {
    event.preventDefault();
    if (!blockQuery.trim()) return;
    try {
      await post('/api/actions/block', { query: blockQuery.trim() });
      setToast(`Bloqueado: ${blockQuery.trim()}`);
      setBlockQuery('');
      setBlockOpen(false);
      resource.reload();
    } catch (err) {
      setToast(`Não bloqueei: ${err.message}`);
    }
  };

  const copyNumber = async (contact) => {
    try { await navigator.clipboard.writeText(phoneOf(contact.chat_id)); setToast('Número copiado'); }
    catch { setToast('Não consegui copiar o número'); }
  };
  const blockOne = async (contact) => {
    try {
      await post('/api/actions/block', { chat_id: contact.chat_id, name: contact.name });
      setToast(`${contact.name} bloqueado`);
      resource.reload();
    } catch (err) { setToast(`Não bloqueei: ${err.message}`); }
  };

  const unblock = async (contact) => {
    try {
      await post('/api/actions/unblock', { chat_id: contact.chat_id });
      setToast(`${contact.name} liberado. A conversa anterior da IA será arquivada.`);
      resource.reload();
    } catch (err) {
      setToast(`Não desbloqueei: ${err.message}`);
    }
  };

  const toggleAiAccess = async (contact) => {
    const enabled = !(contact.ai && contact.ai.enabled);
    try {
      await post('/api/actions/ai-access', { chat_id: contact.chat_id, enabled });
      setToast(enabled ? `IA liberada para ${contact.name}` : `IA desligada para ${contact.name}`);
      resource.reload();
    } catch (err) {
      setToast(`Não alterei a IA: ${err.message}`);
    }
  };

  const selectContact = (contact) => go(`contacts/${encodeURIComponent(contact.chat_id)}`);
  const deselect = () => go('contacts');

  return html`<div class="contacts-page contacts-split">
    <${ErrorBox} error=${resource.error}/>
    <section class="contacts-metrics five compact" aria-label="Resumo dos contatos">
      <div><span>Base total</span><b>${data ? fmt.int(counts.all || 0) : '…'}</b><small>contatos no diretório</small></div>
      <div><span>Legado (IA desligada)</span><b>${data ? fmt.int(counts.legacy || 0) : '…'}</b><small>histórico importado</small></div>
      <div><span>${assistantName} atendendo</span><b>${data ? fmt.int(counts.aya || 0) : '…'}</b><small>automação ativa</small></div>
      <div><span>Pedem atenção</span><b>${data ? fmt.int(counts.attention || 0) : '…'}</b><small>reunião, ação ou toque vencido</small></div>
      <div><span>Bloqueados</span><b>${data ? fmt.int(counts.blocked || 0) : '…'}</b><small>fora do atendimento</small></div>
    </section>

    <section class="contacts-surface">
     <div class=${`contacts-master-detail${chatId ? ' has-selection' : ''}`}>
      <div class="contacts-master">
        <header class="contacts-master-toolbar">
          <label class="contacts-search"><span>Buscar contatos</span><div><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/></div><small>${fmt.int(filtered.length)} ${filtered.length === 1 ? 'contato encontrado' : 'contatos encontrados'}</small></label>
          <div class="contacts-filter-row"><span>Filtrar por situação</span><${ScopeTabs} scope=${scope} setScope=${setScope} counts=${counts} assistantName=${assistantName}/></div>
          <div class="contacts-filter-row"><span>Filtrar por classificação da triagem</span><${FlagChips} flag=${flag} setFlag=${setFlag} counts=${flagCounts}/></div>
          <button type="button" class="contacts-block-toggle" onClick=${() => setBlockOpen(!blockOpen)}>${blockOpen ? 'Fechar' : 'Bloquear contato'}</button>
        </header>
        ${blockOpen ? html`<form class="contacts-block-form" onSubmit=${blockContact}>
          <label><span>Número ou nome</span><input value=${blockQuery} onInput=${(event) => setBlockQuery(event.target.value)} placeholder="Ex.: +55 11 99999-9999"/><small>${assistantName} deixará de receber novas mensagens desse contato.</small></label>
          <button type="submit" disabled=${!blockQuery.trim()}>Bloquear</button>
        </form>` : null}
        <div class="contacts-list" role="list">
          ${visible.map((contact) => html`<${ContactRow} key=${contact.chat_id} contact=${contact} active=${chatId === contact.chat_id} onSelect=${selectContact}/>`)}
          ${!visible.length && data ? html`<${Empty}>Nenhum contato corresponde à busca e aos filtros.</${Empty}>` : null}
          ${hasMore ? html`<div class="contacts-load-more"><button type="button" class="btn" onClick=${() => setVisibleCount((n) => n + PAGE_SIZE)}>Mostrar mais (${fmt.int(filtered.length - visible.length)} restantes)</button></div>` : null}
        </div>
      </div>
      <div class="contacts-detail">
        <${ContactDetail} chatId=${chatId} status=${status} assistantName=${assistantName} go=${go}
          unblock=${unblock} toggleAiAccess=${toggleAiAccess} blockOne=${blockOne} copyNumber=${copyNumber} onDeselect=${deselect}/>
      </div>
     </div>
    </section>
  </div>`;
}
