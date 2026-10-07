#!/bin/sh
# Auditoria em disco, sem mensagens ou propostas automáticas ao dono.
# Hermes cron (uid 10000): "15 21 * * *", --no-agent --deliver local.
set -eu
export WHATSAPP_AUDIT_ENABLED=true
exec python3 /opt/data/.hermes/scripts/tick_whatsapp_audit.py --local-only "$@"
