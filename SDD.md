# Job Hunter AI — Software Design Document (SDD)

> Decisão de operação: aplicação, painel, PostgreSQL, Redis, workers e arquivos rodam exclusivamente no computador do usuário, via Docker Compose local. Não haverá hospedagem em nuvem. Fontes de vagas e, futuramente, OpenAI/Google são APIs externas acessadas pela aplicação local.

**Versão:** 1.0 · **Data:** 2026-11-18 · **Status:** Proposta técnica para implementação

## 1. Objetivo e limites

Construir uma aplicação que descobre vagas de tecnologia compatíveis com o perfil profissional do usuário, registra oportunidades, produz cópias do currículo mestre com conteúdo otimizado para ATS **sem modificar sua estrutura visual**, solicita aprovação explícita e envia candidaturas por e-mail, registrando cada evento.

**Fluxo obrigatório:** descoberta → normalização → elegibilidade → classificação → persistência/planilha → adaptação factual do CV → validação ATS/visual → prévia → aprovação humana → envio → acompanhamento.

**Fora do escopo do MVP:** candidatura automática em portais que exigem login/CAPTCHA, envio sem aprovação, coleta invasiva de contatos, automação de LinkedIn em desacordo com termos, geração de experiências fictícias e promessa de pontuação ATS universal.

## 2. Princípios arquiteturais

- Monólito modular em Python 3.12+ e Flask, com separação entre `domain`, `application`, `infrastructure`, `api`, `agents` e `workers`.
- PostgreSQL como fonte de verdade; Google Sheets como projeção para acompanhamento, não como banco transacional.
- Celery + Redis para processamento assíncrono; Celery Beat para agendamento diário em `America/Bahia` (horário configurável).
- OpenAI API para extração, correspondência semântica e propostas de reescrita **estruturadas em JSON validado**. Nenhuma saída do modelo executa ações externas diretamente.
- Pipeline determinístico para validações, aprovação, autorização, envio, idempotência e estados.
- CV mestre original em DOCX **imutável**, com versão/hash; saída gerada sempre como nova cópia.
- O scheduler deste repositório é independente da automação já existente no ChatGPT; integração futura requer projeto e autorização específicos.

## 3. Componentes

| Módulo | Responsabilidade | Interface |
|---|---|---|
| `sources` | Conectores para APIs de vagas, feeds e páginas de carreiras permitidas | `JobSource.fetch(since, cursor)` |
| `normalization` | Padronizar cargo, stack, país, remuneração, URL, texto e datas | `normalize(raw_job)` |
| `eligibility` | Excluir vagas presenciais/incompatíveis, sobretudo exigência de residência fora do Brasil | `evaluate(job, profile)` |
| `matching` | Calcular score explicável com evidências do perfil | `score(job, verified_facts)` |
| `resume` | Mapear e alterar apenas campos de conteúdo autorizados do DOCX | `tailor(template, approved_facts, job)` |
| `validation` | Checar factualidade, preservação de template, texto extraído, paginação e diferenças visuais | `validate(original, output)` |
| `applications` | Gerenciar ciclo de vida, aprovação e deduplicação | `transition(application, event)` |
| `email` | Preparar rascunho e enviar via Gmail API após autorização | `send(approved_package)` |
| `sheets` | Sincronizar projeção de oportunidades e estados | `upsert(job/application)` |
| `audit` | Registrar decisões, hashes, eventos e erros sem expor segredos | `append(event)` |

### 3.1 Estrutura sugerida

