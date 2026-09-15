# WhatsAYA · Dr. Exemplo (Clínica Horizonte)

Prévia interativa da operação do Dr. Exemplo reescrita com o Aya Design System.
Abra `index.html` para navegar. Todos os contatos e números exibidos são
sintéticos; a prévia não lê nem expõe o banco real do cliente.

## Componentes reaproveitados

- `Navbar` e `SecondarySidebar` — casca operacional e navegação responsiva.
- `PageHeader` — hierarquia de título, contexto e ações.
- `Button`, `Input`, `Select` e `Badge` — átomos do Aya Design System.
- `WhatsAyaStatus`, `WhatsAyaMetric` e `WhatsAyaToggle` — estados próprios do
  domínio de atendimento.

## Cobertura da Clínica Horizonte

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
| Avisos ao Dr. Exemplo | Controle de notificações de handoff, agenda e falha |

O envio manual do painel antigo não foi reproduzido. A conversa é somente
leitura e orienta o Dr. Exemplo a responder pelo WhatsApp, preservando o fluxo
oficial do plugin, o silêncio automático e as garantias de entrega.

A lógica de produção continua pertencendo aos serviços do plugin e do painel;
esta pasta é a referência visual e de interação para a implementação final.

## Fase 0 — mocks de Atendimento, Contatos e Usuários

`Atendimento.jsx` traz três telas novas, todas em memória (sem rede, sem
persistência), seguindo o vocabulário de [`CONTEXT.md`](../../../CONTEXT.md) e
o contrato de [`docs/ATENDIMENTO_SPEC.md`](../../../docs/ATENDIMENTO_SPEC.md):

- **`WhatsAyaAtendimento`** — três colunas dentro de um único `_surface`: fila
  (abas Meus/Sem responsável/Com a IA/Todos com contagem e busca), conversa
  (protocolo, ações Assumir/Devolver para a IA/Resolver/Reatribuir, eventos de
  sistema, chip de silêncio e faixa de IA pausada) e painel do contato
  recolhível (SLA, etapa, valor, follow-up, reunião, notas). Um toggle "Ver
  todos os atendimentos" simula a permissão do papel atendente. Em ≤760px as
  três colunas viram telas empilhadas com botão voltar via
  `data-mobile-view` no `.wa-atd-layout` (`lista` · `conversa` · `painel`).
- **`WhatsAyaContatos`** — tabela com `DxDataGrid`/`FilterChip`/`DxSearch`/
  `DxPager`, escopos herdados do `contacts.js` anterior ao mestre-detalhe mas
  lendo o responsável do atendimento aberto (IA/atendente/Dono/—) em vez da
  heurística antiga de automação. A linha inteira é clicável e abre o
  atendimento do contato.
- **`WhatsAyaUsuarios`** — lista de usuários (papel, ativo) e formulário em
  `Modal` com a permissão "Ver todos os atendimentos" (admin implica todas e
  mostra o checkbox desabilitado e marcado).

Nenhuma das três telas persiste nada: o estado vive só no componente React da
prévia. A implementação real (painel) é fase posterior desta mesma entrega.
