"""Configured handoff destination and private operational card."""
import re
from urllib.parse import quote, urlsplit

from patient_directory import lookup_for_panel


def destination(root, reason, owner_number):
    routing = root.get("handoff", {})
    recipients = routing.get("recipients", {}) if isinstance(routing, dict) else {}
    match = re.match(r"^([a-z][a-z0-9_-]{0,30}):\s*(.+)$", reason, re.I)
    if match and isinstance(recipients, dict):
        configured = recipients.get(match[1].lower())
        number = re.sub(r"\D", "", str(configured or ""))
        if re.fullmatch(r"[1-9][0-9]{9,14}", number):
            return number, match[2]
    return owner_number, reason


def context_lines(root, chat_id, directory_path):
    lines = []
    routing = root.get("handoff", {})
    base = routing.get("panel_base_url", "") if isinstance(routing, dict) else ""
    parsed = urlsplit(str(base))
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        lines.append("*Atendimento AYA:* " + str(base).rstrip("/") + "/#atendimento-todas/" + quote(chat_id, safe=""))
    cfg = root.get("patient_directory", {})
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
        return lines
    try:
        match = lookup_for_panel(directory_path, cfg["clinic_id"], chat_id,
                                 source_clinic_hash=cfg["source_clinic_hash"])
        if match["status"] == "matched":
            lines.append("*Ficha PV vinculada ao telefone:* ID " + match["patient_id"] + " — conferir se pertence à pessoa que será atendida.")
        else:
            lines.append("*Ficha PV:* vínculo não confirmado; conferir identidade no PV.")
    except (OSError, ValueError, KeyError, TypeError):
        lines.append("*Ficha PV:* consulta indisponível; conferir identidade no PV.")
    return lines
