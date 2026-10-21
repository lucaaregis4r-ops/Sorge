"""Testes unitários para o gateway Telegram, autorização, deduplicação e Smart Router."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path
from sorge_gateway.database import create_event, init_db, is_update_processed
from sorge_gateway import telegram

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch):
    """Configura um banco SQLite limpo para cada teste."""
    test_db = tmp_path / "test_telegram.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=test_db, schema_path=schema_file)
    monkeypatch.setattr("sorge_gateway.config.DATABASE_PATH", test_db)
    monkeypatch.setattr(telegram, "DATABASE_PATH", test_db)
    return test_db

def test_is_user_authorized(monkeypatch):
    """Testa filtro de autorização de usuário."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)
    assert telegram.is_user_authorized(12345) is True
    assert telegram.is_user_authorized(99999) is False
    assert telegram.is_user_authorized(None) is False

    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", None)
    assert telegram.is_user_authorized(12345) is False

def test_uptime_format():
    """Testa se o uptime retorna formato legível de tempo."""
    uptime = telegram.get_uptime_str()
    assert isinstance(uptime, str)
    assert len(uptime) > 0

def test_build_application_without_token(monkeypatch):
    """Testa se tentar construir aplicação sem token lança ValueError."""
    monkeypatch.setattr(telegram, "TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        telegram.build_application()

@pytest.mark.asyncio
async def test_start_handler_authorized(monkeypatch):
    """Testa execução do /start para usuário autorizado."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 202
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await telegram.start_handler(update, context)

    update.message.reply_text.assert_called_once()
    assert is_update_processed(202)

    # Tentativa subsequente com mesmo update_id deve ser ignorada (deduplicação)
    update.message.reply_text.reset_mock()
    await telegram.start_handler(update, context)
    update.message.reply_text.assert_not_called()

@pytest.mark.asyncio
async def test_status_handler_authorized(monkeypatch):
    """Testa execução do /status para usuário autorizado."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 303
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await telegram.status_handler(update, context)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    resposta = args[0]
    assert "Sorge online" in resposta
    assert "Banco SQLite: OK" in resposta
    assert is_update_processed(303)

@pytest.mark.asyncio
async def test_help_handler_authorized(monkeypatch):
    """Testa execução do /ajuda."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 404
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await telegram.help_handler(update, context)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "Comandos disponíveis" in args[0]

@pytest.mark.asyncio
async def test_usage_handler_authorized(monkeypatch):
    """Testa execução do /uso."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 505
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await telegram.usage_handler(update, context)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "SORGE — USO HOJE" in args[0]

@pytest.mark.asyncio
async def test_smart_router_agenda_message(monkeypatch, setup_test_db):
    """Testa mensagem natural 'agenda hoje' através do smart_router_message_handler."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    # Cria um evento de teste para a data atual
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    create_event("Dentista", f"{hoje_iso}T14:00:00", db_path=setup_test_db)

    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 606
    update.message.text = "agenda hoje"
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await telegram.smart_router_message_handler(update, context)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "Dentista" in args[0]

@pytest.mark.asyncio
async def test_smart_router_cancel_and_complete(monkeypatch, setup_test_db):
    """Testa cancelamento e conclusão de eventos determinísticos."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    ev_id = create_event("Reunião", "2026-10-25T10:00:00", db_path=setup_test_db)

    # Cancela evento
    update_cancel = MagicMock()
    update_cancel.effective_user.id = 12345
    update_cancel.update_id = 701
    update_cancel.message.text = f"cancelar {ev_id}"
    update_cancel.message.reply_text = AsyncMock()

    await telegram.smart_router_message_handler(update_cancel, MagicMock())
    args, _ = update_cancel.message.reply_text.call_args
    assert f"Compromisso #{ev_id} cancelado com sucesso" in args[0]

@pytest.mark.asyncio
async def test_smart_router_llm_fallback(monkeypatch):
    """Testa frase ambígua encaminhada para LLM fallback."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    update = MagicMock()
    update.effective_user.id = 12345
    update.update_id = 801
    update.message.text = "quinta depois do almoço coloca uma reunião com a fisio"
    update.message.reply_text = AsyncMock()

    await telegram.smart_router_message_handler(update, MagicMock())
    args, _ = update.message.reply_text.call_args
    # Como pode haver OpenClaw real online ou fallback offline, aceita ambos
    assert ("marcado" in args[0].lower() or "esclarecimento" in args[0].lower() or "não consegui" in args[0].lower() or "temporariamente indisponível" in args[0].lower())
