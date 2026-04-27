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
