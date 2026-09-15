# Spec — Aba Atendimento (multiatendimento)

Fechada em 15/09/2026 em sessão de grilling com o dono; todas as recomendações aceitas.
Vocabulário em [`CONTEXT.md`](../CONTEXT.md). Decisão estrutural em
[ADR 0001](adr/0001-silencio-do-bridge-como-portao-de-atendimento.md). Este documento é
o contrato: o que não está aqui não foi pedido.

## Problem Statement

O painel acabou de ganhar resposta pelo chat na tela Contatos e usuários com papéis, mas
continua sem a noção de "quem está cuidando de quem". Não existe atendimento: só contato,
mensagens e um silêncio de 10 minutos que mora na memória do bridge e só é consultado
quando alguém abre um contato. Com mais de uma pessoa atendendo, ninguém sabe o que é
seu, o que está sem dono, o que a IA ainda está conversando, nem há quanto tempo um
cliente espera. A tela Contatos, feita para ser uma lista de pessoas, virou um chat e
deixou de ser uma tabela. E o dono quer, no futuro, centralizar Instagram e outros canais
no mesmo lugar, o que exige uma entidade de atendimento independente do WhatsApp.

## Solution

Uma aba **Atendimento**, espelho da experiência de WhatsApp Web e Intercom, com quatro
filas (Meus, Sem responsável, Com a IA, Todos), um único composer no sistema e um painel
lateral do contato com etapa, valor, follow-up, protocolo e SLA. Cada conversa passa a
ter **atendimentos**: episódios com protocolo, responsável (atendente, Dono, IA ou
ninguém), abertura, primeira resposta, assunção e resolução. Assumir um atendimento cala
a IA para aquele contato até resolver ou devolver; o handoff da IA cala a IA e joga o
atendimento na fila de quem precisa de humano. Contatos volta a ser uma tabela, Lead fica
só leitura, e usuários ganham permissões por pessoa, começando por "ver todos os
atendimentos".

## User Stories

### Atendente

1. Como atendente, quero abrir a aba Atendimento e ver primeiro a fila "Meus", para
   trabalhar no que é meu sem procurar.
2. Como atendente, quero ver a fila "Sem responsável", para pegar o que está esperando
   por um humano.
3. Como atendente, quero ver a fila "Com a IA" com o nome do assistente configurado, para
   saber o que o assistente ainda está resolvendo sozinho.
4. Como atendente com a permissão de ver todos, quero ver a fila "Todos", para ter a
   visão completa do que está aberto.
5. Como atendente, quero que cada atendimento na lista mostre nome, prévia da última
   mensagem, hora, responsável e se está aguardando nós, para decidir o que abrir.
6. Como atendente, quero que os atendimentos aguardando nós apareçam destacados e
   ordenados por espera, para nunca deixar um cliente falando sozinho.
7. Como atendente, quero um botão "Assumir" num atendimento sem humano, para me tornar
   responsável antes de responder.
8. Como atendente, quero que minha primeira resposta num atendimento sem humano me torne
   responsável automaticamente, para não precisar clicar antes de falar.
9. Como atendente, quero ser impedido de responder num atendimento que é de outro
   atendente, com uma mensagem clara, para não atropelar um colega.
10. Como atendente, quero um botão "Devolver para a IA", para liberar o assistente quando
    o assunto humano acabou e ele pode seguir.
11. Como atendente, quero que "Devolver para a IA" fique indisponível quando a IA do
    contato está desligada ou o contato está bloqueado, para não achar que devolvi
    quando ninguém vai responder.
12. Como atendente, quero um botão "Resolver", para encerrar o atendimento e tirá-lo das
    filas.
13. Como atendente, quero que uma nova mensagem do contato depois de resolvido abra um
    atendimento novo, com outro protocolo, para o histórico de atendimentos ficar fiel.
14. Como atendente, quero ver o protocolo do atendimento no painel lateral, para citá-lo
    em anotações e conversas internas.
15. Como atendente, quero ver os relógios de SLA (primeira resposta e resolução) com
    destaque quando estourados, para priorizar.
16. Como atendente, quero mudar etapa e valor do lead no painel lateral sem sair do
    atendimento, para não perder o fio da conversa.
17. Como atendente, quero ver notas, próximo follow-up e status da reunião no painel
    lateral, para ter contexto antes de responder.
