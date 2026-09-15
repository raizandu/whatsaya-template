import { useEffect, useState } from 'preact/hooks';
import { html, useApi, post, fmt, Icon, Dot } from '../lib.js';

// Configurações: estado geral, conexão, saúde e opções da ponte. Desenho do
// Aya Design System (ui_kits/aya-platform, tela Configurações): seções com
// cabeçalho, linhas ícone + título + descrição + controle, switch de verdade.
// Cada opção salva na hora — não há "salvar alterações" global.

function Switch({ checked, disabled, label, onChange }) {
  return html`<input type="checkbox" role="switch" class="switch" checked=${Boolean(checked)} disabled=${disabled} aria-label=${label} onChange=${onChange}/>`;
}

function Row({ icon, tone, title, description, children }) {
  return html`<div class="settings-row">
    <span class=${'settings-row-icon' + (tone ? ' ' + tone : '')}>${icon ? html`<i class=${`fi fi-rr-${icon}`} aria-hidden="true"></i>` : null}${tone && !icon ? html`<${Dot} tone=${tone}/>` : null}</span>
    <div class="settings-row-copy"><b>${title}</b>${description ? html`<span>${description}</span>` : null}</div>
    ${children ? html`<div class="settings-row-detail">${children}</div>` : null}
  </div>`;
}

function SectionHead({ title, sub, children }) {
  return html`<div class="settings-section-head"><div><h2>${title}</h2>${sub ? html`<p>${sub}</p>` : null}</div>${children || null}</div>`;
}

