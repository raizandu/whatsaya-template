# Ritmo, horário e reativação — Therapify

Spec fechado em sessão de grilling em 2026-09-10. Vocabulário em `CONTEXT.md`.
Alvo: WhatsAYA (plugin Python + bridge.js + painel). O bot legado Node/Baileys é só
referência de comportamento validado.

## 1. Horário

| Período | Regra |
|---|---|
| Dia útil, 9h–21h (America/Sao_Paulo) | Funil completo, com delays. |
| Noite útil, 21h–9h | Silêncio total. Lead vai para a fila da manhã. |
| Sábado, domingo, feriado, qualquer horário | Silêncio total. Nenhuma mensagem automática sai, inclusive a Fase 1; lead aguarda o próximo dia útil. |
| Retomada: próximo dia útil às 9h | Quem respondeu segue de onde parou; quem não respondeu entra na Fase 7. |

- O gate é checado **na hora de enviar**, não só ao enfileirar. Corta em 21h em ponto, sem
  tolerância: qualquer delay que atravesse 21h, caia em fim de semana ou feriado vira job de
  retomada no próximo dia útil às 9h e recebe o delay de novo. Não existe exceção para a Fase 1.
- Feriados: lista nacional fixa no profile da Therapify (já existe como set no código, hoje só
  informativo). Lista editável no painel fica para depois.
- O profile mantém `schedule.allow_new_lead_off_days=false` como sentinela explícito: Lead Novo
  nunca recebe abertura em fim de semana ou feriado.
- Notificações ao Rodrigo (paciente existente, pendência humana) saem sempre, na hora, sem
  delay. Disparos manuais do painel (reativação por etiqueta) respeitam horário e delays.
- Paciente e contato `legacy_history` nunca entram no funil; nada aqui muda isso.

## 2. Ritmo

Dois mecanismos, dois sinais:

**Debounce** (antes de chamar o modelo). Decidido pela **última bolha do bot** (regex, como a
Fase 3 já faz):

| Situação | Espera (trailing, reinicia a cada mensagem) | Teto |
|---|---|---|
| Última bolha foi pergunta de dor (Fase 1) ou pergunta diagnóstica (Fase 2) | 2 a 3 min | 5 min |
| Resto | 8 a 15 s | 5 min |

O bridge.js continua juntando fragmentos (8 s decaindo até 2 s) e mostrando "digitando".
Isso é técnico e independe do cliente. O debounce acima é do Python, lido do profile.

**Delay de resposta** (depois do modelo). Decidido pela **categoria** que o modelo devolve
num marcador cortado antes do envio (`[cat:...]`, mesmo mecanismo das tags de voz):

| Categoria | Delay randomizado |
|---|---|
| Lead Novo (nenhuma mensagem do bot ainda) — ignora categoria | 12 a 35 min |
| `intencao` ("quero marcar", "sim", "bora") | 5 a 75 s |
| `comum` (padrão; também depois do debounce de sintomas) | 15 s a 3,5 min |
| `objecao` ("tá caro", "vou pensar") | 30 s a 6 min |

- Marcador ausente ou inválido: `comum`.
- Mensagem nova do lead durante um delay de segundos: descarta a resposta planejada e
  reprocessa com o contexto completo.
- Lead Novo: vencimento fixo (não reinicia); a resposta na hora considera tudo que chegou.
- Esperas acima de 60 s (Lead Novo, retomada) são jobs em `followup_jobs`, vencimento
  explícito, tique do cron Hermes de 1 min. Esperas abaixo ficam em thread; um restart
  perde no máximo uma resposta de segundos.
- Fila da manhã: cada lead recebe seu delay de 12 a 35 min a partir das 9h, mais teto de 2
  retomadas por tique (configurável no profile).
- Lead Novo recebido fora de segunda a sexta, 9h–21h, fica na fila e não recebe a Fase 1;
  a primeira resposta só pode ser liberada no próximo dia útil, após a abertura das 9h e o
  delay configurado. Se o delay atravessar 21h, a resposta também fica para o próximo dia útil.
- Faixas ficam no `business_profile.json` da Therapify. Painel só exibe.

## 3. Reativação (Fase 7) e downsell

- A Fase 7 vira uma cadência `reactivation` **dentro** do `commercial_followups.py`
  (lease, idempotência, opt-out e painel reaproveitados). Cadência e textos vêm do profile.
