# Fase 2 — integração do ritmo no pipeline de resposta

Complementa `2026-09-10-ritmo-e-horario-therapify.md` com o *como*. Fatos levantados no
código em 2026-09-10 que amarram o desenho:

- O modelo só roda quando o Hermes consome um evento de `GET /messages` do bridge e chama
  os hooks do plugin (`pre_gateway_dispatch` → LLM → `transform_llm_output`). O plugin não
  tem como iniciar um turno sozinho.
- `pre_gateway_dispatch` só sabe `return None` (segue para o LLM) ou
  `{"action": "skip"}`. Para trocar o texto que o modelo vê, muta-se `event.text/body`.
- Toda mensagem recebida já é gravada em `whatsapp_messages.db` pelo bridge, antes de o
  plugin ver o evento. Pular o turno não perde a mensagem.
- Campos extras do evento do bridge (`leadMetadata`, `debounceIds`, `bodyParts`) chegam
  intactos ao plugin.
- A entrega já tem cancelamento por mensagem nova (`StaleContactReply` em
  `_deliver_contact_reply`) e um poll barato `_newer_inbound_arrived`.
- `_check_bot_paused` já segue o padrão "checagem barata cedo + checagem fresca na hora
  de enviar". O gate de horário copia esse formato.

## Peça nova: replay pelo bridge

`POST /requeue` no bridge.js: recebe `{chatId, body, bodyParts, messageIds, reason}` e
empurra em `messageQueue` um evento igual ao de `flushDebounceBuffer`, com
`messageId: "resume:<uuid>"`, `debounceIds: messageIds`, `bodyParts`, `resume: {reason}`.
O Hermes consome como mensagem nova e o pipeline inteiro roda igual, com citação.

O tique de follow-up (`_tick_followups`) ganha um ramo para `cadence_kind == "resume"`:
lê em `whatsapp_messages.db` as mensagens do lead posteriores à última do bot
(`from_me=0`), monta o corpo e chama `/requeue`; `mark_sent` com o id sintético. Sem
mensagem pendente (o Rodrigo respondeu pelo celular), cancela o job.

## Gate de horário e esperas longas (antes do LLM, em `pre_gateway_dispatch`)

Só para chat de lead (não dono, não paciente, IA ligada). Evento com `resume` pula
os passos 2 a 4.

1. `hours = BusinessHours.from_profile(...)`, `now`.
2. **Lead Novo** (bot nunca falou com o chat): só libera a primeira resposta dentro de
   segunda a sexta, 09:00–21:00. Se o inbound chegar fora da janela, ou se o delay de
   `U(12, 35)` minutos atravessar 21:00, use `due = next_business_time(now) + U(12, 35)`
   minutos, `schedule_resume`, skip. Não use `off_days_ok`: fim de semana e feriado nunca
   permitem a Fase 1.
3. **Fora de hora, bot já falou** (noite útil, ou qualquer hora de fim de semana e
   feriado): `due = next_business_time(now) + U(12, 35) min`.
   `schedule_resume`, skip.
4. **Debounce de sintomas**: última bolha do bot bate com
   `humanization.diagnostic_question_regex` → `due = now + U(120, 180) s`. Se já existe
   resume pendente, empurra o vencimento (trailing) com teto `created + 300 s`.
   `schedule_resume`, skip.
5. Senão segue para o LLM agora. O debounce curto geral é o do bridge (8 s decaindo).

"Bot nunca falou" = campo `bot_first_outbound_at` no registro do contato. Setado no
primeiro envio bem-sucedido ao lead (`_deliver_contact_reply` e `_followup_bridge_send`).
Se o campo não existe, uma varredura única do histórico (`_chat_bot_sent_matching`)
decide e persiste o resultado, para leads anteriores ao deploy.

## Categoria e delay de resposta (depois do LLM)

- `transform_llm_output`: extrair `[cat:intencao|comum|objecao]` do fim da resposta
  (regex própria, ao lado de `_extract_handoff_details`), cortar antes de qualquer
  split de bolha ou voz. Inválido ou ausente → `comum`. Passa a categoria para
  `_schedule_contact_reply`.
- `_schedule_contact_reply._run()`: antes de `_deliver_contact_reply`, dorme
  `U(faixa da categoria)` em passos de 2 s consultando `_newer_inbound_arrived`; mensagem
  nova aborta (a resposta é descartada, o novo inbound gera outra). Nos últimos 5 s, ping
  de `/typing`.
- **Gate na hora de enviar**, no mesmo ponto: se `now` não é enviável em dia útil
  (`is_business_time(now)` for falso), não envia; agenda resume para
  `next_business_time(now) + U(12, 35) min` e descarta a resposta. Corte em 21h em ponto,
  inclusive para Lead Novo; não existe exceção de fim de semana, feriado ou Fase 1.
- O prompt ganha uma instrução curta (no `response_format` do profile) pedindo o
  marcador `[cat:...]` como última linha.

## Gates de conteúdo da Therapify

