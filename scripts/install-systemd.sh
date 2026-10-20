#!/usr/bin/env bash
# ==============================================================================
# Sorge - Instalador do Serviço systemd --user
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_SRC="$PROJECT_DIR/systemd/sorge.service"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "=== Instalando Sorge como Serviço systemd --user ==="

# 1. Cria o diretório do systemd do usuário caso não exista
mkdir -p "$USER_SYSTEMD_DIR"

# 2. Copia o arquivo .service
echo "Copiando sorge.service para $USER_SYSTEMD_DIR..."
cp "$SERVICE_SRC" "$USER_SYSTEMD_DIR/sorge.service"

# 3. Recarrega o daemon do systemd
echo "Recarregando systemd --user..."
systemctl --user daemon-reload

# 4. Habilita para iniciar automaticamente no login do usuário
echo "Habilitando inicialização automática (enable)..."
systemctl --user enable sorge.service

echo ""
echo "✅ Serviço sorge.service instalado com sucesso!"
echo ""
echo "Comandos úteis:"
echo "• Iniciar serviço agora:       systemctl --user start sorge.service"
echo "• Parar serviço:               systemctl --user stop sorge.service"
echo "• Ver status do serviço:       systemctl --user status sorge.service"
echo "• Ver logs em tempo real:      journalctl --user -u sorge.service -f"
echo "• Desabilitar inicialização:   systemctl --user disable sorge.service"
