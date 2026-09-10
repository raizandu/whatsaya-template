// Gestão da carteira: lista de clientes e ficha com abas (dados, onboarding,
// tickets, pós-venda, financeiro). Só aparece com `features.management` no
// panel.config.json — é a carteira da própria instância, não do cliente final.
import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, ErrorBox, Empty } from '../lib.js';

const STATUS_ORDER = ['negotiation', 'awaiting_payment', 'onboarding', 'implementation', 'qa', 'active', 'paused', 'cancelled'];
const STATUS_TONE = { active: 'mint', paused: 'amber', cancelled: 'orange', awaiting_payment: 'amber' };
const HEALTH_TONE = { healthy: 'mint', attention: 'amber', at_risk: 'orange' };

// Espelho de `client_status_allowed` em panel/actions.py: o servidor decide, a
// tela só evita oferecer o que vai ser recusado.
function allowedTargets(current) {
  if (current === 'cancelled') return [];
  const pos = STATUS_ORDER.indexOf(current);
  return STATUS_ORDER.filter((target) => {
    if (target === current) return false;
    if (target === 'cancelled') return true;
    if (current === 'paused') return target === 'active';
    if (target === 'paused') return current === 'active';
    return STATUS_ORDER.indexOf(target) > pos;
  });
}

const money = (cents) => fmt.brl((Number(cents) || 0) / 100);
const brlToCents = (text) => {
  const clean = String(text || '').trim().replace(/\./g, '').replace(',', '.');
  if (!clean) return 0;
  const value = Number(clean);
  return Number.isFinite(value) ? Math.round(value * 100) : NaN;
};
const centsToBrlInput = (cents) => cents ? (cents / 100).toFixed(2).replace('.', ',') : '';
const civil = (iso) => iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('pt-BR') : '—';
const stamp = (iso) => iso
  ? new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '';

function nextClientAction(client) {
  if (client.onboarding_pending) return { value: 'Onboarding', detail: client.onboarding_pending };
  const candidates = (client.touchpoints || []).flatMap((touchpoint) => {
    const date = touchpoint.next_contact_on || (!touchpoint.done_on ? touchpoint.scheduled_on : null);
    return date ? [{ date, detail: touchpoint.next_action || 'Próximo contato' }] : [];
  }).sort((a, b) => a.date.localeCompare(b.date));
  return candidates[0]
    ? { value: civil(candidates[0].date), detail: candidates[0].detail }
    : { value: 'A definir', detail: 'Nenhuma ação agendada' };
}

function labelsOf(config) {
  return (config && config.management && config.management.labels) || {};
}

function StatusTag({ status, labels }) {
  const tone = STATUS_TONE[status] || '';
  return html`<span class=${`tag ${tone}`}>${(labels.client_status || {})[status] || status}</span>`;
}

function Select({ value, options, onChange, allowEmpty = false, emptyLabel = '—' }) {
  return html`<select class="input" value=${value || ''} onChange=${(event) => onChange(event.target.value)}>
    ${allowEmpty ? html`<option value="">${emptyLabel}</option>` : null}
    ${Object.entries(options || {}).map(([id, label]) => html`<option key=${id} value=${id}>${label}</option>`)}
  </select>`;
}

// ── formulário de cliente (criar e editar) ────────────────────────────

