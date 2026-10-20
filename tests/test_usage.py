"""Testes unitários para o módulo de estatísticas de uso e telemetria (Fase 7)."""
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

def test_usage_statistics_with_data_and_periods(temp_db: Path):
    # Registra 3 requisições sem LLM hoje
    for _ in range(3):
        record_usage(
            route="deterministic",
            used_llm=False,
            intent="LIST_EVENTS",
            db_path=temp_db
        )

    # Registra 1 requisição com LLM hoje
    record_usage(
        route="openclaw",
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

    # Teste período 'hoje'
    stats_today = get_usage_statistics(db_path=temp_db, period="hoje")
    assert stats_today["total_messages"] == 4
    assert stats_today["zero_llm_total"] == 3
    assert stats_today["llm_calls_total"] == 1
    assert stats_today["zero_llm_rate"] == 75.0
    assert stats_today["total_tokens"] == 200
    assert stats_today["top_model"] == "gpt-4o-mini"

    report_today = format_usage_report(stats_today)
    assert "SORGE — USO HOJE" in report_today
    assert "Sem LLM: 3 (75.0%)" in report_today
    assert "Total: 200" in report_today
    assert "Zero-LLM Rate: 75.0%" in report_today

    # Teste período 'semana'
    stats_week = get_usage_statistics(db_path=temp_db, period="semana")
    assert stats_week["total_messages"] == 4
    report_week = format_usage_report(stats_week)
    assert "SORGE — USO ESTA SEMANA" in report_week

    # Teste período 'mes'
    stats_month = get_usage_statistics(db_path=temp_db, period="mes")
    assert stats_month["total_messages"] == 4
    report_month = format_usage_report(stats_month)
    assert "SORGE — USO ESTE MÊS" in report_month

    # Teste período 'total'
    stats_total = get_usage_statistics(db_path=temp_db, period="total")
    assert stats_total["total_messages"] == 4
    report_total = format_usage_report(stats_total)
    assert "SORGE — USO TOTAL ACUMULADO" in report_total
