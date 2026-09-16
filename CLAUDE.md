# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Documentação e código deste projeto são em português (pt-BR). Mantenha esse idioma em comentários, logs e mensagens ao usuário.

## O que é este repositório

Plugin **`whatsapp-manager`** (v1.1) para o **Hermes Agent v2026** — não é uma aplicação autônoma. Não existe entrypoint local: nada de `npm start`. O código é instalado dentro do container do Hermes, que carrega `whatsapp_manager.py` e chama `register(ctx)` (final do arquivo) para registrar hooks. Deploy é SSH + `docker compose` direto na VPS — sem painel.

Licença **proprietária** (Titular: Anthony Fleuri, Raizandu). O projeto não é
open source: acesso ao código não autoriza execução, implantação, modificação,
redistribuição ou exploração comercial. Qualquer uso depende de autorização
escrita e eventual participação societária ou em resultados pertence a contrato
comercial separado; consulte [`LICENSE`](LICENSE).

## Comandos

```bash
npm install                                   # deps do bridge (package-lock.json é gitignorado de propósito)
npm test                                      # suíte completa: node --test tests/bridge.test.js && python3 -m unittest tests/plugin_test.py
python3 -m unittest tests/plugin_test.py      # só Python (312 testes, 49 classes)
node --test tests/bridge.test.js              # só o bridge (23 asserções; o processo
                                              # não encerra sozinho: importar bridge.js
                                              # sobe o Express na 3000)
python3 validate_dedup.py                     # validação de dedup (roda dentro do container)
python3 -m unittest tests.test_panel_data tests.test_panel_actions tests.test_contacts_store tests.test_users_store   # painel
python3 panel/server.py                       # painel local (exige HERMES_DASHBOARD_BASIC_AUTH_PASSWORD
                                              # forte; caminhos dos bancos via env, ver paths_from_env)
```

Rodar um único teste ou classe:

```bash
python3 -m unittest tests.plugin_test.TestSalesDetection
python3 -m unittest tests.plugin_test.TestSalesDetection.test_find_product_matches_partial_keyword
```

**Requer Python ≥ 3.12.** `whatsapp_manager.py` usa f-strings com backslash na parte de expressão (PEP 701); em 3.11 o arquivo nem compila.

**A suíte tem efeitos colaterais reais.** Importar `whatsapp_manager` dispara `register()`, que escreve em `/opt/data/.hermes/...` e faz requisições HTTP ao GitHub no boot. Fora do container Linux isso cria diretórios no host (em Windows, `C:\opt\data`). Os testes assumem paths POSIX — em Windows, asserts de path (`/opt/data/...` vs `\opt\data\...`) falham por diferença de separador, sem ser bug real. Rode a suíte no container ou em Linux.

Scripts de diagnóstico ficam em `deploy/scripts/` (`diagnose_bridge_dedup.py`, `diagnose_native_whatsapp_conflict.sh`, `capture_logs.sh`, `test_*.py` avulsos que não fazem parte de `npm test`).

## Arquitetura

### Divisão plugin × core (importante e contraintuitivo)

Desde o Hermes Agent v0.19 ("Quicksilver"), o **core** (`hermes_plugins.whatsapp_platform`) é dono do ciclo de vida do processo Node: spawn, pidfile com detecção de PID reciclado, restart em crash, e parsing das mensagens recebidas. Este plugin **não spawna mais o `bridge.js`** — `register()` apenas copia o arquivo para `/opt/data/.hermes/platforms/whatsapp/bridge/` para o core encontrar. Isso eliminou o container duplicado e o erro de desconexão `440 conflict / replaced`. Toda a regra de negócio fica nos hooks Python.

**Um único gateway consome o WhatsApp — o do perfil fica off.** O s6 do container sobe um gateway por perfil (`hermes -p whatsapp gateway run`), e cada um lê só o `.env` do próprio perfil. Por isso o compose grava `WHATSAPP_ENABLED=false` em `profiles/whatsapp/.env` (e `true` só no `.env` principal): com `true` nos dois, o gateway do perfil subia como segundo consumidor do mesmo bridge **sem o plugin carregado** — respondia contato bloqueado/silenciado por fora de todas as regras, e a duplicata só não aparecia porque o dedup do bridge engolia. O perfil `whatsapp` existe apenas como perfil de isolamento das conversas de cliente dentro do gateway principal. Como o `command:` do compose reescreve esses `.env` a cada boot do container, o estado se autocorrige em restart/recreate/reboot.

### Os hooks (`whatsapp_manager.py`, ~7.200 linhas)

| Hook | Linha | Responsabilidade |
|---|---|---|
| `pre_gateway_dispatch` | ~7233 | O maior. Roteia dono × cliente, executa comandos de controle, update de contato em linguagem natural, catálogo de produtos e registro de vendas |
| `pre_llm_call` | ~8626 | Detecta pergunta cross-session ("o que a Isabel falou sobre X?") e injeta histórico de `whatsapp_messages.db` + `state.db` no contexto |
| `pre_tool_call` | ~8957 | Firewall: aborta qualquer chamada de ferramenta vinda do perfil `whatsapp` (clientes) |
| `transform_llm_output` | ~9378 | Único caminho de saída para cliente: extrai o marcador `[[HANDOFF: motivo]]`, dispara o aviso real ao dono e agenda a entrega em bolhas. Devolve `"\n"` para o Hermes não reenviar o bloco |
| `post_llm_call` | ~9438 | Só sessão do dono: executa os `EXEC` de update de contato. Para cliente retorna `None` — o Hermes ignora o retorno deste hook no turno final |
| `register` | ~9604 | Instala `bridge.js` no volume, migra a sessão Baileys do path antigo, inicializa SOULs e `personal_contacts.json`, e sobe o watchdog de recepção |

