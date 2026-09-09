# WhatsAYA · Rodrigo (Therapify)

Prévia interativa da operação do Rodrigo reescrita com o Aya Design System.
Abra `index.html` para navegar. Todos os contatos e números exibidos são
sintéticos; a prévia não lê nem expõe o banco real do cliente.

## Componentes reaproveitados

- `Navbar` e `SecondarySidebar` — casca operacional e navegação responsiva.
- `PageHeader` — hierarquia de título, contexto e ações.
- `Button`, `Input`, `Select` e `Badge` — átomos do Aya Design System.
- `WhatsAyaStatus`, `WhatsAyaMetric` e `WhatsAyaToggle` — estados próprios do
  domínio de atendimento.

## Cobertura da Therapify

| Capacidade anterior | Destino na prévia WhatsAYA |
|---|---|
| Números do funil | Visão geral com leads, mensagens, agenda e fila humana |
| Chat e takeover | Conversas com histórico, pausa/retomada por lead e handoff |
| Lista de leads | Pipeline pesquisável com estado da IA por contato |
| Reativação D+1/D+2/oferta final | Fila revisável, desligada até aprovação explícita |
| Kill switch e rollout | Configurações com pausa global e rollout gradual |
| Horário comercial | Configurações de agenda e janela de atendimento |
| Google Calendar | Estado da integração e pendência de reconciliação |
| Áudio e mídia | Controles de transcrição e manifesto de prova social |
| Avisos ao Rodrigo | Controle de notificações de handoff, agenda e falha |

O envio manual do painel antigo não foi reproduzido. A conversa é somente
leitura e orienta o Rodrigo a responder pelo WhatsApp, preservando o fluxo
oficial do plugin, o silêncio automático e as garantias de entrega.

A lógica de produção continua pertencendo aos serviços do plugin e do painel;
esta pasta é a referência visual e de interação para a implementação final.
