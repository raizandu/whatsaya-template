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
(0600), contendo apenas IDs internos e telefones normalizados, origem, vínculo da
clínica e data. Número de prontuário visível pode estar vazio; a chave utilizada é
`pac_id`. Filtros ativos, linhas inválidas, clínica divergente, IDs repetidos ou
falhas de paginação preservam o último arquivo completo. Não abrir fichas clínicas.
Linhas com apenas `age_id` (agendamento) e sem `pac_id` são contabilizadas em
`unlinked_appointment_rows`; não geram correspondência cadastral nem persistem seus
telefones/identificadores. Linhas sem nenhum dos dois IDs interrompem a coleta.

Instalar as unidades `whatsaya-patient-directory.service` e `.timer` em
`/etc/systemd/system`, executar `systemctl daemon-reload` e
`systemctl enable --now whatsaya-patient-directory.timer`. A coleta roda às 06:15 e
18:15 de São Paulo, com até cinco minutos de atraso aleatório. Consultar resultado
com `journalctl -u whatsaya-patient-directory.service`; logs contêm apenas contagens
e códigos de erro. O timer exige container chamado `hermes`.

O prompt recebe somente status, contagem e atualização. Telefone exato com DDI/DDD:
`matched`, `ambiguous`, `not_found`; dados inválidos, antigos ou sem vínculo de conta:
`unavailable`. LID não resolvido não é tratado como telefone. Não há aproximação por
nome, últimos dígitos ou adição do nono dígito. Cadastro não confirma identidade nem
atendimento anterior; ausência de correspondência não prova que seja paciente novo.

Desabilitar `patient_directory.enabled` remove o contexto no próximo atendimento.
Parar o timer interrompe atualizações. Não modifica contatos, prontuários, agenda,
allowlist de IA ou classificação comercial.

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
