# Plano de implementação

As especificações originais permanecem em [REQUIREMENTS.md](../REQUIREMENTS.md) e
[SDD.md](../SDD.md). Cada fase termina com validação e um commit próprio.

1. **Fundação:** Flask, configuração segura, modelos transacionais iniciais,
   máquina de estados, Alembic, Compose com PostgreSQL/Redis/Celery e testes.
2. **Descoberta e classificação simuladas:** fixtures, normalização, elegibilidade,
   deduplicação, fatos verificados, score determinístico explicável, auditoria e agendamento.
   A integração OpenAI e fontes reais entram em incremento posterior, com credenciais
   e fontes autorizadas. Nenhuma experiência do usuário será presumida.
3. **Sheets:** OAuth, abas, consumidor da outbox e upsert idempotente.
4. **Currículo:** depende do DOCX mestre real e da aprovação do manifesto de campos;
   edição textual preservando XML, validação factual/visual/ATS, exportação PDF.
5. **Aprovação e envio:** pacote imutável, hash, expiração/revogação, OAuth Gmail,
   limites e resolução de envios incertos; E2E com Gmail simulado.
6. **Operação local assistida:** observabilidade, retenção, backup/restauração e piloto
   autorizado individualmente. Envio real permanece desligado até configuração completa.

## Evidências

Os resultados de cada fase e limitações de ambiente são registrados no README.
SQLite é usado para testes locais rápidos; não substitui a validação em PostgreSQL.
Tabelas de aprovações e entregas serão adicionadas nas fases
correspondentes, antes de disponibilizar as respectivas operações.

## Andamento

- Fase 1 concluída e commitada: `9b6004b` (8 testes).
- Fase 2a concluída: descoberta/matching offline (16 testes + smoke Compose).
- Fase 2b1 concluída: busca real Remotive, cache/budget local, atualização de anúncios e score preliminar.
- Fase 2b2 pendente: integração OpenAI e decisão de credenciais.
- Fase 3a: adaptador OAuth Sheets, projeções, outbox, retries e testes de contrato implementados; validação PostgreSQL aprovada (migração, retry, rollback e concorrência).
- Fase 3b pendente: consentimento inicial OAuth, escolha da planilha e validação com conta real.
- Fase 4a concluída: pasta privada, importação imutável, cadastro, manifesto proposto e autorização por campos; 55 testes e smoke PostgreSQL aprovados.
- Fase 4b1 concluída: campos autorizados e fatos confirmados pelo usuário; editor de texto com evidências, validação estrutural, variantes idempotentes e 86 testes.
- Fase 4b2 concluída: LibreOffice no Docker, PDF privado, verificações de geometria/texto, integridade e 107 testes; smoke real PostgreSQL e baseline do mestre aprovados.
- Fases 5–6 pendentes conforme dependências acima.


## Incremento UI-1 — acompanhamento local

Antecipado por solicitação do usuário antes da fase 5: painel React integrado ao
Flask, sessão autenticada, proteção CSRF, vagas/score explicável, currículo/PDF,
auditoria e estados reais de integrações. 114 testes de backend e QA Chromium em
desktop/celular aprovados. Conceito em `docs/design/`. A prévia isolada inicial da
porta 5001 foi substituída pelo Compose local na fase 2b1. A interface não declara
concluídas as fases de análise GPT, aprovação de pacotes ou envio.

## Operação exclusivamente local e busca real

Aplicação e banco permanecem no computador do usuário. Não haverá deploy em nuvem. A fase 2b1 conecta Remotive ao painel e ao agendamento; quatro vagas reais persistidas, 129 testes e smoke PostgreSQL aprovados. O painel principal em `http://127.0.0.1:5000` substitui a prévia isolada da porta 5001. Veja [operação e busca local](LOCAL_DISCOVERY.md). GPT é o próximo incremento.

## Incremento 2b1-config — preferências de busca

Configuração por perfil no PostgreSQL local, migração `0006`, fontes integradas,
termos de cargo/palavras/exclusões, mercados Brasil/exterior/a confirmar e filtro
de elegibilidade. Prévia no cache sem rede; mesma configuração no botão e worker;
versão evita sobrescrita entre abas. 157 testes aprovados e build frontend validado.
Detalhes em [SEARCH_SETTINGS.md](SEARCH_SETTINGS.md). A opção escolhida pelo usuário
foi concluir primeiro as configurações sem IA; sugestões por IA seguem pendentes.

## Incremento 2b1-portais — coleta pública e atualidade

Coletores HTML InfoJobs/Vagas.com, cache independente por fonte, falhas isoladas,
origem e data de publicação. Portais com bloqueio ou sem integração autorizada têm
consulta assistida, sem fingir coleta automática. Migração `0007` e janela obrigatória
de 30 dias na coleta, prévia, API e painel. 164 testes aprovados; evidências e limites
em [PORTAL_COLLECTION.md](PORTAL_COLLECTION.md). IA permanece adiada.
