import type {
  Account,
  Alert,
  Article,
  DomainDetail,
  DomainSummary,
  Job,
  JobRunResult,
  Opportunity,
  PromptComponent,
  RankRow,
  Recommendations,
  TopicIdeas,
  UsageLlm,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
  "https://article-ops-console.onrender.com";

const ACCOUNT_KEY = "aoc.accountId";
const USER_ID = "1"; // auth not built yet

export function getAccountId(): number {
  if (typeof window === "undefined") return 1;
  try {
    return Number(window.localStorage.getItem(ACCOUNT_KEY)) || 1;
  } catch {
    return 1;
  }
}

export function setAccountId(id: number) {
  try {
    window.localStorage.setItem(ACCOUNT_KEY, String(id));
  } catch {
    /* ignore */
  }
}

async function req<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      "X-Account-Id": String(getAccountId()),
      "X-User-Id": USER_ID,
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(rest.headers || {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const b = await res.json();
      if (b?.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export const api = {
  base: BASE,
  health: () => req<{ status: string; db: boolean }>("/healthz"),

  accounts: () => req<Account[]>("/api/accounts"),

  domains: () => req<DomainSummary[]>("/api/domains"),
  domain: (id: number) => req<DomainDetail>(`/api/domains/${id}`),
  createDomain: (body: {
    domain_key: string;
    base_url: string;
    gsc_site_url: string;
    keyword_threshold?: number;
  }) => req<{ id: number; domain_key: string }>("/api/domains", { method: "POST", json: body }),

  rankHistory: (id: number, days = 90) =>
    req<RankRow[]>(`/api/domains/${id}/rank-history?days=${days}`),
  opportunities: (id: number, limit = 20) =>
    req<Opportunity[]>(`/api/domains/${id}/opportunities?limit=${limit}`),
  alerts: (id: number, days = 30) => req<Alert[]>(`/api/domains/${id}/alerts?days=${days}`),
  articles: (id: number) => req<Article[]>(`/api/domains/${id}/articles`),
  recommendations: (id: number) =>
    req<Recommendations>(`/api/domains/${id}/recommendations`),
  topicIdeas: (
    id: number,
    body: { seeds?: string[]; page_url?: string; limit?: number } = {},
  ) => req<TopicIdeas>(`/api/domains/${id}/topic-ideas`, { method: "POST", json: body }),

  prompts: (id: number) => req<Record<string, PromptComponent>>(`/api/domains/${id}/prompts`),
  promptHistory: (id: number, component: string) =>
    req<{ version: number; body: string; edited_by: number | null; created_at: string }[]>(
      `/api/domains/${id}/prompts/${component}/history`,
    ),
  savePrompt: (id: number, component: string, body: string) =>
    req<{ component: string; version: number }>(`/api/domains/${id}/prompts/${component}`, {
      method: "PUT",
      json: { body },
    }),

  jobs: (limit = 50) => req<Job[]>(`/api/jobs?limit=${limit}`),
  job: (jobId: string) => req<Job>(`/api/jobs/${jobId}`),
  runJob: (body: { kind: string; domain_id?: number; params?: Record<string, unknown> }) =>
    req<JobRunResult>("/api/jobs", { method: "POST", json: body }),

  publish: (articleId: number, status: "publish" | "draft" = "publish") =>
    req<{
      article_id: number;
      wp_post_id: number | null;
      link: string | null;
      status: string;
      warnings: string[];
    }>(`/api/articles/${articleId}/publish`, { method: "POST", json: { status } }),

  usageLlm: () => req<UsageLlm>("/api/usage/llm"),
  usageApi: () =>
    req<{ provider: string; operation: string; calls: number }[]>("/api/usage/api"),

  oauthStatus: () =>
    req<{ connected: boolean; google_email?: string | null; scopes?: string }>(
      "/api/oauth/google/status",
    ),
};
