// Tickets de toda a carteira: fila por prioridade, filtros por status e
// cliente, abertura e acompanhamento com linha do tempo. O mesmo ticket
// aparece na aba da ficha do cliente; aqui é a visão transversal.
import { useState } from 'preact/hooks';
import { html, useApi, post, Card, ErrorBox, Empty } from '../lib.js';

const DONE = ['resolved', 'closed'];
const PRIORITY_TONE = { critical: 'orange', high: 'orange', medium: 'amber', low: '' };
const stamp = (iso) => iso
  ? new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '';
const civil = (iso) => iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('pt-BR') : '';
const labelsOf = (config) => (config && config.management && config.management.labels) || {};

function Select({ value, options, onChange, allowEmpty = false, emptyLabel = '—' }) {
  return html`<select class="input" value=${value || ''} onChange=${(e) => onChange(e.target.value)}>
    ${allowEmpty ? html`<option value="">${emptyLabel}</option>` : null}
    ${Object.entries(options || {}).map(([id, label]) => html`<option key=${id} value=${id}>${label}</option>`)}
  </select>`;
}

function StatusForm({ ticket, labels, act }) {
  const [status, setStatus] = useState('');
  const [resolution, setResolution] = useState('');
  const [note, setNote] = useState('');
  const closing = DONE.includes(status);
  const submit = async (event) => {
    event.preventDefault();
    if (!status) return;
    await act('ticket-status', { id: ticket.id, status, note: note || undefined, resolution: closing ? resolution : undefined },
      `Ticket #${ticket.id} em ${labels.ticket_status[status]}`);
    setStatus(''); setResolution(''); setNote('');
  };
  return html`<form class="mg-status-form" onSubmit=${submit}>
    <select class="input" value=${status} onChange=${(e) => setStatus(e.target.value)}>
      <option value="">Mudar status…</option>
      ${Object.entries(labels.ticket_status).filter(([id]) => id !== ticket.status).map(([id, label]) => html`<option key=${id} value=${id}>${label}</option>`)}
    </select>
    ${closing && !ticket.resolution ? html`<input class="input" placeholder="Resolução (obrigatória)" value=${resolution} onInput=${(e) => setResolution(e.target.value)} required/>` : null}
    <input class="input" placeholder="Nota (opcional)" value=${note} onInput=${(e) => setNote(e.target.value)}/>
    <button class="btn sm" type="submit" disabled=${!status}>Aplicar</button>
  </form>`;
}

