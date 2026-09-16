"""Páginas de nicho da landing page: registro no `panel.db`, HTML gerado no volume.

Uma página é um registro (slug, nicho, título SEO, H1, bloco do nicho,
pergunta própria do quiz, Pixel), não uma cópia do HTML. O template mestre
mora no volume (`/opt/data/lp/quiz.template.html`), conteúdo da instância como
o `SOUL.md`; `publish` renderiza cada página em `<www>/<slug>/index.html` e
regrava `sitemap.xml` e `robots.txt`. O servidor estático que já servia a LP
continua servindo; o painel só escreve arquivos.

Placeholders do template: `{{x}}` escapa HTML, `{{!x}}` entra cru (HTML que
este módulo montou) e `{{js:x}}` vira literal JSON dentro do script.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from panel_store import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS lp_pages (
    slug TEXT PRIMARY KEY,
    niche TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    h1 TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT '',
    niche_intro TEXT NOT NULL DEFAULT '',
    niche_pains TEXT NOT NULL DEFAULT '[]',
    question TEXT NOT NULL,
    question_sub TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '[]',
    pixel_id TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_utc TEXT NOT NULL,
    proofs TEXT NOT NULL DEFAULT '[]'
);
"""
# Colunas que entraram depois da primeira versão da tabela; `_open` as adiciona.
LATER_COLUMNS = {"proofs": "TEXT NOT NULL DEFAULT '[]'"}

RESERVED_SLUGS = {"api", "bio", "static", "www", "sitemap.xml", "robots.txt"}
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_PIXEL_RE = re.compile(r"^\d{6,32}$")
_PLACEHOLDER_RE = re.compile(r"\{\{(!|js:)?([a-z][a-z0-9_]*)\}\}")
_HIGHLIGHT_RE = re.compile(r"\*\*(.+?)\*\*")
MARKER = "<!-- gerado por lp_pages -->"  # é o que autoriza `publish` a apagar um diretório
LIMITS = {"title": 120, "description": 300, "h1": 160, "sub": 400, "niche": 80, "niche_intro": 1200,
          "question": 160, "question_sub": 300}

# A raiz de hoje, como registro: é o que `publish` gera em `/index.html`.
ROOT_PAGE = {
    "slug": "",
    "niche": "",
    "title": "AYA — Veja como funcionaria no seu negócio",
    "description": "Responda algumas perguntas rápidas e veja como a AYA pode entrar no atendimento comercial do seu negócio.",
    "h1": "Quantas vendas seu WhatsApp perde enquanto ninguém responde?",
    "sub": "A AYA coloca uma **IA humanizada dentro do seu WhatsApp** para atender, acompanhar e fazer follow-up sem parecer um robô.",
    "niche_intro": "",
    "niche_pains": [],
    "question": "Qual é o seu negócio?",
    "question_sub": "Escolha a opção mais próxima. Isso ajuda a gente a entender seu tipo de operação.",
    "options": ["Clínica ou consultório", "Serviços profissionais", "Loja ou comércio", "Educação, cursos ou mentoria", "Outro"],
    "pixel_id": "",
    "enabled": True,
    "proofs": [],
}


def _text(payload: dict, field: str, *, required: bool = False) -> str:
    value = " ".join(str(payload.get(field) or "").split())
    if required and not value:
        raise ValueError(f"{field} é obrigatório")
    limit = LIMITS.get(field)
    if limit and len(value) > limit:
        raise ValueError(f"{field} passa de {limit} caracteres")
    return value


def _lines(payload: dict, field: str, *, limit: int, max_items: int) -> list[str]:
    raw = payload.get(field)
    items = raw if isinstance(raw, list) else str(raw or "").splitlines()
    cleaned = [" ".join(str(item).split()) for item in items]
    cleaned = [item[:limit] for item in cleaned if item]
    if len(cleaned) > max_items:
        raise ValueError(f"{field} aceita no máximo {max_items} itens")
    return cleaned


