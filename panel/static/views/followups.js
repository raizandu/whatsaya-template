import { html, useApi, post, fmt, useNow, countdown, progressPct, Tile, Card, ErrorBox, Empty } from '../lib.js';

function fmtHour(hhmm) {
  const [h, m] = String(hhmm).split(':');
  return m && m !== '00' ? `${Number(h)}h${m}` : `${Number(h)}h`;
}

// Segundos legíveis: só passa pra "min"/"h" quando fecha redondo, senão mistura
// (ex.: "1 min 15 s") — é como as faixas do profile da Therapify caem.
function fmtSecs(s) {
  s = Math.round(Number(s) || 0);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r ? `${m} min ${r} s` : `${m} min`;
}
function fmtRangeSecs(minS, maxS) {
  minS = Number(minS) || 0; maxS = Number(maxS) || 0;
  if (minS >= 60 && maxS >= 60 && minS % 60 === 0 && maxS % 60 === 0) return `${minS / 60} a ${maxS / 60} min`;
  return `${fmtSecs(minS)} a ${fmtSecs(maxS)}`;
}
function fmtHoliday(v) {
  const p = String(v).split('-');
  return p.length === 2 ? `${p[1]}/${p[0]}` : `${p[2]}/${p[1]}/${p[0]}`;
}
const REPLY_DELAY_LABEL = { intencao: 'Intenção', comum: 'Comum', objecao: 'Objeção' };

