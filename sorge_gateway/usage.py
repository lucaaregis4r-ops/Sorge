"""Módulo de estatísticas de uso, consumo de tokens e taxa Zero-LLM."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

from sorge_gateway import config
from sorge_gateway.database import get_db_connection, get_db_path

def get_usage_statistics(db_path: Optional[Path] = None, period: str = "hoje") -> Dict[str, Any]:
    """
    Calcula estatísticas de uso a partir da tabela usage_events para o período especificado:
    - 'hoje': dia atual
    - 'semana': desde a segunda-feira da semana atual
    - 'mes': desde o primeiro dia do mês atual
    - 'total': histórico completo
    """
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    target_db = get_db_path(db_path)
    period_lower = period.lower()

    if period_lower == "hoje":
        start_filter = now.strftime("%Y-%m-%d")
        query_condition = "created_at >= ?"
        query_params = (f"{start_filter}T00:00:00",)
    elif period_lower in ("semana", "week"):
        start_of_week = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        query_condition = "created_at >= ?"
        query_params = (f"{start_of_week}T00:00:00",)
    elif period_lower in ("mes", "mês", "month"):
        start_of_month = now.strftime("%Y-%m-01")
        query_condition = "created_at >= ?"
        query_params = (f"{start_of_month}T00:00:00",)
    else:
        query_condition = "1=1"
        query_params = ()

    with get_db_connection(target_db) as conn:
        cursor = conn.cursor()

        # Totais gerais
        cursor.execute(
            f"""
            SELECT 
                COUNT(*) as total_messages,
                SUM(CASE WHEN used_llm = 0 THEN 1 ELSE 0 END) as zero_llm_total,
                SUM(CASE WHEN used_llm = 1 THEN 1 ELSE 0 END) as llm_calls_total,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost_usd
            FROM usage_events
            WHERE {query_condition}
            """,
            query_params
        )
        row = cursor.fetchone()

        total = row["total_messages"] or 0
        zero_llm = row["zero_llm_total"] or 0
        llm_calls = row["llm_calls_total"] or 0
        input_tokens = row["total_input_tokens"] or 0
        output_tokens = row["total_output_tokens"] or 0
        tokens_sum = row["total_tokens"] or 0
        cost_usd = row["total_cost_usd"] or 0.0

        zero_llm_rate = (zero_llm / total * 100.0) if total > 0 else 100.0
        llm_rate = (llm_calls / total * 100.0) if total > 0 else 0.0

        # Modelo mais utilizado
        cursor.execute(
            f"""
            SELECT model, COUNT(*) as count
            FROM usage_events
            WHERE {query_condition} AND model IS NOT NULL
            GROUP BY model
            ORDER BY count DESC
            LIMIT 1
            """,
            query_params
        )
        model_row = cursor.fetchone()
        top_model = model_row["model"] if model_row else "Nenhum (100% Determinístico)"

    return {
        "period": period_lower,
        "total_messages": total,
        "zero_llm_total": zero_llm,
        "llm_calls_total": llm_calls,
        "zero_llm_rate": zero_llm_rate,
        "llm_rate": llm_rate,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": tokens_sum,
        "top_model": top_model,
        "estimated_cost_usd": cost_usd
    }

def format_usage_report(stats: Dict[str, Any]) -> str:
    """Formata o relatório de uso conforme especificado na Seção 9 do plano."""
    p = stats.get("period", "hoje").lower()
    if p == "hoje":
        periodo_str = "HOJE"
    elif p in ("semana", "week"):
        periodo_str = "ESTA SEMANA"
    elif p in ("mes", "mês", "month"):
        periodo_str = "ESTE MÊS"
    else:
        periodo_str = "TOTAL ACUMULADO"

    return (
        f"📊 SORGE — USO {periodo_str}\n\n"
        f"Mensagens processadas: {stats['total_messages']}\n"
        f"Sem LLM: {stats['zero_llm_total']} ({stats['zero_llm_rate']:.1f}%)\n"
        f"Com LLM: {stats['llm_calls_total']} ({stats['llm_rate']:.1f}%)\n\n"
        f"Tokens de entrada: {stats['input_tokens']:,}\n"
        f"Tokens de saída: {stats['output_tokens']:,}\n"
        f"Total: {stats['total_tokens']:,}\n\n"
        f"Modelo mais usado: {stats['top_model']}\n"
        f"Custo estimado: US$ {stats['estimated_cost_usd']:.2f}\n\n"
        f"⚡ Zero-LLM Rate: {stats['zero_llm_rate']:.1f}% resolvidas sem IA"
    )