### Handoff real e watchdog de recepção

Duas coisas que a IA **não** consegue fazer por conta própria, e que o plugin resolve fora do prompt:

- **Handoff.** A persona termina a resposta com `[[HANDOFF: motivo || RESUMO: uma frase factual]]`. `transform_llm_output` tira o marcador antes de a mensagem sair, e `_notify_owner_handoff` manda para o self-chat do dono um card com nome, número, motivo e um breve resumo da interação. Marcadores antigos continuam aceitos e recebem um fallback extrativo usando somente mensagens do lead. Há cooldown de 15 min por chat, e o cooldown é revertido se o envio falhar — melhor repetir o aviso do que engolir. Só depois de escrever o marcador a IA pode dizer que avisou; sem ele, "já encaminhei" é alucinação e o prompt proíbe.
- **Watchdog de recepção.** Toda mensagem de lead que chega ao fim de `pre_gateway_dispatch` entra em `_pending_inbound`; a entrega confirmada em `_deliver_contact_reply` remove. O que passar de `WHATSAPP_UNANSWERED_ALERT_S` (padrão 180s) vira `logger.error` e aviso ao dono. Existe porque no QA de 21/08 uma mensagem morreu em silêncio: o Codex estourou a cota (`429`) e o fallback OpenRouter estava sem crédito.

### Auditoria diária (`daily_audit.py` + `deploy/scripts/tick_whatsapp_audit.py`)

Módulo **puro**, no mesmo molde de `commercial_followups.py`: não envia mensagem, não
chama LLM e não importa o plugin. Lê linhas de log e linhas de banco, agrega o dia e
devolve texto. Quem agenda, chama o modelo e entrega ao dono é o `whatsapp_manager`.

Três coisas contraintuitivas:

- **A fonte do log é um arquivo, não `docker logs`.** O plugin escrevia só no stdout do
  container, e o cron do auditor roda *dentro* dele, onde `docker` não existe. Por isso
  `_attach_plugin_file_log()` espelha o logger em `logs/whatsapp_plugin.log` (rotativo).
  Isso também tira a retenção do log das mãos do daemon do Docker.
- **O placar "guarda salvou × modelo acertou" é calculado por código, nunca pelo modelo.**
  É a distinção que o relatório existe para mostrar: um dia em que a guarda determinística
  segurou cada turno não é um dia bom, e um auditor livre para resumir diria que foi.
  `classify_reply` marca o turno pela presença de uma frase conhecida da guarda —
  `FallbackCatalogDriftTest` é o que impede o catálogo de divergir das constantes do
  plugin em silêncio.
- **Nada de valor de credencial sai da máquina.** `redact()` corta documento, telefone,
  e-mail e chave, e preserva preço (que é a evidência do achado); `mask_chat()` deixa só
  os 4 últimos dígitos. A prova de que a credencial reproduzida era a real vai pela
  classificação do log (`digits=official:…` × `unknown:…`), não pelo valor.

O parser do log lê as gerações antigas do `[payment-gate]` (`methods=` antes de
`markets=`/`prices=`) de propósito: no dia de um deploy as duas convivem no mesmo arquivo.

Agendamento é o cron do próprio Hermes, como no follow-up:

```bash
hermes cron create "0 20 * * *" --name wa-auditoria-diaria \
  --script /opt/data/.hermes/scripts/tick_whatsapp_audit.py --no-agent
```

`register()` copia o tick para `/opt/data/.hermes/scripts/` no boot. Rodar
`tick_whatsapp_audit.py 2026-08-24` reprocessa um dia específico.

**Dois modos, e a escolha é sobre qual provider paga a conta.** No modo script
(`--no-agent`) o plugin chama o modelo direto por chave — só sabe Google/OpenAI/
OpenRouter, porque credencial do backend Codex é config do *gateway*, não do
plugin. No modo agente (`--material`, cron registrado **sem** `--no-agent`) o
tick não chama LLM nenhuma: imprime instruções + material no stdout e o agente
do Hermes produz o parecer, herdando a cadeia Codex→OpenRouter da assinatura.
A diretiva do dono é Codex primeiro, OpenRouter só em erro — logo, modo agente.
O custo aceito: o veredito não volta ao processo, então o portão sim/não da fase
2 não arma e a proposta vira nota para aplicar à mão.

Atenção ao `max_tokens`: sem teto explícito o OpenRouter **reserva** o máximo de
saída do modelo e cobra a reserva, não o uso — a primeira auditoria morreu com
`402 requested up to 65536 tokens, but can only afford 19788`.

**Propostas com portão (fase 2).** O auditor responde em JSON e cada achado vem
tipado; o tipo decide quem aplica, e os limites são de segurança, não de gosto:

