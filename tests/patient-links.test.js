import test from 'node:test';
import assert from 'node:assert/strict';
import {
  isValidPatientDirectorySession,
  parsePatientDirectorySession,
  patientDirectoryListUrl,
  patientDirectoryRecordUrl,
  patientDirectorySessionKey,
} from '../panel/static/patient-links.js';

const session = '123456789';
const validAddress = `https://app.prontuarioverde.com.br/ords/f?p=100:4:${session}:::RP,4:P4_PAC_ID,42`;

test('extrai apenas a sessão de um endereço HTTPS do Prontuário Verde', () => {
  assert.equal(parsePatientDirectorySession(validAddress), session);
  assert.equal(parsePatientDirectorySession(`https://app.prontuarioverde.com.br/ords/f?x=1&p=100:13:${session}:::13`), session);
  assert.equal(parsePatientDirectorySession(' endereço inválido '), null);
});

test('rejeita host, esquema, rota, credenciais, porta e aplicação diferentes', () => {
  const invalid = [
    validAddress.replace('https://', 'http://'),
    validAddress.replace('app.prontuarioverde.com.br', 'evilhost'),
    validAddress.replace('app.prontuarioverde.com.br', 'app.prontuarioverde.com.br.evilhost'),
    validAddress.replace('/ords/f?', '/ords/g?'),
    validAddress.replace('https://', 'https://usuario:senha@'),
    validAddress.replace('com.br/ords', 'com.br:8443/ords'),
    validAddress.replace('p=100:', 'p=0:'),
    validAddress.replace(`p=100:4:${session}`, 'p=100:4:0'),
    validAddress.replace(`p=100:4:${session}`, 'p=100:4:'),
    `${validAddress}#fragmento`,
  ];
  for (const value of invalid) assert.equal(parsePatientDirectorySession(value), null, value);
});

test('monta links canônicos da lista e da ficha somente com identificadores válidos', () => {
  assert.equal(patientDirectoryListUrl(session), `https://app.prontuarioverde.com.br/ords/f?p=100:13:${session}:::13`);
  assert.equal(patientDirectoryRecordUrl(session, 42), `https://app.prontuarioverde.com.br/ords/f?p=100:4:${session}:::RP,4:P4_PAC_ID,P4_PAGINA_RETORNO:42,13`);
  assert.equal(patientDirectoryListUrl('0'), null);
  assert.equal(patientDirectoryListUrl('12x'), null);
  for (const patientId of ['0', '01', '-1', '1:2', null]) assert.equal(patientDirectoryRecordUrl(session, patientId), null);
});

test('session é validada e a chave de armazenamento fica separada por usuário', () => {
  assert.equal(isValidPatientDirectorySession(session), true);
  assert.equal(isValidPatientDirectorySession('0'), false);
  assert.equal(isValidPatientDirectorySession('1x'), false);
  assert.equal(patientDirectorySessionKey('dra liliane'), 'whatsaya_pv_session:dra%20liliane');
});
