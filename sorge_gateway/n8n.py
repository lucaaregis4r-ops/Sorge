"""Cliente de integração assíncrono com webhooks do n8n e Google Calendar."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import httpx

from sorge_gateway.config import DATABASE_PATH, N8N_WEBHOOK_BASE_URL, TIMEZONE
from sorge_gateway.database import (
    create_event,
    get_events_for_date,
    get_upcoming_events,
    update_event_status,
)
from sorge_gateway.logger import logger

class N8NClient:
    """Cliente para disparo de workflows de calendário no n8n."""

    def __init__(self, base_url: str = N8N_WEBHOOK_BASE_URL, timeout: float = 5.0, db_path: Optional[Path] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.db_path = db_path

    async def create_event(
        self,
        title: str,
        start_at: str,
        duration_minutes: int = 60,
        reminders_minutes: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Dispara workflow WF-01 (Calendar Create) no n8n.
        Em caso de indisponibilidade do n8n, salva localmente no SQLite como fallback resiliente.
        """
        if reminders_minutes is None:
            reminders_minutes = [1440, 60]  # 1 dia e 1 hora antes como padrão

        # Calcula end_at
        try:
            dt_start = datetime.fromisoformat(start_at)
            dt_end = dt_start + timedelta(minutes=duration_minutes)
            end_at = dt_end.isoformat()
        except Exception:
            end_at = None

        payload = {
            "title": title,
            "start": start_at,
            "end": end_at,
            "duration_minutes": duration_minutes,
            "timezone": TIMEZONE,
            "reminders": reminders_minutes
        }

        url = f"{self.base_url}/calendar-create"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    calendar_event_id = data.get("calendar_event_id")
                    local_id = create_event(
                        title=title,
                        start_at=start_at,
                        end_at=end_at,
                        calendar_event_id=calendar_event_id,
                        db_path=self.db_path
                    )
                    return {
                        "id": local_id,
                        "calendar_event_id": calendar_event_id,
                        "title": title,
                        "start_at": start_at,
                        "end_at": end_at,
                        "source": "google_calendar",
                        "status": "success"
                    }
        except Exception as e:
            logger.warning(f"n8n indisponível ({e}). Salvando evento no banco SQLite local.")

        # Fallback local SQLite
        local_id = create_event(
            title=title,
            start_at=start_at,
            end_at=end_at,
            calendar_event_id=None,
            db_path=self.db_path
        )
        return {
            "id": local_id,
            "calendar_event_id": None,
            "title": title,
            "start_at": start_at,
            "end_at": end_at,
            "source": "local_sqlite",
            "status": "success_local"
        }

    async def list_events(self, target_date_str: str) -> List[Dict[str, Any]]:
        """
        Dispara workflow WF-02 (Calendar List) no n8n.
        Retorna eventos do Google Calendar ou do SQLite local em caso de fallback.
        """
        start_date = f"{target_date_str}T00:00:00"
        end_date = f"{target_date_str}T23:59:59"

        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "timezone": TIMEZONE
        }

        url = f"{self.base_url}/calendar-list"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "events" in data:
                        return data["events"]
        except Exception as e:
            logger.info(f"n8n list_events fallback para SQLite local: {e}")

        # Fallback local no SQLite
        return get_events_for_date(target_date_str, db_path=self.db_path)

    async def delete_event(self, event_id: int, calendar_event_id: Optional[str] = None) -> bool:
        """
        Dispara workflow WF-04 (Calendar Delete) no n8n e atualiza o SQLite local.
        """
        if calendar_event_id:
            url = f"{self.base_url}/calendar-delete"
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    await client.post(url, json={"calendar_event_id": calendar_event_id})
            except Exception as e:
                logger.warning(f"Falha ao deletar evento no n8n Google Calendar: {e}")

        return update_event_status(event_id, "cancelled", db_path=self.db_path)

# Instância padrão compartilhada
default_n8n_client = N8NClient()
