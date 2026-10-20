# SORGE — Plano de Implementação V1

> Assistente pessoal local, econômico em tokens, acessado pelo Telegram e executado apenas quando o computador estiver ligado.

**Versão:** V1 — Local / Telegram  
**Objetivo:** colocar o Sorge em uso real antes de gastar dinheiro com hospedagem ou complicar a infraestrutura.

---

## 1. Visão da V1

A primeira versão do Sorge será um assistente pessoal capaz de:

- receber mensagens pelo Telegram;
- criar compromissos no Google Calendar;
- consultar a agenda;
- reagendar e cancelar compromissos;
- criar lembretes;
- enviar lembretes pelo Telegram enquanto o computador estiver ligado;
- usar lembretes nativos do Google Calendar como redundância;
- entender frases em linguagem natural;
- evitar LLM quando regras simples resolvem a mensagem;
- registrar quantidade de chamadas de IA e tokens utilizados;
- recuperar mensagens pendentes quando o computador voltar a ligar;
- detectar lembretes perdidos durante o período offline.

A V1 **não precisa ficar disponível 24/7**.

O computador do usuário será o servidor do Sorge.

---

## 2. Decisão principal de arquitetura

Nesta versão, **não usar WhatsApp**.

Motivos:

- autenticação mais trabalhosa;
- sessão mais frágil;
- necessidade de QR Code e persistência de sessão;
- mais componentes para depurar;
- não agrega valor suficiente para validar o produto.

Usar **Telegram Bot** como interface inicial.

O Telegram permite long polling, o que significa que o Sorge pode funcionar localmente sem domínio, HTTPS público ou porta aberta na internet.

### Arquitetura

```text
                    TELEGRAM
                       │
                       │ mensagens
                       ▼
              ┌─────────────────┐
              │ sorge-gateway   │
              │ Python          │
              │ long polling    │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  SMART ROUTER   │
              └───────┬─────────┘
                      │
          ┌───────────┴────────────┐
          │                        │
          ▼                        ▼
  Determinístico              Ambíguo
  regex / regras                   │
          │                        ▼
          │                   OpenClaw
          │                        │
          │                 intenção JSON
          │                        │
          └────────────┬───────────┘
                       ▼
                     n8n
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
 Google Calendar   SQLite         Telegram
        │                              ▲
        └──────── lembretes ───────────┘
```

---

## 3. O que acontece quando o computador está desligado?

### 3.1 Mensagens enviadas ao bot

O Telegram mantém updates não entregues por até aproximadamente **24 horas**.

Portanto:

```text
10:00 — computador desligado
11:00 — usuário envia:
        "marca dentista amanhã às 14h"

17:00 — computador ligado
17:01 — Sorge inicia
17:01 — long polling recebe a mensagem pendente
17:02 — evento é criado
```

Isso é adequado para a V1.

### Limitação

Se o Sorge permanecer desligado por mais de 24 horas, **não se deve assumir que mensagens antigas ainda estarão disponíveis pela fila da Bot API**.

Por isso o bot deve informar sua condição local em `/status`.

---

## 4. E os lembretes enquanto o computador está desligado?

O Sorge local **não consegue enviar uma mensagem pelo Telegram enquanto o computador estiver desligado**.

Isso não é um bug: não existe processo rodando para disparar a mensagem.

A V1 terá duas proteções.

### Proteção A — lembrete nativo do Google Calendar

Ao criar um compromisso, o Sorge também configura uma notificação padrão do próprio Google Calendar.

Exemplo:

```text
Evento: Dentista
Data: 21/10/2026 — 14:00

Google Calendar:
- notificar 1 dia antes
- notificar 1 hora antes

Sorge:
- Telegram 2 horas antes
- Telegram 30 minutos antes
```

Se o PC estiver desligado, o Google Calendar ainda poderá notificar pelo celular normalmente.

### Proteção B — Catch-up ao iniciar

O Sorge manterá registro dos lembretes pendentes.

Quando iniciar, executará:

```text
Buscar lembretes vencidos
        ↓
Já foram enviados?
  │
  ├── sim → ignorar
  │
  └── não
       ↓
Evento ainda é relevante?
  │
  ├── sim → enviar aviso atrasado
  └── não → registrar como perdido
```

Exemplo:

```text
⚠️ Sorge ficou offline.

Você tinha um lembrete às 14:00:
Reunião com fisioterapia — 15:00

O lembrete está 37 minutos atrasado.
```

---

## 5. Componentes da V1

### 5.1 Telegram Bot

Criado no BotFather.

Responsabilidades:

- receber mensagens;
- enviar respostas;
- enviar lembretes;
- oferecer comandos;
- futuramente exibir botões inline.

Credencial:

```text
TELEGRAM_BOT_TOKEN
```

Nunca versionar o token.

---

## 5.2 sorge-gateway

Pequeno serviço em Python.

Responsabilidades:

- conectar à Telegram Bot API por long polling;
- receber updates pendentes;
- verificar se o remetente está autorizado;
- deduplicar mensagens usando `update_id`;
- entregar a mensagem ao Smart Router;
- enviar respostas ao Telegram;
- registrar eventos básicos.

Biblioteca sugerida:

```text
python-telegram-bot
```

O gateway deve ser deliberadamente pequeno.

Não colocar lógica de negócio complexa nele.

---

## 5.3 Smart Router

É o componente central da estratégia de economia de tokens.

Ordem de decisão:

```text
Mensagem
   │
   ▼
1. É comando exato?
   ├── sim → sem LLM
   └── não
        ↓
2. Regex/parser entende com alta confiança?
   ├── sim → sem LLM
   └── não
        ↓
3. Enviar apenas a mensagem necessária ao OpenClaw
        ↓
4. OpenClaw retorna JSON estruturado
        ↓
5. n8n executa a ação
```

### Exemplos sem LLM

```text
/agenda
/agenda hoje
/agenda amanha
/uso
/status
/ajuda

agenda hoje
agenda amanhã
cancelar 184
feito 184
```

### Exemplos que podem usar LLM

```text
quinta depois do almoço coloca uma reunião com o pessoal da fisio

semana que vem preciso lembrar de conversar com a Helena

muda aquela consulta de terça para quinta de manhã
```

---

## 6. Papel do OpenClaw

Na V1 o OpenClaw não deve ser o executor de tudo.

Ele será principalmente a **camada de interpretação e raciocínio**.

Entrada:

```text
"quinta depois do almoço coloca uma reunião com o pessoal da fisio"
```

Saída esperada:

```json
{
  "action": "CREATE_EVENT",
  "title": "Reunião com fisioterapia",
  "date": "2026-10-22",
  "time": "15:00",
  "duration_minutes": 60,
  "reminders": [120, 30],
  "confidence": 0.93
}
```

O OpenClaw **não deve criar o evento diretamente**.

Ele interpreta.

O n8n executa.

Isso facilita:

- auditoria;
- testes;
- troca de modelo;
- economia de tokens;
- segurança;
- manutenção.

---

## 7. Papel do n8n

O n8n será o motor de automação.

Workflows da V1:

### WF-01 — Calendar Create

Entrada:

```json
{
  "title": "Dentista",
  "start": "2026-10-21T14:00:00-03:00",
  "duration_minutes": 60
}
```

Ações:

1. validar dados;
2. criar evento no Google Calendar;
3. adicionar lembretes nativos;
4. registrar ID do evento;
5. devolver resultado.

---

### WF-02 — Calendar List

Suportar:

```text
hoje
amanhã
esta semana
próximos 7 dias
```

Retorno estruturado.

---

### WF-03 — Calendar Update

Alterar:

- data;
- horário;
- título;
- duração.

Exigir ID interno ou confirmação quando houver ambiguidade.

---

### WF-04 — Calendar Delete

Nunca apagar silenciosamente um evento ambíguo.

Exemplo:

