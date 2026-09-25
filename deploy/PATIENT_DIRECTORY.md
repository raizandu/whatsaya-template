# Cadastro de pacientes — Prontuário Verde

Integração opcional de leitura, desabilitada por padrão. Usa o navegador local do
Hermes para abrir a lista Pacientes; não depende da API pública nem reutiliza o
cookie como Bearer. A interface interna pode mudar e interromper a coleta.

## Configuração

No `panel.config.json`, configurar `patient_directory` com `enabled: false`,
`clinic_id` (identificador local), `expected_clinic_name` (linha exata do cabeçalho),
`source_clinic_hash` e `max_age_hours: 24`.

Criar `/opt/data/.hermes/secrets/prontuario-verde.json` no container com as chaves
`url`, `email`, `password`. Diretório 0700 e arquivo 0600, proprietário 10000:10000.
A URL deve ser HTTPS em `app.prontuarioverde.com.br`. Não versionar esse arquivo.
Instalar o navegador local usado pelas ferramentas do Hermes em volume persistente;
os caches no HOME devem pertencer ao usuário 10000.

Executar no container, como usuário 10000:10000:

```sh
/opt/hermes/.venv/bin/python /opt/data/.hermes/plugins/whatsapp-manager/deploy/scripts/sync_prontuario_verde.py --inspect
```

Conferir o cabeçalho da clínica e ausência de filtros. Registrar no config o hash
retornado, derivado de `cli_id` da sessão autenticada. Esse hash vincula o snapshot
à conta; não é credencial nem substitui a autenticação. Executar sem `--inspect`
para a primeira sincronização completa, e só então habilitar `enabled: true`.

## Operação

O coletor pagina até o fim e publica atomicamente `/opt/data/patient_directory.json`
(0600), contendo apenas IDs internos e telefones normalizados com DDI/DDD, origem,
vínculo da clínica e data. Telefones móveis legados são canonicalizados durante a
coleta e também na consulta. Número de prontuário visível pode estar vazio; a chave
utilizada é `pac_id`. Filtros ativos, linhas inválidas, clínica divergente, IDs
repetidos ou falhas de paginação preservam o último arquivo completo. Não abrir
fichas clínicas.
Linhas com apenas `age_id` (agendamento) e sem `pac_id` são contabilizadas em
`unlinked_appointment_rows`; não geram correspondência cadastral nem persistem seus
telefones/identificadores. Linhas sem nenhum dos dois IDs interrompem a coleta.

Instalar as unidades `whatsaya-patient-directory.service` e `.timer` em
`/etc/systemd/system`, executar `systemctl daemon-reload` e
`systemctl enable --now whatsaya-patient-directory.timer`. A coleta roda às 06:15 e
18:15 de São Paulo, com até cinco minutos de atraso aleatório. Consultar resultado
com `journalctl -u whatsaya-patient-directory.service`; logs contêm apenas contagens
e códigos de erro. O timer exige container chamado `hermes`.

O prompt recebe somente status, contagem e atualização. Na consulta, telefones móveis
brasileiros legados com DDD e oito dígitos iniciados por 6–9 são canonicalizados com
o nono dígito; linhas fixas iniciadas por 2–5 permanecem iguais. Assim, um JID antigo
pode corresponder ao cadastro móvel atual. Se as formas antiga e atual apontarem para
IDs de pacientes distintos, o resultado continua `ambiguous`. Telefone com DDI/DDD:
`matched`, `ambiguous`, `not_found`; dados inválidos, antigos ou sem vínculo de conta:
`unavailable`. LID não resolvido não é tratado como telefone. Não há aproximação por
nome ou últimos dígitos. Cadastro não confirma identidade nem atendimento anterior;
ausência de correspondência não prova que seja paciente novo.

Desabilitar `patient_directory.enabled` remove o contexto no próximo atendimento.
Parar o timer interrompe atualizações. Não modifica contatos, prontuários, agenda,
allowlist de IA ou classificação comercial.

## Agendamentos conferidos

O painel pode mostrar agendamentos do Prontuário Verde na ficha do contato e na
lateral de Atendimento, em uma seção separada da reunião Google Meet. A fonte é
`/opt/data/prontuario_verde_appointments.json`, um arquivo privado (0600) com
registros conferidos individualmente no sistema:

