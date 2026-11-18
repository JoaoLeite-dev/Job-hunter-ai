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
- Fase 5: prévia e aprovação individual do pacote por hash, seguida do envio Gmail autorizado.
- Fase 6: limites, monitoramento e piloto assistido.

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

## Currículo privado e manifesto (fase 4a)

Coloque o DOCX mestre em `var/private/resumes/`. A pasta inteira, seus manifests,
cópias e recibos estão no `.gitignore`; DOCX na raiz também são ignorados.
O `.dockerignore` impede que esses arquivos entrem no build da imagem. No Compose,
a pasta é montada em `/app/var/private/resumes`, sem incorporar dados pessoais
na imagem. O caminho é configurável por `RESUME_STORAGE_ROOT`.

```powershell
flask --app job_hunter:create_app resume-inspect --source-name cv-master.docx
flask --app job_hunter:create_app profile-create --name "Perfil principal"
flask --app job_hunter:create_app resume-import --source-name cv-master.docx --profile-id <id>
```

A inspeção não precisa de perfil nem de acesso ao banco. Ela cria uma cópia
binária idêntica em `templates/<sha256>/master.docx`, o inventário completo em
`manifest.draft.json` e uma seleção legível em `manifest.review.md`, todos
privados. O arquivo fornecido não é regravado. Reimportações com o mesmo conteúdo
e perfil reutilizam o registro; cópias corrompidas são bloqueadas sem sobrescrita.
Um rollback de banco pode deixar um snapshot privado sem registro: reimporte
para associá-lo novamente, sem alterar o original.

O manifesto identifica cada nó textual, caminho XML, estilo, texto original,
hash e limite de caracteres. As sugestões são conservadoras: trechos narrativos
de resumo, bullets sem números e descrições de projetos. Identificação, contatos,
datas, números, cabeçalhos, formação, listas de tecnologias e estruturas complexas
ficam protegidos. Campos em tabelas ou com hyperlinks/objetos exigem mapeamento
manual em um incremento futuro. Alterações rastreadas impedem candidatar campos.

Rotas autenticadas adicionadas:

- `POST /api/v1/resume-templates/import`: `{profile_id, source_name}`; aceita
  somente um nome de arquivo dentro da pasta privada, sem caminhos arbitrários.
- `GET /api/v1/resume-templates/{id}`: metadados e manifesto para revisão.
- `POST /api/v1/resume-templates/{id}/approve-manifest`: `{manifest_hash, field_ids}`;
  autoriza exclusivamente os campos selecionados. Hash divergente, template
  modificado ou seleção de campo protegido retorna `409`.

O manifesto proposto tem `approval=null`. A autorização é uma ação explícita do
usuário, vinculada ao template exato. A aprovação de campos não confirma fatos,
não valida o layout e não autoriza candidatura ou envio. A API não oferece
download público nem geração de variantes neste incremento. O JSON retornado
contém texto privado: use a API apenas no ambiente local autenticado.

A migração `0003` adiciona o cadastro de templates. Os testes usam somente dados
sintéticos, incluindo runs com estilos distintos, tabelas, cabeçalhos, dados
protegidos, arquivos inválidos, macros, XML inseguro e tentativas de path traversal.
O smoke abaixo testa importação privada e migração PostgreSQL num schema isolado:

```powershell
Get-Content -Raw scripts/smoke_resume.py | docker exec -i job-hunter-ai-api-1 python - cv-master.docx
```

Validação executada: 55 testes aprovados, lint/formatação aprovados, importação
do DOCX real preservando o SHA-256, reimportação idempotente, bloqueio de campos
protegidos e upgrade/downgrade/upgrade no PostgreSQL aprovados. A descoberta e o
worker também passaram no teste de regressão. Nenhum fato profissional nem campo
do CV real foi autorizado automaticamente; nenhum trecho do CV foi versionado.

As fases 4b1 e 4b2 implementam a edição de campos autorizados, fatos confirmados, exportação
PDF e validações estrutural, visual e ATS. Não foi gerada variante adaptada neste
incremento 4a; a validação visual foi adicionada na fase 4b2 descrita abaixo.

## Edição controlada e fatos confirmados (fase 4b1)

A autorização dos campos permanece separada da confirmação dos fatos. Foram
adicionadas rotas autenticadas para registrar ações explícitas do proprietário:

- `POST /api/v1/resume-templates/{id}/confirm-facts`: `{manifest_hash, confirmed: true}`
  confirma o conteúdo da versão exata do CV. Registra os trechos literais e extrai
  tecnologias somente de listas explicitamente identificadas. Não infere stacks,
  senioridade, métricas ou experiências ausentes.
- `POST /api/v1/resume-templates/{id}/wording-facts`: `{manifest_hash, field_id, claim,
  confirmed: true}` confirma uma redação específica para um campo autorizado.

