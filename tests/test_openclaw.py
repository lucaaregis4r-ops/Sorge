"""Testes unitários para o intérprete de linguagem natural OpenClaw (Fase 4)."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from sorge_gateway.database import get_db_connection, init_db
from sorge_gateway.openclaw import (
    ActionType,
    OpenClawClient,
    ParsedIntent,
    clean_json_response,
    load_system_prompt,
)

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    test_db = tmp_path / "test_openclaw.db"
    schema_file = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    init_db(db_path=test_db, schema_path=schema_file)
    return test_db

def test_clean_json_response():
    # 1. JSON puro
    assert clean_json_response('{"action": "TEST"}') == '{"action": "TEST"}'

    # 2. Markdown ```json ... ```
    md_str = 'Aqui está:\n```json\n{"action": "CREATE_EVENT", "confidence": 0.95}\n```\nObrigado!'
    assert clean_json_response(md_str) == '{"action": "CREATE_EVENT", "confidence": 0.95}'

def test_parsed_intent_executability():
    # Executável: ação CREATE_EVENT, com data, título e confiança >= 0.70
    intent_ok = ParsedIntent(
        action=ActionType.CREATE_EVENT,
        title="Dentista",
        date="2026-10-22",
        time="14:00",
        confidence=0.92
    )
    assert intent_ok.is_executable() is True

    # Não executável por baixa confiança
    intent_low_conf = ParsedIntent(
        action=ActionType.CREATE_EVENT,
        title="Dentista",
        date="2026-10-22",
        confidence=0.55
    )
    assert intent_low_conf.is_executable() is False

    # Não executável por falta de título ou data
    intent_incomplete = ParsedIntent(
        action=ActionType.CREATE_EVENT,
        confidence=0.95
    )
    assert intent_incomplete.is_executable() is False

    # Desconhecido não é executável
    intent_unknown = ParsedIntent(
        action=ActionType.UNKNOWN,
        confidence=0.85
    )
    assert intent_unknown.is_executable() is False

def test_load_system_prompt():
    prompt = load_system_prompt()
    assert "Sorge" in prompt
    assert "CREATE_EVENT" in prompt

@pytest.mark.asyncio
async def test_interpret_message_success(temp_db: Path):
    """Testa chamada bem sucedida ao OpenClaw com parsing e gravação de telemetria."""
    client = OpenClawClient(
        api_key="mock_key",
        base_url="http://mock-openclaw/v1",
        model="gpt-4o-mini",
        db_path=temp_db
    )

    mock_llm_json = {
        "action": "CREATE_EVENT",
        "title": "Reunião de Equipe",
        "date": "2026-10-23",
        "time": "15:00",
        "duration_minutes": 60,
        "reminders": [120, 30],
        "confidence": 0.96
    }

    mock_resp = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(mock_llm_json)}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165
            }
        },
        request=httpx.Request("POST", "http://mock-openclaw/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        intent = await client.interpret_message(
            user_message="sexta às 15h coloca reunião de equipe",
            current_date_str="2026-10-20",
            update_id=901
        )

        assert intent.action == ActionType.CREATE_EVENT
        assert intent.title == "Reunião de Equipe"
        assert intent.date == "2026-10-23"
        assert intent.confidence == 0.96
        assert intent.is_executable() is True

        # Verifica gravação no SQLite usage_events
        with get_db_connection(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usage_events WHERE telegram_update_id = 901")
            row = cursor.fetchone()
            assert row is not None
            assert row["used_llm"] == 1
            assert row["total_tokens"] == 165
            assert row["model"] == "gpt-4o-mini"
            assert row["intent"] == "CREATE_EVENT"

@pytest.mark.asyncio
async def test_interpret_message_offline_fallback(temp_db: Path):
    """Testa fallback resiliente quando OpenClaw está offline."""
    client = OpenClawClient(
        base_url="http://offline-openclaw/v1",
        timeout=0.1,
        db_path=temp_db
    )

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Offline")):
        intent = await client.interpret_message(
            user_message="alguma frase qualquer",
            current_date_str="2026-10-20",
            update_id=902
        )

        assert intent.action == ActionType.UNKNOWN
        assert intent.confidence == 0.0
        assert intent.is_executable() is False
