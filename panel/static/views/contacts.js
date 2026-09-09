import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, ErrorBox, Empty } from '../lib.js';

const SCOPE_LABELS = {
  all: 'Todos',
  attention: 'Pedem atenção',
  human: 'Com humano',
  blocked: 'Bloqueados',
};

const normalize = (value) => String(value || '')
  .normalize('NFD')
  .replace(/\p{M}/gu, '')
  .toLocaleLowerCase('pt-BR');

const contactStatus = (contact, assistantName = 'Atendimento') => {
  if (contact.kind === 'blocked') return { id: 'blocked', label: 'Bloqueado' };
  if (contact.human) return { id: 'human', label: 'Com humano' };
  if (contact.next_followup_rel === 'atrasado') return { id: 'attention', label: 'Follow-up vencido' };
  if (contact.automation) return { id: 'aya', label: `${assistantName} atendendo` };
  return { id: 'paused', label: 'Follow-up pausado' };
};

const estimatedValue = (contact) => contact.estimated_value_cents == null
  ? 'A definir'
  : fmt.brl(contact.estimated_value_cents / 100);

function Status({ contact, assistantName }) {
  const status = contactStatus(contact, assistantName);
  return html`<span class=${`contacts-status ${status.id}`}><span></span>${status.label}</span>`;
}

function Avatar({ contact }) {
  return html`<span class="contacts-avatar">${fmt.initials(contact.name)}</span>`;
}

function Scopes({ scope, setScope, counts }) {
  return html`<div class="contacts-scopes" role="group" aria-label="Filtrar contatos">
    ${Object.entries(SCOPE_LABELS).map(([id, label]) => html`<button type="button" class=${scope === id ? 'active' : ''} onClick=${() => setScope(id)}>
      ${label}<b>${counts[id]}</b>
    </button>`)}
  </div>`;
}

function GroupHeader({ title, sub, tone, count }) {
  return html`<header class="contacts-group-head"><span class=${`contacts-group-mark ${tone}`}></span><div><h3>${title}</h3><p>${sub}</p></div><b>${count}</b></header>`;
}

function Value({ contact, go }) {
  const pending = contact.estimated_value_cents == null;
  return html`<button type="button" class=${`contacts-value ${pending ? 'pending' : ''}`} onClick=${() => go(`lead/${encodeURIComponent(contact.chat_id)}`)}>
    ${estimatedValue(contact)}
  </button>`;
}

function DesktopGroup({ group, go, unblock, assistantName }) {
  return html`<section class="contacts-table-group">
    <${GroupHeader} title=${group.title} sub=${group.sub} tone=${group.tone} count=${group.items.length}/>
    <table class="contacts-table">
      <thead><tr><th>Contato</th><th>Etapa</th><th>Valor estimado</th><th>Situação</th><th>Última conversa</th><th>Próximo passo</th><th>Responsável</th><th></th></tr></thead>
      <tbody>${group.items.map((contact) => html`<tr key=${contact.chat_id}>
        <td><div class="contacts-person"><${Avatar} contact=${contact}/><span><b>${contact.name}</b><small>${contact.phone}</small></span></div></td>
        <td><span class="contacts-stage">${contact.stage_label}</span></td>
        <td>${contact.kind === 'blocked' ? '—' : html`<${Value} contact=${contact} go=${go}/>`}</td>
        <td><${Status} contact=${contact} assistantName=${assistantName}/></td>
        <td><b class="contacts-last">${contact.last || '—'}</b><small class="contacts-preview">${contact.preview || contact.reason || 'Sem mensagem recente'}</small></td>
        <td><span class=${contact.next_followup_rel === 'atrasado' ? 'contacts-due late' : 'contacts-due'}>${contact.next_followup || 'Não agendado'}</span></td>
        <td>${contact.human ? 'Você' : contact.kind === 'blocked' ? '—' : assistantName}</td>
        <td>${contact.kind === 'blocked'
          ? html`<button type="button" class="contacts-text-action" onClick=${() => unblock(contact)}>Desbloquear</button>`
          : html`<button type="button" class="contacts-text-action" onClick=${() => go(`lead/${encodeURIComponent(contact.chat_id)}`)}>Ver conversa →</button>`}</td>
      </tr>`)}</tbody>
    </table>
  </section>`;
}

