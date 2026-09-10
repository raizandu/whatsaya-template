# Módulo de gestão do painel (substitui a Central de Operações do Notion)

Spec de 09/09/2026. Vale para o painel da instalação `instance` (a AYA da
Raizandu, que vende a WhatsAYA). Contrato das fases de implementação; o que não
está aqui não entra sem revisar este arquivo.

## 1. Por que

A Central de Operações no Notion (CRM, Clientes, Onboarding, Pós-venda,
Tickets, Follow-ups) tem estrutura rica e quase nenhum dado vivo: 27
oportunidades importadas e marcadas como legado, 1 cliente, 1 onboarding
(a própria AYA), 7 tickets, 0 follow-ups, 0 pós-venda. O plano gratuito não
sustenta a automação. O painel já é a fonte do funil (`lead_state`) e dos
follow-ups (`followup_jobs`); o que falta é o que acontece **depois** do lead
virar cliente, e o dinheiro em volta disso.

Decisões já tomadas com o dono:

- O destino é o painel da instância que está na `main`, não um produto novo.
- Notion fica **desligado por env**, código mantido. Sem `NOTION_API_KEY` +
  `NOTION_TICKETS_DB` (ticket) ou `NOTION_LEADS_DB` (lead) nada é chamado.
  Os dois caminhos já são fail-closed; basta remover as envs da VPS.
- Recebimentos: **cobrança prevista gerada da mensalidade + baixa manual.**
- Custo de IA por cliente: **lançamento mensal manual** agora; ingestão
  remota da VPS do cliente fica para depois, pelo mesmo canal dos tickets.
- Moeda: **tudo em BRL, valor efetivamente pago**, com moeda e valor original
  opcionais só para referência.
- Status do cliente enxugado para 7 etapas; onboarding é checklist, não etapa.

## 2. Escopo

Entra:

1. Cadastro de **clientes** com ciclo de vida e vínculo ao lead do funil.
2. **Onboarding** como checklist por cliente.
3. **Tickets** com histórico de mudança.
4. **Pós-venda** como pontos de contato do cliente.
5. **Financeiro**: cobranças previstas/recebidas, custos por cliente e
   categoria, MRR e margem por competência.
6. Importação única do que existe no Notion (1 cliente, 7 tickets).

Não entra (registrado para não voltar por acidente):

- Integração com gateway de pagamento. Exige URL pública com HTTPS que o
  painel de gestão não tem (9120 é HTTP puro).
- Ingestão remota de ticket/consumo vindo da VPS de cada cliente. Mesma razão.
  O auditor de cada cliente continua imprimindo o corpo do ticket no
  relatório diário; o operador abre à mão.
- Rateio automático da fatura do provider entre clientes.
- Reescrever o CRM do Notion no painel. O kanban já é o CRM; os campos de
  qualificação que o Notion tinha a mais (fit, interesse, motivo da perda)
  não entram agora.

## 3. Onde liga

O painel não conhece `is_whatsaya_instance` (isso é config do plugin). O
módulo liga por `panel.config.json`:

```json
"features": { "management": true }
```

Sem a flag, nenhuma rota `/api/management/*` responde (404) e as telas não
aparecem no menu. Instalação de cliente nunca vê isso.

Banco: `/opt/data/.hermes/management.db`, env `WHATSAPP_MANAGEMENT_DB`,
campo novo `management_db` em `panel_data.Paths` e `paths_from_env`.

## 4. Modelo de dados (`management_store.py`, raiz do repo)

Módulo **puro**, no molde de `reactivation_store.py`: `ensure_schema`,
`_read`/`_write` com WAL e `busy_timeout`, funções de leitura e escrita
recebendo o caminho do banco. Não importa o plugin nem o painel. Dinheiro é
sempre inteiro em centavos. Datas UTC ISO em `*_utc`; datas civis (vencimento,
competência) como texto `YYYY-MM-DD` / `YYYY-MM`.

### `clients`