function TicketDetail({ ticketId, labels, act, go, clients }) {
  const resource = useApi(`/api/management/ticket/${ticketId}`);
  const t = resource.data;
  const [comment, setComment] = useState('');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);
  if (resource.error) return html`<${ErrorBox} error=${resource.error}/>`;
  if (!t) return html`<div class="mg-muted">Carregando…</div>`;

  const send = async (action, body, ok) => { await act(action, body, ok); await resource.reload(); };
  const addComment = async (event) => {
    event.preventDefault();
    if (!comment.trim()) return;
    await send('ticket-comment', { id: t.id, note: comment }, 'Comentário registrado');
    setComment('');
  };
  const startEdit = () => {
    setForm({ title: t.title, description: t.description || '', kind: t.kind, priority: t.priority, origin: t.origin,
      due_on: t.due_on || '', client_id: t.client_id ? String(t.client_id) : '', resolution: t.resolution || '' });
    setEditing(true);
  };
  const saveEdit = async (event) => {
    event.preventDefault();
    await send('ticket-update', { id: t.id, ...form, client_id: form.client_id ? Number(form.client_id) : null, due_on: form.due_on || null }, 'Ticket salvo');
    setEditing(false);
  };
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  return html`<div class="mg-ticket-detail">
    ${editing ? html`<form class="mg-form" onSubmit=${saveEdit}>
      <label class="field-label">Título<input class="input" value=${form.title} onInput=${set('title')} required/></label>
      <div class="mg-form-grid">
        <label class="field-label">Cliente<${Select} value=${form.client_id} options=${clients} allowEmpty=${true} emptyLabel="Interno (sem cliente)" onChange=${(v) => setForm((f) => ({ ...f, client_id: v }))}/></label>
        <label class="field-label">Tipo<${Select} value=${form.kind} options=${labels.ticket_kind} onChange=${(v) => setForm((f) => ({ ...f, kind: v }))}/></label>
        <label class="field-label">Prioridade<${Select} value=${form.priority} options=${labels.ticket_priority} onChange=${(v) => setForm((f) => ({ ...f, priority: v }))}/></label>
        <label class="field-label">Origem<${Select} value=${form.origin} options=${labels.ticket_origin} onChange=${(v) => setForm((f) => ({ ...f, origin: v }))}/></label>
        <label class="field-label">Prazo<input class="input" type="date" value=${form.due_on} onInput=${set('due_on')}/></label>
      </div>
      <label class="field-label">Descrição<textarea class="input" rows="4" value=${form.description} onInput=${set('description')}></textarea></label>
      <label class="field-label">Resolução<textarea class="input" rows="2" value=${form.resolution} onInput=${set('resolution')}></textarea></label>
      <div class="form-row"><button class="btn primary" type="submit">Salvar</button><button class="btn" type="button" onClick=${() => setEditing(false)}>Cancelar</button></div>
    </form>` : html`
      ${t.description ? html`<p class="mg-prewrap">${t.description}</p>` : html`<p class="mg-muted">Sem descrição.</p>`}
      ${t.resolution ? html`<p class="mg-resolution"><b>Resolução:</b> ${t.resolution}</p>` : null}
      <div class="mg-ticket-meta">
        <span>aberto ${stamp(t.opened_utc)}</span>
        ${t.due_on ? html`<span>prazo ${civil(t.due_on)}</span>` : null}
        ${t.resolved_utc ? html`<span>resolvido ${stamp(t.resolved_utc)}</span>` : null}
        ${t.client_id ? html`<button class="text-action" onClick=${() => go(`client/${t.client_id}`)}>ficha de ${t.client_company || t.client_name} →</button>` : null}
        <button class="text-action" onClick=${startEdit}>editar</button>
      </div>
      <${StatusForm} ticket=${t} labels=${labels} act=${send}/>
    `}
    <div class="mg-timeline">${t.events.map((e) => html`<div class="mg-event" key=${e.id}>
      <span class="mg-event-when">${stamp(e.created_utc)}</span>
      <div>${e.kind === 'status' ? html`<b>${e.from_status ? `${labels.ticket_status[e.from_status]} → ` : ''}${labels.ticket_status[e.to_status]}</b>` : null}${e.note ? html`<p>${e.note}</p>` : null}</div>
    </div>`)}</div>
    <form class="form-row" onSubmit=${addComment}>
      <input class="input" placeholder="Comentar…" value=${comment} onInput=${(e) => setComment(e.target.value)}/>
      <button class="btn" type="submit" disabled=${!comment.trim()}>Comentar</button>
    </form>
  </div>`;
}

