"""Módulo do OpenClaw como intérprete estruturado de linguagem natural (Fase 4)."""
import json
import os
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field, ValidationError

from sorge_gateway.config import (
    BASE_DIR,
    DATABASE_PATH,
    OPENCLAW_API_KEY,
    OPENCLAW_BASE_URL,
    OPENCLAW_MODEL,
    TIMEZONE,
)
from sorge_gateway.database import record_usage
from sorge_gateway.logger import logger

class ActionType(str, Enum):
    CREATE_EVENT = "CREATE_EVENT"
    LIST_EVENTS = "LIST_EVENTS"
    UPDATE_EVENT = "UPDATE_EVENT"
    CANCEL_EVENT = "CANCEL_EVENT"
    REMINDER = "REMINDER"
    UNKNOWN = "UNKNOWN"

class ParsedIntent(BaseModel):
    """Schema Pydantic estrito para saída do modelo de raciocínio."""
    action: ActionType = ActionType.UNKNOWN
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    duration_minutes: Optional[int] = 60
    reminders: List[int] = Field(default_factory=lambda: [120, 30])
    target_id: Optional[int] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    clarification_needed: Optional[str] = None

    def is_executable(self, min_confidence: float = 0.70) -> bool:
        """Determina se a intenção possui confiança suficiente para execução sem ambiguidade."""
        if self.confidence < min_confidence:
            return False
        if self.action == ActionType.UNKNOWN:
            return False
        if self.action == ActionType.CREATE_EVENT and not (self.title and self.date):
            return False
        return True

def load_system_prompt() -> str:
    """Carrega o prompt estruturado de interpretação de prompts/intent-parser.md."""
    prompt_file = BASE_DIR / "prompts" / "intent-parser.md"
    if prompt_file.exists():
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    return "Você é um interpretador de intenções em português para calendário. Retorne JSON estruturado."

def clean_json_response(raw_response: str) -> str:
    """Extrai objeto JSON de uma resposta do modelo, removendo delimitadores markdown se presentes."""
    text = raw_response.strip()
    # Se estiver em bloco de código ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Busca primeiro e último colchetes {}
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    return text

class OpenClawClient:
    """Cliente para interpretar frases através do OpenClaw / LLM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 10.0,
        db_path: Optional[Path] = None
    ):
        self.api_key = api_key or OPENCLAW_API_KEY
        self.base_url = base_url or OPENCLAW_BASE_URL
        self.model = model or OPENCLAW_MODEL or "openai/gpt-6-astra"
        self.timeout = timeout
        self.db_path = db_path
        self.system_prompt = load_system_prompt()

    async def interpret_message(
        self,
        user_message: str,
        current_date_str: str,
        update_id: Optional[int] = None
    ) -> ParsedIntent:
        """
        Envia a mensagem ao OpenClaw com contexto mínimo (data atual e fuso)
        e valida o schema retornado via Pydantic.
        """
        # Contexto mínimo rigoroso
        context_msg = (
            f"Data de hoje: {current_date_str} (fuso {TIMEZONE}).\n"
            f"Mensagem do usuário: \"{user_message}\""
        )

        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": context_msg}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        # Tentativa de chamada HTTP para o provedor
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)
                    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

                    # Estimativa de custo para gpt-4o-mini ($0.15 / 1M in, $0.60 / 1M out)
                    cost = (input_tokens * 0.00000015) + (output_tokens * 0.00000060)

                    cleaned_json = clean_json_response(raw_content)
                    parsed_dict = json.loads(cleaned_json)
                    intent = ParsedIntent(**parsed_dict)

                    record_usage(
                        route="openclaw",
                        used_llm=True,
                        provider="openclaw",
                        model=self.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        estimated_cost_usd=cost,
                        intent=intent.action.value,
                        telegram_update_id=update_id,
                        db_path=self.db_path
                    )

                    return intent
        except Exception as e:
            logger.warning(f"Chamada ao OpenClaw falhou ou offline ({e}).")

        # Fallback offline seguro para teste ou ausência de modelo
        fallback_intent = ParsedIntent(
            action=ActionType.UNKNOWN,
            confidence=0.0,
            clarification_needed="Serviço de IA temporariamente indisponível para interpretar frases livres."
        )
        record_usage(
            route="openclaw_fallback",
            used_llm=False,
            provider="local",
            model="fallback",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            intent=ActionType.UNKNOWN.value,
            telegram_update_id=update_id,
            db_path=self.db_path
        )
        return fallback_intent

default_openclaw_client = OpenClawClient()