function MobileGroup({ group, go, unblock, assistantName }) {
  return html`<section class="contacts-mobile-group">
    <${GroupHeader} title=${group.title} sub=${group.sub} tone=${group.tone} count=${group.items.length}/>
    ${group.items.map((contact) => html`<article class=${`contacts-record ${contactStatus(contact, assistantName).id === 'attention' ? 'urgent' : ''}`} key=${contact.chat_id}>
      <div class="contacts-record-main"><${Avatar} contact=${contact}/><div><b>${contact.name}</b><small>${contact.phone}</small></div><span class="contacts-stage">${contact.stage_label}</span></div>
      <p>${contact.preview || contact.reason || 'Sem mensagem recente'}</p>
      <div class="contacts-record-facts">
        <${Status} contact=${contact} assistantName=${assistantName}/>
        ${contact.kind === 'blocked' ? null : html`<span class="contacts-record-value"><small>Valor estimado</small><b class=${contact.estimated_value_cents == null ? 'pending' : ''}>${estimatedValue(contact)}</b></span>`}
        <span><small>Último contato</small><b>${contact.last || '—'}</b></span>
        <span><small>Próximo passo</small><b>${contact.next_followup || 'Não agendado'}</b></span>
      </div>
      ${contact.kind === 'blocked'
        ? html`<button type="button" class="contacts-primary-action secondary" onClick=${() => unblock(contact)}>Desbloquear contato</button>`
        : html`<button type="button" class="contacts-primary-action" onClick=${() => go(`lead/${encodeURIComponent(contact.chat_id)}`)}>Ver conversa <span>→</span></button>`}
    </article>`)}
  </section>`;
}

