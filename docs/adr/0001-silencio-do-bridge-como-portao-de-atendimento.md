---
status: accepted
date: 2026-09-15
---

# Silêncio do bridge é o único portão da IA; o atendimento mora no painel

O painel ganha atendimentos com responsável humano, e enquanto houver responsável a IA
não pode responder o contato. Decidimos que o único mecanismo que cala a IA continua
sendo o silêncio por chat do `bridge.js`, que ganha um modo "até liberar" persistido e
uma listagem; o plugin não muda nesse ponto, porque já consulta `GET /chat-status` antes
de cada resposta e fica calado em caso de dúvida. O estado do atendimento (protocolo,
responsável, status, SLA) mora no `panel.db` e é reconciliado pelo painel com o bridge;
o plugin não conhece atendimento.

## Considered Options

- **Plugin lê o atendimento no `panel.db`.** Rejeitado: cria dependência do plugin no
  esquema do painel e um segundo portão a manter em fail-closed, além do que já existe.
- **Painel desliga `ai_enabled` em `personal_contacts.json`.** Rejeitado: o campo pertence
  ao gate de escopo comercial do plugin, que o reescreve nos próprios fluxos; o painel
  disputaria a mesma chave com semântica diferente.

## Consequences

- O estado fica em dois lugares (bridge e `panel.db`); a reconciliação periódica do painel
  é obrigatória, e o bridge precisa expor `GET /chat-silence` para ela.
- O handoff passa a calar a IA por prazo (silêncio temporizado longo, com motivo), não
  por hold, para que uma instalação sem ninguém no painel recupere a IA sozinha.