```text
job-hunter-ai/
├── docs/{SDD.md,REQUIREMENTS.md}
├── src/job_hunter/
│   ├── api/{routes,schemas,auth}/
│   ├── domain/{entities,enums,policies}/
│   ├── application/{discovery,matching,resume,approval,submission}/
│   ├── agents/{job_parser,match_explainer,resume_editor,email_writer}/
│   ├── infrastructure/{db,openai,gmail,sheets,job_sources,documents,storage}/
│   ├── workers/{tasks,scheduler}/
│   └── config.py
├── tests/{unit,integration,contract,e2e,fixtures}/
├── migrations/
├── templates/cv-master.docx   # arquivo privado, não versionar
├── .env.example
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## 4. Descoberta e elegibilidade

Fontes iniciais: APIs públicas de ATS e páginas oficiais de carreiras com acesso permitido (ex.: Greenhouse/Lever quando disponíveis), feeds de vagas e fontes licenciadas. Implementar adaptadores isolados, tratamento de paginação, rate limiting, `robots.txt`/termos aplicáveis e backoff. Não contornar autenticação, bloqueios ou CAPTCHA.

Critérios: Full Stack, Frontend, React Native/Expo e Backend; pleno/sênior; Brasil remoto e internacional remoto **explicitamente elegível a residentes no Brasil**. Remoto restrito aos EUA/UE não é automaticamente elegível. Vaga sem prova suficiente de elegibilidade fica `needs_review`, não aprovada automaticamente.

Persistir `source_url`, `canonical_url`, `source_id`, `discovered_at`, `published_at` quando informado, `last_verified_at`, evidências textuais e `status` (ativa, expirada, desconhecida). Validar atualidade; não afirmar disponibilidade sem evidência.

Deduplicar por identificador da fonte ou URL canônica; fallback para assinatura normalizada `(empresa, cargo, localidade, modalidade)` com revisão de colisões.

## 5. Motor de compatibilidade

### 5.1 Fonte de verdade do perfil

Manter uma base versionada de fatos confirmados: cargos, empresas, períodos, stacks efetivamente usadas, projetos, resultados mensuráveis, formação, idiomas, restrições e links. O currículo e seus anexos são entradas; qualquer informação ambígua fica pendente de confirmação. Exemplo de fatos relatados para verificação no cadastro: experiência AGU/PGU Parcela, React, TypeScript, Python, Flask, MySQL, RabbitMQ, Docker, mentoria React, desenvolvimento mobile com React Native/Expo. **Não inferir** uso de AWS Lambda, Terraform, apps publicados ou tecnologias não comprovadas.

### 5.2 Score explicável (0–100)

Proposta inicial, calibrável com feedback:

- 40 pontos: requisitos técnicos obrigatórios comprovados;
- 20 pontos: experiência/senioridade e responsabilidades;
- 15 pontos: domínio e tipo de produto;
- 15 pontos: aderência de modalidade, localização e elegibilidade;
- 10 pontos: diferenciais e preferências.

**Hard gates:** exigência de residência incompatível, necessidade de autorização de trabalho inexistente, presencial obrigatório fora da área desejada, vaga expirada. Um hard gate bloqueia envio independentemente do score. Ausência de informação é `unknown`, nunca `met`.

Guardar por requisito `{requirement, status: met|partial|missing|unknown, evidence_fact_ids, explanation}`. IA sugere correspondências, regras validam evidências. Limite inicial para preparar CV: 75/100, configurável; envio exige aprovação mesmo com 100/100.

## 6. Pipeline de currículo ATS com template preservado

### 6.1 Contrato de preservação

**Imutáveis:** estrutura de seções, ordem, tabelas/colunas, cabeçalhos, rodapés, estilos, fontes, cores, margens, alinhamentos, espaçamentos, dados de contato, datas e conquistas comprovadas. Não adicionar/remover seções, experiências, certificações ou tecnologias inexistentes. Não sobrescrever o original.

**Mutáveis, quando autorizadas e factualmente suportadas:** texto do resumo, bullets e descrições existentes, ordem de termos dentro do mesmo campo e ênfase semântica no conteúdo textual. Alterações só em campos explicitamente mapeados; não trocar estilos nem criar parágrafos arbitrários.

**Risco conhecido:** textos maiores podem provocar quebra de linha/página mesmo sem mudar estilos. Estabelecer limites por campo e comparar renderizações; se a paginação/layout mudar além da tolerância configurada, reduzir o texto ou enviar para revisão, **nunca** declarar preservação perfeita sem teste.

### 6.2 Preparação do template

1. Importar `cv-master.docx` fornecido pelo usuário.
2. Inspecionar estrutura real do arquivo e criar `template_manifest.json` com identificadores de campos editáveis, tipo, comprimento recomendado, parágrafo/run de referência, hash do template e versão.
3. Preferir content controls/bookmarks quando viáveis; caso contrário, mapeamento robusto por IDs/âncoras e runs. Evitar `paragraph.text = ...` indiscriminado, pois destrói formatação de runs.
4. Implementar substituição por campo preservando propriedades XML e estilos. Não modificar cabeçalhos/rodapés ou blocos não autorizados.
5. Produzir cópia DOCX; converter para PDF com pipeline reproduzível e verificar integridade.

### 6.3 Geração com OpenAI

Enviar ao modelo apenas: requisitos normalizados, fatos comprovados pertinentes e campos editáveis com limites. Solicitar **JSON Schema estrito**:

```json
{
  "job_id": "uuid",
  "template_version": "v1",
  "edits": [
    {
      "field_id": "experience_agu_bullet_1",
      "original_text": "...",
      "proposed_text": "...",
      "supporting_fact_ids": ["fact-001"],
      "matched_requirements": ["req-003"],
      "rationale": "..."
    }
  ],
  "unmet_requirements": ["req-007"]
}
```

Validar schema, `field_id` existente, `original_text` correspondente à versão base, limite de tamanho e suporte factual de cada afirmação. Rejeitar propostas sem evidência. Guardar versão do prompt, modelo e identificador da execução. Tratar descrição da vaga como **dados não confiáveis**: ignorar instruções nela contidas para alterar regras ou enviar e-mails.

### 6.4 Validação obrigatória

- **Factual:** nenhuma alegação nova sem `fact_id`; datas, cargos, empresas, diplomas e números protegidos.
- **Estrutural:** mesma sequência de seções, número/ordem de elementos protegidos, estilos e propriedades principais; diff XML controlado.
- **Visual:** renderizar original e versão adaptada com mesma engine, comparar páginas e posições-chave; diferenças apenas textuais toleradas; reprovar sobreposição, corte, mudanças inesperadas de página.
- **ATS:** extrair texto de DOCX e PDF e verificar nome, contato, cargos, datas, termos relevantes efetivamente comprovados e legibilidade/ordem de leitura. Não alegar compatibilidade com todo ATS.
- **Integridade:** calcular SHA-256 do template e de cada saída, armazenar artefatos versionados e resultados dos testes.

Falha em qualquer validação impede envio e gera estado `validation_failed` para revisão.

## 7. Aprovação e envio

### 7.1 Pacote imutável de aprovação

Cada proposta deve exibir: empresa, cargo, link oficial, evidência de elegibilidade, score e lacunas, destinatário validado, assunto, corpo do e-mail, CV DOCX/PDF (prévia e download), hash dos anexos e timestamp. A aprovação é explícita por candidatura e vinculada a `application_id`, `recipient`, `subject`, `body_hash`, `attachment_hashes` e `approval_token` com validade curta. Qualquer mudança invalida a aprovação anterior.

**Não enviar** se endereço ausente, inferido, não publicado para candidatura ou não validado; usar `contact_missing` e disponibilizar link oficial para candidatura manual. Não extrair e-mails pessoais por adivinhação nem disparar campanhas em massa.

### 7.2 Gmail API

OAuth 2.0 com escopo mínimo, tokens criptografados e renovação controlada. Construir MIME com anexos aprovados; validar destinatário, domínio e limites; usar fila com idempotency key por `(job_id, recipient, approved_package_hash)`; persistir `provider_message_id` e data. Antes de retry após timeout, consultar histórico/registro para evitar duplicatas. Aplicar rate limit configurável e respeitar políticas do provedor.

Estados sugeridos: `discovered`, `eligible`, `ranked`, `cv_drafting`, `validation_failed`, `ready_for_review`, `approved`, `queued`, `sent`, `send_failed`, `contact_missing`, `rejected`, `interview`, `closed`. Transições permitidas implementadas como máquina de estados. `sent` somente após confirmação do provedor; falhas não equivalem a envio.

## 8. Modelo de dados PostgreSQL

| Tabela | Campos principais |
|---|---|
| `profiles` | id, name, preferences_json, timezone, created_at |
| `verified_facts` | id, profile_id, category, claim, evidence_source, verified_at, version |
| `resume_templates` | id, profile_id, storage_key, sha256, manifest_json, version, active |
| `job_sources` | id, name, connector_type, config_json, enabled |
| `jobs` | id, source_id, external_id, company, title, country, location, remote_policy, contract_type, salary_json, description, canonical_url, published_at, discovered_at, last_verified_at, status |
| `job_requirements` | id, job_id, text, kind, priority, normalized_skill |
| `matches` | id, job_id, profile_id, score, hard_gate, evidence_json, gaps_json, model_version, created_at |
| `resume_variants` | id, job_id, template_id, docx_key, pdf_key, sha256_docx, sha256_pdf, edits_json, validation_json, state |
| `applications` | id, job_id, profile_id, resume_variant_id, status, recipient, subject, body, package_hash, created_at, updated_at |
| `approvals` | id, application_id, package_hash, approved_by, approved_at, expires_at, revoked_at |
| `email_deliveries` | id, application_id, idempotency_key, provider_message_id, attempt_count, status, sent_at, error_code |
| `audit_events` | id, actor, entity_type, entity_id, event_type, payload_redacted, created_at |
| `sync_outbox` | id, entity_type, entity_id, event_type, payload, processed_at, attempts |

Índices únicos: `jobs(source_id, external_id)` quando `external_id` existe; `jobs(canonical_url)` quando válida; `email_deliveries(idempotency_key)`; `applications(job_id, profile_id, recipient)` com política para candidaturas múltiplas justificadas. Migrações via Alembic.

## 9. API REST proposta

| Método | Rota | Função |
|---|---|---|
| GET | `/api/v1/jobs` | Listar vagas, filtros, ordenação |
| POST | `/api/v1/discovery/run` | Iniciar busca manual autorizada |
| GET | `/api/v1/jobs/{id}/match` | Score e evidências |
| POST | `/api/v1/jobs/{id}/resume-variants` | Gerar variante ATS |
| GET | `/api/v1/resume-variants/{id}` | Metadados, validação, links temporários |
| POST | `/api/v1/applications` | Criar pacote de candidatura |
| GET | `/api/v1/applications/{id}/preview` | Prévia completa para revisão |
| POST | `/api/v1/applications/{id}/approve` | Aprovar hash exato do pacote |
| POST | `/api/v1/applications/{id}/reject` | Rejeitar candidatura |
| POST | `/api/v1/applications/{id}/send` | Enfileirar envio de pacote aprovado |
| GET | `/api/v1/applications` | Status e histórico |
| POST | `/api/v1/integrations/sheets/sync` | Sincronização manual |
| GET | `/health/live`, `/health/ready` | Saúde |

Autenticação obrigatória para rotas mutáveis; autorização de usuário único no MVP, com possibilidade de multiusuário futura. Idempotency-Key nas operações sensíveis. `approve` deve receber `package_hash` e rejeitar divergências (`409 Conflict`).

## 10. Planilha Google Sheets

Abas sugeridas: `Vagas`, `Candidaturas`, `Configurações` (sem segredos). Colunas `Vagas`: ID, descoberta, empresa, cargo, país, política remoto, contrato, salário, stack, score, hard gate, lacunas, URL, verificação, status, contato validado, link da variante CV, data da última atualização. `Candidaturas`: application ID, job ID, destinatário, assunto, versão CV, aprovação, envio, ID Gmail, status, observações.

Sincronização por `job_id`/`application_id` com `upsert` e outbox transacional; retries com backoff. Não guardar tokens, dados secretos ou currículo integral na planilha. Permissões mínimas na conta Google.

## 11. Segurança, privacidade e conformidade

- Secrets apenas em ambiente/secret manager; `.env` fora do Git; `.env.example` sem valores reais.
- OAuth Gmail e Sheets com escopos mínimos; armazenamento criptografado; logs com PII mascarada.
- Retenção configurável de descrições, currículos e dados pessoais; exclusão/exportação sob demanda.
- URLs e conteúdo de vagas são não confiáveis: proteção SSRF, allowlist de esquemas, timeouts, sanitização e prevenção de prompt injection.
- Evitar scraping proibido, contatos obtidos de forma invasiva e disparos não solicitados; observar LGPD e termos das fontes.
- Proteção CSRF nas interfaces web, rate limits, RBAC básico, auditoria e backups.
- OpenAI API: configurar limites de custo, retry/backoff, timeouts, validação JSON e não registrar conteúdo sensível desnecessário.

## 12. Operação e observabilidade

Logs estruturados com `correlation_id`, métricas de vagas descobertas, elegíveis, duplicadas, CVs aprovados, falhas de validação, candidaturas aprovadas/enviadas, custo de IA e tempo por etapa. Alertas para falhas recorrentes. Jobs Celery idempotentes, DLQ/registro de falhas e reprocessamento manual seguro.

Configurações exemplares (sem credenciais):

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://jobhunter:local@db:5432/jobhunter
REDIS_URL=redis://redis:6379/0
OPENAI_API_KEY=
OPENAI_MODEL=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_SHEETS_SPREADSHEET_ID=
GMAIL_SENDER_ADDRESS=
JOB_SEARCH_TIMEZONE=America/Bahia
JOB_SEARCH_CRON=0 8 * * *
MATCH_PREPARE_THRESHOLD=75
EMAIL_SEND_ENABLED=false
EMAIL_DAILY_LIMIT=10
STORAGE_ROOT=./var/private
```