export default function Contacts({ setToast, go, config }) {
  const leads = useApi('/api/leads', { every: 30000 });
  const blocked = useApi('/api/blocked', { every: 30000 });
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('all');
  const [blockOpen, setBlockOpen] = useState(false);
  const [blockQuery, setBlockQuery] = useState('');
  const assistantName = (config && config.assistant_name) || 'Atendimento';
  const active = leads.data ? leads.data.stages.flatMap((stage) => stage.cards.map((contact) => ({
    ...contact,
    kind: 'active',
    stage_label: stage.label,
  }))) : [];
  const blockedContacts = blocked.data ? blocked.data.blocked.map((contact) => ({
    ...contact,
    kind: 'blocked',
    stage_label: 'Bloqueado',
    last: '',
    preview: '',
    next_followup: '',
  })) : [];
  const attention = active.filter((contact) => contact.human || contact.next_followup_rel === 'atrasado');
  const counts = {
    all: active.length,
    attention: attention.length,
    human: active.filter((contact) => contact.human).length,
    blocked: blockedContacts.length,
  };
  const source = scope === 'blocked' ? blockedContacts : active.filter((contact) => {
    if (scope === 'attention') return contact.human || contact.next_followup_rel === 'atrasado';
    if (scope === 'human') return contact.human;
    return true;
  });
  const needle = normalize(query.trim());
  const visible = source.filter((contact) => !needle || normalize([
    contact.name, contact.phone, contact.preview, contact.reason, contact.stage_label,
  ].join(' ')).includes(needle));
  const attentionVisible = visible.filter((contact) => contact.kind !== 'blocked' && (contact.human || contact.next_followup_rel === 'atrasado'));
  const groups = scope === 'blocked'
    ? [{ title: 'Contatos bloqueados', sub: `${assistantName} ignora novas mensagens desses números`, tone: 'dark', items: visible }].filter((group) => group.items.length)
    : [
        { title: 'Pedem atenção', sub: 'Decisão humana ou follow-up vencido', tone: 'orange', items: attentionVisible },
        { title: 'Operação fluindo', sub: `${assistantName} conduzindo ou nutrindo o contato`, tone: 'green', items: visible.filter((contact) => !attentionVisible.includes(contact)) },
      ].filter((group) => group.items.length);

  const blockContact = async (event) => {
    event.preventDefault();
    if (!blockQuery.trim()) return;
    try {
      await post('/api/actions/block', { query: blockQuery.trim() });
      setToast(`Bloqueado: ${blockQuery.trim()}`);
      setBlockQuery('');
      setBlockOpen(false);
      blocked.reload();
      leads.reload();
    } catch (err) {
      setToast(`Não bloqueei: ${err.message}`);
    }
  };

  const unblock = async (contact) => {
    try {
      await post('/api/actions/unblock', { chat_id: contact.chat_id });
      setToast(`${contact.name} liberado. A conversa anterior da IA será arquivada.`);
      blocked.reload();
      leads.reload();
    } catch (err) {
      setToast(`Não desbloqueei: ${err.message}`);
    }
  };

  return html`<div class="contacts-page">
    <${ErrorBox} error=${leads.error || blocked.error}/>
    <section class="contacts-metrics" aria-label="Resumo dos contatos">
      <div><span>Base ativa</span><b>${leads.data ? fmt.int(active.length) : '…'}</b><small>leads no funil</small></div>
      <div><span>Pedem atenção</span><b>${leads.data ? fmt.int(attention.length) : '…'}</b><small>ação ou toque vencido</small></div>
      <div><span>${assistantName} atendendo</span><b>${leads.data ? fmt.int(active.filter((contact) => contact.automation && !contact.human).length) : '…'}</b><small>automação ativa</small></div>
      <div><span>Bloqueados</span><b>${blocked.data ? fmt.int(blockedContacts.length) : '…'}</b><small>fora do atendimento</small></div>
    </section>

    <section class="contacts-surface">
      <header class="contacts-toolbar">
        <div class="contacts-toolbar-heading"><span class="kpi-eyebrow">Base comercial</span><h2>Todos os contatos</h2><p>Contexto essencial antes de abrir a conversa.</p></div>
        <div class="contacts-toolbar-tools">
          <label class="contacts-search"><span>Buscar contatos</span><div><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/></div><small>${visible.length} ${visible.length === 1 ? 'contato encontrado' : 'contatos encontrados'}</small></label>
          <div class="contacts-filter-row"><span>Filtrar por situação</span><${Scopes} scope=${scope} setScope=${setScope} counts=${counts}/></div>
          <button type="button" class="contacts-block-toggle" onClick=${() => setBlockOpen(!blockOpen)}>${blockOpen ? 'Fechar' : 'Bloquear contato'}</button>
        </div>
      </header>
      ${blockOpen ? html`<form class="contacts-block-form" onSubmit=${blockContact}>
        <label><span>Número ou nome</span><input value=${blockQuery} onInput=${(event) => setBlockQuery(event.target.value)} placeholder="Ex.: +55 11 99999-9999"/><small>${assistantName} deixará de receber novas mensagens desse contato.</small></label>
        <button type="submit" disabled=${!blockQuery.trim()}>Bloquear</button>
      </form>` : null}
      ${groups.length ? html`<div class="contacts-desktop-groups">${groups.map((group) => html`<${DesktopGroup} group=${group} go=${go} unblock=${unblock} assistantName=${assistantName}/>` )}</div>` : null}
      ${groups.length ? html`<div class="contacts-mobile-groups">${groups.map((group) => html`<${MobileGroup} group=${group} go=${go} unblock=${unblock} assistantName=${assistantName}/>` )}</div>` : null}
      ${!groups.length && (leads.data || blocked.data) ? html`<${Empty}>Nenhum contato corresponde à busca e aos filtros.</${Empty}>` : null}
    </section>
  </div>`;
}
