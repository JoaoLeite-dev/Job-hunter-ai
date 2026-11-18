# Coleta por portais e publicações recentes

O sistema continua local, com PostgreSQL local. Este incremento adiciona coleta
HTML pública em **InfoJobs** e **Vagas.com**, além da API Remotive já existente.

## Estado real das fontes

| Fonte | Implementação nesta etapa |
|---|---|
| Remotive | API pública, já integrada |
| InfoJobs Brasil | Coletor HTML de listagens públicas, testado com resposta HTTP 200 |
| Vagas.com | Coletor HTML de listagens públicas, testado com resposta HTTP 200 |
| LinkedIn — publicações | Link assistido de pesquisa de conteúdo; sem coleta automática |
| Indeed | Link assistido; a tentativa de acesso público automático retornou HTTP 403 |
| Catho | Link assistido; a tentativa de acesso público automático retornou HTTP 403 |
| Gupy | Link assistido; a API documentada exige token de uma empresa |
| Trabalha Brasil | Link assistido; a listagem consultada não trouxe datas suficientes |

LinkedIn restringe coleta automatizada em suas [regras de acesso](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions)
e [robots.txt](https://www.linkedin.com/robots.txt). Indeed publica condições de
acesso em seus [termos](https://br.indeed.com/legal). A documentação da
[Gupy](https://developers.gupy.io/docs/fluxo-de-pagina-de-carreiras) descreve token
para a API de vagas da empresa. Essas fontes não são apresentadas como conectores
automáticos funcionando. Links assistidos não importam dados nem confirmam datas.
Filtros do portal externo precisam ser conferidos pelo usuário.

## Como a coleta funciona

Em **Configurar busca**, habilite InfoJobs e/ou Vagas.com e salve. As palavras dos
cargos definem consultas públicas; palavras gerais, exclusões, mercados e
eligibilidade filtram os resultados extraídos.

Por fonte HTML e por ciclo:

- Até três cargos distintos, em ordem de configuração. Variantes como Frontend e
  Front-end não gastam duas consultas. Somente a primeira página de cada cargo.
- Até 30 cartões por página, com deduplicação pelo ID da fonte.
- Verificação de robots.txt com regras específicas, curingas e precedência.
- Agente identificado, HTTPS, origens e caminhos fixos, sem sessão do usuário.
- Sem redirects, perfis, login, detalhes de candidatos ou execução de JavaScript.
- Sem tentativa de contornar CAPTCHA, HTTP 403/429 ou bloqueios de autenticação.
- Limite de tamanho, prazo total do lote e intervalo entre páginas.

A cobertura é parcial: não representa todos os anúncios do portal. O texto
extraído é o resumo público da listagem, identificado como incompleto. O score
usa termos mencionados nesse resumo e permanece preliminar. Modalidade só é
extraída do campo próprio, sem inferir trabalho remoto de palavras soltas na
descrição. Cidade/estado brasileiro explícito é evidência de região; o domínio
brasileiro do portal não é usado sozinho para presumir residência permitida.

O cache/budget é separado por fonte, com ciclo mínimo de seis horas, compartilhado
por API e worker, inclusive após falhas. Alterar palavras não força novas chamadas.
Se os termos do lote em cache forem diferentes, o resultado informa que a nova
consulta aguarda o próximo ciclo. Uma falha de fonte é auditada e não desfaz o
resultado de outra. O painel de fontes mostra a última resposta, erros e termos
consultados. A prévia usa os caches selecionados e avisa quando alguma fonte ainda
não tem cache.

## Regra obrigatória: no máximo 30 dias

A janela é calculada pela **data de publicação**, com limite inclusivo de 30×24
horas até o instante atual. Não usa data de descoberta, atualização ou importação
como substituto. Datas ausentes, inválidas ou futuras ficam fora da coleta e da
listagem. Datas só com dia são interpretadas no início desse dia, conservadoramente.
Remotive sem offset é interpretada em UTC; campos dos portais brasileiros usam
America/Sao_Paulo. Não se infere uma data a partir de rótulos vagos como “nova”.

A regra vale para coleta, prévia, `GET /api/v1/jobs`, dashboard e métricas de vagas.
Uma vaga envelhecida desaparece da listagem sem apagar o histórico transacional.
A migração `0007` cria `jobs.published_at` e índice, preenchendo somente datas de
publicação válidas já presentes no JSON antigo. Registros sem essa evidência não
recebem datas inventadas. Documentos e candidaturas históricas permanecem intactos.
As novas fixtures de demonstração têm data explicitamente sintética; demonstrações
antigas sem data também ficam fora da lista.

## Verificação

164 testes Python aprovados: fronteiras de 30 dias, offset, datas desconhecidas e
futuras, listagem/métricas, extração HTML, links externos rejeitados, robots,
limites, cache independente e persistência de sucesso quando outra fonte falha.
Build TypeScript/Vite, Ruff e formatação também são verificados antes do commit.

Coleta real no Compose local: 11 novas vagas (10 InfoJobs e 1 Vagas.com), além das
4 Remotive já existentes; 15 publicações com data válida na janela. As duas novas
fontes foram habilitadas nas preferências, preservando os demais filtros.
Smoke PostgreSQL em schema isolado aprovou migração sem divergências, filtros,
concorrência de configuração/cache e bloqueio de cache antigo.

QA Chromium/Playwright em 1487×1058 e 390×844 aprovou salvamento das fontes,
coleta real, timestamps de todas as vagas listadas dentro dos últimos 30 dias,
links assistidos, prévia e navegação/filtro Brasil. Sem erros de console/JavaScript
ou transbordamento horizontal. Browser plugin indisponível; fallback Playwright.
Capturas e relatório ficam em `%TEMP%/jobhunter-portals-qa/`, fora do Git.
