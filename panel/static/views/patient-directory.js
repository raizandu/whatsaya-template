import { useEffect, useState } from 'preact/hooks';
import { api, html, post } from '../lib.js';
import {
  parsePatientDirectorySession,
  patientDirectoryListUrl,
  patientDirectoryRecordUrl,
  patientDirectorySessionKey,
  isValidPatientDirectorySession,
} from '../patient-links.js';

const ROOT_URL = 'https://app.prontuarioverde.com.br/ords/f?p=100:1';
const saoPauloDateTime = (value) => new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo',
}).format(new Date(value));

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

const cancelKey = (username, appointmentId) => `pv-cancel:${username}:${appointmentId}`;
const readCancel = (username, appointmentId) => {
  if (!username || typeof sessionStorage === 'undefined') return null;
  try {
    const value = JSON.parse(sessionStorage.getItem(cancelKey(username, appointmentId)) || 'null');
    return value && typeof value.request_id === 'string' ? value : null;
  } catch { return null; }
};
const saveCancel = (username, appointmentId, value) => {
  if (!username || typeof sessionStorage === 'undefined') return;
  try { sessionStorage.setItem(cancelKey(username, appointmentId), JSON.stringify(value)); } catch {}
};
const cancelMessage = (status, code) => {
  if (status === 'running') return 'Cancelamento em andamento no Prontuário Verde.';
  if (status === 'pending') return 'Cancelamento enviado para o Prontuário Verde.';
  if (status === 'succeeded') return 'Cancelamento concluído. Atualizando o status conferido…';
  if (status === 'needs_review') return 'O resultado precisa ser conferido no Prontuário Verde antes de tentar novamente.';
  if (code === 'appointment_changed') return 'O agendamento mudou. Atualize a ficha antes de tentar novamente.';
  if (status === 'failed') return 'O Prontuário Verde não confirmou o cancelamento. Confira o agendamento antes de tentar novamente.';
  return '';
};

