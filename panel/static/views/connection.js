import { useEffect, useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, Icon, Dot } from '../lib.js';

export default function Connection({ status, setToast }) {
  const metrics = useApi('/api/metrics?period=hoje', { every: 60000 }).data;
  const usage = useApi('/api/usage?period=hoje', { every: 120000 }).data;
  const [qrTick, setQrTick] = useState(0);
  const waitingQr = status && status.bridge === 'up' && status.connection !== 'connected' && status.qr_available;

  useEffect(() => {
    if (!waitingQr) return;
    const timer = setInterval(() => setQrTick((t) => t + 1), 15000);
    return () => clearInterval(timer);
  }, [waitingQr]);

  const pause = async (paused) => {
    try {
      await post('/api/actions/pause', { paused });
      setToast(paused ? 'IA pausada para todos os clientes' : 'IA retomada');
    } catch (err) {
      setToast(`Não consegui: ${err.message}`);
    }
  };

  const bridgeDown = !status || status.bridge !== 'up';
  const connected = !bridgeDown && status.connection === 'connected';
  const health = [
    { label: 'Ponte (bridge.js)', value: bridgeDown ? 'fora do ar' : `no ar · ${fmt.uptime(status.uptime_s)}`, tone: bridgeDown ? 'bad' : 'ok' },
    { label: 'Sessão do WhatsApp', value: connected ? 'conectada' : waitingQr ? 'aguardando QR' : 'desconectada', tone: connected ? 'ok' : waitingQr ? 'warn' : 'bad' },
    { label: 'IA para clientes', value: status && status.paused ? 'pausada' : 'atendendo', tone: status && status.paused ? 'warn' : 'ok' },
    { label: 'Mensagens sem resposta hoje', value: metrics ? (metrics.unanswered.length ? `${metrics.unanswered.length} acima do limite` : 'nenhuma acima do limite') : '…', tone: metrics && metrics.unanswered.length ? 'bad' : 'ok' },
    { label: 'Chamadas de modelo hoje', value: usage ? `${fmt.int(usage.calls)} · ${fmt.tokens(usage.input + usage.output)} tokens` : '…', tone: 'ok' },
  ];

  return html`<div class="grid c2 start">
    <div class="card conn-panel">
      ${connected ? html`
        <div class="big mint" style="color:var(--green-dark)"><${Icon.check}/></div>
        <div><h2>WhatsApp conectado</h2><p class="card-sub" style="margin:6px 0 0">sessão ativa ${fmt.uptime(status.uptime_s)}</p></div>
        <p class="card-sub" style="margin:0;max-width:360px">Para trocar de aparelho, desconecte pelo próprio WhatsApp em Aparelhos conectados. A ponte gera um QR novo sozinha.</p>`
      : waitingQr ? html`
        <div class="qr"><img src=${`/api/qr.png?t=${qrTick}`} alt="QR code de pareamento"/></div>
        <div><h2>Escaneie para parear</h2><p class="card-sub" style="margin:6px 0 0">WhatsApp → Aparelhos conectados → Conectar um aparelho</p>
          <p style="margin:6px 0 0;font-size:13px;color:var(--amber-ink);font-weight:600">O código renova sozinho. A imagem atualiza a cada 15 s.</p></div>`
      : html`
        <div class="big orange" style="color:var(--orange)"><${Icon.power}/></div>
        <div><h2>${bridgeDown ? 'Ponte fora do ar' : 'Ponte desconectada'}</h2>
          <p class="card-sub" style="margin:6px 0 0">${bridgeDown ? 'O painel não alcançou o bridge. Veja o container hermes.' : 'A AYA não recebe nem responde mensagens até parear de novo. O QR aparece aqui quando o bridge gerar um.'}</p></div>`}
    </div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <${Card} title="Saúde da operação" className="health">
        <div class="row-list">${health.map((h) => html`<div class="item" key=${h.label}><${Dot} tone=${h.tone}/><span class="name">${h.label}</span><span class="when" style="color:var(--muted)">${h.value}</span></div>`)}</div>
      </${Card}>
      <${Card} title="Pausa global" className="dark" sub="Suspende a IA para todos os clientes sem desconectar o aparelho. Mensagens continuam chegando no seu WhatsApp.">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px">
          <span style="font-size:14px;font-weight:600">${status && status.paused ? 'IA pausada para clientes' : 'IA atendendo normalmente'}</span>
          <button class=${'btn ' + (status && status.paused ? 'green' : '')} style=${status && status.paused ? '' : 'background:var(--soft);color:var(--ink)'} disabled=${bridgeDown} onClick=${() => pause(!(status && status.paused))}>${status && status.paused ? 'Retomar' : 'Pausar IA'}</button>
        </div>
      </${Card}>
    </div>
  </div>`;
}
