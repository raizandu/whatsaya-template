#!/usr/bin/env python3
"""Atualiza `panel/pricing.json` com os preços públicos da OpenRouter.

O painel lê preço de arquivo, nunca da rede: o custo que ele mostra tem que ser
o mesmo entre dois carregamentos e não pode depender de um site estar de pé.
Este script é a ponte manual entre os dois — rode quando quiser refrescar a
tabela, confira o diff, e comite.

    python3 deploy/scripts/update_pricing.py                 # descobre os modelos em uso
    python3 deploy/scripts/update_pricing.py --model gpt-5.6-terra --model x/y
    python3 deploy/scripts/update_pricing.py --dry-run       # só mostra o que mudaria

Modelo do Codex (assinatura) é resolvido pelo equivalente `openai/<nome>` na
OpenRouter. Isso não é o que se paga por ele; é quanto custaria se o mesmo
tráfego fosse por API, que é exatamente a comparação que o painel mostra.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import date
from pathlib import Path

CATALOG_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_PRICING = Path(__file__).resolve().parent.parent.parent / "panel" / "pricing.json"
DEFAULT_STATE_DB = Path("/opt/data/.hermes/state.db")
PER_MILLION = 1_000_000


def fetch_catalog(url: str = CATALOG_URL, timeout: float = 30.0) -> dict[str, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return {str(m["id"]): m for m in payload.get("data", []) if m.get("id")}


def discover_models(state_db: Path) -> list[str]:
    """Modelos que as sessões de WhatsApp realmente usaram."""
    if not Path(state_db).is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT u.model FROM session_model_usage u"
            " JOIN sessions s ON s.id = u.session_id WHERE s.source = 'whatsapp' AND u.model IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return sorted({str(r[0]) for r in rows if r[0]})


def resolve(model: str, catalog: dict[str, dict]) -> tuple[str | None, dict | None]:
    """(id na OpenRouter, preços) para o nome que o Hermes registra."""
    for candidate in ([model] if "/" in model else [f"openai/{model}", model]):
        entry = catalog.get(candidate)
        if entry:
            return candidate, entry.get("pricing") or {}
    return None, None


def price_block(pricing: dict, source_id: str) -> dict:
    """Preço por milhão de tokens, que é a unidade que o painel usa."""
    def per_million(key: str) -> float:
        try:
            return round(float(pricing.get(key) or 0) * PER_MILLION, 6)
        except (TypeError, ValueError):
            return 0.0
    return {
        "input": per_million("prompt"),
        "cached_input": per_million("input_cache_read"),
        "output": per_million("completion"),
        "source": source_id,
    }


def build(models: list[str], catalog: dict[str, dict], current: dict) -> tuple[dict, list[str]]:
    updated = dict(current)
    updated.setdefault("usd_brl", 5.0)
    updated.setdefault("subscription_usd_month", 0)
    table = dict(updated.get("models") or {})
    missing: list[str] = []
    for model in models:
        source_id, pricing = resolve(model, catalog)
        if not pricing:
            missing.append(model)
            existing = table.get(model)
            if not isinstance(existing, dict):
                table[model] = {"input": 0, "cached_input": 0, "output": 0, "needs_review": True}
            continue
        table[model] = price_block(pricing, source_id or model)
    updated["models"] = dict(sorted(table.items()))
    updated["updated_at"] = date.today().isoformat()
    updated["source"] = CATALOG_URL
    updated.pop("_comment", None)
    updated["_comment"] = (
        "Preço por 1 milhão de tokens, em US$, buscado na OpenRouter por "
        "deploy/scripts/update_pricing.py. Modelo de assinatura é precificado pelo "
        "equivalente de API (campo `source`). `usd_brl` é a taxa fixa da conversão."
    )
    return updated, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", default=[], help="modelo a precificar (repetível)")
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        current = json.loads(args.pricing.read_text(encoding="utf-8")) if args.pricing.exists() else {}
    except ValueError as exc:
        print(f"pricing.json ilegível: {exc}", file=sys.stderr)
        return 2

    models = list(args.model) or discover_models(args.state_db) or sorted(current.get("models") or {})
    if not models:
        print("nenhum modelo para precificar: passe --model ou aponte --state-db", file=sys.stderr)
        return 2

    try:
        catalog = fetch_catalog()
    except Exception as exc:
        print(f"não consegui ler o catálogo da OpenRouter: {exc}", file=sys.stderr)
        return 1

    updated, missing = build(models, catalog, current)
    for name, block in updated["models"].items():
        if name not in models:
            continue
        if block.get("needs_review"):
            print(f"  {name:34s} SEM PREÇO no catálogo")
        else:
            print(f"  {name:34s} in={block['input']:>9.4f} out={block['output']:>9.4f} "
                  f"cache={block['cached_input']:>8.4f}  US$/mi  ({block['source']})")
    if missing:
        print(f"\n{len(missing)} modelo(s) sem preço: {', '.join(missing)}", file=sys.stderr)

    if args.dry_run:
        print("\n(dry-run: nada gravado)")
        return 0
    args.pricing.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\ngravado em {args.pricing} · câmbio US$ 1 = R$ {updated['usd_brl']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
