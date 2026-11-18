export type BrowserSession = { authenticated: boolean; csrf_token: string };
export type Job = {
  id: string;
  company: string;
  title: string;
  description: string;
  url: string;
  countries: string[];
  remote: boolean | null;
  status: string;
  is_demo: boolean;
  source_name: string;
  source_location: string;
  market: "brazil" | "international" | "unknown";
  score_notice: string;
  score: number | null;
  discovered_at: string;
  published_at: string;
  verified_at: string | null;
  match_profile: string;
  eligibility: { status: string; reason: string };
  match: null | {
    requirements: {
      requirement: string;
      status: string;
      explanation: string;
    }[];
  };
};
export type Template = {
  id: string;
  version: number;
  profile_name: string;
  facts_count: number;
  authorized_count: number;
  is_demo: boolean;
  protected: boolean;
  fields: { id: string; section: string; text: string }[];
};
export type ActivityItem = {
  id: string;
  label: string;
  detail: string;
  created_at: string;
  type: string;
};
export type Variant = {
  id: string;
  job_id: string;
  template_id: string;
  state: string;
  pdf_available: boolean;
  validation: Record<string, { status?: string; code?: string }>;
};
export type Dashboard = {
  publication_policy: { max_age_days: number; hidden: number };
  updated_at: string;
  stats: {
    jobs: number;
    eligible: number;
    applications: number;
    templates: number;
  };
  jobs: Job[];
  templates: Template[];
  variants: Variant[];
  activity: ActivityItem[];
  applications: {
    id: string;
    job_id: string;
    status: string;
    recipient: string | null;
  }[];
  integrations: {
    discovery_mode: string;
    sheets_enabled: boolean;
    render_enabled: boolean;
    email_enabled: boolean;
    ai_enabled: boolean;
    preview_mode?: boolean;
    baseline_preview_only?: boolean;
    snapshot_at?: string;
  };
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
  csrf?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(response.status, data.error || "request_failed");
  return data as T;
}
