# Relatorio: Upload/Download de Arquivos e Testes no Insomnia

## Contexto

Este projeto expoe rotas FastAPI para upload e download de arquivos ligados a uma automacao oficial.
Os arquivos pertencem a um `analysis_request_id`, e esse request pertence a uma `automation_id`.

A autorizacao nao e apenas por token valido. O token operacional precisa ter permissao para a automacao dona do `analysis_request_id`.

## Ambiente testado

- API: `http://127.0.0.1:8000`
- Healthcheck validado:
  - `GET /health/live`
  - Resultado: `200 OK`
- Django estava rodando separadamente no ambiente local.
- Postgres do Docker foi mapeado para `5433` no host para evitar conflito com Postgres local em `5432`.

## Automacao real usada no teste

Automacao:

```text
Teste multiplos arquivos
automation_id=a8f0d74f-588e-4a36-a6d2-efb734aac2b2
```

Caracteristicas observadas:

- Provider/model: `openai / gpt-4o-mini`
- Credencial: `usandoapideteste2`
- Prompt oficial: vinculado
- Contrato: explicito
- Tipo: Planilha
- Parser: Tabular estruturado
- Formatador: Planilha tabular

## Token e request de teste

Foi criado um token operacional `ia_live` para a automacao acima, com:

- `allow_execution=True`
- `allow_file_upload=True`
- escopo: `automation_id=a8f0d74f-588e-4a36-a6d2-efb734aac2b2`

Por seguranca, o plaintext do token nao deve ser salvo em arquivo versionado. Use o token emitido localmente ou gere outro.

Tambem foi criado:

```text
analysis_request_id=ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0
```

Esse request esta ligado a automacao real acima.

## Regra de permissao importante

Para upload/download funcionar:

```text
token ia_live -> permissao na automation_id
analysis_request_id -> pertence a mesma automation_id
arquivo -> pertence ao analysis_request_id
```

Se o token pertencer a outra automacao, o download pode retornar:

```json
{
  "error": {
    "code": "file_download_permission_denied",
    "message": "Token cannot download this request file."
  }
}
```

Tokens `ia_int_...` sao tokens de integracao/admin/bootstrap. Eles nao devem ser usados para upload/download operacional de arquivos.

## Rotas de upload existentes

Existem duas rotas:

### Upload unico

```text
POST /api/v1/files/request-upload
```

Campos multipart:

```text
analysis_request_id
file
```

### Upload multiplo

```text
POST /api/v1/files/request-uploads
```

Campos multipart:

```text
analysis_request_id
files
files
files
```

## Decisao recomendada

Para simplificar o uso por clientes externos, usar somente:

```text
POST /api/v1/files/request-uploads
```

Essa rota aceita um ou varios arquivos. Mesmo para apenas um arquivo, enviar no campo `files`.

Regra simples para clientes:

```text
Sempre usar /request-uploads
Sempre mandar arquivos no campo files
```

## Configuracao correta no Insomnia

### Upload multiplo

Method:

```text
POST
```

URL:

```text
http://127.0.0.1:8000/api/v1/files/request-uploads
```

Headers:

```text
Authorization: Bearer <IA_LIVE_TOKEN_DA_AUTOMACAO>
Accept: */*
```

Nao adicionar `Content-Type` manualmente.

O Insomnia precisa gerar automaticamente:

```text
Content-Type: multipart/form-data; boundary=...
```

Se o header manual for apenas `multipart/form-data`, sem `boundary`, a API recebe body vazio e retorna erro de campos ausentes.

Body:

```text
Multipart Form
```

Campos:

```text
analysis_request_id   Text   ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0
files                 File   arquivo.xlsx
files                 File   arquivo.pdf
files                 File   arquivo.docx
```

Para apenas um arquivo:

```text
analysis_request_id   Text   ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0
files                 File   arquivo.xlsx
```

## Erro comum no Insomnia

