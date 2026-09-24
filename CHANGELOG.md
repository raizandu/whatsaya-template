# Changelog

## 2026-09-17 — resiliência de envio (plugin `whatsapp-manager`)

Aprendido em produção na Therapify (auditoria de 2026-09-16/17).

- **Cache do cadastro de contatos.** `_load_personal_contacts` sanitizava todos os registros a cada
  chamada (~4 s com 1,9 mil contatos) e o gate de entrega lia o arquivo quatro vezes por bolha: cada
  bolha automática levava ~20 s. Agora o resultado fica em cache enquanto o arquivo não muda
  (inode/mtime/tamanho) e cada chamada recebe uma cópia própria. Bolha cai para ~1,5 s.
- **Nunca dois contatos no mesmo instante.** Texto, follow-ups e áudio automáticos compartilham
  uma trava de arquivo entre o gateway e o cron; ao trocar de contato o bot espera um intervalo aleatório
  `WHATSAPP_CHAT_GAP_MIN_S..WHATSAPP_CHAT_GAP_MAX_S` (padrão 15–30 s). Motivo: o WhatsApp bloqueia
  o número que fala com vários contatos ao mesmo tempo (fila da manhã disparava em paralelo).
- **Log por bolha.** `[human-send] bolha i/n chat=… Ns` mede guard + envio de cada bolha.

Ainda só na branch `therapify/painel-2026-09-09` (dependem do motor de ritmo/retomada, que o
template não tem): cursor parcial gravado a cada bolha e varredura pós-restart que reagenda bolhas
restantes e mensagens de lead sem resposta; Fase 1 direta sem passar pelo modelo.
