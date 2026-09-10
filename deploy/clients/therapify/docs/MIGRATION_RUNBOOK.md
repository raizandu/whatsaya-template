# Runbook de cutover em `/opt/whatsaya`

Este procedimento migra dados comerciais sem misturar a migração com a sessão
WhatsApp. Execute em janela de manutenção, com acesso local à VPS e sem copiar
credenciais para o repositório.

## 1. Pré-checagens

1. Confirme que o clone ativo é `/opt/whatsaya`, que o serviço está saudável e
   que há espaço para pelo menos dois snapshots completos.
2. Pare o recebimento de novas mensagens (pause global no painel e desabilite o
   worker/cron do cliente). Não apague nem mova a sessão Baileys.
3. Registre a revisão do template (`git rev-parse HEAD`), a versão do Python e
   o caminho exato do SQLite Therapify. O banco de origem deve permanecer
   somente leitura.
4. Confira `WHATSAPP_OWNER_NUMBER`, `data/.env`, persona, catálogo, manifest de
   mídia e timezone; valores ausentes são bloqueadores, não defaults silenciosos.
5. Faça um backup operacional normal:

   ```bash
   cd /opt/whatsaya
   WHATSAYA_DATA=/opt/whatsaya/data ./deploy/backup-whatsaya.sh
   ```

## 2. Snapshot e dry-run

O importador usa `sqlite3.Connection.backup()` para capturar a origem com WAL
aberto. Não use `cp` do `.db`, não remova `.db-wal`/`.db-shm` e não rode contra o
banco enquanto outro processo escreve.

```bash
cd /opt/whatsaya
mkdir -p /opt/whatsaya/data/migration-reports
python3 deploy/clients/therapify/tools/therapify_migrate.py \
  --source-db /var/lib/therapify/therapify.db \
  --data-dir /opt/whatsaya/data \
  --owner-number "$WHATSAPP_OWNER_NUMBER" \
  --dry-run \
  --report /opt/whatsaya/data/migration-reports/therapify-dry-run.json
```

Revise as contagens sem abrir conteúdo de conversa. O dry-run não cria bancos,
JSONs, backups ou sessão. Schema incompleto, `integrity_check` diferente de
`ok` ou identidade inválida encerra com código 2.

## 3. Execução controlada

1. Mantenha a pausa global e o bridge sem ingestão.
2. Rode sem `--enable-automation` e sem `--activate-escalations`:

   ```bash
   python3 deploy/clients/therapify/tools/therapify_migrate.py \
     --source-db /var/lib/therapify/therapify.db \
     --data-dir /opt/whatsaya/data \
     --owner-number "$WHATSAPP_OWNER_NUMBER" \
     --report /opt/whatsaya/data/migration-reports/therapify-apply.json
   ```

3. Guarde a pasta `data/.hermes/migration-backups/<timestamp>/` e confira no
   relatório apenas contagens, `settings_redacted`, `messages_inserted` e
   `target_after`.
4. Rode as verificações locais:

   ```bash
   python3 -m py_compile deploy/clients/therapify/tools/therapify_migrate.py history_store.py panel/data.py
   python3 -m unittest discover -s tests -v
   ```

5. Abra um lead sintético no painel. Confirme conversa histórica, status,
   compras, appointments, escalonamentos e estágio de reativação; históricos
   não podem criar job de follow-up nem chamada ao LLM.

## 4. Ativação gradual

Após o aceite do painel, configure persona, catálogo, agenda, mídia,
notificações e horários via arquivos/env da instância. Ative a automação para o
primeiro lote somente com uma segunda execução explícita usando
`--enable-automation`; escalonamentos antigos só entram no outbox quando a fila
for revisada e `--activate-escalations` for usado.

Faça um teste de ponta a ponta com número sintético/controle: mensagem inbound,
debounce, resposta, takeover manual, pausa global e rollback do follow-up. Só
então retire a pausa global e habilite o cron do cliente.

## 5. Migração separada da sessão WhatsApp

1. Preserve a sessão antiga em seu backup operacional, com permissões restritas;
   ela não é entrada do importador.
2. Para uma sessão nova, suba o bridge com `WHATSAPP_ENABLED=false`, valide
   persona/configuração, então pareie pelo QR e aguarde `/whatsapp/status` como
   `connected`.
3. Nunca copie chaves Baileys para git, relatório, fixture ou outra instância.
   Se houver troca de número, atualize `WHATSAPP_OWNER_NUMBER` e repita a
   checagem de exclusão do owner antes de liberar mensagens.

## 6. Validação e rollback

Aceite o cutover somente se:

- ambos os SQLite retornarem `PRAGMA integrity_check = ok`;
- o `target_after` bater com as contagens elegíveis do dry-run;
- uma segunda execução informar zero mensagens/vendas novas;
- nenhum item do owner aparecer nos stores;
- contatos manuais/bloqueios permanecerem intactos;
- não houver `.env`, sessão, mídia ou texto de conversa no `git status`.

Se qualquer item falhar, mantenha o bridge pausado. Pare workers, preserve os
logs sanitizados e restaure os arquivos da pasta de backup criada pela execução
(`personal_contacts.json`, `sales.json`, `whatsapp_messages.db` e
`commercial_followups.db`) usando cópia atômica/`sqlite3 .backup` em um caminho
temporário. Reabra os bancos, rode `integrity_check`, mantenha a sessão
WhatsApp separada e só depois decida se corrige a origem ou repete a migração.

O rollback não remove a sessão nem apaga dados amplos; ele restaura apenas os
stores listados da execução que falhou. Após o aceite, retenha o snapshot pelo
período de auditoria acordado e elimine-o por política segura.

