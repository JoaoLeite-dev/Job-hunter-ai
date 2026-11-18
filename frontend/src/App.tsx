import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  api,
  ApiError,
  type BrowserSession,
  type Dashboard,
  type Job,
} from "./api";
import { NAV, Icon, Brand, Loading, currentView, type View } from "./ui";
import SearchSettings from "./SearchSettings";
import {
  Jobs,
  ResumeCard,
  Activity,
  Curriculum,
  Integrations,
  EmptyApplications,
  JobDialog,
} from "./panels";
function Login({
  session,
  onLogin,
}: {
  session: BrowserSession;
  onLogin: (s: BrowserSession) => void;
}) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<BrowserSession>(
        "/ui/login",
        { method: "POST", body: JSON.stringify({ token }) },
        session.csrf_token,
      );
      setToken("");
      onLogin(result);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "Atualize a página e tente novamente."
          : "Token inválido. Confira o acesso do ambiente local.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <Brand />
        <div className="login-heading">
          <h1>Entre no seu espaço</h1>
          <p>Suas oportunidades e seu currículo, sob seu controle.</p>
        </div>
        <form onSubmit={submit}>
          <label htmlFor="access-token">Token de acesso</label>
          <input
            id="access-token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Token do seu ambiente local"
            required
          />
          <p className="help">
            Use o API_TOKEN configurado no arquivo .env do projeto.
          </p>
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
          <button className="button primary" disabled={busy || !token.trim()}>
            {busy ? "Entrando…" : "Entrar"}
            <Icon name="arrow" />
          </button>
        </form>
        <p className="login-note">
          <Icon name="lock" />O token não fica salvo no navegador.
        </p>
      </div>
      <p className="login-caption">
        Seu espaço de trabalho local. Nenhum envio automático.
      </p>
    </div>
  );
}
export default function App() {
  const [auth, setAuth] = useState<BrowserSession | null>(null);
  const [bootError, setBootError] = useState(false);
  const [data, setData] = useState<Dashboard | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>(currentView);
  const [menu, setMenu] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api<BrowserSession>("/ui/session", { signal: controller.signal })
      .then(setAuth)
      .catch((e) => {
        if (e.name !== "AbortError") setBootError(true);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const change = () => {
      setView(currentView());
      setMenu(false);
      setJob(null);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    document.title = `${NAV.find((n) => n.id === view)?.label || "Visão geral"} · Job Hunter AI`;
  }, [view]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  const refresh = useCallback(async () => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setRefreshing(true);
    try {
      const response = await api<Dashboard>("/api/v1/dashboard", {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setData(response);
        setError("");
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setAuth(await api<BrowserSession>("/ui/session"));
        setData(null);
      } else if (!(e instanceof DOMException && e.name === "AbortError"))
        setError("Não foi possível atualizar os dados. Tente novamente.");
    } finally {
      if (pending.current === controller) setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    if (!auth?.authenticated) return;
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 30000);
    return () => {
      clearInterval(timer);
      pending.current?.abort();
    };
  }, [auth?.authenticated, refresh]);
  async function demo() {
    if (!auth) return;
    setBusy(true);
    try {
      const result = await api<{
        created: number;
        duplicates: number;
        updated?: number;
        cached?: boolean;
        paused?: boolean;
      }>("/api/v1/discovery/run", { method: "POST" }, auth.csrf_token);
      await refresh();
      setToast(
        result.paused
          ? "Busca pausada nas preferências. Ative a busca e selecione uma fonte em Configurar busca."
          : `Busca concluída: ${result.created} novas vagas; ${result.duplicates} já existentes.${result.cached ? " Cache local reutilizado (consulta à fonte a cada 6 horas)." : ""}`,
      );
    } catch {
      setToast(
        "Não foi possível concluir a busca. Confira o perfil cadastrado e a conexão com a fonte; tente novamente mais tarde.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    if (!auth) return;
    try {
      const result = await api<BrowserSession>(
        "/ui/logout",
        { method: "POST" },
        auth.csrf_token,
      );
      pending.current?.abort();
      setData(null);
      setAuth(result);
      setJob(null);
    } catch {
      setToast("Não foi possível encerrar a sessão. Tente novamente.");
    }
  }
  if (bootError)
    return (
      <div className="login-screen">
        <div className="panel empty-state">
          <Icon name="connect" />
          <h1>Conexão indisponível</h1>
          <p>Verifique o servidor local e atualize esta página.</p>
          <a className="button primary" href="/">
            Tentar novamente
          </a>
        </div>
      </div>
    );
  if (!auth)
    return (
      <div className="login-screen">
        <Loading />
      </div>
    );
  if (!auth.authenticated) return <Login session={auth} onLogin={setAuth} />;
  const template =
    data?.templates.find((t) => !t.is_demo) || data?.templates[0];
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Pular para o conteúdo
      </a>
      {menu ? (
        <button
          className="nav-scrim"
          aria-label="Fechar menu"
          onClick={() => setMenu(false)}
        />
      ) : null}
      <aside className={`sidebar ${menu ? "is-open" : ""}`}>
        <Brand />
        <nav aria-label="Navegação principal">
          {NAV.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className={view === item.id ? "active" : ""}
              aria-current={view === item.id ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <p className="send-status">
            <Icon name="lock" />
            Envio desativado
          </p>
          <div className="account">
            <span className="avatar">P</span>
            <span>Meu espaço</span>
            <button className="icon-button" onClick={logout} aria-label="Sair">
              <Icon name="logout" />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-menu"
              aria-label="Abrir menu"
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              <Icon name="menu" />
            </button>
            <span>Meu espaço</span>
            <span className="crumb-separator">/</span>
            <strong>{NAV.find((n) => n.id === view)?.label}</strong>
          </div>
          <div className="topbar-right">
            <button
              className="icon-button"
              onClick={() => refresh()}
              disabled={refreshing}
              aria-label="Atualizar dados"
            >
              <Icon name="refresh" className={refreshing ? "spin" : ""} />
            </button>
            <span className="environment">
              <span />
              {data?.integrations.preview_mode
                ? "Prévia isolada"
                : "Ambiente local"}
            </span>
          </div>
        </header>
        <main id="main" className="main-content">
          <div className="page-heading">
            <div>
              <h1>
                {view === "overview"
                  ? "Sua próxima oportunidade"
                  : view === "vagas"
                    ? "Encontre seu próximo passo"
                    : view === "curriculo"
                      ? "Seu currículo, preservado"
                      : view === "candidaturas"
                        ? "Cada candidatura, uma decisão"
                        : view === "atividade"
                          ? "Seu fluxo, passo a passo"
                          : view === "busca"
                            ? "Sua busca, do seu jeito"
                            : "Suas integrações"}
              </h1>
              <p>
                {view === "overview"
                  ? "Acompanhe vagas, revise seu currículo e mantenha o controle."
                  : view === "vagas"
                    ? "Revise a aderência e entenda os critérios de cada oportunidade."
                    : view === "curriculo"
                      ? "O mestre é imutável. Cada adaptação precisa passar pelas validações."
                      : view === "candidaturas"
                        ? "Acompanhe os pacotes preparados para sua revisão individual."
                        : view === "atividade"
                          ? "Consulte o histórico dos passos registrados no seu espaço."
                          : view === "busca"
                            ? "Defina fontes, cargos e mercados antes de procurar oportunidades."
                            : "Veja o que está disponível no seu ambiente local."}
              </p>
            </div>
            {view === "overview" || view === "vagas" ? (
              <button
                className="button primary demo-button"
                onClick={demo}
                disabled={
                  busy ||
                  !data ||
                  !["fixture", "live"].includes(
                    data.integrations.discovery_mode,
                  )
                }
              >
                <Icon
                  name={busy ? "refresh" : "play"}
                  className={busy ? "spin" : ""}
                />
                {busy
                  ? "Buscando…"
                  : data?.integrations.discovery_mode === "live"
                    ? "Buscar vagas reais"
                    : "Executar demonstração"}
              </button>
            ) : null}
          </div>
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button className="text-button" onClick={() => refresh()}>
                Tentar novamente
              </button>
            </div>
          ) : null}
          {!data ? (
            <Loading />
          ) : (
            <>
              {view === "overview" ? (
                <>
                  <section className="stats" aria-label="Resumo do espaço">
                    {[
                      { value: data.stats.jobs, label: "Vagas encontradas" },
                      { value: data.stats.eligible, label: "Elegível" },
                      { value: data.stats.applications, label: "Candidaturas" },
                      { value: data.stats.templates, label: "CV mestre" },
                    ].map((stat) => (
                      <div key={stat.label}>
                        <strong>{stat.value}</strong>
                        <span>{stat.label}</span>
                      </div>
                    ))}
                  </section>
                  <Jobs jobs={data.jobs} onSelect={setJob} />
                  <div className="overview-bottom">
                    <ResumeCard
                      template={template}
                      renderEnabled={data.integrations.render_enabled}
                    />
                    <Activity events={data.activity} compact />
                  </div>
                </>
              ) : view === "vagas" ? (
                <Jobs jobs={data.jobs} onSelect={setJob} />
              ) : view === "busca" ? (
                <SearchSettings csrf={auth.csrf_token} />
              ) : view === "curriculo" ? (
                <Curriculum
                  data={data}
                  csrf={auth.csrf_token}
                  onRefresh={() => refresh()}
                  onMessage={setToast}
                />
              ) : view === "atividade" ? (
                <Activity events={data.activity} />
              ) : view === "integracoes" ? (
                <Integrations data={data} />
              ) : data.applications.length ? (
                <section className="panel">
                  <h2>Candidaturas registradas</h2>
                  {data.applications.map((a) => (
                    <div key={a.id} className="application-row">
                      <strong>
                        {data.jobs.find((j) => j.id === a.job_id)?.title ||
                          "Oportunidade registrada"}
                      </strong>
                      <span>{a.recipient || "Contato não definido"}</span>
                      <span className="badge neutral">
                        {(
                          {
                            ready_for_review: "Em revisão",
                            approved: "Aprovada",
                            sent: "Enviada",
                            rejected: "Rejeitada",
                            discovered: "Registrada",
                          } as Record<string, string>
                        )[a.status] || "Em acompanhamento"}
                      </span>
                    </div>
                  ))}
                </section>
              ) : (
                <EmptyApplications />
              )}
              <footer className="page-footer">
                {data.integrations.preview_mode ? (
                  <p>
                    Prévia isolada: as ações desta tela não alteram os
                    containers atuais.
                  </p>
                ) : null}
                Você decide cada candidatura. Nenhum e-mail é enviado
                automaticamente.
              </footer>
            </>
          )}
        </main>
      </div>
      <JobDialog job={job} onClose={() => setJob(null)} />
      {toast ? (
        <div className="toast" role="status">
          <Icon name="check" />
          <span>{toast}</span>
          <button
            className="icon-button"
            onClick={() => setToast("")}
            aria-label="Fechar aviso"
          >
            <Icon name="close" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
