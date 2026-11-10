# WhatsAYA — Atendimento comercial Therapify

Bot de WhatsApp que conduz leads vindos de anúncio pelo funil de vendas do Dr. Rodrigo
(psicoterapia para dependência emocional) até o agendamento, com ritmo que imite o
consultório e não uma central de atendimento.

## Language

### Funil

**Lead**:
Número desconhecido que escreveu pela primeira vez e ainda não é paciente. Só leads
entram no funil.
_Avoid_: contato, cliente, usuário

**Paciente**:
Pessoa que já fez ao menos uma sessão com o Dr. Rodrigo. Nunca entra no funil; a
mensagem vai direto para notificação do Rodrigo.
_Avoid_: cliente existente, paciente antigo

**Fase 1 (Abertura)**:
Apresentação fixa em seis bolhas mais a pergunta de dor ("tem quanto tempo que
terminaram? como você vem lidando?"). Sai no horário comercial e, em fim de semana e
feriado, das 16h às 21h; à noite aguarda a próxima abertura.
_Avoid_: 1ª sequência, apresentação + triagem, primeira sequência, abertura + triagem

**Fase 2 (Diagnóstico)**:
As quatro perguntas diagnósticas e o acolhimento à resposta do lead.

**Fase 3 (Prova social)**:
Prova social e reframe, seguidos da agenda do dia. Dispara uma única vez por lead.

**Fase 7 (Reativação)**:
Sequência automática para lead que parou de responder: D1 pergunta se desistiu, D2
oferece o método gravado, o toque final oferece o protocolo. Depois do toque final o
bot nunca mais escreve para o lead por conta própria.
_Avoid_: follow-up genérico, nudge, cadência de silêncio

**Gate de perguntas comerciais**:
Antes de terminar diagnóstico, prova social/reframe e agenda, perguntas sobre preço,
pagamento, duração, formato, Meet ou sessão versus tratamento ficam pendentes. A Aya diz
"Vamos lhe passar maiores informações", faz a próxima pergunta obrigatória e só responde
completo no fechamento.

**Acompanhamento com outro profissional**:
Informar que já faz terapia com outro profissional não é recusa nem evidência de
que a pessoa é paciente do Dr. Rodrigo. O atendimento comercial continua da etapa
pendente; não se encerra com "leve isso para sua terapeuta" por esse motivo.
Para o lead já admitido pelo anúncio, seguir o fluxo normal sem perguntar novamente
se quer conhecer o atendimento: próxima pergunta pendente, Fase 3 após diagnóstico
ou pergunta de horário depois da agenda, sem reiniciar etapas concluídas.
Respeitar recusas, pedidos de humano e pontos terminais, sem desqualificar outro
profissional ou recomendar interrupção de tratamento. Isso não restringe ajuda
em situações de risco nem orientação clínica solicitada.

**Calma clínica**:
Menção a sofrimento, ideação ou autolesão segue o script calmo do Rodrigo ("Ok✅",
"Tudo bem", "Não se preocupe, rapidamente resolvemos o que vem sentindo"). Esse sinal
isolado não gera encaminhamento externo nem handoff automático; qualquer exceção é manual.

**Admissão de campanha**:
Um contato novo só entra no funil quando o texto ou os metadados identificam o escopo da
Therapify. Origem genérica de anúncio não basta. Registros antigos admitidos sem evidência
são reavaliados no próximo inbound e ficam em `scope_pending` se o escopo não for confirmado.
_Avoid_: admitir todo anúncio, campanha genérica

### Tempo

**Horário comercial**:
Segunda a sexta, 9h às 21h, horário de São Paulo. Dentro dele o funil roda completo.
_Avoid_: horário de atendimento, janela

**Noite útil**:
De 21h às 9h em dia de semana. Pausa total: nada sai, leads esperam na fila da manhã.

**Fim de semana**:
Sábado, domingo e feriado. Só sai a Fase 1 de Lead Novo, das 16h às 21h; o resto do
funil pausa até o próximo dia útil.
_Avoid_: final de semana, folga

**Feriado**:
Feriado nacional fixo ou data cadastrada no painel. Comporta-se como fim de semana.

**Fila da manhã**:
Leads que escreveram fora do horário comercial e aguardam o próximo dia útil às 9h.
Processada em lotes pequenos, mais antigo primeiro.
_Avoid_: fila pendente, backlog, represados

**Gate de envio**:
O sistema confere a janela no instante de cada envio. Se o delay atravessar 21h ou cair em
fim de semana/feriado, a mensagem permanece em job e só pode sair no próximo dia útil, entre
9h e 21h. A única exceção é a Fase 1 de Lead Novo, que em fim de semana e feriado sai das
16h às 21h.

**Retomada**:
Momento em que o funil de um lead volta a andar às 9h do próximo dia útil: quem
respondeu segue de onde parou, quem não respondeu recebe a Fase 7.

**Saudação de retomada**:
Duas bolhas antes de continuar o roteiro na fila da manhã: "Olá 👋" e
"Bom dia <primeiro nome>, tudo bem?". A segunda usa "Boa tarde" a partir das 12h e
"Boa noite" a partir das 18h, conforme o envio em São Paulo, omitindo nome inválido.
Vale também após fim de semana e feriado, somente se o lead respondeu depois de uma
saída do bot e há roteiro pendente. O bot segue na mesma sequência, sem esperar uma
resposta ao cumprimento. Não se aplica à abertura, Fase 7, debounce ou takeover.

### Ritmo (humanização)

**Lead Novo**:
Lead que ainda não recebeu nenhuma mensagem do bot. A primeira resposta demora de 12 a
35 minutos de propósito.
_Avoid_: primeiro contato, novo contato

**Debounce**:
Espera até o lead terminar de mandar mensagens picadas antes de o bot ler tudo junto.
Reinicia a cada mensagem nova. Mais longo quando o lead responde às perguntas de sintomas.
_Avoid_: buffer, coalescência

**Delay de resposta**:
Espera randomizada entre o fim do debounce e o envio, escolhida pela categoria da
mensagem do lead. Uma mensagem nova do lead durante o delay descarta a resposta planejada.
_Avoid_: atraso, humanização (é o objetivo, não o mecanismo)

**Saída expirada**:
Resposta do modelo que demora mais de oito minutos desde o início real do turno é bloqueada
antes do primeiro efeito e o inbound é reagendado para nova geração na próxima janela válida.
Uma reserva de agenda já efetivada é preservada e pode confirmar mesmo após esse limite.

**Cursor de entrega parcial**:
Registro durável das bolhas ainda não confirmadas quando uma resposta falha no meio. A
retomada reenvia apenas o restante; voz ou sequência híbrida ambígua exige intervenção
manual, porque não há prova suficiente para repetir efeitos com segurança.

**Categoria da mensagem**:
Classificação de cada mensagem do lead em intenção clara, troca comum, objeção ou
sintomas. Decide o delay de resposta.
_Avoid_: intenção, sentimento

### Oferta

**Oferta de agenda entregue**:
Uma consulta de disponibilidade não é uma oferta. A vaga só pode ser confirmada após
o envio da bolha que informa seu horário, com ID de entrega registrado. O inbound de
confirmação deve chegar depois dessa entrega e selecionar uma vaga da oferta válida.
Cancelar o turno invalida a oferta não entregue; um resultado atrasado não a restaura.

**Fechamento comercial**:
Agendamento confirmado, compra ou handoff de pós-venda encerra de forma persistente
a cadência de vendas e cancela seus jobs abertos. Nova mensagem ou confirmação
incidental não reabre a venda. Remarcação continua disponível com nova oferta e
confirmação, sem reativação comercial. Reabertura exige ação operacional explícita.

**Reserva e entrega humana**:
O roteiro permite criar o evento real após confirmação válida. Na Therapify, Rodrigo
assume Pix, comprovante e link do Meet após a notificação; a Aya confirma o horário.
O link pode constar do registro interno da reserva, sem ser enviado automaticamente
ao lead. A configuração `calendar.send_meet_to_lead=false` expressa esse limite.

**Saúde da conexão**:
O painel usa o estado atual do bridge em `/whatsapp/status` para `/api/health`.
`gateway_state.json` é um registro do Hermes e pode conter uma falha antiga; não
determina isoladamente se o WhatsApp está conectado. Verificar sinais runtime com
horário de consulta, sem apagar o registro antigo para simular recuperação.

**Downsell**:
Escada de ofertas de menor valor quando o lead trava por preço: sessão (R$247) →
método gravado (R$47) → protocolo (R$27, só no toque final da Fase 7). Nunca desconto na
sessão.
_Avoid_: desconto, condição especial, custo social

**Posicionamento**:
Autoridade fixa do script: "especialista em dependência emocional, 8 anos de
experiência". Aparece na Fase 1 e não muda.
