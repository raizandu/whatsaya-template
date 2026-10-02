import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const appSource = readFileSync(new URL('../panel/static/app.js', import.meta.url), 'utf8');
const agendaSource = readFileSync(new URL('../panel/static/views/agenda.js', import.meta.url), 'utf8');

function captureHtml(strings, ...values) {
  return { strings: [...strings], values };
}

function componentFrom(source, name, context = {}) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} component exists`);
  const bodyStart = source.indexOf(') {', start) + 2;
  assert.ok(bodyStart > 1, `${name} body exists`);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}') depth -= 1;
    if (depth === 0) {
      const declaration = source.slice(start, i + 1);
      return vm.runInNewContext(`${declaration}; ${name}`, { html: captureHtml, ...context });
    }
  }
  assert.fail(`${name} component is incomplete`);
}

function helpersFromAgenda() {
  const start = agendaSource.indexOf('function formatReconnectionCountdown(');
  const end = agendaSource.indexOf('// ── datas', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return vm.runInNewContext(`${agendaSource.slice(start, end)}; calendarReconnectionMessage`);
}

function renderedText(node) {
  if (node === null || node === undefined || node === false) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(renderedText).join(' ');
  if (node.strings && node.values) {
    return node.strings.map((part, index) => `${part}${renderedText(node.values[index])}`).join('');
  }
  return '';
}

test('global reconnection banner shows due and unknown states, and hides disabled integration', () => {
  const banner = componentFrom(appSource, 'CalendarReconnectBanner');
  const due = banner({ reconnection: { enabled: true, state: 'due', oauth_available: true } });
  const unknown = banner({ reconnection: { enabled: true, state: 'unknown', oauth_available: true } });
  const disabled = banner({ reconnection: { enabled: false, state: 'disabled' } });

  assert.match(renderedText(due), /vence em breve/);
  assert.match(renderedText(due), /Reconectar Google Agenda/);
  assert.match(renderedText(unknown), /iniciar o acompanhamento da autorização/);
  assert.equal(disabled, null);
});

test('global banner disables OAuth action when server reports missing credentials', () => {
  const banner = componentFrom(appSource, 'CalendarReconnectBanner');
  const output = banner({ reconnection: { enabled: true, state: 'expired', oauth_available: false } });

  assert.match(renderedText(output), /Configure as credenciais no servidor/);
  assert.match(renderedText(output), /expirou/);
  assert.ok(output.values.includes(true));
});

test('agenda countdown follows the absolute deadline, formats days, and hides disabled state', () => {
  const message = helpersFromAgenda();
  const expiresAt = '2026-10-09T12:00:00.000Z';
  const early = message({ enabled: true, state: 'healthy', expires_at: expiresAt }, Date.parse('2026-10-02T12:00:00.000Z'));
  const later = message({ enabled: true, state: 'healthy', expires_at: expiresAt }, Date.parse('2026-10-02T13:00:00.000Z'));
  const disabled = message({ enabled: false, state: 'disabled', expires_at: expiresAt }, Date.parse('2026-10-02T12:00:00.000Z'));

  assert.match(early, /7d 0h/);
  assert.match(later, /6d 23h/);
  assert.equal(disabled, '');
});