- Antes de o lead concluir o diagnóstico e receber prova social/reframe e agenda, perguntas sobre
  preço, pagamento, duração, formato, Google Meet ou sessão versus tratamento ficam pendentes. A
  resposta curta é "Vamos lhe passar maiores informações", seguida da próxima pergunta obrigatória;
  a explicação completa só sai no fechamento.
- Menção a sofrimento, ideação ou autolesão segue a calma clínica do roteiro do Rodrigo e não cria
  encaminhamento externo ou `[[HANDOFF]]` automático. Uma exceção só pode ser decidida manualmente
  pelo Rodrigo.

## Admissão, expiração e entrega parcial

- `contact_admission.require_scope_signal=true` exige evidência específica da Therapify no texto,
  campanha, título/corpo do anúncio ou oferta. Uma origem genérica como `meta_ads` não autoriza o funil. A
  policy v3 revalida no próximo inbound os registros antigos `new_live_commercial`; sem evidência,
  desliga a IA e grava `scope_pending`. Perfil Therapify ausente ou inválido falha fechado; palavras
  genéricas como "consulta", "sessão", "relacionamento" ou sofrimento isolado não admitem o contato.
- `delivery.max_model_response_age_s=480` mede apenas o trecho iniciado em `pre_llm_call`, depois
  das esperas humanas anteriores ao modelo. Ao ultrapassar o limite, a saída é suprimida antes do
  envio e o mesmo inbound recebe um job para regeneração na próxima janela válida. Confirmação de
  agenda já efetivada é a exceção, pois descartar esse efeito duplicaria ou ocultaria a reserva.
- Se `_human_send` confirma uma ou mais bolhas e falha depois, persiste em
  `partial_reply_state.json` somente as bolhas restantes e agenda um `resume:partial_delivery`.
  O job carrega a chave exata do turno; nunca seleciona cursor apenas pelo chat. O replay usa o
  inbound original mesmo quando não há mais mensagem pendente no banco e cancela o cursor se chegar
  inbound novo, inclusive quando isso só é detectável no SQLite após restart. Voz real e sequências
  híbridas ambíguas não têm retry automático.

## Config no `business_profile.json`

```json
"schedule": {"allow_new_lead_off_days": false},
"delivery": {"max_model_response_age_s": 480},
"humanization": {
  "first_reply_min_s": 720, "first_reply_max_s": 2100,
  "diagnostic_debounce_min_s": 120, "diagnostic_debounce_max_s": 180,
  "diagnostic_debounce_cap_s": 300,
  "diagnostic_question_regex": "tem quanto tempo que terminaram|afetando no trabalho|de 0 a 10|deixou de sentir fome|...",
  "reply_delay_s": {"intencao": [5, 75], "comum": [15, 210], "objecao": [30, 360]}
}
```
Sem o bloco (cliente genérico) nada disso liga: sem gate, sem delay, comportamento atual.

## Motor (`commercial_followups.py`)

- `schedule_resume(..., extend=True)`: se já existe resume pendente na generation,
  atualiza `due_utc = min(due, created_utc + cap)` em vez de ignorar.

## Arquivos da fase (5)

`bridge.js`, `whatsapp_manager.py`, `commercial_followups.py`,
`deploy/clients/therapify/business_profile.json`, `tests/test_humanization.py` (novo).

## Fora desta fase

Fase 7 (`reactivation`), marca de downsell, painel, deploy.

## Notas da implementação (2026-09-10)

- **Fail-closed sem motor de follow-up.** O gate e o corte das 21h continuam bloqueando
  qualquer envio fora de segunda a sexta, 09:00–21:00. Sem o tique do cron, o lead permanece
  pendente até a próxima retomada; não se libera a resposta imediatamente.
- **Adiar descarta o registro em memória do inbound** (`_clear_inbound` dentro de
  `_ritmo_gate`). O replay volta com o mesmo texto, e a reserva do turno pega o registro
  mais antigo: sem o descarte, a entrega compararia o token com o registro do replay e
  derrubaria a resposta como stale. Coberto por teste de regressão.
- **Lead Novo por histórico**: para leads anteriores ao deploy, a primeira leitura olha
  o banco do bridge (`from_me=1`, confirmado em produção) e grava o sentinela `legacy`
  no contato; a partir daí a resposta vem do registro.
- **Watchdog de "sem resposta" e o delay** (hotfix 2026-09-10 14:35): o watchdog apagava o
  registro do inbound aos 180 s e a entrega tratava o registro ausente como mensagem nova,
  cancelando a resposta que esperou o delay da categoria. O limite do watchdog passa a ser
  no mínimo o maior delay do profile + 120 s, e só um registro diferente conta como novo.
- **Resposta descartada fica na sessão do Hermes** (hotfix 2, 2026-09-10 14:42): o modelo
  continua de um ponto que o lead nunca viu. Cada descarte é registrado por chat e vira o
  bloco "RESPOSTAS QUE NÃO FORAM ENVIADAS" no contexto do turno seguinte; a lista some na
  primeira entrega real.
