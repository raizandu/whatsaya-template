// Financeiro da carteira, por competência: MRR, cobranças (baixa manual),
// custos por cliente e compartilhados, planos de custo recorrentes e margem.
// Abrir a competência já materializa mensalidade e planos (idempotente, no
// servidor). Nada aqui fala com gateway de pagamento.
import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, ErrorBox, Empty, Menu, Select } from '../lib.js';

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
const monthShort = (m) => ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][m - 1] || '';
const nextRenewalLabel = (activeFrom, renewalMonth, currentPeriod) => {
  if (!renewalMonth) {
    renewalMonth = Number(activeFrom.split('-')[1]) || 1;
  }
  const [currY, currM] = currentPeriod.split('-').map(Number);
  let targetY = currY;
  if (currM > renewalMonth) {
    targetY += 1;
  }
  return `${targetY}-${String(renewalMonth).padStart(2, '0')}`;
};

const RENEWAL_MONTHS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
  .map((label, index) => ({ value: String(index + 1), label: `Renova: ${label}` }));
const PERIODICITIES = [
  { value: 'monthly', label: 'Mensal' },
  { value: 'annual', label: 'Anual (renovação 1x/ano)' },
  { value: 'annual_amortized', label: 'Anual amortizado (12x)' },
];

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
      ? html`<button class="btn sm" onClick=${() => act('charge-pay', { id: charge.id, paid_on: today }, 'Recebimento registrado')}>Receber hoje</button><${Menu} label="Mais ações da cobrança" size="sm" items=${[
          { label: 'Cancelar cobrança', icon: 'cross-circle', danger: true, onClick: () => act('charge-cancel', { id: charge.id }, 'Cobrança cancelada') },
        ]}/>`
      : html`<${Menu} label="Mais ações da cobrança" size="sm" items=${[
          { label: 'Desfazer', icon: 'undo', onClick: () => act('charge-reopen', { id: charge.id }, 'Cobrança reaberta') },
        ]}/>`}</td>
  </tr>`;
}

function CostRow({ cost, labels, act, today }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const save = async (event) => {
    event.preventDefault();
    const cents = brlToCents(value);
    if (Number.isNaN(cents)) return;
    await act('cost-upsert', { id: cost.id, amount_cents: cents }, 'Custo ajustado');
    setEditing(false);
  };
  const periodicity = cost.periodicity || cost.plan_periodicity || 'one_off';
  const tag = periodicity === 'annual'
    ? html`<span class="tag amber" title="Cobrança anual">anual</span>`
    : periodicity === 'annual_amortized'
    ? html`<span class="tag" title="Rateio mensal em 12x">amortizado</span>`
    : periodicity === 'monthly'
    ? html`<span class="tag mint" title="Cobrança mensal recorrente">mensal</span>`
    : html`<span class="tag" title="Desembolso avulso nesta competência">avulso</span>`;

  const statusTag = cost.status === 'paid'
    ? html`<span class="tag mint" title=${`Pago em ${civil(cost.paid_on)}`}>pago ${civil(cost.paid_on)}</span>`
    : cost.overdue
    ? html`<span class="tag orange" title=${`Vencido em ${civil(cost.due_on)}`}>vencido ${civil(cost.due_on)}</span>`
    : html`<span class="tag amber" title="Aguardando pagamento">a pagar${cost.due_on ? ` · vence ${civil(cost.due_on)}` : ''}</span>`;

  return html`<tr>
    <td>${labels.cost_category[cost.category] || cost.category}</td>
    <td>
      <div style="display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap;">
        <span>${cost.label || '—'}</span>
        ${tag}
        ${cost.source === 'plan' && periodicity === 'annual' ? html`<small class="mg-muted"> · renovação anual</small>` : null}
        ${cost.source === 'plan' && periodicity === 'annual_amortized' ? html`<small class="mg-muted"> · 1/12 de ${money(cost.plan_amount_cents || cost.amount_cents * 12)}/ano</small>` : null}
        ${cost.currency_original && cost.amount_original ? html`<small class="mg-muted"> · ${cost.amount_original} ${cost.currency_original}</small>` : null}
      </div>
    </td>
    <td class="mono">${editing
      ? html`<form class="form-row" onSubmit=${save}><input class="input sm" value=${value} placeholder=${(cost.amount_cents / 100).toFixed(2).replace('.', ',')} onInput=${(e) => setValue(e.target.value)} inputmode="decimal" autofocus/><button class="btn sm" type="submit">Salvar</button><button class="text-action" type="button" onClick=${() => setEditing(false)}>cancelar</button></form>`
      : money(cost.amount_cents)}</td>
    <td>${statusTag}</td>
    <td class="mg-actions">
      ${cost.status === 'pending'
        ? html`<button class="btn sm primary" onClick=${() => act('cost-pay', { id: cost.id, paid_on: today }, 'Custo marcado como pago')}><i class="fi fi-rr-check" aria-hidden="true"></i>Pagar</button>`
        : null}
      <${Menu} label="Mais ações do custo" size="sm" items=${[
        ...(cost.status === 'pending' ? [] : [{ label: 'Desfazer pagamento', icon: 'undo', onClick: () => act('cost-reopen', { id: cost.id }, 'Pagamento desfeito') }]),
        ...(editing ? [] : [{ label: 'Ajustar valor', icon: 'pencil', onClick: () => { setValue(''); setEditing(true); } }]),
        'separator',
        { label: 'Remover custo', icon: 'trash', danger: true, onClick: () => act('cost-delete', { id: cost.id }, 'Custo removido') },
      ]}/>
    </td>
  </tr>`;
}

function CostForm({ period, clientId, labels, act, onDone }) {
  const [form, setForm] = useState({ category: 'ai', amount: '', label: '', due_on: '', currency_original: '', amount_original: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = async (event) => {
    event.preventDefault();
    const cents = brlToCents(form.amount);
    if (Number.isNaN(cents)) return;
    const body = { client_id: clientId, period, category: form.category, amount_cents: cents, label: form.label, due_on: form.due_on || null };
    if (form.currency_original && form.amount_original) {
      body.currency_original = form.currency_original;
      body.amount_original = Number(String(form.amount_original).replace(',', '.'));
    }
    await act('cost-upsert', body, 'Custo lançado');
    setForm({ category: 'ai', amount: '', label: '', due_on: '', currency_original: '', amount_original: '' });
    if (onDone) onDone();
  };
  return html`<form class="mg-inline-form" onSubmit=${submit}>
    <${Select} value=${form.category} options=${labels.cost_category} onChange=${(v) => setForm((f) => ({ ...f, category: v }))}/>
    <input class="input" placeholder="Valor em R$" value=${form.amount} onInput=${set('amount')} inputmode="decimal" required/>
    <input class="input" placeholder="Descrição (OpenRouter, Contabo…)" value=${form.label} onInput=${set('label')}/>
    <input class="input sm" type="date" value=${form.due_on} onInput=${set('due_on')} title="Vencimento (opcional)"/>
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