function PatientDirectoryAppointment({ appointment, username, chatId, enabled, isAdmin, reload }) {
  const [cancel, setCancel] = useState(() => readCancel(username, appointment.id));
  const [busy, setBusy] = useState(false);
  const appointmentStatus = String(appointment.status || '').trim().toLocaleLowerCase('pt-BR');
  const canCancel = enabled && isAdmin && /^\d+$/.test(String(appointment.professional_id || '')) && appointmentStatus === 'agendado';

  useEffect(() => { setCancel(readCancel(username, appointment.id)); }, [username, appointment.id]);

  useEffect(() => {
    if (!cancel || !['pending', 'running'].includes(cancel.status)) return undefined;
    let active = true;
    const expiresAt = (cancel.started_at || Date.now()) + 15 * 60 * 1000;
    let timer;
    const poll = async () => {
      if (Date.now() >= expiresAt) {
        const review = { ...cancel, status: 'needs_review', code: 'panel_poll_expired' };
        saveCancel(username, appointment.id, review);
        if (active) setCancel(review);
        return;
      }
      try {
        const result = await api(`/api/prontuario-verde/cancellations/${encodeURIComponent(cancel.request_id)}`);
        const updated = { ...cancel, status: result.status, code: result.code || '', updated_at: result.updated_at || '' };
        saveCancel(username, appointment.id, updated);
        if (active) {
          setCancel(updated);
          if (result.status === 'succeeded') reload();
        }
        if (!['succeeded', 'failed', 'needs_review'].includes(result.status)) timer = setTimeout(poll, 2500);
      } catch {
        if (active) timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, [cancel && cancel.request_id, cancel && cancel.status, username, appointment.id]);

  useEffect(() => {
    if (!cancel || cancel.status !== 'succeeded' || appointmentStatus !== 'agendado') return undefined;
    const expiresAt = (cancel.started_at || Date.now()) + 15 * 60 * 1000;
    const timer = setInterval(() => {
      if (Date.now() >= expiresAt) {
        clearInterval(timer);
        return;
      }
      reload();
    }, 3000);
    return () => clearInterval(timer);
  }, [cancel && cancel.status, appointmentStatus]);

  const requestCancel = async () => {
    const start = new Date(appointment.start).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' });
    if (!window.confirm(`Cancelar ${appointment.type} em ${start}? Esta ação altera o Prontuário Verde e não envia mensagem ao paciente.`)) return;
    setBusy(true);
    try {
      const result = await post('/api/actions/prontuario-verde/appointment-cancel', {
        chat_id: chatId,
        appointment_id: appointment.id,
        expected_start: appointment.start,
        expected_end: appointment.end,
      });
      const next = { request_id: result.request_id, status: result.status, started_at: Date.now() };
      saveCancel(username, appointment.id, next);
      setCancel(next);
    } catch (error) {
      setCancel({ status: 'failed', code: 'request_rejected', message: error.message });
    } finally {
      setBusy(false);
    }
  };

  const success = appointmentStatus === 'cancelado' || (cancel && cancel.status === 'succeeded');
  const cancelPending = !success && cancel && ['pending', 'running'].includes(cancel.status);
  const reviewNeeded = !success && cancel && cancel.status === 'needs_review';
  return html`<article class="patient-directory-appointment" key=${appointment.id}>
    <div class="patient-directory-appointment-head">
      <b>${appointment.type}</b>
      <span class="patient-directory-status">${appointment.status}</span>
    </div>
    <div>${saoPauloDateTime(appointment.start)}–${new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit',
    }).format(new Date(appointment.end))}</div>
    <small>${appointment.professional_name}</small>
    ${appointment.purpose === 'test' ? html`<small class="patient-directory-test">Teste de integração</small>` : null}
    <small>Conferido no Prontuário Verde em ${saoPauloDateTime(appointment.verified_at)} · horário de São Paulo.</small>
    ${canCancel ? html`<button type="button" class="btn sm patient-directory-cancel" disabled=${busy || cancelPending || reviewNeeded || success} onClick=${requestCancel}>${cancelPending ? 'Cancelando…' : reviewNeeded ? 'Verificação pendente' : success ? 'Cancelamento concluído' : 'Cancelar consulta'}</button>` : null}
    ${cancel && (cancelPending || success || reviewNeeded || cancel.status === 'failed') ? html`<small class=${`patient-directory-cancel-status${reviewNeeded ? ' review' : ''}`} role="status">${success && appointmentStatus !== 'agendado' ? 'Cancelamento confirmado no Prontuário Verde.' : cancel.message || cancelMessage(cancel.status, cancel.code)}</small>` : null}
  </article>`;
}

export function NextAppointmentSummary({ nextAppointment }) {
  if (!nextAppointment || nextAppointment.status !== 'scheduled' || !nextAppointment.appointment) return null;
  const appointment = nextAppointment.appointment;
  return html`<div class="patient-next-summary" aria-label="Resumo da próxima consulta" title=${nextAppointment.updated_at ? `Atualizado em ${saoPauloDateTime(nextAppointment.updated_at)}` : ''}>
    <strong>Próxima consulta: ${saoPauloDateTime(appointment.start)}</strong>
    <small>${appointment.professional_name} · Prontuário Verde</small>
  </div>`;
}

export default function PatientDirectory({ directory, nextAppointment = null, appointments = [], username, chatId, isAdmin = false, cancellationEnabled = false, reload = () => {} }) {
  const [session, setSession] = useState(() => readSession(username));
  const [connectionError, setConnectionError] = useState('');
  const connected = Boolean(session);

  useEffect(() => {
    const stored = readSession(username);
    setSession(stored);
  }, [username]);

  if (!directory) return null;

  const connect = (event) => {
    event.preventDefault();
    const parsed = parsePatientDirectorySession(new FormData(event.currentTarget).get('pv_url'));
    event.currentTarget.reset();
    if (!parsed) {
      setConnectionError('Não encontrei a conexão nesse endereço. Abra uma ficha no Prontuário Verde neste navegador e copie o endereço completo da aba.');
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
      <small>Use o Prontuário Verde logado neste mesmo navegador e perfil.</small>
    </div>
    ${nextAppointment ? html`<div class="patient-directory-appointments" aria-label="Próxima consulta">
      <span class="card-sub">Próxima consulta</span>
      ${nextAppointment.status === 'scheduled' && nextAppointment.appointment ? html`
        <b>${saoPauloDateTime(nextAppointment.appointment.start)}</b>
        <small>${nextAppointment.appointment.professional_name}</small>
        <small>${nextAppointment.appointment.status}</small>
      ` : html`<small>${nextAppointment.status === 'not_found' ? 'Nenhuma próxima consulta identificada no período consultado.' : 'Não foi possível confirmar a próxima consulta com dados atualizados.'}</small>`}
      ${nextAppointment.updated_at ? html`<small>Atualizado em ${saoPauloDateTime(nextAppointment.updated_at)} · horário de São Paulo.</small>` : null}
      ${nextAppointment.coverage_end ? html`<small>Agenda consultada até ${new Intl.DateTimeFormat('pt-BR', {dateStyle: 'short', timeZone: 'America/Sao_Paulo'}).format(new Date(Date.parse(nextAppointment.coverage_end) - 1))}. Alterações recentes podem ainda não aparecer.</small>` : null}
    </div>` : null}
    ${appointments.length ? html`<div class="patient-directory-appointments">
      <span class="card-sub">Agendamentos conferidos</span>
      ${appointments.map((appointment) => html`<${PatientDirectoryAppointment} key=${appointment.id} appointment=${appointment} username=${username} chatId=${chatId} enabled=${cancellationEnabled} isAdmin=${isAdmin} reload=${reload}/>`)}
    </div>` : null}
    <details class="patient-directory-connection">
      <summary>${connected ? 'Conexão salva · atualizar' : 'Conectar esta aba'}</summary>
      <div class="patient-directory-connection-body">
        <a class="patient-directory-link" href=${ROOT_URL} target="_blank" rel="noopener noreferrer">Abrir Prontuário Verde</a>
        <small>Abra uma ficha da mesma clínica neste navegador e copie o endereço completo dessa aba. Não use um endereço copiado de outro navegador.</small>
        <form class="patient-directory-form patient-directory-connect" onSubmit=${connect}>
          <label class="atd-field"><span>Endereço da aba do Prontuário Verde</span><input class="input" name="pv_url" autocomplete="off" spellcheck="false"/></label>
          <button class="btn sm" type="submit">Conectar aba</button>
        </form>
        ${connected ? html`<small class="patient-directory-session-hint">Se trocar de navegador ou fizer novo login, atualize a conexão com um endereço gerado nele.</small><button type="button" class="patient-directory-link" onClick=${disconnect}>Desconectar</button>` : null}
      </div>
    </details>
    ${connectionError ? html`<small class="patient-directory-error" role="alert">${connectionError}</small>` : null}
  </section>`;
}
