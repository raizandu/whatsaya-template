// Financeiro da carteira, por competência: MRR, cobranças (baixa manual),
// custos por cliente e compartilhados, planos de custo recorrentes e margem.
// Abrir a competência já materializa mensalidade e planos (idempotente, no
// servidor). Nada aqui fala com gateway de pagamento.
import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, ErrorBox, Empty } from '../lib.js';

const money = (cents) => fmt.brl((Number(cents) || 0) / 100);
const civil = (iso) => iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('pt-BR') : '—';
const brlToCents = (text) => {
  const clean = String(text || '').trim().replace(/\./g, '').replace(',', '.');
  if (!clean) return NaN;
  const value = Number(clean);
  return Number.isFinite(value) ? Math.round(value * 100) : NaN;
};
const currentPeriod = () => new Date().toISOString().slice(0, 7);
const shiftPeriod = (period, delta) => {
  const [y, m] = period.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
};
const periodLabel = (period) => {
  const [y, m] = period.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, 15)).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' });
};
const labelsOf = (config) => (config && config.management && config.management.labels) || {};

function Select({ value, options, onChange, allowEmpty = false, emptyLabel = '—' }) {
  return html`<select class="input" value=${value || ''} onChange=${(e) => onChange(e.target.value)}>
    ${allowEmpty ? html`<option value="">${emptyLabel}</option>` : null}
    ${Object.entries(options || {}).map(([id, label]) => html`<option key=${id} value=${id}>${label}</option>`)}
  </select>`;
}

function ChargeRow({ charge, labels, act, today }) {
  const late = charge.status === 'expected' && charge.due_on < today;
  return html`<tr>
    <td>${labels.charge_kind[charge.kind]}${charge.note ? html`<small class="mg-muted"> · ${charge.note}</small>` : null}</td>
    <td>${civil(charge.due_on)}</td>
    <td class="mono">${money(charge.status === 'paid' ? charge.paid_cents : charge.amount_cents)}</td>
    <td>${charge.status === 'paid' ? html`<span class="tag mint">recebido ${civil(charge.paid_on)}</span>`
      : charge.status === 'cancelled' ? html`<span class="tag">cancelada</span>`
      : late ? html`<span class="tag orange">atrasada</span>` : html`<span class="tag amber">prevista</span>`}</td>
    <td class="mg-actions">${charge.status === 'expected'
      ? html`<button class="btn sm" onClick=${() => act('charge-pay', { id: charge.id, paid_on: today }, 'Recebimento registrado')}>Receber hoje</button><button class="text-action" onClick=${() => act('charge-cancel', { id: charge.id }, 'Cobrança cancelada')}>cancelar</button>`
      : html`<button class="text-action" onClick=${() => act('charge-reopen', { id: charge.id }, 'Cobrança reaberta')}>desfazer</button>`}</td>
  </tr>`;
}

function CostRow({ cost, labels, act }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const save = async (event) => {
    event.preventDefault();
    const cents = brlToCents(value);
    if (Number.isNaN(cents)) return;
    await act('cost-upsert', { id: cost.id, amount_cents: cents }, 'Custo ajustado');
    setEditing(false);
  };
  return html`<tr>
    <td>${labels.cost_category[cost.category]}</td>
    <td>${cost.label || '—'}${cost.source === 'plan' ? html`<small class="mg-muted"> · previsto pelo plano</small>` : null}${cost.currency_original && cost.amount_original ? html`<small class="mg-muted"> · ${cost.amount_original} ${cost.currency_original}</small>` : null}</td>
    <td class="mono">${editing
      ? html`<form class="form-row" onSubmit=${save}><input class="input sm" value=${value} placeholder=${(cost.amount_cents / 100).toFixed(2).replace('.', ',')} onInput=${(e) => setValue(e.target.value)} inputmode="decimal" autofocus/><button class="btn sm" type="submit">Salvar</button><button class="text-action" type="button" onClick=${() => setEditing(false)}>cancelar</button></form>`
      : money(cost.amount_cents)}</td>
    <td class="mg-actions">${!editing ? html`<button class="text-action" onClick=${() => { setValue(''); setEditing(true); }}>ajustar</button><button class="text-action" onClick=${() => act('cost-delete', { id: cost.id }, 'Custo removido')}>remover</button>` : null}</td>
  </tr>`;
}

