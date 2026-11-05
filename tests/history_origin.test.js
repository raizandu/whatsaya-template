import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

test('a confirmação explícita corrige e sobrevive a eco de origem ambígua', async () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'origin-test-'));
  process.env.WHATSAPP_HISTORY_DB_PATH = path.join(dir, 'messages.db');
  try {
    const { persistMessageOrigin } = await import('../history_bridge.js');
    await persistMessageOrigin('lead@s.whatsapp.net', 'id1', 'human_device_inferred');
    await persistMessageOrigin('lead@s.whatsapp.net', 'id1', 'ai');
    await persistMessageOrigin('lead@s.whatsapp.net', 'id1', 'human_device_inferred');
    const value = execFileSync('python3', ['-c',
      'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select origin from message_origins").fetchone()[0])',
      process.env.WHATSAPP_HISTORY_DB_PATH], { encoding: 'utf8' }).trim();
    assert.equal(value, 'ai');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
