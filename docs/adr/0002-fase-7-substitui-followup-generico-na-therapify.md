---
status: accepted
date: 2026-09-10
---

# A Fase 7 substitui o follow-up genérico para a Therapify, com cadência e textos no profile

O motor de follow-up da WhatsAYA nasceu com cadências genéricas de venda B2B (`silence`,
`proposal`, `payment`, `post_sale`) e textos que citam um fato do lead. O script da
Therapify tem uma reativação própria e validada (Fase 7: D1 "desistiu do tratamento?",
D2 método gravado, toque final protocolo), com textos literais. Decidimos manter um único
motor: a Fase 7 vira a cadência `reactivation` dentro dele, lida do
`business_profile.json` junto com a janela de horário e os feriados, e o profile da
Therapify desliga as demais cadências.

## Considered Options

- Módulo de reativação separado, como no bot legado: dois motores mandando follow-up
  para o mesmo lead é o cenário de mensagem duplicada, e o painel só enxerga um.
- Manter as cadências genéricas ligadas em paralelo: o "silence" de 30 min dispararia um
  toque genérico antes do D1 do script.

## Consequences

- O motor deixa de ter janela de horário e cadências como constantes de módulo; passa a
  recebê-las na construção. O padrão continua sendo o genérico (8h–18h, sem feriados),
  então outros clientes não mudam.
- O relógio da Fase 7 corre em tempo útil (9h–21h, seg–sex, sem feriado), diferente das
  72 horas corridas do legado. Lead de sábado recebe o D1 na terça.