function ClientForm({ initial = {}, labels, submitLabel, onSubmit, onCancel, withStatus = false }) {
  const [form, setForm] = useState({
    name: initial.name || '', company: initial.company || '', segment: initial.segment || '',
    phone: initial.phone || '', email: initial.email || '', kind: initial.kind || '',
    monthly: centsToBrlInput(initial.monthly_cents), setup: centsToBrlInput(initial.setup_cents),
    billing_day: initial.billing_day || '', started_on: initial.started_on || '',
    activated_on: initial.activated_on || '', environment_url: initial.environment_url || '',
    notes: initial.notes || '', status: initial.status || 'negotiation',
    ssh_host: initial.ssh_host || '', ssh_port: initial.ssh_port || '', ssh_user: initial.ssh_user || '', ssh_password: '',
  });
  const [error, setError] = useState(null);
  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    const monthly = brlToCents(form.monthly), setup = brlToCents(form.setup);
    if (Number.isNaN(monthly) || Number.isNaN(setup)) { setError('Valor inválido. Use 1497,00.'); return; }
    const body = {
      name: form.name, company: form.company, segment: form.segment, phone: form.phone, email: form.email,
      kind: form.kind || null, monthly_cents: monthly, setup_cents: setup,
      billing_day: form.billing_day ? Number(form.billing_day) : null,
      started_on: form.started_on || null, activated_on: form.activated_on || null,
      environment_url: form.environment_url, notes: form.notes,
      ssh_host: form.ssh_host, ssh_port: form.ssh_port ? Number(form.ssh_port) : null, ssh_user: form.ssh_user,
      // Vazio no update é "não mexer"; o servidor nunca reexibe a senha.
      ssh_password: form.ssh_password,
    };
    if (withStatus) body.status = form.status;
    setError(null);
    try { await onSubmit(body); } catch (err) { setError(err.message); }
  };

  return html`<form class="mg-form" onSubmit=${submit}>
    <${ErrorBox} error=${error}/>
    <div class="mg-form-grid">
      <label class="field-label">Nome do contato<input class="input" value=${form.name} onInput=${set('name')} required/></label>
      <label class="field-label">Empresa<input class="input" value=${form.company} onInput=${set('company')}/></label>
      <label class="field-label">Segmento<input class="input" value=${form.segment} onInput=${set('segment')}/></label>
      <label class="field-label">Tipo<${Select} value=${form.kind} options=${labels.client_kind} allowEmpty=${true} emptyLabel="Sem tipo" onChange=${(v) => setForm((f) => ({ ...f, kind: v }))}/></label>
      <label class="field-label">WhatsApp (só dígitos)<input class="input" value=${form.phone} onInput=${set('phone')} inputmode="numeric"/></label>
      <label class="field-label">E-mail<input class="input" type="email" value=${form.email} onInput=${set('email')}/></label>
      <label class="field-label">Mensalidade (R$)<input class="input" value=${form.monthly} onInput=${set('monthly')} placeholder="1497,00" inputmode="decimal"/></label>
      <label class="field-label">Implementação (R$)<input class="input" value=${form.setup} onInput=${set('setup')} placeholder="0,00" inputmode="decimal"/></label>
      <label class="field-label">Dia do vencimento<input class="input" type="number" min="1" max="28" value=${form.billing_day} onInput=${set('billing_day')} placeholder="10"/></label>
      <label class="field-label">Início do contrato<input class="input" type="date" value=${form.started_on} onInput=${set('started_on')}/></label>
      <label class="field-label">Ativação<input class="input" type="date" value=${form.activated_on} onInput=${set('activated_on')}/></label>
      <label class="field-label">Link do ambiente<input class="input" type="url" value=${form.environment_url} onInput=${set('environment_url')} placeholder="https://"/></label>
      ${withStatus ? html`<label class="field-label">Etapa inicial<${Select} value=${form.status} options=${labels.client_status} onChange=${(v) => setForm((f) => ({ ...f, status: v }))}/></label>` : null}
      <label class="field-label mg-span">Observações<textarea class="input" rows="3" value=${form.notes} onInput=${set('notes')}></textarea></label>
    </div>
    <div class="mg-form-section"><b>Servidor do cliente</b><span class="mg-muted">Acesso à VPS para o monitoramento de saúde e conexão. A senha nunca volta para a tela.</span></div>
    <div class="mg-form-grid four">
      <label class="field-label">Host ou IP<input class="input" value=${form.ssh_host} onInput=${set('ssh_host')} placeholder="203.0.113.10"/></label>
      <label class="field-label">Porta<input class="input" type="number" min="1" max="65535" value=${form.ssh_port} onInput=${set('ssh_port')} placeholder="22"/></label>
      <label class="field-label">Usuário SSH<input class="input" value=${form.ssh_user} onInput=${set('ssh_user')} placeholder="root"/></label>
      <label class="field-label">Senha SSH<input class="input" type="password" autocomplete="new-password" value=${form.ssh_password} onInput=${set('ssh_password')} placeholder=${initial.ssh_password_set ? 'definida · deixe em branco para manter' : ''}/></label>
    </div>
    <div class="form-row">
      <button class="btn primary" type="submit">${submitLabel}</button>
      ${onCancel ? html`<button class="btn" type="button" onClick=${onCancel}>Cancelar</button>` : null}
    </div>
  </form>`;
}

// ── lista ─────────────────────────────────────────────────────────────

