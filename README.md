# NEF IA API

API operacional de IA com FastAPI, PostgreSQL, Redis e worker assincrono.

## Painel Django (transicao arquitetural)
- Documento da etapa de limpeza controlada: `docs/django_admin_transition_stage8.md`
- Regra atual: entidades operacionais devem ter fonte da verdade na FastAPI.

## Stack
- Python 3.11+
- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL
- Redis
- Dramatiq
- Docker + Docker Compose

## Estado atual (Etapa 9)
- Arquitetura modular e banco operacional `django_ai_*`
- Seguranca com JWT admin, API tokens e middleware global
- Upload/download de arquivos com checksum e storage local
- Execucao assincrona com fila Redis + Dramatiq
- Integracao real com providers OpenAI, Anthropic/Claude e Gemini via camadas nativas
- Resolucao de prompt oficial a partir do banco compartilhado
- Registro de usage e custo em `django_ai_provider_usage`
- Observabilidade e governanca:
  - metricas de execucao, fila, usage e custos
  - endpoints administrativos para dashboard
  - correlacao de logs por `correlation_id` e `execution_id`
  - alertas basicos (falhas seguidas, custo alto, fila travada)
  - healthcheck avancado com provider configurado e fila
- Escalabilidade e resiliencia:
  - idempotencia de execucao no worker
  - retry inteligente com backoff exponencial
  - resolucao estrita de provider/modelo pelo sistema geral
  - timeout e classificacao de erros retryables
  - controle de custo por execucao
  - controle de tokens/contexto por execucao
  - chunking de conteudo para arquivos grandes
  - limite global de concorrencia no worker
  - protecao contra duplicidade de processamento
- Camada administrativa de catalogo IA:
  - CRUD administrativo de providers
  - CRUD administrativo de modelos por provider
  - CRUD administrativo de credenciais por provider
  - ativacao/desativacao operacional
  - status operacional consolidado para dashboard
- Seguranca de credenciais:
  - credenciais de provider criptografadas com Fernet em `encrypted_api_key`
  - chave de criptografia via `CREDENTIALS_ENCRYPTION_KEY` (fora do banco)
  - segredo nunca retornado em response e nunca logado
  - formato legado `base64:`/`plain:` rejeitado e exige rotacao/regravacao

## Regra de prompt
O prompt oficial nao pertence a API de IA.  
Ele e resolvido a partir das tabelas compartilhadas do sistema geral.

## Fluxo de execucao
1. API cria execucao e job na fila.
2. Worker busca prompt oficial + provider/modelo no banco compartilhado e arquivo de entrada.
3. Worker valida provider/modelo/credencial ativos no catalogo operacional.
4. Worker executa IA real.
5. Worker gera arquivo de output.
6. Worker registra tokens e custo.
7. Worker atualiza status da execucao.

## Estrutura
```text
app/
  api/
  core/
  db/
  integrations/
    providers/
    queue/
    shared_db/
    storage/
  models/
    operational/
    shared/
  repositories/
    operational/
    shared/
  schemas/
  services/
    shared/
  workers/
alembic/
tests/
```

## Configuracao
1. Copie `.env.example` para `.env`.
2. Para ambiente local, a FastAPI e o worker usam o banco `nef_ia` no Postgres do Compose:
   - `DB_HOST=postgres`
   - `DB_PORT=5432`
   - `DB_USER=postgres`
   - `DB_PASSWORD=postgres`
   - `DB_NAME=nef_ia`
3. O painel Django local usa um banco separado no mesmo servidor Postgres:
   - `DJANGO_DB_HOST=127.0.0.1`
   - `DJANGO_DB_PORT=5432`
   - `DJANGO_DB_NAME=nef_ia_django`
   - `DJANGO_DB_USER=postgres`
   - `DJANGO_DB_PASSWORD=postgres`
4. Se outro ambiente precisar de engine diferente, ajuste `DJANGO_DB_ENGINE` explicitamente.
5. Preencha `django_ai_provider_credentials` com credencial ativa quando precisar testar providers reais.
6. Configure `CREDENTIALS_ENCRYPTION_KEY` com uma chave Fernet valida antes de criar ou editar credenciais de provider.

Importante sobre `CREDENTIALS_ENCRYPTION_KEY`:
- O valor `replace-with-fernet-key` presente no `.env.example` e apenas um placeholder invalido.
- Ele nao deve ser usado em producao.
- Gere uma chave valida com:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Variaveis importantes da Etapa 6/7/8/9:
- `MAX_TOKENS`
- `TEMPERATURE`
- `PROVIDER_TIMEOUT_SECONDS`
- `MAX_INPUT_CHARACTERS`
- `MAX_CONTEXT_CHARACTERS`
- `MAX_CONTEXT_FILE_CHARACTERS`
- `MAX_PROMPT_CHARACTERS`
- `ALERT_FAILURE_STREAK_THRESHOLD`
- `ALERT_COST_THRESHOLD`
- `ALERT_QUEUE_STUCK_MINUTES`
- `MAX_RETRIES`
- `RETRY_BACKOFF`
- `RETRY_BACKOFF_SECONDS`
- `PROVIDER_TIMEOUT`
- `MAX_TOKENS_PER_EXECUTION`
- `MAX_COST_PER_EXECUTION`
- `MAX_CONCURRENT_EXECUTIONS`
- `MAX_EXECUTION_ROWS_HARD_LIMIT`
- `MAX_PROVIDER_CALLS_HARD_LIMIT`
- `MAX_TEXT_CHUNKS_HARD_LIMIT`
- `MAX_TABULAR_ROW_CHARACTERS_HARD_LIMIT`
- `MAX_EXECUTION_SECONDS_HARD_LIMIT`
- `MAX_JOB_RETRIES_HARD_LIMIT`
- `EXECUTION_PROFILE_DEFAULT`
- `EXECUTION_PROFILE_AUTOMATION_OVERRIDES`
- `EXECUTION_PROFILE_STANDARD_MAX_*`
- `EXECUTION_PROFILE_HEAVY_MAX_*`
- `EXECUTION_PROFILE_EXTENDED_MAX_*`
- `CHUNK_SIZE_CHARACTERS`
- `CREDENTIALS_ENCRYPTION_KEY`

