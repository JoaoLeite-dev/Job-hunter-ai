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
