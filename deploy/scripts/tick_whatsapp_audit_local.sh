#!/bin/sh
# Auditoria em disco, sem mensagens ou propostas automáticas ao dono.
# Hermes cron (uid 10000): "15 21 * * *", --no-agent --deliver local.
set -eu
export WHATSAPP_AUDIT_ENABLED=true
# Provider explícito e independente do modelo do gateway.
if [ "${WHATSAPP_BUSINESS_PROFILE:-}" = "therapify" ]; then
    export WHATSAPP_AUDIT_PROVIDER=openai
    export WHATSAPP_AUDIT_MODEL=gpt-4.1
    # O cron do Hermes remove chaves de provider do ambiente do subprocesso.
    # No deploy, gravar a chave OpenAI já configurada neste arquivo (0600,
    # dono do cron); somente este auditor a carrega, sem mudar o gateway.
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        audit_key_file="${WHATSAPP_AUDIT_OPENAI_KEY_FILE:-${HERMES_HOME:-/opt/data/.hermes}/whatsapp_audit_openai_key}"
        if [ -r "$audit_key_file" ]; then
            OPENAI_API_KEY="$(cat "$audit_key_file")"
            export OPENAI_API_KEY
        fi
        if [ -z "${OPENAI_API_KEY:-}" ]; then
            printf '%s\n' 'Auditoria Therapify: OPENAI_API_KEY indisponível; configure o arquivo privado whatsapp_audit_openai_key. O relatório registrará INDISPONIVEL se houver amostra.' >&2
        fi
    fi
fi
exec python3 /opt/data/.hermes/scripts/tick_whatsapp_audit.py --local-only "$@"
