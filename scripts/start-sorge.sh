#!/usr/bin/env bash
# ==============================================================================
# Sorge - Script de Inicialização Local
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.sorge.pid"
LOG_FILE="$PROJECT_DIR/logs/sorge.log"

cd "$PROJECT_DIR"

echo "=== Iniciando Sorge (Assistente Pessoal Local) ==="

# 1. Verifica se já está em execução
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️ O Sorge já está em execução (PID: $PID)."
        exit 0
    else
        echo "Removendo arquivo PID órfão..."
        rm -f "$PID_FILE"
    fi
fi

# 2. Verifica se o ambiente virtual existe
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "❌ Erro: Ambiente virtual .venv não encontrado em $PROJECT_DIR"
    echo "Execute: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 3. Verifica conectividade com a internet
echo "Verificando conexão com a internet..."
if ping -c 1 8.8.8.8 > /dev/null 2>&1 || ping -c 1 1.1.1.1 > /dev/null 2>&1; then
    echo "✅ Conexão com internet: OK"
else
    echo "⚠️ Aviso: Sem conexão com a internet. O Telegram responderá assim que a rede for restabelecida."
fi

# 4. Verifica status do n8n local
echo "Verificando serviço n8n..."
if curl -s http://localhost:5678/healthz > /dev/null 2>&1; then
    echo "✅ n8n ativo em http://localhost:5678"
else
    echo "⚠️ n8n não respondeu em http://localhost:5678. O Sorge usará fallback local SQLite."
fi

# 5. Garante que diretórios essenciais existam
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data"

# 6. Inicia o Sorge Gateway
if [ "$1" = "--foreground" ]; then
    echo "Iniciando em primeiro plano (Ctrl+C para sair)..."
    exec "$PROJECT_DIR/.venv/bin/python3" -m sorge_gateway.main
else
    echo "Iniciando em segundo plano..."
    nohup "$PROJECT_DIR/.venv/bin/python3" -m sorge_gateway.main >> "$LOG_FILE" 2>&1 &
    NEW_PID=$!
    echo "$NEW_PID" > "$PID_FILE"
    echo "✅ Sorge iniciado com sucesso (PID: $NEW_PID)"
    echo "📄 Logs disponíveis em: $LOG_FILE"
    echo "Para verificar status: ./scripts/status-sorge.sh"
    echo "Para encerrar: ./scripts/stop-sorge.sh"
fi