export default function Clients({ config, setToast, go }) {
  const resource = useApi('/api/management/clients', { every: 60000 });
  const labels = labelsOf(config);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const data = resource.data;

  const create = async (body) => {
    const result = await post('/api/actions/management/client-create', body);
    setToast(`Cliente ${result.client.name} criado`);
    setCreating(false);
    go(`client/${result.client.id}`);
  };

  const rows = data ? data.clients.filter((c) => !filter || c.status === filter) : [];
  const onboarding = data ? data.clients.filter((c) => ['onboarding', 'implementation', 'qa'].includes(c.status)).length : 0;
  const openTickets = data ? data.clients.reduce((sum, c) => sum + (c.open_tickets || 0), 0) : 0;

  return html`<div class="mg-page">
    <${ErrorBox} error=${resource.error}/>
    <div class="grid c4 mg-tiles">
      <div class="card tile"><span class="k">Clientes ativos</span><span class="v green">${data ? data.counts.active : '—'}</span></div>
      <div class="card tile dark"><span class="k">MRR</span><span class="v">${data ? money(data.mrr_cents) : '—'}</span><span class="s">mensalidades dos ativos</span></div>
      <div class="card tile"><span class="k">Em implantação</span><span class="v">${data ? onboarding : '—'}</span><span class="s">onboarding, implementação e QA</span></div>
      <div class="card tile"><span class="k">Tickets abertos</span><span class="v">${data ? openTickets : '—'}</span></div>
    </div>

    <div class="mg-toolbar">
      <div class="mg-chips">
        <button class=${!filter ? 'active' : ''} onClick=${() => setFilter('')}>Todos <b>${data ? data.clients.length : 0}</b></button>
        ${data ? data.statuses.filter((s) => data.counts[s.id]).map((s) => html`<button key=${s.id} class=${filter === s.id ? 'active' : ''} onClick=${() => setFilter(filter === s.id ? '' : s.id)}>${s.label} <b>${data.counts[s.id]}</b></button>`) : null}
      </div>
      <button class="btn primary" onClick=${() => setCreating((v) => !v)}>${creating ? 'Fechar' : 'Novo cliente'}</button>
    </div>

    ${creating ? html`<${Card} title="Novo cliente" sub="Quem veio pelo funil entra pelo botão Virou cliente na conversa; aqui é o cadastro manual.">
      <${ClientForm} labels=${labels} submitLabel="Criar cliente" withStatus=${true} onSubmit=${create} onCancel=${() => setCreating(false)}/>
    </${Card}>` : null}

    ${data && rows.length === 0 ? html`<${Empty}>${data.clients.length ? 'Nenhum cliente nessa etapa.' : 'Nenhum cliente ainda. Marque um lead como Virou cliente na conversa dele, ou cadastre à mão.'}</${Empty}>` : null}
    ${rows.length ? html`<div class="card mg-table-card"><table class="plain mg-table">
      <thead><tr><th>Cliente</th><th>Etapa</th><th>Mensalidade</th><th>Saúde</th><th>Onboarding</th><th>Tickets</th><th></th></tr></thead>
      <tbody>${rows.map((c) => html`<tr key=${c.id} class="mg-row" onClick=${() => go(`client/${c.id}`)}>
        <td><div class="mg-identity"><span class="avatar mint">${fmt.initials(c.company || c.name)}</span><div><b>${c.company || c.name}</b><span>${c.company ? c.name : c.phone_display}</span></div></div></td>
        <td><${StatusTag} status=${c.status} labels=${labels}/></td>
        <td class="mono">${c.monthly_cents ? money(c.monthly_cents) : '—'}</td>
        <td>${c.health ? html`<span class=${`tag ${HEALTH_TONE[c.health] || ''}`}>${(labels.health || {})[c.health] || c.health}</span>` : html`<span class="mg-muted">sem avaliação</span>`}</td>
        <td>${c.onboarding_total ? html`<span class="mg-progress"><i style=${`width:${Math.round((c.onboarding_done / c.onboarding_total) * 100)}%`}></i></span><small>${c.onboarding_done}/${c.onboarding_total}</small>` : html`<span class="mg-muted">—</span>`}</td>
        <td>${c.open_tickets ? html`<span class="tag orange">${c.open_tickets}</span>` : html`<span class="mg-muted">0</span>`}</td>
        <td class="mg-arrow">→</td>
      </tr>`)}</tbody>
    </table></div>` : null}
  </div>`;
}

// ── ficha ─────────────────────────────────────────────────────────────

function StatusChange({ client, labels, onChange }) {
  const targets = allowedTargets(client.status);
  const [target, setTarget] = useState('');
  const [note, setNote] = useState('');
  if (!targets.length) return null;
  const submit = async (event) => {
    event.preventDefault();
    if (!target) return;
    await onChange(target, note);
    setTarget(''); setNote('');
  };
  return html`<form class="mg-status-form" onSubmit=${submit}>
    <select class="input" value=${target} onChange=${(e) => setTarget(e.target.value)}>
      <option value="">Mudar etapa…</option>
      ${targets.map((id) => html`<option key=${id} value=${id}>${labels.client_status[id]}</option>`)}
    </select>
    <input class="input" placeholder="Nota (opcional)" value=${note} onInput=${(e) => setNote(e.target.value)}/>
    <button class="btn primary" type="submit" disabled=${!target}>Aplicar</button>
  </form>`;
}

