import { useEffect, useState } from 'preact/hooks';
import { html, useApi, post, fmt, ErrorBox, Empty } from '../lib.js';

const PAGE_SIZE = 100;

const SCOPES = [
  ['all', 'Todos'],
  ['attention', 'Pedem atenção'],
  ['aya', 'AYA atendendo'],
  ['legacy', 'Legado (IA desligada)'],
  ['reactivation', 'Reativação'],
  ['blocked', 'Bloqueados'],
];

const FLAGS = ['Lead', 'Cliente', 'Pessoal', 'Fornecedor/parceiro', 'Spam/irrelevante', 'Revisar'];

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

const normalize = (value) => String(value || '')
  .normalize('NFD')
  .replace(/\p{M}/gu, '')
  .toLocaleLowerCase('pt-BR');

const inScope = (contact, scope) => {
  if (scope === 'attention') return contact.human || contact.next_followup_rel === 'atrasado';
  if (scope === 'aya') return contact.automation && !contact.human;
  if (scope === 'legacy') return contact.kind === 'legacy';
  if (scope === 'reactivation') return contact.kind === 'reactivation';
  if (scope === 'blocked') return contact.kind === 'blocked';
  return true;
};

const aiTone = (contact) => {
  if (contact.kind === 'blocked') return 'blocked';
  if (contact.human) return 'human';
  if (contact.ai && contact.ai.enabled) return 'aya';
  return 'paused';
};

const nextStepText = (contact) => (contact.triage && contact.triage.next_action) || contact.next_followup || 'Não agendado';

function Avatar({ contact }) {
  return html`<span class="contacts-avatar">${fmt.initials(contact.name)}</span>`;
}

function AiStatus({ contact }) {
  return html`<span class=${`contacts-status ${aiTone(contact)}`}><span></span>${contact.ai ? contact.ai.label : '…'}</span>`;
}

function Classification({ contact }) {
  const flagText = contact.triage ? contact.triage.flag : null;
  const stageText = contact.triage
    ? (TRIAGE_STAGE_LABELS[contact.triage.stage] || contact.triage.stage || null)
    : (contact.stage_label || null);
  if (!flagText && !stageText) return html`<span class="contacts-preview">—</span>`;
  return html`<div>
    <span class="contacts-stage">${flagText || stageText}</span>
    ${flagText && stageText ? html`<small class="contacts-preview">${stageText}</small>` : null}
  </div>`;
}

function NextStep({ contact }) {
  const late = contact.next_followup_rel === 'atrasado';
  return html`<span class=${late ? 'contacts-due late' : 'contacts-due'}>${nextStepText(contact)}</span>`;
}