```text
Encontrei dois eventos chamados "Consulta":

1. terça 10h
2. sexta 14h

Qual deles?
```

---

### WF-05 — Reminder Dispatcher

Executar periodicamente enquanto o PC estiver ligado.

```text
buscar lembretes com:
send_at <= agora
status = pending
```

Enviar Telegram e marcar como enviado.

---

### WF-06 — Startup Catch-up

Executado quando o Sorge inicia.

Buscar lembretes:

```text
status = pending
send_at < agora
```

Classificar como:

```text
late_send
expired
cancelled
```

---

### WF-07 — Usage Stats

Gerar estatísticas para:

```text
/uso
/uso hoje
/uso semana
/uso mes
```

---

## 8. Banco de dados da V1

Para não tornar a primeira versão pesada, usar **SQLite**.

Arquivo:

```text
data/sorge.db
```

Quando o projeto for para uma VPS, migrar para PostgreSQL se necessário.

### Tabela `events`

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_event_id TEXT UNIQUE,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

### Tabela `reminders`

```sql
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    send_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    sent_at TEXT,
    channel TEXT NOT NULL DEFAULT 'telegram',
    FOREIGN KEY(event_id) REFERENCES events(id)
);
```

### Tabela `usage_events`

```sql
CREATE TABLE usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    route TEXT NOT NULL,
    used_llm INTEGER NOT NULL DEFAULT 0,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL,
    intent TEXT,
    telegram_update_id INTEGER
);
```

### Tabela `processed_updates`

```sql
CREATE TABLE processed_updates (
    telegram_update_id INTEGER PRIMARY KEY,
    processed_at TEXT NOT NULL
);
```

Isso evita duplicação após reinicializações.

---

## 9. Contador de tokens

O contador de tokens faz parte da V1.

O objetivo não é apenas mostrar consumo.

O objetivo é medir **quanto do Sorge funciona sem IA**.

### Comando

```text
/uso
```

Resposta desejada:

```text
📊 SORGE — USO HOJE

Mensagens processadas: 43
Sem LLM: 34 (79,1%)
Com LLM: 9 (20,9%)

Tokens de entrada: 6.840
Tokens de saída: 1.120
Total: 7.960

Modelo mais usado: modelo-economico
Custo conhecido: US$ 0,00 / N/A
```

### Métricas importantes

```text
messages_total
zero_llm_total
llm_calls_total
input_tokens
output_tokens
total_tokens
model_usage
intent_usage
errors
```

### Métrica principal para portfólio

```text
ZERO-LLM RATE
```

Exemplo:

```text
79,1% das interações foram resolvidas sem chamada a um modelo.
```

Essa é uma métrica mais honesta que tentar calcular “tokens economizados” imaginários.

---

## 10. Comandos iniciais do Telegram

### `/start`

```text
Olá. Eu sou o Sorge.

Posso cuidar da sua agenda e dos seus lembretes.
Digite /ajuda para ver os comandos.
```

### `/agenda`

Mostra próximos compromissos.

### `/hoje`

Agenda do dia.

### `/amanha`

Agenda do dia seguinte.

### `/uso`

Uso de LLM e tokens.

### `/status`

Exemplo:

```text
🟢 Sorge online

Telegram: OK
n8n: OK
OpenClaw: OK
Calendar: OK
Banco: OK

Iniciado há: 3h42m
Último catch-up: 21:08
```

### `/ajuda`

Lista curta de exemplos.

---

## 11. Linguagem natural suportada na V1

### Criar evento

```text
marca dentista amanhã às 14h

tenho reunião com a fisio sexta 15h

terça de manhã coloca consulta às 10
```

### Consultar

```text
o que tenho amanhã?

qual minha agenda sexta?

tenho alguma coisa de manhã?
```

### Alterar

```text
muda o dentista para quinta às 16
```

### Cancelar

```text
cancela o dentista de amanhã
```

### Lembretes

```text
me lembra duas horas antes

me lembra amanhã de mandar o relatório
```

---

## 12. Segurança

