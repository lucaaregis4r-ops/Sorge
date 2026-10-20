"""Ponto de entrada principal para execução do sorge-gateway local."""
import sys
from sorge_gateway.config import TELEGRAM_ALLOWED_USER_ID, TELEGRAM_BOT_TOKEN
from sorge_gateway.database import init_db
from sorge_gateway.logger import logger
from sorge_gateway.telegram import build_application

def main() -> None:
    """Inicia os serviços locais do Sorge."""
    logger.info("=== Iniciando Sorge Gateway (Local / V1) ===")

    # Garante que as tabelas estejam criadas
    init_db()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("ERRO: TELEGRAM_BOT_TOKEN não encontrado no ambiente (.env).")
        print("\n[!] Por favor, configure o TELEGRAM_BOT_TOKEN no seu arquivo .env para iniciar o bot.")
        print("[!] Consulte o arquivo .env.example para mais detalhes.\n")
        sys.exit(1)

    if TELEGRAM_ALLOWED_USER_ID is None:
        logger.warning("ATENÇÃO: TELEGRAM_ALLOWED_USER_ID não foi definido. Nenhuma mensagem será aceita.")
        print("\n[!] TELEGRAM_ALLOWED_USER_ID não configurado. Por segurança, o bot ignorará mensagens.")
        print("[!] Adicione seu ID do Telegram no .env para permitir seus comandos.\n")

    logger.info("Construindo aplicação Telegram Bot...")
    app = build_application()

    logger.info("Iniciando long polling com o Telegram (pressione Ctrl+C para encerrar)...")
    try:
        app.run_polling(drop_pending_updates=False)
    except KeyboardInterrupt:
        logger.info("Gateway encerrado pelo usuário via teclado.")
    except Exception as e:
        logger.error(f"Erro fatal durante execução do gateway: {e}")
        raise
    finally:
        logger.info("=== Sorge Gateway finalizado ===")

if __name__ == "__main__":
    main()