```json
{
  "schema_version": 1,
  "source": "prontuario_verde",
  "clinic_id": "cuidar-odontologia",
  "source_clinic_hash": "<mesmo hash de patient_directory>",
  "appointments": [{
    "id": "<id do agendamento>",
    "patient_id": "<id do paciente>",
    "start": "2026-09-28T16:00:00-03:00",
    "end": "2026-09-28T16:30:00-03:00",
    "professional_name": "Dra. Liliane Oliveira",
    "type": "Avaliação",
    "status": "agendado",
    "verified_at": "2026-09-23T18:00:00+00:00",
    "purpose": "test"
  }]
}
```

`purpose` é opcional; `test` marca o cartão como **Teste de integração**. Só são
exibidos IDs numéricos ligados a uma correspondência única e recente de telefone,
com clínica e hash iguais aos da configuração. Datas sem fuso, intervalos
inválidos, arquivo malformado ou vínculo divergente falham fechados. O cartão
mostra o momento da conferência em horário de São Paulo. A lista é de registros
conferidos individualmente, não uma sincronização completa da agenda; a ausência
de um agendamento no arquivo não significa que não exista no Prontuário Verde.
Não grave nomes de pacientes, dados clínicos ou URLs com sessão nesse arquivo.

## Abrir pelo painel

O detalhe do contato e a lateral do Atendimento exibem o status cadastral. Para
abrir uma ficha, o operador acessa o Prontuário Verde na conta da mesma clínica e
abre uma ficha e cola o endereço dessa aba em **Conectar aba**. O painel usa somente a sessão contida
nesse endereço, guardada no navegador daquela aba, separada por usuário. Ela não
é enviada à API do painel, gravada no snapshot ou compartilhada com o agente.
Se o Prontuário Verde pedir novo login, atualizar a conexão com o novo endereço.
O painel e a ficha precisam estar no mesmo navegador e perfil, com login ativo
na clínica. Copiar o endereço de outro navegador não transfere seus cookies de
autenticação: cada navegador precisa conectar um endereço gerado nele. A indicação
de conexão salva confirma apenas o formato do endereço; não valida a sessão externa.

Uma correspondência única habilita **Abrir prontuário**. Telefones compartilhados
levam à lista para conferência, sem escolher um paciente. Sem correspondência,
**Consultar e cadastrar** abre a lista, onde o operador confere outros telefones
antes de usar **Criar novo paciente**. O painel não cria cadastros automaticamente.
Links sem sessão perdem o destino após login, e a tela de criação exige checksum
do próprio Prontuário Verde; por isso não são armazenados links estáticos de ficha
ou criação. O identificador de paciente só é disponibilizado à interface autenticada
para correspondências únicas e válidas; o prompt continua recebendo apenas status.

## Cancelamento administrativo pelo painel

A opção `patient_directory.cancellation_enabled: true` habilita o botão para
administradores, apenas em reservas verificadas com status `agendado` e
`professional_id` numérico. O padrão é desligado. A identidade deve continuar
resolvendo para um único cadastro atualizado da mesma clínica. O pedido inclui
ID e intervalo esperado; o worker relê a ficha/agenda antes de qualquer escrita.
Não habilita ferramentas de agenda do bot nem Google/Meet.

Instalar `deploy/whatsaya-prontuario-verde-actions.service` em `/etc/systemd/system/`,
rodar `systemctl daemon-reload` e `systemctl enable --now
whatsaya-prontuario-verde-actions.service` **antes** de ligar a configuração.
O serviço usa o navegador local do Hermes como UID/GID 10000 e as mesmas
credenciais privadas do coletor. Não expõe endpoint externo nem Docker ao painel.

O worker cria `/opt/data/prontuario_verde_actions` e subdiretórios com setgid
02770; pedidos/resultados têm 0640 e lock 0660. Inicializar pelo worker preserva
proprietário/grupo 10000 para interoperar com o painel. O spool contém apenas
referências operacionais, nunca cookies/senhas. Pedidos expiram após 15 minutos;
cliques repetidos enquanto pendente reutilizam o mesmo pedido. Se o processo
interromper uma operação em curso, ela vira `needs_review`, sem repetir escrita.