function DataTab({ client, labels, act }) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState('');
  const addNote = async (event) => {
    event.preventDefault();
    if (!note.trim()) return;
    await act('client-note', { id: client.id, note }, 'Nota registrada');
    setNote('');
  };
  return html`<section class="mg-dossier-sheet">
    <header class="mg-dossier-head">
      <div><span class="kpi-eyebrow">Ficha ativa</span><h2>Dados e contexto</h2></div>
      <button class="btn sm" onClick=${() => setEditing((v) => !v)}>${editing ? 'Fechar' : 'Editar dados'}</button>
    </header>
    <div class="mg-dossier-body">
      ${editing ? html`<${ClientForm} initial=${client} labels=${labels} submitLabel="Salvar"
        onSubmit=${async (body) => { await act('client-update', { id: client.id, ...body }, 'Dados salvos'); setEditing(false); }}
        onCancel=${() => setEditing(false)}/>`
      : html`<div class="mg-pairs">
        <div class="detail-pair"><span>Empresa</span><b>${client.company || '—'}</b></div>
        <div class="detail-pair"><span>Segmento</span><b>${client.segment || '—'}</b></div>
        <div class="detail-pair"><span>Tipo</span><b>${(labels.client_kind || {})[client.kind] || '—'}</b></div>
        <div class="detail-pair"><span>WhatsApp</span><b>${client.phone_display || '—'}</b></div>
        <div class="detail-pair"><span>E-mail</span><b>${client.email || '—'}</b></div>
        <div class="detail-pair"><span>Mensalidade</span><b>${money(client.monthly_cents)}</b></div>
        <div class="detail-pair"><span>Implementação</span><b>${client.setup_cents ? money(client.setup_cents) : '—'}</b></div>
        <div class="detail-pair"><span>Vencimento</span><b>${client.billing_day ? `dia ${client.billing_day}` : 'dia 10 (padrão)'}</b></div>
        <div class="detail-pair"><span>Início</span><b>${civil(client.started_on)}</b></div>
        <div class="detail-pair"><span>Ativação</span><b>${civil(client.activated_on)}</b></div>
        ${client.churned_on ? html`<div class="detail-pair"><span>Encerramento</span><b>${civil(client.churned_on)}</b></div>` : null}
        <div class="detail-pair"><span>Ambiente</span><b>${client.environment_url ? html`<a href=${client.environment_url} target="_blank" rel="noopener">${client.environment_url}</a>` : '—'}</b></div>
        <div class="detail-pair"><span>Servidor</span><b>${client.ssh_host ? `${client.ssh_user ? `${client.ssh_user}@` : ''}${client.ssh_host}${client.ssh_port ? `:${client.ssh_port}` : ''}` : '—'}</b></div>
        <div class="detail-pair"><span>Senha SSH</span><b>${client.ssh_password_set ? 'definida' : 'não definida'}</b></div>
      </div>${client.notes ? html`<section class="mg-dossier-note"><div><span class="kpi-eyebrow">Contexto importante</span><h3>Observações da conta</h3><p class="mg-prewrap">${client.notes}</p></div>${client.environment_url ? html`<a class="btn sm" href=${client.environment_url} target="_blank" rel="noopener">Abrir ambiente <i class="fi fi-rr-arrow-up-right" aria-hidden="true"></i></a>` : null}</section>` : null}`}
    </div>
    <section class="mg-dossier-history">
      <header><div><h3>Atividade recente</h3><p>Mudanças de etapa e notas da equipe</p></div></header>
      <form class="form-row" onSubmit=${addNote}>
        <input class="input" placeholder="Registrar uma nota…" value=${note} onInput=${(e) => setNote(e.target.value)}/>
        <button class="btn" type="submit" disabled=${!note.trim()}>Anotar</button>
      </form>
      <div class="mg-timeline">${client.events.map((e) => html`<div class="mg-event" key=${e.id}>
        <span class="mg-event-when">${stamp(e.created_utc)}</span>
        <div>${e.kind === 'status'
          ? html`<b>${e.from_status ? `${labels.client_status[e.from_status]} → ` : ''}${labels.client_status[e.to_status]}</b>`
          : null}${e.note ? html`<p>${e.note}</p>` : null}</div>
      </div>`)}</div>
    </section>
  </section>`;
}

