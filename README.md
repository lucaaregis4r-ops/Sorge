# 🧠 SORGE — Assistente Pessoal Local Inteligente & Econômico em Tokens

> **SORGE** é um assistente pessoal local executado inteiramente no seu próprio computador (Linux/macOS), integrado ao **Telegram**, focado em **máxima privacidade**, **agilidade** e **economia extrema de tokens de IA**.

---

## 🚀 Destaques e Diferenciais

- ⚡ **Smart Router Determinístico (Zero-LLM):** Comandos comuns (`/agenda`, `/hoje`, `/amanha`, `/status`, `/ajuda`) e consultas de data/horário são processados **instantaneamente em < 5ms sem gastar 1 único token** de IA.
- 🤖 **Intérprete com OpenClaw / LLM:** Frases livres e agendamentos complexos são interpretados por modelos locais ou via gateway OpenClaw (ex: GPT Luna, Astra, Ollama ou endpoints OpenAI-compatíveis), retornando **JSON estruturado estrito via Pydantic**.
- 💬 **Memória Conversacional (Multi-Turn):** O assistente mantém o contexto das últimas mensagens, permitindo confirmações naturais em linguagem corrente (*"Sim"*, *"Desejo"*, *"Confirmo"*, *"Isso mesmo"*).
- 📋 **Agendamento em Lote (Batch):** Capacidade de interpretar e agendar múltiplos compromissos em uma única mensagem (ex: *"Pedro quinta às 20h30; Antonela sábado às 10h; Bento sábado às 11h"*).
- 🔄 **Integração com n8n & Google Calendar:** Criação, listagem e cancelamento assíncrono via workflows locais no n8n.
- 🛡️ **Resiliência Offline Total:** Se o n8n ou o Google Calendar estiverem inacessíveis, o Sorge realiza **fallback transparente para o banco SQLite local** sem interromper o usuário.
- ⏰ **Agendador de Lembretes Proporcionais:** Disparo de notificações automáticas via Telegram com mecanismo de **Startup Catch-up** (se o computador estava desligado na hora do compromisso, o lembrete pendente é notificado assim que o sistema inicia).
- 📊 **Telemetria de Tokens & Custo em Tempo Real:** Acompanhe a economia gerada via `/uso hoje`, `/uso semana`, `/uso mes` ou `/uso total` com cálculo da taxa Zero-LLM (ex: 85%+ de economia).
- 🔒 **Acesso Restrito:** Bloqueio automático de qualquer usuário que não corresponda ao `TELEGRAM_ALLOWED_USER_ID` configurado.

---

## 🏗️ Arquitetura do Sistema

```
                      ┌───────────────────────┐
                      │   Usuário (Telegram)  │
                      └──────────┬────────────┘
                                 │ Long Polling
                                 ▼
                   ┌─────────────────────────────┐
                   │        SORGE GATEWAY        │
                   │   (FastAPI / Python Async)  │
                   └──────┬───────────────┬──────┘
                          │               │
        [Comandos / Regex]│               │[Linguagem Natural Livre]
                          ▼               ▼
                 ┌────────────────┐   ┌───────────────────────┐
                 │  Smart Router  │   │     OpenClaw / LLM    │
                 │   (Zero-LLM)   │   │(GPT Luna / Pydantic)  │
                 └────────┬───────┘   └───────────┬───────────┘
                          │                       │
                          └───────────┬───────────┘
                                      ▼
                   ┌──────────────────────────────────────┐
                   │       Hub de Execução e Fallback     │
                   └──────────┬────────────────┬──────────┘
                              │                │
            [Normal / Online] │                │ [Offline Fallback]
                              ▼                ▼
                 ┌──────────────────────┐  ┌────────────────────┐
                 │  n8n Local (Docker)  │  │    SQLite Local    │
                 │   Google Calendar    │  │   (data/sorge.db)  │
                 └──────────────────────┘  └────────────────────┘
```

---

## 📁 Estrutura de Diretórios

```text
Sorge/
├── database/            # Schema DDL e migrações SQLite (events, reminders, usage, history)
├── data/                # Banco de dados local sorge.db (ignorado no Git)
├── logs/                # Logs rotativos estruturados sorge.log / error.log
├── n8n/                 # Templates JSON exportáveis dos workflows WF-01 a WF-07
├── prompts/             # Prompts de sistema com validação JSON estrita (intent-parser.md)
├── scripts/             # Scripts operacionais (start, stop, status, install-systemd)
├── sorge_gateway/       # Código-fonte principal da aplicação
│   ├── config.py        # Carregador de variáveis de ambiente
│   ├── database.py      # Camada de persistência SQLite e histórico conversacional
│   ├── logger.py        # Logger com rotação e formatação estruturada
│   ├── main.py          # Ponto de entrada do serviço
│   ├── n8n.py           # Cliente assíncrono para webhooks do n8n
│   ├── openclaw.py      # Intérprete estruturado e cliente OpenClaw / OpenAI
│   ├── reminders.py     # Agendador de lembretes e startup catch-up
│   ├── router.py        # Smart Router determinístico (Zero-LLM)
│   ├── telegram.py      # Bot Telegram, deduplicação e roteamento de mensagens
│   └── usage.py         # Cálculo de estatísticas e telemetria de tokens
├── systemd/             # Unit file do systemd --user para execução como serviço
├── tests/               # Suíte completa de testes automatizados com pytest (37 testes)
├── .env.example         # Modelo de variáveis de ambiente
└── requirements.txt     # Dependências Python
```

