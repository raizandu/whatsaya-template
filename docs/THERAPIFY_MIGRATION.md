# Migração Therapify → WhatsAYA

O importador [`tools/therapify_migrate.py`](../tools/therapify_migrate.py) é o
único caminho suportado para trazer o SQLite do backend TypeScript para uma
instalação do template. Ele lê um snapshot SQLite consistente (inclusive quando
a origem está em WAL), valida as sete tabelas da origem antes de escrever e usa
IDs da origem para que uma segunda execução não duplique dados.

## Mapeamento de stores

| Origem Therapify | Destino WhatsAYA | Regra |
| --- | --- | --- |
| `leads` | `personal_contacts.json`, `commercial_followups.db.lead_state` e `therapify_leads` | O telefone vira JID `@s.whatsapp.net`; status bruto é preservado, e o estágio é mapeado para o funil do painel. Flags existentes de bloqueio, relação manual e IA nunca são sobrescritas. |
| `messages` | `whatsapp_messages.db.messages` e `commercial_followups.db.therapify_message_map` | `wamid` é a chave; quando ausente, o ID da linha vira `therapify-<id>`. Tudo entra como histórico (`is_historical=1`) e não entra na fila do LLM. `context_wamid` é mantido. |
| `appointments` | `commercial_followups.db.appointments` | Preserva janela, tipo, status e ID da origem. Não inventa evento Google quando a origem não tem `event_id` ou Meet. |
| `purchases` | `commercial_followups.db.purchases` e `sales.json` | Registros importados entram como venda confirmada com ID determinístico `therapify-<id>`. O caminho de comprovante nunca é inventado. |
| `escalations` | `commercial_followups.db.escalations` | O histórico é sempre salvo. O outbox de handoff só é ativado com `--activate-escalations`, para não disparar alertas durante a preparação. |
| `app_settings` | `commercial_followups.db.app_settings` | Colisões com chaves operacionais recebem prefixo `therapify.`. Chaves que parecem segredo/token são armazenadas como `[REDACTED]`. |
| `reactivation_progress` | `commercial_followups.db.reactivation_progress` e contato | O maior estágio vence em reexecuções; o painel exibe o estado legado como somente leitura. |

A execução não habilita automação por padrão. `--enable-automation` é uma
decisão explícita de cutover e ainda respeita `paused` e estados terminais da
origem. O owner number informado em `--owner-number` (ou
`WHATSAPP_OWNER_NUMBER`) é excluído de leads, mensagens, vendas e escalonamentos.

## Uso seguro

Primeiro valide sem tocar nos stores:

```bash
cd /opt/whatsaya
python3 tools/therapify_migrate.py \
  --source-db /var/lib/therapify/therapify.db \
  --data-dir /opt/whatsaya/data \
  --owner-number "$WHATSAPP_OWNER_NUMBER" \
  --dry-run \
  --report /opt/whatsaya/data/migration-reports/therapify-dry-run.json
```

Depois da revisão humana do plano, execute em janela de manutenção. O comando
cria backup consistente dos dois bancos e dos JSONs que serão alterados:

```bash
python3 tools/therapify_migrate.py \
  --source-db /var/lib/therapify/therapify.db \
  --data-dir /opt/whatsaya/data \
  --owner-number "$WHATSAPP_OWNER_NUMBER" \
  --report /opt/whatsaya/data/migration-reports/therapify-apply.json
```

Somente depois de conferir as contagens e de testar a fila pode-se optar por
`--enable-automation`. Alertas de escalonamento também são uma decisão separada
(`--activate-escalations`). O importador nunca copia a sessão Baileys, tokens,
mídia ou arquivos `.env`.

## Garantias de operação

- **Schema:** `integrity_check`, tabelas e colunas exigidas são validados no
  snapshot. Banco incompleto, JSON inválido, conflito de IDs ou falha de
  transação encerra com erro não-zero.
- **WAL:** a origem é lida por `Connection.backup()`, não por `cp` do `.db`.
  Após a escrita, os stores canônicos passam por `integrity_check` e
  `wal_checkpoint(TRUNCATE)`; sidecars nunca são removidos manualmente.
- **Backup:** cada execução de escrita cria uma pasta timestampada em
  `data/.hermes/migration-backups/`. Preserve-a até o aceite do cutover.
- **Idempotência:** tabelas de extensão têm chaves de origem; mensagens usam
  índice único `(chat_id, message_id)`; contatos e vendas fazem merge sem
  substituir decisões manuais.