export default function Connection({ status, setToast, assistantName }) {
  const metrics = useApi('/api/metrics?period=hoje', { every: 60000 }).data;
  const settings = useApi('/api/whatsapp-settings', { every: 30000 });
  const [qrTick, setQrTick] = useState(0);
  const [debounceDraft, setDebounceDraft] = useState('');
  const [pairingStarted, setPairingStarted] = useState(false);
  const pairingInfo = status && status.pairing;
  const pairingActive = Boolean(pairingInfo && pairingInfo.pairing);
  const waitingQr = status && status.bridge === 'up' && status.connection !== 'connected'
    && (pairingInfo ? pairingActive : status.qr_available);

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
      setToast('Configuração aplicada na ponte');
      settings.reload();
    } catch (err) {
      setToast(`Não consegui salvar: ${err.message}`);
    }
  };

  const startPairing = async () => {
    setPairingStarted(true);
    try {
      await post('/api/actions/start-pairing', {});
      setToast('Gerando o QR Code. Ele aparecerá aqui em alguns segundos.');
      setTimeout(() => setPairingStarted(false), 30000);
    } catch (err) {
      setPairingStarted(false);
      setToast(`Não consegui gerar o QR: ${err.message}`);
    }
  };

  const bridgeDown = !status || status.bridge !== 'up';
  const connected = !bridgeDown && status.connection === 'connected';
  const paused = Boolean(status && status.paused);
  const aya = assistantName || 'AYA';
  const stateTone = bridgeDown ? 'bad' : paused ? 'warn' : 'ok';
  const stateLabel = bridgeDown ? 'Ponte fora do ar' : paused ? 'IA pausada para clientes' : 'IA ativa';
  const stateDetail = bridgeDown
    ? `${aya} não recebe mensagens até a ponte voltar.`
    : connected ? `WhatsApp conectado · ponte no ar ${fmt.uptime(status.uptime_s)}`
    : waitingQr ? 'Ponte no ar · aguardando o pareamento do aparelho'
    : 'Ponte no ar · sessão do WhatsApp desconectada';

  const supervisorOn = Boolean(pairingInfo && pairingInfo.supervisor === 'running');
  const unanswered = metrics ? metrics.unanswered.length : null;
  const health = [
    { icon: 'signal-alt', tone: bridgeDown ? 'bad' : 'ok', title: 'Ponte com o WhatsApp', description: bridgeDown ? 'Fora do ar. O container do gateway precisa voltar.' : `No ar ${fmt.uptime(status.uptime_s)}.` },
    { icon: 'link-alt', tone: connected ? 'ok' : waitingQr ? 'warn' : 'bad', title: 'Sessão do aparelho', description: connected ? 'Conectada e recebendo mensagens.' : waitingQr ? 'Aguardando a leitura do QR.' : 'Desconectada. Gere um QR para parear de novo.' },
    { icon: 'eye', tone: supervisorOn ? 'ok' : 'warn', title: 'Monitor de pareamento', description: supervisorOn ? 'Ativo: renova o QR e aplica a conexão sozinho.' : 'Inativo: o pareamento precisa ser iniciado à mão.' },
    { icon: 'comment-alt', tone: unanswered === null ? 'warn' : unanswered ? 'bad' : 'ok', title: 'Mensagens sem resposta hoje', description: unanswered === null ? 'Calculando…' : unanswered ? `${unanswered} acima do limite de espera.` : 'Nenhuma acima do limite de espera.' },
  ];

  const currentSettings = settings.data || {};
  const settingsUnavailable = !currentSettings.known;

  return html`<div class="settings-page">
    <section class=${'settings-section state ' + stateTone}>
      <${SectionHead} title="Estado geral" sub="A pausa global interrompe as respostas automáticas para todos os clientes sem desconectar o aparelho. As mensagens continuam chegando no seu WhatsApp."/>
      <div class="settings-state-row">
        <div class="status"><span class=${'status-pill ' + stateTone}><${Dot} tone=${stateTone}/>${stateLabel}</span><small>${stateDetail}</small></div>
        <button class=${'btn ' + (paused ? 'primary' : '')} disabled=${bridgeDown} onClick=${() => pause(!paused)}>
          <i class=${`fi fi-rr-${paused ? 'play' : 'pause'}`} aria-hidden="true"></i>${paused ? 'Retomar atendimento' : 'Pausar IA'}
        </button>
      </div>
    </section>

    <div class="settings-grid">
      <section class="settings-section">
        <${SectionHead} title="Conexão" sub="Pareamento do aparelho com a ponte."/>
        <div class="settings-conn">
        ${connected ? html`
          <div class="big mint"><${Icon.check}/></div>
          <div><h3>WhatsApp conectado</h3><p>sessão ativa ${fmt.uptime(status.uptime_s)}</p></div>
          <p class="settings-conn-note">Para trocar de aparelho, desconecte pelo próprio WhatsApp em Aparelhos conectados. A ponte gera um QR novo sozinha.</p>`
        : waitingQr ? html`
          <div class="qr"><img src=${`/api/qr.png?t=${qrTick}`} alt="QR code de pareamento"/></div>
          <div><h3>Escaneie para parear</h3><p>WhatsApp → Aparelhos conectados → Conectar um aparelho</p></div>
          <p class="settings-conn-note">O código renova sozinho e a imagem atualiza a cada 15 s.${pairingActive ? ' A conexão é aplicada automaticamente depois do scan.' : ''}</p>
          ${pairingActive ? html`<button class="btn sm" disabled=${pairingStarted} onClick=${startPairing}>Gerar outro QR</button>` : null}`
        : html`
          <div class="big orange"><${Icon.power}/></div>
          <div><h3>${bridgeDown ? 'WhatsApp desconectado' : 'Conexão interrompida'}</h3><p>Gere um QR Code e escaneie pelo WhatsApp. A conexão é concluída nesta tela.</p></div>
          <button class="btn green lg" disabled=${pairingStarted} onClick=${startPairing}><i class="fi fi-rr-qrcode" aria-hidden="true"></i>${pairingStarted ? 'Gerando QR Code…' : 'Gerar QR Code'}</button>
          ${pairingInfo && pairingInfo.auto_start ? html`<p class="settings-conn-note">O painel pede um QR sozinho em instantes se a ponte continuar fora do ar.</p>` : null}`}
        </div>
      </section>

      <section class="settings-section">
        <${SectionHead} title="Saúde da operação" sub="O que a ponte e o atendimento estão fazendo agora."/>
        ${health.map((h) => html`<${Row} key=${h.title} icon=${h.icon} tone=${h.tone} title=${h.title} description=${h.description}/>`)}
      </section>

      <section class="settings-section wide">
        <${SectionHead} title="WhatsApp" sub="Aplicado pela ponte na hora e mantido depois de reiniciar a conexão."/>
        ${settingsUnavailable ? html`<div class="banner warn"><span class="dot warn"></span><span class="grow">A ponte está indisponível. As opções ficam bloqueadas até a conexão voltar.</span></div>` : null}
        <${Row} icon="phone-call" title="Recusar ligações" description="Encerra chamadas de voz ou vídeo recebidas neste número, antes de tocar.">
          <${Switch} checked=${currentSettings.reject_calls} disabled=${settingsUnavailable} label="Recusar ligações" onChange=${() => saveSettings({ reject_calls: !currentSettings.reject_calls })}/>
        </${Row}>
        <${Row} icon="users-alt" title="Ler mensagens de grupos" description=${`Quando ligado, ${aya} processa e responde mensagens dos grupos permitidos. Listas de transmissão continuam ignoradas.`}>
          <${Switch} checked=${currentSettings.groups_enabled} disabled=${settingsUnavailable} label="Ler mensagens de grupos" onChange=${() => saveSettings({ groups_enabled: !currentSettings.groups_enabled })}/>
        </${Row}>
        <${Row} icon="hourglass-end" title="Espera inicial" description="Junta mensagens picadas enviadas em sequência antes de responder. Use 0 para desligar.">
          <form class="debounce-form" onSubmit=${(event) => { event.preventDefault(); saveSettings({ debounce_seconds: Number(debounceDraft) }); }}>
            <input type="number" min="0" max="60" step="1" value=${debounceDraft} disabled=${settingsUnavailable} aria-label="Segundos de espera" onInput=${(event) => setDebounceDraft(event.target.value)}/>
            <span>segundos</span>
            <button class="btn sm" type="submit" disabled=${settingsUnavailable || debounceDraft === String(currentSettings.debounce_seconds)}>Aplicar</button>
          </form>
        </${Row}>
      </section>
    </div>
  </div>`;
}