---

## ⚙️ Pré-requisitos

1. **Python 3.12+** instalado.
2. **Bot no Telegram:** Crie um bot gratuito via [@BotFather](https://t.me/BotFather) e pegue o token. Obtenha seu ID numérico do Telegram via [@userinfobot](https://t.me/userinfobot).
3. **Provedor de LLM / OpenClaw:**
   - Instalação local do [OpenClaw](https://openclaw.ai) (com porta HTTP habilitada) **OU** qualquer endpoint compatível com OpenAI (Ollama, vLLM, OpenAI oficial).
4. **n8n Local (Opcional para Google Calendar):**
   - Instalação via Docker (`docker run -d --name n8n -p 5678:5678 n8nio/n8n`). Se não estiver rodando, o Sorge utiliza o SQLite local com 100% das funcionalidades ativas.

---

## 📦 Instalação e Configuração

### 1. Clonar o Repositório
```bash
git clone https://github.com/lucaaregis4r-ops/Sorge.git
cd Sorge
```

### 2. Configurar o Ambiente Virtual
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configurar as Variáveis de Ambiente
Copie o arquivo de exemplo:
```bash
cp .env.example .env
```
Edite o arquivo `.env` com os seus dados:
```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=seu_bot_token_aqui
TELEGRAM_ALLOWED_USER_ID=seu_telegram_user_id_aqui

# Banco de Dados
DATABASE_PATH=data/sorge.db

# Configurações do Sistema
TIMEZONE=America/Sao_Paulo
LOG_LEVEL=INFO

# n8n Webhook / API
N8N_WEBHOOK_BASE_URL=http://localhost:5678/webhook

# OpenClaw Local / OpenAI Compatível
OPENCLAW_BASE_URL=http://127.0.0.1:18789/v1
OPENCLAW_API_KEY=seu_openclaw_token_aqui
OPENCLAW_MODEL=openclaw/seu-agente
```

### 4. Inicializar o Banco de Dados
```bash
python3 -c "from sorge_gateway.database import init_db; init_db()"
```

### 5. Executar os Testes
```bash
pytest
```

---

## 🚀 Como Executar

### Modo Interativo (Primeiro Plano)
```bash
./scripts/start-sorge.sh --foreground
```

### Modo Segundo Plano (Background)
```bash
./scripts/start-sorge.sh
./scripts/status-sorge.sh
./scripts/stop-sorge.sh
```

### Como Serviço de Sistema (`systemd --user`)
Para inicializar automaticamente ao ligar o computador:
```bash
./scripts/install-systemd.sh
systemctl --user start sorge.service
systemctl --user status sorge.service
```
Para acompanhar os logs em tempo real:
```bash
journalctl --user -u sorge.service -f
```

---

## 💬 Guia de Uso no Telegram

### 1. Comandos Rápidos (Zero-LLM — 0 Tokens)
| Comando | O que faz |
| :--- | :--- |
| `/start` | Mensagem inicial de boas-vindas e verificação de autorização. |
| `/ajuda` | Manual completo de uso e comandos. |
| `/hoje` | Lista os compromissos agendados para a data de hoje. |
| `/amanha` | Lista os compromissos agendados para o dia seguinte. |
| `/agenda` | Consulta a agenda do dia ou de uma data específica (`/agenda 25/10/2026`). |
| `/status` | Diagnóstico de integridade (Gateway, SQLite, n8n, OpenClaw, Uptime). |
| `/uso` | Relatório de economia e telemetria de tokens (`/uso hoje`, `/uso semana`, etc.). |

### 2. Linguagem Natural Simples (Zero-LLM)
- `"agenda hoje"` ou `"agenda amanhã"`
- `"agenda 25/10/2026"`
- `"cancela 3"` ou `"cancelar compromisso #3"`

### 3. Linguagem Natural Avançada (OpenClaw / GPT Luna)
- **Compromisso Único:**
  - *"Agendar dentista na sexta às 14h"*
  - *"Reunião com fisioterapia quinta depois do almoço"*
  - *"Almoço em família domingo ao meio-dia"*
- **Múltiplos Compromissos em Lote:**
  - *"Pedro quinta às 20h30; Antonela sábado às 10h; Bento sábado às 11h; Gabriel terça às 10h; Ana Beatriz sexta às 10h"*
- **Conversação com Confirmação:**
  - *Usuário:* *"Gostaria de marcar atendimento toda quarta às 10h15"*
  - *Sorge:* *"Você deseja agendar atendimento às quartas às 10h15 começando hoje?"*
  - *Usuário:* *"Sim, desejo"*
  - *Sorge:* *"✅ Atendimento marcado para 21/10/2026 das 10:15 às 11:15"*

---

## 🔒 Segurança e Privacidade

- **Nenhuma credencial ou token é enviado para servidores externos.**
- Os dados da sua agenda ficam gravados localmente no arquivo SQLite protegido da sua máquina.
- Apenas mensagens vindas do seu Telegram ID autorizado são processadas; mensagens de estranhos são sumariamente descartadas.
- O arquivo `.env` e os bancos de dados locais são estritamente ignorados pelo `.gitignore`.

---

## 📄 Licença

Distribuído sob a licença MIT. Consulte `LICENSE` para mais informações.
