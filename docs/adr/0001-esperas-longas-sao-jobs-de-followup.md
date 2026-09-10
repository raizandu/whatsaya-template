---
status: accepted
date: 2026-09-10
---

# Respostas com espera longa viram jobs em `followup_jobs`

A Therapify exige que a primeira resposta a um lead demore 12 a 35 minutos e que leads
fora do horário comercial (noite, fim de semana) esperem até as 9h do próximo dia útil.
Uma espera dessas em memória morre num restart do hermes e o lead nunca recebe resposta.
Decidimos que toda espera acima de 60 s é um job com vencimento em `followup_jobs`
(cadência `resume`), processado pelo mesmo cron de 1 minuto que já tica o motor de
follow-up, e que só esperas de segundos ficam em thread.

## Considered Options

- Fila própria em memória no bridge.js: já existe (100 itens) mas some no restart e não
  aparece no painel.
- "Resposta pendente" gravada no registro do contato em `personal_contacts.json` com uma
  varredura às 9h: durável, mas duplicaria lease, idempotência e a fila do painel que o
  motor já tem.

## Consequences

- Um restart perde no máximo uma resposta de segundos; o lead escreve de novo.
- A fila da manhã aparece no painel de graça, porque é a mesma tabela.
- O tique do cron passa a ter dois tipos de trabalho: enviar texto fixo (cadências) e rodar
  o pipeline de resposta (`resume`). Mensagem nova do lead não cancela um job `resume`,
  ao contrário das cadências.