| Tipo | Portão |
|---|---|
| `DADO` | Único aplicável por *sim/não* no chat do dono (`_pending_audit_action`, TTL 15 min, ao lado do fluxo de catálogo em `pre_gateway_dispatch`). Só nota de contato e campo de item de catálogo |
| `PROMPT` | Nunca automático — o texto iria direto ao prompt de produção sem suíte cobrindo, e a regra medida aqui é que instruir não funciona |
| `CODIGO` | Nunca automático. Vira corpo de ticket no relatório, no ciclo de 24/08 (achado com texto cru → teste vermelho com a frase literal → filtro determinístico → deploy) |

`pix_key` e `link` ficam **fora do aplicável mesmo sendo campo de catálogo**: são
destino de dinheiro e de tráfego, um "sim" distraído não é consentimento
suficiente para redirecionar pagamento, e o modelo deste sistema já reproduziu
credencial real por contaminação de provider. O mesmo vale para `summary`/`tone`/
`guidelines` do contato, que são do classificador. `_apply_audit_proposal`
**revalida o alvo no backend** — é a segunda camada da mesma decisão que mantém
`toolsets: []` no perfil de cliente: o agente não se automodifica por caminho
nenhum.

**Achados de código.** Proposta de `CODIGO` do auditor diário é formatada e
salva diretamente no relatório em disco (`reports/audit-YYYYMMDD.md`) com o corpo
do ticket pronto para revisão e abertura no painel de gestão (`management.db`).
O corpo passa por `redact` antes de sair para garantir que credenciais e dados
sensíveis nunca vazem no relatório.

### Painel de operação (`panel/`)

Serviço `painel` do compose: container `python:3.12-slim` só com stdlib que roda
`panel/server.py` a partir do **próprio clone do plugin no volume** — `git pull`
mais `docker restart whatsaya-painel` atualiza. Porta 9120, basic auth do
dashboard (recusa subir com senha fraca). Frontend Preact + htm por CDN, sem
build, em `panel/static/`; tema por variáveis CSS e `panel/panel.config.json`
por cliente.

- **`panel/data.py` só lê; `panel/actions.py` só escreve.** Leitura reaproveita
  `daily_audit` (atendimentos, handoffs, sem resposta por dia), o
  `commercial_followups.db` (etapa do lead e fila) e o `state.db` do Hermes
  (`session_model_usage`: tokens de entrada, saída, cache e reasoning por modelo,
  filtrado a `sessions.source='whatsapp'`). A leitura de custo continua disponível
  internamente em `/api/usage`, mas não aparece na interface do cliente. A tela
  **Assinatura** usa somente `panel.config.json.subscription` — nome, mensalidade,
  periodicidade e itens incluídos — e nunca reaproveita o custo do provider em
  `panel/pricing.json` como preço comercial.
- **O detalhe do lead é `GET /api/lead/<chat_id>`.** A leitura junta telefone e
  `@lid`, deduplica por `message_id`, exclui a importação histórica e atravessa
  todos os dias da conversa viva. `from_me` não decide autoria: os eventos
  `[human-send]` dos logs rotacionados são normalizados para a mesma identidade
  e passados por dia a `daily_audit.split_owner_manual`. Handoffs e follow-ups com hora
  confiável entram na timeline; etapa e bloqueio aparecem apenas como estado
  atual, pois suas fontes não guardam histórico de mudança. Áudio sem corpo é
  exibido como “Áudio recebido”. O backend mantém consumo agregado por sessão
  para diagnóstico interno, mas a tela do cliente não mostra tokens por contato.
- **Escrita em `personal_contacts.json` passa por `contacts_store.file_lock`**, um
  `flock` em `personal_contacts.json.lock` que o plugin também segura em
  `_write_personal_contacts_atomic` e `_merge_contact_record_atomic`. O lock de
  thread do plugin não atravessa processos; sem o flock o painel e o plugin se
  atropelariam no ler-mesclar-gravar.
- **Desbloquear pelo painel é em dois tempos.** O painel não alcança o objeto do
  gateway, então grava `blocked=false` + `session_reset_pending=true` com a IA
  desligada. `_complete_pending_panel_unblock` roda no `pre_gateway_dispatch`
  na próxima mensagem do contato, encerra as sessões antigas e só então liga a
  IA — mesma transação fail-closed do comando `desbloquear`.
- **O bridge ganhou `POST /bot-pause` e `POST /chat-silence`** (mesmo efeito de
  `stop_bot` e da mensagem manual do dono). O painel fala com ele em
  `http://hermes:3000` mandando `Host: 127.0.0.1`, porque o allowlist
  anti-DNS-rebinding do bridge só aceita loopback.
- **Configurações operacionais do WhatsApp são estado do bridge.** O painel lê e
  grava `GET/POST /runtime-settings`: recusa automática de ligações, processamento
  de grupos e espera inicial do debounce. O bridge valida, aplica em memória e
  persiste atomicamente em `runtime_settings.json` dentro da sessão, com modo 0600.
  O painel nunca edita o `.env`, que também contém segredos.