18. Como atendente, quero recolher o painel lateral, para dar mais espaço à conversa.
19. Como atendente, quero que a conversa mostre os eventos do atendimento (aberto,
    assumido por quem, devolvido, resolvido, handoff) como mensagens de sistema, para
    entender o que aconteceu sem ler log.
20. Como atendente, quero um chip "silenciada até HH:MM" quando o Dono leu a conversa no
    celular, para entender por que a IA está calada num atendimento "Com a IA".
21. Como atendente, quero uma faixa "IA pausada" quando a pausa global está ligada, para
    saber que nada novo vai chegar até alguém retomar.
22. Como atendente, quero um badge no menu e no título da aba com quantos atendimentos
    aguardam nós em Meus e Sem responsável, para perceber movimento com a aba fechada.
23. Como atendente, quero que a lista e a conversa aberta se atualizem sozinhas a cada
    poucos segundos, para não precisar recarregar.
24. Como atendente, quero que o link do atendimento seja compartilhável e sobreviva a um
    refresh, para mandar para um colega.
25. Como atendente no celular, quero que lista, conversa e painel lateral virem telas
    empilhadas com botão voltar, para atender de qualquer lugar.
26. Como atendente sem a permissão de ver todos, quero que a aba mostre só Meus e Sem
    responsável, para não me distrair com o que não é meu.
27. Como atendente sem a permissão de ver todos, quero ser recusado ao abrir a conversa
    de um atendimento que é de outro atendente, para a regra valer também pelo link.

### Admin

28. Como admin, quero reatribuir qualquer atendimento a outro atendente, para
    redistribuir carga.
29. Como admin, quero assumir um atendimento que é de outro atendente, para cobrir uma
    ausência.
30. Como admin, quero definir permissões por usuário ao criar e ao editar, começando por
    "ver todos os atendimentos", para controlar quem vê o quê.
31. Como admin, quero que desativar um atendente mande os atendimentos abertos dele para
    Sem responsável, para nada ficar preso com quem saiu.
32. Como admin, quero definir os alvos de SLA da instalação, para o destaque refletir o
    compromisso do negócio.
33. Como admin, quero definir o tempo de inatividade que resolve atendimentos da IA e do
    Dono, para o funil não acumular lixo.
34. Como admin, quero que no primeiro dia a aba já mostre quem escreveu na última semana,
    para a equipe não abrir uma tela vazia.

### Dono

35. Como Dono, quero continuar respondendo pelo celular como sempre, para não mudar meu
    hábito.
36. Como Dono, quero que minha resposta pelo celular apareça no painel como "Dono" e
    assuma o atendimento se ninguém tinha, para a equipe saber que já estou nele.
37. Como Dono, quero que um atendimento que assumi pelo celular se resolva sozinho depois
    de um tempo sem conversa, porque não vou abrir o painel para fechar.
38. Como Dono, quero continuar recebendo o card de handoff no meu WhatsApp, para não
    depender do painel para saber que a IA pediu ajuda.
39. Como Dono numa instalação sem atendentes no painel, quero que a IA volte sozinha a
    responder um contato de handoff depois de um prazo, para nenhum cliente ficar mudo
    para sempre.
40. Como Dono, quero que ler uma conversa no celular continue calando a IA por 10
    minutos, para poder responder à mão sem ser atropelado.

### Gestor do negócio

41. Como gestor, quero que cada atendimento registre quando abriu, quando teve a
    primeira resposta e por quem, quando foi assumido e quando resolveu, para medir SLA
    depois.
42. Como gestor, quero que a primeira resposta da IA conte como primeira resposta, para
    o SLA refletir o que o cliente sentiu.
43. Como gestor, quero que a tabela de Contatos volte a ser tabela, com colunas,
    ordenação e os escopos de hoje, para procurar pessoas e não conversas.
44. Como gestor, quero que a linha da tabela de Contatos abra o atendimento daquela
    pessoa, para ir da pessoa à conversa em um clique.
45. Como gestor, quero que a tela Lead continue com o workspace e a timeline, mas sem
    composer, para responder sempre no mesmo lugar e sob as mesmas regras.
46. Como gestor, quero que o modelo já tenha "canal", para o Instagram entrar sem
    refazer o atendimento.

### Contato (cliente)

