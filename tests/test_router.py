"""Testes unitários para o Smart Router determinístico (Zero-LLM)."""
from datetime import date
import pytest
from sorge_gateway.router import (
    Intent,
    RouteType,
    calculate_next_weekday,
    normalize_text,
    route_message,
)

BASE_DATE = date(2026, 10, 20)  # Uma terça-feira (weekday = 1)

def test_normalize_text():
    assert normalize_text("  Agenda AMANHÃ!  ") == "agenda amanha!"
    assert normalize_text("Terça-Feira") == "terca-feira"

def test_calculate_next_weekday():
    # BASE_DATE é terça-feira (1)
    # Próxima terça (mesmo dia)
    assert calculate_next_weekday(1, BASE_DATE) == date(2026, 10, 20)
    # Próxima quarta (2) -> amanhã
    assert calculate_next_weekday(2, BASE_DATE) == date(2026, 10, 21)
    # Próxima sexta (4) -> 23/10/2026
    assert calculate_next_weekday(4, BASE_DATE) == date(2026, 10, 23)
    # Próxima segunda (0) -> 26/10/2026
    assert calculate_next_weekday(0, BASE_DATE) == date(2026, 10, 26)

def test_commands_routing():
    # Comandos básicos
    r = route_message("/start", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.START and not r.used_llm

    r = route_message("/status", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.STATUS and not r.used_llm

    r = route_message("/ajuda", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.HELP and not r.used_llm

    r = route_message("/uso", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.USAGE and not r.used_llm

    # Comandos de agenda
    r = route_message("/hoje", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.LIST_EVENTS
    assert r.target_date == BASE_DATE

    r = route_message("/amanha", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.LIST_EVENTS
    assert r.target_date == date(2026, 10, 21)

    r = route_message("/agenda hoje", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.LIST_EVENTS
    assert r.target_date == BASE_DATE

    r = route_message("/agenda amanha", BASE_DATE)
    assert r.route == RouteType.COMMAND and r.intent == Intent.LIST_EVENTS
    assert r.target_date == date(2026, 10, 21)

def test_deterministic_natural_language():
    # Hoje
    for phrase in ["hoje", "agenda hoje", "o que tenho hoje", "minha agenda hoje"]:
        r = route_message(phrase, BASE_DATE)
        assert r.route == RouteType.DETERMINISTIC
        assert r.intent == Intent.LIST_EVENTS
        assert r.target_date == BASE_DATE
        assert not r.used_llm

    # Amanhã
    for phrase in ["amanha", "amanhã", "agenda amanhã", "o que tenho amanha"]:
        r = route_message(phrase, BASE_DATE)
        assert r.route == RouteType.DETERMINISTIC
        assert r.intent == Intent.LIST_EVENTS
        assert r.target_date == date(2026, 10, 21)
        assert not r.used_llm

    # Dia da semana específico (ex: sexta-feira)
    for phrase in ["agenda sexta", "o que tenho sexta", "agenda de sexta"]:
        r = route_message(phrase, BASE_DATE)
        assert r.route == RouteType.DETERMINISTIC
        assert r.intent == Intent.LIST_EVENTS
        assert r.target_date == date(2026, 10, 23)
        assert not r.used_llm

    # Cancelar e Concluir ID
    r_cancel = route_message("cancelar 184", BASE_DATE)
    assert r_cancel.route == RouteType.DETERMINISTIC
    assert r_cancel.intent == Intent.CANCEL_EVENT
    assert r_cancel.target_id == 184

    r_done = route_message("feito 99", BASE_DATE)
    assert r_done.route == RouteType.DETERMINISTIC
    assert r_done.intent == Intent.COMPLETE_EVENT
    assert r_done.target_id == 99

def test_llm_fallback_routing():
    # Frases complexas ou ambíguas que devem seguir para LLM (OpenClaw na Fase 4)
    complex_phrases = [
        "quinta depois do almoço coloca uma reunião com o pessoal da fisio",
        "marca dentista amanhã às 14h",
        "semana que vem preciso lembrar de conversar com a Helena",
        "muda aquela consulta de terça para quinta de manhã"
    ]
    for phrase in complex_phrases:
        r = route_message(phrase, BASE_DATE)
        assert r.route == RouteType.LLM_FALLBACK
        assert r.intent == Intent.UNKNOWN
        assert r.used_llm is True