- **O painel envia mensagem só pela rota `POST /api/actions/reply`**
  (`panel/actions.py::reply`) — nunca chame `/send` cru do bridge de outro
  lugar do painel, isso furaria o fail-closed abaixo. Ordem: valida `chat_id`
  (recusa grupo `@g.us` e qualquer sufixo que não seja `@s.whatsapp.net`/`@lid`)
  e a mensagem (vazia ou acima de 4096 caracteres) antes de qualquer chamada;
  recusa contato bloqueado (`personal_contacts.json`) antes de chegar na
  ponte; chama `POST /send` do bridge com `automation: false` e timeout de
  30 s, exigindo `messageId` na resposta — sem ele nada é persistido. Só
  então: grava a mensagem em `whatsapp_messages.db`
  (`history_store.insert_records`, `from_me=1`, `sender_name` = nome do
  atendente), porque o bridge marca o próprio envio em `recentlySentIds` e
  nunca o grava sozinho; registra a autoria em `panel.db`
  (`outbound_messages`, `panel_store.py`, novo, `sent_by`/`sent_by_user`),
  porque `daily_audit.split_owner_manual` só distingue dono × AYA pelo log
  `[human-send]` do plugin — sem essa tabela própria, toda resposta do painel
  num dia sem envio da AYA naquele chat viraria "aya" na timeline
  (`lead_detail` sobrescreve `owner`/`sent_by` a partir dela depois de
  `_mark_conversation_owners`); marca `takeover` no motor de follow-up
  (`FollowupEngine.note_human_takeover`, best-effort, contato sem lead não
  quebra) se houver lead no funil; e silencia a IA por 10 min via
  `POST /chat-silence`. Falha do silêncio depois do envio não desfaz a
  mensagem — devolve `silenced: null` mais um aviso visível na UI, nunca
  esconde que a IA pode responder também.
- **Tela Contatos é mestre-detalhe (`#contacts/<chat_id>`)**: lista compacta
  à esquerda (avatar, prévia, hora, status da IA, marca de atenção), conversa
  com composer à direita usando o mesmo `conversation.js` que a tela Lead
  (`Conversation`/`Composer`, extraídos de `lead.js` nesta feature — nunca
  duplique a timeline entre as duas telas). Polling de 5 s só enquanto uma
  conversa está selecionada; a lista em si segue no intervalo próprio (30 s).
  Seleção fica no hash para o link ser compartilhável e sobreviver a um
  refresh. Abaixo de 1180px lista e conversa nunca dividem a tela: selecionar
  abre a conversa em tela cheia com botão voltar, e some o título da página e
  a faixa de métricas para a conversa ganhar a viewport inteira.
- **Usuários do painel (`panel_users.json`, `users_store.py`)**: papéis
  `admin` e `atendente`. O admin do env
  (`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`/`_PASSWORD`) continua existindo
  fora do arquivo, sempre admin, sem precisar de registro. Senha por
  `pbkdf2_hmac` sha256, 200k iterações; arquivo 0600 com o mesmo `flock`
  entre processos de `contacts_store.py`. A sessão carrega o `username` real
  de quem logou, e cada requisição reconsulta o arquivo — desativar um
  usuário derruba a sessão dele na hora, sem esperar expirar; trocar a senha
  não derruba a sessão corrente. `GET /api/me` devolve `{username, name,
  role}`. Papel `atendente` só chama `reply`, `stage`, `value`, `followup`,
  `silence`, `unsilence`, `meeting-outcome` (`ATTENDANT_ACTIONS` em
  `panel/server.py`) — tudo mais, `management/*` e `users/*` incluídos, cai
  num único ponto do dispatcher de `/api/actions/` e devolve 403. `GET
  /api/users`, `users/create`, `users/password` e `users/active` são só
  admin; nenhuma rota devolve o hash da senha, e ninguém pode se
  autodesativar.
- **Funil do kanban é preset declarado, não código.** `panel/data.py` só conhece o
  `default`; um funil de cliente vem inteiro do `panel.config.json` (`"pipeline"`
  como objeto: etapas, `engine_stage_map`, tabela `imported` de um sistema anterior
  com status excluídos, `commercial_metrics`). O formato está no
  `panel.config.example.json`. Nome de cliente nunca entra em `PIPELINES`.
- **O supervisor de pareamento (`panel/pairing.py`) nunca chama `apply` com
  credenciais já no disco.** `apply` reinicia o gateway. Ponte conectada sem
  pareamento nosso é a ponte do gateway (em `--pair-only` o bridge encerra 2 s
  depois de conectar): só registra e sai. Ponte fora do ar com `creds.json`
  existente: `gateway start` (no-op se o serviço está de pé, e o gateway sai
  com 78 quando não pareado); `gateway restart` só com a ponte morta há
  `restart_after` (10 min) e no máximo um a cada `reapply_backoff` (15 min).
  Em 09/09/2026 a versão anterior "reconciliou" um gateway saudável no
  primeiro boot sem estado e o derrubou; o gateway novo caiu no `npm install`
  do bridge porque o cache `/opt/data/.npm` tinha entradas de root — o compose
  agora faz `chown` do cache no boot. `docker exec hermes npm ...` como root
  recria o problema; rode como `hermes` (`su hermes -s /bin/sh -c ...`).

