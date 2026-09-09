# Onboarding de um cliente (operador)

Este é o caminho oficial para replicar o kit. Você opera o servidor; o cliente só entrega conteúdo (persona, catálogo, número, Pix).

Para uma VPS vazia, comece pelo checklist curto e executável em
[`VPS_CHECKLIST.md`](VPS_CHECKLIST.md). Este documento continua sendo a
referência detalhada para decisões, exceções e diagnóstico.

Deploy é SSH + `docker compose` na VPS, sem painel — se você (ou seu agente de IA) tem acesso SSH ao host, não precisa de mais nada. Domínio é opcional (veja README.md).

Agente: use a skill `whatsaya-onboard` para executar este roteiro e `whatsaya-diagnose` quando o bot já está no ar e o comportamento está errado.

---

## 1. Intake — o cliente manda isto antes do `up`

| Campo | Env / arquivo | Formato |
|---|---|---|
| Nome como os clientes chamam | `WHATSAPP_OWNER_NAME` + `{{OWNER_FIRST_NAME}}` | texto |
| Nome completo | `{{OWNER_NAME}}` nos SOULs | texto |
| WhatsApp do dono | `WHATSAPP_OWNER_NUMBER` | internacional sem `+` (`5562…`) |
| Chave Pix | `WHATSAPP_PIX_KEY` | sem default — vazio é melhor que chave errada |
| Catálogo e preços | `support_rules.md` | só o que existe de verdade |
| Tom / o que nunca dizer | `SOUL_WHATSAPP.md` | preencher todo `{{…}}` |

Não suba com placeholder. `{{PIX_KEY}}` literal no chat e produto inventado vêm daqui.

Não copie CNPJ, preço ou nome de outro cliente para o código. Cliente novo = env + templates.

---

## 2. VPS

- Ubuntu 24, Docker Engine + plugin Compose v2.
- SSH por chave. Pasta típica: `/opt/whatsaya`.
- O compose usa bind mount (`/opt/whatsaya/data:/opt/data`), não volume Docker nomeado. **Nunca troque pra volume nomeado num host que já tem dados** — `docker compose up -d` cria um volume vazio em vez de montar os dados existentes, e o container sobe "limpo" (sessão do WhatsApp, contatos, vendas — tudo sumindo da vista do container, embora continue intacto em `/opt/whatsaya/data` no disco).
- IP basta. Domínio é opcional.
- Portas no host: `9119` (dashboard + `/whatsapp/qr`) e, se for usar a API, `8642`.

Use [`docker-compose.yml`](docker-compose.yml) — funciona com `docker compose up -d` puro, sem Swarm, sem painel. Um `.env` na mesma pasta preenche as variáveis `${VAR}` do compose.

No `.env` do host, mapeie as portas se o compose não publicar `HOST:CONTAINER`:

```bash
# se o arquivo só lista "9119", ajuste para "9119:9119" no serviço hermes
```

---

## 3. Ambiente

