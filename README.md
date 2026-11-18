# Job Hunter AI

Implementação incremental do [SDD](SDD.md) e dos [requisitos](REQUIREMENTS.md).
Plano e dependências por fase em [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Desenvolvimento local

Python 3.12 é a versão do container. O código também suporta Python 3.11 para
testes locais. PostgreSQL é a fonte de verdade em execução pelo Compose.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
New-Item -ItemType Directory -Force var
$env:DATABASE_URL = 'sqlite:///var/local.db'
$env:API_TOKEN = 'escolha-um-token-local-longo'
.venv/Scripts/alembic upgrade head
.venv/Scripts/flask --app job_hunter:create_app run
```

Use `Authorization: Bearer <API_TOKEN>` nas rotas `/api/v1/*`.
O token vazio bloqueia todas as rotas da API. Healthchecks são públicos e não
expõem configuração. `/health/ready` exige banco acessível e migração aplicada.

```powershell
.venv/Scripts/python -m pytest
.venv/Scripts/ruff check .
.venv/Scripts/ruff format --check .
```

## Docker

Copie `.env.example` para `.env`, configure `API_TOKEN` e execute:

```powershell
docker compose up --build -d
docker compose exec api alembic current
docker compose logs worker beat
```

API em `http://127.0.0.1:5000`; banco e Redis não publicam portas.
A migração roda antes da API e do worker. Credenciais `local` do PostgreSQL
são exclusivamente para desenvolvimento. Não use esse Compose em produção.

## Estado da implementação

- Fase 1: núcleo transacional inicial, healthchecks, autenticação por token,
  máquina de estados, infraestrutura e testes de migração.
- Envio real não implementado. `EMAIL_SEND_ENABLED` diferente de `false` bloqueia
  inicialização. Não existem endpoints de aprovação/envio nesta fase.
- OpenAI e fontes externas ainda sem integração; Sheets desabilitado por padrão.
- PostgreSQL/Redis/Compose validados; resultados e comandos de smoke abaixo.

## Descoberta simulada (fase 2a)

Este incremento implementa a parte offline da fase 2: conector fixture, URLs
canônicas, deduplicação por fonte/ID ou URL, gates de elegibilidade, fatos
verificados e score determinístico com evidências. Os pesos seguem o SDD;
requisitos sem comprovação ficam `unknown` e categorias ausentes não ganham pontos.
Não há matching semântico ou acesso à OpenAI nesta versão.

```powershell
flask --app job_hunter:create_app demo
# Repetir retorna created=0, duplicates=3.
```

O comando cria exclusivamente um perfil sintético identificado como demo.
Não cadastra fatos profissionais do usuário. Para habilitar também a execução
manual pela API e o agendamento de fixtures, configure `DISCOVERY_MODE=fixture`
e reinicie os processos. O padrão `disabled` mantém o scheduler sem fonte ativa.

- `POST /api/v1/discovery/run`: executa somente o lote fixture configurado.
- `GET /api/v1/jobs`: lista até 100 vagas.
- `GET /api/v1/jobs/{id}/match`: score, gates e evidências verificadas.

As rotas exigem token. A execução manual é síncrona neste incremento; o Beat
publica a mesma descoberta no worker às 08h em `America/Bahia`.
Cada fonte registra resultado, falhas não expõem exceções/segredos, e cada vaga
nova grava matching, auditoria e outbox na mesma transação. A outbox tem consumidor Sheets, desabilitado por padrão. Reprocessamento não atualiza anúncios existentes;
revalidação/histórico de alterações será um incremento antes de fontes reais.

## Próximos incrementos

- Fase 2b: fontes reais autorizadas, paginação/backoff, filtros configuráveis,
  revalidação de anúncios e integração OpenAI com schema, limites e credenciais.
- Fase 3b: consentimento inicial Google e teste com uma planilha real.
- Fase 4: requer DOCX mestre real, fatos confirmados e manifesto aprovado.
- Fases 5/6: aprovação por hash, Gmail, limites e operação assistida.

A implementação atual não atende ainda ao fluxo completo de candidatura.

## Validação executada

- Fase 1: 8 testes aprovados; upgrade/downgrade/upgrade Alembic em SQLite.
- Fase 2a: 16 testes no total, lint e formatação aprovados.
- Compose: build Python 3.12, migração PostgreSQL, API saudável, worker e Beat ativos.
- Smoke integrado: descoberta HTTP, replay sem duplicação, dois gates de
  elegibilidade, três matches/outbox e tarefa processada pelo worker via Redis.

Para repetir o smoke num ambiente de desenvolvimento com apenas os dados demo:

```powershell
$env:DISCOVERY_MODE = 'fixture'
docker compose up --build -d
Get-Content -Raw scripts/smoke_compose.py | docker exec -i job-hunter-ai-api-1 python -
docker compose exec api alembic check
```

O nome do container acima pressupõe o projeto Compose `job-hunter-ai`.
O smoke grava somente fixtures no banco configurado. Use um ambiente de teste.


## Sheets e outbox (fase 3a)

O adaptador Google Sheets implementa as abas `Vagas`, `Candidaturas` e
`Configurações`, valida seus cabeçalhos e faz upsert pelo ID da primeira coluna.
As células são escritas com `valueInputOption=RAW`: conteúdo de fontes externas
é tratado como dado, inclusive quando começa com `=`. Referências oficiais:
[escrita de valores](https://developers.google.com/workspace/sheets/api/guides/values)
e [renovação OAuth](https://google-auth.readthedocs.io/en/latest/reference/google.auth.transport.requests.html).

A configuração padrão `SHEETS_SYNC_ENABLED=false` impede chamadas ao Google.
O backend não reutiliza automaticamente conexões Google do ChatGPT.
Para uso real será necessário obter consentimento OAuth separado, habilitar
Sheets API no projeto Google e selecionar uma planilha editável pela conta.
O fluxo inicial de consentimento ainda não tem interface nesta versão; o
adaptador recebe um refresh token autorizado com o escopo exclusivo
`https://www.googleapis.com/auth/spreadsheets`.

As variáveis estão em `.env.example`. Client secret e refresh token devem ser
injetados por ambiente/secret manager, nunca versionados. Access tokens existem
apenas em memória; o adaptador não persiste credenciais nem registra respostas
sensíveis do provedor. A integração não solicita permissões Gmail/Drive.

Após configurar e habilitar a integração, as opções de execução são:

```powershell
flask --app job_hunter:create_app sheets-sync
# Após corrigir uma falha permanente ou esgotar as tentativas:
flask --app job_hunter:create_app sheets-sync --retry-failed
```

Também há `POST /api/v1/integrations/sheets/sync`, autenticado por Bearer token.
Sem habilitação ou configuração, retorna `409`. Cada execução processa até 25
registros. A resposta informa `processed`, `failed` e `busy`; uma execução
concorrente retorna `409` com `busy=true`. Falhas de eventos retornam contadores
no JSON e ficam registradas na auditoria e na outbox.

O Beat executa `job_hunter.sheets_sync` a cada 60 segundos. O consumidor usa um
lock transacional PostgreSQL para serializar os escritores, marca conclusão
somente após confirmação da escrita e aplica backoff de 60 segundos até 16
minutos, com no máximo cinco tentativas. Erros permanentes exigem intervenção
pelo comando de retry. Um timeout ou rollback após a escrita permite repetir o
upsert sem criar outra linha. O estado da vaga/candidatura não é alterado.

Use uma planilha dedicada ao backend. Preserve os cabeçalhos e IDs; não
reordene linhas enquanto uma sincronização estiver em andamento. O lock
coordena instâncias que compartilham o mesmo PostgreSQL, não escritores
independentes nem edições simultâneas pela interface Google Sheets.
Os campos de aprovação/envio/CV permanecem vazios até suas fases de domínio.
O backend não importa alterações da planilha para o banco.

A migração `0002` adiciona metadados de retry e índice da fila, preservando os
eventos existentes. A suíte atual tem 31 testes. Para testar também PostgreSQL
com provedor simulado e schema isolado:

```powershell
Get-Content -Raw scripts/smoke_sheets.py | docker exec -i job-hunter-ai-api-1 python -
```

Esse smoke não acessa o Google: testa migrações, retry após confirmação perdida,
rollback e concorrência, e remove somente o schema temporário que ele criou.

Validação desta fase: 31 testes aprovados, lint/formatação aprovados, smoke
PostgreSQL de Sheets aprovado e smoke de regressão da descoberta/Redis/Celery
aprovado. `alembic check` não detectou divergências no PostgreSQL. Nenhuma
conta Google foi conectada nem planilha real modificada durante os testes.