### Gestão da carteira (`management_store.py` + `panel/static/views/clients.js`, `finance.js`)

Central de Gestão e Operações na instalação da própria instância.
Spec e decisões em [`docs/GESTAO_SPEC.md`](docs/GESTAO_SPEC.md). Liga por
`"features": {"management": true}` no `panel.config.json` do volume; sem a
flag as rotas `/api/management/*` são 404 e o menu não mostra o grupo Gestão.
Instalação de cliente nunca liga. Banco `/opt/data/.hermes/management.db`
(`WHATSAPP_MANAGEMENT_DB`), modo 0600.

Três coisas contraintuitivas:

- **"Virou cliente" é ação explícita no detalhe do lead**, não inferência do
  kanban: cria o cliente em `awaiting_payment` e marca o lead como `won`
  terminal no motor de follow-up, que é como ele some das colunas.
- **Cobrança e custo previsto nascem ao abrir a competência** na tela
  Financeiro (`ensure_period`, idempotente), não por cron. Atraso é calculado
  na leitura. Plano de custo materializa `source='plan'`; ajustar vira `manual`
  e a reabertura do mês não recria.
- **A senha SSH do cliente é write-only.** Nenhuma rota devolve o valor (só
  `ssh_password_set`); só `get_ssh_credentials` lê, para o poller de saúde.
  Vazio no update mantém; `None` apaga.

### Reset de contato de teste (`deploy/scripts/wa_reset_contact.py`)

Depois de uma rodada de QA, zerar o histórico do número de teste. Dry-run por
padrão; `--apply` grava, com backup em `/opt/data/backups/` antes de qualquer
DELETE. **Rode no host com o container parado** — o SessionStore regrava
`sessions.json` no shutdown, então limpar com ele de pé faz a sessão ressuscitar.

```bash
docker stop hermes
WA_BASE=/opt/whatsaya/data python3 wa_reset_contact.py <numero> --apply
docker start hermes
```

Duas armadilhas que custaram caro e que o script cobre:

- **`@lid` é o mesmo contato com outros dígitos.** Resolver os `@lid` pelo
  `personal_contacts.json` **não basta**: em 24/08 nenhum dos dois números de
  teste estava cadastrado lá, a auto-detecção devolveu zero, e 39 das 74
  mensagens sobreviveriam sob `@lid` — com a AYA seguindo "lembrando" do lead
  depois do reset. A fonte confiável é o mapa `lidToPhone` do bridge
  (`GET /bot-status`); o cadastro é só fallback. Sem `@lid` conhecido o script
  avisa em vez de fingir que limpou.
- **`sessions.json` existe em mais de um lugar.** A sessão viva estava em
  `profiles/whatsapp/sessions/`, não no caminho documentado — a busca é
  recursiva.

### Dois perfis de isolamento

- **`default`** — dono, no SelfChat. Persona `SOUL.md`, histórico completo, todas as ferramentas.
- **`whatsapp`** — clientes. Persona `SOUL_WHATSAPP.md` + `support_rules.md`, `toolsets: []`, todas as 25 famílias de ferramentas desativadas, `skills.enabled: false`. `pre_tool_call` é a segunda camada, no backend.

### Pausa global × silêncio por chat (não confundir)

São mecanismos distintos, em camadas diferentes:

- **Pausa global** — `stop_bot` / `start_bot` (sinônimos `!pausar`, `!retomar`, `!parar`, `!iniciar`). Aplicada no Node (`bridge.js`), persistida em `bot_state.json` dentro de `SESSION_DIR`. Descarta na origem mensagens de qualquer um que não seja o dono. **Só funciona se enviada pelo dono no self-chat** — digitar na conversa de cliente não faz nada — ou por `POST /bot-pause {paused}` (painel). Estado consultável via `GET /bot-status` (`{ botPaused, uptime }`).
- **Silêncio de 10 min** (`WHATSAPP_SILENCE_DURATION_MIN`) — por chat individual. Dois gatilhos: o dono **lê** a conversa (detectado por `chats.update` quando não-lidas cai para `0`/`-1`), ou o dono **envia mensagem manual** (`fromMe: true` e o id não está em `recentlySentIds`). Mensagens começando com `!` ou comandos de controle não disparam o silêncio. Consultável via `GET /chat-status/:chatId`; `POST /chat-unsilence` limpa manualmente antes dos 10 min.
- **Bloqueio por contato** — `bloquear <contato>` / `desbloquear <contato>` no self-chat do dono. Grava `blocked: true` em `personal_contacts.json` (espelhado entre `@lid` e `@s.whatsapp.net`). O **bridge lê esse arquivo** e descarta a mensagem do contato bloqueado no ponto de entrada (`ownerBlockedContact`, cache por mtime): sem read receipt, sem download de mídia, sem histórico, sem "digitando…", sem fila pro agente. Isso existe porque o gate do plugin (`_ensure_contact_ai_access`) roda depois de o bridge já ter marcado como lida — o contato via "visualizado" de um bot que nunca respondia. O plugin continua como segunda camada: se o JSON estiver ilegível o bridge deixa passar e o plugin segura a IA (fail-closed lá). Registro corrompido na chave do contato bloqueia nas duas camadas.