O editor inicial exige uma redação exata confirmada para cada alteração. Um ID de
fato sobre uma tecnologia isolada não é evidência suficiente para uma frase nova.
A integração semântica com IA continua pendente; nenhuma chamada OpenAI é feita.
O aceite da redação é uma confirmação factual, ainda separado da aprovação final
individual do pacote de candidatura.

`POST /api/v1/jobs/{job_id}/resume-variants` recebe `{template_id, edits}`, com
cada edição contendo `field_id`, `original_text`, `proposed_text` e
`supporting_fact_ids`. A geração exige template autorizado, fatos do mesmo perfil,
confirmação vinculada ao campo/template, vaga ativa verificada nas últimas 24h e
match sem hard gate com score no mínimo `MATCH_PREPARE_THRESHOLD` (padrão 75).

O editor usa offsets de bytes dos nós `w:t`, preservando o XML fora dos textos
editados. Estilos, atributos, prefixos de namespaces, runs e partes protegidas
não são serializados novamente. Limites de tamanho, números novos, contatos,
controles, campos protegidos e alterações sem evidência são bloqueados.
A validação estrutural compara cada parte do pacote e a ordem do texto extraído.
Isso não substitui validação de layout nem assegura compatibilidade universal ATS.

A migração `0004` registra variantes, hashes, plano e versões de evidências.
Repetir o mesmo plano reutiliza a variante; corrupção do arquivo, revogação de um
fato ou mudança de versão de evidência bloqueiam sua consulta/uso. Metadados ficam
em `GET /api/v1/resume-variants/{id}`. Os arquivos permanecem na pasta privada.
As respostas não aceitam flags de validação enviadas pelo cliente.

Antes da validação da fase 4b2, as variantes têm estado `validation_pending`. Na entrega 4b1, a renderização e os
testes PDF/visuais ainda estavam pendentes. O relatório inicial informa
`not_run` para essas verificações e `can_approve_application=false`.
Nenhuma variante real do usuário foi gerada para vagas simuladas.

Validação: 86 testes aprovados, lint/formatação aprovados e smoke com editor,
revogação, replay e migrações em PostgreSQL isolado aprovado:

```powershell
Get-Content -Raw scripts/smoke_resume_editor.py | docker exec -i job-hunter-ai-api-1 python -
```

## PDF e validação visual ATS (fase 4b2)

O runtime Docker inclui LibreOffice Writer, fontes Carlito/Liberation e Poppler;
PyMuPDF é usado para analisar o PDF. `RESUME_RENDER_ENABLED=true` habilita a
validação no Compose. Para execução nativa sem esse runtime, mantenha a variável
em `false`. O caminho do conversor é configurado no servidor por
`LIBREOFFICE_BINARY`, nunca recebido do cliente.

Depois de criar uma variante, execute:

- `POST /api/v1/resume-variants/{id}/validate`, com corpo vazio ou `{}`.
- `GET /api/v1/resume-variants/{id}` para consultar o resultado e os hashes.
- `GET /api/v1/resume-variants/{id}/pdf` para baixar a prévia autenticada.

As rotas exigem Bearer token. Resultados de validação enviados pelo cliente são
rejeitados. O download verifica o hash do PDF e as evidências atuais e envia
`Cache-Control: private, no-store`. Um PDF reprovado pode ser baixado para revisão,
mas não libera a candidatura. O corpo da resposta informa `validation_complete`;
a aprovação de candidatura continuará indisponível até a fase 5.

Cada conversão usa uma cópia temporária, um perfil LibreOffice exclusivo e um
timeout de 45 segundos. Em timeout, o grupo de processos é encerrado no Linux.
Tokens OAuth, chave de API e credenciais do banco não são herdados pelo conversor.
Recursos externos vinculados, objetos incorporados, SVG e campos de carregamento
externo são bloqueados; hyperlinks usuais de contato HTTP(S), mailto e tel são
preservados. O DOCX mestre e os arquivos de origem não são regravados.

Mestre e variante são renderizados pela mesma engine. As verificações incluem:

- Mesma quantidade e dimensões de páginas, texto dentro da página e posições de
  âncoras protegidas, imagens e formas, com tolerância de 1,5 ponto.
- Texto editado contido na área original, sem deslocar os demais campos.
- Extração de todos os campos em ordem de leitura e comparação do texto completo
  do PDF, descontando somente as alterações autorizadas. Texto extra também falha.
- Integridade do mestre, do DOCX, das evidências e do PDF, verificada novamente
  depois da conversão. A versão da engine e os hashes da baseline ficam no relatório.

