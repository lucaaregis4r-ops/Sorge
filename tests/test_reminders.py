"""Testes unitários para o módulo de agendamento, despacho e catch-up de lembretes."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from sorge_gateway.database import (
    create_event,
    get_reminders_for_event,
    init_db,
)
from sorge_gateway.reminders import (
    dispatch_due_reminders,
    schedule_reminders_for_event,
    startup_catchup,
)

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_reminders.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=test_db, schema_path=schema_file)
    monkeypatch.setattr("sorge_gateway.config.DATABASE_PATH", test_db)
    return test_db

def test_schedule_reminders_for_event():
    """Testa criação de lembretes proporcionais ao horário de início."""
    ev_id = create_event(
        title="Consulta Médica",
        start_at="2026-10-25T14:00:00"
    )

    # 120min (2h antes) e 30min antes
    ids = schedule_reminders_for_event(
        event_id=ev_id,
        start_at_iso="2026-10-25T14:00:00",
        reminders_minutes=[120, 30]
    )

    assert len(ids) == 2
    reminders = get_reminders_for_event(ev_id)
    assert len(reminders) == 2

    # Lembrete 1: 12:00
    assert "2026-10-25T12:00:00" in reminders[0]["send_at"]
    assert reminders[0]["status"] == "pending"

    # Lembrete 2: 13:30
    assert "2026-10-25T13:30:00" in reminders[1]["send_at"]
    assert reminders[1]["status"] == "pending"

@pytest.mark.asyncio
async def test_dispatch_due_reminders():
    """Testa envio de lembretes no horário programado."""
    ev_id = create_event(
        title="Reunião Zoom",
        start_at="2026-10-25T14:00:00"
    )
    schedule_reminders_for_event(
        event_id=ev_id,
        start_at_iso="2026-10-25T14:00:00",
        reminders_minutes=[60]
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    # Horário antes do envio (12:30) -> não deve enviar
    sent = await dispatch_due_reminders(
        bot=mock_bot,
        chat_id=12345,
        now_iso="2026-10-25T12:30:00"
    )
    assert len(sent) == 0
    mock_bot.send_message.assert_not_called()

    # Horário do envio (13:00) -> deve enviar
    sent = await dispatch_due_reminders(
        bot=mock_bot,
        chat_id=12345,
        now_iso="2026-10-25T13:00:00"
    )
    assert len(sent) == 1
    mock_bot.send_message.assert_called_once()
    args, _ = mock_bot.send_message.call_args
    assert "Reunião Zoom" in args[1] if len(args) > 1 else mock_bot.send_message.call_args[1]["text"]

    # Verifica status atualizado no banco
    reminders = get_reminders_for_event(ev_id)
    assert reminders[0]["status"] == "sent"
    assert reminders[0]["sent_at"] == "2026-10-25T13:00:00"

    # Segunda chamada não envia novamente
    mock_bot.send_message.reset_mock()
    sent_second = await dispatch_due_reminders(
        bot=mock_bot,
        chat_id=12345,
        now_iso="2026-10-25T13:01:00"
    )
    assert len(sent_second) == 0
    mock_bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_startup_catchup_late_warning():
    """Testa aviso retroativo para lembretes perdidos durante período offline."""
    ev_id = create_event(
        title="Reunião com fisioterapia",
        start_at="2026-10-25T15:00:00"
    )
    # Lembrete agendado para 14:00
    schedule_reminders_for_event(
        event_id=ev_id,
        start_at_iso="2026-10-25T15:00:00",
        reminders_minutes=[60]
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    # Sorge inicia às 14:37 (37 minutos após o lembrete, mas antes do evento das 15:00)
    catchup_sent = await startup_catchup(
        bot=mock_bot,
        chat_id=12345,
        now_iso="2026-10-25T14:37:00"
    )

    assert len(catchup_sent) == 1
    mock_bot.send_message.assert_called_once()
    kwargs = mock_bot.send_message.call_args[1]
    msg = kwargs.get("text", "")

    assert "⚠️ Sorge ficou offline." in msg
    assert "Reunião com fisioterapia — 15:00" in msg
    assert "37 minutos atrasado" in msg

    # Status deve ser late_sent
    reminders = get_reminders_for_event(ev_id)
    assert reminders[0]["status"] == "late_sent"

@pytest.mark.asyncio
async def test_startup_catchup_expired():
    """Testa que evento passado há muito tempo é marcado como expirado sem enviar mensagem."""
    ev_id = create_event(
        title="Evento de Ontem",
        start_at="2026-10-24T10:00:00"
    )
    schedule_reminders_for_event(
        event_id=ev_id,
        start_at_iso="2026-10-24T10:00:00",
        reminders_minutes=[30]
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    # Sorge inicia 1 dia depois
    catchup_sent = await startup_catchup(
        bot=mock_bot,
        chat_id=12345,
        now_iso="2026-10-25T14:00:00"
    )

    assert len(catchup_sent) == 0
    mock_bot.send_message.assert_not_called()

    # Status deve ser expired
    reminders = get_reminders_for_event(ev_id)
    assert reminders[0]["status"] == "expired"