`DESIGN.md` tem o fluxograma completo em Mermaid.

### Volume `/opt/data` — persistente × efêmero

Persistem: `.hermes/platforms/whatsapp/session/` (creds Baileys), `.hermes/whatsapp_messages.db`, `.hermes/state.db`, `personal_contacts.json`, `support_rules.md`, `SOUL*.md`.

**É wipeado em rebuild:** `.hermes/platforms/whatsapp/bridge/bridge.js`. Editar o `bridge.js` do volume é inútil — edite `bridge.js` na raiz do repo, que é o que `register()` copia para lá.

### Sync de contatos

`personal_contacts.json` **pode** ser versionado num repositório GitHub privado (`CONFIG_REPO` + `CONFIG_GITHUB_TOKEN`) — é opt-in e vem desligado. O GitHub público do produto (`raizandu/whatsaya-template`) contém somente código e templates genéricos; contato, venda e catálogo são dado de operação do cliente e ficam no volume. Sem os dois, o plugin nem tenta o push e não avisa o dono; a proteção nesse modo é `deploy/backup-whatsaya.sh` (snapshot local no cron, inclui a sessão do Baileys para não precisar reparear). O sync roda sempre em thread daemon via `_run_sync_in_background` — **nunca no boot**, só no intervalo periódico (`WHATSAPP_SYNC_INTERVAL_HOURS`) ou por comando no chat. Contatos são classificados por LLM em `Cliente | Amigo | AmigoProximo | Parente | Filho | Vendedor`; o campo `notes` entra no prompt como instrução obrigatória; `full_summary` acumula por sessão e é comprimido em `summary` quando fica longo. Campos auto-gerados (`tone`, `summary`, `guidelines`) não são sobrescritos por update manual.

## Armadilhas de arquivo duplicado

O mesmo arquivo existe em vários caminhos — edite o certo:

- `bridge.js` (raiz, 77 KB) é a **fonte da verdade**. `docs/bridge-artifacts/bridge.js` e `deploy/docs/bridge-artifacts/bridge.js` (63 KB) são artefatos defasados.
- `google_api.py` existe na raiz e em `deploy/scripts/google_api.py`.
- `skills/whatsapp-logs-diagnostics/SKILL.md` está duplicado em `deploy/skills/`.

## Deploy de alterações

O runbook completo está em `.gemini/skills/deploy-plugin/SKILL.md` (escrito para o Gemini CLI, mas o procedimento é agnóstico e roda por SSH, sem painel): commit e push no `main` → dentro do container, `git pull` no clone do plugin (`docker exec hermes sh -c 'cd /opt/data/.hermes/plugins/whatsapp-manager && git pull --ff-only origin main'`) → `docker restart hermes` (ou `docker compose restart`, do host) → conferir `grep "whatsapp-manager" /opt/data/.hermes/logs/hermes.log | tail -20` procurando por `bridge.js atualizado` → testar com `stop_bot` no WhatsApp. Alterações no plugin só carregam após o restart. `bot_state.json` sobrevive ao restart.

**Restart não é sempre suficiente.** `docker restart` reexecuta o `Cmd` já gravado no container — pega mudança de *código* (o plugin git-pulled acima), mas **não** pega mudança no próprio `docker-compose.yml`/`.env` (chave nova, provider novo, porta nova). Pra isso precisa `docker compose up -d` no host, que recria o container com o `Cmd`/env atualizados.

**`bridge.js` tem uma flakiness conhecida no boot:** o bootstrap do plugin (`shutil.copy2`) às vezes falha com `Permission denied` ao copiar `bridge.js` do clone pros caminhos que o Node realmente lê (`platforms/whatsapp/bridge/`, `scripts/whatsapp-bridge/`, `profiles/whatsapp/scripts/whatsapp-bridge/` — o processo em execução usa o último). Parece uma race transitória do bind mount, não reproduz sob demanda. Se depois de um restart `grep -c` de uma mudança recente em `bridge.js` der 0 nesses 3 caminhos, copie manualmente (`docker exec hermes cp <clone>/bridge.js <caminho>`) e reinicie de novo.

## Contrato visual do painel (sem slop)

O CSS e o JS de `panel/static/` consomem o token layer do `theme.css`, que replica o
`Aya Design System/colors_and_type.css`. Antes de desenhar ou alterar qualquer tela,
leia `Aya Design System/SKILL.md` (skill `aya-design`) e o `CHECKLIST.md` da mesma pasta.
Decisões fechadas em 15/09/2026 que não estão no DS de origem: no painel o botão
primário é **preto** (`--ink`), laranja fica para CTA de conexão/seleção e alerta;
pressed state é `translateY(1px)` sem spring; verde só para WhatsApp, conexão e sucesso.

O que o teste `tests/test_panel_ui.py::PanelMaterialityContractTest` bloqueia, e onde
bloqueia (pre-commit, hook PostToolUse do Claude Code e CI, todos rodando o mesmo módulo):

- Hex fora da paleta (4 cores de marca + branco + derivados fixados no token layer) e
  qualquer `rgb()`/`rgba()`/`hsl()` cru fora dos blocos `:root`/`.dark` do `theme.css`.
  Sombra tingida é `hsl(var(--shadow-tint) / a)`; fundo lavado é `--green-wash`,
  `--orange-wash`, `--mint`, `--orange-soft`.
