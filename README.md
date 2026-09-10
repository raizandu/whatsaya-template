# WhatsAYA Template

Distribuição genérica do WhatsAYA para instalações administradas em VPS. O
repositório contém o plugin do Hermes, a ponte WhatsApp, o painel de operação e
templates sem dados de cliente.

> **Licença proprietária:** todos os direitos reservados a Anthony Fleuri
> (Raizandu). Este software não é open source. Ler o código publicamente não
> concede autorização para usar, implantar, modificar, redistribuir ou explorar
> comercialmente o produto. Consulte [`LICENSE`](LICENSE).

## Instalar numa VPS nova

O fluxo não exige conta, token ou chave SSH do GitHub no servidor:

```bash
git clone https://github.com/raizandu/whatsaya-template.git /opt/whatsaya
cd /opt/whatsaya
./deploy/bootstrap-vps.sh
```

Depois siga o [`checklist de onboarding`](deploy/VPS_CHECKLIST.md). Ele cobre:

1. Docker e Compose v2;
2. `.env`, persona, catálogo e assinatura do painel;
3. inicialização do Hermes, plugin e painel;
4. primeiro pareamento do WhatsApp;
5. Cloudflare Tunnel + Access;
6. testes de entrega e backup.

O bootstrap nunca sobrescreve dados existentes. Credenciais ficam em
`deploy/.env`; sessão, contatos, configuração comercial e marca ficam em
`/opt/whatsaya/data`. Esses arquivos não devem ser enviados ao GitHub.

## Componentes

- `whatsapp_manager.py`: regras, segurança, contatos, agenda e follow-ups;
- `bridge.js`: integração Baileys e entrega de mensagens;
- `panel/`: painel de contatos, Kanban, conversas, agenda (Google Calendar) e assinatura;
- `deploy/docker-compose.yml`: Hermes e painel com dados persistentes;
- `deploy/ONBOARDING.md`: referência operacional detalhada.

## Atualizar

```bash
cd /opt/whatsaya
git pull --ff-only origin main
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

Para uma instalação estável, use uma tag publicada em
`HERMES_SETUP_GITHUB_REF`. Personalizações de cliente devem ser configuração ou
feature flag, nunca alteração direta do código na VPS.

## Segurança

Dashboard, painel e QR ficam vinculados ao loopback por padrão. Não abra suas
portas diretamente na internet; publique apenas por HTTPS e autenticação,
conforme [`deploy/CLOUDFLARE.md`](deploy/CLOUDFLARE.md).

Este repositório é uma distribuição sanitizada. A fonte interna e os dados de
operação da Raizandu permanecem em repositório privado e não fazem parte deste
histórico.

## Migrar dados de um cliente anterior

Instalações que migram de um sistema anterior têm um importador idempotente e
fail-closed versionado na pasta do próprio cliente, em `deploy/clients/<id>/tools/`,
com o runbook de cutover e o mapeamento de dados em `deploy/clients/<id>/docs/`
— nunca no código do template. Veja [`deploy/clients/README.md`](deploy/clients/README.md)
para a convenção completa; fixtures de teste são sintéticas e nenhum banco,
sessão ou credencial deve ser versionado.