## Execucao local

### Pre-requisitos
- Docker e Docker Compose
- Python 3.11+
- `venv` habilitado no Python local

### Arquitetura local esperada
- FastAPI + worker + Redis + Postgres via Docker Compose
- Banco `nef_ia` para FastAPI/worker
- Banco `nef_ia_django` para o Django local
- Django local fora do Docker, conectado ao Postgres do Compose pela porta `5432`

### 1. Subir infraestrutura da FastAPI
```powershell
docker compose up --build -d
```

Servicos:
- API: `http://localhost:8000`
- Worker Dramatiq: `nef-ia-worker`
- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- Django local: `http://127.0.0.1:8001`

O container Postgres inicializa automaticamente:
- `nef_ia` para FastAPI e worker
- `nef_ia_django` para o Django

### 2. Conferir que os dois bancos existem
```powershell
docker compose exec postgres psql -U postgres -lqt
```

Voce deve ver pelo menos:
- `nef_ia`
- `nef_ia_django`

Se voce ja tinha um volume antigo do Postgres antes dessa configuracao, os scripts de inicializacao nao sao reexecutados automaticamente. Nesse caso:

```powershell
docker compose down -v
docker compose up --build -d
```

### 3. Rodar migrations da FastAPI
```powershell
docker compose exec api python -m alembic upgrade head
```

### 4. Rodar seed/bootstrap da FastAPI
Seed basico:

```powershell
docker compose exec api python -m app.seed
```

Com atualizacao forcada dos dados padrao:

```powershell
docker compose exec api python -m app.seed --force
```

Com criacao do token bootstrap para integracao com Django:

```powershell
docker compose exec api python -m app.seed --with-bootstrap-token
```

Opcionalmente, para nomear o token bootstrap:

```powershell
docker compose exec api python -m app.seed --with-bootstrap-token --bootstrap-token-name django-bootstrap
```

Ao usar `--with-bootstrap-token`, o seed cria `django-bootstrap` (ou o nome informado) somente se ainda nao existir, salva apenas o hash no banco e exibe o plaintext apenas nessa execucao.

### 5. Criar e ativar o venv do Django
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Observacao:
- O fluxo local padrao usa PostgreSQL, nao SQLite.
- O Django conecta em `nef_ia_django` por `127.0.0.1:5432`.

### 6. Rodar migrations do Django local
```powershell
python manage.py migrate
```

### 7. Subir o painel Django local
```powershell
python manage.py runserver 8001
```

### 8. Bootstrap Django <-> FastAPI (sem JWT manual)
1. Rode as migrations da FastAPI e do Django.
2. Rode o seed da FastAPI com bootstrap:

```powershell
docker compose exec api python -m app.seed --with-bootstrap-token
```

3. Copie o token bootstrap exibido no terminal (exibicao unica).
4. No Django, acesse `Configuracoes > Integracao FastAPI`.
5. Em `Cadastrar token bootstrap`, informe nome e token plaintext copiado.
6. Salve e use a mesma tela para:
- criar novos tokens na FastAPI
- listar tokens
- revogar tokens
- selecionar o token ativo usado pelo Django

`FASTAPI_ADMIN_TOKEN` permanece apenas como fallback legado temporario quando nenhum token ativo estiver cadastrado na tela.

## Endpoints principais
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `POST /api/v1/admin/auth/login`
- `POST /api/v1/files/request-upload`
- `POST /api/v1/executions`
- `GET /api/v1/executions/{execution_id}`
- `GET /api/v1/executions/{execution_id}/files`
- `GET /api/v1/executions/{execution_id}/inputs`
- `GET /api/v1/analysis-requests/{analysis_request_id}/executions`
- `GET /api/v1/admin/metrics/executions`
- `GET /api/v1/admin/metrics/usage`
- `GET /api/v1/admin/metrics/costs`
- `GET /api/v1/admin/metrics/queue`
- `GET /api/v1/admin/executions/failed`
- `GET /api/v1/admin/executions/running`
- `GET /api/v1/admin/providers/usage`
- `GET /api/v1/admin/providers`
- `POST /api/v1/admin/providers`
- `PATCH /api/v1/admin/providers/{provider_id}`
- `PATCH /api/v1/admin/providers/{provider_id}/activate`
- `PATCH /api/v1/admin/providers/{provider_id}/deactivate`
- `GET /api/v1/admin/providers/{provider_id}/models`
- `POST /api/v1/admin/providers/{provider_id}/models`
- `PATCH /api/v1/admin/models/{model_id}`
- `PATCH /api/v1/admin/models/{model_id}/activate`
- `PATCH /api/v1/admin/models/{model_id}/deactivate`
- `GET /api/v1/admin/providers/{provider_id}/credentials`
- `POST /api/v1/admin/providers/{provider_id}/credentials`
- `PATCH /api/v1/admin/credentials/{credential_id}`
- `PATCH /api/v1/admin/credentials/{credential_id}/activate`
- `PATCH /api/v1/admin/credentials/{credential_id}/deactivate`
- `GET /api/v1/admin/catalog/status`

## Testes
```powershell
python -m pytest -q
```

# nef-ia-api
