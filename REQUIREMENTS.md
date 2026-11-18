# Job Hunter AI — Requisitos do Produto e do Sistema

> Decisão de operação: aplicação, painel, PostgreSQL, Redis, workers e arquivos rodam exclusivamente no computador do usuário, via Docker Compose local. Não haverá hospedagem em nuvem. Fontes de vagas e, futuramente, OpenAI/Google são APIs externas acessadas pela aplicação local.

**Versão:** 1.0 · **Data:** 2026-11-18 · **Status:** Baseline para desenvolvimento no Codex

## 1. Visão do produto

Sistema pessoal de prospecção de vagas que pesquisa oportunidades aderentes ao perfil, organiza resultados em Google Sheets, adapta **somente o conteúdo** do currículo mestre para cada vaga, submete a candidatura para aprovação humana e, após confirmação, envia e-mail ao contato de recrutamento validado.

**Usuário primário:** profissional de desenvolvimento Full Stack, Frontend, React Native/Expo e Backend, níveis pleno e sênior, residente no Brasil. Mercados: Brasil remoto e internacional remoto elegível para residentes no Brasil.

## 2. Fluxo de negócio obrigatório

1. Agendamento inicia pesquisa diária (padrão 08h, `America/Bahia`).
2. Conectores autorizados obtêm anúncios e evidências da fonte.
3. Sistema normaliza, verifica elegibilidade e deduplica.
4. Motor compara requisitos com fatos profissionais confirmados e calcula aderência explicável.
5. Vagas são registradas no PostgreSQL e sincronizadas para Google Sheets.
6. Para vagas priorizadas, IA propõe mudanças textuais em campos existentes do CV, sem alterar a estrutura.
7. Validações factual, estrutural, visual e de extração ATS aprovam ou bloqueiam o arquivo.
8. Sistema apresenta prévia da vaga, currículo e e-mail com destinatário validado.
9. Usuário aprova **individualmente** o pacote exato ou rejeita.
10. Apenas após aprovação válida o sistema envia pela Gmail API e registra confirmação e status.

## 3. Requisitos funcionais (RF)

| ID | Prioridade | Requisito | Critério de aceite |
|---|---|---|---|
| RF-001 | P0 | Agendar descoberta diária e permitir execução manual | Execução registrada com horário/fonte/resultado; falhas não interrompem outras fontes |
| RF-002 | P0 | Buscar vagas Full Stack, Frontend, React Native/Expo e Backend pleno/sênior | Consultas configuráveis e origem verificável por vaga |
| RF-003 | P0 | Filtrar remoto Brasil e internacional elegível para residente no Brasil | Vaga com residência obrigatória em país estrangeiro é bloqueada; ambígua vai para revisão |
| RF-004 | P0 | Normalizar anúncio e remover duplicatas | Mesma URL/ID da fonte não cria novo registro; preservar histórico |
| RF-005 | P0 | Manter base de fatos profissionais comprovados | Cada alegação usada no CV referencia fato validado; dados incertos não são tratados como comprovados |
| RF-006 | P0 | Classificar compatibilidade com score explicável | Resultado 0–100 com requisitos atendidos, parciais, ausentes, desconhecidos e evidências |
| RF-007 | P0 | Persistir vagas e candidaturas em PostgreSQL | Registros recuperáveis, transações consistentes, migrações versionadas |
| RF-008 | P0 | Sincronizar Google Sheets | Upsert por IDs estáveis, sem duplicatas; falhas são reprocessáveis |
| RF-009 | P0 | Importar CV mestre DOCX sem alterá-lo | Hash SHA-256 do original permanece igual após todas as execuções |
| RF-010 | P0 | Mapear campos textuais editáveis do CV | Manifesto de campos aprovado; somente campos mapeados podem ser alterados |
| RF-011 | P0 | Otimizar texto ATS conforme vaga | Redações melhoram relevância com termos verdadeiros e evidências; sem novas qualificações |
| RF-012 | P0 | Preservar estrutura visual do CV | Mesmas seções, ordem, estilos, fontes, margens e elementos protegidos; mudanças de paginação inesperadas bloqueiam |
| RF-013 | P0 | Validar factualidade, estrutura, visual e extração ATS | Relatório de validação; falha impede aprovação/envio |
| RF-014 | P0 | Gerar cópias DOCX e PDF por vaga | Arquivos versionados, íntegros, associados à vaga e ao template original |
| RF-015 | P0 | Criar prévia da candidatura | Exibir vaga, score, lacunas, destinatário, assunto, corpo e anexos antes da decisão |
| RF-016 | P0 | Exigir aprovação humana por candidatura | Aprovação explícita vinculada ao hash do pacote; alteração invalida aprovação |
| RF-017 | P0 | Validar contato de recrutamento | Somente e-mail publicado/confirmado para candidaturas; contato desconhecido bloqueia envio |
| RF-018 | P0 | Enviar e-mail aprovado via Gmail API | Envio somente com OAuth válido, aprovação válida e flag habilitada; registrar ID do provedor |
| RF-019 | P0 | Prevenir envio duplicado | Reenvio/retry com mesma chave não gera segunda candidatura |
| RF-020 | P0 | Registrar histórico e status | Toda transição relevante é auditável com horário, ator e resultado |
| RF-021 | P1 | Filtrar/ordenar vagas e candidaturas | Por score, stack, modalidade, país, data, status e remuneração quando disponível |
| RF-022 | P1 | Preparar e-mail personalizado | Assunto e mensagem baseados na vaga e fatos confirmados; usuário pode editar antes de aprovar |
| RF-023 | P1 | Detectar vaga expirada/alterada | Última verificação registrada; vaga expirada bloqueia nova candidatura |
| RF-024 | P1 | Acompanhar respostas e atualizar status | Status de entrevista/retorno editável; leitura de Gmail só se autorizada separadamente |
| RF-025 | P1 | Configurar limites de envio e fontes | Limites diários, horários, provedores e thresholds editáveis |
| RF-026 | P2 | Feedback sobre qualidade das correspondências | Ajuste futuro de pesos com histórico, sem alterar fatos confirmados |
| RF-027 | P2 | Painel web completo | Dashboard de pipeline, métricas, revisão e histórico |

