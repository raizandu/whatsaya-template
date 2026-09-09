// Agenda (Google Calendar) do painel. Semana (segunda–domingo) por padrão;
// em telas estreitas mostra um dia por vez. Eventos vêm já classificados e
// sanitizados pela API (/api/calendar/events) — esta tela só posiciona e exibe.
import { useEffect, useRef, useState } from 'preact/hooks';
import { html, useApi, post, Card, ErrorBox, Empty, Dot, Icon } from '../lib.js';

const HOUR_HEIGHT = 52; // px por hora na grade
const PX_PER_MIN = HOUR_HEIGHT / 60;
const NARROW_BREAKPOINT = 720;
const DAY_LABELS = { 1: 'Seg', 2: 'Ter', 3: 'Qua', 4: 'Qui', 5: 'Sex', 6: 'Sáb', 7: 'Dom' };

const STATE_INFO = {
  connected: { tone: 'ok', label: 'Conectado' },
  not_configured: { tone: 'warn', label: 'Não conectado', help: 'Conecte sua conta do Google para ver a agenda aqui.' },
  insufficient_scope: { tone: 'warn', label: 'Permissão insuficiente', help: 'Reconecte e autorize o acesso à agenda ao entrar com o Google.' },
  token_expired: { tone: 'warn', label: 'Conexão expirada', help: 'A conexão com o Google expirou. Reconecte para continuar.' },
  permission: { tone: 'warn', label: 'Sem permissão', help: 'A conta conectada não tem acesso a este calendário.' },
  unavailable: { tone: 'bad', label: 'Google Agenda indisponível', help: 'Não consegui falar com o Google Agenda agora. Tento de novo em instantes.' },
  disabled: { tone: 'off', label: 'Agenda desativada', help: 'A integração está desligada nas configurações abaixo.' },
};

const OAUTH_ERROR_MESSAGES = {
  denied: 'Você cancelou a autorização no Google.',
  invalid_state: 'A conexão expirou antes de terminar. Tente conectar de novo.',
  exchange_failed: 'Não consegui concluir a conexão com o Google. Tente de novo.',
  no_refresh_token: 'O Google não devolveu acesso permanente. Reconecte e aceite o acesso offline.',
  save_failed: 'Não consegui salvar a conexão. Tente de novo.',
};

const KIND_META = {
  booking: 'AYA',
  slot: 'Livre',
  block: 'Bloqueado',
  busy: 'Ocupado',
};

const OUTCOME_META = {
  attended: { label: 'Comparecida', className: 'attended' },
  no_show: { label: 'No Show', className: 'no-show' },
  no_status: { label: 'Sem status', className: 'no-status' },
  rescheduled: { label: 'Remarcada', className: 'rescheduled' },
};

// ── datas (pt-BR, fuso do navegador — a mesma simplificação vale para toda a tela) ──
const monthShortFmt = new Intl.DateTimeFormat('pt-BR', { month: 'short' });
const weekdayShortFmt = new Intl.DateTimeFormat('pt-BR', { weekday: 'short' });
const weekdayLongFmt = new Intl.DateTimeFormat('pt-BR', { weekday: 'long' });
const dayMonthLongFmt = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long' });
const dayMonthWeekdayFmt = new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });

const pad2 = (n) => String(n).padStart(2, '0');
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const hm = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const isoWeekday = (d) => { const w = d.getDay(); return w === 0 ? 7 : w; };
const mondayOf = (d) => addDays(startOfDay(d), 1 - isoWeekday(d));
const firstOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const dateKey = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const sameDay = (a, b) => dateKey(a) === dateKey(b);

function monthRange(anchor) {
  const first = firstOfMonth(anchor);
  const start = mondayOf(first);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const end = addDays(mondayOf(addDays(last, 7)), 0);
  return [start, end];
}

function rangeLabel(rangeStart, rangeEnd, dayMode) {
  if (dayMode) return cap(`${weekdayLongFmt.format(rangeStart)}, ${dayMonthLongFmt.format(rangeStart)}`);
  const last = addDays(rangeEnd, -1);
  const sameMonth = rangeStart.getMonth() === last.getMonth();
  if (sameMonth) return `${rangeStart.getDate()} – ${last.getDate()} de ${monthShortFmt.format(last)}`;
  return `${rangeStart.getDate()} de ${monthShortFmt.format(rangeStart)} – ${last.getDate()} de ${monthShortFmt.format(last)}`;
}

function parseHM(value) {
  const [h, m] = String(value || '').split(':').map(Number);
  return { h: Number.isFinite(h) ? h : 0, m: Number.isFinite(m) ? m : 0 };
}

