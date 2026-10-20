#!/usr/bin/env bash
# ==============================================================================
# Sorge - Script de Parada Local
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.sorge.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "ℹ️ O Sorge não parece estar em execução (arquivo $PID_FILE não encontrado)."
    # Tenta localizar processos python do sorge_gateway caso tenham sido iniciados sem PID file
    PIDS=$(pgrep -f "sorge_gateway.main" || true)
    if [ -n "$PIDS" ]; then
        echo "Processos residuais encontrados: $PIDS. Encerrando..."
        kill -15 $PIDS 2>/dev/null || true
    fi
    exit 0
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
    echo "Encerrando Sorge (PID: $PID)..."
    kill -15 "$PID" 2>/dev/null || true
    
    # Aguarda encerramento gracioso (até 5 segundos)
    for i in {1..5}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    # Força encerramento se ainda estiver rodando
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Forçando encerramento (SIGKILL)..."
        kill -9 "$PID" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    echo "✅ Sorge encerrado com sucesso."
else
    echo "O processo $PID não estava em execução. Removendo arquivo PID antigo."
    rm -f "$PID_FILE"
fi