function CostForm({ period, clientId, labels, act, onDone }) {
  const [form, setForm] = useState({ category: 'ai', amount: '', label: '', currency_original: '', amount_original: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = async (event) => {
    event.preventDefault();
    const cents = brlToCents(form.amount);
    if (Number.isNaN(cents)) return;
    const body = { client_id: clientId, period, category: form.category, amount_cents: cents, label: form.label };
    if (form.currency_original && form.amount_original) {
      body.currency_original = form.currency_original;
      body.amount_original = Number(String(form.amount_original).replace(',', '.'));
    }
    await act('cost-upsert', body, 'Custo lançado');
    setForm({ category: 'ai', amount: '', label: '', currency_original: '', amount_original: '' });
    if (onDone) onDone();
  };
  return html`<form class="mg-inline-form" onSubmit=${submit}>
    <${Select} value=${form.category} options=${labels.cost_category} onChange=${(v) => setForm((f) => ({ ...f, category: v }))}/>
    <input class="input" placeholder="Valor em R$" value=${form.amount} onInput=${set('amount')} inputmode="decimal" required/>
    <input class="input" placeholder="Descrição (OpenRouter, Contabo…)" value=${form.label} onInput=${set('label')}/>
    <input class="input xs" placeholder="USD" value=${form.currency_original} onInput=${set('currency_original')} maxlength="3"/>
    <input class="input xs" placeholder="valor orig." value=${form.amount_original} onInput=${set('amount_original')} inputmode="decimal"/>
    <button class="btn sm" type="submit">Lançar</button>
  </form>`;
}

function AdhocForm({ period, clientId, act }) {
  const [form, setForm] = useState({ amount: '', due_on: '', note: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = async (event) => {
    event.preventDefault();
    const cents = brlToCents(form.amount);
    if (Number.isNaN(cents) || !form.due_on) return;
    await act('charge-adhoc', { client_id: clientId, period, amount_cents: cents, due_on: form.due_on, note: form.note }, 'Cobrança avulsa criada');
    setForm({ amount: '', due_on: '', note: '' });
  };
  return html`<form class="mg-inline-form" onSubmit=${submit}>
    <input class="input" placeholder="Valor em R$" value=${form.amount} onInput=${set('amount')} inputmode="decimal" required/>
    <input class="input" type="date" value=${form.due_on} onInput=${set('due_on')} required/>
    <input class="input" placeholder="Motivo (horas extras, ajuste…)" value=${form.note} onInput=${set('note')}/>
    <button class="btn sm" type="submit">Cobrança avulsa</button>
  </form>`;
}

function ClientBlock({ row, period, labels, act, today, go }) {
  const [open, setOpen] = useState(row.overdue || row.charges.some((c) => c.status === 'expected'));
  return html`<div class=${'mg-fin-client' + (open ? ' open' : '')}>
    <button class="mg-fin-head" onClick=${() => setOpen((v) => !v)} aria-expanded=${open}>
      <span class="mg-fin-name"><b>${row.company || row.name}</b><small>${labels.client_status[row.status]}${row.overdue ? ' · em atraso' : ''}</small></span>
      <span class="mg-fin-num"><small>Recebido</small><b class="mono">${money(row.received_cents)}</b></span>
      <span class="mg-fin-num"><small>Custos</small><b class="mono">${money(row.costs_cents)}</b></span>
      <span class="mg-fin-num"><small>Margem</small><b class=${'mono' + (row.margin_cents < 0 ? ' neg' : '')}>${money(row.margin_cents)}</b></span>
      <span class="mg-arrow">${open ? '−' : '+'}</span>
    </button>
    ${open ? html`<div class="mg-fin-body">
      <div class="mg-fin-section">
        <div class="mg-fin-section-head"><b>Cobranças</b><button class="text-action" onClick=${() => go(`client/${row.client_id}`)}>ficha do cliente →</button></div>
        ${row.charges.length ? html`<table class="plain mg-table compact"><tbody>${row.charges.map((c) => html`<${ChargeRow} key=${c.id} charge=${c} labels=${labels} act=${act} today=${today}/>`)}</tbody></table>`
          : html`<span class="mg-muted">Sem cobrança nesta competência${row.status !== 'active' ? ' (cliente não está ativo)' : ''}.</span>`}
        <${AdhocForm} period=${period} clientId=${row.client_id} act=${act}/>
      </div>
      <div class="mg-fin-section">
        <div class="mg-fin-section-head"><b>Custos</b></div>
        ${row.costs.length ? html`<table class="plain mg-table compact"><tbody>${row.costs.map((c) => html`<${CostRow} key=${c.id} cost=${c} labels=${labels} act=${act}/>`)}</tbody></table>`
          : html`<span class="mg-muted">Nenhum custo lançado. Crie um plano recorrente abaixo ou lance aqui.</span>`}
        <${CostForm} period=${period} clientId=${row.client_id} labels=${labels} act=${act}/>
      </div>
    </div>` : null}
  </div>`;
}

function PlansCard({ data, period, labels, act }) {
  const [form, setForm] = useState({ client_id: '', category: 'vps', amount: '', label: '', active_from: period });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const clients = Object.fromEntries(data.clients.map((c) => [String(c.client_id), c.company || c.name]));
  const submit = async (event) => {
    event.preventDefault();
    const cents = brlToCents(form.amount);
    if (Number.isNaN(cents)) return;
    await act('cost-plan-upsert', {
      client_id: form.client_id ? Number(form.client_id) : null, category: form.category, monthly_cents: cents,
      label: form.label, active_from: form.active_from || period,
    }, 'Plano de custo criado');
    setForm({ client_id: '', category: 'vps', amount: '', label: '', active_from: period });
  };
  const plans = data.all_cost_plans || [];
  return html`<${Card} title="Custos recorrentes" sub="Planos viram lançamento previsto ao abrir cada competência; ajuste o valor real no fechamento. Sem cliente é custo compartilhado da operação.">
    ${plans.length ? html`<table class="plain mg-table compact">
      <thead><tr><th>Cliente</th><th>Categoria</th><th>Descrição</th><th>Mensal</th><th>Vigência</th><th></th></tr></thead>
      <tbody>${plans.map((p) => html`<tr key=${p.id} class=${p.active_to && p.active_to < period ? 'mg-ended' : ''}>
        <td>${p.client_name || html`<span class="tag">compartilhado</span>`}</td>
        <td>${labels.cost_category[p.category]}</td>
        <td>${p.label || '—'}</td>
        <td class="mono">${money(p.monthly_cents)}</td>
        <td class="mono">${p.active_from}${p.active_to ? ` → ${p.active_to}` : ' →'}</td>
        <td class="mg-actions">${!p.active_to ? html`<button class="text-action" onClick=${() => act('cost-plan-end', { id: p.id, active_to: period }, `Plano encerrado em ${period}`)}>encerrar em ${period}</button>` : null}</td>
      </tr>`)}</tbody>
    </table>` : html`<${Empty}>Nenhum plano recorrente. Cadastre VPS, domínio e IA por cliente para a margem sair sozinha.</${Empty}>`}
    <form class="mg-inline-form" onSubmit=${submit}>
      <${Select} value=${form.client_id} options=${clients} allowEmpty=${true} emptyLabel="Compartilhado" onChange=${(v) => setForm((f) => ({ ...f, client_id: v }))}/>
      <${Select} value=${form.category} options=${labels.cost_category} onChange=${(v) => setForm((f) => ({ ...f, category: v }))}/>
      <input class="input" placeholder="R$ por mês" value=${form.amount} onInput=${set('amount')} inputmode="decimal" required/>
      <input class="input" placeholder="Descrição" value=${form.label} onInput=${set('label')}/>
      <input class="input xs" type="month" value=${form.active_from} onInput=${set('active_from')}/>
      <button class="btn sm primary" type="submit">Criar plano</button>
    </form>
  </${Card}>`;
}

export default function Finance({ config, setToast, go }) {
  const [period, setPeriod] = useState(currentPeriod());
  const resource = useApi(`/api/management/finance?period=${period}`, { every: 60000 });
  const labels = labelsOf(config);
  const data = resource.data;
  const today = new Date().toISOString().slice(0, 10);

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

  const categories = data ? Object.entries(data.costs_by_category).filter(([, v]) => v > 0) : [];
  return html`<div class="mg-page">
    <${ErrorBox} error=${resource.error}/>
    <div class="mg-toolbar">
      <div class="mg-period">
        <button class="btn sm" onClick=${() => setPeriod(shiftPeriod(period, -1))} aria-label="Mês anterior">←</button>
        <input class="input" type="month" value=${period} onInput=${(e) => e.target.value && setPeriod(e.target.value)}/>
        <button class="btn sm" onClick=${() => setPeriod(shiftPeriod(period, 1))} aria-label="Próximo mês">→</button>
        <span class="mg-muted">${periodLabel(period)}${period === currentPeriod() ? ' · mês atual' : ''}</span>
      </div>
      ${data && (data.created.monthly || data.created.setup || data.created.costs) ? html`<span class="tag mint">competência aberta agora: ${data.created.monthly + data.created.setup} cobranças, ${data.created.costs} custos previstos</span>` : null}
    </div>

    <div class="grid c3 mg-tiles">
      <div class="card tile dark"><span class="k">MRR</span><span class="v">${data ? money(data.mrr_cents) : '—'}</span><span class="s">${data ? `${data.active_clients} cliente${data.active_clients === 1 ? '' : 's'} ativo${data.active_clients === 1 ? '' : 's'}` : ''}</span></div>
      <div class="card tile"><span class="k">Recebido no mês</span><span class="v green">${data ? money(data.received_cents) : '—'}</span><span class="s">${data ? `previsto ainda em aberto ${money(data.expected_cents)}` : ''}</span></div>
      <div class="card tile"><span class="k">Em atraso</span><span class=${'v' + (data && data.overdue_cents ? ' warn' : '')}>${data ? money(data.overdue_cents) : '—'}</span><span class="s">${data ? `${data.overdue_count} cobrança${data.overdue_count === 1 ? '' : 's'} desta competência` : ''}</span></div>
      <div class="card tile"><span class="k">Custos</span><span class="v">${data ? money(data.costs_cents) : '—'}</span><span class="s">${data ? `compartilhados ${money(data.shared_costs_cents)}` : ''}</span></div>
      <div class="card tile"><span class="k">Margem</span><span class=${'v' + (data && data.margin_cents < 0 ? ' warn' : ' green')}>${data ? money(data.margin_cents) : '—'}</span><span class="s">recebido − todos os custos</span></div>
      <div class="card tile"><span class="k">Custos por categoria</span><div class="mg-cat-list">${categories.length ? categories.map(([cat, v]) => html`<span key=${cat}><small>${labels.cost_category[cat]}</small><b class="mono">${money(v)}</b></span>`) : html`<span class="mg-muted">nenhum custo no mês</span>`}</div></div>
    </div>

    ${data && data.overdue_all.some((c) => c.period !== period) ? html`<${Card} title="Atrasadas de outras competências" className="mg-overdue">
      <table class="plain mg-table compact"><tbody>${data.overdue_all.filter((c) => c.period !== period).map((c) => html`<tr key=${c.id}>
        <td><b>${c.client_name}</b></td><td class="mono">${c.period}</td><td>${labels.charge_kind[c.kind]}</td><td>${civil(c.due_on)}</td><td class="mono">${money(c.amount_cents)}</td>
        <td class="mg-actions"><button class="btn sm" onClick=${() => act('charge-pay', { id: c.id, paid_on: today }, 'Recebimento registrado')}>Receber hoje</button><button class="text-action" onClick=${() => act('charge-cancel', { id: c.id }, 'Cobrança cancelada')}>cancelar</button></td>
      </tr>`)}</tbody></table>
    </${Card}>` : null}

    <${Card} title="Por cliente" sub="Cobranças e custos da competência. Clique no cliente para abrir.">
      ${data && data.clients.length === 0 ? html`<${Empty}>Nenhum cliente com movimento nesta competência.</${Empty}>` : null}
      <div class="mg-fin-list">${data ? data.clients.map((row) => html`<${ClientBlock} key=${row.client_id} row=${row} period=${period} labels=${labels} act=${act} today=${today} go=${go}/>`) : null}</div>
    </${Card}>

    <${Card} title="Custos compartilhados" sub="Domínio raiz, ferramentas e provider comum. Entram na margem total, não na de um cliente.">
      ${data && data.shared_costs.length ? html`<table class="plain mg-table compact"><tbody>${data.shared_costs.map((c) => html`<${CostRow} key=${c.id} cost=${c} labels=${labels} act=${act}/>`)}</tbody></table>` : null}
      <${CostForm} period=${period} clientId=${null} labels=${labels} act=${act}/>
    </${Card}>

    ${data ? html`<${PlansCard} data=${data} period=${period} labels=${labels} act=${act}/>` : null}
  </div>`;
}