// Corta o evento em um pedaço por dia (o pedaço que atravessa meia-noite vira dois).
function splitTimedSegments(ev) {
  const start = new Date(ev.start);
  const end = new Date(ev.end);
  const segments = [];
  let curStart = start;
  for (let guard = 0; guard < 14; guard += 1) {
    const dayEnd = new Date(curStart.getFullYear(), curStart.getMonth(), curStart.getDate(), 23, 59, 59, 999);
    const segEnd = end < dayEnd ? end : dayEnd;
    segments.push({ ...ev, segStart: curStart, segEnd, key: dateKey(curStart) });
    if (segEnd.getTime() >= end.getTime()) break;
    curStart = new Date(curStart.getFullYear(), curStart.getMonth(), curStart.getDate() + 1, 0, 0, 0, 0);
  }
  return segments;
}

function allDayKeys(ev) {
  const start = startOfDay(new Date(ev.start));
  const end = startOfDay(new Date(ev.end));
  const last = end > start ? addDays(end, -1) : start;
  const keys = [];
  let cur = start;
  for (let guard = 0; guard < 60 && cur <= last; guard += 1) {
    keys.push(dateKey(cur));
    cur = addDays(cur, 1);
  }
  return keys;
}

// Distribui eventos sobrepostos em "raias" lado a lado dentro do mesmo dia.
function assignLanes(segments) {
  const sorted = [...segments].sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin);
  const laneEnds = [];
  sorted.forEach((seg) => {
    let lane = laneEnds.findIndex((end) => end <= seg.startMin);
    if (lane === -1) { lane = laneEnds.length; laneEnds.push(seg.endMin); }
    else laneEnds[lane] = seg.endMin;
    seg.lane = lane;
  });
  const lanes = laneEnds.length || 1;
  sorted.forEach((seg) => { seg.lanes = lanes; });
  return sorted;
}

function useIsNarrow(breakpoint) {
  const [narrow, setNarrow] = useState(() => window.innerWidth <= breakpoint);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth <= breakpoint);
    addEventListener('resize', onResize);
    return () => removeEventListener('resize', onResize);
  }, [breakpoint]);
  return narrow;
}

function EventDetail({ event, onClose, onUpdated, assistantName = 'AYA', setToast }) {
  if (!event) return null;
  const start = new Date(event.start);
  const end = new Date(event.end);
  const isBooking = event.kind === 'booking';
  const outcome = event.meeting_outcome || 'no_status';
  const outcomeMeta = OUTCOME_META[outcome] || OUTCOME_META.no_status;
  const saveOutcome = async (next) => {
    try {
      await post('/api/actions/meeting-outcome', {
        event_id: event.occurrence_event_id || event.id,
        start: event.start,
        outcome: next,
      });
      setToast(`Reunião marcada como ${OUTCOME_META[next].label}`);
      await onUpdated();
      onClose();
    } catch (err) {
      setToast(`Não alterei o status: ${err.message}`);
    }
  };
  return html`<div class="agenda-detail-overlay" onClick=${onClose}>
    <div class="agenda-detail" onClick=${(e) => e.stopPropagation()}>
      <div class="agenda-detail-head">
        <span class=${'tag' + (isBooking ? ' orange' : '')}>${KIND_META[event.kind] || event.kind}</span>
        <button type="button" class="agenda-detail-close" onClick=${onClose} aria-label="Fechar">×</button>
      </div>
      <h3>${event.title}</h3>
      <p class="agenda-detail-time">${event.all_day ? 'Dia inteiro' : `${cap(dayMonthWeekdayFmt.format(start))} · ${hm(start)}–${hm(end)}`}</p>
      ${isBooking ? html`<p class="agenda-detail-sub">Agendado por ${assistantName}${event.status && event.status !== 'confirmed' ? ` · ${event.status}` : ''}</p>` : null}
      ${isBooking && event.description ? html`<p class="agenda-detail-desc">${event.description}</p>` : null}
      ${isBooking ? html`<section class="agenda-outcome-panel">
        <div class="agenda-outcome-head"><span>Resultado da reunião</span><em class=${`meeting-status ${outcomeMeta.className}`}>${outcomeMeta.label}</em></div>
        <div class="agenda-outcome-actions">
          ${Object.entries(OUTCOME_META).filter(([id]) => id !== 'rescheduled' || outcome === id).map(([id, meta]) => html`<button type="button" class=${outcome === id ? 'active' : ''} onClick=${() => saveOutcome(id)}>${meta.label}</button>`)}
        </div>
        ${outcome === 'rescheduled' && event.rescheduled_to_start ? html`<div class="agenda-rescheduled-to"><span>Nova data</span><b>${dateTimeLabel(event.rescheduled_to_start)}</b></div>` : null}
        <div class="agenda-aya-state"><i></i><span><b>${assistantName} acompanha este status</b><small>${event.outcome_followup_sent ? 'Confirmação pós-reunião enviada ao contato.' : 'Após a reunião, a AYA pede a confirmação ao contato.'}</small></span></div>
      </section>` : null}
      ${isBooking ? html`<div class="agenda-detail-actions">
        ${event.meet_link ? html`<a class="btn primary" href=${event.meet_link} target="_blank" rel="noopener">Abrir no Meet</a>` : null}
        ${event.html_link ? html`<a class="btn" href=${event.html_link} target="_blank" rel="noopener">Abrir no Google Agenda</a>` : null}
      </div>` : null}
    </div>
  </div>`;
}

