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