function CashCard({ cash, labels, act, today }) {
  const [editing, setEditing] = useState(false);
  const [balance, setBalance] = useState('');
  const [calDate, setCalDate] = useState(today);
  const [note, setNote] = useState('');

  if (!cash) return null;

  const submitCalibrate = async (event) => {
    event.preventDefault();
    const cents = brlToCents(balance);
    if (Number.isNaN(cents)) return;
    await act('cash-calibrate', { balance_cents: cents, calibrated_on: calDate, note }, 'Saldo da conta atualizado');
    setEditing(false);
    setBalance('');
    setNote('');
  };

  if (!cash.has_calibration) {
    return html`<div class="card mg-cash-banner-uncalibrated">
      <div>
        <div style="font-weight: 700; font-size: 15px; margin-bottom: 4px; display: flex; align-items: center; gap: 8px;">
          <span>🏦</span> Controle de Caixa e Saldo Bancário
        </div>
        <div class="mg-muted">Defina o saldo atual da sua conta bancária para iniciar o acompanhamento de caixa em tempo real e conciliação de pagamentos.</div>
      </div>
      <form class="mg-inline-form" onSubmit=${submitCalibrate}>
        <input class="input" placeholder="R$ 10.000,00" value=${balance} onInput=${(e) => setBalance(e.target.value)} inputmode="decimal" required style="max-width: 160px;"/>
        <input class="input sm" placeholder="Nota (ex: Inter PJ)" value=${note} onInput=${(e) => setNote(e.target.value)}/>
        <button class="btn sm primary" type="submit">Definir saldo inicial</button>
      </form>
    </div>`;
  }

  const latest = cash.latest_calibration || {};

  return html`<div class="card mg-cash-card">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap;">
      <div>
        <div style="font-weight: 700; font-size: 16px; letter-spacing: -0.01em; display: flex; align-items: center; gap: 8px;">
          <span>🏦</span> Caixa & Saldo Bancário
        </div>
        <small class="mg-muted">
          Saldo real conciliado · base ajustada em ${civil(latest.calibrated_on)}${latest.note ? ` (${latest.note})` : ''}
        </small>
      </div>
      <div>
        <button class="btn sm" type="button" onClick=${() => { setBalance((cash.current_balance_cents / 100).toFixed(2).replace('.', ',')); setCalDate(today); setEditing(!editing); }}>
          ${editing ? 'Fechar ajuste' : '⚙ Ajustar saldo'}
        </button>
      </div>
    </div>

    ${editing ? html`
      <form class="mg-cash-adjust-form" onSubmit=${submitCalibrate}>
        <div style="font-weight: 600; font-size: 13px; margin-bottom: 6px;">Calibrar saldo com o extrato bancário:</div>
        <div class="mg-inline-form">
          <input class="input" placeholder="Novo saldo (R$)" value=${balance} onInput=${(e) => setBalance(e.target.value)} inputmode="decimal" required style="max-width: 160px;"/>
          <input class="input sm" type="date" value=${calDate} onInput=${(e) => setCalDate(e.target.value)} required title="Data da verificação no banco"/>
          <input class="input" placeholder="Motivo / Conta (ex: Rendimento CDI, Banco Inter…)" value=${note} onInput=${(e) => setNote(e.target.value)}/>
          <button class="btn sm primary" type="submit">Salvar novo saldo</button>
          <button class="text-action" type="button" onClick=${() => setEditing(false)}>cancelar</button>
        </div>
      </form>
    ` : null}

    <div class="mg-cash-grid">
      <div class="mg-cash-metric">
        <span class="k">Saldo Atual em Conta</span>
        <span class="v">${money(cash.current_balance_cents)}</span>
        <span class="s">disponível hoje em caixa</span>
      </div>
      <div class="mg-cash-metric">
        <span class="k">A Pagar no Mês</span>
        <span class="v warn">${money(cash.pending_costs_cents)}</span>
        <span class="s">despesas em aberto</span>
      </div>
      <div class="mg-cash-metric">
        <span class="k">A Receber no Mês</span>
        <span class="v">${money(cash.pending_charges_cents)}</span>
        <span class="s">cobranças previstas</span>
      </div>
      <div class="mg-cash-metric">
        <span class="k">Saldo Previsto (Fim do Mês)</span>
        <span class=${'v' + (cash.projected_balance_cents < 0 ? ' warn' : ' green')}>${money(cash.projected_balance_cents)}</span>
        <span class="s">após pagar e receber tudo</span>
      </div>
    </div>

    <div class="mg-cash-footer">
      <span>Movimentação realizada da competência:</span>
      <span class="mono">Entradas <b>${money(cash.cash_inflow_cents)}</b></span>
      <span class="mg-muted">−</span>
      <span class="mono">Saídas <b>${money(cash.cash_outflow_cents)}</b></span>
      <span class="mg-muted">=</span>
      <span class=${'mono ' + (cash.cash_net_cents < 0 ? 'neg' : 'pos')}>Fluxo líquido <b>${money(cash.cash_net_cents)}</b></span>
    </div>
  </div>`;
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
        ${row.costs.length ? html`<table class="plain mg-table compact">
          <thead><tr><th>Categoria</th><th>Descrição</th><th>Valor no mês</th><th>Status</th><th></th></tr></thead>
          <tbody>${row.costs.map((c) => html`<${CostRow} key=${c.id} cost=${c} labels=${labels} act=${act} today=${today}/>`)}</tbody>
        </table>`
          : html`<span class="mg-muted">Nenhum custo lançado. Crie um plano recorrente abaixo ou lance aqui.</span>`}
        <${CostForm} period=${period} clientId=${row.client_id} labels=${labels} act=${act}/>
      </div>
    </div>` : null}
  </div>`;
}

