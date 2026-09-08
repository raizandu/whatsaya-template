import { useEffect, useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, Icon, Dot } from '../lib.js';

export default function Connection({ status, setToast }) {
  const metrics = useApi('/api/metrics?period=hoje', { every: 60000 }).data;
  const settings = useApi('/api/whatsapp-settings', { every: 30000 });
  const [qrTick, setQrTick] = useState(0);
  const [debounceDraft, setDebounceDraft] = useState('');
  const waitingQr = status && status.bridge === 'up' && status.connection !== 'connected' && status.qr_available;

  useEffect(() => {
    if (!waitingQr) return;
    const timer = setInterval(() => setQrTick((t) => t + 1), 15000);
    return () => clearInterval(timer);
  }, [waitingQr]);
  useEffect(() => {
    if (settings.data && settings.data.known) setDebounceDraft(String(settings.data.debounce_seconds));
  }, [settings.data && settings.data.debounce_seconds]);

  const pause = async (paused) => {
    try {
      await post('/api/actions/pause', { paused });
      setToast(paused ? 'IA pausada para todos os clientes' : 'IA retomada');
    } catch (err) {
      setToast(`Não consegui: ${err.message}`);
    }
  };

  const saveSettings = async (changes = {}) => {
    if (!settings.data || !settings.data.known) return;
    const next = { ...settings.data, ...changes };
    try {
      await post('/api/actions/whatsapp-settings', {
        reject_calls: next.reject_calls,
        groups_enabled: next.groups_enabled,
        debounce_seconds: next.debounce_seconds,
      });
      setToast('Configurações do WhatsApp salvas');
      settings.reload();
    } catch (err) {
      setToast(`Não consegui salvar: ${err.message}`);
    }
  };

  const bridgeDown = !status || status.bridge !== 'up';
  const connected = !bridgeDown && status.connection === 'connected';
  const health = [
    { label: 'Ponte (bridge.js)', value: bridgeDown ? 'fora do ar' : `no ar · ${fmt.uptime(status.uptime_s)}`, tone: bridgeDown ? 'bad' : 'ok' },
    { label: 'Sessão do WhatsApp', value: connected ? 'conectada' : waitingQr ? 'aguardando QR' : 'desconectada', tone: connected ? 'ok' : waitingQr ? 'warn' : 'bad' },
    { label: 'IA para clientes', value: status && status.paused ? 'pausada' : 'atendendo', tone: status && status.paused ? 'warn' : 'ok' },
    { label: 'Mensagens sem resposta hoje', value: metrics ? (metrics.unanswered.length ? `${metrics.unanswered.length} acima do limite` : 'nenhuma acima do limite') : '…', tone: metrics && metrics.unanswered.length ? 'bad' : 'ok' },
  ];

  const currentSettings = settings.data || {};
  const settingsUnavailable = !currentSettings.known;

  return html`<div class="connection-page">
    <div class="grid c2 start">
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
    </div>
    <${Card} title="Configurações do WhatsApp" sub="Estas opções são aplicadas na hora e continuam valendo depois de reiniciar a conexão.">
      ${settingsUnavailable ? html`<div class="banner warn"><span class="dot warn"></span><span class="grow">A ponte está indisponível. As configurações ficam bloqueadas até a conexão voltar.</span></div>` : null}
      <div class="settings-grid">
        <div class="setting-item">
          <div><b>Recusar ligações automaticamente</b><span>Encerra chamadas de voz ou vídeo recebidas neste número.</span></div>
          <button class=${`toggle-btn ${currentSettings.reject_calls ? 'active' : ''}`} aria-pressed=${Boolean(currentSettings.reject_calls)} disabled=${settingsUnavailable} onClick=${() => saveSettings({ reject_calls: !currentSettings.reject_calls })}>${currentSettings.reject_calls ? 'Ligado' : 'Desligado'}</button>
        </div>
        <div class="setting-item">
          <div><b>Ler mensagens de grupos</b><span>Quando ligado, a AYA pode processar e responder mensagens dos grupos permitidos.</span></div>
          <button class=${`toggle-btn ${currentSettings.groups_enabled ? 'active' : ''}`} aria-pressed=${Boolean(currentSettings.groups_enabled)} disabled=${settingsUnavailable} onClick=${() => saveSettings({ groups_enabled: !currentSettings.groups_enabled })}>${currentSettings.groups_enabled ? 'Ligado' : 'Desligado'}</button>
        </div>
        <form class="setting-item" onSubmit=${(event) => { event.preventDefault(); saveSettings({ debounce_seconds: Number(debounceDraft) }); }}>
          <div><b>Agrupar mensagens por</b><span>Espera inicial para juntar fragmentos enviados em sequência. Use 0 para desligar.</span></div>
          <div class="debounce-control"><input type="number" min="0" max="60" step="1" value=${debounceDraft} disabled=${settingsUnavailable} onInput=${(event) => setDebounceDraft(event.target.value)}/><span>segundos</span><button class="btn" type="submit" disabled=${settingsUnavailable}>Salvar</button></div>
        </form>
      </div>
    </${Card}>
  </div>`;
}