function dateTimeLabel(value) {
  return value ? new Date(value).toLocaleString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
}

function eventMinutes(event, day) {
  if (event.all_day || event.kind === 'slot' || event.meeting_outcome === 'rescheduled') return 0;
  const start = new Date(event.start);
  const end = new Date(event.end);
  const dayStart = startOfDay(day);
  const dayEnd = addDays(dayStart, 1);
  return Math.max(0, (Math.min(end, dayEnd) - Math.max(start, dayStart)) / 60000);
}

function meetingEvents(events) { return events.filter((event) => event.kind === 'booking'); }

function AgendaSettings({ settings, reloadSettings, reloadEvents, reloadStatus, setToast }) {
  const [form, setForm] = useState(settings || null);
  const [saving, setSaving] = useState(false);
  const touched = useRef(false);

  useEffect(() => {
    if (!touched.current && settings) setForm(settings);
  }, [settings]);

  if (!form) {
    return html`<${Card} title="Configurações da agenda"><p class="card-sub">Carregando configurações…</p></${Card}>`;
  }

  const set = (key, value) => { touched.current = true; setForm((f) => ({ ...f, [key]: value })); };
  const toggleDay = (day) => {
    touched.current = true;
    setForm((f) => {
      const has = f.business_days.includes(day);
      const next = has ? f.business_days.filter((d) => d !== day) : [...f.business_days, day];
      next.sort((a, b) => a - b);
      return { ...f, business_days: next };
    });
  };

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const result = await post('/api/actions/calendar-settings', form);
      touched.current = false;
      setForm(result.settings);
      setToast('Configurações da agenda salvas');
      reloadSettings();
      reloadEvents();
      reloadStatus();
    } catch (err) {
      setToast(`Não consegui salvar: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return html`<${Card} title="Configurações da agenda" sub="Como a AYA enxerga sua disponibilidade no Google Agenda.">
    <form class="agenda-settings-form" onSubmit=${submit}>
      <div class="agenda-form-grid">
        <label class="field-label">Agenda ativa
          <div class="form-row"><button type="button" class=${'toggle-btn' + (form.enabled ? ' active' : '')} aria-pressed=${Boolean(form.enabled)} onClick=${() => set('enabled', !form.enabled)}>${form.enabled ? 'Ligada' : 'Desligada'}</button></div>
        </label>
        <div class="field-label agenda-span-full">Modo de vagas
          <div class="agenda-radio-group">
            <label class="agenda-radio"><input type="radio" name="availability_mode" checked=${form.availability_mode === 'explicit_slots'} onChange=${() => set('availability_mode', 'explicit_slots')}/> Somente horários marcados como Livre</label>
            <label class="agenda-radio"><input type="radio" name="availability_mode" checked=${form.availability_mode === 'freebusy_gaps'} onChange=${() => set('availability_mode', 'freebusy_gaps')}/> Intervalos livres do expediente</label>
          </div>
        </div>
        <label class="field-label">Palavra para horário livre<input class="input" value=${form.slot_keyword} onInput=${(e) => set('slot_keyword', e.target.value)}/></label>
        <label class="field-label">Palavra para bloqueio<input class="input" value=${form.block_keyword} onInput=${(e) => set('block_keyword', e.target.value)}/></label>
        <div class="field-label agenda-span-full">Dias de atendimento
          <div class="agenda-day-chips">
            ${[1, 2, 3, 4, 5, 6, 7].map((d) => html`<button type="button" key=${d} class=${'chip' + (form.business_days.includes(d) ? ' mint' : '')} onClick=${() => toggleDay(d)}>${DAY_LABELS[d]}</button>`)}
          </div>
        </div>
        <label class="field-label">Início do expediente<input class="input" type="time" value=${form.business_start} onInput=${(e) => set('business_start', e.target.value)}/></label>
        <label class="field-label">Fim do expediente<input class="input" type="time" value=${form.business_end} onInput=${(e) => set('business_end', e.target.value)}/></label>
        <label class="field-label">Duração da sessão (min)<input class="input" type="number" min="15" max="240" step="5" value=${form.duration_minutes} onInput=${(e) => set('duration_minutes', Number(e.target.value))}/></label>
        <label class="field-label">Antecedência mínima (min)<input class="input" type="number" min="0" max="10080" value=${form.min_lead_minutes} onInput=${(e) => set('min_lead_minutes', Number(e.target.value))}/></label>
        <label class="field-label">Dias de busca<input class="input" type="number" min="1" max="42" value=${form.search_days} onInput=${(e) => set('search_days', Number(e.target.value))}/></label>
        <label class="field-label">ID do calendário<input class="input" value=${form.calendar_id} onInput=${(e) => set('calendar_id', e.target.value)}/></label>
        <label class="field-label">Fuso horário<input class="input" value=${form.timezone} onInput=${(e) => set('timezone', e.target.value)}/></label>
        <label class="field-label">Título do evento<input class="input" value=${form.event_title} onInput=${(e) => set('event_title', e.target.value)}/></label>
        <div class="agenda-settings-actions agenda-span-full"><button class="btn primary" type="submit" disabled=${saving}>${saving ? 'Salvando…' : 'Salvar'}</button></div>
      </div>
    </form>
  </${Card}>`;
}

function AttendanceValue({ summary }) {
  return html`<b>${summary && summary.attendance_rate != null ? `${summary.attendance_rate}%` : '—'}</b>`;
}

function TodayMetrics({ events, summary, settings, day }) {
  const bookings = meetingEvents(events).filter((event) => sameDay(new Date(event.start), day));
  const occupied = events.reduce((total, event) => total + eventMinutes(event, day), 0);
  const { h: startH, m: startM } = parseHM(settings ? settings.business_start : '08:00');
  const { h: endH, m: endM } = parseHM(settings ? settings.business_end : '18:00');
  const capacity = Math.max(1, (endH * 60 + endM) - (startH * 60 + startM));
  const next = bookings
    .filter((event) => new Date(event.start) > new Date())
    .sort((a, b) => new Date(a.start) - new Date(b.start))[0];
  return html`<section class="agenda-ops-metrics" aria-label="Resumo de hoje">
    <div><span>HOJE</span><b>${bookings.length}</b><small>compromissos</small></div>
    <div><span>OCUPAÇÃO</span><b>${Math.round((occupied / capacity) * 100)}%</b><small>${Math.round(occupied / 60 * 10) / 10}h de ${Math.round(capacity / 60 * 10) / 10}h</small></div>
    <div><span>COMPARECIMENTO</span><${AttendanceValue} summary=${summary}/><small>${summary ? `${summary.attended} comparecidas · ${summary.no_show} no show` : 'sem resultados'}</small></div>
    <div><span>PRÓXIMO</span><b>${next ? hm(new Date(next.start)) : '—'}</b><small>${next ? next.title : 'agenda livre'}</small></div>
  </section>`;
}

function MonthCapacity({ anchor, days, events, summary, settings, selectedDay, setSelectedDay, setSelected, setMode }) {
  const monthEvents = meetingEvents(events).filter((event) => new Date(event.start).getMonth() === anchor.getMonth());
  const businessDays = settings ? settings.business_days : [1, 2, 3, 4, 5];
  const { h: startH, m: startM } = parseHM(settings ? settings.business_start : '08:00');
  const { h: endH, m: endM } = parseHM(settings ? settings.business_end : '18:00');
  const dailyCapacity = Math.max(1, (endH * 60 + endM) - (startH * 60 + startM));
  const chosen = selectedDay && days.some((day) => sameDay(day, selectedDay)) ? selectedDay : days.find((day) => sameDay(day, new Date())) || firstOfMonth(anchor);
  const chosenEvents = events.filter((event) => sameDay(new Date(event.start), chosen));
  const chosenBusy = chosenEvents.reduce((total, event) => total + eventMinutes(event, chosen), 0);
  const businessDayCount = days.filter((day) => day.getMonth() === anchor.getMonth() && businessDays.includes(isoWeekday(day))).length;
  const monthBusy = events.reduce((total, event) => total + (new Date(event.start).getMonth() === anchor.getMonth() ? eventMinutes(event, new Date(event.start)) : 0), 0);
  return html`<div class="agenda-month-capacity">
    <div class="agenda-month-summary">
      <p><b>${monthEvents.length} compromissos</b><span>em ${monthShortFmt.format(anchor)}</span></p>
      <p><b>${new Set(monthEvents.map((event) => dateKey(new Date(event.start)))).size} dias</b><span>com agendamentos</span></p>
      <p><b>${Math.max(0, Math.round((businessDayCount * dailyCapacity - monthBusy) / 60))}h</b><span>disponíveis no mês</span></p>
      <p class="attendance"><${AttendanceValue} summary=${summary}/><span>de comparecimento</span></p>
    </div>
    <div class="agenda-capacity-layout">
      <section class="agenda-month-calendar">
        <div class="agenda-capacity-legend"><b>Capacidade do mês</b><span><i class="free"></i>Livre <i class="light"></i>Leve <i class="medium"></i>Moderado <i class="full"></i>Ocupado</span></div>
        <div class="agenda-month-weekdays">${['SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB', 'DOM'].map((label) => html`<span>${label}</span>`)}</div>
        <div class="agenda-capacity-grid">${days.map((day) => {
          const dayEvents = events.filter((event) => sameDay(new Date(event.start), day));
          const busy = dayEvents.reduce((total, event) => total + eventMinutes(event, day), 0);
          const pct = businessDays.includes(isoWeekday(day)) ? Math.min(100, Math.round((busy / dailyCapacity) * 100)) : 0;
          const level = pct >= 75 ? 3 : pct >= 40 ? 2 : pct > 0 ? 1 : 0;
          const outside = day.getMonth() !== anchor.getMonth();
          const selected = sameDay(day, chosen);
          const label = level === 3 ? 'Ocupado' : level === 2 ? 'Moderado' : level === 1 ? 'Leve' : 'Livre';
          return html`<button type="button" class=${`agenda-capacity-day level-${level}${outside ? ' outside' : ''}${sameDay(day, new Date()) ? ' today' : ''}${selected ? ' selected' : ''}`} style=${`--fill:${Math.max(8, pct)}%`} onClick=${() => !outside && setSelectedDay(day)} disabled=${outside} aria-pressed=${selected}>
            <span class="agenda-capacity-date">${day.getDate()}</span>
            ${outside ? null : html`<div class="agenda-thermometer" aria-label=${`${pct}% ocupado`}><span></span><i></i></div><small>${label}</small><b>${dayEvents.length ? `${dayEvents.length} agend.` : `${Math.round(dailyCapacity / 60)}h livres`}</b>`}
          </button>`;
        })}</div>
      </section>
      <aside class="agenda-capacity-detail">
        <span>${cap(dayMonthWeekdayFmt.format(chosen)).toUpperCase()}</span>
        <b>${chosenEvents.length ? `${chosenEvents.length} compromisso${chosenEvents.length > 1 ? 's' : ''}` : 'Dia totalmente livre'}</b>
        <p>${chosenEvents.length ? `${Math.round(chosenBusy)} min ocupados · ${Math.max(0, Math.round((dailyCapacity - chosenBusy) / 60 * 10) / 10)}h disponíveis` : `${Math.round(dailyCapacity / 60)}h disponíveis para novos agendamentos`}</p>
        <div class="agenda-status-key"><span><i class="attended"></i>Comparecida</span><span><i class="no-show"></i>No Show</span><span><i class="no-status"></i>Sem status</span></div>
        <div class="agenda-capacity-events">${chosenEvents.length ? chosenEvents.map((event) => {
          const meta = OUTCOME_META[event.meeting_outcome || 'no_status'] || OUTCOME_META.no_status;
          return html`<button type="button" onClick=${() => setSelected(event)}><i></i><span><b>${event.all_day ? 'Dia' : hm(new Date(event.start))}</b>${event.title}</span>${event.kind === 'booking' ? html`<em class=${`meeting-status ${meta.className}`}>${meta.label}</em>` : html`<em>${KIND_META[event.kind]}</em>`}</button>`;
        }) : html`<div class="agenda-capacity-empty">Nenhum compromisso neste dia.</div>`}</div>
        <button type="button" class="btn primary" onClick=${() => { setSelectedDay(chosen); setMode('day'); }}>Ver agenda do dia</button>
      </aside>
    </div>
  </div>`;
}

export default function Agenda({ assistantName = 'AYA', setToast }) {
  const narrow = useIsNarrow(NARROW_BREAKPOINT);
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [selected, setSelected] = useState(null);
  const [selectedDay, setSelectedDay] = useState(() => startOfDay(new Date()));
  const [mode, setMode] = useState(() => window.innerWidth <= NARROW_BREAKPOINT ? 'day' : 'month');
  const [refreshing, setRefreshing] = useState(false);
  const lastAutoRefreshAt = useRef(0);
  const activeMode = narrow ? 'day' : mode;
  const dayMode = activeMode === 'day';

  const [monthStart, monthEnd] = monthRange(anchor);
  const rangeStart = activeMode === 'month' ? monthStart : dayMode ? startOfDay(anchor) : mondayOf(anchor);
  const rangeEnd = activeMode === 'month' ? monthEnd : dayMode ? addDays(rangeStart, 1) : addDays(rangeStart, 7);

  const statusRes = useApi('/api/calendar/status', { every: 60000 });
  const status = statusRes.data;
  const eventsPath = `/api/calendar/events?from=${encodeURIComponent(rangeStart.toISOString())}&to=${encodeURIComponent(rangeEnd.toISOString())}`;
  const eventsRes = useApi(eventsPath, { every: 60000 });
  const settingsRes = useApi('/api/calendar/settings');

  useEffect(() => {
    const refreshWhenVisible = () => {
      const now = Date.now();
      if (document.visibilityState !== 'visible' || now - lastAutoRefreshAt.current < 1000) return;
      lastAutoRefreshAt.current = now;
      eventsRes.reload();
      statusRes.reload();
    };
    addEventListener('focus', refreshWhenVisible);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      removeEventListener('focus', refreshWhenVisible);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, [eventsPath]);

  // Lê #agenda?connected=1 / #agenda?oauth_error=… uma vez, mostra o toast e limpa o hash.
  useEffect(() => {
    const raw = location.hash.replace('#', '');
    const [base, query] = raw.split('?');
    if (base !== 'agenda' || !query) return;
    const params = new URLSearchParams(query);
    if (params.get('connected') === '1') {
      setToast('Google Agenda conectada');
    } else if (params.has('oauth_error')) {
      setToast(OAUTH_ERROR_MESSAGES[params.get('oauth_error')] || 'Não consegui conectar ao Google Agenda.');
    }
    location.hash = 'agenda';
  }, []);

  if (!status && statusRes.loading) {
    return html`<div class="empty">Carregando agenda…</div>`;
  }

  const info = STATE_INFO[status && status.state] || STATE_INFO.unavailable;
  const connected = status && status.state === 'connected';
  const oauthAvailable = !status || status.oauth_available !== false;
  const connectLabel = !oauthAvailable ? 'Configure as credenciais no servidor' : connected ? 'Reconectar' : 'Conectar Google Agenda';
  const ready = Boolean(status && status.ready);

  const settings = settingsRes.data && settingsRes.data.settings;
  const businessDays = settings ? settings.business_days : [1, 2, 3, 4, 5];
  const bStart = parseHM(settings ? settings.business_start : '08:00');
  const bEnd = parseHM(settings ? settings.business_end : '18:00');
  const startHour = Math.min(7, Math.max(0, bStart.h - 1));
  const endHour = Math.max(19, Math.min(24, (bEnd.m > 0 ? bEnd.h + 2 : bEnd.h + 1)));
  const hours = Array.from({ length: endHour - startHour }, (_, i) => startHour + i);
  const totalHeight = (endHour - startHour) * HOUR_HEIGHT;

  const dayCount = activeMode === 'month' ? Math.round((rangeEnd - rangeStart) / 86400000) : dayMode ? 1 : 7;
  const days = Array.from({ length: dayCount }, (_, i) => addDays(rangeStart, i));
  const events = (eventsRes.data && eventsRes.data.events) || [];

  const timedByDay = {};
  const allDayByDay = {};
  days.forEach((d) => { timedByDay[dateKey(d)] = []; allDayByDay[dateKey(d)] = []; });
  events.forEach((ev) => {
    if (ev.all_day) {
      allDayKeys(ev).forEach((k) => { if (allDayByDay[k]) allDayByDay[k].push(ev); });
    } else {
      splitTimedSegments(ev).forEach((seg) => { if (timedByDay[seg.key]) timedByDay[seg.key].push(seg); });
    }
  });

  // Recorta cada segmento à faixa visível (startHour..endHour); o que ficar
  // totalmente fora (ex.: 23h com grade até 19h) some da grade e vira chip
  // na faixa "Dia inteiro", nunca sobrepondo as linhas de hora.
  const gridStartMin = startHour * 60;
  const gridEndMin = endHour * 60;
  const gridDays = activeMode === 'month' ? [] : days;
  const dayColumns = gridDays.map((d) => {
    const key = dateKey(d);
    const inGrid = [];
    const offGrid = [];
    timedByDay[key].forEach((s) => {
      const rawStart = s.segStart.getHours() * 60 + s.segStart.getMinutes();
      const rawEnd = Math.min(24 * 60, s.segEnd.getHours() * 60 + s.segEnd.getMinutes() + (s.segEnd.getSeconds() || s.segEnd.getMilliseconds() ? 1 : 0));
      if (rawEnd <= gridStartMin || rawStart >= gridEndMin) {
        offGrid.push(s);
      } else {
        inGrid.push({ ...s, startMin: Math.max(rawStart, gridStartMin), endMin: Math.min(rawEnd, gridEndMin) });
      }
    });
    return { date: d, key, segments: assignLanes(inGrid), allDay: allDayByDay[key], offGrid };
  });

  const showSkeleton = eventsRes.loading && !eventsRes.data;
  const showEmpty = !showSkeleton && !eventsRes.error && events.length === 0;
  const meetingSummary = eventsRes.data && eventsRes.data.meetings;
  const step = activeMode === 'month' ? 0 : dayMode ? 1 : 7;
  const move = (direction) => setAnchor((current) => activeMode === 'month'
    ? new Date(current.getFullYear(), current.getMonth() + direction, 1)
    : addDays(current, step * direction));
  const changeMode = (next) => {
    setMode(next);
    if (next === 'day') setAnchor(startOfDay(selectedDay || new Date()));
  };
  const refreshAgenda = async () => {
    setRefreshing(true);
    const [eventsOk] = await Promise.all([eventsRes.reload(), statusRes.reload()]);
    setRefreshing(false);
    setToast(eventsOk ? 'Agenda atualizada' : 'Não consegui atualizar a agenda');
  };

  return html`
    <div class="card agenda-status-bar">
      <div class="agenda-status-info">
        <${Dot} tone=${info.tone}/>
        <div>
          <span class="agenda-status-label">${info.label}</span>
          <span class="agenda-status-help">${connected
            ? `${(status && (status.calendar_label || status.calendar_id)) || ''} · ${status && status.timezone || ''}`
            : (status && status.error) || info.help}</span>
        </div>
      </div>
      <button class="btn" disabled=${!oauthAvailable} onClick=${() => { location.href = '/api/calendar/oauth/start'; }}>${connectLabel}</button>
    </div>
    ${!ready ? html`
      <${Card} title="Conecte o Google Agenda">
        <p class="card-sub">${(status && status.error) || info.help || 'Conecte sua conta do Google para ver a agenda aqui.'}</p>
      </${Card}>
    ` : html`
      <div class="card agenda-board">
        <div class="agenda-toolbar">
          <div class="agenda-nav">
            <button class="btn sm" aria-label="Período anterior" onClick=${() => move(-1)}><${Icon.left}/></button>
            <button class="btn sm" onClick=${() => { setAnchor(startOfDay(new Date())); setSelectedDay(startOfDay(new Date())); }}>Hoje</button>
            <button class="btn sm" aria-label="Próximo período" onClick=${() => move(1)}><${Icon.right}/></button>
          </div>
          <span class="agenda-range-label">${activeMode === 'month' ? cap(`${monthShortFmt.format(anchor)} de ${anchor.getFullYear()}`) : rangeLabel(rangeStart, rangeEnd, dayMode)}</span>
          <button type="button" class="btn sm agenda-refresh" disabled=${refreshing} aria-busy=${refreshing} onClick=${refreshAgenda}><${Icon.refresh}/>${refreshing ? 'Atualizando…' : 'Atualizar'}</button>
          <div class="agenda-mode-switch" role="group" aria-label="Visualização da agenda">
            <button type="button" class=${activeMode === 'day' ? 'active' : ''} onClick=${() => changeMode('day')}>Hoje</button>
            <button type="button" class=${activeMode === 'week' ? 'active' : ''} onClick=${() => changeMode('week')}>Semana</button>
            <button type="button" class=${activeMode === 'month' ? 'active' : ''} onClick=${() => changeMode('month')}>Mês</button>
          </div>
        </div>
        ${showSkeleton ? html`<div class="empty">Carregando agenda…</div>`
          : eventsRes.error ? html`<${ErrorBox} error=${eventsRes.error}/>`
          : activeMode === 'month' ? html`<${MonthCapacity} anchor=${anchor} days=${days} events=${events} summary=${meetingSummary} settings=${settings} selectedDay=${selectedDay} setSelectedDay=${setSelectedDay} setSelected=${setSelected} setMode=${changeMode}/>`
          : html`<div class=${dayMode ? 'agenda-today-view' : 'agenda-week-view'}>
            ${dayMode ? html`<${TodayMetrics} events=${events} summary=${meetingSummary} settings=${settings} day=${rangeStart}/>` : html`<div class="agenda-week-legend"><span><i class="kind-booking"></i>AYA</span><span><i class="kind-slot"></i>Livre</span><small>Horário de Brasília</small></div>`}
            ${showEmpty ? html`<${Empty}>Nenhum compromisso neste período.</${Empty}>` : html`<div class="agenda-grid-wrap">
            <div class="agenda-grid" style=${`--agenda-cols:${days.length}`}>
              <div class="agenda-corner"></div>
              ${days.map((d) => html`<div key=${dateKey(d)} class=${'agenda-day-head' + (businessDays.includes(isoWeekday(d)) ? '' : ' dim') + (sameDay(d, new Date()) ? ' today' : '')}>
                <span class="agenda-day-name">${cap(weekdayShortFmt.format(d))}</span>
                <span class="agenda-day-num">${d.getDate()}</span>
              </div>`)}
              <div class="agenda-corner agenda-allday-label">Dia inteiro</div>
              ${dayColumns.map((col) => html`<div key=${col.key} class="agenda-allday-cell">
                ${col.allDay.map((ev) => html`<button type="button" key=${ev.id} class=${'tag agenda-allday-chip kind-' + ev.kind} onClick=${() => setSelected(ev)}>${ev.title}</button>`)}
                ${col.offGrid.map((seg) => html`<button type="button" key=${seg.id + seg.key} class=${'tag agenda-allday-chip kind-' + seg.kind} onClick=${() => setSelected(seg)}>${hm(seg.segStart)} ${seg.title}</button>`)}
              </div>`)}
              <div class="agenda-gutter" style=${`height:${totalHeight}px`}>
                ${hours.map((h) => html`<div key=${h} class="agenda-hour-label" style=${`height:${HOUR_HEIGHT}px`}>${pad2(h)}:00</div>`)}
              </div>
              ${dayColumns.map((col) => html`<div key=${col.key} class=${'agenda-day-col' + (businessDays.includes(isoWeekday(col.date)) ? '' : ' dim') + (sameDay(col.date, new Date()) ? ' today' : '')} style=${`height:${totalHeight}px`}>
                ${hours.map((h) => html`<div key=${h} class="agenda-hour-row" style=${`height:${HOUR_HEIGHT}px`}></div>`)}
                <div class="agenda-events-layer">
                  ${col.segments.map((seg) => {
                    const top = Math.max(0, (seg.startMin - startHour * 60)) * PX_PER_MIN;
                    const height = Math.max((seg.endMin - seg.startMin) * PX_PER_MIN, 20);
                    const width = 100 / seg.lanes;
                    const left = seg.lane * width;
                    return html`<button type="button" key=${seg.id + seg.key} class=${'agenda-event kind-' + seg.kind}
                      style=${`top:${top}px;height:${height}px;left:${left}%;width:calc(${width}% - 3px)`}
                      title=${`${hm(seg.segStart)} · ${seg.title}`}
                      onClick=${() => setSelected(seg)}>
                      <span class="agenda-event-time">${hm(seg.segStart)}</span>
                      <span class="agenda-event-title">${seg.title}</span>
                      ${seg.kind === 'booking' ? html`<span class="agenda-badge">AYA</span>` : null}
                    </button>`;
                  })}
                  ${sameDay(col.date, new Date()) && new Date().getHours() >= startHour && new Date().getHours() < endHour ? html`<div class="agenda-now-line" style=${`top:${((new Date().getHours() * 60 + new Date().getMinutes()) - startHour * 60) * PX_PER_MIN}px`}><span>Agora</span></div>` : null}
                </div>
              </div>`)}
            </div>
          </div>`}
          </div>`}
      </div>
    `}
    <${AgendaSettings} settings=${settings} reloadSettings=${settingsRes.reload} reloadEvents=${eventsRes.reload} reloadStatus=${statusRes.reload} setToast=${setToast}/>
    <${EventDetail} event=${selected} onClose=${() => setSelected(null)} onUpdated=${eventsRes.reload} assistantName=${assistantName} setToast=${setToast}/>
  `;
}
