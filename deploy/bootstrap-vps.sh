#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
EXPECTED_DIR="/opt/whatsaya"
MODE="${1:-init}"

say() { printf '%s\n' "$*"; }
die() { say "ERRO: $*" >&2; exit 1; }

case "$MODE" in
  init|--check|--start) ;;
  *) die "uso: ./deploy/bootstrap-vps.sh [init|--check|--start]" ;;
esac

if [ "$MODE" != "--check" ] && [ "$REPO_DIR" != "$EXPECTED_DIR" ]; then
  die "clone o repositório em $EXPECTED_DIR; o compose usa bind mounts absolutos desse caminho"
fi

command -v docker >/dev/null 2>&1 || die "Docker não encontrado; instale Docker Engine + Compose v2"
docker compose version >/dev/null 2>&1 || die "plugin 'docker compose' v2 não encontrado"

if [ "$MODE" = "--check" ]; then
  [ -f "$SCRIPT_DIR/docker-compose.yml" ] || die "docker-compose.yml ausente"
  [ -f "$SCRIPT_DIR/.env.example" ] || die ".env.example ausente"
  bash -n "$0"
  say "OK: bootstrap, Docker e Compose disponíveis."
  exit 0
fi

mkdir_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    mkdir -p "$@"
  else
    sudo mkdir -p "$@"
  fi
}

install_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    install "$@"
  else
    sudo install "$@"
  fi
}

mkdir_as_root "$EXPECTED_DIR/data" "$EXPECTED_DIR/root-hermes"

if [ ! -f "$ENV_FILE" ]; then
  install_as_root -m 0600 "$SCRIPT_DIR/.env.example" "$ENV_FILE"
  say "Criado: $ENV_FILE"
else
  say "Mantido: $ENV_FILE (não sobrescrito)"
fi

for name in SOUL.md SOUL_WHATSAPP.md SOUL_EMAIL.md support_rules.md; do
  target="$EXPECTED_DIR/data/$name"
  if [ ! -f "$target" ]; then
    install_as_root -m 0600 "$SCRIPT_DIR/$name" "$target"
    say "Criado: $target"
  fi
done

if [ ! -f "$EXPECTED_DIR/data/panel.config.json" ]; then
  install_as_root -m 0600 "$REPO_DIR/panel/panel.config.example.json" \
    "$EXPECTED_DIR/data/panel.config.json"
  say "Criado: $EXPECTED_DIR/data/panel.config.json"
fi

if [ "$MODE" = "--start" ]; then
  required_placeholders='SUBSTITUA_POR_UMA_CHAVE_ALEATORIA|SUBSTITUA_POR_UMA_SENHA_FORTE|WHATSAPP_OWNER_NAME=Nome do responsavel|WHATSAPP_BUSINESS_NAME=Nome da empresa atendida|WHATSAPP_ASSISTANT_NAME=Nome do atendimento'
  if grep -Eq "$required_placeholders" "$ENV_FILE"; then
    die "preencha os campos obrigatórios de deploy/.env antes de iniciar"
  fi
  if grep -Rq '{{' "$EXPECTED_DIR/data/SOUL.md" "$EXPECTED_DIR/data/SOUL_WHATSAPP.md" "$EXPECTED_DIR/data/SOUL_EMAIL.md" "$EXPECTED_DIR/data/support_rules.md"; then
    die "preencha todos os placeholders {{...}} nos arquivos de /opt/whatsaya/data"
  fi
  docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/docker-compose.yml" config --quiet
  docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/docker-compose.yml" up -d
  say "Stack iniciada. Veja o próximo passo em deploy/VPS_CHECKLIST.md."
  exit 0
fi

say "Estrutura inicial pronta. Agora siga deploy/VPS_CHECKLIST.md a partir do passo 4."
