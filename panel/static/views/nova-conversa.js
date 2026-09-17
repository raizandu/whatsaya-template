// Diálogo "Nova conversa" da aba Atendimento: atendente busca um contato
// existente ou cadastra um número novo, escreve a primeira mensagem e abre o
// atendimento já assumido. Mesma ação de backend nos dois casos
// (`atendimento/iniciar`) — aqui só a UI.
import { useEffect, useState } from 'preact/hooks';
import { html, Fragment, api, post, Avatar, normalize, Select } from '../lib.js';

const MSG_MAX = 4096;
const MSG_WARN_AT = 3900;

// Máscara só para o Brasil (DDD + número); outros países vão como dígitos.
function maskPhone(digits, cc) {
  if (cc !== '55') return digits.slice(0, 15);
  const d = digits.slice(0, 11);
  if (d.length <= 2) return d;
  if (d.length <= 7) return `${d.slice(0, 2)} ${d.slice(2)}`;
  return `${d.slice(0, 2)} ${d.slice(2, d.length - 4)}-${d.slice(-4)}`;
}

// Bandeira é informação (o país do número), não decoração. Brasil primeiro; o
// resto em ordem de uso provável. O nono dígito quem decide é o WhatsApp, via ponte.
const COUNTRIES = [
  ['55', '🇧🇷', 'Brasil'], ['351', '🇵🇹', 'Portugal'], ['1', '🇺🇸', 'Estados Unidos / Canadá'], ['54', '🇦🇷', 'Argentina'],
  ['598', '🇺🇾', 'Uruguai'], ['595', '🇵🇾', 'Paraguai'], ['56', '🇨🇱', 'Chile'], ['57', '🇨🇴', 'Colômbia'], ['51', '🇵🇪', 'Peru'],
  ['591', '🇧🇴', 'Bolívia'], ['52', '🇲🇽', 'México'], ['34', '🇪🇸', 'Espanha'], ['39', '🇮🇹', 'Itália'], ['33', '🇫🇷', 'França'],
  ['49', '🇩🇪', 'Alemanha'], ['44', '🇬🇧', 'Reino Unido'], ['353', '🇮🇪', 'Irlanda'], ['31', '🇳🇱', 'Países Baixos'], ['41', '🇨🇭', 'Suíça'],
  ['244', '🇦🇴', 'Angola'], ['258', '🇲🇿', 'Moçambique'], ['238', '🇨🇻', 'Cabo Verde'], ['81', '🇯🇵', 'Japão'], ['61', '🇦🇺', 'Austrália'],
  ['971', '🇦🇪', 'Emirados Árabes'], ['972', '🇮🇱', 'Israel'],
];
const COUNTRY_OPTIONS = COUNTRIES.map(([cc, flag, name]) => ({ value: cc, label: `${flag} +${cc} ${name}` }));

function ResultRow({ contact, assistantName, onSelect }) {
  const blocked = contact.kind === 'blocked';
  const atd = contact.atendimento;
  const emAtendimento = atd && atd.responsavel_tipo !== 'nenhum';
  const chip = blocked
    ? { label: 'Bloqueado', tone: 'orange' }
    : emAtendimento
      ? { label: `Em atendimento com ${atd.responsavel_tipo === 'ia' ? assistantName : (atd.responsavel_nome || 'alguém')}`, tone: '' }
      : null;
  return html`<li>
    <button type="button" class="nc-result" disabled=${blocked} onClick=${() => onSelect(contact)}>
      <${Avatar} name=${contact.name} url=${contact.avatar_url} className="contacts-avatar"/>
      <span class="nc-result-main"><b>${contact.name}</b><small>${contact.phone}</small></span>
      ${chip ? html`<span class=${'tag' + (chip.tone ? ' ' + chip.tone : '')}>${chip.label}</span>` : null}
    </button>
  </li>`;
}

