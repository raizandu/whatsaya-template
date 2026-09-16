// Contatos é uma tabela de pessoas (não de conversas): colunas, ordenação e
// escopos. A linha abre o atendimento do contato (#atendimento/<id>); a ficha
// completa (#lead/<id>) fica no menu. Os escopos que falam de IA leem o
// atendimento aberto que o servidor anexa a cada contato.
import { useEffect, useState } from 'preact/hooks';
import { html, useApi, post, fmt, ErrorBox, Empty, Menu, isAdmin as isAdminUser, normalize, dateTime, TRIAGE_STAGE_LABELS } from '../lib.js';

const PAGE_SIZE = 100;

const scopes = (assistantName) => [
  ['all', 'Todos'],
  ['attention', 'Pedem atenção'],
  ['aya', `Com a ${assistantName}`],
  ['human', 'Com humano'],
  ['sem_responsavel', 'Sem responsável'],
  ['legacy', 'Legado (IA desligada)'],
  ['reactivation', 'Reativação'],
  ['blocked', 'Bloqueados'],
];

const FLAGS = ['Lead', 'Cliente', 'Pessoal', 'Fornecedor/parceiro', 'Spam/irrelevante', 'Revisar'];

// Ordenação crescente por coluna; a direção inverte o sinal. Responsável ordena
// pelo tipo e depois pelo nome, para agrupar IA, Dono e cada atendente.
const responsavelKey = (contact) => (contact.atendimento
  ? `${contact.atendimento.responsavel_tipo}:${contact.atendimento.responsavel_nome || ''}` : '');
const SORTS = {
  name: (a, b) => a.name.localeCompare(b.name, 'pt-BR'),
  last: (a, b) => (a.last_at || 0) - (b.last_at || 0),
  stage: (a, b) => String(a.stage_label || '').localeCompare(String(b.stage_label || ''), 'pt-BR'),
  responsavel: (a, b) => responsavelKey(a).localeCompare(responsavelKey(b), 'pt-BR'),
};

const meetingPending = (contact) => Boolean(contact.meeting && contact.meeting.outcome_pending);
const needsAttention = (contact) => contact.human || contact.next_followup_rel === 'atrasado' || meetingPending(contact);
const responsavelTipo = (contact) => (contact.atendimento ? contact.atendimento.responsavel_tipo : null);

const inScope = (contact, scope) => {
  if (scope === 'attention') return needsAttention(contact) && contact.kind !== 'blocked';
  if (scope === 'aya') return contact.atendimento ? responsavelTipo(contact) === 'ia' : contact.automation && !contact.human;
  if (scope === 'human') return contact.human;
  if (scope === 'sem_responsavel') return responsavelTipo(contact) === 'nenhum';
  if (scope === 'legacy') return contact.kind === 'legacy';
  if (scope === 'reactivation') return contact.kind === 'reactivation';
  if (scope === 'blocked') return contact.kind === 'blocked';
  return true;
};

function responsavelText(contact, assistantName) {
  const atd = contact.atendimento;
  if (!atd) return '';
  if (atd.responsavel_tipo === 'ia') return assistantName;
  if (atd.responsavel_tipo === 'dono') return 'Dono';
  if (atd.responsavel_tipo === 'atendente') return atd.responsavel_nome || atd.responsavel_user || '';
  return 'Sem responsável';
}

const aiTone = (contact) => {
  if (contact.kind === 'blocked') return 'blocked';
  if (contact.human) return 'human';
  if (meetingPending(contact)) return 'attention';
  if (contact.ai && contact.ai.enabled) return 'aya';
  return 'paused';
};

const aiLabel = (contact, assistantName) => {
  if (meetingPending(contact)) return 'Reunião sem status';
  const label = contact.ai ? contact.ai.label : '…';
  // O backend fixa "AYA" no rótulo padrão (_AI_LABEL["on"] em panel/data.py).
  return label.replace(/^AYA\b/, assistantName);
};

const nextStepText = (contact) => {
  if (meetingPending(contact)) return 'Confirmar comparecimento';
  if (contact.meeting && contact.meeting.start && new Date(contact.meeting.start) > new Date()) {
    return `Reunião ${dateTime(contact.meeting.start)}`;
  }
  return (contact.triage && contact.triage.next_action) || contact.next_followup || 'Não agendado';
};

