"""Gerenciamento de conexão e operações do banco de dados SQLite."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional
from zoneinfo import ZoneInfo

from sorge_gateway import config
from sorge_gateway.logger import logger

def get_db_path(db_path: Optional[Path] = None) -> Path:
    """Retorna o caminho do banco de dados fornecido ou o configurado dinamicamente."""
    return db_path if db_path is not None else config.DATABASE_PATH

def init_db(db_path: Optional[Path] = None, schema_path: Optional[Path] = None) -> None:
    """Inicializa as tabelas do banco de dados a partir do arquivo schema.sql."""
    target_db = get_db_path(db_path)
    target_schema = schema_path if schema_path is not None else config.SCHEMA_PATH

    target_db.parent.mkdir(parents=True, exist_ok=True)
    with open(target_schema, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with sqlite3.connect(target_db) as conn:
        conn.executescript(schema_sql)
        conn.commit()
    logger.info(f"Banco de dados inicializado em {target_db}")

@contextmanager
def get_db_connection(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager para conexão com o banco de dados com suporte a dicionários (row_factory)."""
    target_db = get_db_path(db_path)
    conn = sqlite3.connect(target_db)
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

def is_update_processed(update_id: int, db_path: Optional[Path] = None) -> bool:
    """Verifica se um telegram update_id já foi processado anteriormente."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM processed_updates WHERE telegram_update_id = ?", (update_id,))
        return cursor.fetchone() is not None

def mark_update_processed(update_id: int, db_path: Optional[Path] = None) -> None:
    """Marca um update_id como processado no banco de dados."""
    now = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
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
    db_path: Optional[Path] = None
) -> int:
    """Registra uma transação ou evento de uso para o contador de tokens / telemetria."""
    now = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
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

# --- Funções para gerenciamento de eventos (events) ---

def create_event(
    title: str,
    start_at: str,
    end_at: Optional[str] = None,
    calendar_event_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> int:
    """Cria um novo evento no banco de dados SQLite."""
    now = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (title, start_at, end_at, calendar_event_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (title, start_at, end_at, calendar_event_id, now, now)
        )
        return cursor.lastrowid

def get_events_for_date(target_date: str, db_path: Optional[Path] = None) -> list[dict]:
    """Retorna eventos ativos para uma data específica (YYYY-MM-DD)."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, start_at, end_at, status, calendar_event_id
            FROM events
            WHERE status = 'active' AND start_at LIKE ?
            ORDER BY start_at ASC
            """,
            (f"{target_date}%",)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_upcoming_events(limit: int = 10, db_path: Optional[Path] = None) -> list[dict]:
    """Retorna os próximos eventos ativos."""
    now = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, start_at, end_at, status, calendar_event_id
            FROM events
            WHERE status = 'active' AND start_at >= ?
            ORDER BY start_at ASC
            LIMIT ?
            """,
            (now, limit)
        )
        return [dict(row) for row in cursor.fetchall()]

def update_event_status(event_id: int, status: str, db_path: Optional[Path] = None) -> bool:
    """Atualiza o status de um evento (ex: 'cancelled', 'completed')."""
    now = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE events SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, event_id)
        )
        return cursor.rowcount > 0