export default function Followups({ period, setToast }) {
  const fu = useApi(`/api/followups?period=${period}`, { every: 30000 });
  const f = fu.data;
  const now = useNow();
  const ritmo = f && f.ritmo;

  const act = async (job, action) => {
    try {
      await post('/api/actions/followup', { chat_id: job.chat_id, action });
      setToast(action === 'cancel' ? `Follow-up de ${job.name} cancelado` : action === 'pause' ? `Follow-up de ${job.name} pausado` : `Follow-up de ${job.name} retomado`);
      fu.reload();
    } catch (err) {
      setToast(`Não consegui: ${err.message}`);
    }
  };
  const first = f ? f.queue.find((j) => !j.paused) : null;
  const schedule = f && f.schedule;
  const scheduleCopy = schedule
    ? `Só sai das ${fmtHour(schedule.open)} às ${fmtHour(schedule.close)}, horário de São Paulo. Resposta do lead ou você assumir cancela o que falta.`
    : 'Só sai em horário comercial, horário de São Paulo. Resposta do lead ou você assumir cancela o que falta.';

  return html`
    <${ErrorBox} error=${fu.error}/>
    <div class="grid c4">
      <${Tile} dark label="Na fila" value=${f ? fmt.int(f.queue.length) : '…'} sub=${first ? `próximo ${first.due_rel}` : 'nada agendado'}/>
      <${Tile} label="Enviados" value=${f ? fmt.int(f.stats.sent) : '…'} sub="sempre citando um fato da conversa"/>
      <${Tile} label="Trouxeram resposta" green value=${f ? fmt.int(f.stats.replied) : '…'} pct=${f ? fmt.pct(f.stats.replied, f.stats.sent) : ''} sub="lead voltou a falar depois do toque"/>
      <${Tile} label="Cancelados antes de sair" value=${f ? fmt.int(f.stats.cancelled) : '…'} sub=${f ? `${f.stats.cancelled_replied} porque o lead respondeu antes` : ''}/>
    </div>

    <div class="grid wide-15 start">
      <${Card} title="Fila de envio" sub=${scheduleCopy}>
        ${f && f.queue.length === 0 ? html`<${Empty}>Nada na fila. A AYA agenda o próximo toque quando um lead para de responder.</${Empty}>` : null}
        <div class="row-list">${f ? f.queue.map((j) => html`<div class="item" key=${j.id} style=${`align-items:flex-start;padding:14px 0;opacity:${j.paused ? 0.6 : 1}`}>
          <div style="width:86px;flex-shrink:0;display:flex;flex-direction:column;gap:3px" title=${j.due_local}>
            <span style=${`font-size:13px;font-weight:700;color:${j.paused ? 'var(--muted-2)' : j.soon ? 'var(--orange)' : 'var(--ink)'}`}>${j.due}</span>
            <span style=${`font-size:11px;color:${!j.waiting_window && j.soon ? 'var(--orange)' : 'var(--muted-2)'}`}>${j.waiting_window ? 'aguardando horário comercial' : `sai em ${countdown(j.due_utc, now)}`}</span>
          </div>
          <div class="grow" style="gap:6px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span class="name">${j.name}</span><span class="tag">${j.stage}</span>
              <span style="font-size:12px;color:var(--muted)">${j.kind === 'resume' ? `${j.cadence} · ${j.reason_label}` : j.kind === 'reactivation' ? `${j.cadence} · ${j.step_label}` : `${j.cadence} · toque ${j.step} de 3`}</span>
              ${j.paused ? html`<span class="tag amber">Pausado</span>` : null}
            </div>
            <div class="job-progress"><div class=${`job-progress-fill kind-${j.kind}`} style=${`width:${progressPct(j.created_utc, j.due_utc, now)}%`}></div></div>
            <span style="font-size:13px;color:var(--muted);line-height:1.45;font-style:italic;white-space:normal">"${j.text}"</span>
          </div>
          <div style="display:flex;gap:6px;align-self:center">
            <button class="btn" onClick=${() => act(j, j.paused ? 'resume' : 'pause')}>${j.paused ? 'Retomar' : 'Pausar'}</button>
            <button class="btn sm danger" style="height:36px" onClick=${() => act(j, 'cancel')}>Cancelar</button>
          </div>
        </div>`) : null}</div>
      </${Card}>

      <div style="display:flex;flex-direction:column;gap:16px">
        <${Card} title="Já saíram">
          ${f && f.history.length === 0 ? html`<${Empty}>Nenhum toque no período.</${Empty}>` : null}
          <div class="row-list">${f ? f.history.map((h) => html`<div class="item" key=${h.id} style="padding:10px 0">
            <span class=${'dot ' + (h.kind === 'replied' ? 'ok' : h.kind === 'cancelled' ? 'bad' : 'off')}></span>
            <div class="grow"><span class="name" style="font-size:13px">${h.name} <span style="font-weight:400;color:var(--muted-2)">· toque ${h.step}</span></span>
              <span class="meta" style=${`color:${h.kind === 'replied' ? 'var(--green-dark)' : h.kind === 'cancelled' ? 'var(--orange-ink)' : 'var(--muted)'}`}>${h.result}</span></div>
            <span class="when">${h.when}</span>
          </div>`) : null}</div>
        </${Card}>
        <${Card} title="Por cadência">
          <div class="row-list">${f ? f.cadences.map((c) => html`<div class="item" key=${c.id} style="padding:10px 0">
            <div style="display:flex;flex-direction:column;gap:1px;width:110px;flex-shrink:0"><span style="font-size:13px;font-weight:600">${c.label}</span><span style="font-size:11px;color:var(--muted-2)">${c.steps}</span></div>
            <div class="track" style="flex:1;height:8px;border-radius:4px;background:var(--soft-2);overflow:hidden"><div style=${`height:100%;border-radius:4px;background:var(--green);width:${c.rate}%`}></div></div>
            <span style="width:36px;text-align:right;font-size:13px;font-weight:700;color:var(--green-dark)">${c.rate}%</span>
            <span style="width:54px;text-align:right;font-size:12px;color:var(--muted)">${c.sent} env.</span>
          </div>`) : null}</div>
        </${Card}>
      </div>
    </div>

    <${Card} title="Ritmo" sub="Faixas de humanização e reativação do profile — só leitura.">
      ${!ritmo ? html`<${Empty}>Perfil de negócio sem os blocos de horário/humanização.</${Empty}>` : html`
      <div class="grid c4 start">
        <div>
          <span class="card-sub" style="text-transform:uppercase;font-weight:700;font-size:11px;letter-spacing:0.4px">Horário</span>
          <p style="margin:6px 0 4px">Seg a sex, ${fmtHour(ritmo.schedule.open)} às ${fmtHour(ritmo.schedule.close)} (São Paulo)
            ${(ritmo.schedule.holidays_fixed.length + ritmo.schedule.holidays_extra.length) > 0 ? html`
              <details style="display:inline-block;margin-left:4px"><summary style="cursor:pointer;display:inline;color:var(--muted)">${ritmo.schedule.holidays_fixed.length + ritmo.schedule.holidays_extra.length} feriados</summary>
                <div style="margin-top:4px;font-size:12px;color:var(--muted)">${[...ritmo.schedule.holidays_fixed, ...ritmo.schedule.holidays_extra].map(fmtHoliday).join(' · ')}</div>
              </details>` : null}
          </p>
          <p style="margin:0 0 4px;font-size:12px;color:var(--muted)">Noite útil: silêncio, fila da manhã às 9h.</p>
          <p style="margin:0;font-size:12px;color:var(--muted)">Sábado, domingo e feriado: só a Fase 1, das ${fmtHour(ritmo.schedule.open)} às ${fmtHour(ritmo.schedule.close)}.</p>
        </div>
        <div>
          <span class="card-sub" style="text-transform:uppercase;font-weight:700;font-size:11px;letter-spacing:0.4px">Esperas</span>
          <div style="margin-top:6px;display:flex;flex-direction:column;gap:6px">
            <span class="chip">Lead Novo: ${fmtRangeSecs(ritmo.humanization.first_reply.min_s, ritmo.humanization.first_reply.max_s)}</span>
            <span class="chip">Debounce sintomas: ${fmtRangeSecs(ritmo.humanization.diagnostic_debounce.min_s, ritmo.humanization.diagnostic_debounce.max_s)} (teto ${Math.round((ritmo.humanization.diagnostic_debounce.cap_s || 0) / 60)})</span>
            ${Object.entries(ritmo.humanization.reply_delay_s).map(([cat, range]) => html`<span class="chip" key=${cat}>${REPLY_DELAY_LABEL[cat] || cat}: ${fmtRangeSecs(range[0], range[1])}</span>`)}
          </div>
        </div>
        <div>
          <span class="card-sub" style="text-transform:uppercase;font-weight:700;font-size:11px;letter-spacing:0.4px">Fase 7</span>
          <div class="row-list" style="margin-top:6px">${ritmo.reactivation.steps.map((step, i) => html`<div class="item" key=${step.name} style="padding:8px 0;align-items:flex-start">
            <div class="grow">
              <div style="display:flex;align-items:center;gap:8px"><span class="name">${step.label}</span><span style="font-size:12px;color:var(--muted)">${i === 0 ? `+${step.offset} dia útil` : `+${step.offset}`}</span></div>
              <details><summary style="cursor:pointer;font-size:12px;color:var(--muted)">ver mensagens</summary>
                <div style="display:flex;flex-direction:column;gap:3px;margin-top:6px">
                  ${step.bubbles.map((b, bi) => html`<p key=${bi} style="margin:0;font-size:12px;color:var(--muted)">${b}</p>`)}
                  ${step.media_key ? html`<p class="mono" style="margin:0;font-size:12px;color:var(--muted)">[print]</p>` : null}
                  ${step.bubbles_after_media.map((b, bi) => html`<p key=${bi} style="margin:0;font-size:12px;color:var(--muted)">${b}</p>`)}
                </div>
              </details>
            </div>
          </div>`)}</div>
        </div>
        <div>
          <span class="card-sub" style="text-transform:uppercase;font-weight:700;font-size:11px;letter-spacing:0.4px">Motor</span>
          <div style="margin-top:6px;display:flex;flex-direction:column;gap:8px;align-items:flex-start">
            <span class="pill" style=${`color:${ritmo.engine.enabled === true ? 'var(--green-dark)' : ritmo.engine.enabled === false ? 'var(--orange-ink)' : 'var(--muted)'}`}>
              <span class=${'dot ' + (ritmo.engine.enabled === true ? 'ok' : ritmo.engine.enabled === false ? 'bad' : 'off')}></span>
              ${ritmo.engine.enabled === true ? 'Motor ligado' : ritmo.engine.enabled === false ? 'Motor desligado' : 'Motor: status desconhecido'}
            </span>
            <span style="font-size:12px;color:var(--muted)">${ritmo.engine.last_tick_utc ? `Último tique: ${ritmo.engine.last_tick_rel} (enviou ${ritmo.engine.last_tick_sent})` : 'Sem tique registrado ainda'}</span>
            ${ritmo.engine.stalled ? html`<span class="tag amber">cron parado?</span>` : null}
          </div>
        </div>
      </div>`}
    </${Card}>`;
}