function Avatar({ contact }) {
  return html`<span class="contacts-avatar">${fmt.initials(contact.name)}</span>`;
}

function AiStatus({ contact, assistantName }) {
  return html`<span class=${`contacts-status ${aiTone(contact)}`}><span></span>${aiLabel(contact, assistantName)}</span>`;
}

function Responsavel({ contact, assistantName }) {
  const atd = contact.atendimento;
  if (!atd) return html`<span class="contacts-preview">—</span>`;
  const tone = atd.responsavel_tipo === 'nenhum' ? 'orange' : atd.responsavel_tipo === 'ia' ? 'mint' : '';
  return html`<div>
    <span class=${`tag ${tone}`}>${responsavelText(contact, assistantName)}</span>
    ${atd.aguardando_nos ? html`<small class="contacts-preview">aguardando nós</small>` : null}
  </div>`;
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
  const late = contact.next_followup_rel === 'atrasado' || meetingPending(contact);
  return html`<span class=${late ? 'contacts-due late' : 'contacts-due'}>${nextStepText(contact)}</span>`;
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
const openAtendimento = (go, contact) => go(`atendimento/${encodeURIComponent(contact.chat_id)}`);

// Menu de ações por linha (receita do DS). Bloqueio e acesso da IA são só de
// admin — o servidor já nega para atendente, isto só evita oferecer o que
// seria recusado.
function rowActions({ contact, go, unblock, toggleAiAccess, blockOne, copyNumber, isAdmin }) {
  if (contact.kind === 'blocked') {
    const items = [{ label: 'Copiar número', icon: 'copy', onClick: () => copyNumber(contact) }];
    if (isAdmin) items.push('separator', { label: 'Desbloquear contato', icon: 'unlock', onClick: () => unblock(contact) });
    return items;
  }
  const aiOn = Boolean(contact.ai && contact.ai.enabled);
  const items = [
    { label: 'Abrir atendimento', icon: 'headset', onClick: () => openAtendimento(go, contact) },
    { label: 'Ficha do lead', icon: 'expand', onClick: () => go(`lead/${encodeURIComponent(contact.chat_id)}`) },
    { label: 'Abrir no WhatsApp', icon: 'paper-plane', href: `https://wa.me/${phoneOf(contact.chat_id)}` },
    { label: 'Copiar número', icon: 'copy', onClick: () => copyNumber(contact) },
  ];
  if (isAdmin) {
    items.push('separator', { label: aiOn ? 'Desligar IA neste contato' : 'Liberar IA neste contato', icon: aiOn ? 'pause' : 'play', onClick: () => toggleAiAccess(contact) });
    items.push('separator', { label: 'Bloquear contato', icon: 'ban', danger: true, onClick: () => blockOne(contact) });
  }
  return items;
}

function SortTh({ id, label, sort, setSort }) {
  const active = sort.key === id;
  return html`<th aria-sort=${active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : null}>
    <button type="button" class=${`contacts-sort${active ? ' active' : ''}`} onClick=${() => setSort({ key: id, dir: active && sort.dir === 'asc' ? 'desc' : 'asc' })}>${label}${active ? html`<span aria-hidden="true">${sort.dir === 'asc' ? ' ↑' : ' ↓'}</span>` : null}</button>
  </th>`;
}

function DesktopTable({ contacts, go, unblock, toggleAiAccess, blockOne, copyNumber, isAdmin, assistantName, sort, setSort }) {
  return html`<div class="contacts-table-group">
    <table class="contacts-table contacts-table--directory">
      <thead><tr>
        <${SortTh} id="name" label="Contato" sort=${sort} setSort=${setSort}/>
        <${SortTh} id="stage" label="Classificação" sort=${sort} setSort=${setSort}/>
        <${SortTh} id="responsavel" label="Responsável" sort=${sort} setSort=${setSort}/>
        <th>IA</th>
        <${SortTh} id="last" label="Última conversa" sort=${sort} setSort=${setSort}/>
        <th>Próximo passo</th><th></th>
      </tr></thead>
      <tbody>${contacts.map((contact) => html`<tr key=${contact.chat_id} class=${contact.kind === 'blocked' ? 'is-blocked' : 'is-link'} onClick=${contact.kind === 'blocked' ? null : () => openAtendimento(go, contact)}>
        <td><div class="contacts-person"><${Avatar} contact=${contact}/><span><b>${contact.name}</b><small>${contact.phone}</small></span></div></td>
        <td><${Classification} contact=${contact}/></td>
        <td><${Responsavel} contact=${contact} assistantName=${assistantName}/></td>
        <td><${AiStatus} contact=${contact} assistantName=${assistantName}/></td>
        <td>
          <b class="contacts-last">${contact.last || '—'}</b>
          ${contact.last_historical ? html`<span class="tag">histórico</span>` : null}
          <small class="contacts-preview">${contact.preview || 'Sem mensagem recente'}</small>
        </td>
        <td><${NextStep} contact=${contact}/></td>
        <td class="contacts-actions-cell" onClick=${(event) => event.stopPropagation()}><${Menu} label=${`Ações para ${contact.name}`} size="sm" items=${rowActions({ contact, go, unblock, toggleAiAccess, blockOne, copyNumber, isAdmin })}/></td>
      </tr>`)}</tbody>
    </table>
  </div>`;
}

function MobileList({ contacts, go, unblock, toggleAiAccess, isAdmin, assistantName }) {
  return html`<div class="contacts-mobile-group">
    ${contacts.map((contact) => html`<article class=${`contacts-record ${needsAttention(contact) && contact.kind !== 'blocked' ? 'urgent' : ''}`} key=${contact.chat_id}>
      <div class="contacts-record-main">
        <${Avatar} contact=${contact}/>
        <div><b>${contact.name}</b><small>${contact.phone}</small></div>
        ${contact.triage ? html`<span class="contacts-stage">${contact.triage.flag}</span>` : contact.stage_label ? html`<span class="contacts-stage">${contact.stage_label}</span>` : null}
      </div>
      <p>${contact.preview || 'Sem mensagem recente'}</p>
      <div class="contacts-record-facts">
        <${AiStatus} contact=${contact} assistantName=${assistantName}/>
        <span><small>Responsável</small><b>${responsavelText(contact, assistantName) || '—'}</b></span>
        <span><small>Última conversa</small><b>${contact.last || '—'}${contact.last_historical ? ' · histórico' : ''}</b></span>
        <span><small>Próximo passo</small><b>${nextStepText(contact)}</b></span>
      </div>
      ${contact.kind === 'blocked'
        ? (isAdmin ? html`<button type="button" class="contacts-primary-action secondary" onClick=${() => unblock(contact)}>Desbloquear contato</button>` : null)
        : html`<button type="button" class="contacts-primary-action" onClick=${() => openAtendimento(go, contact)}>Abrir atendimento <span>→</span></button>`}
      ${contact.kind !== 'blocked' && isAdmin ? html`<button type="button" class="contacts-primary-action secondary" onClick=${() => toggleAiAccess(contact)}>${contact.ai && contact.ai.enabled ? 'Desligar IA' : 'Liberar IA'}</button>` : null}
    </article>`)}
  </div>`;
}

export default function Contacts({ assistantName = 'AYA', setToast, go, me }) {
  const isAdmin = isAdminUser(me);
  const resource = useApi('/api/contacts', { every: 30000 });
  const data = resource.data;
  const contacts = data ? data.contacts : [];
  const counts = (data && data.counts) || {};
  const flagCounts = (data && data.flags) || {};

  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('all');
  const [flag, setFlag] = useState('');
  const [sort, setSort] = useState({ key: 'last', dir: 'desc' });
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [blockOpen, setBlockOpen] = useState(false);
  const [blockQuery, setBlockQuery] = useState('');

  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [scope, flag, query, sort]);

  const needle = normalize(query.trim());
  const filtered = contacts.filter((contact) => {
    if (!inScope(contact, scope)) return false;
    if (flag && !(contact.triage && contact.triage.flag === flag)) return false;
    if (!needle) return true;
    return normalize([
      contact.name, contact.phone, contact.preview, contact.triage && contact.triage.summary,
    ].join(' ')).includes(needle);
  });
  const sorted = [...filtered].sort((a, b) => (SORTS[sort.key] || SORTS.last)(a, b) * (sort.dir === 'asc' ? 1 : -1));
  const visible = sorted.slice(0, visibleCount);
  const hasMore = sorted.length > visible.length;

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

  const rowProps = { go, unblock, toggleAiAccess, blockOne, copyNumber, isAdmin, assistantName };
  return html`<div class="contacts-page">
    <${ErrorBox} error=${resource.error}/>
    <section class="contacts-metrics five" aria-label="Resumo dos contatos">
      <div><span>Base total</span><b>${data ? fmt.int(counts.all || 0) : '…'}</b><small>contatos no diretório</small></div>
      <div><span>Com a ${assistantName}</span><b>${data ? fmt.int(counts.aya || 0) : '…'}</b><small>atendimento com a IA</small></div>
      <div><span>Com humano</span><b>${data ? fmt.int(counts.human || 0) : '…'}</b><small>atendente ou Dono</small></div>
      <div><span>Pedem atenção</span><b>${data ? fmt.int(counts.attention || 0) : '…'}</b><small>reunião, ação ou toque vencido</small></div>
      <div><span>Bloqueados</span><b>${data ? fmt.int(counts.blocked || 0) : '…'}</b><small>fora do atendimento</small></div>
    </section>

    <section class="contacts-surface">
      <header class="contacts-toolbar">
        <div class="contacts-toolbar-heading"><span class="kpi-eyebrow">Base comercial</span><h2>Todos os contatos</h2><p>Procure pessoas; a linha abre o atendimento.</p></div>
        <div class="contacts-toolbar-tools">
          <label class="contacts-search"><span>Buscar contatos</span><div><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/></div><small>${fmt.int(filtered.length)} ${filtered.length === 1 ? 'contato encontrado' : 'contatos encontrados'}</small></label>
          <div class="contacts-filter-row contacts-filter-row--scope"><span>Filtrar por situação</span><${ScopeTabs} scope=${scope} setScope=${setScope} counts=${counts} assistantName=${assistantName}/></div>
          <div class="contacts-filter-row contacts-filter-row--flags"><span>Filtrar por classificação da triagem</span><${FlagChips} flag=${flag} setFlag=${setFlag} counts=${flagCounts}/></div>
          ${isAdmin ? html`<button type="button" class="contacts-block-toggle" onClick=${() => setBlockOpen(!blockOpen)}>${blockOpen ? 'Fechar' : 'Bloquear contato'}</button>` : null}
        </div>
      </header>
      ${isAdmin && blockOpen ? html`<form class="contacts-block-form" onSubmit=${blockContact}>
        <label><span>Número ou nome</span><input value=${blockQuery} onInput=${(event) => setBlockQuery(event.target.value)} placeholder="Ex.: +55 11 99999-9999"/><small>${assistantName} deixará de receber novas mensagens desse contato.</small></label>
        <button type="submit" disabled=${!blockQuery.trim()}>Bloquear</button>
      </form>` : null}
      ${visible.length ? html`<div class="contacts-desktop-groups"><${DesktopTable} contacts=${visible} sort=${sort} setSort=${setSort} ...${rowProps}/></div>` : null}
      ${visible.length ? html`<div class="contacts-mobile-groups"><${MobileList} contacts=${visible} go=${go} unblock=${unblock} toggleAiAccess=${toggleAiAccess} isAdmin=${isAdmin} assistantName=${assistantName}/></div>` : null}
      ${!visible.length && data ? html`<${Empty}>Nenhum contato corresponde à busca e aos filtros.</${Empty}>` : null}
      ${hasMore ? html`<div class="contacts-load-more"><button type="button" class="btn" onClick=${() => setVisibleCount((n) => n + PAGE_SIZE)}>Mostrar mais (${fmt.int(sorted.length - visible.length)} restantes)</button></div>` : null}
    </section>
  </div>`;
}