function ScopeTabs({ scope, setScope, counts }) {
  return html`<div class="contacts-scopes" role="group" aria-label="Filtrar por situação">
    ${SCOPES.map(([id, label]) => html`<button key=${id} type="button" class=${scope === id ? 'active' : ''} onClick=${() => setScope(id)}>
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

function RowActions({ contact, go, unblock, toggleAiAccess }) {
  const open = html`<button type="button" class="contacts-text-action" onClick=${() => go(`lead/${encodeURIComponent(contact.chat_id)}`)}>Ver conversa →</button>`;
  if (contact.kind === 'blocked') {
    return html`<div class="contacts-row-actions">${open}<button type="button" class="contacts-text-action" onClick=${() => unblock(contact)}>Desbloquear</button></div>`;
  }
  return html`<div class="contacts-row-actions">${open}<button type="button" class="contacts-text-action" onClick=${() => toggleAiAccess(contact)}>${contact.ai && contact.ai.enabled ? 'Desligar IA' : 'Liberar IA'}</button></div>`;
}

function DesktopTable({ contacts, go, unblock, toggleAiAccess }) {
  return html`<div class="contacts-table-group">
    <table class="contacts-table contacts-table--directory">
      <thead><tr><th>Contato</th><th>Classificação</th><th>IA</th><th>Última conversa</th><th>Próximo passo</th><th></th></tr></thead>
      <tbody>${contacts.map((contact) => html`<tr key=${contact.chat_id}>
        <td><div class="contacts-person"><${Avatar} contact=${contact}/><span><b>${contact.name}</b><small>${contact.phone}</small></span></div></td>
        <td><${Classification} contact=${contact}/></td>
        <td><${AiStatus} contact=${contact}/></td>
        <td>
          <b class="contacts-last">${contact.last || '—'}</b>
          ${contact.last_historical ? html`<span class="tag">histórico</span>` : null}
          <small class="contacts-preview">${contact.preview || 'Sem mensagem recente'}</small>
        </td>
        <td><${NextStep} contact=${contact}/></td>
        <td><${RowActions} contact=${contact} go=${go} unblock=${unblock} toggleAiAccess=${toggleAiAccess}/></td>
      </tr>`)}</tbody>
    </table>
  </div>`;
}

function MobileList({ contacts, go, unblock, toggleAiAccess }) {
  return html`<div class="contacts-mobile-group">
    ${contacts.map((contact) => html`<article class="contacts-record" key=${contact.chat_id}>
      <div class="contacts-record-main">
        <${Avatar} contact=${contact}/>
        <div><b>${contact.name}</b><small>${contact.phone}</small></div>
        ${contact.triage ? html`<span class="contacts-stage">${contact.triage.flag}</span>` : contact.stage_label ? html`<span class="contacts-stage">${contact.stage_label}</span>` : null}
      </div>
      <p>${contact.preview || 'Sem mensagem recente'}</p>
      <div class="contacts-record-facts">
        <${AiStatus} contact=${contact}/>
        <span><small>Última conversa</small><b>${contact.last || '—'}${contact.last_historical ? ' · histórico' : ''}</b></span>
        <span><small>Próximo passo</small><b>${nextStepText(contact)}</b></span>
      </div>
      <button type="button" class="contacts-primary-action" onClick=${() => go(`lead/${encodeURIComponent(contact.chat_id)}`)}>Ver conversa <span>→</span></button>
      ${contact.kind === 'blocked'
        ? html`<button type="button" class="contacts-primary-action secondary" onClick=${() => unblock(contact)}>Desbloquear contato</button>`
        : html`<button type="button" class="contacts-primary-action secondary" onClick=${() => toggleAiAccess(contact)}>${contact.ai && contact.ai.enabled ? 'Desligar IA' : 'Liberar IA'}</button>`}
    </article>`)}
  </div>`;
}

export default function Contacts({ setToast, go }) {
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

  return html`<div class="contacts-page">
    <${ErrorBox} error=${resource.error}/>
    <section class="contacts-metrics five" aria-label="Resumo dos contatos">
      <div><span>Base total</span><b>${data ? fmt.int(counts.all || 0) : '…'}</b><small>contatos no diretório</small></div>
      <div><span>Legado (IA desligada)</span><b>${data ? fmt.int(counts.legacy || 0) : '…'}</b><small>histórico importado</small></div>
      <div><span>AYA atendendo</span><b>${data ? fmt.int(counts.aya || 0) : '…'}</b><small>automação ativa</small></div>
      <div><span>Pedem atenção</span><b>${data ? fmt.int(counts.attention || 0) : '…'}</b><small>ação ou toque vencido</small></div>
      <div><span>Bloqueados</span><b>${data ? fmt.int(counts.blocked || 0) : '…'}</b><small>fora do atendimento</small></div>
    </section>

    <section class="contacts-surface">
      <header class="contacts-toolbar">
        <div class="contacts-toolbar-heading"><span class="kpi-eyebrow">Base comercial</span><h2>Todos os contatos</h2><p>Contexto essencial antes de abrir a conversa.</p></div>
        <div class="contacts-toolbar-tools">
          <label class="contacts-search"><span>Buscar contatos</span><div><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/></div><small>${fmt.int(filtered.length)} ${filtered.length === 1 ? 'contato encontrado' : 'contatos encontrados'}</small></label>
          <div class="contacts-filter-row contacts-filter-row--scope"><span>Filtrar por situação</span><${ScopeTabs} scope=${scope} setScope=${setScope} counts=${counts}/></div>
          <div class="contacts-filter-row contacts-filter-row--flags"><span>Filtrar por classificação da triagem</span><${FlagChips} flag=${flag} setFlag=${setFlag} counts=${flagCounts}/></div>
          <button type="button" class="contacts-block-toggle" onClick=${() => setBlockOpen(!blockOpen)}>${blockOpen ? 'Fechar' : 'Bloquear contato'}</button>
        </div>
      </header>
      ${blockOpen ? html`<form class="contacts-block-form" onSubmit=${blockContact}>
        <label><span>Número ou nome</span><input value=${blockQuery} onInput=${(event) => setBlockQuery(event.target.value)} placeholder="Ex.: +55 11 99999-9999"/><small>A AYA deixará de receber novas mensagens desse contato.</small></label>
        <button type="submit" disabled=${!blockQuery.trim()}>Bloquear</button>
      </form>` : null}
      ${visible.length ? html`<div class="contacts-desktop-groups"><${DesktopTable} contacts=${visible} go=${go} unblock=${unblock} toggleAiAccess=${toggleAiAccess}/></div>` : null}
      ${visible.length ? html`<div class="contacts-mobile-groups"><${MobileList} contacts=${visible} go=${go} unblock=${unblock} toggleAiAccess=${toggleAiAccess}/></div>` : null}
      ${!visible.length && data ? html`<${Empty}>Nenhum contato corresponde à busca e aos filtros.</${Empty}>` : null}
      ${hasMore ? html`<div class="contacts-load-more"><button type="button" class="btn" onClick=${() => setVisibleCount((n) => n + PAGE_SIZE)}>Mostrar mais (${fmt.int(filtered.length - visible.length)} restantes)</button></div>` : null}
    </section>
  </div>`;
}