- **Histórico:** mensagens importadas são exclusivamente históricas e não são
  entregues ao LLM. O detalhe do lead no painel exibe a contagem desse histórico
  junto ao estado comercial, sem misturá-lo à fila viva. A primeira execução
  deixa automação desligada para impedir respostas acidentais.
- **Privacidade:** relatórios contêm apenas contagens e um fingerprint; fixtures
  de teste são sintéticas. Nunca versione bancos, sessões, conversas, mídia,
  credenciais ou dumps.

## Capacidades e configuração

As capacidades da Therapify que já têm owner no template são configuradas assim:

- **Mídia/prova social:** `data/media-manifest.json` e o contrato de envio nativo
  do bridge. Assets do cliente ficam somente em `/opt/whatsaya/data`.
- **Persona/prompt:** `SOUL_WHATSAPP.md`, `SOUL.md` e `support_rules.md`; o
  prompt proprietário da Therapify não é copiado para o template.
- **Calendário:** `calendar_booking.py` é o owner de disponibilidade, booking e
  token Google. Os appointments legados ficam em histórico até reconciliação.
  A tela Agenda do painel (ver seção abaixo) lê e ajusta essa mesma configuração.
- **Notificações/takeover:** o plugin persiste handoff em
  `handoff_notification_outbox.json`; o painel controla pausa, retomada e
  silêncio pelo bridge.
- **Debounce/horários:** flags `WHATSAPP_DEBOUNCE_*`, `runtime_settings.json`
  e `WHATSAPP_FOLLOWUP_SILENCE_MIN`; não há fork de código por cliente.
- **Reativação:** o motor de follow-up comercial do template continua dono de
  novos toques; o estágio Therapify importado é referência histórica até o
  aceite da política do cliente.

## Gaps priorizados

1. **P0 — Reconciliação de agenda:** appointments antigos não trazem `event_id`,
   timezone ou Meet. Destino proposto: uma revisão no painel que vincule cada
   linha a um evento Google existente. Dados necessários: calendário, fuso,
   evento e estado final. Aceite: nenhum evento duplicado e cada appointment
   aprovado aponta para um `current_bookings` válido. (Não confundir com a tela
   Agenda do painel, seção abaixo — ela já lê o calendário atual; este gap é só
   sobre os registros importados do Therapify.)
2. **P0 — Persona e catálogo:** a origem usa prompt, preços e mídia Therapify,
   enquanto o template usa arquivos por cliente. Destino: preencher
   `SOUL_WHATSAPP.md`, `support_rules.md`, catálogo e manifest aprovados. Aceite:
   simulação sintética cobre abertura, objeção, compra, agenda e handoff sem
   texto ou asset da Therapify no repositório.
3. **P1 — Configuração operacional:** `global_pause`, rollout e modelo são
   preservados em `app_settings`, mas não são aplicados automaticamente ao
   bridge. Destino: revisão no painel e gravação explícita em
   `bot_state.json`, `runtime_settings.json` ou env. Aceite: cada chave tem
   valor auditável e o bot permanece pausado durante a revisão.
4. **P1 — Reativação automática:** os estágios antigos (D+1/D+2/R$27) não são
   equivalentes às cadências genéricas do template. Destino: política de cliente
   com feature flag, janela e mensagens aprovadas. Aceite: opt-out, takeover,
   janela de horário e cancelamento terminal são testados antes do primeiro
   envio. A **reativação manual por etiqueta** já existe e é outra coisa: veja
   a seção abaixo.
5. **P2 — Escalonamentos antigos:** razões e estados são preservados; alertas
   não são disparados por padrão. Destino: revisar a fila e ativar o outbox em
   lote controlado. Aceite: nenhum alerta duplicado e cada item resolvido mantém
   o estado histórico.

## Painel Therapify: funil, KPIs e reativação por etiqueta

Tudo é configurado em `panel.config.json` (fora do clone, no volume):

```json
{ "pipeline": "therapify", "reactivation": { "label": "remarketing" } }
```

- **Funil:** o preset `therapify` mostra as seis etapas do painel legado (Novo,
  No funil, Sessão agendada, Comprou R$47, Comprou R$27, Perdido). O
  `FollowupEngine` continua com o domínio dele: mover um card grava a etapa
  escolhida em `pipeline_stage` no contato (telefone e `@lid` juntos) e chama
  `configure_lead` com a etapa mapeada e o flag terminal. Sem escolha explícita,
  o card cai pela `therapify_leads.status` importada e, por último, pela etapa
  do engine. `existing_patient` fica fora do board e aparece como contagem.