def parse_proofs(raw) -> list[dict]:
    """Uma prova social por linha: `[opção do quiz] | Nome, cargo | frase`.
    A opção é opcional e casa com a resposta da pergunta de nicho; sem ela a
    frase vale para todo mundo. Já vem como lista de dicts quando o registro
    é relido."""
    if isinstance(raw, list) and all(isinstance(item, dict) for item in raw):
        lines = [" | ".join(filter(None, (item.get("option"), item.get("who"), item.get("quote")))) for item in raw]
    else:
        lines = raw if isinstance(raw, list) else str(raw or "").splitlines()
    proofs: list[dict] = []
    for line in lines:
        parts = [" ".join(str(part).split()) for part in str(line).split("|")]
        parts = [part for part in parts if part]
        if not parts:
            continue
        if len(parts) == 1:
            proofs.append({"option": "", "who": "", "quote": parts[0][:220]})
        elif len(parts) == 2:
            proofs.append({"option": "", "who": parts[0][:80], "quote": parts[1][:220]})
        else:
            proofs.append({"option": parts[0][:80], "who": parts[1][:80], "quote": parts[2][:220]})
    if len(proofs) > 24:
        raise ValueError("no máximo 24 provas sociais por página")
    return proofs


def clean_page(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("página inválida")
    slug = str(payload.get("slug") or "").strip().strip("/").lower()
    if slug and (not _SLUG_RE.match(slug) or slug in RESERVED_SLUGS):
        raise ValueError("slug inválido: só letras minúsculas, números e hífen; api, bio e static são reservados")
    pixel_id = str(payload.get("pixel_id") or "").strip()
    if pixel_id and not _PIXEL_RE.match(pixel_id):
        raise ValueError("pixel_id deve ser só dígitos")
    options = _lines(payload, "options", limit=80, max_items=8)
    if len(options) < 2:
        raise ValueError("a pergunta precisa de pelo menos duas opções")
    return {
        "slug": slug,
        "niche": _text(payload, "niche"),
        "title": _text(payload, "title", required=True),
        "description": _text(payload, "description", required=True),
        "h1": _text(payload, "h1", required=True),
        "sub": _text(payload, "sub"),
        "niche_intro": _text(payload, "niche_intro"),
        "niche_pains": _lines(payload, "niche_pains", limit=160, max_items=8),
        "question": _text(payload, "question", required=True),
        "question_sub": _text(payload, "question_sub"),
        "options": options,
        "pixel_id": pixel_id,
        "enabled": bool(payload.get("enabled", True)),
        "proofs": parse_proofs(payload.get("proofs")),
    }


def _row_to_page(row: sqlite3.Row) -> dict:
    page = dict(row)
    page["niche_pains"] = json.loads(page.get("niche_pains") or "[]")
    page["options"] = json.loads(page.get("options") or "[]")
    page["proofs"] = json.loads(page.get("proofs") or "[]")
    page["enabled"] = bool(page.get("enabled"))
    return page


def _open(db_path: Path | str) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    present = {row[1] for row in conn.execute("PRAGMA table_info(lp_pages)")}
    for column, decl in LATER_COLUMNS.items():
        if column not in present:
            conn.execute(f"ALTER TABLE lp_pages ADD COLUMN {column} {decl}")
    return conn


def save_page(db_path: Path | str, payload: dict, *, now: datetime | None = None) -> dict:
    page = clean_page(payload)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _open(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO lp_pages (slug, niche, title, description, h1, sub, niche_intro,"
            " niche_pains, question, question_sub, options, pixel_id, enabled, updated_utc, proofs)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (page["slug"], page["niche"], page["title"], page["description"], page["h1"], page["sub"],
             page["niche_intro"], json.dumps(page["niche_pains"], ensure_ascii=False), page["question"],
             page["question_sub"], json.dumps(page["options"], ensure_ascii=False), page["pixel_id"],
             int(page["enabled"]), stamp, json.dumps(page["proofs"], ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    page["updated_utc"] = stamp
    return page


def delete_page(db_path: Path | str, slug: str) -> bool:
    slug = str(slug or "").strip().strip("/").lower()
    if not slug:
        raise ValueError("a página raiz não pode ser apagada; desative-a")
    conn = _open(db_path)
    try:
        removed = conn.execute("DELETE FROM lp_pages WHERE slug = ?", (slug,)).rowcount
        conn.commit()
        return removed > 0
    finally:
        conn.close()


def list_pages(db_path: Path | str) -> list[dict]:
    if not Path(db_path).is_file():
        return []
    conn = _open(db_path)
    try:
        rows = conn.execute("SELECT * FROM lp_pages ORDER BY slug").fetchall()
        return [_row_to_page(r) for r in rows]
    finally:
        conn.close()


def get_page(db_path: Path | str, slug: str) -> dict | None:
    for page in list_pages(db_path):
        if page["slug"] == str(slug or "").strip().strip("/").lower():
            return page
    return None


# ── renderização ────────────────────────────────────────────────────────────

def _sub_html(text: str) -> str:
    """`**trecho**` vira o destaque laranja da intro; o resto é escapado."""
    escaped = html.escape(text)
    return _HIGHLIGHT_RE.sub(r'<span class="highlight">\1</span>', escaped)


def _niche_block(page: dict) -> str:
    if not page.get("niche_intro") and not page.get("niche_pains"):
        return ""
    parts = ['        <div class="niche">']
    if page.get("niche_intro"):
        parts.append(f"          <p>{html.escape(page['niche_intro'])}</p>")
    if page.get("niche_pains"):
        parts.append("          <ul>")
        parts.extend(f"            <li>{html.escape(item)}</li>" for item in page["niche_pains"])
        parts.append("          </ul>")
    parts.append("        </div>")
    return "\n".join(parts)


def _options_html(options: list[str]) -> str:
    return "\n".join(
        f'          <button class="opt" role="radio" aria-checked="false" data-value="{html.escape(o, quote=True)}">{html.escape(o)}</button>'
        for o in options
    )


def page_url(base_url: str, slug: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/{slug}/" if slug else f"{base}/"


def _jsonld(page: dict, *, base_url: str) -> str:
    """Organization + WebSite + WebPage. Sem FAQ inventado: as dores do nicho
    são afirmações, não perguntas, e rich result falso é penalidade."""
    base = base_url.rstrip("/")
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "@id": f"{base}/#org", "name": "AYA", "url": f"{base}/",
             "logo": f"{base}/og.png"},
            {"@type": "WebSite", "@id": f"{base}/#site", "url": f"{base}/", "name": "AYA",
             "inLanguage": "pt-BR", "publisher": {"@id": f"{base}/#org"}},
            {"@type": "WebPage", "@id": page_url(base, page["slug"]), "url": page_url(base, page["slug"]),
             "name": page["title"], "description": page["description"], "inLanguage": "pt-BR",
             "isPartOf": {"@id": f"{base}/#site"}, "about": page.get("niche") or "Atendimento comercial no WhatsApp com IA"},
        ],
    }
    body = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


def _niche_index(page: dict, pages: list[dict] | None, *, base_url: str) -> str:
    """Rodapé da raiz com um link por página de nicho publicada. Só a raiz o
    recebe: é o caminho do Google e de quem navega até cada nicho."""
    if page["slug"] or not pages:
        return ""
    others = [p for p in pages if p["slug"] and p.get("enabled", True)]
    if not others:
        return ""
    items = "\n".join(
        f'        <li><a href="{html.escape(page_url(base_url, p["slug"]), quote=True)}">{html.escape(p["niche"] or p["title"])}</a></li>'
        for p in sorted(others, key=lambda p: (p["niche"] or p["title"]).lower())
    )
    return (
        '    <footer class="niche-index" aria-label="AYA por segmento">\n'
        '      <h2>AYA para o seu segmento</h2>\n'
        f'      <ul>\n{items}\n      </ul>\n'
        '    </footer>'
    )


def render(template: str, page: dict, *, base_url: str, pages: list[dict] | None = None) -> str:
    values = {
        "title": page["title"],
        "description": page["description"],
        "canonical": page_url(base_url, page["slug"]),
        "h1": page["h1"],
        "sub_html": _sub_html(page.get("sub") or ""),
        "niche_block": _niche_block(page),
        "question": page["question"],
        "question_sub": page.get("question_sub") or "",
        "options": _options_html(page["options"]),
        "lp_id": page["slug"] or "home",
        "niche": page.get("niche") or "",
        "pixel_id": page.get("pixel_id") or "",
        "proofs": page.get("proofs") or [],
        "og_image": f"{base_url.rstrip('/')}/og.png",
        "jsonld": _jsonld(page, base_url=base_url),
        "niche_index": _niche_index(page, pages, base_url=base_url),
    }

    def fill(match: re.Match) -> str:
        kind, key = match.group(1), match.group(2)
        if key not in values:
            raise KeyError(f"placeholder desconhecido no template: {key}")
        value = values[key]
        if kind == "!":
            return value
        if kind == "js:":
            return json.dumps(value, ensure_ascii=False)
        return html.escape(str(value), quote=True)

    return _PLACEHOLDER_RE.sub(fill, template).rstrip("\n") + f"\n{MARKER}\n"


def _redirect_html(target: str) -> str:
    safe = html.escape(target, quote=True)
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">\n'
        f'<meta http-equiv="refresh" content="0; url={safe}">\n'
        '<meta name="robots" content="noindex"><title>AYA</title></head>\n'
        f'<body><a href="{safe}">Continuar</a></body></html>\n{MARKER}\n'
    )


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def publish(
    db_path: Path | str, *, www_dir: Path | str, template_path: Path | str, base_url: str,
    now: datetime | None = None,
) -> list[str]:
    """Gera todas as páginas, o sitemap e o robots. Devolve os caminhos escritos.
    Página desativada vira um redirect para a raiz, sem link morto; página
    apagada some do disco na próxima publicação (só diretórios de slug)."""
    template = Path(template_path).read_text(encoding="utf-8")
    www = Path(www_dir)
    pages = list_pages(db_path)
    if not any(p["slug"] == "" for p in pages):
        raise ValueError("falta a página raiz (slug vazio)")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    written: list[str] = []
    live_slugs = {p["slug"] for p in pages if p["slug"]}
    for page in pages:
        target = (www / page["slug"] / "index.html") if page["slug"] else (www / "index.html")
        content = render(template, page, base_url=base_url, pages=pages) if page["enabled"] else _redirect_html(page_url(base_url, ""))
        _write_atomic(target, content)
        written.append(str(target))
    # ponytail: só remove diretórios que já foram página; bio/ e o resto ficam.
    for old in www.glob("*/index.html"):
        slug = old.parent.name
        if slug not in live_slugs and slug not in RESERVED_SLUGS and _looks_like_ours(old):
            shutil.rmtree(old.parent, ignore_errors=True)
    urls = [page_url(base_url, p["slug"]) for p in pages if p["enabled"]]
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sitemap += [f"  <url><loc>{html.escape(u)}</loc><lastmod>{stamp}</lastmod></url>" for u in urls]
    sitemap.append("</urlset>\n")
    _write_atomic(www / "sitemap.xml", "\n".join(sitemap))
    _write_atomic(www / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base_url.rstrip('/')}/sitemap.xml\n")
    _write_atomic(www / "llms.txt", llms_txt(pages, base_url=base_url))
    written += [str(www / "sitemap.xml"), str(www / "robots.txt"), str(www / "llms.txt")]
    return written


def llms_txt(pages: list[dict], *, base_url: str) -> str:
    """Resumo em texto para agentes (llmstxt.org): o que é, para quem, e uma
    linha por página de nicho. Só o que está publicado."""
    root = next((p for p in pages if p["slug"] == ""), None)
    live = [p for p in pages if p["enabled"]]
    lines = ["# AYA", ""]
    if root:
        lines += [f"> {root['description']}", ""]
    lines += [
        "AYA é uma IA humanizada que atende, acompanha e faz follow-up de leads pelo WhatsApp de negócios que vendem por conversa.",
        "O caminho para conhecer é responder o quiz da página e continuar a conversa no WhatsApp.",
        "",
        "## Páginas",
    ]
    for p in live:
        label = p["niche"] or "Geral"
        lines.append(f"- [{p['title']}]({page_url(base_url, p['slug'])}): {label}. {p['description']}")
        for pain in p.get("niche_pains") or []:
            lines.append(f"  - {pain}")
    return "\n".join(lines) + "\n"


def _looks_like_ours(index_html: Path) -> bool:
    try:
        return MARKER in index_html.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
