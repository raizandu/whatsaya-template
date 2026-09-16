import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

const TEST_ROOT = path.join('/tmp', `whatsaya-bridge-media-test-${process.pid}`);
fs.mkdirSync(TEST_ROOT, { recursive: true });
process.on('exit', () => fs.rmSync(TEST_ROOT, { recursive: true, force: true }));
process.env.HOME = TEST_ROOT;
process.env.WHATSAPP_HISTORY_DB_PATH = path.join(TEST_ROOT, 'whatsapp_messages.db');
process.env.WHATSAPP_HISTORY_PERSIST_DISABLED = 'true';
process.env.WHATSAPP_OWNER_NUMBER = '99999';
process.env.WHATSAPP_MODE = 'bot';

const { shouldPersistMedia, mediaObjectKey, MEDIA_MAX_BYTES, getRuntimeSettings, updateRuntimeSettings } = await import('../bridge.js');

const on = { saveClientMedia: true };

test('desligado por padrão: nada é guardado mesmo com R2', () => {
  assert.equal(getRuntimeSettings().saveClientMedia, false);
  assert.equal(shouldPersistMedia({ settings: getRuntimeSettings(), r2Configured: true, mediaType: 'image', size: 10 }), false);
});

test('ligado sem R2 não guarda; ligado com R2 guarda imagem, áudio, ptt e documento', () => {
  assert.equal(shouldPersistMedia({ settings: on, r2Configured: false, mediaType: 'image', size: 10 }), false);
  for (const mediaType of ['image', 'audio', 'ptt', 'document']) {
    assert.equal(shouldPersistMedia({ settings: on, r2Configured: true, mediaType, size: 10 }), true, mediaType);
  }
  for (const mediaType of ['sticker', 'contacts', 'location']) {
    assert.equal(shouldPersistMedia({ settings: on, r2Configured: true, mediaType, size: 10 }), false, mediaType);
  }
});

test('vídeo respeita o teto de 25 MB e exige tamanho conhecido', () => {
  assert.equal(shouldPersistMedia({ settings: on, r2Configured: true, mediaType: 'video', size: MEDIA_MAX_BYTES }), true);
  assert.equal(shouldPersistMedia({ settings: on, r2Configured: true, mediaType: 'video', size: MEDIA_MAX_BYTES + 1 }), false);
  assert.equal(shouldPersistMedia({ settings: on, r2Configured: true, mediaType: 'video', size: NaN }), false);
});

test('chave vem de ids e mime, nunca do nome do cliente', () => {
  assert.equal(mediaObjectKey('5511999@s.whatsapp.net', 'ABC123', 'image/jpeg'), 'media/5511999/ABC123.jpg');
  assert.equal(mediaObjectKey('123@lid', 'X-1', 'audio/ogg; codecs=opus'), 'media/123/X-1.ogg');
  assert.equal(mediaObjectKey('1@s.whatsapp.net', 'M', 'application/octet-stream', '../../etc/passwd.docx'), 'media/1/M.docx');
  assert.equal(mediaObjectKey('1@s.whatsapp.net', 'M', 'application/x-unknown', 'nome sem ext'), 'media/1/M.bin');
  assert.equal(mediaObjectKey('1@s.whatsapp.net', 'M', '', 'a.<script>'), 'media/1/M.bin');
});

test('runtime settings aceita saveClientMedia e trata ausência como false', () => {
  const base = { rejectCalls: false, groupsEnabled: false, debounceInitialMs: 0 };
  assert.equal(updateRuntimeSettings(base).saveClientMedia, false);
  assert.equal(updateRuntimeSettings({ ...base, saveClientMedia: true }).saveClientMedia, true);
  assert.throws(() => updateRuntimeSettings({ ...base, saveClientMedia: 'sim' }), RangeError);
  updateRuntimeSettings(base);
});

test('foto de perfil: chave por dígitos e renovação a cada 7 dias', async () => {
  const { avatarObjectKey, avatarNeedsRefresh, AVATAR_TTL_MS } = await import('../bridge.js');
  assert.equal(avatarObjectKey('5511999@s.whatsapp.net'), 'avatars/5511999.jpg');
  assert.equal(avatarNeedsRefresh(undefined), true);
  assert.equal(avatarNeedsRefresh({ fetchedAt: Date.now(), key: null }), false);
  assert.equal(avatarNeedsRefresh({ fetchedAt: Date.now() - AVATAR_TTL_MS - 1, key: 'avatars/1.jpg' }), true);
  assert.equal(avatarNeedsRefresh({ fetchedAt: 'ontem' }), true);
});
