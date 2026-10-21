"""Módulo de configuração do Sorge."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega variáveis do .env se existir
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Caminhos do sistema
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

# Garante que pastas locais existam
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Banco de dados
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "sorge.db")))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_allowed_user = os.getenv("TELEGRAM_ALLOWED_USER_ID")
TELEGRAM_ALLOWED_USER_ID = int(_allowed_user) if _allowed_user and _allowed_user.strip().isdigit() else None

# Fuso horário e logs
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Integrações futuras
N8N_WEBHOOK_BASE_URL = os.getenv("N8N_WEBHOOK_BASE_URL", "http://localhost:5678/webhook")
OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789/v1")
OPENCLAW_API_KEY = os.getenv("OPENCLAW_API_KEY", "")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "")
