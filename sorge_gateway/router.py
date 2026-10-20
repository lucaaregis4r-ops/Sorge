"""Smart Router determinístico (Zero-LLM) para classificação de intenções."""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from sorge_gateway.config import TIMEZONE

class RouteType(str, Enum):
    COMMAND = "command"
    DETERMINISTIC = "deterministic"
    LLM_FALLBACK = "llm_fallback"

class Intent(str, Enum):
    START = "START"
    STATUS = "STATUS"
    HELP = "HELP"
    LIST_EVENTS = "LIST_EVENTS"
    CANCEL_EVENT = "CANCEL_EVENT"
    COMPLETE_EVENT = "COMPLETE_EVENT"
    USAGE = "USAGE"
    UNKNOWN = "UNKNOWN"

@dataclass
class RouterResult:
    route: RouteType
    intent: Intent
    used_llm: bool
    confidence: float
    target_date: Optional[date] = None
    target_id: Optional[int] = None
    period: Optional[str] = None
    original_text: str = ""

def normalize_text(text: str) -> str:
    """Remove acentos, converte para minúsculas e remove espaços extras."""
    text = text.lower().strip()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def get_current_date() -> date:
    """Retorna a data atual no fuso horário configurado."""
    return datetime.now(ZoneInfo(TIMEZONE)).date()

def calculate_next_weekday(target_weekday: int, current_date: Optional[date] = None) -> date:
    """
    Calcula a data do próximo dia da semana especificado (0 = segunda, 6 = domingo).
    Se o dia da semana for hoje, retorna hoje.
    """
    cur = current_date or get_current_date()
    days_ahead = (target_weekday - cur.weekday()) % 7
    return cur + timedelta(days=days_ahead)