`EMAIL_SEND_ENABLED=false` não substitui a aprovação por candidatura; ambos são obrigatórios para envio. Não publicar credenciais, CV mestre ou tokens no repositório.

## 13. Testes e critérios arquiteturais de aceite

- **Unitários:** normalização, gates, score, máquina de estados, deduplicação, hash, limites.
- **Contrato:** conectores de fontes, OpenAI structured output, Gmail, Sheets.
- **Integração:** PostgreSQL, Celery/Redis, OAuth com mocks, outbox.
- **Documentos:** fixtures DOCX com runs mistos, tabelas e estilos; diff estrutural; renderização PDF; extração textual.
- **E2E:** vaga → score → variante → aprovação → envio mock → atualização de planilha.
- **Segurança:** prompt injection na vaga, URL maliciosa, aprovação adulterada, envio duplicado, vazamento de tokens.

**Invariantes inegociáveis:** (a) CV original permanece byte a byte idêntico; (b) nenhum conteúdo novo sem evidência; (c) documento inválido não é enviado; (d) e-mail sem aprovação válida não é enviado; (e) retry não duplica candidatura; (f) destinatário não verificado bloqueia envio.

## 14. Plano de implementação

1. **Fundação:** Flask, configuração, Postgres/Alembic, Celery/Redis, Docker, testes, entidades e estados.
2. **Discovery:** 1–2 fontes permitidas, normalização, elegibilidade, deduplicação, agendamento.
3. **Matching:** perfil verificado, parser OpenAI com schema, score explicável e filtros.
4. **Planilha:** OAuth Sheets, abas, sincronização idempotente, outbox.
5. **CV ATS:** importar template real, manifesto, editor de campos, validação factual/visual, PDF.
6. **Aprovação:** prévia, hashes, API e interface mínima, auditoria.
7. **Envio:** Gmail OAuth, MIME, fila, idempotência, logs, limites e testes.
8. **Hardening:** métricas, backups, segurança, políticas de retenção, documentação operacional.

## 15. Pendências de decisão antes do código de produção

- Disponibilizar o **DOCX mestre real** e confirmar os campos que podem ser reescritos; não presumir sua estrutura.
- Confirmar fatos profissionais e tecnologias efetivamente usadas a partir do CV e evidências.
- Escolher conta Google e planilha de destino; concluir OAuth com consentimento.
- Definir fontes de vagas autorizadas e critérios de elegibilidade internacional.
- Definir limite diário de candidaturas, prazo de validade de aprovações e retenção de dados.
- Definir canal de aprovação (painel web ou outro) e identidade do usuário.

---

**Nota para o Codex:** implemente em incrementos testáveis. Não habilite envio real nem altere o CV original durante desenvolvimento. Priorize fixtures, mocks, dry-run e testes de invariantes antes de conectar contas externas.
