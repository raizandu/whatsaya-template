import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('native ad metadata survives a later fragment in the same inbound batch', () => {
  const scenario = `
    import assert from 'node:assert/strict';
    import { mkdtempSync, rmSync } from 'node:fs';
    import { tmpdir } from 'node:os';
    import path from 'node:path';
    const dir = mkdtempSync(path.join(tmpdir(), 'wa-ads-'));
    process.env.WHATSAPP_MODE = 'bot';
    process.env.WHATSAPP_ALLOWED_USERS = '*';
    process.env.WHATSAPP_HISTORY_PERSIST_DISABLED = 'true';
    process.env.WHATSAPP_DEBOUNCE_INITIAL_MS = '20';
    process.env.WHATSAPP_DEBOUNCE_MIN_MS = '5';
    process.argv.push('--session', dir, '--state-dir', path.join(dir, 'state'));
    const b = await import('./bridge.js');
    b.setSock({ user: { id: '15550000000@s.whatsapp.net' }, readMessages: async () => {}, sendPresenceUpdate: async () => {} });
    const chat = '15551112222@s.whatsapp.net';
    const event = (id, message) => ({ key: { id, remoteJid: chat, fromMe: false }, message, messageTimestamp: 1793650000 });
    await b.onMessagesUpsert({ type: 'notify', messages: [
      event('plain-first', { conversation: 'Oi' }),
      event('native-second', { extendedTextMessage: { text: 'Quero saber mais', contextInfo: {
        externalAdReply: { sourceId: 'ad-native-42', title: 'Therapify', sourceApp: 'facebook', ctwaClid: 'click-42' },
      } } }),
      event('inferred-third', { conversation: 'Olá! Tenho interesse e queria mais informações, por favor.' }),
    ] });
    await new Promise(resolve => setTimeout(resolve, 80));
    const incoming = b.getMessageQueue()[0];
    assert.equal(incoming.leadMetadata?.ad_id, 'ad-native-42');
    assert.equal(incoming.leadMetadata?.ctwa_clid, 'click-42');
    assert.equal(incoming.leadMetadata?.origin_evidence, 'native');
    assert.equal(incoming.leadMetadata?.campaign, undefined, 'creative title is not a campaign identifier');
    assert.deepEqual(incoming.debounceIds, ['plain-first', 'native-second', 'inferred-third']);
    rmSync(dir, { recursive: true, force: true });
    process.exit(0);
  `;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', scenario], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
});

test('the real bridge stores a native ad receipt before queuing its event', () => {
  const scenario = `
    import assert from 'node:assert/strict';
    import { mkdtempSync, rmSync } from 'node:fs';
    import { execFileSync } from 'node:child_process';
    import { tmpdir } from 'node:os';
    import path from 'node:path';
    const dir = mkdtempSync(path.join(tmpdir(), 'wa-ad-receipt-'));
    process.env.WHATSAPP_MODE = 'bot';
    process.env.WHATSAPP_ALLOWED_USERS = '*';
    process.env.WHATSAPP_HISTORY_PERSIST_DISABLED = 'false';
    process.env.WHATSAPP_HISTORY_DB_PATH = path.join(dir, 'messages.db');
    process.env.WHATSAPP_DEBOUNCE_INITIAL_MS = '0';
    process.argv.push('--session', path.join(dir, 'session'), '--state-dir', path.join(dir, 'state'));
    const b = await import('./bridge.js');
    b.setSock({ user: { id: '15550000000@s.whatsapp.net' }, readMessages: async () => {} });
    await b.onMessagesUpsert({ type: 'notify', messages: [{
      key: { id: 'ad-proof', remoteJid: '15551112222@s.whatsapp.net', fromMe: false }, messageTimestamp: 1793650000,
      message: { extendedTextMessage: { text: 'Olá', contextInfo: { externalAdReply: {
        sourceId: 'ad-real-43', title: 'Therapify', sourceApp: 'ig', ctwaClid: 'click-43',
      }, conversionDelaySeconds: 0 } } },
    }] });
    assert.equal(b.getMessageQueue()[0].leadMetadata.ad_id, 'ad-real-43');
    const raw = execFileSync('python3', ['-c',
      'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select metadata_json from lead_attribution where message_id=\\\'ad-proof\\\'").fetchone()[0])',
      process.env.WHATSAPP_HISTORY_DB_PATH], { encoding: 'utf8' });
    const metadata = JSON.parse(raw);
    assert.equal(metadata.ctwa_clid, 'click-43');
    assert.equal(metadata.ad_source_app, 'instagram');
    assert.equal(metadata.origin_evidence, 'native');
    assert.equal(metadata.conversion_delay_seconds, 0);
    rmSync(dir, { recursive: true, force: true });
    process.exit(0);
  `;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', scenario], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
});
