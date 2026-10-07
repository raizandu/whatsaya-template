import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../bridge.js', import.meta.url), 'utf8');

function bridge(state, queue = []) {
  const start = source.indexOf("messagingRouter.post('/requeue'");
  const end = source.indexOf('// Chat info', start);
  const context = vm.createContext({
    messagingRouter: { post(_route, handler) { context.handler = handler; } },
    connectionState: state,
    sock: {},
    messageQueue: queue,
    MAX_QUEUE_SIZE: 2,
    WHATSAPP_OWNER_NUMBER: '15550000000',
    randomUUID: () => 'dispatch-id',
    resolveContactName: async () => 'Lead',
    activityCounters: { messagesEnqueued: 0, messagesReceived: 0 },
    console: { log() {} },
  });
  vm.runInContext(source.slice(start, end), context);
  return context.handler;
}

function response() {
  return {
    code: 200,
    status(code) { this.code = code; return this; },
    json(body) { this.body = body; return this; },
  };
}

const request = { body: { chatId: '15551112222@s.whatsapp.net', body: 'Olá', messageIds: ['lead-id'] } };

test('resume rejects a disconnected bridge without consuming a queued message', async () => {
  const queue = [];
  const res = response();
  await bridge('disconnected', queue)(request, res);
  assert.equal(res.code, 503);
  assert.equal(queue.length, 0);
});

test('resume rejects a full queue instead of losing its oldest event', async () => {
  const queue = [{ messageId: 'first' }, { messageId: 'second' }];
  const res = response();
  await bridge('connected', queue)(request, res);
  assert.equal(res.code, 503);
  assert.deepEqual(queue.map(item => item.messageId), ['first', 'second']);
});

test('connected resume confirms dispatch and preserves the original inbound identity', async () => {
  const queue = [];
  const res = response();
  await bridge('connected', queue)(request, res);
  assert.equal(res.code, 200);
  assert.equal(res.body.messageId, 'resume:dispatch-id');
  assert.equal(queue.length, 1);
  assert.equal(queue[0].resume.messageIds[0], 'lead-id');
});
