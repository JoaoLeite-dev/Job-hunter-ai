import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "./api";
import { Loading, time } from "./ui";

type Config = {
  enabled: boolean;
  sources: string[];
  title_terms: string[];
  keywords: string[];
  excluded_keywords: string[];
  excluded_titles: string[];
  keyword_mode: "any" | "all";
  keyword_scope: "title" | "title_description";
  markets: string[];
  brazil_keywords: string[];
  international_keywords: string[];
  locations: string[];
  eligible_only: boolean;
};
type Settings = {
  version: number;
  config: Config;
  sources: { id: string; name: string; description: string; url: string }[];
  schedule: { cron: string; timezone: string };
  discovery_mode: string;
};
type Preview = {
  scanned: number;
  matched: number;
  fetched_at: string;
  markets: Record<string, number>;
  samples: { title: string; company: string; market: string }[];
};
const MARKET_NAMES: Record<string, string> = {
  brazil: "Brasil",
  international: "Exterior / internacional",
  unknown: "Região a confirmar",
};
const TERM_KEYS = [
  "title_terms",
  "keywords",
  "excluded_keywords",
  "excluded_titles",
  "brazil_keywords",
  "international_keywords",
  "locations",
] as const;
type TermKey = (typeof TERM_KEYS)[number];
const split = (text: string) =>
  text
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
function Terms({
  id,
  label,
  value,
  onChange,
  help,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (s: string) => void;
  help: string;
  placeholder?: string;
}) {
  return (
    <div className="search-field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        rows={2}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-describedby={`${id}-help`}
      />
      <p id={`${id}-help`} className="help">
        {help}
      </p>
    </div>
  );
}
function Editor({
  initial,
  csrf,
  onSaved,
}: {
  initial: Settings;
  csrf: string;
  onSaved: (s: Settings) => void;
}) {
  const [config, setConfig] = useState(initial.config);
  const [terms, setTerms] = useState(
    () =>
      Object.fromEntries(
        TERM_KEYS.map((key) => [key, initial.config[key].join(", ")]),
      ) as Record<TermKey, string>,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<{
    data: Preview;
    query: string;
  } | null>(null);
  const draft = {
    ...config,
    ...Object.fromEntries(TERM_KEYS.map((key) => [key, split(terms[key])])),
  } as Config;
  const query = JSON.stringify(draft);
  const dirty = query !== JSON.stringify(initial.config);
  function toggle(key: "sources" | "markets", value: string) {
    setConfig((c) => ({
      ...c,
      [key]: c[key].includes(value)
        ? c[key].filter((v) => v !== value)
        : [...c[key], value],
    }));
  }
  function field(
    key: TermKey,
    label: string,
    help: string,
    placeholder?: string,
  ) {
    return (
      <Terms
        id={key}
        label={label}
        help={help}
        placeholder={placeholder}
        value={terms[key]}
        onChange={(value) => setTerms((prev) => ({ ...prev, [key]: value }))}
      />
    );
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<Settings>(
        "/api/v1/search-settings",
        {
          method: "PUT",
          body: JSON.stringify({ version: initial.version, config: draft }),
        },
        csrf,
      );
      onSaved(result);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? "As preferências mudaram em outra aba. Recarregue a página antes de salvar; seu rascunho continua nesta tela."
          : "Não foi possível salvar. Informe pelo menos um cargo e um mercado; use até 40 termos por campo, com até 80 caracteres por termo.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    setBusy(true);
    setError("");
    try {
      const data = await api<Preview>(
        "/api/v1/search-settings/preview",
        { method: "POST", body: query },
        csrf,
      );
      setPreview({ data, query });
    } catch (e) {
      setError(
        e instanceof ApiError && e.message === "source_cache_missing"
          ? "Ainda não existe uma consulta local para testar. Execute uma busca real primeiro."
          : "Não foi possível testar. Confira os cargos, mercados e limites dos campos.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="search-settings" onSubmit={submit}>
      <fieldset className="search-controls" disabled={busy}>
        <legend className="sr-only">Preferências de busca</legend>
        <section className="panel search-section">
          <h2>Onde buscar</h2>
          <label className="check-line">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) =>
                setConfig({ ...config, enabled: e.target.checked })
              }
            />
            Ativar busca manual e agendada
          </label>
          <p className="muted">
            Desative para pausar novas consultas. As vagas já salvas permanecem
            no histórico.
          </p>
          {initial.sources.map((source) => (
            <div className="source-choice" key={source.id}>
              <label className="check-line">
                <input
                  type="checkbox"
                  checked={config.sources.includes(source.id)}
                  onChange={() => toggle("sources", source.id)}
                />
                {source.name}
              </label>
              <p>
                {source.description}.{" "}
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  Conhecer a fonte
                </a>
              </p>
            </div>
          ))}
          <p className="help">
            Remotive é a única fonte integrada nesta etapa. Não há busca em
            LinkedIn, Google ou em sites arbitrários. O feed é consultado no
            máximo a cada 6 horas; mudar filtros reutiliza o cache.
          </p>
        </section>
        <section className="panel search-section">
          <h2>Como encontrar vagas</h2>
          <p className="muted">
            Separe termos por vírgula ou linha. A busca ignora diferenças de
            caixa, acentos e hífens; palavras e expressões são comparadas
            literalmente.
          </p>
          <div className="search-form-grid">
            {field(
              "title_terms",
              "Cargos no título",
              "Pelo menos um termo deve aparecer no título. Campo obrigatório.",
              "Frontend, Full Stack, React Native",
            )}
            {field(
              "excluded_titles",
              "Excluir cargos no título",
              "Qualquer um destes termos exclui o anúncio.",
              "Junior, estágio, trainee",
            )}
            {field(
              "keywords",
              "Palavras-chave gerais",
              "Campo vazio não adiciona restrição de palavras-chave.",
              "React, TypeScript, Python",
            )}
            {field(
              "excluded_keywords",
              "Palavras-chave a excluir",
              "Qualquer ocorrência no escopo selecionado exclui a vaga.",
              "Presencial, relocation required",
            )}
            <div className="search-field">
              <label htmlFor="keyword-mode">
                Combinação das palavras gerais
              </label>
              <select
                id="keyword-mode"
                value={config.keyword_mode}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    keyword_mode: e.target.value as Config["keyword_mode"],
                  })
                }
              >
                <option value="any">Qualquer palavra (OU)</option>
                <option value="all">Todas as palavras (E)</option>
              </select>
            </div>
            <div className="search-field">
              <label htmlFor="keyword-scope">
                Onde procurar palavras-chave
              </label>
              <select
                id="keyword-scope"
                value={config.keyword_scope}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    keyword_scope: e.target.value as Config["keyword_scope"],
                  })
                }
              >
                <option value="title_description">Título e descrição</option>
                <option value="title">Somente no título</option>
              </select>
            </div>
          </div>
        </section>
        <section className="panel search-section">
          <h2>Brasil e exterior</h2>
          <p className="muted">
            Mercado representa o escopo de contratação declarado no anúncio, não
            a sede da empresa. LATAM e Worldwide entram em
            exterior/internacional, mesmo quando aceitam residentes no Brasil.
          </p>
          <div className="market-choices">
            {Object.entries(MARKET_NAMES).map(([key, label]) => (
              <label className="check-line" key={key}>
                <input
                  type="checkbox"
                  checked={config.markets.includes(key)}
                  onChange={() => toggle("markets", key)}
                />
                {label}
              </label>
            ))}
          </div>
          <div className="search-form-grid">
            {field(
              "brazil_keywords",
              "Palavras adicionais para Brasil",
              "Se preenchido, exige pelo menos um destes termos, além das regras gerais.",
              "Pleno, sênior",
            )}
            {field(
              "international_keywords",
              "Palavras adicionais para exterior",
              "Se preenchido, exige pelo menos um destes termos, além das regras gerais.",
              "Senior, remote",
            )}
            {field(
              "locations",
              "Países ou regiões no anúncio",
              "Opcional. Exige um destes termos no campo de região da fonte; Global não substitui automaticamente um país específico.",
              "Brazil, LATAM, Worldwide",
            )}
          </div>
          <label className="check-line">
            <input
              type="checkbox"
              checked={config.eligible_only}
              onChange={(e) =>
                setConfig({ ...config, eligible_only: e.target.checked })
              }
            />
            Importar somente vagas elegíveis para residentes no Brasil
          </label>
          <p className="help">
            Se desmarcado, vagas restritas ou ambíguas também podem ser
            importadas com seu bloqueio ou aviso. Nenhum filtro remove essas
            proteções.
          </p>
        </section>
        <section className="panel search-section">
          <h2>Testar antes de salvar</h2>
          <p className="muted">
            A prévia aplica o rascunho à última resposta guardada no banco. Não
            consulta a internet, não salva regras nem importa vagas.
          </p>
          <button
            className="button secondary"
            type="button"
            disabled={busy}
            onClick={test}
          >
            Testar filtros no cache
          </button>
          {preview && preview.query === query ? (
            <div className="search-preview" role="status">
              <strong>
                {preview.data.matched} de {preview.data.scanned} anúncios passam
                pelos filtros
              </strong>
              <p>
                Resposta da fonte: {time(preview.data.fetched_at)}. É uma
                amostra do feed em cache, que pode estar desatualizado.
              </p>
              <p>
                {Object.entries(MARKET_NAMES)
                  .map(
                    ([key, name]) =>
                      `${name}: ${preview.data.markets[key] || 0}`,
                  )
                  .join(" · ")}
              </p>
              <ul>
                {preview.data.samples.map((job, i) => (
                  <li key={i}>
                    {job.company} — {job.title}{" "}
                    <span className="muted">({MARKET_NAMES[job.market]})</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : preview ? (
            <p className="help">
              O rascunho mudou. Teste novamente para atualizar a prévia.
            </p>
          ) : null}
        </section>
        <section className="panel search-section">
          <h2>Execução local</h2>
          <p className="muted">
            Agendamento: <code>{initial.schedule.cron}</code> ·{" "}
            {initial.schedule.timezone}. O horário continua configurado no
            ambiente local. Docker, worker e beat precisam estar ativos.
          </p>
          <p className="help">
            Modo do ambiente: {initial.discovery_mode}. Preferências salvas
            serão usadas na próxima busca real, manual ou agendada. Não apagam
            nem ocultam automaticamente vagas antigas; use os filtros da lista
            para consultar o histórico.
          </p>
          <p className="help">
            Sugestões por IA ficam para a próxima etapa, conforme sua escolha.
            Esta tela não faz chamadas de IA.
          </p>
        </section>
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="search-save">
          <span className="muted">
            {dirty
              ? "Alterações ainda não salvas"
              : `Versão ${initial.version} · regras carregadas`}
          </span>
          <button className="button primary" disabled={busy}>
            {busy ? "Aguarde…" : "Salvar preferências"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
export default function SearchSettings({ csrf }: { csrf: string }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    api<Settings>("/api/v1/search-settings", { signal: controller.signal })
      .then(setSettings)
      .catch((e) => {
        if (e.name !== "AbortError") setError(true);
      });
    return () => controller.abort();
  }, [attempt]);
  if (error)
    return (
      <section className="panel search-section">
        <h2>Preferências indisponíveis</h2>
        <p>Confira o perfil real com currículo cadastrado e a conexão local.</p>
        <button
          className="button secondary"
          onClick={() => setAttempt((n) => n + 1)}
        >
          Tentar novamente
        </button>
      </section>
    );
  if (!settings) return <Loading />;
  return (
    <>
      {saved ? (
        <p className="notice" role="status">
          Último salvamento concluído no banco local. Novas alterações precisam
          ser salvas.
        </p>
      ) : null}
      <Editor
        key={settings.version}
        initial={settings}
        csrf={csrf}
        onSaved={(value) => {
          setSettings(value);
          setSaved(true);
        }}
      />
    </>
  );
}
