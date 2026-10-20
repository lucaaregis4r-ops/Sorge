"""Testes unitários para o gateway Telegram, autorização e deduplicação."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path
from sorge_gateway.database import init_db, is_update_processed
from sorge_gateway import telegram

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch):
    """Configura um banco SQLite limpo para cada teste."""
    test_db = tmp_path / "test_telegram.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=test_db, schema_path=schema_file)
    monkeypatch.setattr(telegram, "DATABASE_PATH", test_db)
    monkeypatch.setattr("sorge_gateway.database.DATABASE_PATH", test_db)
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
async def test_start_handler_unauthorized(monkeypatch):
    """Garante que mensagens de usuários não autorizados são ignoradas."""
    monkeypatch.setattr(telegram, "TELEGRAM_ALLOWED_USER_ID", 12345)

    update = MagicMock()
    update.effective_user.id = 99999
    update.update_id = 101
    context = MagicMock()

    await telegram.start_handler(update, context)

    # Não deve ter respondido
    update.message.reply_text.assert_not_called()
    # Não deve ter registrado como processado
    assert not is_update_processed(101)

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

    # Deve responder e registrar como processado
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
