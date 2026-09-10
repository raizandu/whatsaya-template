# Configuração por cliente

Cada instalação com necessidades além do padrão genérico tem uma pasta aqui,
`deploy/clients/<id>/`, versionada no template mas sem dados pessoais nem
segredos:

- `panel.config.json` — a marca, o funil (`pipeline`), a agenda e a assinatura
  do cliente. Na VPS ele é copiado para `/opt/data/panel.config.json`, que o
  painel lê.
- `business_profile.json` — textos e regras de negócio do plugin do Hermes.
  Lido quando `WHATSAPP_BUSINESS_PROFILE=<id>` no `.env`, a partir do arquivo
  apontado por `WHATSAPP_BUSINESS_PROFILE_FILE` (padrão
  `/opt/data/business_profile.json` na VPS).
- `docs/` — runbooks e notas de migração específicos dessa instalação.
- `tools/` — scripts de uma vez só (ex.: importador de um sistema anterior)
  que só fazem sentido para essa instalação.

A persona completa do cliente (`SOUL_WHATSAPP.md`, `support_rules.md`,
catálogo, mídia) nunca entra no repositório — ela fica só no volume
(`/opt/data` na VPS), fora do controle de versão.

## Aplicar numa instalação

Copie os dois JSON para o volume de dados e reinicie os serviços:

```bash
cp deploy/clients/<id>/panel.config.json /opt/data/panel.config.json
cp deploy/clients/<id>/business_profile.json /opt/data/business_profile.json
docker compose --env-file deploy/.env -f deploy/docker-compose.yml restart painel hermes
```