A V1 deve ser pessoal.

O bot não deve aceitar comandos de qualquer usuário do Telegram.

`.env`:

```text
TELEGRAM_ALLOWED_USER_ID=<id-do-usuario>
```

Toda mensagem recebida deve executar:

```text
if telegram_user_id != TELEGRAM_ALLOWED_USER_ID:
    ignore
```

Nunca expor em GitHub:

- token do Telegram;
- chave de modelo;
- credencial do Google;
- cookies;
- refresh tokens;
- banco real.

Adicionar ao `.gitignore`:

```text
.env
data/
credentials/
*.db
```

---

## 13. Estrutura do repositório

```text
sorge/
├── README.md
├── PLAN.md
├── .env.example
├── .gitignore
├── requirements.txt
│
├── sorge_gateway/
│   ├── __init__.py
│   ├── main.py
│   ├── telegram.py
│   ├── router.py
│   ├── openclaw.py
│   ├── n8n.py
│   ├── database.py
│   ├── usage.py
│   └── config.py
│
├── n8n/
│   ├── calendar-create.json
│   ├── calendar-list.json
│   ├── calendar-update.json
│   ├── calendar-delete.json
│   ├── reminder-dispatcher.json
│   ├── startup-catchup.json
│   └── usage-stats.json
│
├── prompts/
│   └── intent-parser.md
│
├── database/
│   └── schema.sql
│
├── scripts/
│   ├── start-sorge.sh
│   ├── stop-sorge.sh
│   ├── status-sorge.sh
│   └── install-systemd.sh
│
├── systemd/
│   └── sorge.service
│
├── tests/
│   ├── test_router.py
│   ├── test_dates.py
│   ├── test_usage.py
│   └── fixtures/
│
└── data/
    └── .gitkeep
```

---

## 14. Como o Sorge ficará rodando no PC

A meta é que o usuário **não precise abrir quatro terminais** toda vez.

### Desenvolvimento

```bash
./scripts/start-sorge.sh
```

O script deve:

1. verificar internet;
2. verificar OpenClaw;
3. iniciar n8n;
4. iniciar `sorge-gateway`;
5. executar catch-up;
6. gravar PID/logs;
7. mostrar status.

### Uso normal

Depois de estável, criar serviço `systemd --user`.

Comportamento desejado:

```text
PC liga
   ↓
Linux inicia sessão
   ↓
sorge.service inicia
   ↓
n8n inicia
   ↓
gateway inicia long polling
   ↓
Telegram entrega mensagens pendentes
   ↓
catch-up verifica lembretes perdidos
   ↓
Sorge envia:
"🟢 Estou online novamente."
```

### Desligamento

O serviço deve encerrar de forma limpa e persistir estado.

---

## 15. Estratégia de logs

Criar:

```text
logs/sorge.log
logs/error.log
```

Não registrar texto completo de mensagens sensíveis por padrão.

Formato sugerido:

```text
2026-10-19T21:10:21-03:00
update=893214
route=deterministic
intent=LIST_TODAY
llm=false
status=success
latency_ms=312
```

---

## 16. Fases de implementação

# FASE 0 — Repositório

Objetivo: deixar a base pronta.

- [ ] criar repositório `sorge`;
- [ ] criar estrutura de pastas;
- [ ] criar `.env.example`;
- [ ] criar `.gitignore`;
- [ ] criar banco SQLite;
- [ ] criar logger;
- [ ] criar testes básicos.

**Critério de conclusão:**

```text
pytest
```

passa sem erros.

---

# FASE 1 — Telegram local

- [ ] criar bot no BotFather;
- [ ] configurar token;
- [ ] descobrir `TELEGRAM_ALLOWED_USER_ID`;
- [ ] implementar long polling;
- [ ] responder `/start`;
- [ ] responder `/status`;
- [ ] salvar `update_id` processados;
- [ ] testar desligar/religar gateway.

**Teste obrigatório:**