Lista completa e defaults: cabeçalho de [`docker-compose.yml`](docker-compose.yml). Tabela curta: [CLAUDE.md — Ao replicar](../CLAUDE.md#ao-replicar-este-kit-para-outro-cliente).

Mínimo para o bot responder:

- `API_SERVER_KEY` — `openssl rand -hex 32`
- `WHATSAPP_OWNER_NUMBER` / `WHATSAPP_OWNER_NAME`
- **Um** provider de modelo. A cadeia do plugin é Google → OpenAI → OpenRouter e para na primeira chave preenchida. Deixe as outras vazias.
  - OpenRouter: `OPENROUTER_API_KEY` (default da stack)
  - Gemini: `GOOGLE_API_KEY`
  - Codex OAuth: autentique no dashboard do Hermes (fluxo “Other” / Codex). Não misture com chave OpenAI preenchida se a intenção for Codex.
- `WHATSAPP_PIX_KEY` se houver venda no chat
- `HERMES_SETUP_GITHUB_USER` — ver passo 4

`CONFIG_REPO` + `CONFIG_GITHUB_TOKEN` vêm **vazios** e o normal é deixar assim: o GitHub do projeto é do produto (código e templates), não dos dados de operação do cliente. Se for preencher, preencha **os dois** — só um faz o dono receber "não consegui sincronizar" no WhatsApp a cada contato salvo e venda registrada.

Backup nesse modo é local: instale `deploy/backup-whatsaya.sh` no cron (instruções no cabeçalho do próprio arquivo). Ele inclui a sessão do Baileys, então restaurar não obriga a reparear o número.

### Campanhas CTWA e mercado do lead

Use `WHATSAPP_LEAD_CAMPAIGN_METADATA_JSON` para associar o ID ou nome nativo de uma campanha Click-to-WhatsApp ao mercado comercial correto. As chaves são comparadas exatamente com `smbClientCampaignId`, `smbServerCampaignId` ou `utm.utmCampaign`, nessa ordem de prioridade; texto do anúncio, palavras do nome da campanha e idioma da primeira mensagem nunca são usados para adivinhar o mercado.

Exemplo no `.env` para uma campanha dos EUA cujo atendimento começa em espanhol:

```dotenv
WHATSAPP_LEAD_CAMPAIGN_METADATA_JSON='{"120012345678900001":{"market_id":"US","language":"es","timezone":"America/New_York","origin":"meta_ads"}}'
```

Cada entrada aceita somente `market_id` (`BR` ou `US`), `language` (`pt`, `en` ou `es`), `timezone` e `origin` (strings de até 100 caracteres). O mercado governa moeda, oferta e pagamento; o idioma governa apenas a língua da conversa. Portanto, um lead da campanha dos EUA que escreve em espanhol continua no fluxo internacional em USD/Zelle. Campanhas desconhecidas não herdam metadados por semelhança de nome. Depois de alterar essa variável, rode `docker compose up -d` para recriar o container; `docker restart` não atualiza o ambiente.

Quando o WhatsApp entrega dados nativos do anúncio, o bridge armazena no cadastro do contato somente `origin` e o identificador/nome exato de `campaign`, mesmo que essa campanha ainda não exista no mapa acima. Isso preserva a atribuição para análise, relatórios ou classificação posterior sem confiar em texto livre do anúncio. Uma campanha sem mapeamento não define mercado automaticamente; até existir uma origem confiável ou o lead informar onde a empresa opera, o fluxo deve perguntar o país.

---

## 4. Plugin no volume

O `command:` do compose clona

```text
https://github.com/${HERMES_SETUP_GITHUB_USER:-raizandu}/${HERMES_SETUP_GITHUB_REPO:-whatsaya-template}
```

Defaults: usuário `raizandu`, repo `whatsaya-template`, referência `main`. O clone
é público e não exige credencial do GitHub na VPS. Para congelar uma versão,
defina `HERMES_SETUP_GITHUB_REF` com uma tag publicada.

Depois do primeiro `docker compose up -d`:

1. Confira se o código em `/opt/data/.hermes/plugins/whatsapp-manager` é **este** repo (`plugin.yaml` name `whatsapp-manager`, arquivos `whatsapp_manager.py` + `bridge.js` da raiz).
2. Se o clone falhou: copie este repo para esse diretório (incluindo `.git` se quiser puxar updates).
3. Correção de código = nova publicação no repositório de distribuição + restart.
   O boot faz `fetch` + `reset --hard` na referência configurada.
4. Patch temporário no volume: `KEEP_LOCAL_PLUGIN=true` no `.env` e recreate. Sem isso o próximo boot apaga o patch. O auto-update do plugin (`_self_update_plugin_code`) também respeita essa flag.
5. Habilite o plugin. `plugins.enabled: []` faz o cliente receber o Hermes padrão (`/sethome`), não a persona:

```bash
docker compose exec hermes hermes plugins enable whatsapp-manager
```

6. Se a sessão Baileys não gravar creds, o diretório costuma estar root-owned. Ajuste para o user do container (na prática, `10000`) e reinicie:

```bash
docker compose exec hermes ls -ld /opt/data/.hermes/platforms/whatsapp/session
# no host, no volume montado:
sudo chown -R 10000:10000 /opt/data/.hermes/platforms/whatsapp/session
```

---

## 5. Personas no volume

Esta composição usa `WHATSAPP_CONFIG_SUBDIR=generic` por padrão. No primeiro
boot, `SOUL.md`, `SOUL_WHATSAPP.md`, `SOUL_EMAIL.md` e `support_rules.md` vêm dos
templates genéricos em `deploy/`. Uma instalação privada pode apontar para outro
subdiretório explicitamente, mas esse conteúdo nunca é publicado no template.

O compose só copia esses arquivos se **ainda não existirem** em `/opt/data`. Em
uma instalação existente, atualizar o código não substitui a configuração
comercial ativa. Confirme `WHATSAPP_CONFIG_SUBDIR=generic` no `.env` e rode
`docker compose up -d`; um `docker restart` isolado não aplica variáveis novas.

```bash
grep -n '{{' /opt/data/SOUL.md /opt/data/SOUL_WHATSAPP.md /opt/data/SOUL_EMAIL.md /opt/data/support_rules.md
```

Zero matches. Depois: restart do container para o plugin reler.

`SOUL.md` = dono (self-chat, ferramentas). `SOUL_WHATSAPP.md` + `support_rules.md` = clientes.

---

## 6. Parear o WhatsApp

A tela **Channels → WhatsApp** do dashboard do Hermes inicia o primeiro
pareamento e gera o QR real. Enquanto essa sessão estiver aberta, a tela
**Conexão** do painel de operação também detecta a ponte e mostra o mesmo QR.
Para o primeiro acesso:

1. Suba com `WHATSAPP_ENABLED=false` (mantém o gateway estável enquanto plugin/personas terminam de ser conferidos).
2. Abra o dashboard HTTPS do Hermes, entre em **Channels → WhatsApp** e clique para conectar.
3. Escaneie o QR em **WhatsApp → Aparelhos conectados → Conectar um aparelho** no celular.
4. Confirme/aplique a conexão no dashboard. O Hermes salva a sessão e reinicia o gateway.
5. Confirme `WHATSAPP_ENABLED=true` no `.env` do deploy e recrie o serviço se o dashboard não tiver aplicado essa variável ao ambiente do container.

O fluxo por terminal continua disponível como recuperação:

```bash
docker compose -f deploy/docker-compose.yml exec hermes hermes whatsapp
```

Não publique o endpoint bruto do bridge. O dashboard do Hermes exige login e o
painel usa a mesma senha; o QR só aparece neles durante uma sessão de
pareamento ativa.

O card do dashboard (Bot / Self-chat) lê `WHATSAPP_MODE` do `.env` do Hermes (`/opt/data/.hermes/.env`). O número `15551234567` é só placeholder da UI — a allowlist real é `WHATSAPP_ALLOWED_USERS`. **Deixe Mode = Bot.** Self-chat nativo do Hermes atende só você mesmo e corta os clientes. Comando do dono no “mensagem para si” (`quais comandos`, `stop_bot`) já funciona em modo Bot, via plugin. O compose regrava isso no boot para não sumir no reset.

Modelo persistente: clientes/WhatsApp = `WHATSAPP_CLIENT_MODEL` (padrão `gpt-5.6-terra`, `WHATSAPP_CLIENT_REASONING_EFFORT` padrão `medium`). Uso interno no perfil default = `WHATSAPP_OWNER_MODEL` (padrão `gpt-5.6-luna`, `WHATSAPP_OWNER_REASONING_EFFORT` padrão `high` — não `max`, porque o `deepseek-v4-flash` do fallback nem sempre suporta esse nível). Sem isso o dashboard volta para o modelo que estiver no `config.yaml` antigo.

Se o dashboard não iniciar o primeiro QR, use o comando de recuperação acima.
Depois do scan, deixe apenas o bridge gerenciado pelo gateway e confirme
`connected` na tela **Conexão**.

Para manter uma página de QR independente do dashboard, instale o serviço versionado no host:

```bash
sudo apt-get install -y python3-qrcode
sudo install -m 0755 deploy/qr-server.py /opt/whatsaya/qr-server.py
sudo install -m 0644 deploy/whatsaya-qr.service /etc/systemd/system/whatsaya-qr.service
sudo systemctl daemon-reload
sudo systemctl enable --now whatsaya-qr.service
curl -fsS http://127.0.0.1/whatsapp/status
```

O serviço consulta o bridge vivo dentro do container; um `creds.json` antigo não é tratado como conexão ativa. Ele escuta só em `127.0.0.1`: publique a página por um proxy reverso autenticado, porque **quem abre o QR pareia o WhatsApp do cliente no próprio aparelho**.

Confira o bind depois de instalar, e de novo a cada atualização do host — um servidor
que recebeu o script antes desta trava continua ouvindo em `0.0.0.0` mesmo com a
unit nova, porque o `Environment` sozinho não corrige um script sem a variável:

```bash
ss -ltn | grep ':80 '                 # tem que mostrar 127.0.0.1:80, nunca 0.0.0.0:80
curl -sS -m 5 http://<ip-público>/whatsapp/status   # tem que falhar a conexão
```

Para parear sem expor a porta, use um túnel a partir da sua máquina:

```bash
ssh -L 8080:127.0.0.1:80 <host>       # e abra http://127.0.0.1:8080/whatsapp/qr
```

Não pareie o mesmo número em dois bridges ao mesmo tempo — Baileys cai com `440 conflict / replaced`.

### Follow-up transacional

O plugin copia `tick_whatsapp_followups.py` para `/opt/data/.hermes/scripts` em todo boot. Crie o ticker uma única vez e confirme que não há job duplicado:

```bash
docker compose exec hermes hermes cron list
docker compose exec hermes hermes cron create 1m \
  --name wa-silencio-followup \
  --script /opt/data/.hermes/scripts/tick_whatsapp_followups.py \
  --no-agent
```

O padrão do template é `WHATSAPP_FOLLOWUP_SILENCE_MIN=5`. O ticker só envia para lead comercial explicitamente habilitado, revalida takeover/opt-out antes do envio e não usa LLM. Contatos pessoais ou com escopo comercial não confirmado ficam pausados e têm follow-up cancelado.

### Publicar com HTTPS e login

O painel (9120), o dashboard (9119) e a página de QR (80) não devem ficar abertos
na internet: os dois primeiros só têm basic auth, que em HTTP puro trafega em
texto claro, e o terceiro permite parear o WhatsApp do cliente. O caminho
recomendado é Cloudflare Tunnel mais Access, que publica os três por HTTPS sem
abrir porta nenhuma: [`deploy/CLOUDFLARE.md`](CLOUDFLARE.md).

### O compose do repositório é a fonte da verdade

Todo valor que muda por cliente é variável no `.env`; o `deploy/docker-compose.yml`
não deve ser editado no servidor. Se você se pegar editando o compose de um host,
falta parametrizar algo — inclusive a versão do Hermes, que é `HERMES_IMAGE_TAG`
(padrão fixado no arquivo). Deixar `latest` significa subir versão nova sem aviso
no próximo pull.

Antes de copiar o compose para um servidor que já roda, diffe primeiro:

```bash
diff /opt/whatsaya/docker-compose.yml deploy/docker-compose.yml
```

Diferença que não seja variável de ambiente ou apresentação comercial em
`panel/panel.config.json` é decisão de produto (ferramentas liberadas para o
cliente, por exemplo), não detalhe de deploy.

### Painel de operação (porta 9120)

Serviço `painel` do compose: container Python só com stdlib que roda o código do
próprio clone do plugin (`panel/server.py`), pelo mesmo bind mount. Mostra status
e QR, bloqueados, funil por etapa, fila de follow-ups, atendimentos resolvidos
pela IA, tempo economizado e assinatura comercial; e escreve: bloquear/desbloquear,
mover etapa, pausar/cancelar follow-up, pausa global da IA e configurações do
WhatsApp (ligações, grupos e agrupamento de mensagens).

```bash
docker compose up -d painel                       # cria só o painel; não mexe no hermes
curl -u "$HERMES_DASHBOARD_BASIC_AUTH_USERNAME:$HERMES_DASHBOARD_BASIC_AUTH_PASSWORD" \
  http://127.0.0.1:9120/api/status
```

- **Login** é o mesmo basic auth do dashboard (`HERMES_DASHBOARD_BASIC_AUTH_*`).
  Sem senha, ou com `admin123`, o container sobe e sai com erro na hora — de
  propósito. Ponha o proxy HTTPS na frente da 9120, como na 9119.
- **A interface do cliente não mostra custo de tokens.** A tela Assinatura vem
  de `panel/panel.config.json`, conforme o exemplo versionado: nome do plano,
  mensalidade comercial, periodicidade e itens incluídos. Sem `price_brl`, ela
  mostra “Consulte sua proposta”. O custo técnico continua disponível apenas
  para diagnóstico interno em `/api/usage`, calculado pelo `state.db` e por
  `panel/pricing.json`. Para refrescar essa tabela interna:

  ```bash
  python3 deploy/scripts/update_pricing.py --dry-run   # confira antes
  python3 deploy/scripts/update_pricing.py             # grava panel/pricing.json
  ```

  Ele lê o catálogo público da OpenRouter e, sem `--model`, descobre sozinho os
  modelos usados no `state.db`. Modelo de assinatura é precificado pelo
  equivalente `openai/<nome>`; o campo `source` no arquivo registra de onde veio
  cada preço. Ajuste `usd_brl` à mão. O painel nunca chama a rede: preço é
  arquivo, para o número não mudar entre dois carregamentos.
- **Tempo economizado** = atendimentos resolvidos pela IA ×
  `WHATSAPP_PANEL_MINUTES_PER_RESOLVED` (padrão 6), valorado por
  `WHATSAPP_PANEL_HOURLY_RATE_BRL` (padrão 38).
- **Marca, cores e assinatura por cliente**: o bootstrap copia
  `panel/panel.config.example.json` para `/opt/whatsaya/data/panel.config.json`.
  Esse arquivo fica no volume persistente e não é apagado por atualização do
  plugin. Não edite componente para trocar de cliente ou definir mensalidade.
- **Estado operacional do bridge** (pausa global, silêncio por chat, configurações
  do WhatsApp e catálogo de etiquetas) fica em `platforms/whatsapp/state/`, ao lado
  da sessão, não dentro dela: o logout apaga a pasta da sessão inteira e não pode
  levar a pausa junto. Arquivos antigos são migrados no primeiro boot. Depois de um
  logout, confira a pausa em Conexão mesmo assim.
- **Funil por cliente**: `"pipeline": "therapify"` em `panel.config.json` troca
  as cinco etapas genéricas pelas seis etapas comerciais da Therapify e liga os
  KPIs de sessões, downsells e escalonamentos na Visão geral; sem a chave, o
  painel continua com o funil padrão. Detalhes em `docs/THERAPIFY_MIGRATION.md`.
- **Reativação por etiqueta**: a tela Reativação lê a etiqueta do WhatsApp
  Business definida em `"reactivation": {"label": "remarketing"}`; o bridge
  precisa estar no ar para “Preparar lista da etiqueta”. Nada é enviado pelo
  painel.
- **Agenda (Google Calendar)**: variáveis novas no `deploy/.env`:
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `WHATSAPP_PANEL_PUBLIC_URL` e
  `WHATSAPP_CALENDAR_TOKEN_PATH` (default `/opt/data/.hermes/google_token.json`,
  o mesmo arquivo que o Hermes já usa para agendar). No Google Cloud Console,
  cadastre nas credenciais OAuth o redirect URI
  `<WHATSAPP_PANEL_PUBLIC_URL>/api/calendar/oauth/callback` — sem isso o
  Google recusa a conexão. Caminho preferido: botão "Conectar Google Agenda"
  na tela Agenda do painel, sem precisar de terminal. Fallback por SSH:
  `deploy/scripts/authorize_google.py` — o escopo padrão agora é só Calendar;
  use `GOOGLE_OAUTH_SCOPES=gmail` para o preset com os três escopos de Gmail
  somados ao Calendar (o que antes era o comportamento padrão do script).
  Horário de expediente, duração da sessão, antecedência mínima, dias de
  busca e o modo de vagas (`explicit_slots` para calendários com eventos
  "Livre"/"Bloqueada" marcados à mão, como o do Rodrigo; `freebusy_gaps` para
  o padrão genérico) se ajustam pelo card "Configurações da agenda" na
  própria tela, não pelo `.env`. As variáveis legadas
  `WHATSAPP_CALENDAR_ID`/`WHATSAPP_CALENDAR_TZ`/`WHATSAPP_CALENDAR_MIN_LEAD_MINUTES`
  continuam funcionando como fallback só enquanto a chave `calendar` não
  existir em `panel.config.json`; depois da primeira gravação pelo painel,
  elas deixam de ser lidas. Detalhes em
  [`../docs/THERAPIFY_MIGRATION.md`](../docs/THERAPIFY_MIGRATION.md#agenda-google-calendar-no-painel).
- **Desbloquear pelo painel não liga a IA na hora**: grava a intenção e o plugin
  encerra as sessões antigas do contato na próxima mensagem dele, antes de
  liberar — a mesma transação fail-closed do comando `desbloquear`.
- O navegador do dono carrega Preact e htm do jsdelivr (não há build). Em rede
  fechada, copie as três libs para `panel/static/vendor/` e aponte o import map
  de `index.html` para lá.

---

## 7. Fumaça (obrigatório)

Não declare o cliente no ar sem isto:

| Teste | Esperado |
|---|---|
| Mensagem de um número que **não** é o dono | Tom de `SOUL_WHATSAPP` + catálogo. **Não** é onboarding do Hermes (`/sethome`, “set your home”) |
| `{{` em qualquer resposta | Falhou o passo 5 |
| Dono no self-chat: `quais comandos` | Ajuda do plugin (`stop_bot`, `start_bot`, …) |
| Duas ideias na resposta | Duas bolhas, se o `main` já tiver o hook `transform_llm_output` (PR de bolhas). Um bloco só + SOUL pedindo `\n\n` = hook ausente ou plugin velho |
| Texto com `[confident]` / `[empathetic]` / `[happy]` | Cliente **não** vê a tag. Se vazar, o strip do `_human_send` / adapter não está no plugin que está rodando |

Sessão de teste suja o histórico. Apague a sessão Hermes daquele JID se for repetir o teste do zero.

Antes de encaminhar a versão para QA Final, execute o runbook
[`AYA_V1_DEFINITION_OF_DONE.md`](AYA_V1_DEFINITION_OF_DONE.md). `npm test` sozinho
valida os guards, mas não substitui os cenários de staging que dependem de modelo,
memória, sessão e entrega real.

### Reset de um contato de teste

O reset é dry-run por padrão. Confira os aliases `@lid` encontrados e só aplique com o
container parado, para o SessionStore não regravar a sessão durante o shutdown:

```bash
docker stop hermes
WA_BASE=/opt/whatsaya/data python3 deploy/scripts/wa_reset_contact.py NUMERO_DE_TESTE
WA_BASE=/opt/whatsaya/data python3 deploy/scripts/wa_reset_contact.py NUMERO_DE_TESTE --apply
docker start hermes
```

O script cria backup antes dos `DELETE`. Nunca use esse procedimento em contato real ou
sem conferir o número resolvido no dry-run.

**Riscos conhecidos:**
- Transcrição de áudio **não passa por LLM nem pelo Fish**. O bridge reconhece `audioMessage.ptt=true` como nota de voz e entrega `mediaType=ptt`; então o STT local nativo do Hermes transcreve com Whisper antes do turno chegar ao agente. `WHATSAPP_CLIENT_MEDIA_MODEL` cuida só de imagem. Se o agente receber `[audio received]` ou um anexo `.ogg`, confirme primeiro que o bridge preservou o sinalizador PTT.
- `git: dubious ownership` no boot é corrigido automaticamente pelo próprio `command:` do compose (`git config --global --add safe.directory`) — não é erro.
- `Cannot find package '@whiskeysockets/baileys'` ao rodar os testes locais significa que as dependências ainda não foram instaladas — rode `npm ci` antes de `npm test`.

---

## 8. Fullsync e triagem inicial

Depois do primeiro pareamento e de `/whatsapp/status` ficar `connected`, rode o pipeline em [`WHATSAPP_HISTORY_TRIAGE.md`](WHATSAPP_HISTORY_TRIAGE.md). Mensagens históricas vão para o SQLite e **não entram na fila do LLM**.

```bash
python3 deploy/scripts/whatsapp_history_triage.py \
  --config deploy/scripts/whatsapp_history_triage.yaml run
```

Isso espera o lote estabilizar e grava snapshot, CSV e o prompt da skill `whatsapp-client-triage`. Depois da classificação:

```bash
python3 deploy/scripts/whatsapp_history_triage.py \
  --config deploy/scripts/whatsapp_history_triage.yaml report \
  --snapshot /opt/data/.hermes/workspace/whatsapp_fullsync_YYYY-MM-DD.json \
  --classification /opt/data/.hermes/workspace/whatsapp_classification.json
```

O Markdown de revisão sai em `/opt/data/.hermes/workspace/whatsapp_triagem_revisao_cliente_YYYY-MM-DD.md`. O dono valida antes de qualquer flag ir para `personal_contacts.json`. Envio ao self-chat é explícito (`send`) e exige `--chat-id` do dono.

Não envie o snapshot bruto. Não declare o onboarding completo sem conferir `historical > 0` quando o número tem histórico.

---

## 9. Skills do Hermes (dono)

O perfil `whatsapp` (cliente) já sobe com `skills.enabled: false`. O perfil do dono herda o catálogo bundled — dezenas de skills de studio, MLOps, GitHub e desktop. O `command:` do compose grava `skills.disabled` no `config.yaml` a cada boot.

Ficam ligadas só as úteis nesta operação: `session-librarian`, OCR/PDF/DOCX, Google Workspace / e-mail, Notion (onboarding de clientes), mapas, atas, `plan`, `hermes-agent`, `grounded-citations`.

Para ver: `docker compose exec hermes hermes skills list`.

WhatsApp não recebe status interno do gateway: o compose grava `display.busy_ack_enabled: false`, `busy_input_mode: queue` e desliga heartbeat/clarify. O cliente não deve ver `⚡ Interrupting`, `⏳ Working` nem `iteration N/60`. PDF/proposta sai com subagentes em paralelo, sem a ferramenta `clarify`.

Áudio: o Hermes 0.20+ transcreve notas de voz com Whisper local. O compose grava `stt.provider: local`, `stt.language: pt` e `HERMES_LOCAL_STT_LANGUAGE=pt`. O plugin da AYA não consome nem apaga o arquivo antes dessa etapa. `stt.echo_transcripts: false` mantém a transcrição só no contexto do agente; o cliente não vê a bolha `🎙️ "..."`.

Mensagens aceitas pelo atendimento são marcadas como lidas antes do debounce e continuam mostrando `composing` durante a espera. `WHATSAPP_SEND_READ_RECEIPTS=false` desliga somente o recibo de leitura. O bridge é o único dono dessa janela: o boot grava `platforms.whatsapp.text_batch_delay_seconds: 0` e `text_batch_split_delay_seconds: 0` para o adapter nativo do Hermes não acrescentar outra espera.

Voz de resposta: Fish Audio, modelo `s2.1-pro-free` (campanha grátis até 31/08/2026; no dia 30 o cron avisa o dono para trocar para `s2.1-pro`). Gere a chave em https://fish.audio/app/api-keys/ e coloque `FISH_API_KEY` no `.env`. Opcional: `FISH_REFERENCE_ID`, `FISH_TTS_MODEL` e `FISH_TTS_VOLUME` (padrão `4`). Resposta falável vai em nota de voz **apenas quando o lead mandou áudio** (gate de modalidade: quem escreve recebe texto). `WHATSAPP_AUTO_TTS=false` desliga a voz de vez. Dados de pagamento, endereço, link, e-mail, código e intro do tipo “vou te enviar um audio” ficam **texto**. Sem chave, o texto continua indo. Tags `[happy]` / `[confident]` / `[empathetic]` / `[warm and friendly]` são só para o Fish: o plugin corta no `_human_send` e o adapter corta no `send`, mesmo se o `fish_tts.py` não carregar. Se a tag aparecer no chat, o volume está com plugin velho. `[número omitido]` não é tag de voz e fica. Preço no áudio vai por extenso na moeda do mercado. O primeiro fragmento de texto espera até 8s para juntar mensagens rápidas do mesmo lead (`WHATSAPP_DEBOUNCE_INITIAL_MS=8000`); fragmentos seguintes reduzem progressivamente essa espera. O bridge envia `composing` assim que a espera começa e renova o indicador a cada 5s (`WHATSAPP_DEBOUNCE_TYPING_REFRESH_MS=5000`) até consolidar o turno.

---

## 10. Depois do ar

- Atualizar plugin: push neste repo → `docker restart hermes` (ou `docker compose restart`) já basta — o boot faz `fetch` + `reset --hard` do plugin. Confira no log `bridge.js atualizado` / `whatsapp-manager`.
- Mudou env var ou o próprio `docker-compose.yml`? `docker restart` **não** pega — precisa `docker compose up -d` (recria o container com o `Cmd`/env novos).
- Mudar só persona/catálogo: edite `/opt/data/SOUL_WHATSAPP.md` e `support_rules.md` (ou o `CONFIG_REPO`) e reinicie.
- `stop_bot` / `start_bot` só valem no self-chat do dono.
- Cliente seguinte: volte ao passo 1. Código igual; mudam env + templates.

---

Aviso histórico: este kit não é o fork `leoalvesia/whatsappkit` (Comunidade Empreendedor Serial, Portainer, Gemini, `setup.sh` via curl). Não faça fork de `whatsappkit` nem rode aquele `setup.sh` apontando pra este projeto — não é o mesmo fluxo.
