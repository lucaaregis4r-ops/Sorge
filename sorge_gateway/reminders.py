"""Módulo de agendamento, despacho periódico e catch-up offline de lembretes."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from sorge_gateway import config
from sorge_gateway.database import (
    create_reminder,
    get_due_reminders,
    get_pending_overdue_reminders,
    update_reminder_status,
)
from sorge_gateway.logger import logger

def schedule_reminders_for_event(
    event_id: int,
    start_at_iso: str,
    reminders_minutes: Optional[List[int]] = None,
    db_path: Optional[Path] = None
) -> List[int]:
    """
    Agenda lembretes locais para um evento com base nos minutos de antecedência.
    Padrão: 120 minutos (2 horas) e 30 minutos antes.
    """
    if reminders_minutes is None:
        reminders_minutes = [120, 30]

    try:
        dt_start = datetime.fromisoformat(start_at_iso)
    except Exception as e:
        logger.error(f"Data de início inválida para agendar lembrete ({start_at_iso}): {e}")
        return []

    created_ids = []
    for minutes in reminders_minutes:
        send_at = dt_start - timedelta(minutes=minutes)
        rem_id = create_reminder(
            event_id=event_id,
            send_at=send_at.isoformat(),
            channel="telegram",
            db_path=db_path
        )
        created_ids.append(rem_id)
        logger.info(f"Lembrete #{rem_id} agendado para {send_at.isoformat()} (evento #{event_id})")

    return created_ids

async def dispatch_due_reminders(
    bot: Any,
    chat_id: Optional[int],
    now_iso: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[dict]:
    """
    Busca lembretes vencidos pendentes (send_at <= agora) e envia via Telegram.
    """
    due_list = get_due_reminders(now_iso=now_iso, db_path=db_path)
    current_time_str = now_iso or datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    sent_reminders = []

    for rem in due_list:
        try:
            dt_start = datetime.fromisoformat(rem["start_at"])
            hora_str = dt_start.strftime("%H:%M")
            data_str = dt_start.strftime("%d/%m/%Y")
        except Exception:
            hora_str = rem["start_at"]
            data_str = ""

        texto = (
            "⏰ Lembrete de compromisso!\n\n"
            f"📌 {rem['title']}\n"
            f"📅 {data_str}\n"
            f"🕑 Horário: {hora_str}"
        )

        if bot and chat_id:
            try:
                await bot.send_message(chat_id=chat_id, text=texto)
            except Exception as e:
                logger.error(f"Erro ao enviar lembrete #{rem['id']} pelo Telegram: {e}")
                continue

        update_reminder_status(rem["id"], status="sent", sent_at=current_time_str, db_path=db_path)
        logger.info(f"Lembrete #{rem['id']} enviado com sucesso.")
        sent_reminders.append(rem)

    return sent_reminders

async def startup_catchup(
    bot: Any,
    chat_id: Optional[int],
    now_iso: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[dict]:
    """
    Executado na inicialização do Sorge.
    Identifica lembretes que venceram enquanto o sistema/PC esteve offline.
    """
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(ZoneInfo(config.TIMEZONE))
    now_str = now.isoformat()
    overdue_list = get_pending_overdue_reminders(now_iso=now_str, db_path=db_path)
    processed = []

    for rem in overdue_list:
        try:
            dt_send = datetime.fromisoformat(rem["send_at"])
            dt_start = datetime.fromisoformat(rem["start_at"])
        except Exception:
            update_reminder_status(rem["id"], status="expired", db_path=db_path)
            continue

        # Calcula atraso
        delay_seconds = int((now - dt_send).total_seconds())
        delay_minutes = max(1, delay_seconds // 60)

        # Se o evento já terminou há mais de 1 hora, considera expirado/perdido
        if (now - dt_start).total_seconds() > 3600:
            update_reminder_status(rem["id"], status="expired", sent_at=now_str, db_path=db_path)
            logger.info(f"Lembrete #{rem['id']} marcado como expirado (evento já finalizado há mais de 1h).")
            continue

        # Se o evento ainda não ocorreu ou ocorreu há poucos minutos, envia alerta atrasado
        hora_lembrete = dt_send.strftime("%H:%M")
        hora_evento = dt_start.strftime("%H:%M")
        
        texto = (
            "⚠️ Sorge ficou offline.\n\n"
            f"Você tinha um lembrete às {hora_lembrete}:\n"
            f"{rem['title']} — {hora_evento}\n\n"
            f"O lembrete está {delay_minutes} minutos atrasado."
        )

        if bot and chat_id:
            try:
                await bot.send_message(chat_id=chat_id, text=texto)
            except Exception as e:
                logger.error(f"Erro ao enviar aviso de catch-up do lembrete #{rem['id']}: {e}")
                continue

        update_reminder_status(rem["id"], status="late_sent", sent_at=now_str, db_path=db_path)
        logger.info(f"Lembrete #{rem['id']} enviado retroativamente (catch-up com {delay_minutes}m de atraso).")
        processed.append(rem)

    return processed

async def reminder_dispatcher_loop(bot: Any, chat_id: Optional[int], poll_interval: int = 30) -> None:
    """Loop em segundo plano que verifica e despacha lembretes periodicamente."""
    logger.info("Iniciando despachante periódico de lembretes...")
    while True:
        try:
            if chat_id:
                await dispatch_due_reminders(bot=bot, chat_id=chat_id)
        except Exception as e:
            logger.error(f"Erro no loop do dispatcher de lembretes: {e}")
        await asyncio.sleep(poll_interval)
