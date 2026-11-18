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
- Não há acesso a OpenAI, Google ou fontes externas. CVs e segredos não são versionados.
- Validação PostgreSQL/Redis/Compose deve ser registrada após execução real.

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
nova grava matching, auditoria e outbox na mesma transação. A outbox aguarda o
consumidor Sheets da fase 3. Reprocessamento não atualiza anúncios existentes;
revalidação/histórico de alterações será um incremento antes de fontes reais.

## Próximos incrementos

- Fase 2b: fontes reais autorizadas, paginação/backoff, filtros configuráveis,
  revalidação de anúncios e integração OpenAI com schema, limites e credenciais.
- Fase 3: OAuth Google Sheets e consumidor idempotente da outbox.
- Fase 4: requer DOCX mestre real, fatos confirmados e manifesto aprovado.
- Fases 5/6: aprovação por hash, Gmail, limites e operação assistida.

A implementação atual não atende ainda ao fluxo completo de candidatura.

## Valida??o executada

- Fase 1: 8 testes aprovados; upgrade/downgrade/upgrade Alembic em SQLite.
- Fase 2a: 16 testes no total, lint e formata??o aprovados.
- Compose: build Python 3.12, migra??o PostgreSQL, API saud?vel, worker e Beat ativos.
- Smoke integrado: descoberta HTTP, replay sem duplica??o, dois gates de
  elegibilidade, tr?s matches/outbox e tarefa processada pelo worker via Redis.

Para repetir o smoke num ambiente de desenvolvimento com apenas os dados demo:

```powershell
$env:DISCOVERY_MODE = 'fixture'
docker compose up --build -d
Get-Content -Raw scripts/smoke_compose.py | docker exec -i job-hunter-ai-api-1 python -
docker compose exec api alembic check
```

O nome do container acima pressup?e o projeto Compose `job-hunter-ai`.
O smoke grava somente fixtures no banco configurado. Use um ambiente de teste.
