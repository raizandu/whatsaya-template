import { useEffect, useRef, useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, ErrorBox, Empty } from '../lib.js';

const DEFAULT_LABEL = 'remarketing';

const dateTime = (value) => value
  ? new Date(value).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '';

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    try {
      const el = document.createElement('textarea');
      el.value = text;
      el.style.position = 'fixed';
      el.style.opacity = '0';
      document.body.appendChild(el);
      el.focus();
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      resolve();
    } catch (err) { reject(err); }
  });
}

function ReactivationCard({ item, sent, setToast, reload, go }) {
  const [text, setText] = useState(item.message || '');
  useEffect(() => { setText(item.message || ''); }, [item.message, item.chat_id]);

  const suggest = async () => {
    try {
      const result = await post('/api/actions/reactivation_suggest', { chat_id: item.chat_id });
      setText(result.message);
      reload();
    } catch (err) {
      setToast(`Não gerei a sugestão: ${err.message}`);
    }
  };

  const saveIfChanged = async () => {
    if (text === (item.message || '')) return;
    try {
      await post('/api/actions/reactivation_message', { chat_id: item.chat_id, message: text });
      reload();
    } catch (err) {
      setToast(`Não salvei o texto: ${err.message}`);
    }
  };

  const copy = async () => {
    try {
      await copyText(text);
      setToast('Copiado');
    } catch {
      setToast('Não consegui copiar. Selecione o texto manualmente.');
    }
  };

  const toggleSent = async () => {
    try {
      await post('/api/actions/reactivation_sent', { chat_id: item.chat_id, sent: !sent });
      setToast(sent ? `${item.name} voltou para pendentes` : `Marcado: ${item.name}`);
      reload();
    } catch (err) {
      setToast(`Não atualizei: ${err.message}`);
    }
  };

  return html`<div class="reactivation-card" style=${sent ? 'opacity:0.6' : ''}>
    <div class="reactivation-head">
      <span class="avatar mint">${fmt.initials(item.name)}</span>
      <div class="grow">
        <button type="button" class="reactivation-name" onClick=${() => go(`lead/${encodeURIComponent(item.chat_id)}`)}>${item.name}</button>
        <span class="reactivation-phone">${item.phone}</span>
      </div>
      <span class="tag">${item.stage_label}</span>
    </div>
    ${(item.last_inbound || sent) ? html`<div class="reactivation-meta">
      ${item.last_inbound ? html`<span>último contato ${item.last_inbound}</span>` : null}
      ${sent ? html`<span>enviado em ${dateTime(item.sent_utc)}</span>` : null}
    </div>` : null}
    <textarea class="input reactivation-text" rows="3" placeholder="Gere uma sugestão ou escreva a mensagem…"
      value=${text} readOnly=${sent}
      onInput=${(event) => setText(event.target.value)}
      onBlur=${saveIfChanged}></textarea>
    <div class="reactivation-actions">
      <button class="btn" onClick=${suggest} disabled=${sent}>${item.message ? 'Gerar outra variação' : 'Gerar sugestão'}</button>
      <button class="btn" onClick=${copy} disabled=${!text}>Copiar texto</button>
      <button class=${'btn' + (sent ? '' : ' primary')} onClick=${toggleSent}>${sent ? 'Desmarcar' : 'Marquei que mandei'}</button>
    </div>
  </div>`;
}

export default function Reactivation({ config, setToast, go }) {
  const resource = useApi('/api/reactivation', { every: 30000 });
  const r = resource.data;
  const [label, setLabel] = useState('');
  const [preparing, setPreparing] = useState(false);
  const labelTouched = useRef(false);

  useEffect(() => {
    if (!labelTouched.current && config && config.reactivation && config.reactivation.label) {
      setLabel(config.reactivation.label);
    }
  }, [config]);

  const prepare = async () => {
    const value = label.trim();
    setPreparing(true);
    try {
      const result = await post('/api/actions/reactivation_prepare', value ? { label: value } : {});
      setToast(`${result.added} contatos adicionados, ${result.rearmed} já estavam na lista`);
      resource.reload();
    } catch (err) {
      setToast(err.message);
    } finally {
      setPreparing(false);
    }
  };

  const empty = r && r.pending.length === 0 && r.sent.length === 0;

  return html`
    <${ErrorBox} error=${resource.error}/>
    <div class="page-head" style="align-items:center">
      <span class="card-sub">Aqui você só prepara envios manuais, um contato de cada vez — nada sai daqui sozinho.
        A sugestão de mensagem nunca inventa preço, link ou promessa: revise, edite, copie e cole no seu WhatsApp.
        Espalhe os envios ao longo do dia, de 15 a 20 por dia.</span>
    </div>
    <div class="reactivation-toolbar">
      <label class="field-label">Etiqueta no WhatsApp Business
        <div class="form-row">
          <input class="input" value=${label} placeholder=${DEFAULT_LABEL}
            onInput=${(event) => { labelTouched.current = true; setLabel(event.target.value); }}/>
          <button class="btn primary" onClick=${prepare} disabled=${preparing}>Preparar lista da etiqueta</button>
        </div>
      </label>
    </div>
    ${empty ? html`<${Empty}>Nenhum contato na lista ainda. Marque as conversas com a etiqueta no WhatsApp Business e clique em Preparar lista da etiqueta.</${Empty}>` : html`<div class="reactivation-sections">
      <${Card} title=${`Pendentes (${r ? r.pending.length : 0})`}>
        ${r && r.pending.length === 0 ? html`<${Empty}>Nenhum pendente.</${Empty}>` : null}
        <div class="reactivation-list">${r ? r.pending.map((item) => html`<${ReactivationCard} key=${item.chat_id} item=${item} sent=${false} setToast=${setToast} reload=${resource.reload} go=${go}/>`) : null}</div>
      </${Card}>
      <${Card} title=${`Já contatados (${r ? r.sent.length : 0})`}>
        ${r && r.sent.length === 0 ? html`<${Empty}>Ninguém contatado ainda.</${Empty}>` : null}
        <div class="reactivation-list">${r ? r.sent.map((item) => html`<${ReactivationCard} key=${item.chat_id} item=${item} sent=${true} setToast=${setToast} reload=${resource.reload} go=${go}/>`) : null}</div>
      </${Card}>
    </div>`}
  `;
}
