"""Módulo de integração com a Telegram Bot API via long polling, Smart Router e n8n."""
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
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
    get_upcoming_events,
    is_update_processed,
    mark_update_processed,
    record_usage,
)
from sorge_gateway.logger import log_event, logger
from sorge_gateway.n8n import default_n8n_client
from sorge_gateway.openclaw import ActionType, default_openclaw_client
from sorge_gateway.reminders import reminder_dispatcher_loop, startup_catchup
from sorge_gateway.router import Intent, RouteType, get_current_date, route_message
from sorge_gateway.usage import format_usage_report, get_usage_statistics

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

async def check_n8n_status() -> bool:
    """Verifica se a instância local do n8n está ativa."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get("http://localhost:5678/healthz")
            return res.status_code == 200
    except Exception:
        return False

def format_events_list(events: list[dict], title: str) -> str:
    """Formata lista de compromissos para exibição no Telegram."""
    if not events:
        return f"📅 {title}\nNenhum compromisso agendado."

    linhas = [f"📅 {title}:"]
    for ev in events:
        # Extrai horário se start_at tiver ISO timestamp
        start_raw = ev.get("start_at") or ev.get("start", "")
        hora_str = ""
        if "T" in str(start_raw):
            try:
                dt = datetime.fromisoformat(str(start_raw))
                hora_str = dt.strftime("%H:%M") + " - "
            except Exception:
                hora_str = ""
        ev_id = ev.get("id") or ev.get("calendar_event_id") or "?"
        linhas.append(f"• [#{ev_id}] {hora_str}{ev.get('title') or ev.get('summary', 'Compromisso')}")
    return "\n".join(linhas)

# --- Handlers de Comandos e Roteamento ---

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /start."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        logger.warning(f"Acesso não autorizado ignorado: user_id={update.effective_user.id if update.effective_user else 'None'}")
        return

    update_id = update.update_id
    if is_update_processed(update_id):
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
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    db_ok = await check_database_status()
    n8n_ok = await check_n8n_status()
    uptime = get_uptime_str()

    record_usage(
        route="command",
        used_llm=False,
        intent="STATUS",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="STATUS", used_llm=False, status="success", update_id=update_id)

    status_db = "OK" if db_ok else "ERRO"
    status_n8n = "OK" if n8n_ok else "Offline (fallback local)"
    texto = (
        "🟢 Sorge online (Modo Local)\n\n"
        f"• Telegram: OK (long polling)\n"
        f"• Banco SQLite: {status_db}\n"
        f"• n8n: {status_n8n}\n"
        f"• Smart Router: OK (Zero-LLM)\n"
        f"• OpenClaw: Pendente (Fase 4)\n\n"
        f"⏱️ Ativo há: {uptime}\n"
        f"📍 Fuso horário: {TIMEZONE}"
    )
    await update.message.reply_text(texto)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /ajuda."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    record_usage(
        route="command",
        used_llm=False,
        intent="HELP",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="HELP", used_llm=False, status="success", update_id=update_id)

    texto = (
        "🤖 Comandos disponíveis no Sorge:\n\n"
        "📅 Agenda:\n"
        "• /hoje ou 'agenda hoje' — Compromissos do dia\n"
        "• /amanha ou 'agenda amanhã' — Compromissos de amanhã\n"
        "• /agenda ou 'agenda sexta' — Consulta de agenda por dia\n"
        "• cancelar <id> — Cancela um compromisso (ex: cancelar 184)\n"
        "• feito <id> — Conclui um compromisso (ex: feito 184)\n\n"
        "📊 Métricas & Status:\n"
        "• /uso — Estatísticas de Zero-LLM e economia de tokens\n"
        "• /status — Diagnóstico e estado dos serviços\n"
        "• /ajuda — Esta mensagem de ajuda"
    )
    await update.message.reply_text(texto)

async def usage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /uso."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    record_usage(
        route="command",
        used_llm=False,
        intent="USAGE",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="USAGE", used_llm=False, status="success", update_id=update_id)

    stats = get_usage_statistics(DATABASE_PATH, period="hoje")
    relatorio = format_usage_report(stats)
    await update.message.reply_text(relatorio)

async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /hoje."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    cur_date = get_current_date()
    events = await default_n8n_client.list_events(cur_date.strftime("%Y-%m-%d"))

    record_usage(
        route="command",
        used_llm=False,
        intent="LIST_EVENTS",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="LIST_EVENTS", used_llm=False, status="success", update_id=update_id)

    msg = format_events_list(events, f"Agenda de Hoje ({cur_date.strftime('%d/%m/%Y')})")
    await update.message.reply_text(msg)

async def tomorrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /amanha."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    cur_date = get_current_date()
    tom_date = cur_date + timedelta(days=1)
    events = await default_n8n_client.list_events(tom_date.strftime("%Y-%m-%d"))

    record_usage(
        route="command",
        used_llm=False,
        intent="LIST_EVENTS",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="LIST_EVENTS", used_llm=False, status="success", update_id=update_id)

    msg = format_events_list(events, f"Agenda de Amanhã ({tom_date.strftime('%d/%m/%Y')})")
    await update.message.reply_text(msg)

async def agenda_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipulador do comando /agenda."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    user_text = update.message.text if update.message else ""
    route_res = route_message(user_text)

    if route_res.target_date:
        events = await default_n8n_client.list_events(route_res.target_date.strftime("%Y-%m-%d"))
        titulo = f"Agenda para {route_res.target_date.strftime('%d/%m/%Y')}"
    else:
        events = get_upcoming_events(limit=7, db_path=DATABASE_PATH)
        titulo = "Próximos compromissos"

    record_usage(
        route="command",
        used_llm=False,
        intent="LIST_EVENTS",
        telegram_update_id=update_id,
    )
    log_event(route="command", intent="LIST_EVENTS", used_llm=False, status="success", update_id=update_id)

    msg = format_events_list(events, titulo)
    await update.message.reply_text(msg)

async def smart_router_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roteador principal para mensagens livres via Smart Router (Zero-LLM) e n8n."""
    if not update.effective_user or not is_user_authorized(update.effective_user.id):
        return

    update_id = update.update_id
    if is_update_processed(update_id):
        return

    mark_update_processed(update_id)
    user_text = update.message.text if update.message else ""

    result = route_message(user_text)

    # 1. Rota de Ajuda determinística
    if result.intent == Intent.HELP:
        record_usage("deterministic", False, intent="HELP", telegram_update_id=update_id)
        log_event("deterministic", "HELP", False, "success", update_id=update_id)
        await help_handler(update, context)
        return

    # 2. Rota de Status determinística
    if result.intent == Intent.STATUS:
        record_usage("deterministic", False, intent="STATUS", telegram_update_id=update_id)
        log_event("deterministic", "STATUS", False, "success", update_id=update_id)
        await status_handler(update, context)
        return

    # 3. Rota de Uso determinística
    if result.intent == Intent.USAGE:
        record_usage("deterministic", False, intent="USAGE", telegram_update_id=update_id)
        log_event("deterministic", "USAGE", False, "success", update_id=update_id)
        await usage_handler(update, context)
        return

    # 4. Rota de Listagem de Eventos determinística (via n8n / SQLite)
    if result.intent == Intent.LIST_EVENTS:
        target = result.target_date or get_current_date()
        events = await default_n8n_client.list_events(target.strftime("%Y-%m-%d"))
        record_usage("deterministic", False, intent="LIST_EVENTS", telegram_update_id=update_id)
        log_event("deterministic", "LIST_EVENTS", False, "success", update_id=update_id)
        msg = format_events_list(events, f"Agenda para {target.strftime('%d/%m/%Y')}")
        await update.message.reply_text(msg)
        return

    # 5. Rota de Cancelar Evento determinística (via n8n / SQLite)
    if result.intent == Intent.CANCEL_EVENT and result.target_id:
        success = await default_n8n_client.delete_event(result.target_id)
        record_usage("deterministic", False, intent="CANCEL_EVENT", telegram_update_id=update_id)
        log_event("deterministic", "CANCEL_EVENT", False, "success" if success else "not_found", update_id=update_id)
        if success:
            await update.message.reply_text(f"✅ Compromisso #{result.target_id} cancelado com sucesso.")
        else:
            await update.message.reply_text(f"⚠️ Compromisso #{result.target_id} não encontrado ou já cancelado.")
        return

    # 6. Roteamento para OpenClaw (Linguagem Natural - Fase 5)
    cur_date = get_current_date()
    intent = await default_openclaw_client.interpret_message(
        user_message=user_text,
        current_date_str=cur_date.strftime("%Y-%m-%d"),
        update_id=update_id
    )

    if intent.is_executable(min_confidence=0.70):
        if intent.action == ActionType.CREATE_EVENT and intent.title and intent.date:
            hora_inicio_str = intent.time or "09:00"
            start_iso = f"{intent.date}T{hora_inicio_str}:00"
            dur = intent.duration_minutes or 60

            try:
                dt_start = datetime.fromisoformat(start_iso)
                dt_end = dt_start + timedelta(minutes=dur)
                data_formatada = dt_start.strftime("%d/%m/%Y")
                hora_formatada = f"{dt_start.strftime('%H:%M')}–{dt_end.strftime('%H:%M')}"
            except Exception:
                data_formatada = intent.date
                hora_formatada = hora_inicio_str

            await default_n8n_client.create_event(
                title=intent.title,
                start_at=start_iso,
                duration_minutes=dur,
                reminders_minutes=intent.reminders
            )

            resposta = (
                f"✅ {intent.title} marcado\n"
                f"📅 {data_formatada}\n"
                f"🕑 {hora_formatada}"
            )
            await update.message.reply_text(resposta)
            return

        elif intent.action == ActionType.LIST_EVENTS:
            target_str = intent.date or cur_date.strftime("%Y-%m-%d")
            events = await default_n8n_client.list_events(target_str)
            msg = format_events_list(events, f"Agenda para {target_str}")
            await update.message.reply_text(msg)
            return

        elif intent.action == ActionType.CANCEL_EVENT and intent.target_id:
            await default_n8n_client.delete_event(intent.target_id)
            await update.message.reply_text(f"✅ Compromisso #{intent.target_id} cancelado com sucesso.")
            return

    # Pedido de esclarecimento em caso de baixa confiança ou dados incompletos
    msg_clarification = (
        intent.clarification_needed
        or "🤔 Não consegui identificar com certeza todos os dados do compromisso (data ou título).\n"
           "Poderia reenviar especificando o dia e o horário? (Ex: 'marca dentista amanhã às 14h')"
    )
    await update.message.reply_text(msg_clarification)

async def on_post_init(app: Application) -> None:
    """Executa o startup catch-up e inicia o despachante periódico de lembretes."""
    if TELEGRAM_ALLOWED_USER_ID:
        import asyncio
        logger.info("Executando startup catch-up de lembretes...")
        await startup_catchup(bot=app.bot, chat_id=TELEGRAM_ALLOWED_USER_ID)
        asyncio.create_task(reminder_dispatcher_loop(bot=app.bot, chat_id=TELEGRAM_ALLOWED_USER_ID, poll_interval=30))

def build_application() -> Application:
    """Cria e configura a instância do Application do Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN não foi configurado no arquivo .env.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(on_post_init).build()

    # Comandos
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("ajuda", help_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("uso", usage_handler))
    app.add_handler(CommandHandler("hoje", today_handler))
    app.add_handler(CommandHandler("amanha", tomorrow_handler))
    app.add_handler(CommandHandler("amanhã", tomorrow_handler))
    app.add_handler(CommandHandler("agenda", agenda_handler))

    # Handler para todas as mensagens de texto naturais
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_router_message_handler))

    return app
