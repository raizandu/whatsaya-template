"""Serviço de fundo do contato ativo da LP: a cada minuto, manda a primeira
mensagem da AYA para quem terminou o quiz e não chamou. Best-effort: ponte
fora do ar, config desligada ou erro num lead não derrubam o painel nem
repetem envio — `contacted_at` marca a tentativa, com o status do que houve.
"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone

import marketing
import marketing_outreach
import marketing_store
from actions import ActionError, lp_outreach

INTERVALO_S = 60.0


class OutreachService:
    def __init__(self, paths, bridge, *, delay_min: int = 30, assistant_name: str = "AYA",
                 site: str = "agenteaya.com", owner_number: str = "", enabled: bool = False):
        self.paths = paths
        self.bridge = bridge
        self.delay_min = max(1, int(delay_min))
        self.assistant_name = assistant_name
        self.site = site
        self.owner_number = owner_number
        self.enabled = enabled
        self.last_run: datetime | None = None
        self.last_error: str = ""
        self._lock = threading.Lock()

    def arrived_session_ids(self) -> set[str]:
        inbound = marketing.load_first_inbound(self.paths.messages_db)
        return {sid for sid in (marketing.session_id_from_message(row.get("body", "")) for row in inbound.values()) if sid}

    def tick(self, now: datetime | None = None) -> list[dict]:
        """Uma passada. Devolve o que tentou, com status."""
        if not self.enabled or not self._lock.acquire(blocking=False):
            return []
        try:
            now = now or datetime.now(timezone.utc)
            leads = marketing_store.list_leads(self.paths.panel_db, limit=500)
            arrived = self.arrived_session_ids()
            results = []
            for lead in marketing_outreach.due(leads, arrived, now=now, delay_min=self.delay_min):
                try:
                    results.append(lp_outreach(
                        self.paths, self.bridge, lead, assistant_name=self.assistant_name,
                        site=self.site, owner_number=self.owner_number,
                    ))
                except ActionError as exc:
                    results.append({"session_id": lead["session_id"], "status": "failed", "detail": str(exc)})
            self.last_run = now
            self.last_error = ""
            return results
        except Exception as exc:  # o serviço nunca derruba o painel
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            traceback.print_exc()
            return []
        finally:
            self._lock.release()

    def start_background(self, interval_s: float = INTERVALO_S) -> threading.Thread:
        def loop():
            while True:
                time.sleep(interval_s)
                self.tick()
        thread = threading.Thread(target=loop, daemon=True, name="marketing-outreach")
        thread.start()
        return thread
