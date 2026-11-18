# Operação e busca de vagas local

Aplicação, painel, PostgreSQL, Redis, workers e arquivos permanecem no computador
do usuário. Não haverá deploy ou hospedagem em nuvem. APIs de vagas e, futuramente,
OpenAI/Google são serviços externos consultados pela aplicação local. Isso não
significa inferência GPT offline. O banco transacional é local.

O Compose publica somente o painel/API em `127.0.0.1:5000`. PostgreSQL e Redis
permanecem na rede interna; o volume `pgdata` guarda o banco no computador.
O ambiente local foi atualizado nesta fase e substitui a prévia da porta 5001.

## Fonte real

A busca usa a [API pública da Remotive](https://github.com/remotive-com/remote-jobs-api).
Consulta somente o endpoint fixo HTTPS de desenvolvimento, sem enviar dados do
currículo. O conector não segue redirects nem visita URLs retornadas, limita
tempo/tamanho da resposta e converte HTML em texto, descartando scripts. A tela
identifica a fonte e preserva o link Remotive de cada anúncio. A API informa vagas
ativas com atraso de 24 horas. A data exibida representa observação no feed, não
verificação independente no site da empresa.

Configuração no `.env` privado:

```dotenv
DISCOVERY_MODE=live
DISCOVERY_PROFILE_ID=
DISCOVERY_ROLES=frontend,front end,backend,back end,fullstack,full stack,react native,expo,software engineer,software developer
```

O ID vazio usa o único perfil real com template ativo. Se houver ambiguidade,
configure o ID explicitamente; o pipeline não usa o perfil sintético para vagas
reais. Os filtros são comparados ao título, excluindo junior/estágio/trainee.
Senioridade não informada não é presumida.

A pontuação é preliminar: tags da fonte comparadas aos fatos confirmados por
igualdade sem distinção de caixa. Tags não representam uma lista completa de
requisitos obrigatórios. O próximo incremento implementará análise GPT.

Worldwide/Brasil/LATAM são evidências de região declaradas pelo provedor. Região
desconhecida ou conflito com restrição explícita de residência/autorização vai
para revisão. Restrições estrangeiras conhecidas bloqueiam elegibilidade. Isso
não confirma condições de contratação, visto ou autorização de trabalho.

## Cache e processamento

O cache fica no PostgreSQL local (`source_cache`, migração `0005`). Uma reserva
atômica compartilhada entre API e worker permite uma tentativa a cada seis horas,
inclusive após falhas, respeitando a recomendação de até quatro consultas diárias.
Buscas repetidas reutilizam o feed dentro da validade. Cache antigo não atualiza
evidências de disponibilidade. Falhas são auditadas com códigos sanitizados;
a tela conserva as vagas e a data da última observação.

URLs/IDs existentes mantêm seu registro e recebem dados/classificação atualizados,
com auditoria e outbox quando houver mudança. Ausência no feed não prova expiração
e não altera vagas antigas automaticamente. Nenhuma candidatura é enviada.

O botão **Buscar vagas reais** aciona o pipeline. Use o filtro **Vagas reais** para
ocultar demonstrações antigas. O agendamento continua diário às 08h no fuso
configurado, enquanto Docker, worker e beat estiverem ativos. Computador desligado
ou suspenso não executa a busca naquele horário.

Para iniciar/parar o ambiente, sem apagar o banco:

```powershell
docker compose -p job-hunter-ai up -d
docker compose -p job-hunter-ai stop
```

Não use `down -v` para uma parada normal: essa opção remove o volume do banco.
Nenhuma conta Google nem chave OpenAI foi conectada nesta fase.

## Verificação

A resposta pública consultada gerou quatro vagas nos filtros atuais, persistidas
no PostgreSQL; duas têm restrições de região que excluem o Brasil. Repetir o
processamento retornou quatro duplicatas e nenhuma nova vaga, usando o cache.

129 testes Python aprovados, Ruff, TypeScript/Vite e formatação. Smoke PostgreSQL
em schema temporário isolado aprovou migração sem divergências, replay, reserva
concorrente e rejeição de cache antigo:

```powershell
Get-Content -Raw -Encoding UTF8 scripts/smoke_live_discovery.py | docker exec -i job-hunter-ai-api-1 python -
```

Playwright/Chromium validou o painel local em 1487×1058 e 390×844: login, filtro
por origem/situação, busca sem resultados, detalhes com atribuição e link Remotive,
repetição usando cache, estado das integrações, PDF real, SHA do mestre intacto e
navegação móvel. Sem erros de console/JavaScript ou transbordamento horizontal.
O Browser plugin não está disponível; foi usado o fallback Playwright. Capturas e
relatório privados estão em `%TEMP%/jobhunter-live-qa/`, fora do Git. A inspeção
visual levou à separação do nome da fonte em linha própria e à quebra responsiva
da barra de filtros.
