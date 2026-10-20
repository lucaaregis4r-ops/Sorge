"""Módulo de integração com a Telegram Bot API via long polling."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from sorge_gateway.config import (
    DATABASE_PATH,
    TELEGRAM_ALLOWED_USER_ID,
    TELEGRAM_BOT_TOKEN,
    TIMEZONE,
)
from sorge_gateway.database import (
    get_db_connection,
    is_update_processed,
    mark_update_processed,
    record_usage,
)
from sorge_gateway.logger import log_event, logger

# Registro de timestamp de início do processo para cálculo de uptime
START_TIME = time.time()

def is_user_authorized(user_id: int | None) -> bool:
    """Verifica se o usuário é o proprietário autorizado do Sorge."""
    if TELEGRAM_ALLOWED_USER_ID is None:
        logger.warning("TELEGRAM_ALLOWED_USER_ID não configurado. Bloqueando mensagens por segurança.")
        return False
    return user_id == TELEGRAM_ALLOWED_USER_ID

def get_uptime_str() -> str:
    """Retorna uma string legível com o tempo em atividade do gateway."""
    seconds = int(time.time() - START_TIME)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

async def check_database_status() -> bool:
    """Verifica se a conexão com o SQLite está íntegra."""
    try:
        with get_db_connection(DATABASE_PATH) as conn:
            conn.execute("SELECT 1;")
            return True
    except Exception as e:
        logger.error(f"Falha de integridade no banco de dados: {e}")
        return False

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /start."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        logger.warning(f"Acesso não autorizado ignorado: user_id={update.effective_user.id if update.effective_user else 'None'}")
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        logger.info(f"Update duplicado ignorado: {update_id}")
        return

    mark_update_processed(update_id)
    record_usage(
        route="command",
        used_llm=False,
        intent="START",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="START", used_llm=False, status="success", update_id=update_id)

    texto = (
        "Olá. Eu sou o Sorge.\n\n"
        "Posso cuidar da sua agenda e dos seus lembretes locais.\n"
        "Digite /ajuda para ver os comandos ou /status para verificar a saúde do assistente."
    )
    await update.message.reply_text(texto)

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /status."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        logger.warning(f"Acesso não autorizado ignorado: user_id={update.effective_user.id if update.effective_user else 'None'}")
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        logger.info(f"Update duplicado ignorado: {update_id}")
        return

    mark_update_processed(update_id)
    db_ok = await check_database_status()
    uptime = get_uptime_str()

    record_usage(
        route="command",
        used_llm=False,
        intent="STATUS",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="STATUS", used_llm=False, status="success", update_id=update_id)

    status_db = "OK" if db_ok else "ERRO"
    texto = (
        "🟢 Sorge online (Modo Local)\n\n"
        f"• Telegram: OK (long polling)\n"
        f"• Banco SQLite: {status_db}\n"
        f"• n8n: Pendente (Fase 3)\n"
        f"• OpenClaw: Pendente (Fase 4)\n\n"
        f"⏱️ Ativo há: {uptime}\n"
        f"📍 Fuso horário: {TIMEZONE}"
    )
    await update.message.reply_text(texto)

async def generic_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador temporário para mensagens livres antes do Smart Router (Fase 2)."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    user_text = update.message.text if update.message else ""

    record_usage(
        route="fallback",
        used_llm=False,
        intent="UNKNOWN",
        telegram_update_id=update_id,
    )
    log_event(route="fallback", intent="UNKNOWN", used_llm=False, status="received", update_id=update_id)

    await update.message.reply_text(
        f"Recebi sua mensagem: '{user_text}'.\n"
        "O Smart Router determinístico será integrado na Fase 2."
    )

def build_application() -> Application:
    """Cria e configura a instância do Application do Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN não foi configurado no arquivo .env.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Comandos básicos da Fase 1
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("status", status_handler))

    # Handler para outras mensagens de texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generic_message_handler))

    return app