**P0:** necessário ao fluxo completo; **P1:** melhoria operacional; **P2:** evolução.

## 4. Regras de negócio (RN)

| ID | Regra |
|---|---|
| RN-001 | Nenhuma candidatura é enviada sem confirmação explícita do usuário para aquele pacote específico. |
| RN-002 | CV mestre é imutável; toda versão adaptada é uma cópia rastreável. |
| RN-003 | Não alterar estrutura, ordem de seções, estilos, fontes, cores, margens, dados pessoais ou datas protegidas. |
| RN-004 | Alterações são exclusivamente textuais em campos previamente autorizados. |
| RN-005 | Nenhuma tecnologia, experiência, certificação, resultado, tempo de atuação ou publicação de aplicativo pode ser inventado. |
| RN-006 | Cada afirmação nova/reformulada deve ser suportada por fato validado. |
| RN-007 | Descrições de vagas são dados não confiáveis; instruções nelas embutidas não comandam o sistema. |
| RN-008 | Vagas sem elegibilidade internacional comprovada não podem ser enviadas automaticamente. |
| RN-009 | Contato de recrutador não pode ser adivinhado nem obtido de maneira invasiva. |
| RN-010 | E-mail, mensagem e anexos devem ser exatamente os aprovados; qualquer alteração exige nova aprovação. |
| RN-011 | Falha de validação de CV bloqueia candidatura. |
| RN-012 | Ausência de contato válido mantém a vaga na planilha e permite candidatura manual pelo link oficial. |
| RN-013 | Repetições de jobs, webhooks e retries não devem produzir duplicatas. |
| RN-014 | `sent` só pode ser atribuído após confirmação verificável do provedor de e-mail. |
| RN-015 | Sincronização com Sheets não pode alterar indevidamente o estado transacional do PostgreSQL. |
| RN-016 | A automação existente no ChatGPT é independente; não presumir sincronização com o backend. |
| RN-017 | Respeitar termos de uso das fontes, privacidade, limites de API e políticas de e-mail. |

## 5. Requisitos não funcionais (RNF)