function OnboardingTab({ client, labels, act, onFinish }) {
  const [title, setTitle] = useState('');
  const [noteFor, setNoteFor] = useState(null);
  const [noteText, setNoteText] = useState('');
  const steps = client.onboarding || [];
  const done = steps.filter((s) => s.done_utc).length;
  const add = async (event) => {
    event.preventDefault();
    if (!title.trim()) return;
    await act('onboarding-step', { client_id: client.id, title }, 'Passo adicionado');
    setTitle('');
  };
  const saveNote = async (step) => {
    await act('onboarding-step', { id: step.id, pending_note: noteText }, 'Pendência anotada');
    setNoteFor(null); setNoteText('');
  };
  const canFinish = steps.length > 0 && done === steps.length && ONBOARDING_STATUSES.has(client.status) && allowedTargets(client.status).includes('active');
  const finish = async () => {
    await act('client-status', { id: client.id, status: 'active', note: 'Onboarding finalizado' }, 'Onboarding finalizado · cliente ativo');
    onFinish();
  };
  return html`<section class="mg-onboarding-workspace">
    <header class="mg-onboarding-head"><div><span class="kpi-eyebrow">Implantação</span><h2>${steps.length ? `${done} de ${steps.length} etapas concluídas` : 'Onboarding ainda não iniciado'}</h2><p>${steps.length ? 'Marque cada entrega; a primeira pendência aberta aparece na carteira.' : 'O checklist padrão é criado quando o cliente entra em Onboarding.'}</p></div><strong>${steps.length ? `${Math.round((done / Math.max(1, steps.length)) * 100)}%` : '—'}</strong></header>
    ${steps.length ? html`<span class="mg-progress lg"><i style=${`width:${Math.round((done / Math.max(1, steps.length)) * 100)}%`}></i></span>` : null}
    <div class="mg-checklist">${steps.map((step) => html`<div class=${'mg-step' + (step.done_utc ? ' done' : '')} key=${step.id}>
      <label><input type="checkbox" checked=${!!step.done_utc} onChange=${(e) => act('onboarding-step', { id: step.id, done: e.target.checked }, e.target.checked ? 'Passo concluído' : 'Passo reaberto')}/><span>${step.title}</span></label>
      ${noteFor === step.id ? html`<div class="form-row">
        <input class="input" value=${noteText} placeholder="O que está pendente?" onInput=${(e) => setNoteText(e.target.value)}/>
        <button class="btn sm" onClick=${() => saveNote(step)}>Salvar</button>
        <button class="btn sm" onClick=${() => setNoteFor(null)}>Cancelar</button>
      </div>` : html`<div class="mg-step-tools">
        ${step.pending_note ? html`<span class="mg-pending">${step.pending_note}</span>` : null}
        ${!step.done_utc ? html`<button class="text-action" onClick=${() => { setNoteFor(step.id); setNoteText(step.pending_note || ''); }}>${step.pending_note ? 'editar pendência' : 'anotar pendência'}</button>` : null}
        <button class="text-action" onClick=${() => act('onboarding-step', { id: step.id, delete: true }, 'Passo removido')}>remover</button>
      </div>`}
    </div>`)}</div>
    <form class="form-row" onSubmit=${add}>
      <input class="input" placeholder="Novo passo…" value=${title} onInput=${(e) => setTitle(e.target.value)}/>
      <button class="btn" type="submit" disabled=${!title.trim()}>Adicionar</button>
    </form>
    ${canFinish ? html`<div class="mg-onboarding-finish"><div><span class="kpi-eyebrow">Pronto para produção</span><b>Checklist concluído</b><p>Confirme para ativar o cliente e abrir o dossiê operacional.</p></div><button class="btn primary" onClick=${finish}>Finalizar onboarding</button></div>` : null}
    ${client.status === 'active' && steps.length ? html`<div class="mg-onboarding-complete"><span class="dot ok"></span><div><b>Onboarding concluído</b><p>Histórico preservado para consulta.</p></div></div>` : null}
  </section>`;
}