function NewTicket({ labels, clients, act, onDone }) {
  const [form, setForm] = useState({ title: '', client_id: '', kind: 'request', priority: 'medium', origin: 'whatsapp', due_on: '', description: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = async (event) => {
    event.preventDefault();
    await act('ticket-create', { ...form, client_id: form.client_id ? Number(form.client_id) : null, due_on: form.due_on || null }, 'Ticket aberto');
    onDone();
  };
  return html`<${Card} title="Abrir ticket" sub="Sem cliente é ticket interno da operação, como os do auditor.">
    <form class="mg-form" onSubmit=${submit}>
      <label class="field-label">Título<input class="input" value=${form.title} onInput=${set('title')} required autofocus/></label>
      <div class="mg-form-grid">
        <label class="field-label">Cliente<${Select} value=${form.client_id} options=${clients} allowEmpty=${true} emptyLabel="Interno (sem cliente)" onChange=${(v) => setForm((f) => ({ ...f, client_id: v }))}/></label>
        <label class="field-label">Tipo<${Select} value=${form.kind} options=${labels.ticket_kind} onChange=${(v) => setForm((f) => ({ ...f, kind: v }))}/></label>
        <label class="field-label">Prioridade<${Select} value=${form.priority} options=${labels.ticket_priority} onChange=${(v) => setForm((f) => ({ ...f, priority: v }))}/></label>
        <label class="field-label">Origem<${Select} value=${form.origin} options=${labels.ticket_origin} onChange=${(v) => setForm((f) => ({ ...f, origin: v }))}/></label>
        <label class="field-label">Prazo<input class="input" type="date" value=${form.due_on} onInput=${set('due_on')}/></label>
      </div>
      <label class="field-label">Descrição<textarea class="input" rows="4" value=${form.description} onInput=${set('description')}></textarea></label>
      <div class="form-row"><button class="btn primary" type="submit">Abrir ticket</button><button class="btn" type="button" onClick=${onDone}>Cancelar</button></div>
    </form>
  </${Card}>`;
}

export default function Tickets({ config, setToast, go }) {
  const labels = labelsOf(config);
  const [status, setStatus] = useState('');
  const [clientFilter, setClientFilter] = useState('');
  const [showDone, setShowDone] = useState(false);
  const [open, setOpen] = useState(null);
  const [creating, setCreating] = useState(false);
  const query = [status ? `status=${status}` : '', clientFilter ? `client_id=${clientFilter}` : '', !status && !showDone ? 'open=1' : '']
    .filter(Boolean).join('&');
  const resource = useApi(`/api/management/tickets${query ? `?${query}` : ''}`, { every: 60000 });
  const clientsResource = useApi('/api/management/clients');
  const data = resource.data;
  const clients = clientsResource.data
    ? Object.fromEntries(clientsResource.data.clients.map((c) => [String(c.id), c.company || c.name])) : {};

  const act = async (action, body, okText) => {
    try {
      await post(`/api/actions/management/${action}`, body);
      if (okText) setToast(okText);
      await resource.reload();
    } catch (err) {
      setToast(err.message);
      throw err;
    }
  };

  const today = new Date().toISOString().slice(0, 10);
  return html`<div class="mg-page">
    <${ErrorBox} error=${resource.error}/>
    <div class="mg-toolbar">
      <div class="mg-chips">
        <button class=${!status ? 'active' : ''} onClick=${() => setStatus('')}>Abertos <b>${data ? data.open : 0}</b></button>
        ${data ? Object.entries(labels.ticket_status || {}).filter(([id]) => data.counts[id]).map(([id, label]) => html`<button key=${id} class=${status === id ? 'active' : ''} onClick=${() => setStatus(status === id ? '' : id)}>${label} <b>${data.counts[id]}</b></button>`) : null}
      </div>
      <div class="form-row">
        <${Select} value=${clientFilter} options=${clients} allowEmpty=${true} emptyLabel="Todos os clientes" onChange=${setClientFilter}/>
        ${!status ? html`<label class="mg-check"><input type="checkbox" checked=${showDone} onChange=${(e) => setShowDone(e.target.checked)}/> incluir fechados</label>` : null}
        <button class="btn primary" onClick=${() => setCreating((v) => !v)}>${creating ? 'Fechar' : 'Novo ticket'}</button>
      </div>
    </div>

    ${creating ? html`<${NewTicket} labels=${labels} clients=${clients} act=${act} onDone=${() => setCreating(false)}/>` : null}

    ${data && data.tickets.length === 0 ? html`<${Empty}>Nenhum ticket ${status ? `em ${labels.ticket_status[status]}` : 'aberto'}.</${Empty}>` : null}
    <div class="mg-list">${data ? data.tickets.map((t) => {
      const late = t.due_on && t.due_on < today && !DONE.includes(t.status);
      const isOpen = open === t.id;
      return html`<div class=${'mg-ticket' + (isOpen ? ' open' : '')} key=${t.id}>
        <button class="mg-ticket-row" onClick=${() => setOpen(isOpen ? null : t.id)} aria-expanded=${isOpen}>
          <span class=${`tag ${PRIORITY_TONE[t.priority] || ''}`}>${labels.ticket_priority[t.priority]}</span>
          <b>#${t.id} ${t.title}</b>
          <span class="mg-ticket-meta"><span>${t.client_company || t.client_name || 'interno'}</span><span>${labels.ticket_kind[t.kind]}</span>${late ? html`<span class="mg-pending">prazo vencido</span>` : null}<span>${stamp(t.updated_utc)}</span></span>
          <span class=${`tag ${DONE.includes(t.status) ? 'mint' : ''}`}>${labels.ticket_status[t.status]}</span>
        </button>
        ${isOpen ? html`<${TicketDetail} ticketId=${t.id} labels=${labels} act=${act} go=${go} clients=${clients}/>` : null}
      </div>`;
    }) : null}</div>
  </div>`;
}