| coluna | tipo | nota |
|---|---|---|
| id | INTEGER PK | |
| chat_id | TEXT UNIQUE NULL | lead de origem no funil, canônico (`@s.whatsapp.net`) |
| name | TEXT NOT NULL | pessoa de contato |
| company | TEXT | |
| segment | TEXT | |
| phone | TEXT | dígitos |
| email | TEXT | |
| status | TEXT NOT NULL | ver etapas |
| kind | TEXT | `atendimento` / `reativacao` / `teste` (o "Tipo" do Notion) |
| monthly_cents | INTEGER NOT NULL DEFAULT 0 | mensalidade contratada |
| setup_cents | INTEGER NOT NULL DEFAULT 0 | implementação, cobrada uma vez |
| billing_day | INTEGER | dia do vencimento, 1–28 |
| started_on | TEXT | data civil do contrato |
| activated_on | TEXT | data civil da ativação |
| churned_on | TEXT | |
| environment_url | TEXT | link do ambiente (painel do cliente) |
| notes | TEXT | |
| ssh_host, ssh_port, ssh_user | TEXT, INTEGER, TEXT | acesso à VPS do cliente, para o poller futuro de saúde e conexão |
| ssh_password | TEXT | **write-only**: nenhuma leitura do store devolve o valor (sai como `ssh_password_set`); só `get_ssh_credentials` lê. O arquivo do banco fica 0600. Vazio no update é "manter", `None` apaga. Preferir chave SSH quando o poller existir |
| created_utc, updated_utc | TEXT NOT NULL | |

Etapas de `status`, nesta ordem e sem outras:

`negotiation` → `awaiting_payment` → `onboarding` → `implementation` → `qa` →
`active` → `paused` | `cancelled`

`active` é a única que conta para MRR. `paused` e `cancelled` são terminais
para cobrança (não gera cobrança nova; as já geradas ficam).

### `client_events`

Histórico de mudança de status e observações livres: `id, client_id, kind
('status'|'note'), from_status, to_status, note, created_utc`. Toda mudança
de status grava um evento; é o que o Notion não guardava.

### `onboarding_steps`

`id, client_id, position, title, done_utc, pending_note, updated_utc`.
Criado com o checklist padrão ao mover o cliente para `onboarding`:

1. Entrada recebida
2. Pendências do cliente (envs, personas, catálogo)
3. VPS e domínio provisionados
4. Configuração e pareamento
5. QA interno
6. Validação do cliente
7. Ajustes
8. Pronto para ativar

Progresso é `done / total`; a tela mostra a primeira pendência aberta com a
`pending_note`. Passos podem ser adicionados e removidos; o padrão é só o
ponto de partida.

### `tickets` e `ticket_events`

`tickets`: `id, client_id NULL, title, description, kind, priority, origin,
status, due_on, resolution, opened_utc, resolved_utc, updated_utc`.

Vocabulário igual ao do Notion, em slug: `kind` em `incident|question|
request|improvement|billing|other`; `priority` em `critical|high|medium|
low`; `origin` em `whatsapp|internal|email|audit|other`; `status` em
`open|triage|in_progress|waiting_client|waiting_third_party|resolved|closed`.

`ticket_events`: `id, ticket_id, kind ('status'|'comment'), from_status,
to_status, note, created_utc`. Resolver exige `resolution` preenchida.

Ticket **sem** cliente é válido (ticket interno da AYA, como os 7 atuais).

### `touchpoints` (pós-venda)

`id, client_id, kind ('kickoff'|'checkin'|'usage_review'|'renewal'|
'churn_risk'|'other'), scheduled_on, done_on, health ('healthy'|
'attention'|'at_risk'), summary, next_action, next_contact_on, created_utc,
updated_utc`. A "saúde" do cliente é a do último touchpoint concluído.

### `charges` (cobranças)

`id, client_id, period ('YYYY-MM'), kind ('monthly'|'setup'|'adhoc'),
due_on, amount_cents, status ('expected'|'paid'|'cancelled'), paid_on,
paid_cents, note, created_utc, updated_utc`. `UNIQUE(client_id, period,
kind)` para `monthly` e `setup`; `adhoc` pode repetir.