`validated` exige aprovação de todas as cinco verificações: factual, estrutural,
texto DOCX, visual e texto PDF. Qualquer falha mantém `validation_failed`.
A renderização desabilitada mantém o rascunho pendente; uma falha de conversão
produz um código sanitizado no relatório. Repetir uma validação já aprovada
reutiliza o PDF íntegro. Fatos revogados ou alterados continuam bloqueando o uso.

A avaliação visual é automatizada e conservadora, baseada em geometria e extração
pela engine registrada. Ela complementa a revisão humana do pacote; não declara
compatibilidade com todo ATS nem equivalência entre todas as versões do Word.
Mudanças intencionais de estrutura/paginação continuam fora da autorização atual.

Parâmetros e interfaces seguem as referências oficiais de
[LibreOffice](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html)
e [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html).

Validação executada: 107 testes aprovados, lint e formatação aprovados. O smoke
com LibreOffice real e PostgreSQL isolado aceita uma edição válida, bloqueia uma
alteração que quebra o layout, verifica replay e o download privado:

```powershell
Get-Content -Raw scripts/smoke_pdf.py | docker exec -i job-hunter-ai-api-1 python -
```

As imagens de QA ficam privadas em `var/private/resumes/qa/synthetic-render/`.
Também foi verificada a conversão da baseline do mestre real: duas páginas,
44 âncoras e extração textual aprovadas, com inspeção das imagens e SHA-256 do
DOCX inalterado. Isso valida a baseline do ambiente, não uma adaptação real para
vaga. Nenhuma variante do CV pessoal foi gerada para candidaturas fictícias.


## Interface de acompanhamento ? fase UI-1

O painel React ? servido pelo pr?prio Flask em `/`, com as telas Vis?o geral,
Vagas, Curr?culo, Candidaturas, Atividade e Integra??es. Inclui busca e filtro de
vagas, motivos do score, hist?rico, campos autorizados e pr?via PDF autenticada do
mestre. Atualiza os dados a cada 30 segundos enquanto a aba est? vis?vel.

O acesso usa o `API_TOKEN` do ambiente: digite-o na tela de entrada. A sess?o tem
cookie HttpOnly e SameSite Strict; opera??es pela interface exigem CSRF. O token
n?o fica no HTML nem no armazenamento do navegador. Configure um
`UI_SESSION_SECRET` aleat?rio e est?vel para manter sess?es entre reinicializa??es;
em HTTPS use `UI_COOKIE_SECURE=true`. As APIs tamb?m continuam aceitando Bearer.

Para compilar localmente:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

O Dockerfile agora compila o frontend em um est?gio Node separado e inclui os
arquivos no pacote Python. Depois de uma atualiza??o autorizada do Compose, a
interface ser? servida na mesma porta da API. **A atualiza??o dos containers foi
recusada pelo controle de execu??o nesta sess?o; essa nova imagem ainda n?o foi
validada nem aplicada ao Docker.**

Para a demonstra??o desta sess?o, est? dispon?vel uma pr?via em
`http://127.0.0.1:5001`, com SQLite privado criado a partir de uma leitura dos dados
existentes. Suas a??es afetam apenas essa c?pia; containers e PostgreSQL atuais
permanecem intactos. Essa pr?via usa o PDF verdadeiro da baseline j? validada do
mestre, vinculado ao hash do DOCX; novas convers?es de variantes ficam indispon?veis
nesse processo. O processo de pr?via ? tempor?rio e precisa ser reiniciado ap?s
encerrar a sess?o de desenvolvimento.

As tr?s vagas s?o simuladas e os scores pertencem ao perfil sint?tico. A interface
mostra essa origem. Seu CV real aparece com 78 fatos confirmados e cinco campos
autorizados. Fontes reais, OpenAI, aprova??o de pacotes e envio Gmail continuam
pendentes; nenhum e-mail ? enviado.

Valida??o: 114 testes Python, Ruff, TypeScript, build Vite e formata??o aprovados.
Playwright com Chromium verificou login/logout, prote??o da API, filtros, detalhes,
demonstra??o idempotente, cinco campos, PDF real e as seis telas. Capturas em
1487?1058 e 390?844 inspecionadas; sem erros JavaScript/console ou transbordamento
horizontal no celular. O navegador integrado indispon?vel motivou esse fallback.
Capturas e relat?rio ficam fora do Git em `%TEMP%/jobhunter-ui-qa/`.

Refer?ncia: [conceito visual](docs/design/dashboard-concept.png) e
[brief](docs/design/BRIEF.md). Compara??o visual conclu?da para sidebar, cabe?alho,
m?tricas, tabela e pain?is inferiores, incluindo tipografia e cores. Diferen?as
intencionais: score real 40 para Demo Unknown, hor?rios/eventos reais e aviso de
pr?via isolada; texto e ?cones nativos mant?m a estrutura do conceito.
