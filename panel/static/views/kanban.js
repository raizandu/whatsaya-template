import { useState } from 'preact/hooks';
import { html, useApi, post, Icon, ErrorBox } from '../lib.js';

const normalizeSearch = (value) => String(value || '')
  .normalize('NFD')
  .replace(/\p{M}/gu, '')
  .toLocaleLowerCase('pt-BR')
  .replace(/[^\p{L}\p{N}]+/gu, '');

export default function Kanban({ setToast, go }) {
  const leads = useApi('/api/leads', { every: 30000 });
  const [query, setQuery] = useState('');
  const l = leads.data;
  const normalizedQuery = normalizeSearch(query);
  const stages = (l ? l.stages : []).map((stage) => ({
    ...stage,
    cards: normalizedQuery
      ? stage.cards.filter((card) => [card.name, card.phone, card.chat_id, card.preview]
        .some((value) => normalizeSearch(value).includes(normalizedQuery)))
      : stage.cards,
  }));
  const visibleCount = stages.reduce((total, stage) => total + stage.cards.length, 0);

  const move = async (card, delta) => {
    const order = l.stages.map((stage) => stage.id);
    const idx = order.indexOf(card.stage);
    const next = order[Math.max(0, Math.min(order.length - 1, idx + delta))];
    if (next === card.stage) return;
    try {
      await post('/api/actions/stage', { chat_id: card.chat_id, stage: next });
      setToast(`${card.name} → ${l.stages.find((s) => s.id === next).label}`);
      leads.reload();
    } catch (err) {
      setToast(`Não movi: ${err.message}`);
    }
  };

  return html`
    <${ErrorBox} error=${leads.error}/>
    <div class="page-head" style="align-items:center">
      <span class="card-sub">Etapa vem do módulo de follow-up. Mover um lead cancela os toques abertos e, fora das etapas finais, a AYA reagenda pela nova etapa.</span>
      ${l ? html`<div style="display:flex;gap:8px">${l.pipeline === 'therapify'
        ? html`<span class="chip mint">${l.excluded ? l.excluded.existing_patients : 0} pacientes</span>`
        : html`<span class="chip mint">${l.terminal.won} ganhos</span><span class="chip">${l.terminal.lost} perdidos</span>`}</div>` : null}
    </div>
    <div class="kanban-tools">
      <label class="kanban-search">
        <span>Buscar</span>
        <input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/>
      </label>
      <span class="kanban-result" aria-live="polite">${l ? `${visibleCount} ${visibleCount === 1 ? 'lead encontrado' : 'leads encontrados'}` : 'Carregando leads…'}</span>
    </div>
    ${l && normalizedQuery && visibleCount === 0 ? html`<div class="kanban-no-results">Nenhum contato corresponde a “${query.trim()}”.</div>` : null}
    <div class="kanban" style=${`--kanban-cols:${Math.max(1, stages.length)}`}>
      ${stages.map((col) => html`<div class=${'column' + (col.terminal ? ' terminal' : '')} key=${col.id}>
        <div class="column-head"><span class="t">${col.label}</span><span class="badge">${col.cards.length}</span></div>
        ${col.cards.map((card) => html`<div class="lead-card clickable" key=${card.chat_id} role="button" tabIndex="0"
          onClick=${() => go(`lead/${encodeURIComponent(card.chat_id)}`)}
          onKeyDown=${(event) => { if (event.key === 'Enter' || event.key === ' ') go(`lead/${encodeURIComponent(card.chat_id)}`); }}>
          <div class="top"><span class="name">${card.name}</span><span class=${'tag ' + (card.human ? 'orange' : 'mint')}>${card.human ? 'Humano' : 'IA'}</span></div>
          <span class="preview">${card.preview || card.phone}</span>
          ${card.next_followup ? html`<span class="fu"><span class=${'dot ' + (card.automation ? 'ok' : 'warn')} style="width:7px;height:7px"></span>${card.automation ? `toque ${card.next_followup}` : 'follow-up pausado'}</span>` : null}
          <div class="foot">
            <span class="when">${card.last}</span>
            <div style="display:flex;gap:4px">
              <button class="icon-btn" title="Etapa anterior" onClick=${(event) => { event.stopPropagation(); move(card, -1); }}><${Icon.left}/></button>
              <button class="icon-btn primary" title="Próxima etapa" onClick=${(event) => { event.stopPropagation(); move(card, 1); }}><${Icon.right}/></button>
            </div>
          </div>
        </div>`)}
      </div>`)}
    </div>`;
}
