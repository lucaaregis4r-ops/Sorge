#!/usr/bin/env bash
# ==============================================================================
# Sorge - Script de Diagnóstico e Status Local
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.sorge.pid"
DB_FILE="$PROJECT_DIR/data/sorge.db"

echo "=================================================="
echo "          DIAGNÓSTICO OPERACIONAL - SORGE         "
echo "=================================================="

# 1. Gateway Process Status
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "🟢 Sorge Gateway: ATIVO (PID: $PID)"
    else
        echo "🔴 Sorge Gateway: INATIVO (PID $PID não encontrado)"
    fi
else
    PIDS=$(pgrep -f "sorge_gateway.main" || true)
    if [ -n "$PIDS" ]; then
        echo "🟡 Sorge Gateway: ATIVO (sem PID file, PIDs: $PIDS)"
    else
        echo "⚪ Sorge Gateway: PARADO"
    fi
fi

# 2. SQLite Database Status
if [ -f "$DB_FILE" ]; then
    SIZE=$(du -h "$DB_FILE" | cut -f1)
    echo "🟢 Banco SQLite: OK ($DB_FILE - $SIZE)"
else
    echo "🔴 Banco SQLite: NÃO ENCONTRADO ($DB_FILE)"
fi

# 3. n8n Status
if curl -s http://localhost:5678/healthz > /dev/null 2>&1; then
    echo "🟢 n8n Local: ONLINE (http://localhost:5678)"
else
    echo "🟡 n8n Local: OFFLINE (Sorge operando em fallback SQLite)"
fi

# 4. Systemd User Service Status
if systemctl --user is-active --quiet sorge.service 2>/dev/null; then
    echo "🟢 Serviço systemd --user: ATIVO (sorge.service)"
else
    echo "⚪ Serviço systemd --user: INATIVO / NÃO INSTALADO"
fi

echo "=================================================="
