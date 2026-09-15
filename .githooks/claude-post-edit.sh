#!/bin/sh
# Hook PostToolUse do Claude Code: recebe o JSON da ferramenta no stdin e roda o
# contrato visual quando o arquivo editado é de UI. Exit 2 devolve o erro ao agente.
file=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null)
[ -n "$file" ] || exit 0
root=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null) || exit 0
rel=${file#"$root"/}
exec sh "$root/.githooks/design-contract.sh" "$rel"
