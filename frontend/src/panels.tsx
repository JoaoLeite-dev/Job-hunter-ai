import { useEffect, useRef, useState } from "react";
import {
  api,
  type Dashboard,
  type Job,
  type Template,
  type ActivityItem,
  type Variant,
} from "./api";
import { Icon, Gate, Score, modality, time } from "./ui";
export function Jobs({
  jobs,
  onSelect,
}: {
  jobs: Job[];
  onSelect: (j: Job) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const filtered = jobs.filter(
    (j) =>
      (filter === "all" || j.eligibility.status === filter) &&
      `${j.company} ${j.title}`
        .toLocaleLowerCase("pt-BR")
        .includes(query.toLocaleLowerCase("pt-BR")),
  );
  const anyDemo = jobs.some((j) => j.is_demo);
  return (
    <section className="panel jobs-panel">
      <div className="table-toolbar">
        <div className="section-heading">
          <h2>Oportunidades recentes</h2>
          {anyDemo ? <span className="subtle-tag">Dados simulados</span> : null}
        </div>
        <div className="filters">
          <div className="search-input">
            <Icon name="search" />
            <input
              aria-label="Buscar vaga ou empresa"
              placeholder="Buscar vaga ou empresa…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select
            aria-label="Filtrar situação"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">Todas as situações</option>
            <option value="eligible">Elegível</option>
            <option value="blocked">Restrita</option>
            <option value="needs_review">Revisão</option>
          </select>
        </div>
      </div>
      {filtered.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Vaga / Empresa</th>
                <th>Modalidade</th>
                <th>Aderência</th>
                <th>Situação</th>
                <th>
                  <span className="sr-only">Ações</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((job) => (
                <tr key={job.id}>
                  <td className="job-name">
                    <strong>{job.company}</strong>
                    <span>{job.title}</span>
                  </td>
                  <td className="job-modality">{modality(job)}</td>
                  <td>
                    <Score value={job.score} />
                  </td>
                  <td>
                    <Gate status={job.eligibility.status} />
                  </td>
                  <td className="row-action">
                    <button
                      className="text-button"
                      onClick={() => onSelect(job)}
                      aria-label={`Ver detalhes de ${job.company}`}
                    >
                      Ver detalhes
                      <Icon name="chevron" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state compact">
          <Icon name="search" />
          <h3>
            {jobs.length
              ? "Nenhuma vaga com esses filtros"
              : "Suas oportunidades aparecerão aqui"}
          </h3>
          <p>
            {jobs.length
              ? "Experimente outro nome ou situação."
              : "Execute a demonstração para conhecer o fluxo com vagas de exemplo."}
          </p>
          {jobs.length ? (
            <button
              className="button secondary"
              onClick={() => {
                setQuery("");
                setFilter("all");
              }}
            >
              Limpar filtros
            </button>
          ) : null}
        </div>
      )}
      <div className="table-note">
        {anyDemo
          ? "Aderência calculada com um perfil sintético de demonstração."
          : "A aderência depende de avaliação com os fatos confirmados do perfil."}
        {jobs.length >= 200 ? <span>Últimas 200 vagas no painel.</span> : null}
      </div>
    </section>
  );
}
export function ResumeCard({
  template,
  renderEnabled,
}: {
  template: Template | undefined;
  renderEnabled: boolean;
}) {
  return (
    <section className="panel resume-panel">
      <h2>Seu currículo</h2>
      {template ? (
        <>
          <div className="resume-summary">
            <div className="document-tile">
              <Icon name="file" />
            </div>
            <div>
              <h3>Currículo principal</h3>
              <p className="document-state">Mestre protegido</p>
              <p className="muted">
                {template.facts_count} fatos confirmados ·{" "}
                {template.authorized_count} campos autorizados
              </p>
              {renderEnabled ? (
                <a
                  className="button secondary pdf-button"
                  href={`/api/v1/resume-templates/${template.id}/master.pdf`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Visualizar PDF
                </a>
              ) : (
                <p className="muted">Prévia PDF indisponível neste ambiente.</p>
              )}
            </div>
          </div>
          <p className="panel-footnote">
            O documento original permanece intacto.
          </p>
        </>
      ) : (
        <div className="empty-state compact">
          <Icon name="file" />
          <h3>Nenhum currículo cadastrado</h3>
          <p>O mestre aparecerá aqui após a importação privada no projeto.</p>
        </div>
      )}
    </section>
  );
}
export function Activity({
  events,
  compact = false,
}: {
  events: ActivityItem[];
  compact?: boolean;
}) {
  const meaningful = events.filter((e) =>
    [
      "resume.facts_confirmed",
      "resume.fields_authorized",
      "resume.imported",
      "discovery.completed",
      "resume.validated",
    ].includes(e.type),
  );
  const visible = compact
    ? (meaningful.length ? meaningful : events).slice(0, 3)
    : events;
  return (
    <section className="panel activity-panel">
      <h2>Atividade recente</h2>
      {visible.length ? (
        <ol className="timeline">
          {visible.map((event) => (
            <li key={event.id}>
              <span className="timeline-dot" />
              <div>
                <strong>{event.label}</strong>
                {!compact && event.detail ? <p>{event.detail}</p> : null}
              </div>
              <time dateTime={event.created_at}>{time(event.created_at)}</time>
            </li>
          ))}
        </ol>
      ) : (
        <div className="empty-state compact">
          <Icon name="pulse" />
          <p>Os próximos passos do seu fluxo ficarão registrados aqui.</p>
        </div>
      )}
    </section>
  );
}
export function EmptyApplications() {
  return (
    <section className="panel empty-state large">
      <Icon name="check" />
      <h2>Nenhuma candidatura preparada</h2>
      <p>
        Os pacotes aparecerão aqui para sua revisão individual.
        <br />O envio está desativado.
      </p>
      <a className="button secondary" href="#vagas">
        Explorar vagas
        <Icon name="arrow" />
      </a>
    </section>
  );
}
export function Integrations({ data }: { data: Dashboard }) {
  const rows = [
    {
      title: "Fontes de vagas",
      icon: "search",
      state:
        data.integrations.discovery_mode === "fixture"
          ? "Demonstração"
          : "Não configuradas",
      tone: "blue",
      description:
        "Vagas de exemplo para conhecer o fluxo. A busca em fontes reais ainda não está conectada.",
    },
    {
      title: data.integrations.baseline_preview_only
        ? "PDF do mestre"
        : "Currículo e PDF",
      icon: "file",
      state: data.integrations.render_enabled ? "Disponível" : "Indisponível",
      tone: data.integrations.render_enabled ? "green" : "neutral",
      description: data.integrations.baseline_preview_only
        ? "Baseline previamente renderizada e verificada. Novas conversões não estão habilitadas nesta prévia."
        : "Geração local com preservação do mestre e verificação de texto e layout.",
    },
    {
      title: "Google Sheets",
      icon: "connect",
      state: data.integrations.sheets_enabled
        ? "Sincronização habilitada"
        : "Desabilitado",
      tone: data.integrations.sheets_enabled ? "blue" : "neutral",
      description:
        "A sincronização real depende da conta Google autorizada e da planilha escolhida.",
    },
    {
      title: "IA de adaptação",
      icon: "compass",
      state: "Não conectada",
      tone: "neutral",
      description:
        "A integração semântica com IA ainda está pendente. Nenhuma chamada é feita por esta tela.",
    },
    {
      title: "Gmail",
      icon: "lock",
      state: "Envio desativado",
      tone: "neutral",
      description:
        "Cada pacote precisará de aprovação individual antes de qualquer envio.",
    },
  ];
  return (
    <section className="panel integrations-panel">
      <h2>Conexões do seu espaço</h2>
      {rows.map((row) => (
        <div className="integration-row" key={row.title}>
          <div className="integration-icon">
            <Icon name={row.icon} />
          </div>
          <div>
            <h3>{row.title}</h3>
            <p>{row.description}</p>
          </div>
          <span className={`badge ${row.tone}`}>{row.state}</span>
        </div>
      ))}
    </section>
  );
}
export function JobDialog({
  job,
  onClose,
}: {
  job: Job | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (job && !dialog?.open) dialog?.showModal();
    if (!job && dialog?.open) dialog.close();
  }, [job]);
  const reasons: Record<string, string> = {
    residency_restriction: "A fonte exige residência fora do Brasil.",
    insufficient_evidence:
      "A fonte ainda não comprova elegibilidade para residentes no Brasil.",
    expired: "A vaga está expirada.",
    onsite: "A modalidade não atende ao critério remoto.",
    work_authorization_unconfirmed:
      "A autorização de trabalho precisa ser confirmada.",
  };
  const reason = job
    ? reasons[job.eligibility.reason] || job.eligibility.reason
    : "";
  return (
    <dialog
      className="job-dialog"
      ref={ref}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      {job ? (
        <>
          <div className="dialog-header">
            <span>Detalhes da oportunidade</span>
            <button
              className="icon-button"
              aria-label="Fechar detalhes"
              onClick={onClose}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="dialog-body">
            <div className="dialog-company">{job.company}</div>
            <h2>{job.title}</h2>
            <p className="muted">{modality(job)}</p>
            {job.is_demo ? (
              <div className="notice">
                <Icon name="shield" />
                <p>
                  Esta é uma vaga simulada. A aderência usa um perfil sintético,
                  separado do seu currículo.
                </p>
              </div>
            ) : null}
            <div className="detail-score">
              <div>
                <span>Aderência</span>
                <strong>
                  {job.score === null ? "Não avaliada" : `${job.score} / 100`}
                </strong>
              </div>
              <Gate status={job.eligibility.status} />
            </div>
            <h3>Elegibilidade geográfica</h3>
            <p>
              {job.eligibility.status === "eligible"
                ? "A fonte informa trabalho remoto elegível no Brasil."
                : reason}
            </p>
            <h3>Requisitos e evidências</h3>
            {job.match?.requirements.length ? (
              <ul className="requirements">
                {job.match.requirements.map((r, i) => (
                  <li key={`${r.requirement}-${i}`}>
                    <div>
                      <strong>{r.requirement}</strong>
                      <p>
                        {r.status === "met"
                          ? "Há evidência confirmada no perfil avaliado."
                          : "Ainda não há evidência confirmada para este requisito."}
                      </p>
                    </div>
                    <span
                      className={`badge ${r.status === "met" ? "green" : "neutral"}`}
                    >
                      {r.status === "met"
                        ? "Comprovado"
                        : r.status === "partial"
                          ? "Parcial"
                          : "Não comprovado"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">
                A avaliação desta vaga ainda não está disponível.
              </p>
            )}
            <h3>Descrição da fonte</h3>
            <p className="source-description">{job.description}</p>
            <dl className="detail-dates">
              <div>
                <dt>Encontrada</dt>
                <dd>{time(job.discovered_at)}</dd>
              </div>
              <div>
                <dt>Disponibilidade</dt>
                <dd>{time(job.verified_at)}</dd>
              </div>
            </dl>
            <p className="muted small">
              O score não autoriza candidatura. Currículo validado, contato
              confirmado e sua aprovação continuam necessários.
            </p>
          </div>
          <div className="dialog-footer">
            {!job.is_demo && job.url.startsWith("https://") ? (
              <a
                className="button primary"
                href={job.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Abrir anúncio
                <Icon name="arrow" />
              </a>
            ) : (
              <span className="muted">
                O link desta vaga é apenas um exemplo.
              </span>
            )}
            <button className="button secondary" onClick={onClose}>
              Fechar
            </button>
          </div>
        </>
      ) : null}
    </dialog>
  );
}
const SECTION_NAMES: Record<string, string> = {
  summary: "Resumo profissional",
  experience: "Experiência profissional",
  projects: "Descrição de projeto",
};
export function Curriculum({
  data,
  csrf,
  onRefresh,
  onMessage,
}: {
  data: Dashboard;
  csrf: string;
  onRefresh: () => void;
  onMessage: (s: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const template = data.templates.find((t) => !t.is_demo) || data.templates[0];
  async function validate(variant: Variant) {
    setBusy(variant.id);
    try {
      const result = await api<{ state: string }>(
        `/api/v1/resume-variants/${variant.id}/validate`,
        { method: "POST" },
        csrf,
      );
      onMessage(
        result.state === "validated"
          ? "Validações do documento aprovadas."
          : "O documento requer revisão. Consulte o resultado.",
      );
      onRefresh();
    } catch {
      onMessage("Não foi possível validar o documento agora.");
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="curriculum-grid">
      <ResumeCard
        template={template}
        renderEnabled={data.integrations.render_enabled}
      />
      {template ? (
        <section className="panel authorized-panel">
          <div className="section-heading">
            <h2>Campos autorizados</h2>
            <span className="subtle-tag">
              {template.authorized_count} campos
            </span>
          </div>
          <p className="muted">
            Os demais textos, datas, números, contatos e estilos permanecem
            protegidos.
          </p>
          {template.fields.map((field, i) => (
            <details key={field.id}>
              <summary>
                <span>
                  {SECTION_NAMES[field.section] || "Campo textual"}
                  {template.fields.filter((f) => f.section === field.section)
                    .length > 1
                    ? ` · ${i}`
                    : ""}
                </span>
                <Icon name="chevron" />
              </summary>
              <p>{field.text}</p>
            </details>
          ))}
        </section>
      ) : null}
      <section className="panel variants-panel">
        <h2>Variantes por oportunidade</h2>
        {data.variants.length ? (
          <div className="variant-list">
            {data.variants.map((v) => (
              <article className="variant-row" key={v.id}>
                <div>
                  <h3>
                    {data.jobs.find((j) => j.id === v.job_id)?.title ||
                      "Currículo por oportunidade"}
                  </h3>
                  <p className="muted">
                    {v.state === "validated"
                      ? "Validações aprovadas"
                      : v.state === "validation_failed"
                        ? "Documento requer revisão"
                        : "Aguardando validação"}
                  </p>
                  <div className="check-list">
                    {Object.entries(v.validation)
                      .filter(([key]) => key !== "render")
                      .map(([key, value]) => (
                        <span
                          key={key}
                          className={`check-result ${value.status === "passed" ? "ok" : ""}`}
                        >
                          {(
                            {
                              factual: "Fatos",
                              structural: "Estrutura",
                              docx_ats: "Texto DOCX",
                              visual: "Layout",
                              pdf_ats: "Texto PDF",
                            } as Record<string, string>
                          )[key] || key}
                          :{" "}
                          {value.status === "passed"
                            ? "OK"
                            : value.status === "failed"
                              ? "revisar"
                              : "pendente"}
                        </span>
                      ))}
                  </div>
                </div>
                <div className="variant-actions">
                  {v.pdf_available ? (
                    <a
                      className="button secondary"
                      href={`/api/v1/resume-variants/${v.id}/pdf`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Ver PDF
                    </a>
                  ) : null}
                  {data.integrations.render_enabled &&
                  !data.integrations.baseline_preview_only &&
                  v.state !== "validated" ? (
                    <button
                      className="button secondary"
                      onClick={() => validate(v)}
                      disabled={busy !== null}
                    >
                      {busy === v.id ? "Validando…" : "Validar documento"}
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state compact">
            <Icon name="file" />
            <h3>Nenhuma variante preparada</h3>
            <p>
              As versões para cada vaga aparecerão aqui com o resultado das
              validações.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
