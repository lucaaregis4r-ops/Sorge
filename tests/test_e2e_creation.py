"""Testes End-to-End (E2E) para a criação de compromissos em linguagem natural (Fase 5)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from sorge_gateway import telegram
from sorge_gateway.database import get_db_connection, get_events_for_date, init_db
from sorge_gateway.openclaw import ActionType, ParsedIntent

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch):
    """Configura um banco SQLite limpo para cada teste."""
    test_db = tmp_path / "test_e2e.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=test_db, schema_path=schema_file)
    monkeypatch.setattr("sorge_gateway.config.DATABASE_PATH", test_db)
    monkeypatch.setattr(telegram, "DATABASE_PATH", test_db)
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)
    return test_db

@pytest.mark.asyncio
async def test_e2e_natural_language_dentist_creation():
    """
    Testa o fluxo E2E:
    1. Usuário envia: 'marca dentista amanhã às 14h'
    2. Smart Router encaminha para OpenClaw
    3. OpenClaw retorna JSON estruturado com alta confiança
    4. n8n / SQLite cria o compromisso
    5. Bot responde no formato especificado na Seção 16 do plano
    """
    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 1001
    update.message.text = "marca dentista amanhã às 14h"
    update.message.reply_text = AsyncMock()

    mock_intent = ParsedIntent(
        action=ActionType.CREATE_EVENT,
        title="Dentista",
        date="2026-10-21",
        time="14:00",
        duration_minutes=60,
        reminders=[120, 30],
        confidence=0.98
    )

    with patch("sorge_gateway.telegram.default_openclaw_client.interpret_message", new_callable=AsyncMock) as mock_interpret:
        mock_interpret.return_value = mock_intent

        await telegram.smart_router_message_handler(update, MagicMock())

        # Verifica resposta enviada ao Telegram
        update.message.reply_text.assert_called_once()
        args, _ = update.message.reply_text.call_args
        resposta = args[0]

        assert "✅ Dentista marcado" in resposta
        assert "📅 21/10/2026" in resposta
        assert "🕑 14:00–15:00" in resposta

    # Verifica se o evento foi persistido no SQLite local
    events = get_events_for_date("2026-10-21")
    assert len(events) == 1
    assert events[0]["title"] == "Dentista"
    assert "2026-10-21T14:00:00" in events[0]["start_at"]

@pytest.mark.asyncio
async def test_e2e_natural_language_fisioterapia_creation():
    """
    Testa o fluxo E2E com frase complexa:
    'quinta depois do almoço coloca uma reunião com o pessoal da fisio'
    """
    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 1002
    update.message.text = "quinta depois do almoço coloca uma reunião com o pessoal da fisio"
    update.message.reply_text = AsyncMock()

    mock_intent = ParsedIntent(
        action=ActionType.CREATE_EVENT,
        title="Reunião com fisioterapia",
        date="2026-10-22",
        time="14:00",
        duration_minutes=60,
        reminders=[120, 30],
        confidence=0.93
    )

    with patch("sorge_gateway.telegram.default_openclaw_client.interpret_message", new_callable=AsyncMock) as mock_interpret:
        mock_interpret.return_value = mock_intent

        await telegram.smart_router_message_handler(update, MagicMock())

        update.message.reply_text.assert_called_once()
        args, _ = update.message.reply_text.call_args
        resposta = args[0]

        assert "✅ Reunião com fisioterapia marcado" in resposta
        assert "📅 22/10/2026" in resposta
        assert "🕑 14:00–15:00" in resposta

    events = get_events_for_date("2026-10-22")
    assert len(events) == 1
    assert events[0]["title"] == "Reunião com fisioterapia"

@pytest.mark.asyncio
async def test_e2e_low_confidence_clarification():
    """Testa frase ambígua onde o assistente solicita esclarecimento sem criar evento."""
    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 1003
    update.message.text = "preciso ver aquele negócio"
    update.message.reply_text = AsyncMock()

    mock_intent = ParsedIntent(
        action=ActionType.UNKNOWN,
        confidence=0.25,
        clarification_needed="Não entendi qual compromisso você deseja marcar. Poderia especificar o título e o dia?"
    )

    with patch("sorge_gateway.telegram.default_openclaw_client.interpret_message", new_callable=AsyncMock) as mock_interpret:
        mock_interpret.return_value = mock_intent

        await telegram.smart_router_message_handler(update, MagicMock())

        update.message.reply_text.assert_called_once()
        args, _ = update.message.reply_text.call_args
        assert "Não entendi qual compromisso" in args[0]

    # Nenhum evento deve ter sido criado
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM events")
        assert cursor.fetchone()["total"] == 0
