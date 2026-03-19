# NEF IA API

API operacional de IA com FastAPI, PostgreSQL, Redis e worker assincrono.

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
- Integracao real com provider (OpenAI) via camada abstraida
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
2. Ajuste variaveis sensiveis e conexoes.
3. Preencha `django_ai_provider_credentials` com credencial ativa.
4. Configure `CREDENTIALS_ENCRYPTION_KEY` com uma chave Fernet valida.

Variaveis importantes da Etapa 6/7/8/9:
- `MAX_TOKENS`
- `TEMPERATURE`
- `PROVIDER_TIMEOUT_SECONDS`
- `MAX_INPUT_CHARACTERS`
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
- `CHUNK_SIZE_CHARACTERS`
- `CREDENTIALS_ENCRYPTION_KEY`

## Rodando com Docker
```bash
docker compose up --build
```

Servicos:
- API: `http://localhost:8000`
- Worker Dramatiq: `nef-ia-worker`
- Postgres: `localhost:5432`
- Redis: `localhost:6379`

## Endpoints principais
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `POST /api/v1/admin/auth/login`
- `POST /api/v1/files/request-upload`
- `POST /api/v1/executions`
- `GET /api/v1/executions/{execution_id}`
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

## Migrations
```bash
python -m alembic upgrade head
```

## Seed inicial (FastAPI)
```bash
python -m app.seed
```

Com atualizacao forcada dos dados padrao:
```bash
python -m app.seed --force
```

Com criacao do token bootstrap para integracao com Django:
```bash
python -m app.seed --with-bootstrap-token
```

Opcionalmente, para nomear o token bootstrap:
```bash
python -m app.seed --with-bootstrap-token --bootstrap-token-name django-bootstrap
```

Ao usar `--with-bootstrap-token`, o seed cria `django-bootstrap` (ou o nome informado) somente se ainda nao existir, salva apenas o hash no banco e exibe o plaintext apenas nessa execucao.

## Bootstrap Django <-> FastAPI (sem JWT manual)
1. Instale dependencias e configure `.env`.
2. Rode as migrations:
```bash
python -m alembic upgrade head
python manage.py migrate
```
3. Rode o seed da FastAPI com bootstrap:
```bash
python -m app.seed --with-bootstrap-token
```
4. Copie o token bootstrap exibido no terminal (exibicao unica).
5. No Django, acesse `Configuracoes > Integracao FastAPI`.
6. Em `Cadastrar token bootstrap`, informe nome e token plaintext copiado.
7. Salve e use a mesma tela para:
- criar novos tokens na FastAPI
- listar tokens
- revogar tokens
- selecionar o token ativo usado pelo Django

`FASTAPI_ADMIN_TOKEN` permanece apenas como fallback legado temporario quando nenhum token ativo estiver cadastrado na tela.

## Testes
```bash
python -m pytest -q
```

# nef-ia-api
