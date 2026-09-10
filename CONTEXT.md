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
terminaram? como você vem lidando?"). É a única coisa que sai fora do horário comercial.
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

### Tempo

**Horário comercial**:
Segunda a sexta, 9h às 21h, horário de São Paulo. Dentro dele o funil roda completo.
_Avoid_: horário de atendimento, janela

**Noite útil**:
De 21h às 9h em dia de semana. Pausa total: nada sai, leads esperam na fila da manhã.

**Fim de semana**:
Sábado, domingo e feriado. Sai só a Fase 1 e o bot pausa até o próximo dia útil.
_Avoid_: final de semana, folga

**Feriado**:
Feriado nacional fixo ou data cadastrada no painel. Comporta-se como fim de semana.

**Fila da manhã**:
Leads que escreveram fora do horário comercial e aguardam o próximo dia útil às 9h.
Processada em lotes pequenos, mais antigo primeiro.
_Avoid_: fila pendente, backlog, represados

**Retomada**:
Momento em que o funil de um lead volta a andar às 9h do próximo dia útil: quem
respondeu segue de onde parou, quem não respondeu recebe a Fase 7.

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

**Categoria da mensagem**:
Classificação de cada mensagem do lead em intenção clara, troca comum, objeção ou
sintomas. Decide o delay de resposta.
_Avoid_: intenção, sentimento

### Oferta

**Downsell**:
Escada de ofertas de menor valor quando o lead trava por preço: sessão (R$247) →
método gravado (R$47) → protocolo (R$27, só no toque final da Fase 7). Nunca desconto na
sessão.
_Avoid_: desconto, condição especial, custo social

**Posicionamento**:
Autoridade fixa do script: "especialista em dependência emocional, 8 anos de
experiência". Aparece na Fase 1 e não muda.