Erro:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": {
      "errors": [
        {
          "loc": ["body", "analysis_request_id"],
          "msg": "Field required"
        },
        {
          "loc": ["body", "file"],
          "msg": "Field required"
        }
      ]
    }
  }
}
```

Causas comuns:

- Body nao esta em `Multipart Form`.
- `Content-Type` foi criado manualmente e esta sem `boundary`.
- A rota usada foi `/request-upload`, mas o campo enviado foi `files`.
- A rota usada foi `/request-uploads`, mas o campo enviado foi `file`.
- Faltou o campo `analysis_request_id`.
- Campo de arquivo esta como `Text` em vez de `File`.

Resumo:

```text
/request-upload   -> file
/request-uploads  -> files
```

## Download

Rota:

```text
GET /api/v1/files/request-files/{file_id}/download
```

Exemplo:

```text
GET http://127.0.0.1:8000/api/v1/files/request-files/0e96a005-4591-403e-a6d9-4b2ecbaae1c0/download
```

Headers:

```text
Authorization: Bearer <IA_LIVE_TOKEN_DA_AUTOMACAO>
Accept: */*
```

Sem body.

## Arquivos testados com sucesso

Upload multiplo validado com:

```text
planilha_teste.xlsx
pdf_teste_simples.pdf
documento_teste_multiplos_arquivos.docx
```

Resultado do upload:

```text
XLSX file_id=0e96a005-4591-403e-a6d9-4b2ecbaae1c0
PDF  file_id=ad4fce83-f59c-45af-9b45-4194afb5b809
DOCX file_id=7849cec6-2fde-4567-bc83-cefa37b76159
```

Download validado:

```text
GET /api/v1/files/request-files/0e96a005-4591-403e-a6d9-4b2ecbaae1c0/download
```

Resultado:

```text
200 OK
filename=planilha_teste.xlsx
content-length=4924
x-file-checksum=6bddee1b005ca34f7135c6c085ab62949a1afc95a97537c98d8a677db580772c
```

## Resultados adicionais dos testes no Insomnia

Apos corrigir a configuracao do Insomnia para enviar `Multipart Form` corretamente, foram feitos novos uploads com sucesso usando a rota padronizada:

```text
POST http://127.0.0.1:8000/api/v1/files/request-uploads
```

Com:

```text
analysis_request_id=ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0
campo de arquivo=files
```

### Upload DOCX duplicado

Foram enviados dois arquivos DOCX com o mesmo nome. A API aceitou ambos e gerou nome fisico unico para evitar conflito:

```text
DOCX file_id=cd447aa5-4f99-4b3b-a6e5-c9a61ee066da
file_name=contexto_teste_juridico.docx
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/contexto_teste_juridico.docx
file_size=38690
checksum=cb79abd94b34614a8490789b500d2588f8c0ab5843715a675b79e91e89a16371
```

```text
DOCX file_id=2547ef97-e904-44a2-9f63-1046d5a3118a
file_name=contexto_teste_juridico.docx
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/contexto_teste_juridico-1.docx
file_size=38690
checksum=cb79abd94b34614a8490789b500d2588f8c0ab5843715a675b79e91e89a16371
```

### Upload DOCX + PDF

Outro teste enviou um DOCX e um PDF no mesmo request:

```text
DOCX file_id=e4d30b10-65fd-421c-8af9-e3cac84ca944
file_name=contexto_teste_juridico.docx
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/contexto_teste_juridico-2.docx
file_size=38690
checksum=cb79abd94b34614a8490789b500d2588f8c0ab5843715a675b79e91e89a16371
```

```text
PDF file_id=fa238cff-587b-4cd2-9b1f-0bbb4d9a5d14
file_name=Relatorio_NEf_IA_API.pdf
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/Relatorio_NEf_IA_API.pdf
file_size=4040
checksum=0848db044bf7324dd6467af074fcf9f2dd1850441149e2d34a95833786b1b47b
```

### Upload PDF + XLSX

Foi testado upload de PDF junto com planilha XLSX:

```text
PDF file_id=524d207c-ab35-42bd-8f4f-b6119021e797
file_name=Relatorio_NEf_IA_API.pdf
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/Relatorio_NEf_IA_API-1.pdf
file_size=4040
checksum=0848db044bf7324dd6467af074fcf9f2dd1850441149e2d34a95833786b1b47b
```

```text
XLSX file_id=908aed12-05a8-493b-b481-7c942edfa254
file_name=planilha_teste.xlsx
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/planilha_teste-2.xlsx
file_size=4967
checksum=38f239ec50f4a7b1949c9c5881f7726d9456c27dde1feaa0fa4efb5034d79dbc
```

### Novo upload PDF + XLSX

Outro upload PDF + XLSX tambem foi validado:

```text
PDF file_id=1e75916b-47b2-4330-bf1d-2f5c70333d6c
file_name=Relatorio_NEf_IA_API.pdf
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/Relatorio_NEf_IA_API-2.pdf
file_size=4040
checksum=0848db044bf7324dd6467af074fcf9f2dd1850441149e2d34a95833786b1b47b
```

```text
XLSX file_id=7775a951-45ee-4640-b9e3-94ede64c876b
file_name=planilha_teste.xlsx
file_path=requests/ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0/uploads/planilha_teste-3.xlsx
file_size=4967
checksum=38f239ec50f4a7b1949c9c5881f7726d9456c27dde1feaa0fa4efb5034d79dbc
```

## Teste de download ZIP

A rota ZIP baixa arquivos ligados a uma execucao, nao diretamente todos os arquivos de um `analysis_request_id`.

Rota:

```text
GET /api/v1/external/executions/{execution_id}/files/download
```

Foi criada uma execucao de teste para validar o download ZIP com arquivos ja enviados.

Primeiro teste ZIP:

```text
execution_id=6750e013-4622-4062-878b-9858e606605a
```

Rota completa:

```text
GET http://127.0.0.1:8000/api/v1/external/executions/6750e013-4622-4062-878b-9858e606605a/files/download
```

Resultado:

```text
200 OK
content-type=application/zip
content-length=7324
filename=execution_6750e013-4622-4062-878b-9858e606605a_files.zip
```

Conteudo validado dentro do ZIP:

```text
input/planilha_teste.xlsx
input/Relatorio_NEf_IA_API.pdf
```

Segundo teste ZIP, vinculado aos arquivos mais recentes:

```text
execution_id=7c0fe287-3bec-40a1-b8b9-1abcbcdc6889
```

Rota completa:

```text
GET http://127.0.0.1:8000/api/v1/external/executions/7c0fe287-3bec-40a1-b8b9-1abcbcdc6889/files/download
```

Arquivos vinculados:

```text
input/planilha_teste.xlsx
input/Relatorio_NEf_IA_API.pdf
```

Observacao:

```text
O pacote gerado e ZIP, nao RAR.
```

## Conclusao dos testes de upload/download

- Upload multiplo esta funcionando pela rota `/api/v1/files/request-uploads`.
- A mesma rota deve ser usada tambem quando houver apenas um arquivo.
- O campo de arquivo deve ser sempre `files`.
- O campo `analysis_request_id` e obrigatorio no body multipart.
- Download individual por `file_id` esta funcionando.
- Download em pacote ZIP por `execution_id` esta funcionando quando a execucao possui arquivos vinculados.
- A API evita colisao de nomes no storage adicionando sufixos como `-1`, `-2`, `-3`.
- Erros anteriores no Insomnia foram causados por configuracao de request, principalmente:
  - `Content-Type` manual sem `boundary`;
  - uso de `/request-upload` com campo `files`;
  - ausencia de `analysis_request_id`;
  - token fora do escopo da automacao.

## Analise de impacto das mudancas

Foi feita uma verificacao para avaliar se as mudancas e testes prejudicaram outras funcoes do projeto.

### Validacoes executadas

Servicos Docker:

```text
postgres        healthy
redis           healthy
nef-ia-api      healthy
nef-ia-worker   running
```

Healthcheck da API:

```text
GET http://127.0.0.1:8000/health/live
Resultado: 200 OK
Resposta: {"status":"ok","service":"nef-ia-api"}
```

Check do Django:

```text
python manage.py check
Resultado: System check identified no issues (0 silenced).
```

Migrations Alembic:

```text
python -m alembic current
Resultado: 20260323_0013 (head)
```

Chave de criptografia:

```text
CREDENTIALS_ENCRYPTION_KEY validada localmente e dentro do container da API.
Resultado: Fernet OK.
```

Rotas testadas novamente:

```text
POST /api/v1/files/request-uploads
Resultado: upload OK

GET /api/v1/files/request-files/{file_id}/download
Resultado: 200 OK

GET /api/v1/external/executions/{execution_id}/files/download
Resultado: 200 OK
```

### Pontos que nao indicaram quebra

- API continuou saudavel apos as configuracoes.
- Django carregou as configuracoes sem erros.
- Worker continuou rodando.
- Redis continuou saudavel.
- Postgres continuou saudavel.
- Upload padronizado em `/request-uploads` continuou funcionando.
- Download individual por `file_id` continuou funcionando.
- Download ZIP por `execution_id` continuou funcionando.
- Alembic permaneceu no head.
- A chave Fernet atual e valida.

### Pontos de atencao identificados

#### Porta do Postgres no host

O `docker-compose.yml` esta expondo o Postgres em:

```text
5433:5432
```

Motivo:

```text
O host Windows ja tinha um Postgres local usando a porta 5432.
```

Impacto:

- Dentro dos containers, nada muda: `DB_HOST=postgres` e `DB_PORT=5432` continuam corretos.
- Para o Django local fora do Docker, foi usado `DJANGO_DB_PORT=5433`.
- Em outro ambiente, conferir se a porta `5433` faz sentido ou se deve voltar para `5432`.

#### CREDENTIALS_ENCRYPTION_KEY

A chave Fernet foi corrigida e validada.

Impacto:

- Novas credenciais podem ser criptografadas corretamente.
- Se existirem credenciais antigas criptografadas com outra chave, elas nao serao descriptografadas pela chave nova.
- Para producao, a chave deve ser definitiva, segura, armazenada em variavel de ambiente e nunca trocada sem processo de rotacao.

#### Dados de teste criados

Durante os testes, foram criados tokens, requests, uploads e execucoes artificiais.

Tokens de teste encontrados:

```text
integration::automacao-teste-insomnia
insomnia-upload-download-test
insomnia-teste-multiplos-arquivos
insomnia-teste-multiplos-arquivos-v2
```

Execucoes artificiais criadas para validar ZIP:

```text
6750e013-4622-4062-878b-9858e606605a
7c0fe287-3bec-40a1-b8b9-1abcbcdc6889
```

Request de teste principal:

```text
analysis_request_id=ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0
```

Quantidade observada:

```text
27 arquivos vinculados ao request de teste.
```

Impacto:

- Nao quebra a API.
- Pode poluir telas administrativas, metricas, listagens e historico.
- Antes de producao, recomenda-se remover ou revogar os tokens e registros de teste.

#### Automacao artificial antiga

Foi criada uma automacao de teste inicial:

```text
Insomnia Upload Download Test
```

Ela serviu apenas para testar upload/download inicial e apareceu sem runtime/prompt oficial completo.

Impacto:

- Nao deve ser usada para execucao real.
- Pode aparecer em telas/listagens como automacao incompleta.
- Recomenda-se limpar antes de producao.

### Conclusao da analise de impacto

Nao foi encontrada evidencia de quebra funcional causada pelas mudancas feitas para upload/download.

Estado validado:

- Upload OK.
- Download individual OK.
- Download ZIP OK.
- API OK.
- Django check OK.
- Worker/Redis/Postgres OK.
- Migrations OK.
- Fernet OK.

Recomendacao:

```text
As rotas de arquivo estao aptas para homologacao/staging.
Antes de producao, limpar dados de teste, revogar tokens de teste, manter chave Fernet definitiva e validar uma execucao real completa com provider.
```

## Tipos de arquivo

Pelo `.env`, as extensoes permitidas estao em:

```text
ALLOWED_FILE_EXTENSIONS=.xlsx,.csv,.pdf,.docx,.doc
```

Foram observados bloqueios esperados:

- `.json` -> `invalid_file_extension`
- `.txt` -> `invalid_file_extension`

Se for necessario aceitar `.json` ou `.txt`, ajustar `ALLOWED_FILE_EXTENSIONS` e conferir `ALLOWED_FILE_MIME_TYPES`.

## Comandos curl usados para validar

Upload multiplo:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/files/request-uploads `
  -H "Authorization: Bearer <IA_LIVE_TOKEN_DA_AUTOMACAO>" `
  -F "analysis_request_id=ebaf9398-7d10-41ef-8cd2-90a6f9e59ac0" `
  -F "files=@test_files/planilha_teste.xlsx" `
  -F "files=@test_files/pdf_teste_simples.pdf" `
  -F "files=@test_files/documento_teste_multiplos_arquivos.docx"
```

Download:

```powershell
curl.exe -L `
  -H "Authorization: Bearer <IA_LIVE_TOKEN_DA_AUTOMACAO>" `
  -o .tmp/download_new_auto.xlsx `
  http://127.0.0.1:8000/api/v1/files/request-files/0e96a005-4591-403e-a6d9-4b2ecbaae1c0/download
```

## Melhorias realizadas durante a preparacao

- Dependencias Python instaladas em `.venv`.
- Containers Docker da API, worker, Redis e Postgres validados.
- Postgres do Compose ajustado para `5433:5432` para evitar conflito com Postgres local.
- Migrations Alembic aplicadas.
- Seed basico da FastAPI executado.
- Migrations Django aplicadas.
- Usuario admin Django criado.
- `CREDENTIALS_ENCRYPTION_KEY` corrigida para uma chave Fernet valida.
- API e worker recriados para carregar a chave nova.
- Token bootstrap/integracao gerado e cadastrado no fluxo admin.
- Tokens operacionais `ia_live` criados para testes de automacao/arquivo.
- Testes de upload/download executados e validados.

## Observacoes para continuidade

- Nao gravar plaintext de tokens em arquivos versionados.
- Para cada automacao oficial, criar ou selecionar um token `ia_live` com permissao na mesma `automation_id`.
- A rota recomendada para clientes e `/api/v1/files/request-uploads`.
- O cliente deve sempre enviar `multipart/form-data` gerado automaticamente pela ferramenta HTTP.
- Para automacoes do tipo planilha, o arquivo principal da execucao deve ser `.csv` ou `.xlsx`; PDFs/DOCX podem ser usados como contexto conforme o fluxo de execucao.

## Nova funcionalidade adicionada: Banco de Talentos

Foi adicionada uma nova funcionalidade na FastAPI para leitura e estruturacao de curriculos.

Objetivo:

```text
Receber curriculos em PDF, DOCX ou texto puro e retornar um JSON estruturado com os dados extraidos do candidato.
```

Essa funcionalidade foi integrada na API existente, sem criar nova aplicacao e sem alterar a arquitetura principal.

## Rotas criadas

As novas rotas foram adicionadas no router principal da FastAPI.

Prefixo:

```text
/api/v1/talentos
```

### Parse de curriculo por texto puro

Rota:

```text
POST /api/v1/talentos/curriculos/parse-text
```

Autenticacao:

```text
Authorization: Bearer <TOKEN_VALIDO>
```

Body:

```json
{
  "texto": "conteudo do curriculo"
}
```

Comportamento:

- Recebe texto puro.
- Normaliza o conteudo.
- Extrai campos estruturados via regex e heuristicas locais.
- Retorna tambem o texto completo em `texto_extraido`.

### Parse de curriculo por arquivo

Rota:

```text
POST /api/v1/talentos/curriculos/parse
```

Autenticacao:

```text
Authorization: Bearer <TOKEN_VALIDO>
```

Body:

```text
Multipart Form
```

Campos:

```text
file   File   curriculo.pdf
```

ou

```text
file   File   curriculo.docx
```

Comportamento:

- Aceita apenas `.pdf` e `.docx`.
- Extrai texto do arquivo.
- Rejeita arquivo vazio.
- Rejeita extensao invalida.
- Retorna o mesmo JSON estruturado da rota `parse-text`.

## Estrutura de resposta

As duas rotas retornam uma resposta no formato:

```json
{
  "dados_pessoais": {
    "nome": null,
    "email": null,
    "telefone": null,
    "cidade": null,
    "estado": null,
    "linkedin": null,
    "github": null
  },
  "objetivo": null,
  "resumo_profissional": null,
  "experiencias": [],
  "formacao": [],
  "cursos": [],
  "habilidades": [],
  "idiomas": [],
  "certificacoes": [],
  "texto_extraido": "texto bruto extraido"
}
```

## Campos extraidos pelo parser

O parser atual foi preparado para uso local por heuristica e para futura troca por IA, se necessario.

Campos atualmente extraidos:

- `nome`
- `email`
- `telefone`
- `cidade`
- `estado`
- `linkedin`
- `github`
- `objetivo`
- `resumo_profissional`
- `experiencias`
- `formacao`
- `cursos`
- `habilidades`
- `idiomas`
- `certificacoes`

Regras atuais:

- Campos nao encontrados retornam `null` ou lista vazia.
- O texto completo permanece disponivel em `texto_extraido`.
- Links de LinkedIn e GitHub sao normalizados para URL.
- Telefone brasileiro e normalizado para formato legivel quando possivel.

## Servicos adicionados

Para suportar a funcionalidade, foram criados os seguintes componentes:

Arquivo:

```text
app/api/routes/talent_bank.py
```

Responsabilidade:

- expor as rotas do Banco de Talentos
- manter a rota fina
- delegar extracao e parsing para servicos

Arquivo:

```text
app/services/file_text_extractor.py
```

Responsabilidade:

- extrair texto de PDF com `pypdf`
- extrair texto de DOCX com `python-docx`
- validar extensao
- validar arquivo vazio
- retornar erro claro para falha de extracao

Arquivo:

```text
app/services/resume_parser_service.py
```

Responsabilidade:

- limpar e normalizar o texto
- aplicar regex e heuristicas locais
- montar a resposta estruturada do curriculo

Arquivo:

```text
app/schemas/resume.py
```

Responsabilidade:

- definir os schemas Pydantic da funcionalidade

## Dependencias utilizadas

As dependencias necessarias para a funcionalidade ja estavam disponiveis no projeto:

```text
python-multipart
pypdf
python-docx
```

Nao foi necessario criar projeto novo nem duplicar router principal.

## Fluxo correto de autenticacao para testes no Insomnia

Para testar o Banco de Talentos no Insomnia, foi validado o seguinte fluxo:

### 1. Login administrativo

Rota:

```text
POST /api/v1/admin/auth/login
```

Body:

```json
{
  "email": "admin@nef.local",
  "password": "123456"
}
```

Resposta:

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_at": "..."
}
```

### 2. Criar token de integracao

Rota:

```text
POST /api/v1/admin/integration-tokens
```

Header:

```text
Authorization: Bearer <ACCESS_TOKEN_JWT_ADMIN>
```

Body:

```json
{
  "name": "talent-bank-insomnia"
}
```

Exemplo validado:

```json
{
  "id": "bd17d78b-5eaf-4c5f-bbde-144afd57997d",
  "name": "talent-bank-insomnia",
  "token": "ia_int_uWaVazIL4Gp0WB0RXSDCMgO7jGvjnO6Km8US6DYbE5AcHWDtqmEcmx3TApt5t",
  "is_active": true,
  "created_by_user_id": "12304569-58a3-4731-b145-7c543d36b34d",
  "created_at": "2026-04-28T14:16:09.539017Z"
}
```

### 3. Usar o token criado nas rotas do Banco de Talentos

Header:

```text
Authorization: Bearer <TOKEN_IA_INT_OU_TOKEN_VALIDO>
```

Observacao importante:

- Para as rotas administrativas, usar o `access_token` JWT retornado no login admin.
- Para as rotas do Banco de Talentos, foi validado o uso do token `ia_int_...` criado via `/admin/integration-tokens`.
- Token operacional antigo invalido pode retornar erro de autenticacao.

## Teste validado no Insomnia: parse-text

Rota:

```text
POST http://127.0.0.1:8000/api/v1/talentos/curriculos/parse-text
```

Headers:

```text
Authorization: Bearer <TOKEN_VALIDO>
Content-Type: application/json
```

Body usado no teste:

```json
{
  "texto": "Maria Silva\nSao Paulo / SP\nmaria.silva@email.com\n(11) 98765-4321\nhttps://linkedin.com/in/mariasilva\nhttps://github.com/mariasilva\nObjetivo\nAtuar como desenvolvedora backend.\nHabilidades\n- Python\n- FastAPI\nIdiomas\n- Ingles - Fluente"
}
```

Resultado observado:

```json
{
  "nome": "Maria Silva",
  "email": "maria.silva@email.com",
  "telefone": "(11) 98765-4321",
  "linkedin": "https://linkedin.com/in/mariasilva",
  "github": "https://github.com/mariasilva",
  "objetivo": "Atuar como desenvolvedora backend.",
  "habilidades": ["Python", "FastAPI"],
  "idiomas": ["Ingles:Fluente"]
}
```

## Teste validado no Insomnia: arquivo invalido

Rota:

```text
POST http://127.0.0.1:8000/api/v1/talentos/curriculos/parse
```

Resultado observado ao enviar arquivo com extensao nao permitida:

```json
{
  "error": {
    "code": "invalid_resume_file_extension",
    "message": "Unsupported resume file extension.",
    "details": {
      "allowed_extensions": [".docx", ".pdf"]
    }
  }
}
```

## Erros previstos da nova funcionalidade

Erros esperados nas rotas do Banco de Talentos:

- `missing_file`
- `invalid_resume_file_extension`
- `empty_resume_file`
- `resume_text_not_extractable`
- `empty_resume_text`
- `invalid_admin_token` quando token administrativo for usado incorretamente

## Status da funcionalidade

Estado validado:

- rota integrada no router principal
- `parse-text` funcionando
- autenticacao funcionando
- tratamento de extensao invalida funcionando
- testes automatizados passando localmente
- stack Docker da API, worker, Redis e Postgres ativa durante a validacao

## Incidente: Erro 500 no Django em producao (2026-04-29)

### Sintoma

O Django retornava erro 500 em todas as paginas apos deploy no servidor de producao (`/opt/nef-ia-api`).

### Causa raiz

O arquivo `.env` no servidor tinha variaveis duplicadas e conflitantes para banco de dados.

Problemas encontrados:

```text
DB_HOST aparecia duas vezes:
  - DB_HOST=postgres       (correto para containers Docker)
  - DB_HOST=host.docker.internal  (errado, causava falha de conexao da API)

DJANGO_DB_HOST aparecia duas vezes:
  - DJANGO_DB_HOST=127.0.0.1  (correto para Django no host)
  - DJANGO_DB_HOST=postgres   (errado, Django no host nao enxerga hostname Docker)

DJANGO_DB_PORT=5432 em vez de 5433
  - O Postgres no Docker estava mapeado para 5433 no host
  - Django tentava conectar na 5432 e falhava

Faltavam variaveis obrigatorias do Django:
  - DJANGO_DB_USER
  - DJANGO_DB_PASSWORD
  - DJANGO_DB_ENGINE
  - DJANGO_ALLOWED_HOSTS
  - FASTAPI_BASE_URL
```

### Por que isso acontece

O Django roda fora do Docker (direto no host via `venv311` + Gunicorn).
A API FastAPI e o worker rodam dentro do Docker Compose.

Isso significa que cada um precisa de configuracoes diferentes para acessar o Postgres:

```text
API/worker (dentro do Docker):
  DB_HOST=postgres        <- nome do servico Docker
  DB_PORT=5432            <- porta interna do container

Django (fora do Docker, no host):
  DJANGO_DB_HOST=127.0.0.1  <- localhost do servidor
  DJANGO_DB_PORT=5433        <- porta mapeada pelo Docker para o host
```

Se o `.env` misturar esses valores ou tiver duplicatas, o Django ou a API conectam no banco errado ou nao conectam.

### Solucao aplicada

**Passo 1: Expor o Postgres para o host no docker-compose.yml**

Adicionado o bloco `ports` no servico `postgres`:

```yaml
postgres:
  ports:
    - "5433:5432"
```

Isso faz o Postgres do Docker ficar acessivel em `127.0.0.1:5433` no servidor host.

**Passo 2: Limpar e corrigir o `.env`**

O arquivo foi reescrito sem duplicatas, separando claramente as variaveis da API e do Django:

```env
# Banco da API (containers Docker)
DB_HOST=postgres
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=Nef@2026!
DB_NAME=nef-ia-api

# Banco do Django (host)
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=5433
DJANGO_DB_USER=postgres
DJANGO_DB_PASSWORD=Nef@2026!
DJANGO_DB_NAME=nef-ia-web
DJANGO_DB_ENGINE=django.db.backends.postgresql
DJANGO_ALLOWED_HOSTS=*

# Integracao
FASTAPI_BASE_URL=http://127.0.0.1:8000
```

**Passo 3: Reiniciar containers e servico Django**

```bash
docker compose up -d --build
systemctl restart nef-ia-django.service
```

**Passo 4: Validar conexao do Django**

```bash
python manage.py check
python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('db ok')"
```

Resultado:

```text
System check identified no issues (0 silenced).
db ok
```

### Como reescrever o .env via terminal sem editor

Se o arquivo estiver com conflitos e precisar ser substituido inteiro, usar heredoc no terminal:

```bash
cat > /opt/nef-ia-api/.env << 'EOF'
... conteudo correto ...
EOF
```

Copiar o bloco inteiro (do `cat` ate o `EOF` final) e colar de uma vez no terminal. O shell grava o arquivo sem abrir editor.

### Onde o Gunicorn do Django e gerenciado

O Django em producao roda via `systemd`, nao via Docker:

```bash
systemctl status nef-ia-django.service
systemctl restart nef-ia-django.service
journalctl -u nef-ia-django.service -n 50 --no-pager
```

Apos correcao do `.env`, e obrigatorio reiniciar o servico. O `kill -HUP` nao recarrega variaveis de ambiente — ele so recria workers herdando o ambiente antigo do processo master.

### Resumo do que causa erro 500 no Django neste ambiente

| Causa | Efeito |
|---|---|
| `DJANGO_DB_HOST=postgres` no host | Django nao resolve hostname Docker |
| `DJANGO_DB_PORT=5432` sem mapeamento | Porta nao acessivel no host |
| `DB_HOST=host.docker.internal` no Linux | Containers nao resolvem, API falha |
| Variaveis duplicadas no `.env` | Valor errado pode prevalecer |
| Reiniciar com `kill -HUP` | Nao recarrega `.env`, mantem config antiga |
