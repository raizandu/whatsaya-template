#!/usr/bin/env python3
"""Quanto o uso via assinatura Codex custaria se fosse cobrado pela API.

O Hermes grava os tokens de cada sessão em state.db, mas marca a rota
openai-codex como "included" (custo zero). Este script soma os tokens por
modelo/rota e reprecifica as sessões da assinatura com a tabela oficial da
API que o próprio Hermes usa, para comparar com o que a API cobraria.

Roda dentro do container:
    docker exec hermes python3 /opt/data/.hermes/scripts/estimate_api_cost.py --days 30
"""
import argparse
import sqlite3
import sys
import time
from decimal import Decimal

sys.path.insert(0, "/opt/hermes")
from agent.usage_pricing import get_pricing_entry  # noqa: E402

DB = "/opt/data/.hermes/state.db"
API_PROVIDER = {"openai-codex": "openai-api"}


def price(entry, row):
    inp, out, cr, cw = (Decimal(row[k] or 0) for k in ("inp", "out", "cr", "cw"))
    m = Decimal(1_000_000)
    return (
        inp * entry.input_cost_per_million
        + out * entry.output_cost_per_million
        + cr * entry.cache_read_cost_per_million
        + cw * entry.cache_write_cost_per_million
    ) / m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--source", default=None, help="ex.: whatsapp (default: todas)")
    args = ap.parse_args()

    cutoff = time.time() - args.days * 86400
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    where = "started_at >= ?"
    params = [cutoff]
    if args.source:
        where += " AND source = ?"
        params.append(args.source)
    rows = con.execute(
        f"""
        SELECT model, billing_provider AS provider, billing_mode AS mode,
               COUNT(*) AS sessions, SUM(api_call_count) AS calls,
               SUM(input_tokens) AS inp, SUM(output_tokens) AS out,
               SUM(cache_read_tokens) AS cr, SUM(cache_write_tokens) AS cw,
               SUM(reasoning_tokens) AS reasoning,
               SUM(estimated_cost_usd) AS charged
        FROM sessions WHERE {where}
        GROUP BY model, billing_provider, billing_mode
        ORDER BY inp + out DESC
        """,
        params,
    ).fetchall()

    if not rows:
        print(f"Nenhuma sessão nos últimos {args.days} dias.")
        return

    total_charged = Decimal(0)
    total_api = Decimal(0)
    print(f"Últimos {args.days} dias" + (f" (source={args.source})" if args.source else ""))
    print(f"{'modelo':<22}{'rota':<14}{'sess':>5}{'calls':>7}{'in':>11}{'out':>9}{'cache':>10}{'raciocínio':>11}{'cobrado':>10}{'preço API':>11}")
    for r in rows:
        provider = r["provider"] or "?"
        charged = Decimal(str(r["charged"] or 0))
        api_provider = API_PROVIDER.get(provider, provider)
        entry = get_pricing_entry(r["model"], provider=api_provider)
        api_cost = price(entry, r) if entry else None
        total_charged += charged
        if api_cost is not None:
            total_api += api_cost
        print(
            f"{r['model']:<22}{provider:<14}{r['sessions']:>5}{r['calls'] or 0:>7}"
            f"{r['inp'] or 0:>11,}{r['out'] or 0:>9,}{(r['cr'] or 0) + (r['cw'] or 0):>10,}"
            f"{r['reasoning'] or 0:>11,}{charged:>10.4f}{(f'{api_cost:.4f}' if api_cost is not None else 'n/a'):>11}"
        )
    print(f"\nCobrado de fato (API/fallback): US$ {total_charged:.4f}")
    print(f"Se tudo fosse pela API:          US$ {total_api:.4f}")
    print("Tabela de preço: a mesma que o Hermes usa (agent/usage_pricing.py).")


if __name__ == "__main__":
    main()
