#!/bin/sh
# Contrato visual do painel (tests.test_panel_ui): paleta, sombras, movimento,
# camadas e tipografia só via token do Aya Design System.
# Uso: design-contract.sh <arquivo>... — roda só se algum arquivo for de UI.
# Sai com 2 em falha para o hook do Claude Code devolver o erro ao agente.
case " $* " in
  *" panel/static/"*|*" Aya Design System/"*|*" tests/test_panel_ui.py"*) ;;
  *) exit 0 ;;
esac
cd "$(git rev-parse --show-toplevel)" || exit 0
out=$(python3 -m unittest tests.test_panel_ui 2>&1)
if [ $? -ne 0 ]; then
  printf '%s\n' "$out" | grep -vE '^\s*(File |Traceback|\^+|~+)' | tail -n 40 >&2
  echo "[contrato visual] tests.test_panel_ui falhou: use os tokens do theme.css / Aya Design System." >&2
  exit 2
fi
echo "[contrato visual] ok (tests.test_panel_ui)"
