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
6. **Produção assistida:** observabilidade, retenção, backup/restauração e piloto
   autorizado individualmente. Envio real permanece desligado até configuração completa.

## Evidências

Os resultados de cada fase e limitações de ambiente são registrados no README.
SQLite é usado para testes locais rápidos; não substitui a validação em PostgreSQL.
Tabelas de templates, variantes, aprovações e entregas serão adicionadas nas fases
correspondentes, antes de disponibilizar as respectivas operações.

## Andamento

- Fase 1 conclu?da e commitada: `9b6004b` (8 testes).
- Fase 2a conclu?da: descoberta/matching offline (16 testes + smoke Compose).
- Fase 2b pendente: fontes reais e OpenAI; requer fontes autorizadas e decis?o de credenciais.
- Fases 3?6 pendentes conforme depend?ncias acima.