function TicketsTab({ client, labels, act }) {
  const [form, setForm] = useState({ title: '', kind: 'request', priority: 'medium', origin: 'whatsapp', description: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const create = async (event) => {
    event.preventDefault();
    await act('ticket-create', { client_id: client.id, ...form }, 'Ticket aberto');
    setForm({ title: '', kind: 'request', priority: 'medium', origin: 'whatsapp', description: '' });
  };
  const tickets = client.tickets || [];
  return html`<div class="mg-two">
    <${Card} title=${`Tickets · ${tickets.filter((t) => !['resolved', 'closed'].includes(t.status)).length} abertos`}>
      ${tickets.length === 0 ? html`<${Empty}>Nenhum ticket deste cliente.</${Empty}>` : null}
      <div class="mg-list">${tickets.map((t) => html`<div class="mg-ticket" key=${t.id}>
        <div class="mg-ticket-head">
          <span class=${`tag ${t.priority === 'critical' || t.priority === 'high' ? 'orange' : ''}`}>${labels.ticket_priority[t.priority]}</span>
          <b>#${t.id} ${t.title}</b>
          <span class="tag">${labels.ticket_status[t.status]}</span>
        </div>
        <div class="mg-ticket-meta"><span>${labels.ticket_kind[t.kind]}</span><span>${labels.ticket_origin[t.origin]}</span><span>${stamp(t.opened_utc)}</span></div>
        ${t.description ? html`<p class="mg-prewrap">${t.description}</p>` : null}
        ${t.resolution ? html`<p class="mg-resolution"><b>Resolução:</b> ${t.resolution}</p>` : null}
        <${TicketStatusForm} ticket=${t} labels=${labels} act=${act}/>
      </div>`)}</div>
    </${Card}>
    <${Card} title="Abrir ticket">
      <form class="mg-form" onSubmit=${create}>
        <label class="field-label">Título<input class="input" value=${form.title} onInput=${set('title')} required/></label>
        <div class="mg-form-grid">
          <label class="field-label">Tipo<${Select} value=${form.kind} options=${labels.ticket_kind} onChange=${(v) => setForm((f) => ({ ...f, kind: v }))}/></label>
          <label class="field-label">Prioridade<${Select} value=${form.priority} options=${labels.ticket_priority} onChange=${(v) => setForm((f) => ({ ...f, priority: v }))}/></label>
          <label class="field-label">Origem<${Select} value=${form.origin} options=${labels.ticket_origin} onChange=${(v) => setForm((f) => ({ ...f, origin: v }))}/></label>
        </div>
        <label class="field-label">Descrição<textarea class="input" rows="4" value=${form.description} onInput=${set('description')}></textarea></label>
        <button class="btn primary" type="submit">Abrir ticket</button>
      </form>
    </${Card}>
  </div>`;
}

function TicketStatusForm({ ticket, labels, act }) {
  const [status, setStatus] = useState('');
  const [resolution, setResolution] = useState('');
  const closing = status === 'resolved' || status === 'closed';
  const submit = async (event) => {
    event.preventDefault();
    if (!status) return;
    await act('ticket-status', { id: ticket.id, status, resolution: closing ? resolution : undefined }, `Ticket #${ticket.id} em ${labels.ticket_status[status]}`);
    setStatus(''); setResolution('');
  };
  return html`<form class="mg-status-form" onSubmit=${submit}>
    <select class="input" value=${status} onChange=${(e) => setStatus(e.target.value)}>
      <option value="">Mudar status…</option>
      ${Object.entries(labels.ticket_status).filter(([id]) => id !== ticket.status).map(([id, label]) => html`<option key=${id} value=${id}>${label}</option>`)}
    </select>
    ${closing && !ticket.resolution ? html`<input class="input" placeholder="Resolução (obrigatória)" value=${resolution} onInput=${(e) => setResolution(e.target.value)} required/>` : null}
    <button class="btn sm" type="submit" disabled=${!status}>Aplicar</button>
  </form>`;
}

function TouchpointsTab({ client, labels, act }) {
  const [form, setForm] = useState({ kind: 'checkin', scheduled_on: '', done_on: '', health: '', summary: '', next_action: '', next_contact_on: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const create = async (event) => {
    event.preventDefault();
    const body = { client_id: client.id, ...form, health: form.health || null, scheduled_on: form.scheduled_on || null, done_on: form.done_on || null, next_contact_on: form.next_contact_on || null };
    await act('touchpoint-create', body, 'Acompanhamento registrado');
    setForm({ kind: 'checkin', scheduled_on: '', done_on: '', health: '', summary: '', next_action: '', next_contact_on: '' });
  };
  const items = client.touchpoints || [];
  return html`<div class="mg-two">
    <${Card} title="Pós-venda" sub=${client.health ? `Saúde atual: ${labels.health[client.health]}` : 'Sem avaliação de saúde ainda'}>
      ${items.length === 0 ? html`<${Empty}>Nenhum acompanhamento registrado.</${Empty}>` : null}
      <div class="mg-list">${items.map((tp) => html`<div class="mg-touchpoint" key=${tp.id}>
        <div class="mg-ticket-head">
          <b>${labels.touchpoint_kind[tp.kind]}</b>
          ${tp.health ? html`<span class=${`tag ${HEALTH_TONE[tp.health]}`}>${labels.health[tp.health]}</span>` : html`<span class="tag amber">agendado</span>`}
        </div>
        <div class="mg-ticket-meta">
          ${tp.done_on ? html`<span>realizado ${civil(tp.done_on)}</span>` : html`<span>agendado para ${civil(tp.scheduled_on)}</span>`}
          ${tp.next_contact_on ? html`<span>próximo contato ${civil(tp.next_contact_on)}</span>` : null}
        </div>
        ${tp.summary ? html`<p class="mg-prewrap">${tp.summary}</p>` : null}
        ${tp.next_action ? html`<p><b>Próxima ação:</b> ${tp.next_action}</p>` : null}
        ${!tp.done_on ? html`<${TouchpointDone} tp=${tp} labels=${labels} act=${act}/>` : null}
      </div>`)}</div>
    </${Card}>
    <${Card} title="Registrar acompanhamento">
      <form class="mg-form" onSubmit=${create}>
        <div class="mg-form-grid">
          <label class="field-label">Tipo<${Select} value=${form.kind} options=${labels.touchpoint_kind} onChange=${(v) => setForm((f) => ({ ...f, kind: v }))}/></label>
          <label class="field-label">Saúde<${Select} value=${form.health} options=${labels.health} allowEmpty=${true} emptyLabel="Ainda não avaliado" onChange=${(v) => setForm((f) => ({ ...f, health: v }))}/></label>
          <label class="field-label">Agendado para<input class="input" type="date" value=${form.scheduled_on} onInput=${set('scheduled_on')}/></label>
          <label class="field-label">Realizado em<input class="input" type="date" value=${form.done_on} onInput=${set('done_on')}/></label>
          <label class="field-label">Próximo contato<input class="input" type="date" value=${form.next_contact_on} onInput=${set('next_contact_on')}/></label>
          <label class="field-label">Próxima ação<input class="input" value=${form.next_action} onInput=${set('next_action')}/></label>
        </div>
        <label class="field-label">Resumo<textarea class="input" rows="3" value=${form.summary} onInput=${set('summary')}></textarea></label>
        <button class="btn primary" type="submit">Registrar</button>
      </form>
    </${Card}>
  </div>`;
}

function TouchpointDone({ tp, labels, act }) {
  const [health, setHealth] = useState('healthy');
  const [summary, setSummary] = useState('');
  const today = new Date().toISOString().slice(0, 10);
  return html`<form class="mg-status-form" onSubmit=${async (e) => { e.preventDefault(); await act('touchpoint-update', { id: tp.id, done_on: today, health, summary: summary || undefined }, 'Acompanhamento concluído'); }}>
    <${Select} value=${health} options=${labels.health} onChange=${setHealth}/>
    <input class="input" placeholder="Resumo (opcional)" value=${summary} onInput=${(e) => setSummary(e.target.value)}/>
    <button class="btn sm" type="submit">Concluir hoje</button>
  </form>`;
}

function FinanceTab({ client, labels, act }) {
  const charges = client.charges || [];
  const costs = client.costs || [];
  const today = new Date().toISOString().slice(0, 10);
  const pay = (charge) => act('charge-pay', { id: charge.id, paid_on: today }, `Baixa em ${labels.charge_kind[charge.kind]} ${charge.period}`);
  return html`<div class="mg-two">
    <${Card} title="Cobranças" sub="A mensalidade do mês é gerada quando a tela Financeiro abre a competência. Baixa manual, com desfazer.">
      ${charges.length === 0 ? html`<${Empty}>Nenhuma cobrança gerada ainda.</${Empty}>` : html`<table class="plain mg-table compact">
        <thead><tr><th>Competência</th><th>Tipo</th><th>Vencimento</th><th>Valor</th><th>Situação</th><th></th></tr></thead>
        <tbody>${charges.map((ch) => {
          const late = ch.status === 'expected' && ch.due_on < today;
          return html`<tr key=${ch.id}>
            <td class="mono">${ch.period}</td>
            <td>${labels.charge_kind[ch.kind]}${ch.note ? html`<small class="mg-muted"> · ${ch.note}</small>` : null}</td>
            <td>${civil(ch.due_on)}</td>
            <td class="mono">${money(ch.status === 'paid' ? ch.paid_cents : ch.amount_cents)}</td>
            <td>${ch.status === 'paid' ? html`<span class="tag mint">recebido ${civil(ch.paid_on)}</span>`
              : ch.status === 'cancelled' ? html`<span class="tag">cancelada</span>`
              : late ? html`<span class="tag orange">atrasada</span>` : html`<span class="tag amber">prevista</span>`}</td>
            <td class="mg-actions">${ch.status === 'expected'
              ? html`<button class="btn sm" onClick=${() => pay(ch)}>Receber</button><button class="text-action" onClick=${() => act('charge-cancel', { id: ch.id }, 'Cobrança cancelada')}>cancelar</button>`
              : html`<button class="text-action" onClick=${() => act('charge-reopen', { id: ch.id }, 'Cobrança reaberta')}>desfazer</button>`}</td>
          </tr>`;
        })}</tbody>
      </table>`}
    </${Card}>
    <${Card} title="Custos deste cliente" sub="Edição na tela Financeiro, por competência.">
      ${costs.length === 0 ? html`<${Empty}>Nenhum custo lançado.</${Empty}>` : html`<table class="plain mg-table compact">
        <thead><tr><th>Competência</th><th>Categoria</th><th>Descrição</th><th>Valor</th></tr></thead>
        <tbody>${costs.map((co) => html`<tr key=${co.id}>
          <td class="mono">${co.period}</td><td>${labels.cost_category[co.category]}</td>
          <td>${co.label || '—'}${co.source === 'plan' ? html`<small class="mg-muted"> · previsto</small>` : null}</td>
          <td class="mono">${money(co.amount_cents)}</td>
        </tr>`)}</tbody>
      </table>`}
    </${Card}>
  </div>`;
}

const TABS = [
  ['data', 'Dados', 'document'],
  ['onboarding', 'Onboarding', 'list-check'],
  ['tickets', 'Tickets', 'ticket'],
  ['touchpoints', 'Pós-venda', 'handshake'],
  ['finance', 'Financeiro', 'chart-pie'],
];
const ONBOARDING_STATUSES = new Set(['onboarding', 'implementation', 'qa']);

export function ClientDetail({ clientId, config, status, setToast, go }) {
  const resource = useApi(`/api/management/client/${encodeURIComponent(clientId)}`, { every: 60000 });
  const labels = labelsOf(config);
  const [tab, setTab] = useState(null);
  const client = resource.data;

  // Toda escrita passa aqui: mostra o resultado no toast e recarrega a ficha.
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

  if (resource.error) return html`<${ErrorBox} error=${resource.error}/>`;
  if (!client) return html`<div class="lead-loading">Carregando cliente…</div>`;

  const openTickets = (client.tickets || []).filter((t) => !['resolved', 'closed'].includes(t.status)).length;
  const onboardingDone = Number(client.onboarding_done) || 0;
  const onboardingTotal = Number(client.onboarding_total) || 0;
  const activeTab = tab || (ONBOARDING_STATUSES.has(client.status) ? 'onboarding' : 'data');
  const nextAction = nextClientAction(client);
  const statusLabel = (labels.client_status || {})[client.status] || client.status;
  const connected = status && status.connection === 'connected';
  const copyPhone = async () => {
    try {
      await navigator.clipboard.writeText(client.phone || client.phone_display || '');
      setToast('WhatsApp copiado');
    } catch {
      setToast('Não foi possível copiar o WhatsApp');
    }
  };
  const onTabKeyDown = (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const ids = TABS.map(([id]) => id);
    const current = ids.indexOf(activeTab);
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? ids.length - 1
      : event.key === 'ArrowRight' ? (current + 1) % ids.length
      : (current - 1 + ids.length) % ids.length;
    setTab(ids[next]);
    requestAnimationFrame(() => document.getElementById(`mg-client-tab-${ids[next]}`)?.focus());
  };

  return html`<div class="mg-client-dossier">
    <header class="mg-client-topbar">
      <div class="mg-client-breadcrumb"><button type="button" onClick=${() => go('clients')} aria-label="Voltar para clientes"><i class="fi fi-rr-arrow-left" aria-hidden="true"></i></button><span>Clientes</span><i>/</i><b>${client.company || client.name}</b></div>
      <button class="mg-client-connection" type="button" onClick=${() => go('connection')}><span class=${`dot ${connected ? 'ok' : 'bad'}`}></span>${connected ? 'WhatsApp conectado' : 'Ver conexão'}</button>
    </header>
    <div class="mg-dossier-layout">
      <aside class="mg-client-profile">
        <div class="mg-client-owner"><span class="avatar">${fmt.initials(client.name)}</span><div><span class="kpi-eyebrow">Responsável pela conta</span><h1>${client.name}</h1><p>${client.email || 'sem e-mail cadastrado'}</p></div></div>
        <span class=${`mg-client-state ${STATUS_TONE[client.status] || ''}`}><span class="dot"></span>${client.status === 'active' && client.activated_on ? `Ativo desde ${civil(client.activated_on)}` : statusLabel}</span>
        <section class="mg-client-summary" aria-label="Resumo operacional">
          <div><span>Onboarding</span><b>${onboardingTotal ? (onboardingDone === onboardingTotal ? 'Concluído' : `${onboardingDone}/${onboardingTotal}`) : '—'}</b><small>${onboardingTotal ? `${onboardingDone} de ${onboardingTotal} etapas` : 'não iniciado'}</small></div>
          <div><span>Tickets</span><b>${openTickets} ${openTickets === 1 ? 'aberto' : 'abertos'}</b><small>${openTickets ? 'pedem acompanhamento' : 'nenhuma pendência'}</small></div>
          <div><span>Mensalidade</span><b>${money(client.monthly_cents)}</b><small>${client.billing_day ? `vence dia ${client.billing_day}` : 'vence dia 10'}</small></div>
          <div><span>Próxima ação</span><b>${nextAction.value}</b><small>${nextAction.detail}</small></div>
        </section>
        <div class="mg-client-contact"><span>WhatsApp</span><div><b>${client.phone_display || 'não cadastrado'}</b>${client.phone || client.phone_display ? html`<button type="button" onClick=${copyPhone} aria-label="Copiar número do WhatsApp" title="Copiar número"><i class="fi fi-rr-copy" aria-hidden="true"></i></button>` : null}</div></div>
        <details class="mg-client-stage"><summary><span><small>Etapa do cliente</small><b>${statusLabel}</b></span><i class="fi fi-rr-angle-small-down" aria-hidden="true"></i></summary><${StatusChange} client=${client} labels=${labels} onChange=${(nextStatus, note) => act('client-status', { id: client.id, status: nextStatus, note }, `Etapa: ${labels.client_status[nextStatus]}`)}/></details>
        ${client.chat_id ? html`<button class="btn mg-client-chat" onClick=${() => go(`lead/${encodeURIComponent(client.chat_id)}`)}><i class="fi fi-rr-comments" aria-hidden="true"></i> Ver conversa</button>` : null}
      </aside>
      <section class="mg-client-content">
        <div class="mg-client-tabs" role="tablist" aria-label="Áreas do cliente" onKeyDown=${onTabKeyDown}>${TABS.map(([id, label, icon]) => html`<button id=${`mg-client-tab-${id}`} key=${id} type="button" role="tab" aria-selected=${activeTab === id} aria-controls=${`mg-client-panel-${id}`} tabIndex=${activeTab === id ? 0 : -1} class=${activeTab === id ? 'active' : ''} onClick=${() => setTab(id)}><i class=${`fi fi-rr-${icon}`} aria-hidden="true"></i><span>${label}</span>${id === 'tickets' && openTickets ? html`<b>${openTickets}</b>` : id === 'onboarding' && onboardingTotal ? html`<b>${onboardingDone}/${onboardingTotal}</b>` : null}</button>`)}</div>
        <div id=${`mg-client-panel-${activeTab}`} class="mg-client-panel" role="tabpanel" aria-labelledby=${`mg-client-tab-${activeTab}`}>
          ${activeTab === 'data' ? html`<${DataTab} client=${client} labels=${labels} act=${act}/>` : null}
          ${activeTab === 'onboarding' ? html`<${OnboardingTab} client=${client} labels=${labels} act=${act} onFinish=${() => setTab('data')}/>` : null}
          ${activeTab === 'tickets' ? html`<${TicketsTab} client=${client} labels=${labels} act=${act}/>` : null}
          ${activeTab === 'touchpoints' ? html`<${TouchpointsTab} client=${client} labels=${labels} act=${act}/>` : null}
          ${activeTab === 'finance' ? html`<${FinanceTab} client=${client} labels=${labels} act=${act}/>` : null}
        </div>
      </section>
    </div>
  </div>`;
}
