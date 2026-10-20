# SORGE — Assistente Pessoal Local

Assistente pessoal local, econômico em tokens, acessado pelo Telegram e executado no próprio computador.

## Arquitetura (V1)

- **Interface:** Telegram Bot (long polling local, sem necessidade de IP público ou webhook).
- **Roteamento:** Smart Router determinístico (Zero-LLM) com fallback estruturado para LLM apenas quando estritamente necessário.
- **Automação:** n8n local conectado ao Google Calendar.
- **Banco de Dados:** SQLite local (`data/sorge.db`).

## Estrutura do Projeto

```text
sorge/
├── database/            # Schema e migrações SQLite
├── data/                # Banco de dados local e dados persistentes
├── logs/                # Logs estruturados e rotativos
├── sorge_gateway/       # Gateway Telegram, Smart Router e integrações
├── tests/               # Testes automatizados (pytest)
├── scripts/             # Scripts utilitários e de inicialização
└── systemd/             # Configurações do systemd --user
```

## Como Rodar

1. Crie o ambiente virtual e instale dependências:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure seu arquivo `.env` baseado no `.env.example`:
   ```bash
   cp .env.example .env
   ```

3. Execute os testes:
   ```bash
   pytest
   ```
