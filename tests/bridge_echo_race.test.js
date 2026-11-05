import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('outbound echo arriving before ACK does not silence the conversation; manual sends still do', () => {
  const scenario = `
    import assert from 'node:assert/strict';
    import { mkdtempSync, rmSync } from 'node:fs';
    import { tmpdir } from 'node:os';
    import path from 'node:path';
    const dir = mkdtempSync(path.join(tmpdir(), 'wa-echo-test-'));
    process.env.WHATSAPP_MODE = 'bot';
    process.env.WHATSAPP_HISTORY_PERSIST_DISABLED = 'true';
    process.argv.push('--session', dir, '--state-dir', path.join(dir, 'state'));
    const bridge = await import('./bridge.js');
    const chat = '15551112222@s.whatsapp.net';
    const other = '15553334444@s.whatsapp.net';
    const evt = (jid, id, text) => ({ key: { remoteJid: jid, id, fromMe: true }, message: { conversation: text } });
    bridge.setSock({ user: { id: '15550000000@s.whatsapp.net' },
      sendMessage: async (jid, payload, options) => {
        const id = options?.messageId || 'baileys-generated-after-send';
        await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(jid, id, payload.text)] });
        assert.equal(Boolean(bridge.getSilencedChats()[jid]), false, 'bot echo triggered takeover before ACK');
        await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(other, 'manual-before-ack', 'Estou atendendo')] });
        assert.equal(Boolean(bridge.getSilencedChats()[other]), true, 'real owner reply must silence immediately');
        return { key: { id } };
      },
    });
    await bridge.sendWithTimeout(chat, { text: 'Mensagem automática' }, 1000);
    await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(chat, 'manual-after-ack', 'Vou assumir')] });
    assert.equal(Boolean(bridge.getSilencedChats()[chat]), true, 'manual reply must silence');
    await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(chat, 'owner-command', '!retomar')] });
    assert.equal(Boolean(bridge.getSilencedChats()[chat]), false, 'owner command must still resume');

    const slowChat = '15554445555@s.whatsapp.net';
    let slowId, finishSlow;
    bridge.setSock({ user: { id: '15550000000@s.whatsapp.net' },
      sendMessage: (jid, _payload, options) => {
        if (jid === slowChat) {
          slowId = options.messageId;
          return new Promise(resolve => { finishSlow = () => resolve({ key: { id: slowId } }); });
        }
        return Promise.resolve({ key: { id: options.messageId } });
      },
    });
    const slowSend = bridge.sendWithTimeout(slowChat, { text: 'Em voo' }, 5000);
    for (let i = 0; i < 55; i++) await bridge.sendWithTimeout(chat, { text: 'Outro envio' }, 5000);
    await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(slowChat, slowId, 'Em voo')] });
    assert.equal(Boolean(bridge.getSilencedChats()[slowChat]), false, 'in-flight ID must survive cache eviction');
    await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(slowChat, 'manual-during-send', 'Vou assumir agora')] });
    assert.equal(Boolean(bridge.getSilencedChats()[slowChat]), true, 'manual intervention during a send must silence');
    finishSlow();
    await slowSend;

    const ackedChat = '15558889999@s.whatsapp.net';
    const acked = await bridge.sendWithTimeout(ackedChat, { text: 'Já confirmado' }, 5000);
    for (let i = 0; i < 55; i++) await bridge.sendWithTimeout(chat, { text: 'Outro envio' }, 5000);
    await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(ackedChat, acked.key.id, 'Já confirmado')] });
    assert.equal(Boolean(bridge.getSilencedChats()[ackedChat]), false, 'late echo after ACK must survive cache eviction');

    const timeoutChat = '15556667777@s.whatsapp.net';
    let timeoutId;
    bridge.setSock({ user: { id: '15550000000@s.whatsapp.net' },
      sendMessage: (_jid, _payload, options) => { timeoutId = options.messageId; return new Promise(() => {}); },
    });
    await assert.rejects(bridge.sendWithTimeout(timeoutChat, { text: 'Envio incerto' }, 10), /timed out/);
    await bridge.onMessagesUpsert({ type: 'notify', messages: [evt(timeoutChat, timeoutId, 'Envio incerto')] });
    assert.equal(Boolean(bridge.getSilencedChats()[timeoutChat]), false, 'late echo after timeout must not be mistaken for manual');
    rmSync(dir, { recursive: true, force: true });
    process.exit(0);
  `;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', scenario], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
});