A sequência usa o menu **Alterar a situação → Cancelada pela Clínica → Apenas
cancelar**. Não envia mensagem. Sucesso exige reload e confirmação explícita de
situação cancelada no mesmo evento/paciente/intervalo/profissional; ausência de
evento, remarcação externa, erro ou resposta inconclusiva não contam como sucesso.
Só depois o registro privado da AYA passa a `cancelado` com nova verificação.
Um cancelamento já confirmado no sistema é reconhecido sem nova escrita.

Os estados públicos são `pending`, `running`, `succeeded`, `failed` e
`needs_review`. Falhas devolvem códigos estáveis, sem respostas/segredos do PV.
Se houver resultado inconclusivo, conferir o sistema antes de tentar novamente.
Para desligar, remover `cancellation_enabled`/definir falso e parar o serviço;
o worker revalida a configuração antes do clique final. Um pedido cujo clique já
ocorreu ainda precisa de conferência. Não apagar o spool para ocultar pendências.


### Reuso da sessão do navegador

O worker de cancelamentos mantém um único navegador autenticado entre pedidos
serializados. Ao iniciar, tenta autenticar uma vez se o recurso está habilitado.
Antes de cada pedido, recarrega a página pelo servidor, verifica autenticação e
identidade da clínica; sessão expirada ou navegador perdido causam um novo login
limitado a uma tentativa. Não há renovação periódica do token nem uso como Bearer.
O heartbeat ocioso executa somente JavaScript local (`true`) a cada 45 segundos,
sem HTTP para manter login; isso preserva o processo local do navegador. Cookies permanecem na sessão local do navegador.

Falhas descartam a sessão. Após um clique com resultado incerto, o pedido segue
para revisão, sem repetição automática. Reiniciar o serviço descarta a sessão e
faz novo aquecimento; o cache de pacientes e sua agenda de coleta não mudam.
Logs registram somente `authenticated`/`reused`/`warmup_failed` e duração do
preparo da sessão, nunca URL de sessão, cookies ou credenciais.


### Próxima consulta em cache

`patient_directory.schedule_enabled=true` habilita a leitura periódica pelo mesmo
worker/browser de cancelamentos (a cada30min; em falha, nova tentativa após5min).
A coleta usa a fonte de dados da própria Agenda, todas as unidades/profissionais
visíveis e janela móvel de366dias. O código de prontuário da agenda é cruzado
com `record_number` do cadastro completo, nunca pelo nome. Linhas canceladas,
situações não reconhecidas e eventos sem vínculo cadastral são descartados e
contabilizados; ausência no cache não prova ausência de agendamento.

`/opt/data/prontuario_verde_schedule.json` (0600) guarda IDs, intervalo,
profissional, situação, origem, cobertura, atualização, código e nome do paciente
para exibição na agenda da equipe autenticada. Não guarda telefones ou procedimentos.
O cadastro de telefones continua sem nomes e o resumo enviado ao bot omite nomes e IDs. Snapshot incompleto ou com mais
de2h não é usado para afirmar a próxima consulta. O painel exibe cobertura e
atualização; o prompt recebe apenas resumo do próximo horário para telefone com
vínculo único, sem IDs. Telefones compartilhados permanecem sem resumo até
identificação do paciente. A mensagem não deve revelar horário espontaneamente
nem tratar o cache como confirmação em tempo real.

Cancelamento confirmado pela AYA remove o evento desse cache sem renovar a idade
dos demais registros. A lista histórica `prontuario_verde_appointments.json`
continua separada: a nova coleta não habilita botões de alteração em massa nem
ativa criação/remarcação autônoma. Depois de alterar o módulo patient_directory,
reiniciar o gateway Hermes e o painel para carregar o contexto atualizado.

Nesta conta, `/#agenda` usa esse cache no lugar do Google quando
`patient_directory.enabled` e `schedule_enabled` estão ativos. A tela oferece
dia, semana e mês, filtro por profissional (incluindo Todas) e grupos por
profissional. Recarregar consulta apenas o cache local; o worker sincroniza a
origem a cada 30 minutos. A cobertura não inclui o histórico anterior à coleta
e espaços vazios não comprovam disponibilidade. A consulta seguinte também
aparece no cabeçalho da ficha, inclusive quando a lateral está oculta no celular.


## Rotina de cadastro com identidade confirmada

