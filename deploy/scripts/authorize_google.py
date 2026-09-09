#!/usr/bin/env python3
"""
authorize_google.py — Gera o google_token.json via OAuth2 (primeira vez)

O jeito preferido de conectar o Google Agenda agora é o botão "Conectar
Google Agenda" no painel (fluxo web, sem precisar de terminal). Este script
é o fallback: use-o quando o painel não estiver acessível ou pra gerar o
token antes mesmo de subir o painel.

Execute UMA VEZ no container para autorizar o acesso ao Google:
  cd /opt/data && PYTHONPATH=/opt/hermes/.venv/lib/python3.13/site-packages \
    python3 .hermes/scripts/authorize_google.py

Requisitos:
  - GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET configurados no ambiente ou em /opt/data/.env
  - Acesso à internet para abrir a URL de autorização
  - O redirect_uri configurado no Google Cloud Console deve incluir: http://localhost:8080

Por padrão pede só o escopo do Calendar (o que o agendamento precisa). Pra
customizar, defina GOOGLE_OAUTH_SCOPES com uma lista separada por espaço ou
vírgula; GOOGLE_OAUTH_SCOPES=gmail é um atalho pros três escopos de Gmail
usados pelo suporte por e-mail, somados ao do Calendar.

Após autorizar, o token é salvo em /opt/data/.hermes/google_token.json (mesmo
formato que o painel grava) e o agente usa automaticamente esse token sem
precisar de novos logins.
"""

import os
import json
import sys
from datetime import timezone

PERSISTENT_DATA_DIR = "/opt/data"
HERMES_HOME = os.path.join(PERSISTENT_DATA_DIR, ".hermes")
TOKEN_PATH = os.path.join(HERMES_HOME, "google_token.json")
DOTENV_PATH = os.path.join(PERSISTENT_DATA_DIR, ".env")
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _resolve_scopes() -> list:
    raw = (os.getenv("GOOGLE_OAUTH_SCOPES") or "").strip()
    if not raw:
        return [CALENDAR_SCOPE]
    if raw.lower() == "gmail":
        return [*_GMAIL_SCOPES, CALENDAR_SCOPE]
    parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
    return parts or [CALENDAR_SCOPE]


SCOPES = _resolve_scopes()

try:
    from dotenv import load_dotenv
    load_dotenv(DOTENV_PATH)
except ImportError:
    pass

client_id = os.getenv("GOOGLE_CLIENT_ID")
client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

if not client_id or not client_secret:
    print("❌ GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET não encontrados.")
    print(f"   Configure-os em {DOTENV_PATH}.")
    sys.exit(1)

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
except ImportError:
    print("❌ Bibliotecas Google não encontradas. Execute:")
    print("   uv pip install --python /opt/hermes/.venv/bin/python google-auth-oauthlib google-api-python-client")
    sys.exit(1)

client_config = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": ["http://localhost:8080", "urn:ietf:wg:oauth:2.0:oob"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

print("🔐 Iniciando fluxo de autorização OAuth2 com o Google...")
print("   Será aberta uma URL no browser (ou cole no browser manualmente).")
print()

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

# Tentar porta local. Se não funcionar (sem browser), usar OOB.
try:
    creds = flow.run_local_server(port=8080, prompt="consent", open_browser=True)
except Exception:
    print("⚠️  Browser local não disponível. Use o modo manual:")
    auth_url, _ = flow.authorization_url(prompt="consent")
    print(f"\n👉 Abra esta URL no seu browser:\n{auth_url}\n")
    code = input("Cole aqui o código de autorização recebido: ").strip()
    flow.fetch_token(code=code)
    creds = flow.credentials

# Salvar token — mesmo formato que TokenStore.save_authorized (calendar_service.py)
# grava, pra que o painel e este script leiam/escrevam o mesmo arquivo sem atrito.
os.makedirs(HERMES_HOME, exist_ok=True)
payload = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri": getattr(creds, "token_uri", None) or DEFAULT_TOKEN_URI,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "scopes": list(creds.scopes or []),
    "universe_domain": "googleapis.com",
}
if creds.expiry:
    expiry = creds.expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    payload["expiry"] = expiry.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

with open(TOKEN_PATH, "w") as f:
    json.dump(payload, f, indent=2)
os.chmod(TOKEN_PATH, 0o600)

print(f"\n✅ Autorização concluída! Token salvo em: {TOKEN_PATH}")
print(f"   Escopos autorizados: {', '.join(SCOPES)}")
print("   O agente agora pode acessar o Google automaticamente com esse token.")