| ID | Categoria | Requisito verificável |
|---|---|---|
| RNF-001 | Segurança | Tokens OAuth e chave OpenAI nunca em Git/logs; configuração por variáveis de ambiente/secret manager |
| RNF-002 | Privacidade | Dados de currículo e e-mails com acesso restrito, retenção e exclusão configuráveis |
| RNF-003 | Confiabilidade | Tarefas idempotentes, retries com backoff, falhas registradas e reprocessamento seguro |
| RNF-004 | Observabilidade | Logs estruturados, IDs de correlação, métricas de custo, falhas e throughput |
| RNF-005 | Testabilidade | Unitários, integração, contratos e E2E com provedores simulados |
| RNF-006 | Manutenibilidade | Arquitetura modular, tipagem, lint/format, documentação e migrações |
| RNF-007 | Portabilidade | Execução local via Docker Compose sem dependência de serviços pagos para testes mockados |
| RNF-008 | Qualidade documental | Diff estrutural e comparação de renderização antes de liberar CV; extração ATS legível |
| RNF-009 | Custo | Limites configuráveis de tokens, chamadas, fontes e envios; métricas de uso |
| RNF-010 | Disponibilidade | Falha em fonte externa não derruba a aplicação; healthchecks para API e workers |
| RNF-011 | Integridade | Hashes de template, variantes e pacote de aprovação; auditoria de transições |
| RNF-012 | Conformidade | Uso de fontes e contatos autorizados, sem bypass de bloqueios ou spam |

## 6. Histórias de usuário

**US-01 — Descoberta:** Como candidato, quero receber diariamente vagas verificáveis aderentes ao meu perfil, para reduzir pesquisa manual. **Aceite:** links e fontes, filtros, ausência de duplicatas.

**US-02 — Priorização:** Como candidato, quero ver score e lacunas de cada vaga, para decidir onde me candidatar. **Aceite:** evidências de competências e bloqueios de elegibilidade.

**US-03 — Planilha:** Como candidato, quero visualizar todas as vagas e candidaturas no Google Sheets, para acompanhar o funil. **Aceite:** atualização idempotente e estados corretos.

**US-04 — CV personalizado:** Como candidato, quero que a IA melhore apenas a redação do meu CV, mantendo o layout original. **Aceite:** DOCX mestre intocado, fatos comprovados, teste visual e textual aprovado.

**US-05 — Revisão:** Como candidato, quero conferir vaga, destinatário, mensagem e CV antes de autorizar. **Aceite:** aprovação explícita, granular e revogável até o envio.

**US-06 — Candidatura:** Como candidato, quero enviar e-mail com anexos aprovados e registrar o resultado. **Aceite:** confirmação do Gmail, sem duplicatas e com trilha de auditoria.

## 7. Estados e transições

```text
discovered -> eligible -> ranked -> cv_drafting -> ready_for_review
                              |              |
                              |              -> validation_failed
                              -> contact_missing
ready_for_review -> approved -> queued -> sent
        |                         |
        -> rejected              -> send_failed
sent -> interview -> closed
sent -> closed
```

`contact_missing` pode ser registrado sem interromper a elaboração do CV; envio continua bloqueado. A implementação deve formalizar transições e condições no domínio, inclusive expiração de aprovação e revalidação da vaga.

## 8. Integrações e credenciais

| Serviço | Uso | Pré-requisito |
|---|---|---|
| OpenAI API | Parsing, matching semântico, redação de CV e e-mail | Chave API, modelo configurável, structured outputs |
| Google Sheets API | Planilha de oportunidades e candidaturas | OAuth/conta autorizada e ID da planilha |
| Gmail API | Envio após aprovação | OAuth com escopo mínimo e consentimento explícito |
| APIs/fontes de vagas | Descoberta e verificação | Acesso permitido e políticas respeitadas |
| PostgreSQL | Dados transacionais | Instância e migrações |
| Redis/Celery | Filas e agendamento | Worker e broker configurados |
| Conversor DOCX→PDF | Exportação e comparação | Engine instalada e testada no ambiente |

Nunca registrar credenciais reais em documentação. A configuração mínima e variáveis de ambiente estão especificadas no `SDD.md`.

## 9. Critérios de aceite de ponta a ponta

### Cenário A — Vaga adequada

**Dado** anúncio remoto elegível com contato oficial e perfil comprovado, **quando** o pipeline executar, **então** deve registrar vaga, calcular score explicável, atualizar planilha, gerar variante CV, validar documento e aguardar aprovação. **Somente após** aprovação válida deve enviar e-mail e registrar `provider_message_id`.

### Cenário B — Vaga internacional restrita