export default function NovaConversaDialog({ onClose, onCreated, setToast, assistantName, dailyLimit }) {
  const [contacts, setContacts] = useState(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(null);
  const [nome, setNome] = useState('');
  const [telefone, setTelefone] = useState('');
  const [pais, setPais] = useState('55');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/api/contacts').then((body) => setContacts(body.contacts || [])).catch(() => setContacts([]));
  }, []);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [onClose]);

  const needle = normalize(query.trim());
  const resultados = needle && contacts
    ? contacts.filter((c) => normalize([c.name, c.phone].join(' ')).includes(needle)).slice(0, 8)
    : [];

  const telefoneDigits = telefone.replace(/\D/g, '');
  const nomeValido = nome.trim().length >= 2 && nome.trim().length <= 80;
  const podeEnviar = message.trim().length > 0 && message.length <= MSG_MAX
    && (selected ? true : nomeValido && telefoneDigits.length >= 10);

  const submit = async () => {
    setError('');
    setSending(true);
    try {
      const body = { message: message.trim() };
      if (selected) body.chat_id = selected.chat_id;
      else { body.phone = `+${pais}${telefoneDigits}`; body.name = nome.trim(); }
      const result = await post('/api/actions/atendimento/iniciar', body);
      setToast(result.warning || 'Conversa iniciada.');
      onCreated(result.chat_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  };

  return html`<div class="nc-overlay" onClick=${onClose}>
    <div class="nc-dialog" role="dialog" aria-modal="true" aria-label="Nova conversa" onClick=${(e) => e.stopPropagation()}>
      <header class="nc-head">
        <b>Nova conversa</b>
        <button type="button" class="nc-close" onClick=${onClose} aria-label="Fechar"><i class="fi fi-rr-cross-small" aria-hidden="true"></i></button>
      </header>
      <div class="nc-body">
        <div class="banner bad nc-banner">
          <span class="dot warn"></span>
          <span class="grow">Mensagem para quem nunca escreveu pode ser marcada como spam pelo WhatsApp. Use com moderação — limite de ${dailyLimit} por dia.</span>
        </div>

        ${selected ? html`<div class="nc-selected">
          <${Avatar} name=${selected.name} url=${selected.avatar_url} className="contacts-avatar"/>
          <span class="nc-result-main"><b>${selected.name}</b><small>${selected.phone}</small></span>
          <button type="button" class="btn sm" onClick=${() => setSelected(null)}>Trocar</button>
        </div>` : html`<${Fragment}>
          <label class="contacts-search nc-search"><span>Buscar contato</span>
            <div><input type="search" value=${query} onInput=${(e) => setQuery(e.target.value)} placeholder="Nome ou telefone" autocomplete="off"/></div>
          </label>
          ${needle && resultados.length ? html`<ul class="nc-results">${resultados.map((c) => html`<${ResultRow} key=${c.chat_id} contact=${c} assistantName=${assistantName} onSelect=${setSelected}/>`)}</ul>` : null}
          ${needle && !resultados.length ? html`<p class="nc-hint">Nenhum contato encontrado. Preencha os dados abaixo para cadastrar um novo.</p>` : null}

          <div class="nc-divider"><span>ou novo contato</span></div>

          <label class="field-label"><span>Nome</span><input class="input" value=${nome} onInput=${(e) => setNome(e.target.value)} maxlength="80" placeholder="Nome do contato"/></label>
          <label class="field-label"><span>Telefone</span>
            <div class="nc-phone">
              <${Select} value=${pais} options=${COUNTRY_OPTIONS} onChange=${setPais} ariaLabel="País do número" className="nc-country"/>
              <input class="input" value=${maskPhone(telefoneDigits, pais)} inputmode="numeric" onInput=${(e) => setTelefone(e.target.value)} placeholder=${pais === '55' ? '62 99999-0000' : 'número sem o código do país'}/>
            </div>
            <small class="nc-hint">${pais === '55' ? 'Com DDD, ex.: 62 99999-0000. O nono dígito é resolvido pelo WhatsApp.' : `Número local, sem o +${pais}.`}</small>
          </label>
        </${Fragment}>`}

        <label class="field-label nc-message"><span>Primeira mensagem</span>
          <textarea class="input" rows="4" value=${message} maxlength=${MSG_MAX} onInput=${(e) => setMessage(e.target.value)} placeholder="Escreva a primeira mensagem…"></textarea>
          <small class=${'nc-counter' + (message.length > MSG_WARN_AT ? ' over' : '')}>${message.length}/${MSG_MAX}</small>
        </label>
        ${error ? html`<p class="nc-error">${error}</p>` : null}
      </div>
      <footer class="nc-foot">
        <button type="button" class="btn" onClick=${onClose} disabled=${sending}>Cancelar</button>
        <button type="button" class="btn primary" onClick=${submit} disabled=${!podeEnviar || sending}>${sending ? 'Enviando…' : 'Enviar e abrir atendimento'}</button>
      </footer>
    </div>
  </div>`;
}
