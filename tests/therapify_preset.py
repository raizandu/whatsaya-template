"""Funil e agenda da instalação Therapify, lidos do mesmo JSON que vai para a VPS.

O template não tem mais preset de cliente no código: o funil é declarado em
`panel.config.json`. Os testes usam o arquivo de deploy como fixture para que
uma config inválida quebre aqui antes de chegar em produção."""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "deploy" / "clients" / "therapify" / "panel.config.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

THERAPIFY_PIPELINE: dict = CONFIG["pipeline"]
THERAPIFY_CALENDAR: dict = CONFIG["calendar"]
