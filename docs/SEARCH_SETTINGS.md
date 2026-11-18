# Preferências de busca

Abra **Configurar busca** no painel local: `http://127.0.0.1:5000/#busca`.
As regras são guardadas no PostgreSQL local por perfil, com versão e auditoria.
Nenhuma chave de IA é necessária nesta etapa. Sugestões por IA foram adiadas
por escolha do usuário.

## Onde buscar

É possível ativar/pausar a busca e habilitar Remotive, InfoJobs e Vagas.com.
Os dois últimos usam coleta HTML de listagens públicas, limitada a três cargos
por ciclo e uma página por cargo. LinkedIn e outros portais têm links de consulta
assistida, sem coleta automática. O ciclo mínimo de seis horas por fonte continua
fixo. Alterar filtros não força uma nova chamada nem contorna o cache. Veja
[cobertura e limitações atuais](PORTAL_COLLECTION.md).

Desativar a busca ou desmarcar todas as fontes pausa tanto o botão manual quanto
a tarefa agendada, sem fazer chamadas à fonte. O horário diário e o fuso ainda
são configurados no `.env`; a tela mostra a expressão cron e o fuso vigentes.
Computador, Docker, worker e beat precisam estar ativos para o agendamento rodar.

## Como filtrar

- **Cargos no título:** ao menos um termo deve aparecer no título.
- **Excluir cargos:** qualquer termo exclui a vaga pelo título. A exclusão padrão
  de junior/estágio agora pode ser editada.
- **Palavras gerais:** selecione qualquer palavra (OU) ou todas (E).
- **Escopo:** palavras gerais, exclusões e palavras por mercado são comparadas
  somente ao título ou ao título e descrição, conforme selecionado.
- **Excluir palavras:** qualquer ocorrência exclui a vaga.
- **Palavras por mercado:** Brasil e exterior têm termos adicionais próprios;
  se preenchidos, pelo menos um deles deve aparecer, além das regras gerais.
- **Países/regiões:** filtro opcional no campo de região declarado pela fonte.
  Um anúncio Worldwide não é considerado uma ocorrência literal de Brazil.
- **Somente elegíveis:** exclui da importação vagas restritas ou com elegibilidade
  ambígua. Desmarcar permite guardá-las com seus bloqueios preservados.

Separe termos por vírgula ou linha. O comparador ignora caixa, acentos, espaços
repetidos e diferenças entre hífens/underscores/barras e espaços. Usa palavras ou
expressões literais, sem regex ou execução de comandos. Campos vazios opcionais
não restringem resultados. Máximo de 40 termos por campo e 80 caracteres por termo.

## Brasil e exterior

O mercado é independente da elegibilidade: um anúncio de escopo Brasil entra em
**Brasil**; escopos reconhecidos fora do país, LATAM e Worldwide entram em
**Exterior / internacional**. Região ausente ou não reconhecida fica **A confirmar**.
Isso representa o escopo de contratação, não o país da sede da empresa. Uma vaga
internacional pode aceitar quem mora no Brasil. A lista de vagas tem um filtro de
mercado separado de origem e situação; demonstrações não entram nos mercados reais.

## Prévia e salvamento

**Testar filtros no cache** aplica o rascunho à última resposta guardada no banco,
mostrando quantidades por mercado e até cinco exemplos. Não consulta a internet,
não importa vagas nem salva preferências. A data do feed é exibida; uma prévia com
cache antigo não é confirmação atual de disponibilidade.

**Salvar preferências** persiste as regras para a próxima busca real manual ou
agendada. As vagas antigas continuam no histórico. Salvar não executa uma busca.
Edições simultâneas são protegidas por versão: uma aba desatualizada recebe conflito
sem sobrescrever a alteração da outra. Os campos ficam bloqueados durante a
requisição para não perder edições feitas no meio do salvamento.

A coleta, a prévia e a lista agora exigem data de publicação conhecida de até
30 dias. Datas futuras, ausentes ou inválidas ficam fora. Alterar regras não
desativa esse limite; o histórico antigo é mantido no banco.

Antes do primeiro salvamento, os cargos vêm de `DISCOVERY_ROLES`. Depois dele,
a configuração do perfil no banco prevalece, também no worker. O modo global
`DISCOVERY_MODE` continua sendo uma condição do ambiente; as preferências não
transformam modo fixture/desabilitado em busca real.

## API e validação

- `GET /api/v1/search-settings`: regras, versão, fontes integradas e cron/fuso.
- `PUT /api/v1/search-settings`: corpo completo `{version, config}`; conflito retorna
  409, configuração inválida retorna 400. Fontes não integradas são rejeitadas.
- `POST /api/v1/search-settings/preview`: corpo `config`; sem cache retorna 409.

Todas as rotas exigem autenticação. Escritas e prévia pelo navegador exigem CSRF.
A migração `0006` adiciona `search_configurations`, vinculada ao perfil.

Validação: 157 testes Python aprovados, incluindo persistência, conflitos,
mercados, palavras, acentos, limites, autenticação/CSRF, prévia sem rede, pausa e
uso das mesmas regras pelo worker. Build TypeScript/Vite e Ruff aprovados.

Smoke PostgreSQL em schema isolado aprovado: migração sem divergências, regras por
mercado aplicadas e dois salvamentos concorrentes resultando em um sucesso e um
conflito. O orçamento de chamadas da fonte e o bloqueio de cache antigo continuam
aprovados no mesmo smoke.

QA Playwright/Chromium em 1487×1058 e 390×844 aprovado: edição de termos separados
por vírgula, prévia sem rede, salvamento e recarga, pausa da busca manual, restauração
das preferências anteriores e filtro Brasil/exterior na lista. Sem erros de console
ou JavaScript e sem transbordamento horizontal. O Browser plugin não está disponível;
foi usado Playwright. Capturas e relatório ficam em `%TEMP%/jobhunter-settings-qa/`,
fora do Git. Não houve chamada de IA nem alteração do CV.
