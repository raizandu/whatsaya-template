import { useEffect, useState } from 'preact/hooks';
import { html } from '../lib.js';
import {
  parsePatientDirectorySession,
  patientDirectoryListUrl,
  patientDirectoryRecordUrl,
  patientDirectorySessionKey,
  isValidPatientDirectorySession,
} from '../patient-links.js';

const ROOT_URL = 'https://app.prontuarioverde.com.br/ords/f?p=100:1';

function readSession(username) {
  if (!username || typeof sessionStorage === 'undefined') return '';
  try {
    const session = sessionStorage.getItem(patientDirectorySessionKey(username)) || '';
    return isValidPatientDirectorySession(session) ? session : '';
  } catch { return ''; }
}

function saveSession(username, session) {
  if (!username || typeof sessionStorage === 'undefined') return false;
  try { sessionStorage.setItem(patientDirectorySessionKey(username), session); return true; } catch { return false; }
}

function removeSession(username) {
  if (!username || typeof sessionStorage === 'undefined') return;
  try { sessionStorage.removeItem(patientDirectorySessionKey(username)); } catch {}
}

const statusCopy = (directory) => {
  if (directory.status === 'matched') return { title: 'Cadastro localizado', hint: 'Abra a ficha para conferir os dados do paciente.' };
  if (directory.status === 'ambiguous') return { title: `Possíveis cadastros: ${directory.count || 'mais de um'}`, hint: 'Não foi possível escolher um cadastro com segurança.' };
  if (directory.status === 'not_found') return { title: 'Nenhum cadastro localizado por este telefone', hint: 'Confira se já existe cadastro com outro telefone. Na lista de pacientes, use Criar novo paciente.' };
  return { title: 'Consulta indisponível', hint: 'Consulte os cadastros no Prontuário Verde.' };
};

export default function PatientDirectory({ directory, username }) {
  const [session, setSession] = useState(() => readSession(username));
  const [address, setAddress] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const connected = Boolean(session);

  useEffect(() => {
    const stored = readSession(username);
    setSession(stored);
  }, [username]);

  if (!directory) return null;

  const connect = (event) => {
    event.preventDefault();
    const parsed = parsePatientDirectorySession(address);
    setAddress('');
    if (!parsed) {
      setConnectionError('Endereço inválido. Copie o endereço atual da aba do Prontuário Verde.');
      return;
    }
    if (!saveSession(username, parsed)) {
      setConnectionError('Não consegui guardar a conexão nesta aba. Confira as permissões do navegador.');
      return;
    }
    setSession(parsed);
    setConnectionError('');
    const details = event.currentTarget.closest('details');
    if (details) details.open = false;
  };

  const disconnect = () => {
    removeSession(username);
    setSession('');
    setConnectionError('');
  };

  const copy = statusCopy(directory);
  const recordUrl = directory.status === 'matched' && session
    ? patientDirectoryRecordUrl(session, directory.patient_id)
    : null;
  const listUrl = session ? patientDirectoryListUrl(session) : null;
  const actionLabel = directory.status === 'not_found'
    ? 'Consultar e cadastrar'
    : directory.status === 'ambiguous' ? 'Consultar cadastros' : 'Consultar no sistema';

  return html`<section class="card patient-directory-card" aria-label="Prontuário Verde">
    <div class="card-head"><div><span class="card-title">Prontuário Verde</span><span class="card-sub">Consulta de cadastro</span></div></div>
    <div class="patient-directory-result">
      <b>${copy.title}</b>
      <small>${copy.hint}</small>
      ${recordUrl ? html`<a class="btn primary sm" href=${recordUrl} target="_blank" rel="noopener noreferrer">Abrir prontuário</a>` : null}
      ${directory.status !== 'matched' && listUrl ? html`<a class="btn sm" href=${listUrl} target="_blank" rel="noopener noreferrer">${actionLabel}</a>` : null}
      ${directory.status !== 'matched' && !session ? html`<span class="patient-directory-action-label">${actionLabel}</span>` : null}
      ${directory.status === 'matched' && !recordUrl ? html`<small>Conecte a aba do Prontuário Verde para abrir a ficha.</small>` : null}
    </div>
    <details class="patient-directory-connection">
      <summary>${connected ? 'Aba conectada · atualizar conexão' : 'Conectar esta aba'}</summary>
      <div class="patient-directory-connection-body">
        <a class="patient-directory-link" href=${ROOT_URL} target="_blank" rel="noopener noreferrer">Abrir Prontuário Verde</a>
        <small>Use a aba da mesma clínica. Copie o endereço atual dela.</small>
        <form class="patient-directory-form patient-directory-connect" onSubmit=${connect}>
          <label class="atd-field"><span>Endereço da aba do Prontuário Verde</span><input class="input" name="pv_url" value=${address} onInput=${(event) => setAddress(event.target.value)} autocomplete="off" spellcheck="false"/></label>
          <button class="btn sm" type="submit">Conectar aba</button>
        </form>
        ${connected ? html`<small class="patient-directory-session-hint">Se o sistema pedir login, atualize a conexão com o endereço atual da aba.</small><button type="button" class="patient-directory-link" onClick=${disconnect}>Desconectar</button>` : null}
      </div>
    </details>
    ${connectionError ? html`<small class="patient-directory-error" role="alert">${connectionError}</small>` : null}
  </section>`;
}
