# Django Admin - Etapa 8 (Legado e Limpeza Controlada)

Data de referencia: 2026-03-20

## Objetivo desta etapa
- Deixar explicito no codigo o que e legado local.
- Remover acoplamento residual de views refatoradas ao ORM local.
- Manter operacao sem limpeza destrutiva de tabelas/migrations.

## Fonte da verdade por dominio

### Remoto (FastAPI + banco operacional da API)
- Providers operacionais
- Modelos operacionais
- Credenciais operacionais
- Execucoes
- Arquivos de execucao
- Tokens/operacoes administrativas expostos pela API

### Local permitido (painel Django)
- Usuarios/admin do painel
- Sessoes, grupos e permissoes do painel
- Configuracao de integracao com a FastAPI:
  - `core.FastAPIIntegrationConfig`
  - `core.FastAPIIntegrationToken`
- Estado de UI/sessao (mensagens, resultados temporarios de teste)

### Local legado em transicao (NAO fonte da verdade)
- `providers.Provider`
- `models_catalog.ProviderModel`
- `credentials.ProviderCredential`
- `prompts.AIPrompt` (enquanto catalogo oficial nao estiver completo na API)

## Views ja refatoradas sem dependencia de ORM local
- `providers/views.py`
  - rotas principais operam por `remote_id` (UUID)
  - rotas `*_legacy` por `pk` local foram descontinuadas para lookup local
- `models_catalog/views.py`
  - fluxo principal remoto por `remote_id`
  - rotas `*_legacy` por `pk` local sem lookup ORM
- `credentials/views.py`
  - fluxo principal remoto por `remote_id`
  - rotas `*_legacy` por `pk` local sem lookup ORM
- `executions/views.py`
  - leitura remota via servico HTTP
- `files_admin/views.py`
  - leitura/download remotos via servico HTTP
- `core/views.py` (`DashboardView`)
  - contadores de providers/modelos/credenciais passam por servicos remotos

## Endpoints remotos atualmente usados no painel Django
- Providers
  - `GET /api/v1/admin/providers`
  - `POST /api/v1/admin/providers`
  - `PATCH /api/v1/admin/providers/{provider_id}`
  - `PATCH /api/v1/admin/providers/{provider_id}/activate`
  - `PATCH /api/v1/admin/providers/{provider_id}/deactivate`
  - `POST /api/v1/admin/providers/{provider_id}/connectivity-test`
- Modelos
  - `GET /api/v1/admin/providers/{provider_id}/models`
  - `POST /api/v1/admin/providers/{provider_id}/models`
  - `PATCH /api/v1/admin/models/{model_id}`
  - `PATCH /api/v1/admin/models/{model_id}/activate`
  - `PATCH /api/v1/admin/models/{model_id}/deactivate`
  - `DELETE /api/v1/admin/models/{model_id}`
  - `GET /api/v1/admin/providers/{provider_id}/available-models` (quando disponivel)
- Credenciais
  - `GET /api/v1/admin/providers/{provider_id}/credentials`
  - `POST /api/v1/admin/providers/{provider_id}/credentials`
  - `PATCH /api/v1/admin/credentials/{credential_id}`
  - `PATCH /api/v1/admin/credentials/{credential_id}/activate`
  - `PATCH /api/v1/admin/credentials/{credential_id}/deactivate`
- Execucoes e arquivos
  - `GET /api/v1/admin/executions/running`
  - `GET /api/v1/admin/executions/failed`
  - `GET /api/v1/admin/executions/{execution_id}/files`
  - `GET /api/v1/files/execution-files/{file_id}/download`
- Prompts/catalogo (diagnostico)
  - `GET /api/v1/admin/prompts` (probe)
  - `GET /api/v1/admin/automation-prompts` (probe)
  - `GET /api/v1/admin/automations` (probe)

## Dependencias de endpoint futuro (para encerrar legados)
- Execucoes:
  - endpoint administrativo de listagem completa (alem de running/failed)
  - endpoint administrativo de detalhe por `execution_id` para todos os status
- Arquivos:
  - endpoint administrativo de detalhe por `file_id`
  - endpoint administrativo de download alinhado ao mesmo esquema de auth admin
- Prompts/automações:
  - CRUD administrativo oficial (fonte da verdade remota)
  - estrutura consolidada de automations/automation_prompts

## Decisoes de seguranca e limpeza
- Nenhuma migration/tabela local foi removida nesta etapa.
- Nenhum dado remoto da FastAPI foi alterado fora do fluxo normal de endpoints.
- Models locais legados permanecem apenas para transicao controlada e compatibilidade.
