"""Gerenciamento de conexão e operações do banco de dados SQLite."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional
from zoneinfo import ZoneInfo

from sorge_gateway.config import DATABASE_PATH, SCHEMA_PATH, TIMEZONE
from sorge_gateway.logger import logger

def init_db(db_path: Path = DATABASE_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    """Inicializa as tabelas do banco de dados a partir do arquivo schema.sql."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        conn.commit()
    logger.info(f"Banco de dados inicializado em {db_path}")

@contextmanager
def get_db_connection(db_path: Path = DATABASE_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager para conexão com o banco de dados com suporte a dicionários (row_factory)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro em transação com banco de dados: {e}")
        raise
    finally:
        conn.close()

# --- Funções para deduplicação de mensagens (processed_updates) ---

def is_update_processed(update_id: int, db_path: Path = DATABASE_PATH) -> bool:
    """Verifica se um telegram update_id já foi processado anteriormente."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM processed_updates WHERE telegram_update_id = ?", (update_id,))
        return cursor.fetchone() is not None

def mark_update_processed(update_id: int, db_path: Path = DATABASE_PATH) -> None:
    """Marca um update_id como processado no banco de dados."""
    now = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO processed_updates (telegram_update_id, processed_at) VALUES (?, ?)",
            (update_id, now)
        )

# --- Funções para telemetria de uso (usage_events) ---

def record_usage(
    route: str,
    used_llm: bool,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: Optional[float] = None,
    intent: Optional[str] = None,
    telegram_update_id: Optional[int] = None,
    db_path: Path = DATABASE_PATH
) -> int:
    """Registra uma transação ou evento de uso para o contador de tokens / telemetria."""
    now = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO usage_events (
                created_at, route, used_llm, provider, model,
                input_tokens, output_tokens, total_tokens,
                estimated_cost_usd, intent, telegram_update_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now, route, 1 if used_llm else 0, provider, model,
                input_tokens, output_tokens, total_tokens,
                estimated_cost_usd, intent, telegram_update_id
            )
        )
        return cursor.lastrowid
