"""Testes unitários para o módulo de estatísticas de uso e telemetria."""
from pathlib import Path
import pytest
from sorge_gateway.database import init_db, record_usage
from sorge_gateway.usage import format_usage_report, get_usage_statistics

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_usage.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=db_file, schema_path=schema_file)
    return db_file

def test_usage_statistics_empty(temp_db: Path):
    stats = get_usage_statistics(db_path=temp_db)
    assert stats["total_messages"] == 0
    assert stats["zero_llm_rate"] == 100.0
    assert stats["total_tokens"] == 0

def test_usage_statistics_with_data(temp_db: Path):
    # Registra 3 requisições sem LLM
    for _ in range(3):
        record_usage(
            route="deterministic",
            used_llm=False,
            intent="LIST_EVENTS",
            db_path=temp_db
        )

    # Registra 1 requisição com LLM
    record_usage(
        route="llm_fallback",
        used_llm=True,
        provider="openclaw",
        model="gpt-4o-mini",
        input_tokens=150,
        output_tokens=50,
        total_tokens=200,
        estimated_cost_usd=0.001,
        intent="CREATE_EVENT",
        db_path=temp_db
    )

    stats = get_usage_statistics(db_path=temp_db)
    assert stats["total_messages"] == 4
    assert stats["zero_llm_total"] == 3
    assert stats["llm_calls_total"] == 1
    assert stats["zero_llm_rate"] == 75.0
    assert stats["total_tokens"] == 200
    assert stats["top_model"] == "gpt-4o-mini"
    assert stats["estimated_cost_usd"] == 0.001

    report = format_usage_report(stats)
    assert "SORGE — USO HOJE" in report
    assert "Sem LLM: 3 (75.0%)" in report
    assert "Total: 200" in report