- Para a Therapify as cadências genéricas (`silence`, `proposal`, `payment`, `post_sale`)
  ficam desligadas.
- Relógio em **tempo útil** (9h–21h, seg–sex, sem feriado):
  - D1 após 1 dia útil de silêncio: "Olá 👋" / "Desistiu do tratamento?"
  - D2 após mais 1 dia útil: bloco do método gravado (R$47)
  - Toque final ao fechar 3 dias úteis: protocolo (R$27) com link. Terminal.
- Textos literais do script (Fase 7 de `system_prompt_therapify_v1.md`), só primeiro nome
  interpolado. Não passa pelo modelo.
- Qualquer mensagem do lead cancela os jobs abertos (comportamento atual do motor).
- Downsell continua no prompt (escada R$247 → R$47 → R$27, nunca desconto na sessão).
  Novo: quando o modelo oferece o método gravado (Fase 5), grava
  `downsell_metodo_gravado_at` no contato; a Fase 7 lê isso e pula o D2 direto para o toque
  final. Sem notificação ao Rodrigo; ele vê no painel.
- "8 anos de experiência" já está em produção: o playbook que o bot segue é
  `/opt/whatsaya/data/support_rules.md` na VPS (cópia do `system_prompt_therapify_v1.md`
  do repo legado), fora do repo do WhatsAYA. Nada a adicionar; não mexer.

## 4. Rollout

Liga tudo de uma vez, dentro do horário comercial, com `daily_audit.py` conferido no dia
seguinte. Deploy de `whatsapp_manager.py`, `commercial_followups.py` e `bridge.js` por
three-way merge com a cópia da VPS e gate de conflito (CLAUDE.md do repo legado).

## Fora de escopo nesta entrega

- Lista de feriados editável no painel.
- Faixas de delay editáveis no painel.
- A implementação do gate de perguntas comerciais e da regra de calma clínica fica
  documentada no `system_prompt_therapify_v1.md` e no `business_profile.json`; este spec
  continua sendo a fonte apenas do relógio, dos delays e da reativação.

## Deploy (2026-09-10, ~12:30 BRT)

`/opt/whatsaya-staging/2026-09-10-ritmo-horario/apply.sh`, backup em
`/opt/whatsaya-staging/backup-20260910-172930-ritmo`. Além do código: `WHATSAPP_FOLLOWUP_ENABLED=true`
em `deploy/.env` (estava desligado) com recriação do hermes, e o cron do Hermes
`wa-silencio-followup` (schedule `"every 1m"`; `1m` sozinho é tarefa única e sumiu depois da primeira execução; script relativo a `~/.hermes/scripts/`; criado como uid 10000).
Sem o motor e o cron, os jobs não são retomados; o envio automático fora da janela continua
bloqueado (fail-closed). O cron precisa estar ativo para liberar os leads na manhã seguinte.
Log do tique: `/opt/whatsaya/data/.hermes/logs/whatsapp_followup_cron.log`.

## Revisão 2026-09-17 — Fase 1 imediata

Decisão do Rodrigo em 2026-09-17, após o lead …2604 esperar 7 min pela abertura na fila das 9h.
Substitui as linhas de "Lead Novo 12 a 35 min" e "fila da manhã com delay" acima.

- Lead Novo em horário comercial recebe a Fase 1 **na hora**: fast path determinístico
  (`_try_deterministic_contact_fast_path`, ramo Therapify) envia as 6 bolhas fixas sem passar
  pelo modelo, sem delay por categoria e sem job de retomada (`first_reply_min_s/max_s = 0`).
- Fora do horário a retomada vence exatamente às 9h e a fila sai inteira num tique
  (`resume_per_tick: 20`).
- Mensagem nova do lead durante as 6 bolhas **não** cancela a abertura
  (`allow_committed_stale=True`); o que o lead escreveu entra no turno seguinte do modelo.
  Um segundo turno do mesmo chat espera a abertura em voo antes de decidir se é a primeira
  saída (`_wait_other_turns_in_flight`, teto 45 s), para a Fase 1 não sair duas vezes.
- O passo `lead_novo_wait` saiu do `flow.steps` do painel.
- Deploy: `/opt/whatsaya-staging/2026-09-17-fase1-direta/apply.sh` (backup na mesma pasta).
