import { html, useApi, post, fmt, Tile, Card, ErrorBox, Empty } from '../lib.js';

export default function Followups({ period, setToast }) {
  const fu = useApi(`/api/followups?period=${period}`, { every: 30000 });
  const f = fu.data;

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

  return html`
    <${ErrorBox} error=${fu.error}/>
    <div class="grid c4">
      <${Tile} dark label="Na fila" value=${f ? fmt.int(f.queue.length) : '…'} sub=${first ? `próximo ${first.due_rel}` : 'nada agendado'}/>
      <${Tile} label="Enviados" value=${f ? fmt.int(f.stats.sent) : '…'} sub="sempre citando um fato da conversa"/>
      <${Tile} label="Trouxeram resposta" green value=${f ? fmt.int(f.stats.replied) : '…'} pct=${f ? fmt.pct(f.stats.replied, f.stats.sent) : ''} sub="lead voltou a falar depois do toque"/>
      <${Tile} label="Cancelados antes de sair" value=${f ? fmt.int(f.stats.cancelled) : '…'} sub=${f ? `${f.stats.cancelled_replied} porque o lead respondeu antes` : ''}/>
    </div>

    <div class="grid wide-15 start">
      <${Card} title="Fila de envio" sub="Só sai das 8h às 18h, horário de São Paulo. Resposta do lead ou você assumir cancela o que falta.">
        ${f && f.queue.length === 0 ? html`<${Empty}>Nada na fila. A AYA agenda o próximo toque quando um lead para de responder.</${Empty}>` : null}
        <div class="row-list">${f ? f.queue.map((j) => html`<div class="item" key=${j.id} style=${`align-items:flex-start;padding:14px 0;opacity:${j.paused ? 0.6 : 1}`}>
          <div style="width:86px;flex-shrink:0;display:flex;flex-direction:column;gap:3px">
            <span style=${`font-size:13px;font-weight:700;color:${j.paused ? 'var(--muted-2)' : j.soon ? 'var(--orange)' : 'var(--ink)'}`}>${j.due}</span>
            <span style="font-size:11px;color:var(--muted-2)">${j.due_rel}</span>
          </div>
          <div class="grow" style="gap:6px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span class="name">${j.name}</span><span class="tag">${j.stage}</span>
              <span style="font-size:12px;color:var(--muted)">${j.cadence} · toque ${j.step} de 3</span>
              ${j.paused ? html`<span class="tag amber">Pausado</span>` : null}
            </div>
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
    </div>`;
}
