export interface Account {
  id: number;
  name: string;
  role: "owner" | "editor" | "viewer";
}

export interface DomainSummary {
  id: number;
  domain_key: string;
  base_url: string;
  gsc_site_url: string;
  keyword_threshold: number;
}

export interface DomainDetail extends DomainSummary {
  wp_base_url: string | null;
  has_wp_credentials: boolean;
  has_own_anthropic_key: boolean;
  prompt_versions: Record<string, number>;
}

export interface RankRow {
  metric_date: string;
  keyword: string;
  url: string;
  post_id: number | null;
  gsc_average_position: number | null;
  serp_rank: number | null;
  clicks: number;
  impressions: number;
  ctr: number;
  search_volume: number | null;
}

export interface Opportunity {
  score_date: string;
  keyword: string;
  url: string;
  post_id: number | null;
  score: number | string;
  component_breakdown_json: Record<string, unknown>;
}

export interface Alert {
  detected_date: string;
  keyword: string;
  url: string;
  alert_type: string;
  severity: string;
  from_position: number | null;
  to_position: number | null;
}

export interface Article {
  id: number;
  status: "draft" | "published" | "failed";
  title: string | null;
  slug: string | null;
  wp_post_id: number | null;
  target_keyword: string | null;
  target_search_volume: number | null;
  eyecatch_url: string | null;
  created_at: string | null;
  published_at: string | null;
}

export interface ArticleDetail extends Article {
  domain_id: number;
  updated_at: string | null;
  body_html: string | null;
  meta_description: string | null;
  outline: string[];
  warnings: string[];
  wp_link: string | null;
  faked: boolean | null;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  domain_id: number | null;
  params?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  llm_cost_usd: number;
  created_at: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface JobRunResult {
  job_id: string;
  status: Job["status"];
  result: Record<string, unknown> | null;
  error: string | null;
  llm_cost_usd: number;
}

export interface UsageLlm {
  period: string;
  spent_usd: number;
  budget_usd: number | null;
  budget_action: string | null;
  remaining_usd: number | null;
  by_model: Record<string, number>;
}

export type ActionHint = "ctr" | "rewrite" | "weak" | "review";

export const HINT_LABEL: Record<ActionHint, string> = {
  ctr: "上位。タイトル・説明文の見直しでCTR改善",
  rewrite: "あと一歩。本文リライトで上位化を狙える",
  weak: "内容が弱い。大幅改稿 or 別記事に分割",
  review: "要確認",
};

export interface Recommendations {
  domain_id: number;
  keyword_threshold: number;
  note: string;
  improvement_candidates: {
    keyword: string;
    score: number | string;
    url: string;
    post_id: number | null;
    position: number | null;
    impressions: number | null;
    ctr: number | null;
    action_hint: ActionHint;
  }[];
  declining: {
    keyword: string;
    url: string;
    detected_date: string;
    severity: string;
    from_position: number | null;
    to_position: number | null;
  }[];
}

export interface PromptComponent {
  version: number;
  body: string;
  edited_by: number | null;
}

export interface TopicCandidate {
  keyword: string;
  avg_monthly_searches: number | null;
  competition_level: string | null;
  competition_index: number | null;
}

export interface TopicIdeas {
  domain_id: number;
  seeds_used: string[];
  threshold: number;
  ideas_returned: number;
  covered_keywords: number;
  wp_posts_checked: number;
  own_drafts_checked: number;
  cannibalization_excluded: number;
  single_word_excluded: number;
  candidates: TopicCandidate[];
  recommended: TopicCandidate | null;
  recommended_top: TopicCandidate[];
}

export const PROMPT_COMPONENTS = [
  "system_prompt",
  "article_structure",
  "product_block_spec",
  "internal_link_policy",
  "title_format",
  "vc_auto_ads_defaults",
  "eyecatch_style",
  "keyword_threshold",
] as const;

export type PromptComponentName = (typeof PROMPT_COMPONENTS)[number];

export const COMPONENT_LABELS: Record<string, string> = {
  system_prompt: "システムプロンプト",
  article_structure: "記事構成",
  product_block_spec: "商品ブロック",
  internal_link_policy: "内部リンク方針",
  title_format: "タイトル形式",
  vc_auto_ads_defaults: "vc_auto_ads 既定値 (JSON)",
  eyecatch_style: "アイキャッチ設定 (JSON)",
  keyword_threshold: "月間検索数の下限",
};