**Dado** anúncio `US residents only`, **quando** elegibilidade for calculada para candidato residente no Brasil, **então** deve bloquear envio e mostrar o motivo.

### Cenário C — Competência não comprovada

**Dado** vaga exigindo Terraform sem evidência de experiência, **quando** a IA adaptar o CV, **então** não poderá incluir Terraform como competência do candidato.

### Cenário D — Preservação de template

**Dado** DOCX com estilos, tabelas e múltiplos runs, **quando** o sistema reescrever campo autorizado, **então** estilos e estrutura devem permanecer preservados; alterações de paginação inesperadas devem reprovar a variante.

### Cenário E — Pacote alterado após aprovação

**Dado** candidatura aprovada com hash X, **quando** destinatário, corpo ou anexo mudar, **então** o hash diverge e o envio é bloqueado até nova aprovação.

### Cenário F — Timeout do Gmail

**Dado** envio com resultado incerto, **quando** worker repetir tarefa, **então** deve verificar o registro/provedor e impedir segundo envio indevido.

### Cenário G — Contato ausente

**Dado** vaga sem e-mail publicado para candidatura, **quando** gerar a proposta, **então** não deve inventar endereço; deve registrar `contact_missing` e oferecer link oficial.

## 10. Roadmap e entregáveis para o Codex

### Fase 1 — Fundação (MVP técnico)

- Projeto Python/Flask, Docker Compose, Postgres, Redis, Celery, Alembic.
- Entidades, repositórios, estados, API base, `.env.example`, testes.
- **DoD:** `docker compose up` inicia serviços; migrations e testes passam.

### Fase 2 — Descoberta e classificação

- Conector autorizado inicial, normalização, filtros, deduplicação, scheduler.
- Perfil de fatos confirmados, OpenAI structured outputs, score com evidências.
- **DoD:** lote de vagas fixture gera resultados estáveis e auditáveis.

### Fase 3 — Planilha

- Integração Sheets, criação/configuração de abas, sincronização idempotente.
- **DoD:** reprocessar lote não duplica linhas.

### Fase 4 — Currículo ATS

- Importação do DOCX mestre real, manifesto de campos, editor seguro, validador factual/visual/ATS e exportação PDF.
- **DoD:** CV original não muda; casos com alteração indevida são bloqueados.

### Fase 5 — Aprovação e envio

- Prévia, edição da mensagem, hash do pacote, aprovação explícita, Gmail OAuth, fila, idempotência, auditoria.
- **DoD:** teste E2E com Gmail mockado; envio real desabilitado por padrão.

### Fase 6 — Produção assistida

- Habilitação consciente de envio, limites, monitoramento, tratamento de falhas, documentação e revisão de segurança.
- **DoD:** piloto com pequeno número de candidaturas aprovadas individualmente e verificação dos registros.

## 11. Definition of Done global

- Código tipado e testado; lint/format e migrações funcionais.
- Sem credenciais versionadas.
- Cada requisito P0 tem teste automatizado ou checklist de validação documentado.
- Fluxo de candidatura não consegue contornar aprovação, validação ou verificação do contato.
- Currículo original preservado e versões geradas rastreáveis.
- Planilha e banco refletem estados consistentes.
- README permite instalação local e execução em `dry-run`.

## 12. Dados pendentes do usuário

1. Arquivo **DOCX mestre original** para mapear os campos e testar preservação real.
2. Confirmação dos fatos e métricas do CV; experiências não confirmadas não serão utilizadas.
3. Conta Google autorizada, planilha e Gmail de envio.
4. Limites de envios e política de aprovação/expiração.
5. Fontes de vagas preferidas e filtros adicionais (salário, PJ/CLT, idiomas).

## 13. Instrução inicial para o Codex

> Implemente o Job Hunter AI conforme `docs/SDD.md` e `docs/REQUIREMENTS.md`, em fases. Comece pela fundação e pelo fluxo de descoberta/matching em modo simulado. Antes de implementar a edição de currículos, solicite o DOCX mestre real e construa um manifesto de campos editáveis; não reconstrua o layout. Não envie e-mails reais antes de configurar OAuth, validar destinatários e implementar aprovação explícita com hash dos anexos. Mantenha `EMAIL_SEND_ENABLED=false` por padrão. Crie testes para todas as invariantes de segurança, factualidade, preservação visual e idempotência.