- `box-shadow` com hex literal (use `--shadow-*`, `--inset-highlight`, `--focus-ring`).
- Duração ou easing literal em `transition`/`animation` (use `--duration-*` e
  `--ease-*`; só animação `infinite` de spinner/pulso tem ritmo próprio).
- Gradiente (o DS é chapado; a única exceção é `repeating-linear-gradient` de hachura),
  `!important` fora de `prefers-reduced-motion`, `z-index` ≥ 10 sem `--z-*`.
- `text-transform: uppercase` acima de 11px, `font-family` fora de `--font`/`--mono`,
  e `var(--x)` sem definição em lugar nenhum.

Hooks: `npm install` grava `core.hooksPath=.githooks` (script `prepare`); num clone
sem `npm install`, rode `git config core.hooksPath .githooks`. O hook do Claude Code
está em `.claude/settings.json` e roda `.githooks/claude-post-edit.sh` após cada edição.

**A suíte inteira roda por `discover`, num único processo.** Um teste que executa
`whatsapp_manager.py` de novo por `spec_from_file_location` e troca
`sys.modules["whatsapp_manager"]` quebra ~300 testes de `plugin_test.py` (os `patch`
acertam o módulo novo, o código roda no antigo) sem quebrar nada quando roda sozinho.
Foi assim que o CI ficou vermelho de 09/09 a 15/09/2026. Importe `whatsapp_manager`
normalmente nos testes.

## Grafo de conhecimento (graphify)

`graphify-out/` está commitado (grafo + cache AST + `GRAPH_REPORT.md`). `GEMINI.md` e `.agents/rules/graphify.md` mandam usar `graphify query "<pergunta>"` antes de grepar, `graphify path "<A>" "<B>"` para relações e `graphify explain "<conceito>"`; e `graphify update .` após mudar código. Verifique se o CLI `graphify` existe antes de depender disso — sem ele, `GRAPH_REPORT.md` ainda serve para visão de arquitetura.

## Ao replicar este kit para outro cliente

Runbook do operador: [`deploy/ONBOARDING.md`](deploy/ONBOARDING.md). Skills: `whatsaya-onboard`, `whatsaya-diagnose`.

Tudo o que muda por cliente é **variável de ambiente**, os templates em `deploy/SOUL*.md` e `support_rules.md`, ou a apresentação comercial em `panel/panel.config.json`. Não edite código para trocar de cliente — se você se pegar fazendo isso, é sinal de que falta parametrizar algo.

