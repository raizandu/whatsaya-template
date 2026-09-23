import { useState } from 'preact/hooks';
import { html, useApi, ErrorBox, Empty, Dot, Icon } from '../lib.js';

const TIME_ZONE = 'America/Sao_Paulo';
const WEEKDAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
const MONTH_LONG = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' });
const DATE_LONG = new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
const TIME = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: TIME_ZONE });
const DATE_TIME = new Intl.DateTimeFormat('pt-BR', { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TIME_ZONE });
const pad = (value) => String(value).padStart(2, '0');
const dateKey = (date) => `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
const fromKey = (key) => new Date(`${key}T12:00:00Z`);
const addDays = (key, count) => {
  const date = fromKey(key);
  date.setUTCDate(date.getUTCDate() + count);
  return dateKey(date);
};
const monthFirst = (key) => `${key.slice(0, 7)}-01`;
const monthLast = (key) => {
  const date = fromKey(monthFirst(key));
  date.setUTCMonth(date.getUTCMonth() + 1, 0);
  return dateKey(date);
};
const mondayOf = (key) => {
  const weekday = fromKey(key).getUTCDay() || 7;
  return addDays(key, 1 - weekday);
};
const todayInSaoPaulo = () => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: TIME_ZONE,
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
};
const isoBounds = (start, end) => [
  `${start}T00:00:00-03:00`,
  `${end}T00:00:00-03:00`,
];
const isSameMonth = (a, b) => a.slice(0, 7) === b.slice(0, 7);
const cap = (value) => value ? value[0].toLocaleUpperCase('pt-BR') + value.slice(1) : value;
const formatTime = (value) => value ? TIME.format(new Date(value)) : '—';
const formatDateTime = (value) => value ? cap(DATE_TIME.format(new Date(value))) : '—';
const formatDateLabel = (key) => cap(DATE_LONG.format(fromKey(key)));
const formatMonthLabel = (key) => cap(MONTH_LONG.format(fromKey(monthFirst(key))));
const rangeLabel = (mode, key) => mode === 'month'
  ? formatMonthLabel(key)
  : mode === 'week'
    ? `${fromKey(mondayOf(key)).getUTCDate()}–${fromKey(addDays(mondayOf(key), 6)).getUTCDate()} · ${formatMonthLabel(key)}`
    : formatDateLabel(key);

function eventDay(event) {
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: TIME_ZONE,
  }).format(new Date(event.start));
}

function eventTime(event) {
  if (event.all_day) return 'Dia inteiro';
  return `${formatTime(event.start)}${event.end ? `–${formatTime(event.end)}` : ''}`;
}

function eventStatus(event) {
  return event.status ? ` · ${event.status}` : '';
}

function AppointmentList({ events, selectedDay }) {
  const dayEvents = events.filter((event) => eventDay(event) === selectedDay);
  const groups = [];
  dayEvents.forEach((event) => {
    const name = event.professional_name || 'Profissional não informado';
    const id = event.professional_id;
    let group = groups.find((item) => item.id === id);
    if (!group) { group = { id, name, events: [] }; groups.push(group); }
    group.events.push(event);
  });

  return html`<section class="pv-agenda-day-list" aria-label="Agendamentos do dia">
    <h2>${formatDateLabel(selectedDay)}</h2>
    ${groups.length ? groups.map((group) => html`<section class="pv-agenda-professional-group" key=${group.id}>
      <h3>${group.name}</h3>
      ${group.events.map((event) => html`<article class="pv-agenda-event" key=${event.id}>
        <time>${eventTime(event)}</time>
        <div><b>${event.title || 'Consulta'}</b><small>${event.patient_name || (event.record_number ? `Prontuário nº ${event.record_number}` : 'Paciente')}</small></div>
        ${event.status ? html`<span>${event.status}</span>` : null}
      </article>`)}
    </section>`) : html`<${Empty}>Nenhum agendamento sincronizado neste dia.</${Empty}>`}
  </section>`;
}

function MonthGrid({ anchor, selectedDay, setSelectedDay, events }) {
  const first = monthFirst(anchor);
  const start = mondayOf(first);
  const last = monthLast(anchor);
  const days = [];
  for (let day = start; day <= last || days.length % 7 !== 0; day = addDays(day, 1)) {
    days.push(day);
    if (days.length >= 42) break;
  }
  const counts = new Map();
  events.forEach((event) => counts.set(eventDay(event), (counts.get(eventDay(event)) || 0) + 1));
  return html`<div class="pv-agenda-month-grid" role="grid" aria-label=${formatMonthLabel(anchor)}>
    ${WEEKDAYS.map((day) => html`<span class="pv-agenda-weekday" key=${day}>${day}</span>`)}
    ${days.map((day) => {
      const outside = !isSameMonth(day, anchor);
      const selected = day === selectedDay;
      const count = counts.get(day) || 0;
      return html`<button type="button" role="gridcell" key=${day} class=${`pv-agenda-month-day${outside ? ' outside' : ''}${selected ? ' selected' : ''}${day === todayInSaoPaulo() ? ' today' : ''}`}
        aria-pressed=${selected} aria-label=${`${day}${count ? `, ${count} agendamentos` : ''}`} disabled=${outside}
        onClick=${() => setSelectedDay(day)}>
        <span>${Number(day.slice(-2))}</span>${count ? html`<small>${count}</small>` : null}
      </button>`;
    })}
  </div>`;
}

function WeekStrip({ selectedDay, setSelectedDay, events }) {
  const start = mondayOf(selectedDay);
  return html`<div class="pv-agenda-week-strip" aria-label="Dias da semana">
    ${Array.from({ length: 7 }, (_, index) => {
      const day = addDays(start, index);
      const count = events.filter((event) => eventDay(event) === day).length;
      return html`<button type="button" key=${day} class=${day === selectedDay ? 'selected' : ''} aria-pressed=${day === selectedDay} onClick=${() => setSelectedDay(day)}>
        <small>${WEEKDAYS[index]}</small><b>${Number(day.slice(-2))}</b>${count ? html`<i>${count}</i>` : null}
      </button>`;
    })}
  </div>`;
}

function EventCollection({ events, selectedDay, mode }) {
  const visible = mode === 'day'
    ? events.filter((event) => eventDay(event) === selectedDay)
    : mode === 'week'
      ? events.filter((event) => {
        const start = mondayOf(selectedDay);
        return eventDay(event) >= start && eventDay(event) <= addDays(start, 6);
      })
      : events.filter((event) => isSameMonth(eventDay(event), selectedDay));
  if (mode === 'day') return html`<${AppointmentList} events=${visible} selectedDay=${selectedDay}/>`;
  const dayKeys = [...new Set(visible.map(eventDay))].sort();
  return html`<div class="pv-agenda-event-days">
    ${dayKeys.length ? dayKeys.map((day) => html`<${AppointmentList} key=${day} events=${visible} selectedDay=${day}/>`)
      : html`<${Empty}>Nenhum agendamento sincronizado neste período.</${Empty}>`}
  </div>`;
}

function formatCoverage(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeZone: TIME_ZONE }).format(new Date(value));
}

function formatUpdated(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: TIME_ZONE }).format(new Date(value));
}

export default function ProntuarioAgenda({ statusRes, setToast }) {
  const today = todayInSaoPaulo();
  const [selectedDay, setSelectedDay] = useState(today);
  const [mode, setMode] = useState(() => window.innerWidth <= 720 ? 'day' : 'week');
  const [professionalId, setProfessionalId] = useState('');
  const status = statusRes.data || {};
  const [rangeStart, rangeEnd] = mode === 'month'
    ? [mondayOf(monthFirst(selectedDay)), addDays(mondayOf(monthLast(selectedDay)), 7)]
    : mode === 'week'
      ? [mondayOf(selectedDay), addDays(mondayOf(selectedDay), 7)]
      : [selectedDay, addDays(selectedDay, 1)];
  const [from, to] = isoBounds(rangeStart, rangeEnd);
  const eventsPath = `/api/calendar/events?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}${professionalId ? `&professional_id=${encodeURIComponent(professionalId)}` : ''}`;
  const eventsRes = useApi(eventsPath, { every: 60000 });
  const data = eventsRes.data || {};
  const professionals = data.professionals || [];
  const events = [...(data.events || [])].filter((event) => !professionalId || String(event.professional_id) === professionalId)
    .sort((a, b) => String(a.start).localeCompare(String(b.start)));
  const busy = status.state === 'sync_unavailable';
  const statusTone = busy ? 'warn' : status.ready ? 'ok' : 'off';
  const statusText = busy ? 'Sincronização indisponível' : status.ready ? 'Agenda do Prontuário Verde' : 'Agenda ainda não disponível';
  const updatedAt = data.updated_at || status.updated_at;
  const coverageStart = data.coverage_start || status.coverage_start;
  const coverageEnd = data.coverage_end || status.coverage_end;

  const move = (direction) => {
    if (mode === 'month') {
      const date = fromKey(monthFirst(selectedDay));
      date.setUTCMonth(date.getUTCMonth() + direction);
      setSelectedDay(dateKey(date));
    } else {
      setSelectedDay(addDays(selectedDay, direction * (mode === 'week' ? 7 : 1)));
    }
  };
  const refresh = async () => {
    const [statusOk, eventsOk] = await Promise.all([statusRes.reload(), eventsRes.reload()]);
    setToast(statusOk && eventsOk ? 'Agenda recarregada' : 'Não consegui atualizar a agenda');
  };

  return html`<section class="pv-agenda" aria-label="Agenda do Prontuário Verde">
    <div class="card agenda-status-bar pv-agenda-status">
      <div class="agenda-status-info"><${Dot} tone=${statusTone}/><div>
        <span class="agenda-status-label">${statusText}</span>
        <span class="agenda-status-help">${updatedAt ? `Cache atualizado em ${formatUpdated(updatedAt)} · horário de São Paulo` : 'Agenda sincronizada pelo Prontuário Verde.'}</span>
      </div></div>
      <button type="button" class="btn sm agenda-refresh" disabled=${eventsRes.loading} onClick=${refresh}><${Icon.refresh}/>${eventsRes.loading ? 'Atualizando…' : 'Recarregar agenda'}</button>
    </div>
    ${(coverageStart || coverageEnd) ? html`<p class="pv-agenda-coverage">Consultas sincronizadas de ${formatCoverage(coverageStart) || '—'} até ${coverageEnd ? formatCoverage(new Date(new Date(coverageEnd).getTime() - 1).toISOString()) : '—'}. Horários vazios precisam de confirmação no Prontuário Verde.</p>` : null}
    <div class="card agenda-board pv-agenda-board">
      <div class="agenda-toolbar pv-agenda-toolbar">
        <div class="agenda-nav">
          <button class="btn sm" aria-label="Período anterior" onClick=${() => move(-1)}><${Icon.left}/></button>
          <button class="btn sm" onClick=${() => setSelectedDay(today)}>Hoje</button>
          <button class="btn sm" aria-label="Próximo período" onClick=${() => move(1)}><${Icon.right}/></button>
        </div>
        <span class="agenda-range-label">${rangeLabel(mode, selectedDay)}</span>
        <label class="pv-agenda-filter">Profissional
          <select class="select sm" value=${professionalId} onChange=${(event) => setProfessionalId(event.currentTarget.value)}>
            <option value="">Todas</option>
            ${professionals.map((professional) => html`<option key=${professional.id} value=${String(professional.id)}>${professional.name}</option>`)}
          </select>
        </label>
        <div class="agenda-mode-switch" role="group" aria-label="Visualização da agenda">
          ${[['day', 'Dia'], ['week', 'Semana'], ['month', 'Mês']].map(([id, label]) => html`<button type="button" class=${mode === id ? 'active' : ''} aria-pressed=${mode === id} onClick=${() => setMode(id)}>${label}</button>`)}
        </div>
      </div>
      ${mode === 'month'
        ? html`<${MonthGrid} anchor=${selectedDay} selectedDay=${selectedDay} setSelectedDay=${setSelectedDay} events=${events}/>`
        : mode === 'week' ? html`<${WeekStrip} selectedDay=${selectedDay} setSelectedDay=${setSelectedDay} events=${events}/>` : null}
      ${eventsRes.loading && !eventsRes.data ? html`<div class="empty">Carregando agenda…</div>`
        : eventsRes.error ? html`<${ErrorBox} error=${eventsRes.error}/>`
        : !status.ready && !events.length ? html`<${Empty}>Não há agenda em cache para exibir.</${Empty}>`
        : html`<${EventCollection} events=${events} selectedDay=${selectedDay} mode=${mode}/>`}
    </div>
  </section>`;
}