1. desligar Sorge;
2. enviar mensagem no Telegram;
3. aguardar 5 minutos;
4. ligar Sorge;
5. confirmar que a mensagem é processada apenas uma vez.

---

# FASE 2 — Smart Router sem IA

Implementar primeiro:

```text
/hoje
/amanha
/agenda
/uso
/status
/ajuda
```

Depois regex para frases simples:

```text
agenda hoje
agenda amanhã
agenda sexta
```

Registrar:

```text
used_llm = false
```

para essas rotas.

---

# FASE 3 — Google Calendar via n8n

- [ ] conectar Google OAuth;
- [ ] workflow criar evento;
- [ ] workflow listar eventos;
- [ ] workflow editar;
- [ ] workflow cancelar;
- [ ] validar timezone `America/Sao_Paulo`;
- [ ] adicionar notificação nativa do Calendar.

**Critério de conclusão:**

```text
"agenda amanhã"
```

retorna compromissos reais sem LLM.

---

# FASE 4 — OpenClaw como intérprete

- [ ] criar prompt estruturado;
- [ ] limitar saída a JSON;
- [ ] validar schema;
- [ ] recusar execução com confidence baixa;
- [ ] registrar modelo e tokens;
- [ ] enviar somente contexto necessário.

**Regra:**

Nunca enviar calendário inteiro para interpretar uma frase que não precisa dele.

---

# FASE 5 — Criação em linguagem natural

Suportar:

```text
marca dentista amanhã às 14h
```

Fluxo:

```text
Telegram
↓
Router
↓
OpenClaw
↓
JSON
↓
n8n
↓
Calendar
↓
Telegram
```

Resposta:

```text
✅ Dentista marcado
📅 20/10/2026
🕑 14:00–15:00
```

---

# FASE 6 — Lembretes

- [ ] armazenar lembretes;
- [ ] dispatcher;
- [ ] marcar enviados;
- [ ] evitar duplicados;
- [ ] configurar backup no Calendar;
- [ ] catch-up após período offline.

---

# FASE 7 — Contador de tokens

- [ ] capturar tokens de entrada;
- [ ] capturar tokens de saída;
- [ ] capturar modelo;
- [ ] registrar chamadas zero-LLM;
- [ ] implementar `/uso`;
- [ ] gerar estatísticas diárias e mensais.

---

# FASE 8 — Autostart

- [ ] criar `start-sorge.sh`;
- [ ] criar serviço systemd do usuário;
- [ ] iniciar após login;
- [ ] reiniciar automaticamente após falha;
- [ ] executar catch-up ao iniciar.

**Resultado:**

O usuário liga o computador e não precisa fazer nada.

---

## 17. O que deliberadamente NÃO entra na V1

Não implementar agora:

- WhatsApp;
- servidor VPS;
- domínio;
- HTTPS público;
- RAG;
- e-mail;
- leitura de GitHub;
- múltiplos usuários;
- dashboard web sofisticado;
- agentes múltiplos;
- modelo local pesado;
- voz;
- tarefas recorrentes complexas.

Esses recursos entram depois que calendário e lembretes estiverem realmente sendo usados.

---

## 18. Roadmap depois da V1

### V1.1

- tarefas sem horário;
- botões Telegram;
- `✅ concluir`;
- `⏰ adiar 30 min`;
- `📅 reagendar`.

### V1.2

- resumo diário;
- resumo semanal;
- detecção de conflitos;
- tempo livre na agenda.

### V2

- Gmail;
- criar tarefas a partir de e-mails;
- resumo de mensagens importantes;
- confirmação antes de enviar respostas.

### V3

- hospedagem 24/7;
- PostgreSQL;
- Docker Compose completo;
- backup;
- monitoramento.

### V4

- WhatsApp;
- outros módulos do Sorge;
- vagas;
- relatórios;
- GitHub;
- assistente pessoal mais amplo.

---

## 19. Critério de sucesso da V1

A V1 estará pronta quando esta sequência funcionar de ponta a ponta:

