# WhatsAYA

Atendimento automatizado por WhatsApp para um negócio, com um painel de operação onde o
dono e a equipe acompanham e assumem as conversas. Este glossário fixa o vocabulário do
domínio; não descreve implementação.

## Language

### Pessoas e canais

**Contato**:
Uma pessoa identificada por um número de WhatsApp (e seus aliases). Pode ser lead,
cliente, pessoal, fornecedor ou spam.
_Avoid_: chat, usuário, número

**Canal**:
A origem por onde um contato fala com o negócio. Hoje só WhatsApp.
_Avoid_: inbox, plataforma

**Dono**:
A pessoa do negócio que atende pelo próprio WhatsApp, fora do painel. Não é usuário do
painel; o admin do painel é um login, não o Dono.
_Avoid_: owner, admin

**Atendente**:
Usuário do painel que responde contatos. Todo usuário, admin incluído, pode atender.
_Avoid_: agente, operador

**IA**:
O assistente automatizado que responde contatos em nome do negócio. Na interface leva
o nome configurado do assistente (AYA só na instância própria).
_Avoid_: bot, Aya (no código), robô

### Conversa e atendimento

**Conversa**:
O histórico contínuo de mensagens entre o negócio e um contato, sem começo nem fim.
_Avoid_: chat, thread, timeline

**Atendimento**:
Um episódio delimitado de atenção a um contato dentro da conversa: abre com a primeira
mensagem do contato sem atendimento aberto e termina quando é resolvido. Tem um
responsável (humano ou IA) e um protocolo.
_Avoid_: ticket (reservado ao módulo de Gestão), chamado, caso, sessão

**Protocolo**:
O identificador público e sequencial de um atendimento.
_Avoid_: ticket, número do chamado

**Responsável**:
Quem está com o atendimento: um atendente, o Dono, a IA ou ninguém.
_Avoid_: assignee, dono do chat, agente

**Assumir**:
Um atendente ou o Dono tornar-se responsável por um atendimento. Enquanto houver
responsável humano, a IA não responde esse contato.
_Avoid_: pegar, takeover

**Devolver para a IA**:
Retirar o responsável humano de um atendimento aberto e liberar a IA para responder.
_Avoid_: liberar, reativar

**Resolvido**:
Estado final de um atendimento, por decisão de um atendente ou por inatividade quando
o responsável é a IA ou o Dono. Uma nova mensagem do contato abre outro atendimento.
_Avoid_: fechado, encerrado, concluído

**Aguardando nós**:
Atendimento aberto cuja última mensagem é do contato.
_Avoid_: não lido, pendente, sem resposta

**Handoff**:
O ato da IA pedir um humano para um contato. Tira o atendimento da IA, cala a IA e o
deixa sem responsável até alguém assumir, devolver, ou o prazo de segurança expirar.
_Avoid_: escalação, transbordo

**SLA**:
Os dois prazos medidos por atendimento: primeira resposta (de quem quer que seja, IA
incluída) e resolução. Alvos definidos por instalação.
_Avoid_: tempo de espera, TMA

### Filas do painel

**Meus**:
Atendimentos abertos cujo responsável é o atendente logado.

**Sem responsável**:
Atendimentos abertos sem responsável humano e sem a IA ativa para o contato.

**Com a IA**:
Atendimentos abertos cujo responsável é a IA.

**Todos**:
Todos os atendimentos abertos, qualquer responsável.

### Controles de IA já existentes

**Pausa global**:
A IA para de responder qualquer contato que não seja o Dono. Ligada e desligada pelo
Dono ou pelo painel.
_Avoid_: stop, parar o bot

**Silêncio**:
Bloqueio temporário da IA num único contato, disparado quando um humano lê ou
responde a conversa.
_Avoid_: mute, pausa do chat

**Bloqueio**:
O contato deixa de ser atendido por completo: sem IA, sem histórico, sem visto.
_Avoid_: banir, ignorar

### Módulo de Gestão

**Ticket**:
Um chamado interno de suporte ou melhoria da própria instalação, no módulo de Gestão.
Nunca um atendimento de contato.
_Avoid_: atendimento, chamado
