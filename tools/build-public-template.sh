#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  printf 'uso: %s DIRETORIO_NOVO\n' "$0" >&2
  exit 2
fi
if [ -e "$TARGET" ]; then
  printf 'destino já existe; escolha um diretório novo: %s\n' "$TARGET" >&2
  exit 2
fi

mkdir -p "$TARGET"

# Lista permitida. A publicação nunca espelha o repositório privado inteiro.
paths=(
  .gitignore
  LICENSE
  __init__.py
  adapter.py
  allowlist.js
  bridge.js
  calendar_booking.py
  commercial_followups.py
  contacts_store.py
  daily_audit.py
  google_api.py
  history_bridge.js
  history_store.py
  package-lock.json
  plugin.yaml
  whatsapp_manager.py
  panel
  skills/google-oauth
  skills/research-sources
  skills/whatsapp-client-triage
  skills/whatsapp-logs-diagnostics
  docs/LICENSING_AND_DEPLOYMENT.md
  deploy/.env.example
  deploy/ONBOARDING.md
  deploy/VPS_CHECKLIST.md
  deploy/CLOUDFLARE.md
  deploy/SOUL.md
  deploy/SOUL_EMAIL.md
  deploy/SOUL_WHATSAPP.md
  deploy/backup-whatsaya.sh
  deploy/bootstrap-vps.sh
  deploy/config.yaml.example
  deploy/docker-compose.yml
  deploy/personal_contacts.json.example
  deploy/public/README.md
  deploy/public/package.json
  deploy/qr-server.py
  deploy/support_rules.md
  deploy/whatsaya-qr.service
  deploy/hooks/post_fullsync_triage.sh
  deploy/scripts/authorize_google.py
  deploy/scripts/capture_logs.sh
  deploy/scripts/diagnose_duplicates.sh
  deploy/scripts/diagnose_native_whatsapp_conflict.sh
  deploy/scripts/fish_tts.py
  deploy/scripts/google_api.py
  deploy/scripts/sync_contacts_from_db.py
  deploy/scripts/tick_whatsapp_audit.py
  deploy/scripts/tick_whatsapp_followups.py
  deploy/scripts/update_pricing.py
  deploy/scripts/whatsapp_history_triage.py
  deploy/scripts/whatsapp_history_triage.yaml
  deploy/skills/whatsapp-client-triage
  deploy/skills/whatsapp-logs-diagnostics
  deploy/skills/whatsaya-diagnose
  deploy/skills/whatsaya-onboard
)

git -C "$ROOT" archive --format=tar HEAD -- "${paths[@]}" | tar -xf - -C "$TARGET"
mv "$TARGET/deploy/public/README.md" "$TARGET/README.md"
mv "$TARGET/deploy/public/package.json" "$TARGET/package.json"
rmdir "$TARGET/deploy/public"

for forbidden in deploy/instance graphify-out .git tests; do
  if [ -e "$TARGET/$forbidden" ]; then
    printf 'publicação recusada: caminho privado presente: %s\n' "$forbidden" >&2
    exit 1
  fi
done

if find "$TARGET" -type f \( -name '.env' -o -name 'client_secret_*.json' \
  -o -name '*.pem' -o -name '*.key' -o -name 'token*.json' \) | grep -q .; then
  printf 'publicação recusada: arquivo de credencial encontrado\n' >&2
  exit 1
fi

secret_pattern='GOCSPX-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
if grep -RIEqn --exclude='.env.example' "$secret_pattern" "$TARGET"; then
  printf 'publicação recusada: padrão de segredo encontrado\n' >&2
  exit 1
fi

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks dir --no-banner --redact --exit-code 1 "$TARGET"
fi

printf 'snapshot público criado a partir de %s em %s\n' \
  "$(git -C "$ROOT" rev-parse --short HEAD)" "$TARGET"
