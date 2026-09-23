const PATIENT_DIRECTORY_HOST = 'app.prontuarioverde.com.br';
const PATIENT_DIRECTORY_PATH = '/ords/f';

export const PATIENT_DIRECTORY_SESSION_PREFIX = 'whatsaya_pv_session:';

export const isValidPatientDirectorySession = (session) => /^[1-9]\d{0,30}$/.test(String(session || ''));

export function parsePatientDirectorySession(value) {
  try {
    const url = new URL(String(value || '').trim());
    if (url.protocol !== 'https:'
      || url.hostname !== PATIENT_DIRECTORY_HOST
      || url.port
      || url.pathname !== PATIENT_DIRECTORY_PATH
      || url.username
      || url.password
      || url.hash) return null;

    const match = /^100:\d+:([1-9]\d{0,30})(?::|$)/.exec(url.searchParams.get('p') || '');
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

export function patientDirectorySessionKey(username) {
  return `${PATIENT_DIRECTORY_SESSION_PREFIX}${encodeURIComponent(String(username || '').trim())}`;
}

export function patientDirectoryListUrl(session) {
  if (!isValidPatientDirectorySession(session)) return null;
  return `https://${PATIENT_DIRECTORY_HOST}${PATIENT_DIRECTORY_PATH}?p=100:13:${session}:::13`;
}

export function patientDirectoryRecordUrl(session, patientId) {
  const id = String(patientId || '');
  if (!/^[1-9]\d{0,30}$/.test(id) || !isValidPatientDirectorySession(session)) return null;
  return `https://${PATIENT_DIRECTORY_HOST}${PATIENT_DIRECTORY_PATH}?p=100:4:${session}:::RP,4:P4_PAC_ID,P4_PAGINA_RETORNO:${id},13`;
}