Geração é **idempotente e preguiçosa**: `ensure_period(db, period)` cria a
cobrança `monthly` de cada cliente `active` (e a `setup` na competência de
`started_on`, se `setup_cents > 0`) que ainda não tem linha naquela
competência. Roda quando a tela Financeiro abre uma competência. Nada de cron.

Atraso não é status gravado: é `expected` com `due_on < hoje`, calculado na
leitura. Baixa manual grava `paid_on` e `paid_cents` (pode diferir do
`amount_cents`, desconto ou juros).

### `cost_plans` e `costs`

`cost_plans`: custo recorrente esperado. `id, client_id NULL, category,
monthly_cents, label, active_from ('YYYY-MM'), active_to NULL, updated_utc`.
`client_id NULL` é custo compartilhado da operação (domínio raiz, provider
comum) e entra na margem total, não na de um cliente.

`costs`: o lançamento real. `id, client_id NULL, period, category,
amount_cents, currency_original, amount_original, label, note, source
('plan'|'manual'), created_utc, updated_utc`.

`category` em `vps|ai|domain|tools|other`.

`ensure_period` também materializa os `cost_plans` ativos como `costs` com
`source='plan'` quando a competência ainda não tem lançamento daquele plano.
O operador ajusta o valor no fechamento (o de IA sempre, porque varia) e
o registro vira `source='manual'`.

### Agregados (leitura, `panel/data.py` → `management_*`)

- **MRR** na competência: soma de `monthly_cents` dos clientes `active`
  naquela data (se `activated_on <= último dia` e `churned_on` nulo ou
  posterior).
- **Recebido** = soma de `paid_cents` das cobranças `paid` com `paid_on` na
  competência. **Previsto** = soma de `amount_cents` das `expected`.
  **Atrasado** = `expected` vencidas.
- **Custos** = soma de `costs` na competência, por categoria e por cliente.
- **Margem por cliente** = recebido − custos do cliente. **Margem total** =
  recebido − todos os custos, inclusive compartilhados.

## 5. API

Tudo atrás do login existente e da flag `features.management`.

Leitura (`GET`):

| rota | devolve |
|---|---|
| `/api/management/clients` | lista com status, MRR individual, saúde, progresso de onboarding, tickets abertos |
| `/api/management/client/<id>` | ficha completa: eventos, onboarding, tickets, touchpoints, cobranças, custos |
| `/api/management/tickets?status=&client_id=` | lista |
| `/api/management/ticket/<id>` | ticket + eventos |
| `/api/management/finance?period=YYYY-MM` | chama `ensure_period`; devolve MRR, previsto, recebido, atrasado, custos por categoria, tabela por cliente com margem |

Escrita (`POST /api/actions/management/<ação>`), validação em
`panel/actions.py` e persistência no store:

| ação | corpo |
|---|---|
| `client_create` | campos de `clients`; opcional `chat_id` |
| `client_update` | `id` + campos editáveis |
| `client_status` | `id, status, note` — gera `client_events`; ao entrar em `onboarding` cria o checklist se não existir; ao entrar em `active` preenche `activated_on` se vazio |
| `client_from_lead` | `chat_id` — cria cliente a partir do lead (nome e telefone do contato, `monthly_cents` do `estimated_value_cents`), status `awaiting_payment`, e marca a etapa terminal do funil via `set_stage` |
| `onboarding_step` | `id, done` ou `pending_note`; `client_id, title` cria; `id, delete` remove |
| `ticket_create` / `ticket_update` / `ticket_status` / `ticket_comment` | |
| `touchpoint_create` / `touchpoint_update` | |
| `charge_pay` | `id, paid_on, paid_cents` |
| `charge_cancel` / `charge_adhoc` | |
| `cost_upsert` | `id` ou (`client_id, period, category`) + valor; `cost_delete` |
| `cost_plan_upsert` / `cost_plan_end` | |

