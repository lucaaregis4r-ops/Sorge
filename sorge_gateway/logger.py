"""Configuração de logging centralizado para o Sorge."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from sorge_gateway.config import LOGS_DIR, LOG_LEVEL, TIMEZONE

def setup_logger(name: str = "sorge") -> logging.Logger:
    """Configura e retorna o logger da aplicação com handlers de console e arquivo."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Evita duplicação de handlers caso a função seja chamada múltiplas vezes
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. File Handler para logs gerais (logs/sorge.log)
    sorge_log_path = LOGS_DIR / "sorge.log"
    file_handler = RotatingFileHandler(
        sorge_log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 3. File Handler específico para erros (logs/error.log)
    error_log_path = LOGS_DIR / "error.log"
    error_handler = RotatingFileHandler(
        error_log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger

logger = setup_logger()

def log_event(route: str, intent: str, used_llm: bool, status: str, latency_ms: int = 0, update_id: int | None = None) -> None:
    """Registra um evento operacional estruturado de acordo com o plano."""
    now = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    msg = (
        f"event=operation now={now} update_id={update_id} route={route} "
        f"intent={intent} llm={used_llm} status={status} latency_ms={latency_ms}"
    )
    logger.info(msg)