`deploy/scripts/register_prontuario_verde_patient.py --request-file <arquivo>`
é a interface administrativa da rotina também usada pelo fluxo automático.
O arquivo deve ser privado (0600), conter somente `name`,
`phone`, `identity_confirmed: true`, e ser removido após a execução. Use apenas
dados confirmados da pessoa atendida; nome de exibição do WhatsApp não basta.

A rotina valida clínica e sessão, lê o diretório completo ao vivo e normaliza
telefones com/sem nono dígito. Um único telefone com nome correspondente reutiliza
a ficha. Telefone compartilhado, divergência de nome ou nome já existente em
outro cadastro exigem revisão humana. Só ausência confirmada permite criar.

A gravação usa o botão real da página 26, preenche somente nome/celular e verifica
o campo de telefone submetido após blur. Não marca comunicação de marketing,
rechamada ou CRM e não agenda consultas. Depois lê novamente a lista para
verificar ID, nome e telefone e atualizar o snapshot completo.

`prontuario_verde_registration.py` controla um journal privado por clínica e
telefone e um lock. Antes do clique de salvar persiste o estado submitted;
resultado incerto nunca autoriza outro clique de criação. Uma nova chamada só
reconcilia a ficha encontrada ou retorna needs_review. Não apagar esse journal
para tentar de novo sem conferir o que aconteceu na origem.


### Cadastro iniciado pelo WhatsApp

Com `patient_directory.registration_enabled=true`, o pre-LLM consulta o cache
na primeira mensagem real de um contato admitido no atendimento da clínica.
Vínculo único é reutilizado. Ausência inicia coleta do nome completo da própria
pessoa: uma apresentação explícita confirma identidade; nome isolado exige
confirmação. Nome de exibição do WhatsApp nunca serve como nome de registro.
Urgência e encaminhamento humano têm prioridade sobre essa coleta.

O hook persiste a identidade confirmada no contato e enfileira em
`/opt/data/prontuario_verde_registrations` (0700; arquivos 0600), sem navegador
no caminho da resposta. O worker existente processa cancelamentos primeiro,
depois cadastros e sincronização periódica. Reutiliza a sessão autenticada e
renova quando necessário. A validação ao vivo percorre o diretório completo;
um cadastro pode levar alguns minutos sem bloquear a conversa.

O worker exige mensagem inbound real não histórica, contato com IA ativa e
sem bloqueio/takeover, identidade ainda confirmada e mesma clínica. Revalida
essas condições antes de salvar. Pedido com mais de 15 minutos, identidade
alterada, telefone compartilhado, reinício durante execução ou resultado
incerto não é repetido automaticamente: exige conferência. O resultado só
permite afirmar cadastro após confirmação; não confirma consulta agendada.
Esta opção não habilita criação/remarcação de consultas.

## Política de agendamento e escrita pendente

`appointment_policy.py` classifica a elegibilidade com regras por cliente em
`panel.config.json > appointment_policy`. Cada atendimento define duração,
profissionais elegíveis e condições como cadastro existente, tratamento em curso
ou ficha conferida. A classificação `auto_book` autoriza apenas tentar um fluxo
de reserva; **não confirma vaga, cadastro ou consulta**. Uma política ausente ou
inválida devolve encaminhamento à equipe. A remarcação só pode preservar dados
de uma consulta original conferida ao vivo; o objeto passado à função não faz
essa conferência por si.

Instalações que usam a sessão web e as rotas internas do PV para cadastro,
agenda e cancelamento ainda precisam de um adaptador de disponibilidade e
escrita para marcação automática. A criação/remarcação nativa exige contrato
verificado, persistência contra duplicatas e confirmação pós-gravação antes de
ativar mensagens de consulta marcada. O bot atual não invoca
`appointment_policy.py` para marcar consultas.

`prontuario_verde_availability.py` valida apenas intervalos que uma futura
fonte da **Abertura de agenda** comprove por clínica, profissional, unidade e
data. Ela exige leitura completa e recente, inícios candidatos vindos da
própria fonte e todos os bloqueios; a ausência de eventos na grade não cria
vagas. `prontuario_verde_booking_queue.py` fornece uma fila privada para
pedidos confirmados e idempotentes de criação/remarcação. Resultado incerto
ou worker interrompido exige reconciliação, sem novo clique automático.

