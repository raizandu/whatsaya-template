# Checklist de onboarding — VPS nova

Objetivo: sair de uma VPS Ubuntu vazia para Hermes, infraestrutura de atendimento e painel
rodando, sem conta ou token do GitHub no servidor. O repositório público contém
somente código e templates; credenciais, sessão do WhatsApp, catálogo e dados do
cliente ficam em `/opt/whatsaya/data` e `deploy/.env`.

## 1. Preparar a VPS

- [ ] Criar uma VPS Ubuntu 24.04 LTS.
- [ ] Entrar por SSH usando chave, não senha.
- [ ] Atualizar o sistema e instalar `git`, `curl` e certificados.
- [ ] Instalar Docker Engine e o plugin Compose v2 pelo repositório oficial do
  Docker.
- [ ] Confirmar `docker --version` e `docker compose version`.
- [ ] Não abrir as portas 9119, 9120, 8642 ou 80 na internet. O acesso público
  será feito depois por Cloudflare Tunnel + Access.

Comandos iniciais, executados como `root` ou com `sudo`:

```bash
apt-get update
apt-get install -y ca-certificates curl git
# Instale o Docker conforme https://docs.docker.com/engine/install/ubuntu/
```

## 2. Baixar o template sem autenticação

```bash
git clone https://github.com/raizandu/whatsaya-template.git /opt/whatsaya
cd /opt/whatsaya
./deploy/bootstrap-vps.sh
```

O bootstrap é idempotente: cria a estrutura e os arquivos iniciais, mas não
sobrescreve `.env`, persona, catálogo ou dados já existentes.

## 3. Fazer o intake do cliente

- [ ] Nome completo e nome curto do responsável.
- [ ] Nome da empresa que será representada e nome escolhido para o atendimento.
- [ ] Número do dono em formato internacional, só dígitos e sem `+`.
- [ ] Provider/modelo de IA e a credencial correspondente.
- [ ] Catálogo real, preços e política de atendimento.
- [ ] Chave Pix apenas se houver venda direta no chat.
- [ ] Nome do plano, mensalidade e itens incluídos no painel.
- [ ] Decidir: recusar ligações, ler grupos, enviar confirmação de leitura e
  tempo de agrupamento das mensagens.

## 4. Configurar a instalação

```bash
cd /opt/whatsaya
nano deploy/.env
nano data/SOUL.md
nano data/SOUL_WHATSAPP.md
nano data/SOUL_EMAIL.md
nano data/support_rules.md
```

- [ ] Gerar `API_SERVER_KEY` com `openssl rand -hex 32`.
- [ ] Criar uma senha forte e exclusiva para o dashboard/painel.
- [ ] Preencher `WHATSAPP_OWNER_NUMBER`, `WHATSAPP_OWNER_NAME`,
  `WHATSAPP_BUSINESS_NAME` e `WHATSAPP_ASSISTANT_NAME`.
- [ ] Preencher apenas um provider de IA; deixar os demais vazios.
- [ ] Manter `HERMES_SETUP_GITHUB_REPO=whatsaya-template` e
  `HERMES_SETUP_GITHUB_REF=main`.
- [ ] Manter `WHATSAPP_CONFIG_SUBDIR=generic`.
- [ ] Confirmar que persona, respostas de teste e painel usam somente a marca do
  cliente; WhatsAYA/AYA não são a identidade de instalações genéricas.
- [ ] Deixar `WHATSAPP_ENABLED=false` até o primeiro pareamento.
- [ ] Remover todos os placeholders dos quatro arquivos em `data/`.

Validação:

```bash
grep -RIn '{{' data/SOUL*.md data/support_rules.md
docker compose --env-file deploy/.env -f deploy/docker-compose.yml config --quiet
```

O `grep` deve retornar vazio.

## 5. Iniciar Hermes, plugin e painel

```bash
./deploy/bootstrap-vps.sh --start
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail=100 hermes
```

- [ ] Os serviços `hermes` e `whatsaya-painel` estão em execução.
- [ ] O log informa que o plugin foi clonado de
  `raizandu/whatsaya-template`.
- [ ] Existe `/opt/whatsaya/data/.hermes/plugins/whatsapp-manager/plugin.yaml`.
- [ ] O perfil de clientes não possui ferramentas gerais liberadas.

## 6. Parear o WhatsApp

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec hermes hermes whatsapp
```

- [ ] No celular: WhatsApp → Aparelhos conectados → Conectar aparelho.
- [ ] Escanear o QR exibido no terminal.
- [ ] Alterar `WHATSAPP_ENABLED=true` em `deploy/.env`.
- [ ] Recriar o Hermes para aplicar o ambiente:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate hermes
```

## 7. Configurar o painel e publicar com login

```bash
nano data/panel.config.json
```

- [ ] Definir marca, plano, mensalidade e itens incluídos.
- [ ] Confirmar o painel apenas em loopback:

Sem credencial, a resposta deve ser `401` — isso confirma que o painel não foi
publicado sem autenticação:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9120/api/status
```

- [ ] Configurar Cloudflare Tunnel + Access seguindo
  [`CLOUDFLARE.md`](CLOUDFLARE.md).
- [ ] Publicar dashboard, painel e QR somente atrás de HTTPS + login.

## 8. Validar antes de entregar

- [ ] Mensagem de texto individual recebe resposta.
- [ ] Áudio recebido é transcrito antes de chegar ao modelo.
- [ ] Grupo é ignorado quando `WHATSAPP_GROUPS_ENABLED=false`.
- [ ] Ligação é recusada somente quando `WHATSAPP_REJECT_CALLS=true`.
- [ ] Mensagens fragmentadas são agrupadas conforme o debounce configurado.
- [ ] Busca de contato e Kanban funcionam no painel.
- [ ] Pausar e reativar IA funciona.
- [ ] Reiniciar containers não perde sessão, contatos ou configurações.
- [ ] Backup local está agendado conforme `backup-whatsaya.sh`.

## 9. Atualizações futuras

Não edite código dentro do clone do plugin na VPS. Dados e personalizações ficam
em `.env`, `data/` e `panel.config.json`. Para atualizar o produto:

```bash
cd /opt/whatsaya
git pull --ff-only origin main
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

O boot atualiza o plugin pela referência configurada. Para congelar uma versão,
use uma tag publicada em `HERMES_SETUP_GITHUB_REF`.

Diagnóstico detalhado e exceções estão em [`ONBOARDING.md`](ONBOARDING.md).