function SharedCostsCard({ data, period, labels, act, today }) {
  const sharedCosts = (data && data.shared_costs) || [];
  const allPlans = (data && data.all_cost_plans) || [];
  const sharedPlans = allPlans.filter((p) => p.client_id === null || p.client_id === undefined);
  const [formType, setFormType] = useState('annual');
  const [form, setForm] = useState({
    category: 'domain',
    amount: '',
    label: '',
    due_on: '',
    due_day: '',
    renewal_month: String(Number(period.split('-')[1])),
    active_from: period,
    currency_original: '',
    amount_original: '',
  });

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    const cents = brlToCents(form.amount);
    if (Number.isNaN(cents)) return;

    if (formType === 'one_off') {
      const body = {
        client_id: null,
        period,
        category: form.category,
        amount_cents: cents,
        periodicity: 'one_off',
        label: form.label,
        due_on: form.due_on || null,
      };
      if (form.currency_original && form.amount_original) {
        body.currency_original = form.currency_original;
        body.amount_original = Number(String(form.amount_original).replace(',', '.'));
      }
      await act('cost-upsert', body, 'Custo avulso compartilhado lançado');
    } else {
      const body = {
        client_id: null,
        category: form.category,
        amount_cents: cents,
        periodicity: formType,
        label: form.label,
        active_from: form.active_from || period,
      };
      if (form.due_day) {
        body.due_day = Number(form.due_day);
      }
      if (formType === 'annual') {
        body.renewal_month = Number(form.renewal_month) || Number(period.split('-')[1]);
      }
      await act('cost-plan-upsert', body, formType === 'annual' ? 'Custo anual compartilhado cadastrado' : 'Plano de custo compartilhado criado');
    }
    setForm((f) => ({ ...f, amount: '', label: '', due_on: '', due_day: '', currency_original: '', amount_original: '' }));
  };

  return html`<${Card} title="Custos compartilhados da operação" sub="Custos gerais (domínio raiz, VPS comum, IA base e ferramentas). Entram na margem total do negócio.">
    ${sharedCosts.length ? html`
      <div style="margin-bottom: 6px; font-weight: 600; font-size: 13px;">
        Lançamentos desta competência (${periodLabel(period)})
      </div>
      <table class="plain mg-table compact" style="margin-bottom: 16px;">
        <thead>
          <tr><th>Categoria</th><th>Descrição</th><th>Valor no mês</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>${sharedCosts.map((c) => html`<${CostRow} key=${c.id} cost=${c} labels=${labels} act=${act} today=${today}/>`)}</tbody>
      </table>
    ` : html`
      <div class="mg-muted" style="margin-bottom: 14px; padding: 10px 12px; background: var(--soft); border-radius: var(--radius-sm);">
        Nenhum desembolso compartilhado lançado na competência de ${periodLabel(period)}.
      </div>
    `}

    ${sharedPlans.length ? html`
      <div style="margin-top: 10px; margin-bottom: 14px; border-top: 1px solid var(--line); padding-top: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
          <span style="font-weight: 600; font-size: 13px;">Planos e custos fixos da operação (${sharedPlans.length})</span>
          <span class="mg-muted">Domínios anuais, servidores e assinaturas operacionais</span>
        </div>
        <table class="plain mg-table compact">
          <thead>
            <tr>
              <th>Categoria</th>
              <th>Descrição</th>
              <th>Recorrência / Valor</th>
              <th>Próxima cobrança</th>
              <th>Vigência</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${sharedPlans.map((p) => {
              const periodicity = p.periodicity || 'monthly';
              const rMonth = p.renewal_month || Number(p.active_from.split('-')[1]) || 1;
              const nextPeriod = periodicity === 'annual' ? nextRenewalLabel(p.active_from, rMonth, period) : null;
              const isDueThisMonth = periodicity === 'annual' && period.endsWith(`-${String(rMonth).padStart(2, '0')}`);

              return html`<tr key=${p.id} class=${p.active_to && p.active_to < period ? 'mg-ended' : ''}>
                <td>${labels.cost_category[p.category] || p.category}</td>
                <td><b>${p.label || '—'}</b>${p.due_day ? html`<small class="mg-muted"> · vcto dia ${p.due_day}</small>` : null}</td>
                <td>
                  ${periodicity === 'annual'
                    ? html`<span class="tag amber">anual</span> <b>${money(p.amount_cents || p.monthly_cents * 12)}</b>/ano`
                    : periodicity === 'annual_amortized'
                    ? html`<span class="tag">amortizado</span> <b>${money(p.monthly_cents)}</b>/mês <small class="mg-muted">(${money(p.amount_cents || p.monthly_cents * 12)}/ano)</small>`
                    : html`<span class="tag mint">mensal</span> <b>${money(p.monthly_cents || p.amount_cents)}</b>/mês`}
                </td>
                <td>
                  ${periodicity === 'annual'
                    ? html`<span>${isDueThisMonth ? html`<span class="tag orange">vence este mês</span>` : `em ${monthShort(rMonth)} (${nextPeriod})`}</span>`
                    : periodicity === 'annual_amortized'
                    ? html`<span class="mg-muted">rateado todo mês</span>`
                    : html`<span class="mg-muted">todo mês${p.due_day ? ` (dia ${p.due_day})` : ''}</span>`}
                </td>
                <td class="mono">${p.active_from}${p.active_to ? ` → ${p.active_to}` : ' →'}</td>
                <td class="mg-actions"><${Menu} label="Ações do plano" size="sm" items=${[
                  ...(!p.active_to ? [{ label: `Encerrar em ${period}`, icon: 'calendar-xmark', onClick: () => act('cost-plan-end', { id: p.id, active_to: period }, `Plano encerrado em ${period}`) }, 'separator'] : []),
                  { label: 'Excluir plano', icon: 'trash', danger: true, onClick: () => act('cost-plan-delete', { id: p.id }, 'Plano excluído') },
                ]}/></td>
              </tr>`;
            })}
          </tbody>
        </table>
      </div>
    ` : null}

    <div style="margin-top: 12px; border-top: 1px solid var(--line); padding-top: 12px;">
      <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 10px; flex-wrap: wrap;">
        <span style="font-weight: 600; font-size: 13px;">Adicionar custo compartilhado:</span>
        <div class="mg-chips" style="gap: 4px;">
          <button type="button" class=${formType === 'annual' ? 'active' : ''} onClick=${() => { setFormType('annual'); setForm(f => ({ ...f, category: 'domain' })); }}>
            Anual (renovação 1x/ano)
          </button>
          <button type="button" class=${formType === 'monthly' ? 'active' : ''} onClick=${() => { setFormType('monthly'); setForm(f => ({ ...f, category: 'vps' })); }}>
            Mensal recorrente
          </button>
          <button type="button" class=${formType === 'annual_amortized' ? 'active' : ''} onClick=${() => setFormType('annual_amortized')}>
            Anual amortizado (12x)
          </button>
          <button type="button" class=${formType === 'one_off' ? 'active' : ''} onClick=${() => setFormType('one_off')}>
            Avulso neste mês
          </button>
        </div>
      </div>

      <form class="mg-inline-form" onSubmit=${submit}>
        <${Select} value=${form.category} options=${labels.cost_category} onChange=${(v) => setForm((f) => ({ ...f, category: v }))}/>
        <input class="input" placeholder=${formType === 'annual' || formType === 'annual_amortized' ? 'Valor total anual em R$' : 'Valor em R$'} value=${form.amount} onInput=${set('amount')} inputmode="decimal" required/>
        <input class="input" placeholder="Descrição (ex: Dominio agenteaya.com, Contabo VPS…)" value=${form.label} onInput=${set('label')} required/>
        
        ${formType === 'annual' ? html`
          <${Select} size="sm" value=${form.renewal_month} title="Mês de renovação anual" ariaLabel="Mês de renovação anual" options=${RENEWAL_MONTHS} onChange=${(v) => setForm((f) => ({ ...f, renewal_month: v }))}/>
          <input class="input xs" type="number" min="1" max="31" placeholder="Dia vcto" value=${form.due_day} onInput=${set('due_day')} title="Dia de vencimento (1-31)"/>
          <input class="input xs" type="month" value=${form.active_from} onInput=${set('active_from')} title="Primeiro mês de vigência"/>
        ` : null}

        ${formType === 'monthly' ? html`
          <input class="input xs" type="number" min="1" max="31" placeholder="Dia vcto" value=${form.due_day} onInput=${set('due_day')} title="Dia de vencimento todo mês (1-31)"/>
          <input class="input xs" type="month" value=${form.active_from} onInput=${set('active_from')} title="Início da cobrança mensal"/>
        ` : null}

        ${formType === 'annual_amortized' ? html`
          <input class="input xs" type="month" value=${form.active_from} onInput=${set('active_from')} title="Início do rateio"/>
        ` : null}

        ${formType === 'one_off' ? html`
          <input class="input sm" type="date" value=${form.due_on} onInput=${set('due_on')} title="Vencimento (opcional)"/>
          <input class="input xs" placeholder="USD" value=${form.currency_original} onInput=${set('currency_original')} maxlength="3"/>
          <input class="input xs" placeholder="valor orig." value=${form.amount_original} onInput=${set('amount_original')} inputmode="decimal"/>
        ` : null}

        <button class="btn sm primary" type="submit">
          ${formType === 'annual' ? 'Cadastrar anual' : formType === 'monthly' ? 'Criar plano mensal' : formType === 'annual_amortized' ? 'Criar amortizado' : 'Lançar avulso'}
        </button>
      </form>

      ${formType === 'annual' ? html`
        <div class="mg-muted" style="margin-top: 6px;">
          Cobrado 1x ao ano no mês de renovação (não desconta nos meses intermediários e volta a cobrar daqui a 1 ano automaticamente).
        </div>
      ` : formType === 'annual_amortized' ? html`
        <div class="mg-muted" style="margin-top: 6px;">
          Rateado em 12 parcelas de ~R$ ${(Number(String(form.amount || '0').replace(',', '.')) / 12).toFixed(2).replace('.', ',')}/mês na margem da competência.
        </div>
      ` : null}
    </div>
  </${Card}>`;
}


