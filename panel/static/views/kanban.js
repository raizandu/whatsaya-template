import { useState, useEffect, useRef } from 'preact/hooks';
import { html, useApi, post, Icon, ErrorBox } from '../lib.js';

const normalizeSearch = (value) => String(value || '')
  .normalize('NFD')
  .replace(/\p{M}/gu, '')
  .toLocaleLowerCase('pt-BR')
  .replace(/[^\p{L}\p{N}]+/gu, '');

export default function Kanban({ setToast, go }) {
  const leads = useApi('/api/leads', { every: 30000 });
  const [query, setQuery] = useState('');
  const [collapsedStages, setCollapsedStages] = useState({});
  const [compactMode, setCompactMode] = useState(() => {
    try { return localStorage.getItem('whatsaya_kanban_compact') === '1'; } catch (_) { return false; }
  });
  const [activeStageId, setActiveStageId] = useState(null);
  const kanbanRef = useRef(null);

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

  useEffect(() => {
    if (!activeStageId && stages.length > 0) {
      setActiveStageId(stages[0].id);
    }
  }, [stages, activeStageId]);

  const toggleCompact = () => {
    const next = !compactMode;
    setCompactMode(next);
    try { localStorage.setItem('whatsaya_kanban_compact', next ? '1' : '0'); } catch (_) {}
  };

  const toggleStage = (stageId) => {
    setCollapsedStages((prev) => ({
      ...prev,
      [stageId]: !prev[stageId]
    }));
  };

  const scrollToStage = (stageId) => {
    setActiveStageId(stageId);
    const el = document.getElementById(`kanban-col-${stageId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
    }
  };

  const handleKanbanScroll = () => {
    if (!kanbanRef.current) return;
    const container = kanbanRef.current;
    const scrollLeft = container.scrollLeft;
    let closestId = null;
    let minDiff = Infinity;
    stages.forEach((st) => {
      const el = document.getElementById(`kanban-col-${st.id}`);
      if (el) {
        const diff = Math.abs(el.offsetLeft - container.offsetLeft - scrollLeft);
        if (diff < minDiff) {
          minDiff = diff;
          closestId = st.id;
        }
      }
    });
    if (closestId && closestId !== activeStageId) {
      setActiveStageId(closestId);
    }
  };

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
      ${l ? html`<div style="display:flex;gap:8px">${l.pipeline !== 'default'
        ? html`<span class="chip mint">${l.excluded ? l.excluded.outside_funnel : 0} ${l.excluded_label || 'fora do funil'}</span>`
        : html`<span class="chip mint">${l.terminal.won} ganhos</span><span class="chip">${l.terminal.lost} perdidos</span>`}</div>` : null}
    </div>

    <div class="kanban-tools">
      <label class="kanban-search">
        <span>Buscar</span>
        <input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/>
      </label>
      <div class="kanban-tools-actions">
        <button
          type="button"
          class=${'btn sm' + (compactMode ? ' active' : '')}
          onClick=${toggleCompact}
          title=${compactMode ? 'Mudar para visualização detalhada' : 'Mudar para visualização compacta'}
        >
          <i class=${`fi fi-rr-${compactMode ? 'apps' : 'list'}`} aria-hidden="true"></i>
          <span>${compactMode ? 'Cards compactos' : 'Cards detalhados'}</span>
        </button>
        <span class="kanban-result" aria-live="polite">${l ? `${visibleCount} ${visibleCount === 1 ? 'lead encontrado' : 'leads encontrados'}` : 'Carregando leads…'}</span>
      </div>
    </div>

    ${stages.length > 1 ? html`<div class="kanban-stage-tabs" aria-label="Navegação rápida de etapas">
      ${stages.map((stage) => {
        const isActive = stage.id === activeStageId;
        return html`<button
          key=${stage.id}
          type="button"
          class=${'kanban-stage-tab' + (isActive ? ' active' : '')}
          aria-current=${isActive ? 'true' : null}
          onClick=${() => scrollToStage(stage.id)}
        >
          <span>${stage.label}</span>
          <b>${stage.cards.length}</b>
        </button>`;
      })}
    </div>` : null}

    ${l && normalizedQuery && visibleCount === 0 ? html`<div class="kanban-no-results">Nenhum contato corresponde a “${query.trim()}”.</div>` : null}

    <div
      ref=${kanbanRef}
      class="kanban"
      style=${`--kanban-cols:${Math.max(1, stages.length)}`}
      onScroll=${handleKanbanScroll}
    >
      ${stages.map((col) => {
        const isCollapsed = Boolean(collapsedStages[col.id]);
        return html`<div
          id=${`kanban-col-${col.id}`}
          class=${'column' + (col.terminal ? ' terminal' : '') + (isCollapsed ? ' collapsed' : '')}
          key=${col.id}
        >
          <div
            class="column-head clickable"
            role="button"
            tabIndex="0"
            title=${isCollapsed ? 'Clique para expandir etapa' : 'Clique para recolher etapa'}
            onClick=${() => toggleStage(col.id)}
            onKeyDown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleStage(col.id); } }}
          >
            <span class="t">${col.label}</span>
            <div style="display:flex;align-items:center;gap:6px">
              <span class="badge">${col.cards.length}</span>
              <i class=${`fi fi-rr-angle-small-${isCollapsed ? 'down' : 'up'}`} style="font-size:14px;color:var(--muted)"></i>
            </div>
          </div>

          ${isCollapsed ? html`<button
            type="button"
            class="column-expand-btn"
            onClick=${() => toggleStage(col.id)}
          >
            Expandir etapa (${col.cards.length})
          </button>` : col.cards.map((card) => html`<div
            class=${'lead-card clickable' + (compactMode ? ' compact' : '')}
            key=${card.chat_id}
            role="button"
            tabIndex="0"
            onClick=${() => go(`lead/${encodeURIComponent(card.chat_id)}`)}
            onKeyDown=${(event) => { if (event.key === 'Enter' || event.key === ' ') go(`lead/${encodeURIComponent(card.chat_id)}`); }}
          >
            <div class="top">
              <span class="name">${card.name}</span>
              <span class=${'tag ' + (card.human ? 'orange' : 'mint')}>${card.human ? 'Humano' : 'IA'}</span>
              ${compactMode ? html`<div class="compact-actions" style="margin-left:auto;display:flex;gap:4px">
                <button
                  class="icon-btn xs"
                  title="Etapa anterior"
                  onClick=${(event) => { event.stopPropagation(); move(card, -1); }}
                ><${Icon.left}/></button>
                <button
                  class="icon-btn xs primary"
                  title="Próxima etapa"
                  onClick=${(event) => { event.stopPropagation(); move(card, 1); }}
                ><${Icon.right}/></button>
              </div>` : null}
            </div>

            ${!compactMode ? html`
              <span class="preview">${card.preview || card.phone}</span>
              ${card.next_followup ? html`<span class="fu"><span class=${'dot ' + (card.automation ? 'ok' : 'warn')} style="width:7px;height:7px"></span>${card.automation ? `toque ${card.next_followup}` : 'follow-up pausado'}</span>` : null}
              <div class="foot">
                <span class="when">${card.last}</span>
                <div style="display:flex;gap:4px">
                  <button class="icon-btn" title="Etapa anterior" onClick=${(event) => { event.stopPropagation(); move(card, -1); }}><${Icon.left}/></button>
                  <button class="icon-btn primary" title="Próxima etapa" onClick=${(event) => { event.stopPropagation(); move(card, 1); }}><${Icon.right}/></button>
                </div>
              </div>
            ` : null}
          </div>`)}
        </div>`;
      })}
    </div>`;
}