WEEKDAY_MAP = {
    "segunda": 0, "seg": 0, "segunda-feira": 0,
    "terca": 1, "ter": 1, "terca-feira": 1,
    "quarta": 2, "qua": 2, "quarta-feira": 2,
    "quinta": 3, "qui": 3, "quinta-feira": 3,
    "sexta": 4, "sex": 4, "sexta-feira": 4,
    "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}

def route_message(raw_text: str, current_date: Optional[date] = None) -> RouterResult:
    """
    Classifica a mensagem recebida:
    1. Comandos diretos (/start, /agenda, /hoje, /amanha, /uso, /status, /ajuda)
    2. Padrões determinísticos por regex (agenda hoje, agenda sexta, cancelar 184, feito 184)
    3. Fallback para LLM / OpenClaw se não reconhecido deterministicamente.
    """
    text = raw_text.strip()
    cur_date = current_date or get_current_date()

    # 1. Comandos com barra (/)
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        if cmd == "/start":
            return RouterResult(RouteType.COMMAND, Intent.START, False, 1.0, original_text=raw_text)
        elif cmd == "/status":
            return RouterResult(RouteType.COMMAND, Intent.STATUS, False, 1.0, original_text=raw_text)
        elif cmd in ("/ajuda", "/help"):
            return RouterResult(RouteType.COMMAND, Intent.HELP, False, 1.0, original_text=raw_text)
        elif cmd == "/hoje":
            return RouterResult(RouteType.COMMAND, Intent.LIST_EVENTS, False, 1.0, target_date=cur_date, period="today", original_text=raw_text)
        elif cmd in ("/amanha", "/amanhã"):
            return RouterResult(RouteType.COMMAND, Intent.LIST_EVENTS, False, 1.0, target_date=cur_date + timedelta(days=1), period="tomorrow", original_text=raw_text)
        elif cmd == "/agenda":
            # Suporta argumentos como "/agenda amanha" ou apenas "/agenda"
            parts = text.split()
            if len(parts) > 1:
                arg = normalize_text(parts[1])
                if arg == "hoje":
                    return RouterResult(RouteType.COMMAND, Intent.LIST_EVENTS, False, 1.0, target_date=cur_date, period="today", original_text=raw_text)
                elif arg in ("amanha", "amanha"):
                    return RouterResult(RouteType.COMMAND, Intent.LIST_EVENTS, False, 1.0, target_date=cur_date + timedelta(days=1), period="tomorrow", original_text=raw_text)
            return RouterResult(RouteType.COMMAND, Intent.LIST_EVENTS, False, 1.0, target_date=cur_date, period="upcoming", original_text=raw_text)
        elif cmd == "/uso":
            parts = text.split()
            p = "hoje"
            if len(parts) > 1:
                arg = normalize_text(parts[1])
                if arg in ("semana", "week"):
                    p = "semana"
                elif arg in ("mes", "month"):
                    p = "mes"
                elif arg in ("total", "tudo"):
                    p = "total"
                elif arg == "hoje":
                    p = "hoje"
            return RouterResult(RouteType.COMMAND, Intent.USAGE, False, 1.0, period=p, original_text=raw_text)

    # 2. Padrões determinísticos em linguagem natural
    norm = normalize_text(text)

    # Cancelar evento (ex: "cancelar 184", "cancela 184")
    m_cancel = re.fullmatch(r"(?:cancelar|cancela)\s+(\d+)", norm)
    if m_cancel:
        return RouterResult(
            RouteType.DETERMINISTIC,
            Intent.CANCEL_EVENT,
            False,
            1.0,
            target_id=int(m_cancel.group(1)),
            original_text=raw_text
        )

    # Concluir evento / tarefa (ex: "feito 184", "concluir 184", "concluido 184")
    m_done = re.fullmatch(r"(?:feito|concluir|concluido)\s+(\d+)", norm)
    if m_done:
        return RouterResult(
            RouteType.DETERMINISTIC,
            Intent.COMPLETE_EVENT,
            False,
            1.0,
            target_id=int(m_done.group(1)),
            original_text=raw_text
        )

    # Comandos em texto puro
    if norm in ("ajuda", "help", "socorro"):
        return RouterResult(RouteType.DETERMINISTIC, Intent.HELP, False, 1.0, original_text=raw_text)
    if norm in ("status", "estado"):
        return RouterResult(RouteType.DETERMINISTIC, Intent.STATUS, False, 1.0, original_text=raw_text)

    # Uso / telemetria em texto puro
    m_usage = re.fullmatch(r"(?:uso|tokens|consumo)(?:\s+(hoje|semana|mes|total))?", norm)
    if m_usage:
        p = m_usage.group(1) or "hoje"
        return RouterResult(RouteType.DETERMINISTIC, Intent.USAGE, False, 1.0, period=p, original_text=raw_text)

    # Consultas de agenda determinísticas
    # Ex: "hoje", "agenda hoje", "o que tenho hoje", "minha agenda hoje", "compromissos hoje"
    if re.fullmatch(r"(?:(?:o\s+que\s+tenho|minha\s+agenda|agenda|compromissos)\s+)?hoje", norm):
        return RouterResult(
            RouteType.DETERMINISTIC,
            Intent.LIST_EVENTS,
            False,
            1.0,
            target_date=cur_date,
            period="today",
            original_text=raw_text
        )

    # Ex: "amanha", "agenda amanha", "o que tenho amanha", "minha agenda amanha"
    if re.fullmatch(r"(?:(?:o\s+que\s+tenho|minha\s+agenda|agenda|compromissos)\s+)?amanha", norm):
        return RouterResult(
            RouteType.DETERMINISTIC,
            Intent.LIST_EVENTS,
            False,
            1.0,
            target_date=cur_date + timedelta(days=1),
            period="tomorrow",
            original_text=raw_text
        )

    # Ex: "agenda", "minha agenda", "proximos compromissos", "agenda da semana"
    if norm in ("agenda", "minha agenda", "proximos compromissos", "agenda da semana"):
        return RouterResult(
            RouteType.DETERMINISTIC,
            Intent.LIST_EVENTS,
            False,
            1.0,
            target_date=cur_date,
            period="upcoming",
            original_text=raw_text
        )

    # Ex: "agenda sexta", "o que tenho segunda", "agenda de quarta"
    m_weekday = re.fullmatch(r"(?:(?:o\s+que\s+tenho|minha\s+agenda|agenda|compromissos)(?:\s+de|\s+para)?\s+)([a-z-]+)", norm)
    if m_weekday:
        day_str = m_weekday.group(1)
        if day_str in WEEKDAY_MAP:
            target_dt = calculate_next_weekday(WEEKDAY_MAP[day_str], cur_date)
            return RouterResult(
                RouteType.DETERMINISTIC,
                Intent.LIST_EVENTS,
                False,
                1.0,
                target_date=target_dt,
                period="weekday",
                original_text=raw_text
            )

    # 3. Se não reconhecido deterministicamente, encaminha para LLM Fallback (Fase 4 - OpenClaw)
    return RouterResult(
        route=RouteType.LLM_FALLBACK,
        intent=Intent.UNKNOWN,
        used_llm=True,
        confidence=0.0,
        original_text=raw_text
    )