`deploy/scripts/prontuario_verde_appointment_writer.py` define a pré-checagem,
o limite de um envio e a reconciliação pós-save. O driver
`prontuario_verde_native_booking.py` conhece os controles documentados da
página de agendamento, mas bloqueia a escrita enquanto não houver contratos
verificados para a fonte de vagas abertas, a seleção do paciente, a consulta
de duplicatas e a leitura completa após salvar.
O formulário foi conferido sem gravação: a data usa `dd/mm/aaaa`, e a duração
40 usa Outra (`9999999999`) → `P41_NOVA_DURACAO=40` → `BT_INFORMADO_OK`.
O adaptador preserva a consulta original antes de editar seus horários,
reconsulta abertura/duplicatas antes do envio e aguarda a conclusão das ações
assíncronas do APEX antes de recarregar para conferência. Uma tentativa de
submissão não pode ser reiniciada chamando `prepare` novamente.
A validação nativa que retorna `P41_MSG_FORA_AGENDA` também é consultada antes
do envio; modo de encaixe/liberação forçada é recusado. Essa conferência é
adicional à fonte independente de abertura, nunca a substitui: esta conta
pode permitir marcação em agenda fechada, e uma opção de horário ou duração
no formulário, isoladamente, não comprova vaga. A página 172 (`regdesk`)
fornece os eventos de abertura e o detalhe da página 173 identifica a unidade,
a profissional e o intervalo. A leitura completa ainda não está ligada ao worker. O método `select_patient`
preenche a busca, exige uma sugestão visível com o ID exato, clica pela interface
e aguarda ID/telefone conferidos e término das requisições. O chamador ainda
precisa fornecer nome de busca e telefone obtidos da identidade verificada;
a label da sugestão não é usada como prova de identidade.

A fonte de compromissos deve ser obtida após selecionar profissional/unidade
nos filtros nativos e aguardar a atualização de seus parâmetros. Sobrescrever
somente `profissional_id` no POST mantendo o checksum anterior retornou uma
lista vazia incorreta no teste real. Preserve os parâmetros emitidos pela tela
e confira o escopo antes de interpretar a resposta; nunca registre o checksum.


O worker `process_prontuario_verde_actions.py` consome a fila de agendamentos
após cancelamentos e cadastros. Antes da escrita, revalida mensagem inbound,
IA ativa, ausência de transbordo, identidade única, clínica, política clínica,
profissional, unidade, tipo e, na remarcação, o agendamento original. A escrita
continua desligada: exige `patient_directory.enabled=true`,
`patient_directory.appointment_write_enabled=true` e mapeamentos conferidos em
`appointment_policy`. O fluxo WhatsApp ainda não produz ofertas nem confirma
pedidos nessa fila. Não ativar o flag até completar os contratos nativos e o
fluxo de confirmação; um resultado incerto sempre exige conferência humana.

O UID do gateway e do worker deve ser o mesmo (10000 nesta implantação).
A checagem de takeover também lê `Paths.panel_db`: se o painel roda como root,
manter esse banco com proprietário 10000:10000 e modo 0600; o painel root
continua acessando e preserva o modo privado em suas conexões.
Banco existente porém ilegível bloqueia cadastro; não desabilitar essa checagem.


### Leitura nativa de disponibilidade

`prontuario_verde_native_availability.read_snapshot` lê o dia solicitado no
calendário de Abertura (172), consulta novamente a função de fonte emitida pelo
APEX e exige acordo com os eventos carregados. Confere cada ID no leitor da
página 173: profissional, data, início/fim e duração livre. Usa a grade nativa
para candidatos e desconta compromissos obtidos da fonte assinada da Agenda.
Eventos com status desconhecido continuam bloqueando; lista vazia de consultas
não cria uma abertura. A hora da primeira leitura é preservada para o limite de
60 segundos de `available_starts`.

O leitor navega entre páginas e deve receber **sessão própria de leitura**,
separada do formulário de gravação. Não está ligado ao factory padrão do worker.
A reconciliação completa e o ciclo de oferta/aceitação no WhatsApp continuam
pendentes, portanto a escrita automática permanece desligada.

A validação real com ficha própria autorizada concluiu criação de Avaliação de
40 minutos, remarcação e cancelamento sem mensagem. Esse roteiro conferiu os
campos persistidos; não equivale ao ciclo completo de conversa do bot.
