"""Testes para o módulo de banco de dados e schema do Sorge."""
import sqlite3
import pytest
from pathlib import Path
from sorge_gateway.database import (
    init_db,
    get_db_connection,
    is_update_processed,
    mark_update_processed,
    record_usage,
)

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture que fornece um banco de dados temporário inicializado."""
    db_file = tmp_path / "test_sorge.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=db_file, schema_path=schema_file)
    return db_file

def test_database_initialization(temp_db: Path):
    """Testa se todas as tabelas esperadas foram criadas corretamente."""
    expected_tables = {"events", "reminders", "usage_events", "processed_updates"}
    with get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cursor.fetchall()}
    
    assert expected_tables.issubset(tables)

def test_processed_updates_deduplication(temp_db: Path):
    """Testa marcação e verificação de deduplicação por telegram_update_id."""
    update_id = 987654
    assert not is_update_processed(update_id, db_path=temp_db)

    mark_update_processed(update_id, db_path=temp_db)
    assert is_update_processed(update_id, db_path=temp_db)

    # Inserção duplicada não deve lançar erro devido a INSERT OR IGNORE
    mark_update_processed(update_id, db_path=temp_db)
    assert is_update_processed(update_id, db_path=temp_db)

def test_record_usage(temp_db: Path):
    """Testa o registro de telemetria e contagem de tokens."""
    row_id = record_usage(
        route="deterministic",
        used_llm=False,
        provider=None,
        model=None,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        intent="STATUS",
        telegram_update_id=123,
        db_path=temp_db
    )
    assert row_id > 0

    with get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usage_events WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["route"] == "deterministic"
        assert row["used_llm"] == 0
        assert row["intent"] == "STATUS"
        assert row["total_tokens"] == 0
