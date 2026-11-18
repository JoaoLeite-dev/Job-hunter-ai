import type { Job } from "./api";
export type View =
  | "overview"
  | "vagas"
  | "curriculo"
  | "candidaturas"
  | "atividade"
  | "integracoes"
  | "busca";
export const NAV: { id: View; label: string; icon: string }[] = [
  { id: "overview", label: "Visão geral", icon: "home" },
  { id: "vagas", label: "Vagas", icon: "search" },
  { id: "busca", label: "Configurar busca", icon: "compass" },
  { id: "curriculo", label: "Currículo", icon: "file" },
  { id: "candidaturas", label: "Candidaturas", icon: "check" },
  { id: "atividade", label: "Atividade", icon: "pulse" },
  { id: "integracoes", label: "Integrações", icon: "connect" },
];
const ICONS: Record<string, string> = {
  compass: "M12 2v20M2 12h20M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  home: "m3 10 9-8 9 8M5 9v12h5v-7h4v7h5V9",
  search: "m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  file: "M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h7M8 16h7",
  check: "M9 3h6l1 2h4v17H4V5h4l1-2Zm-1 11 3 3 6-7",
  pulse: "M2 13h5l3-10 4 19 3-9h5",
  connect:
    "m7 7 10 5-10 5M7 7a3 3 0 1 1 0-.1M20 12a3 3 0 1 1 0-.1M7 17a3 3 0 1 1 0-.1",
  lock: "M6 10h12v11H6V10Zm3 0V6a3 3 0 0 1 6 0v4M12 14v3",
  chevron: "m9 5 7 7-7 7",
  play: "m7 3 14 9-14 9V3Z",
  refresh:
    "M20 7v5h-5M4 17v-5h5M19 11a7 7 0 0 0-12-6L4 8M5 13a7 7 0 0 0 12 6l3-3",
  logout: "M9 3H3v18h6M8 12h14m-5-5 5 5-5 5",
  close: "m6 6 12 12M6 18 18 6",
  menu: "M3 6h18M3 12h18M3 18h18",
  shield: "m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6l9-4Zm-4 10 3 3 5-6",
  arrow: "M4 12h16m-6-6 6 6-6 6",
};
export function Icon({
  name,
  className = "",
}: {
  name: string;
  className?: string;
}) {
  return (
    <svg
      className={`icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICONS[name] || ICONS.file} />
    </svg>
  );
}
export function Brand() {
  return (
    <a className="brand" href="#overview">
      <Icon name="compass" />
      <span>Job Hunter AI</span>
    </a>
  );
}
export function currentView(): View {
  const raw = location.hash.slice(1);
  return NAV.some((n) => n.id === raw) ? (raw as View) : "overview";
}
export function time(value: string | null) {
  if (!value) return "Ainda não verificada";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Não informado";
  const options = { timeZone: "America/Sao_Paulo" };
  const day = new Intl.DateTimeFormat("pt-BR", options).format(date);
  const today = new Intl.DateTimeFormat("pt-BR", options).format(new Date());
  return `${day === today ? "Hoje" : day}, ${new Intl.DateTimeFormat("pt-BR", { ...options, hour: "2-digit", minute: "2-digit" }).format(date)}`;
}
const GATES: Record<string, { label: string; tone: string }> = {
  eligible: { label: "Elegível", tone: "green" },
  blocked: { label: "Restrita", tone: "red" },
  needs_review: { label: "Revisão", tone: "amber" },
};
export function Gate({ status }: { status: string }) {
  const gate = GATES[status] || GATES.needs_review;
  return <span className={`badge ${gate.tone}`}>{gate.label}</span>;
}
export function modality(job: Job) {
  return `${job.remote === true ? "Remoto" : job.remote === false ? "Presencial" : "A confirmar"} · ${job.countries.length ? job.countries.map((c) => (({ BR: "Brasil", US: "EUA", WORLDWIDE: "Global" }) as Record<string, string>)[c] || c).join(", ") : "A confirmar"}`;
}
export function Score({ value }: { value: number | null }) {
  return (
    <div className="score">
      <span>{value === null ? "Não avaliada" : `${value} / 100`}</span>
      {value !== null ? (
        <progress
          value={value}
          max={100}
          aria-label={`Aderência ${value} de 100`}
        />
      ) : null}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <Icon name="refresh" className="spin" />
      <span>Carregando seu espaço…</span>
    </div>
  );
}