```text
1. Usuário liga o computador.

2. Sorge inicia automaticamente.

3. Usuário envia no Telegram:
   "quinta às 15 tenho reunião com a fisio"

4. Sorge interpreta a mensagem.

5. Evento aparece no Google Calendar.

6. Sorge responde confirmando.

7. Antes da reunião, Sorge envia lembrete.

8. Usuário digita:
   /uso

9. Sorge mostra quantas mensagens usaram LLM e quantos tokens foram gastos.

10. Usuário desliga o PC.

11. Envia uma nova mensagem ao bot algumas horas depois.

12. Liga o PC.

13. Sorge recupera a mensagem pendente e processa.
```

Se isso funcionar de forma confiável, a V1 está concluída.

---

## 20. Prompt inicial para o Codex

```text
Você vai implementar a V1 do projeto Sorge.

Leia PLAN.md inteiro antes de modificar qualquer arquivo.

OBJETIVO

Construir um assistente pessoal local acessado pelo Telegram.
O computador do usuário será o servidor.
Não implemente hospedagem em nuvem nesta fase.

ARQUITETURA

Telegram
→ gateway Python com long polling
→ Smart Router
→ regras determinísticas quando possível
→ OpenClaw apenas para linguagem natural ambígua
→ n8n executando automações
→ Google Calendar
→ SQLite para estado, lembretes e métricas

PRINCÍPIO MAIS IMPORTANTE

Minimizar chamadas de LLM.

Antes de chamar OpenClaw, tente resolver a mensagem com:

1. comandos exatos;
2. regex;
3. parser determinístico.

Somente então use LLM.

O OpenClaw deve produzir intenção estruturada em JSON.
Ele não deve executar diretamente operações no Google Calendar.

OFFLINE

O sistema deve funcionar somente enquanto o computador estiver ligado.
Ao reiniciar:

1. retomar long polling do Telegram;
2. processar updates pendentes;
3. impedir duplicação por update_id;
4. procurar lembretes que venceram enquanto o sistema estava offline;
5. enviar catch-up quando apropriado.

TOKENS

Registrar em SQLite:

- se houve chamada de LLM;
- modelo;
- input_tokens;
- output_tokens;
- total_tokens;
- intenção;
- data/hora.

Implementar /uso mostrando:

- mensagens totais;
- mensagens resolvidas sem LLM;
- taxa zero-LLM;
- chamadas de LLM;
- tokens de entrada;
- tokens de saída;
- total de tokens.

SEGURANÇA

Aceitar comandos somente de TELEGRAM_ALLOWED_USER_ID.
Nunca versionar credenciais.

IMPLEMENTAÇÃO

Trabalhe por fases.
Antes de cada fase:

1. diga quais arquivos serão alterados;
2. faça a menor implementação funcional;
3. rode testes;
4. só avance se os testes passarem.

Comece apenas pela FASE 0 e FASE 1.
Não implemente todas as fases de uma vez.
```

---

## 21. Princípios do projeto

1. **Útil antes de sofisticado.**
2. **Código antes de LLM quando código resolve.**
3. **IA interpreta; automações executam.**
4. **Toda ação deve ser auditável.**
5. **Toda chamada de IA deve ser mensurável.**
6. **Falhar de forma segura é melhor que executar algo ambíguo.**
7. **A V1 deve funcionar no computador atual antes de existir VPS.**
8. **Hospedagem será uma evolução, não um pré-requisito.**

---

# Resumo técnico

```text
Nome: Sorge
Versão: V1
Interface: Telegram
Execução: PC local
Entrada Telegram: long polling
Automação: n8n
Raciocínio: OpenClaw
Calendário: Google Calendar
Banco: SQLite
Timezone: America/Sao_Paulo
Telemetria: contador de tokens + zero-LLM rate
Offline Telegram: recuperar updates pendentes disponíveis ao reiniciar
Offline lembretes: catch-up + notificações nativas do Calendar
Hospedagem: nenhuma na V1
Custo de infraestrutura: R$ 0
```
