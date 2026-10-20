"""Testes unitários para a integração com n8n e Google Calendar."""
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from sorge_gateway.database import create_event, get_events_for_date, init_db
from sorge_gateway.n8n import N8NClient
from sorge_gateway.telegram import check_n8n_status

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    test_db = tmp_path / "test_n8n.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=test_db, schema_path=schema_file)
    return test_db

@pytest.mark.asyncio
async def test_create_event_success_n8n(temp_db: Path):
    """Testa criação de evento via n8n com resposta de sucesso."""
    client = N8NClient(base_url="http://mock-n8n:5678/webhook", db_path=temp_db)

    mock_resp = httpx.Response(
        200,
        json={
            "status": "success",
            "calendar_event_id": "google_event_123",
            "htmlLink": "https://calendar.google.com/event/123",
            "summary": "Consulta Médica"
        },
        request=httpx.Request("POST", "http://mock-n8n:5678/webhook/calendar-create")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await client.create_event(
            title="Consulta Médica",
            start_at="2026-10-25T14:00:00",
            duration_minutes=60
        )

        assert res["source"] == "google_calendar"
        assert res["calendar_event_id"] == "google_event_123"
        assert res["id"] > 0

        # Verifica se foi espelhado no SQLite local
        events = get_events_for_date("2026-10-25", db_path=temp_db)
        assert len(events) == 1
        assert events[0]["calendar_event_id"] == "google_event_123"

@pytest.mark.asyncio
async def test_create_event_fallback_sqlite(temp_db: Path):
    """Testa fallback transparente para SQLite local quando n8n está inacessível."""
    client = N8NClient(base_url="http://offline-n8n:5678/webhook", timeout=0.1, db_path=temp_db)

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        res = await client.create_event(
            title="Dentista Local",
            start_at="2026-10-26T10:00:00",
            duration_minutes=45
        )

        assert res["source"] == "local_sqlite"
        assert res["calendar_event_id"] is None
        assert res["id"] > 0

        events = get_events_for_date("2026-10-26", db_path=temp_db)
        assert len(events) == 1
        assert events[0]["title"] == "Dentista Local"

@pytest.mark.asyncio
async def test_list_events_n8n_and_fallback(temp_db: Path):
    """Testa listagem de eventos com sucesso no n8n e com fallback no SQLite."""
    client = N8NClient(base_url="http://mock-n8n:5678/webhook", db_path=temp_db)

    # 1. Caso com n8n retornando eventos do Google Calendar
    mock_events = [
        {"id": "g_1", "summary": "Reunião Google", "start": "2026-10-27T09:00:00"}
    ]
    mock_resp = httpx.Response(
        200,
        json={"events": mock_events},
        request=httpx.Request("POST", "http://mock-n8n:5678/webhook/calendar-list")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        events = await client.list_events("2026-10-27")
        assert len(events) == 1
        assert events[0]["summary"] == "Reunião Google"

    # 2. Caso com n8n offline -> busca no SQLite
    create_event("Evento SQLite", "2026-10-28T15:00:00", db_path=temp_db)
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Offline")):
        events_fallback = await client.list_events("2026-10-28")
        assert len(events_fallback) == 1
        assert events_fallback[0]["title"] == "Evento SQLite"

@pytest.mark.asyncio
async def test_delete_event(temp_db: Path):
    """Testa cancelamento de evento com notificação ao n8n e atualização no SQLite."""
    client = N8NClient(base_url="http://mock-n8n:5678/webhook", db_path=temp_db)
    ev_id = create_event("A cancelar", "2026-10-29T10:00:00", calendar_event_id="cal_del_99", db_path=temp_db)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, request=httpx.Request("POST", "http://test"))
        success = await client.delete_event(ev_id, calendar_event_id="cal_del_99")
        assert success is True

    # No SQLite deve estar marcado como cancelled
    events = get_events_for_date("2026-10-29", db_path=temp_db)
    assert len(events) == 0  # get_events_for_date busca apenas ativos

@pytest.mark.asyncio
async def test_check_n8n_status():
    """Testa verificação de integridade do n8n."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", "http://health"))
        assert await check_n8n_status() is True

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Offline")):
        assert await check_n8n_status() is False