| Variável | Para que serve |
|---|---|
| `WHATSAPP_OWNER_NAME` | Nome do dono nos prompts, via `_owner_name()`. `_owner_name_norms()` e `_is_owner_name()` derivam dele as variações usadas para reconhecer as mensagens do dono no histórico |
| `WHATSAPP_OWNER_NUMBER` | Número sem `+`. Também lido pelo `bridge.js` |
| `WHATSAPP_CONFIG_SUBDIR` | Subpasta de `deploy/` com as personas da instância. `instance` é a instalação própria da WhatsAYA e a **única** em que a marca AYA aparece (`config.is_whatsaya_instance`); vazio ou `generic` é instalação de cliente e o plugin fala em nome da empresa dele |
| `WHATSAPP_BUSINESS_NAME` / `WHATSAPP_ASSISTANT_NAME` | Empresa representada e nome do atendimento automatizado numa instalação de cliente. Entram nas réplicas determinísticas, no prompt genérico e na reescrita de apresentação. Nome de cliente **nunca** vai para o código: `tools/build-public-template.sh` recusa publicar se encontrar |
| `WHATSAPP_PIX_KEY` | Chave Pix quando o item do catálogo não define a sua. **Sem default de propósito** — errar aqui manda o pagamento do cliente para a conta errada |
| `OPENROUTER_API_KEY` | Provider padrão. Deixe `GOOGLE_API_KEY` e `OPENAI_API_KEY` **vazias**: a cadeia é Google → OpenAI → OpenRouter e para na primeira chave preenchida |
| `WHATSAPP_*_MODEL` / `*_PROVIDER` | Slugs do OpenRouter (`vendor/modelo`). Texto usa `deepseek/deepseek-v4-flash`; `WHATSAPP_CLIENT_MEDIA_MODEL` é **só imagem** e precisa aceitar imagem (o DeepSeek é só texto). **Áudio não é modelo de LLM**: o bridge marca notas de voz como PTT e o STT local nativo do Hermes transcreve com Whisper |
| `WHATSAPP_HANDOFF_SILENCE_HOURS` | **Default `0` (dormente).** Acima de zero, o handoff confirmado também cala a IA naquele chat por esse prazo (`POST /chat-silence` com `reason: handoff`), para o atendimento do painel assumir. É prazo, não hold: instalação sem ninguém no painel recupera a IA sozinha. Só ligar com o painel com atendimento no ar (ADR 0001) |
| `WHATSAPP_AUDIT_*` | Auditoria diária do atendimento. `WHATSAPP_AUDIT_ENABLED` vem **desligada**; ligar manda o resumo do dia ao dono e envia o material a um provider externo. `WHATSAPP_AUDIT_MODEL`/`_PROVIDER` são **env próprias e nunca herdam `WHATSAPP_CLIENT_*`** — o provider do cliente roda no backend da conta ChatGPT do dono e já reproduziu credencial e preço que não estavam no prompt; auditor ali aprenderia da contaminação que existe para detectar. Sem a chave do provider escolhido não há chamada, e o relatório sai só com o placar determinístico |
| `CONFIG_REPO` + `CONFIG_GITHUB_TOKEN` | **Vazios por padrão.** Opt-in para versionar contatos e personas num repo privado. Preencher só um dos dois faz o dono receber "não consegui sincronizar" no WhatsApp a cada contato e venda — preencha os dois ou nenhum. Sem `user/repo`, o dono cai em `config.github_user` (`HERMES_SETUP_GITHUB_USER` → `DEV_GITHUB_USER` → `raizandu`). Para backup sem GitHub: `deploy/backup-whatsaya.sh` |
| `HERMES_SETUP_GITHUB_USER` / `HERMES_SETUP_GITHUB_REPO` / `HERMES_SETUP_GITHUB_REF` | Distribuição pública usada pelas VPSs, sem autenticação. Padrão: `raizandu` / `whatsaya-template` / `main` |
| `KEEP_LOCAL_PLUGIN` | `true` — o boot e o `_self_update_plugin_code` não fazem fetch/reset no volume |
| `WHATSAPP_GROUPS_ENABLED` | Default inicial desligado. Mensagem de `@g.us` é descartada antes de histórico, mídia, visto e fila. O painel pode mudar e persistir a opção em runtime; broadcast continua sempre descartado |
| `WHATSAPP_REJECT_CALLS` | Default inicial desligado. Quando ligado pelo ambiente ou painel, ofertas de ligação são recusadas pelo bridge assim que o Baileys emite o evento `call` |
| `WHATSAPP_PANEL_DB` | Caminho do `panel.db` (autoria das respostas enviadas pelo painel, tabela `outbound_messages`). Default `/opt/data/.hermes/panel.db`, já dentro do volume persistente — não precisa preencher |
| `WHATSAPP_PANEL_USERS` | Caminho do `panel_users.json` (usuários e papéis do painel). Default `/opt/data/panel_users.json`, também dentro do volume — não precisa preencher |
| `FISH_API_KEY` (+ `FISH_REFERENCE_ID`, `FISH_TTS_MODEL`, `FISH_TTS_VOLUME`) | Síntese das respostas em voz, somente TTS. A transcrição recebida é responsabilidade do STT nativo do Hermes. **Vazia = resposta em áudio desligada, tudo vai em texto** — o encanamento (`tts.provider=fishaudio` → `deploy/scripts/fish_tts.py`) é auto-instalado pelo compose no boot; só falta a chave. `FISH_REFERENCE_ID` escolhe a voz; modelo default `s2.1-pro-free` (campanha grátis até 31/08/2026 — `fish_model_campaign_notice.sh` avisa o dono de trocar). Pix, endereço, link, e-mail e afins nunca vão em áudio (regra `written_only` no `fish_tts.py`). Detalhes: `deploy/ONBOARDING.md` |

Fora as envs, só os arquivos de conteúdo: `deploy/SOUL.md`, `SOUL_WHATSAPP.md`, `SOUL_EMAIL.md` e `support_rules.md` são **templates com placeholders `{{...}}`**. Preencha antes de subir — placeholder não substituído vai literal para o cliente, e um `support_rules.md` com produto errado faz o bot inventar oferta que não existe.

URL do plugin: `config.plugin_git_url` / `config.plugin_raw_root`. Caminho oficial: [`deploy/ONBOARDING.md`](deploy/ONBOARDING.md).

## Como o código chega na VPS

O `command:` do `deploy/docker-compose.yml` clona a distribuição pública
`raizandu/whatsaya-template` (ou `HERMES_SETUP_GITHUB_*`) a cada boot, salvo
`KEEP_LOCAL_PLUGIN`. O repositório privado `raizandu/whatsaya` é a fonte interna;
publique um snapshot sanitizado no repositório de distribuição antes de atualizar
as VPSs. Restart basta para código; recreate é necessário para compose/env vars.

Duas decisões deliberadas nesse bloco:
- **É clone, não download de arquivos avulsos.** O `setup.sh` original baixava 9 arquivos individuais e não criava `.git`, o que fazia `_self_update_plugin_code()` cair no fallback de lista fixa — arquivos novos nunca chegavam.
- **O perfil de isolamento é escrito pelo compose, não pelo repositório clonado.** Se o clone falhar, o container sobe seguro em vez de liberar terminal e leitura de arquivos para quem manda mensagem.

## Pareamento e status

Após subir o container: `/whatsapp/qr` (tela HTML), `/whatsapp/qr?format=png`, `/whatsapp/status` (JSON). O bridge sobe na porta 3000; `adapter.py` (`WhatsAppPlatformAdapter`) conversa com ele por HTTP via `WHATSAPP_BRIDGE_URL`. Endpoints extras já implementados no bridge: `POST /send-poll`, `POST /send-location`.