Regras que o `actions.py` impõe e o store não conhece: transições de status
válidas (qualquer avanço; retorno só para `paused` → `active` e de qualquer
uma para `cancelled`), `resolution` obrigatória ao resolver ticket,
`billing_day` entre 1 e 28, centavos inteiros não negativos.

## 6. Interface

Grupo novo no menu, **Gestão**, visível só com a flag:

- **Clientes** (`views/clients.js`): lista com status, mensalidade, saúde,
  onboarding, tickets abertos. Clique abre a ficha com abas: Dados,
  Onboarding, Tickets, Pós-venda, Financeiro (cobranças e custos daquele
  cliente). Botão "Novo cliente".
- **Tickets** (`views/tickets.js`): lista com filtro por status e cliente,
  detalhe com linha do tempo e caixa de comentário. Botão "Novo ticket".
- **Financeiro** (`views/finance.js`): seletor de competência; cards MRR,
  previsto, recebido, atrasado, custos, margem; tabela por cliente com
  cobrança (baixa inline), custos por categoria (edição inline) e margem;
  bloco de custos compartilhados; gestão dos `cost_plans`.

No detalhe do lead (`views/lead.js`): botão **"Virou cliente"** quando o lead
ainda não tem cliente vinculado; quando tem, link para a ficha.

Nada de nova dependência: Preact + htm por CDN como hoje, estilo em
`theme.css`/arquivo novo `management.css`.

## 7. Importação única (`deploy/scripts/import_notion_management.py`)

Lê pela API do Notion com a chave que já está na VPS (acesso provado em
09/09/2026 para todas as bases): o cliente da data source `Clientes -
WhatsAYA` e os 7 tickets de `Tickets — Suporte`. Dry-run por padrão,
`--apply` grava. Mapeia os selects para os slugs acima; ticket sem relação
com cliente fica `client_id NULL`. Corpo de ticket e "Pendência Atual" do
cliente passam por `daily_audit.redact` antes de gravar: o card do cliente
tem credencial de produção em texto aberto (TKT-1) e a importação não pode
carregar isso para o novo banco.

Depois da importação: remover `NOTION_TICKETS_DB` do `.env` da VPS e
recriar o container. Chave pode ficar; sem base não há chamada.

## 8. Fases

Cada fase toca no máximo 5 arquivos, roda a verificação e espera aprovação.

| fase | arquivos | verificação |
|---|---|---|
| 1. Store | `management_store.py`, `tests/test_management_store.py` | `python3 -m unittest tests.test_management_store` |
| 2. Clientes | `panel/data.py`, `panel/actions.py`, `panel/server.py`, `tests/test_panel_management.py`, `panel/panel.config.example.json` | testes do painel + `python3 panel/server.py` local com flag |
| 3. Telas de clientes + "virou cliente" (feita 10/09) | `panel/static/app.js`, `views/clients.js`, `views/lead.js`, `management.css`, `index.html`, `tests/test_panel_ui.py` | suíte do painel + abrir no navegador |
| 5. Financeiro (feita 10/09, antes da 4) | `views/finance.js`, `app.js`, `management.css`, `tests/test_panel_ui.py` | idem; as rotas já haviam entrado na fase 2 |
| 4. Tela Tickets transversal (feita 10/09) | `views/tickets.js`, `app.js`, `management.css`, teste | fila por prioridade, filtros, detalhe com linha do tempo e edição |
| 6. Importação e corte do Notion | `deploy/scripts/import_notion_management.py`, teste, `CLAUDE.md`, `deploy/ONBOARDING.md` | dry-run na VPS, `--apply`, remover env, recriar |
| 7. Poller de saúde e conexão | usa `get_ssh_credentials` (ou o `/api/health` e `/api/status` do painel de cada cliente, que dispensam SSH) | tela Conexão/uso da carteira |

Fora do plano, para depois: canal de ingestão remota (ticket do auditor e
consumo de IA da VPS de cada cliente), que depende de HTTPS no painel de
gestão.