- **KPIs da Visão geral:** leads totais, sessões agendadas (`appointments`,
  potencial a R$247 só no payload), downsells confirmados (`purchases`, por
  produto) e escalonamentos abertos, com o recorte do período ao lado.
- **Reativação manual:** o bridge mantém `labels_state.json` (eventos
  `labels.edit`/`labels.association`) e expõe `GET /labels` e
  `GET /labels/chats?name=`. O painel prepara a lista na tabela
  `manual_reactivation` de `commercial_followups.db` (idempotente; `@lid` sem
  mapeamento, bloqueados e o dono ficam de fora), sugere texto por template
  determinístico (sem LLM, nunca inventa preço ou link), e marca enviado à mão.
  Nada é disparado pelo sistema. O primeiro envio manual para um contato
  preparado consome `first_manual_pending`: o plugin não registra takeover e
  libera o silêncio do bridge, então a resposta do lead volta ao fluxo normal.
  Um segundo envio manual é takeover de verdade.

## Agenda (Google Calendar) no painel

O painel de operação tem uma tela **Agenda** que lê e — dentro de um conjunto
fechado de campos — escreve a configuração do Google Calendar usada pelo
agendamento (`calendar_booking.py`). A fronteira é deliberadamente simples: o
painel fala com o Google por HTTP direto (`urllib`, stdlib), lendo o mesmo
`google_token.json` que o Hermes usa para agendar. Não há biblioteca Google no
container do painel (`python:3.12-slim`) nem API interna nova no Hermes — os
dois processos só compartilham dois arquivos no volume.

- **Config compartilhada:** `calendar_config.py`, na raiz do repositório,
  define a seção `"calendar"` de `panel.config.json` e é importado tanto pelo
  painel quanto pelo agente. A leitura tem cache por mtime/tamanho do arquivo:
  uma edição feita na tela Agenda vale no próximo turno do agente, sem restart
  do Hermes.
- **`availability_mode`** decide o que conta como vaga:
  - `explicit_slots` — usado pelo Rodrigo (Therapify): só o evento cujo título
    contém a palavra de vaga (`slot_keyword`, padrão "Livre") vira horário
    oferecível; um evento com a palavra de bloqueio (`block_keyword`, padrão
    "Bloqueada") é bloqueio explícito; qualquer outro evento é tratado como
    ocupado — no calendário dele o título costuma ser o nome do paciente, e o
    painel nunca exibe esse título.
  - `freebusy_gaps` — padrão do template genérico: vaga é qualquer intervalo
    livre dentro do expediente, via FreeBusy (o comportamento que
    `calendar_booking.py` já tinha antes desta feature).
  - A diferença de produto entre os dois clientes foi resolvida como config,
    não como um fork silencioso de comportamento: o mesmo `calendar_service.py`
    classifica eventos para os dois modos, e trocar de cliente é trocar
    `availability_mode` em `panel.config.json`.
- **Eventos AYA:** um evento é reconhecido como agendado pela AYA quando
  `extendedProperties.private` tem a chave `whatsayaBookingKey` (template) OU
  `therapifyBookingKey` (a chave que a versão em produção do
  `calendar_booking.py` já grava). Esses eventos aparecem na tela com badge
  "AYA", horário, "Agendado pela AYA" e, se existirem, os links de Meet e do
  Google Agenda.
- **O painel nunca expõe título, descrição ou convidados de um evento
  externo.** Eventos que não são da AYA só aparecem como "Livre", "Bloqueado"
  ou "Ocupado" — mesmo que o título real no Google seja o nome de um paciente.
- **OAuth pelo painel:** `GET /api/calendar/oauth/start` redireciona para o
  Google e `GET /api/calendar/oauth/callback` troca o código e salva o token.
  O redirect URI é `<WHATSAPP_PANEL_PUBLIC_URL>/api/calendar/oauth/callback` e
  **precisa estar cadastrado nas credenciais OAuth do Google Cloud Console**
  antes do primeiro uso — isso é trabalho humano, o painel não registra a URI
  sozinho. Sem `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` no ambiente do
  painel, o botão "Conectar Google Agenda" fica desabilitado com uma
  explicação; a conexão pode continuar sendo feita por terminal com
  `deploy/scripts/authorize_google.py`, que grava o token no mesmo formato e
  arquivo.