47. Como contato, quero que a IA pare de responder assim que um humano assume, para não
    receber duas vozes.
48. Como contato, quero que a IA pare de responder quando ela mesma pediu um humano,
    para não ser enrolado enquanto espero.
49. Como contato bloqueado ou em grupo, não quero abrir atendimento nenhum, porque o
    negócio decidiu não me atender por ali.

## Implementation Decisions

### Modelo

- **Atendimento** é uma entidade nova, dona do painel, persistida no banco do próprio
  painel (o mesmo que hoje guarda a autoria das respostas). Campos: protocolo, contato
  (identidade canônica que colapsa telefone e `@lid`), canal (só WhatsApp), status
  (aberto, resolvido), tipo e usuário do responsável (IA, atendente, Dono, nenhum),
  carimbos de aberto, primeira resposta com autor, assumido, resolvido com motivo
  (manual, inatividade, bloqueio), hora e autor da última mensagem.
- **Eventos do atendimento** ficam numa tabela própria (tipo, ator, detalhe, hora) e
  alimentam a timeline como eventos de sistema, ao lado do handoff que já existe.
- **Protocolo** `AAAAMMDD-NNN`, sequencial por dia por instalação, só no painel.
- **SLA**: dois alvos por instalação no config do painel (primeira resposta em minutos,
  padrão 15; resolução em horas, padrão 24). Estourado é só destaque na lista.
- **Inatividade** que resolve atendimentos de IA e Dono: horas no config, padrão 24.
- **Dono** é identidade fixa, não usuário. O admin do env é um login, não o Dono.
- **Permissões** por usuário: o registro de usuário ganha uma lista de permissões;
  papéis viram presets (atendente = lista vazia; admin implica todas). Primeira
  permissão: ver todos os atendimentos. A rota "quem sou eu" devolve a lista.

### Portão da IA (ADR 0001)

- O silêncio por chat do bridge segue como único portão. Ganha modo **hold** (até
  alguém liberar), campo **motivo** (painel, handoff, dono, leitura), persistência com
  hold sobrevivendo a restart, e uma rota que **lista** os silenciados ativos. A rota de
  status por chat passa a informar hold e motivo. Gatilho temporizado (mensagem manual
  do Dono, leitura) nunca encurta um hold. Liberar limpa hold e prazo.
- O plugin muda em um único ponto: ao emitir o handoff com sucesso, silencia o chat por
  prazo com motivo handoff, se a env de horas de silêncio do handoff for maior que zero.
  Default zero; liga só quando o painel com atendimento estiver no ar. Falha no silêncio
  vira aviso e não desfaz o card ao Dono.
- O plugin **não conhece atendimento**.

### Reconciliação

- Módulo puro do painel, no molde da auditoria diária: recebe mensagens, autoria do
  painel, lista de silenciados do bridge, contatos (bloqueio e IA ligada) e usuários
  (ativos) e devolve as mudanças a aplicar. Nunca envia mensagem nem chama LLM.
- Roda numa thread de fundo do servidor do painel a cada 10 segundos, mais sob demanda
  ao listar, com trava de 5 segundos.
- Passos, idempotentes e nesta ordem: abrir atendimento para mensagem recebida sem
  atendimento aberto (aberto na hora da mensagem; responsável IA se a IA do contato está
  ativa, senão ninguém); atribuir ao Dono a mensagem enviada que não veio do painel nem
  da IA, se não havia humano; mover para "nenhum" o atendimento da IA cujo chat está
  silenciado por handoff, e devolvê-lo à IA com evento automático quando o prazo expira
  sem humano; resolver por inatividade os de IA e Dono; resolver por bloqueio; tirar o
  responsável dos atendimentos de atendente inativo; casar hold com responsável (humano
  sem hold recebe hold; hold do painel sem humano é liberado).
- Primeira execução após o deploy abre atendimento para todo contato com mensagem
  recebida nos últimos 7 dias; os demais só na próxima mensagem.

### API e ações do painel

- Listagem de atendimentos por fila, com cursor de alteração para o polling não reenviar
  tudo, contagens por fila e indicador de pausa global. Filtra pela permissão.
- Quatro ações novas: assumir, devolver, resolver, reatribuir (só admin). Assumir põe
  hold no bridge e falha fechada se o bridge falhar; devolver e resolver liberam, e falha
  ao liberar grava mesmo assim e devolve aviso visível. Devolver só com IA do contato
  ligada e contato não bloqueado.
