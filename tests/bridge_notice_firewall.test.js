import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const SOURCE = fs.readFileSync(path.join(import.meta.dirname, '..', 'bridge.js'), 'utf8');

function loadBridgeSystemError() {
  const declarationsStart = SOURCE.indexOf('const CORE_NOTICE_PHRASES = [');
  const declarationsEnd = SOURCE.indexOf('// Send a message\nmessagingRouter.post', declarationsStart);
  assert.notEqual(declarationsStart, -1, 'bridge notice declarations must exist');
  assert.notEqual(declarationsEnd, -1, 'bridge /send route must exist');
  const declarations = SOURCE.slice(declarationsStart, declarationsEnd);
  const context = vm.createContext({});
  vm.runInContext(`${declarations}\nisSystemError;`, context);
  return vm.runInContext('isSystemError', context);
}

function loadBridgeSendHandler(sendCalls, origins = []) {
  const declarationsStart = SOURCE.indexOf('const CORE_NOTICE_PHRASES = [');
  const declarationsEnd = SOURCE.indexOf('// Send a message\nmessagingRouter.post', declarationsStart);
  const routeStart = declarationsEnd + '// Send a message\n'.length;
  const routeEnd = SOURCE.indexOf('// Edit a previously sent message', routeStart);
  assert.notEqual(routeEnd, -1, 'bridge /edit route must follow /send');
  const context = vm.createContext({
    messagingRouter: {
      post(route, handler) {
        if (route === '/send') context.sendHandler = handler;
      },
    },
    sock: {},
    connectionState: 'connected',
    automationBlockReason: () => '',
    console: { log() {}, error() {} },
    stripFishCues: (message) => message,
    stripExecLines: (message) => message,
    quoteCacheLookup: () => null,
    formatOutgoingMessage: (message) => message,
    splitLongMessage: (message) => message.split('|'),
    sleep: async () => {},
    CHUNK_DELAY_MS: 0,
    sendWithTimeout: async () => {
      sendCalls.count += 1;
      return { key: { id: `sent-${sendCalls.count}` } };
    },
    trackSentMessageId() {},
    HISTORY_PERSIST_DISABLED: false,
    persistMessageOrigin: (...args) => origins.push(args),
    rememberQaWatchOutbound() {},
    presenceIdle: async () => {},
    errorCounters: { bridge_send_timeout: 0, bridge_send_failed: 0 },
    activityCounters: { messagesSendFailed: 0 },
    SEND_TIMEOUT_MS: 1000,
  });
  vm.runInContext(SOURCE.slice(declarationsStart, declarationsEnd), context);
  vm.runInContext(SOURCE.slice(routeStart, routeEnd), context);
  assert.equal(typeof context.sendHandler, 'function', 'bridge /send handler must register');
  return context.sendHandler;
}

const isSystemError = loadBridgeSystemError();

test('bridge /send blocks the core empty-reply notice and sends normal text', async () => {
  const notice = '⚠️ No reply: the model returned empty content after retries and any fallback providers. Try `continue`, switch model/provider, or inspect the tool output above.';
  assert.equal(isSystemError(notice), true);
  assert.equal(isSystemError('No reply: the model returned empty content after retries.'), true);
  assert.equal(isSystemError('Tudo bem. Como você vem lidando com isso?'), false);

  const sendCalls = { count: 0 };
  const sendHandler = loadBridgeSendHandler(sendCalls);
  const response = () => ({
    code: 200,
    body: undefined,
    status(code) { this.code = code; return this; },
    json(body) { this.body = body; return this; },
  });

  const blocked = response();
  await sendHandler({ body: { chatId: '15551234567@s.whatsapp.net', message: notice } }, blocked);
  assert.equal(blocked.code, 200);
  assert.equal(blocked.body.success, true);
  assert.equal(sendCalls.count, 0);

  const delivered = response();
  await sendHandler({ body: { chatId: '15551234567@s.whatsapp.net', message: 'Tudo bem. Como você vem lidando com isso?' } }, delivered);
  assert.equal(delivered.body.messageId, 'sent-1');
  assert.equal(sendCalls.count, 1);
});

test('origem explícita do bot é registrada; automation=false sozinho não prova autoria', async () => {
  const sends = { count: 0 };
  const origins = [];
  const handler = loadBridgeSendHandler(sends, origins);
  const response = () => ({ status() { return this; }, json() { return this; } });
  await handler({ body: { chatId: 'lead', message: 'bot', automation: false, messageOrigin: 'ai' } }, response());
  await handler({ body: { chatId: 'lead', message: 'manual', automation: false } }, response());
  await handler({ body: { chatId: 'lead', message: 'followup', automation: true } }, response());
  await handler({ body: { chatId: 'lead', message: 'parte 1|parte 2', automation: true } }, response());
  assert.deepEqual(origins, [['lead', 'sent-1', 'ai'], ['lead', 'sent-3', 'ai'],
                            ['lead', 'sent-4', 'ai'], ['lead', 'sent-5', 'ai']]);
});