function PlansCard({ data, period, labels, act }) {
  const [form, setForm] = useState({ client_id: '', category: 'vps', periodicity: 'monthly', amount: '', label: '', due_day: '', active_from: period, renewal_month: String(Number(period.split('-')[1])) });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const clients = Object.fromEntries(data.clients.map((c) => [String(c.client_id), c.company || c.name]));
  const submit = async (event) => {
    event.preventDefault();
    const cents = brlToCents(form.amount);
    if (Number.isNaN(cents)) return;
    const body = {
      client_id: form.client_id ? Number(form.client_id) : null,
      category: form.category,
      amount_cents: cents,
      periodicity: form.periodicity,
      label: form.label,
      active_from: form.active_from || period,
    };
    if (form.due_day) {
      body.due_day = Number(form.due_day);
    }
    if (form.periodicity === 'annual') {
      body.renewal_month = Number(form.renewal_month) || Number(period.split('-')[1]);
    }
    await act('cost-plan-upsert', body, 'Plano de custo criado');
    setForm({ client_id: '', category: 'vps', periodicity: 'monthly', amount: '', label: '', due_day: '', active_from: period, renewal_month: String(Number(period.split('-')[1])) });
  };
  const plans = data.all_cost_plans || [];
  return html`<${Card} title="Todos os planos de custo" sub="Planos da carteira e da operação. Viram lançamento previsto ao abrir cada competência; ajuste o valor real no fechamento.">
    ${plans.length ? html`<table class="plain mg-table compact">
      <thead><tr><th>Cliente</th><th>Categoria</th><th>Descrição</th><th>Periodicidade</th><th>Valor</th><th>Vigência</th><th></th></tr></thead>
      <tbody>${plans.map((p) => {
        const periodicity = p.periodicity || 'monthly';
        return html`<tr key=${p.id} class=${p.active_to && p.active_to < period ? 'mg-ended' : ''}>
          <td>${p.client_name || html`<span class="tag">compartilhado</span>`}</td>
          <td>${labels.cost_category[p.category] || p.category}</td>
          <td>
            ${p.label || '—'}
            ${p.due_day ? html`<small class="mg-muted"> · vcto dia ${p.due_day}</small>` : null}
          </td>
          <td>
            ${periodicity === 'annual' ? html`<span class="tag amber">anual</span>`
              : periodicity === 'annual_amortized' ? html`<span class="tag">amortizado</span>`
              : html`<span class="tag mint">mensal</span>`}
          </td>
          <td class="mono">
            ${periodicity === 'annual'
              ? `${money(p.amount_cents || p.monthly_cents * 12)}/ano`
              : periodicity === 'annual_amortized'
              ? `${money(p.monthly_cents)}/mês (${money(p.amount_cents || p.monthly_cents * 12)}/ano)`
              : money(p.monthly_cents || p.amount_cents)}
          </td>
          <td class="mono">${p.active_from}${p.active_to ? ` → ${p.active_to}` : ' →'}</td>
          <td class="mg-actions"><${Menu} label="Ações do plano" size="sm" items=${[
            ...(!p.active_to ? [{ label: `Encerrar em ${period}`, icon: 'calendar-xmark', onClick: () => act('cost-plan-end', { id: p.id, active_to: period }, `Plano encerrado em ${period}`) }, 'separator'] : []),
            { label: 'Excluir plano', icon: 'trash', danger: true, onClick: () => act('cost-plan-delete', { id: p.id }, 'Plano excluído') },
          ]}/></td>
        </tr>`;
      })}</tbody>
    </table>` : html`<${Empty}>Nenhum plano recorrente. Cadastre VPS, domínio e IA por cliente ou compartilhado.</${Empty}>`}
    <form class="mg-inline-form" onSubmit=${submit}>
      <${Select} value=${form.client_id} options=${clients} allowEmpty=${true} emptyLabel="Compartilhado" onChange=${(v) => setForm((f) => ({ ...f, client_id: v }))}/>
      <${Select} value=${form.category} options=${labels.cost_category} onChange=${(v) => setForm((f) => ({ ...f, category: v }))}/>
      <${Select} size="sm" value=${form.periodicity} ariaLabel="Periodicidade" options=${PERIODICITIES} onChange=${(v) => setForm((f) => ({ ...f, periodicity: v }))}/>
      <input class="input" placeholder=${form.periodicity === 'monthly' ? 'R$ por mês' : 'R$ total por ano'} value=${form.amount} onInput=${set('amount')} inputmode="decimal" required/>
      <input class="input" placeholder="Descrição" value=${form.label} onInput=${set('label')}/>
      ${form.periodicity === 'annual' ? html`
        <${Select} size="xs" value=${form.renewal_month} title="Mês de renovação" ariaLabel="Mês de renovação" options=${RENEWAL_MONTHS} onChange=${(v) => setForm((f) => ({ ...f, renewal_month: v }))}/>
      ` : null}
      <input class="input xs" type="number" min="1" max="31" placeholder="Dia vcto" value=${form.due_day} onInput=${set('due_day')} title="Dia do vencimento no mês (1-31)"/>
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

    <${CashCard} cash=${data ? data.cash : null} labels=${labels} act=${act} today=${today}/>

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

    ${data ? html`<${SharedCostsCard} data=${data} period=${period} labels=${labels} act=${act} today=${today}/>` : null}

    ${data ? html`<${PlansCard} data=${data} period=${period} labels=${labels} act=${act}/>` : null}
  </div>`;
}