- A ação de resposta existente passa a assumir se não há humano, recusa com 403 se há
  outro humano, e troca o silêncio de 10 minutos por hold. Todo o resto da cadeia
  fail-closed continua igual.
- O detalhe do lead passa a incluir o atendimento corrente e responde 403 pela regra de
  permissão. Ações de atendimento entram na lista permitida ao papel atendente.
- Ação de usuários para editar permissões; criar aceita permissões.

### Telas

- Aba Atendimento com três colunas (lista com filas, conversa com o composer já
  existente, painel do contato recolhível), rota própria com o contato no hash, polling
  de 5 segundos na lista e na conversa aberta, badge no menu e no título.
- Contatos vira tabela do kit de design com os escopos e chips de hoje; os escopos que
  falam de IA passam a ler o atendimento, não a heurística atual. A linha abre o
  atendimento.
- Lead perde o composer e ganha "abrir atendimento".
- Usuários mostra e edita permissões.
- As três telas nascem primeiro no kit do design system, depois no painel.

### Entrega

Fases com no máximo cinco arquivos cada, verificadas uma a uma: mocks no kit; bridge;
plugin dormente; store e reconciliação; API, ações e permissões; aba Atendimento;
Contatos, Lead e Usuários; docs, template e deploy. Bridge e plugin vão num deploy
próprio, antes, com reinício do gateway; o resto só reinicia o painel. Trabalho em
worktree isolado, commits por pathspec.

## Testing Decisions

Um bom teste aqui exercita comportamento observável por quem usa o painel, o bridge ou
o hook, nunca a forma interna: chama a porta pública, monta o estado por arquivos e
bancos temporários, e afirma o que o usuário veria e o que o bridge receberia.

- **Painel**: a costura é o HTTP do servidor do painel com bridge falso, banco e JSONs
  temporários, como já fazem os testes das ações e do login. Cobre filas, permissão,
  as quatro ações, a resposta que assume ou é recusada, o 403 no detalhe do lead e o
  cursor da listagem. A reconciliação pura ganha testes de cenário diretos onde o HTTP
  ficaria verboso: inatividade, prazo do handoff, atendente desativado, Dono pelo
  celular, primeira execução de 7 dias, casamento de hold.
- **Bridge**: a costura é o HTTP do Express, como no teste atual do bridge. Cobre hold,
  motivo, listagem, persistência do hold e a regra de que gatilho temporizado não
  encurta hold.
- **Plugin**: a costura é o hook, com a chamada HTTP substituída, como na suíte atual do
  plugin. Cobre o silêncio no handoff atrás da flag e o aviso em falha.
- **Frontend**: só o contrato visual de materialidade que já roda no pre-commit e no
  hook do editor, mais screenshots pelo harness da feature anterior. Sem teste de
  comportamento novo no browser.
- Prior art: os testes das ações do painel com bridge falso, os testes de login, os
  testes da auditoria diária (módulo puro alimentado por linhas), o teste do bridge e
  a suíte do plugin.

## Out of Scope

Instagram e qualquer outro canal (só o campo existe); times; etiquetas, inclusive as
nativas do WhatsApp Business que o bridge já expõe; respostas prontas; notas internas
por atendimento; adiar/snooze; protocolo enviado ao contato; relatório e alertas de SLA;
SSE ou WebSocket; restringir visibilidade em Contatos, Lead e kanban; mídia e áudio pelo
painel; notificação push do navegador; mudar o gatilho de leitura pelo celular; mover
atendimentos na pausa global.

## Further Notes

- "Ticket" é o chamado interno do módulo de Gestão e não pode nomear atendimento.
- O rótulo da fila da IA vem do nome do assistente configurado; a marca AYA só existe na
  instância própria e o publicador do template recusa nome de cliente no código.
- O watchdog de mensagem sem resposta do plugin já ignora chats silenciados no caminho
  principal do dispatch, então o hold não gera alerta falso.
- O silêncio do handoff usa prazo, não hold, de propósito: uma instalação onde só o Dono
  atende pelo celular recupera a IA sozinha.
- O estado vive em dois lugares (bridge e banco do painel); a reconciliação é o que
  mantém os dois coerentes, e por isso é thread de fundo, não só leitura.
