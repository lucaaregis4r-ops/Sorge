"""Módulo de integração com a Telegram Bot API via long polling, Smart Router e n8n."""
import asyncio
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
import telegram.error
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from sorge_gateway.config import (
    DATABASE_PATH,
    OPENCLAW_BASE_URL,
    TELEGRAM_ALLOWED_USER_ID,
    TELEGRAM_BOT_TOKEN,
    TIMEZONE,
)
from sorge_gateway.database import (
    get_db_connection,
    get_recent_conversation_history,
    get_upcoming_events,
    is_update_processed,
    mark_update_processed,
    record_usage,
    save_conversation_message,
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

async def check_openclaw_status() -> bool:
    """Verifica se a instância local do OpenClaw está ativa."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{OPENCLAW_BASE_URL}/models")
            return res.status_code == 200
    except Exception:
        return False

async def safe_reply(update: Update, text: str, user_id: int | None = None, max_retries: int = 3) -> bool:
    """Envia resposta ao Telegram com retry automático contra oscilações de rede."""
    for attempt in range(1, max_retries + 1):
        try:
            if update.message:
                await update.message.reply_text(text)
            elif update.effective_chat:
                await update.get_bot().send_message(chat_id=update.effective_chat.id, text=text)
            if user_id:
                save_conversation_message(user_id, "assistant", text)
            return True
        except (telegram.error.TimedOut, telegram.error.NetworkError) as err:
            logger.warning(f"Tentativa {attempt}/{max_retries} de envio ao Telegram falhou ({type(err).__name__}: {err}).")
            if attempt < max_retries:
                await asyncio.sleep(1.5 * attempt)
            else:
                logger.error(f"Falha definitiva ao enviar mensagem após {max_retries} tentativas: {err}")
                if user_id:
                    save_conversation_message(user_id, "assistant", text)
                return False
        except Exception as e:
            logger.error(f"Erro inesperado no envio de resposta ao Telegram: {e}")
            if user_id:
                save_conversation_message(user_id, "assistant", text)
            return False
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
    await safe_reply(update, texto)

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
    openclaw_ok = await check_openclaw_status()
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
    status_openclaw = "OK (GPT Luna)" if openclaw_ok else "Offline"
    texto = (
        "🟢 Sorge online (Modo Local)\n\n"
        f"• Telegram: OK (long polling)\n"
        f"• Banco SQLite: {status_db}\n"
        f"• n8n: {status_n8n}\n"
        f"• Smart Router: OK (Zero-LLM)\n"
        f"• OpenClaw (IA): {status_openclaw}\n\n"
        f"⏱️ Ativo há: {uptime}\n"
        f"📍 Fuso horário: {TIMEZONE}"
    )
    await safe_reply(update, texto)

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
    periodo = "hoje"
    if context.args and len(context.args) > 0:
        periodo = context.args[0].lower()

    stats = get_usage_statistics(DATABASE_PATH, period=periodo)
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
        periodo = result.period or "hoje"
        record_usage("deterministic", False, intent="USAGE", telegram_update_id=update_id)
        log_event("deterministic", "USAGE", False, "success", update_id=update_id)
        stats = get_usage_statistics(DATABASE_PATH, period=periodo)
        relatorio = format_usage_report(stats)
        await update.message.reply_text(relatorio)
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

    user_id = update.effective_user.id
    history = get_recent_conversation_history(user_id=user_id, limit=6)
    save_conversation_message(user_id, "user", user_text)

    # 6. Roteamento para OpenClaw (Linguagem Natural com histórico - Fase 5+)
    cur_date = get_current_date()
    intent = await default_openclaw_client.interpret_message(
        user_message=user_text,
        current_date_str=cur_date.strftime("%Y-%m-%d"),
        update_id=update_id,
        history=history
    )

    if intent.is_executable(min_confidence=0.70):
        if intent.action == ActionType.CREATE_EVENT:
            events_to_create = intent.get_events()
            if len(events_to_create) == 1:
                ev = events_to_create[0]
                hora_inicio_str = ev.time or "09:00"
                start_iso = f"{ev.date}T{hora_inicio_str}:00"
                dur = ev.duration_minutes or 60

                try:
                    dt_start = datetime.fromisoformat(start_iso)
                    dt_end = dt_start + timedelta(minutes=dur)
                    data_formatada = dt_start.strftime("%d/%m/%Y")
                    hora_formatada = f"{dt_start.strftime('%H:%M')}–{dt_end.strftime('%H:%M')}"
                except Exception:
                    data_formatada = ev.date
                    hora_formatada = hora_inicio_str

                await default_n8n_client.create_event(
                    title=ev.title,
                    start_at=start_iso,
                    duration_minutes=dur,
                    reminders_minutes=ev.reminders
                )

                resposta = (
                    f"✅ {ev.title} marcado\n"
                    f"📅 {data_formatada}\n"
                    f"🕑 {hora_formatada}"
                )
                await safe_reply(update, resposta, user_id=user_id)
                return

            elif len(events_to_create) > 1:
                summaries = []
                for ev in events_to_create:
                    hora_inicio_str = ev.time or "09:00"
                    start_iso = f"{ev.date}T{hora_inicio_str}:00"
                    dur = ev.duration_minutes or 60

                    try:
                        dt_start = datetime.fromisoformat(start_iso)
                        dt_end = dt_start + timedelta(minutes=dur)
                        data_formatada = dt_start.strftime("%d/%m/%Y")
                        hora_formatada = f"{dt_start.strftime('%H:%M')}–{dt_end.strftime('%H:%M')}"
                    except Exception:
                        data_formatada = ev.date
                        hora_formatada = hora_inicio_str

                    await default_n8n_client.create_event(
                        title=ev.title,
                        start_at=start_iso,
                        duration_minutes=dur,
                        reminders_minutes=ev.reminders
                    )
                    summaries.append(f"• {ev.title} — {data_formatada} às {hora_formatada}")

                resposta = (
                    f"✅ {len(events_to_create)} compromissos agendados com sucesso:\n"
                    + "\n".join(summaries)
                    + "\n🔔 Lembretes configurados para cada um!"
                )
                await safe_reply(update, resposta, user_id=user_id)
                return

        elif intent.action == ActionType.LIST_EVENTS:
            target_str = intent.date or cur_date.strftime("%Y-%m-%d")
            events = await default_n8n_client.list_events(target_str)
            msg = format_events_list(events, f"Agenda para {target_str}")
            await safe_reply(update, msg, user_id=user_id)
            return

        elif intent.action == ActionType.CANCEL_EVENT and intent.target_id:
            await default_n8n_client.delete_event(intent.target_id)
            resposta = f"✅ Compromisso #{intent.target_id} cancelado com sucesso."
            await safe_reply(update, resposta, user_id=user_id)
            return

    # Pedido de esclarecimento em caso de baixa confiança ou dados incompletos
    msg_clarification = (
        intent.clarification_needed
        or "🤔 Não consegui identificar com certeza todos os dados do compromisso (data ou título).\n"
           "Poderia reenviar especificando o dia e o horário? (Ex: 'marca dentista amanhã às 14h')"
    )
    await safe_reply(update, msg_clarification, user_id=user_id)

async def on_post_init(app: Application) -> None:
    """Executa o startup catch-up e inicia o despachante periódico de lembretes."""
    if TELEGRAM_ALLOWED_USER_ID:
        logger.info("Executando startup catch-up de lembretes...")
        await startup_catchup(bot=app.bot, chat_id=TELEGRAM_ALLOWED_USER_ID)
        asyncio.create_task(reminder_dispatcher_loop(bot=app.bot, chat_id=TELEGRAM_ALLOWED_USER_ID, poll_interval=30))

def build_application() -> Application:
    """Cria e configura a instância do Application do Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN não foi configurado no arquivo .env.")

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=20.0,
        pool_timeout=10.0,
    )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).post_init(on_post_init).build()

    # Comandos
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("ajuda", help_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("uso", usage_handler))
    app.add_handler(CommandHandler("hoje", today_handler))
    app.add_handler(CommandHandler("amanha", tomorrow_handler))
    app.add_handler(CommandHandler("agenda", agenda_handler))

    # Handler para todas as mensagens de texto naturais
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_router_message_handler))

    return app
